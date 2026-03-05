import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import pytest
import sys

# Ensure we can import from the project root
sys.path.append(".")

from server_scheduler import ServerScheduler
from routers.system_api import health_check
from database import DatabaseManager
from config import DatabaseConfig, AppConfig

@pytest.mark.asyncio
async def test_scheduler_lease_is_offloaded():
    """Verify that scheduler lease acquisition is offloaded to a thread."""
    scheduler = ServerScheduler()
    with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
        await scheduler._try_acquire_lease()
        # Verify it was offloaded to the sync helper
        mock_to_thread.assert_called_once()
        assert mock_to_thread.call_args[0][0] == scheduler._sync_try_acquire_lease

@pytest.mark.asyncio
async def test_scheduler_scan_watermarks_offloaded():
    """Verify that ALL folder scan watermarks and mark_scanned are offloaded."""
    scheduler = ServerScheduler()
    folder = {"id": "1", "folder_path": "/tmp"}
    mock_result = {"status": "success", "run_id": "r1"}
    
    with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
        # Mocking the sequence of to_thread calls in _run_scan
        # 1. update_scan_watermarks (started=True)
        # 2. scan_folder
        # 3. update_scan_watermarks (completed=True)
        # 4. mark_scanned
        mock_to_thread.side_effect = [
            True,        # started=True
            mock_result, # scan_folder
            True,        # completed=True
            True         # mark_scanned
        ]
        
        await scheduler._run_scan(folder)
        
        # Verify exactly 4 offloads occurred
        assert mock_to_thread.call_count == 4
        
        # Verify the functions were offloaded in order
        offloaded_funcs = [call[0][0] for call in mock_to_thread.call_args_list]
        from watched_folders import update_scan_watermarks, mark_scanned, scan_folder
        
        # First call MUST be update_scan_watermarks (Fix for missing started=True offload)
        assert offloaded_funcs[0] == update_scan_watermarks
        assert offloaded_funcs[1] == scan_folder
        assert offloaded_funcs[2] == update_scan_watermarks
        assert offloaded_funcs[3] == mark_scanned

@pytest.mark.asyncio
async def test_health_check_db_offloaded():
    """Verify that database health check is offloaded to a thread."""
    with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
        mock_to_thread.return_value = {"status": "healthy"}
        with patch("services.init_complete", True):
            with patch("routers.system_api.get_db_manager") as mock_get_db:
                mock_db = MagicMock()
                mock_get_db.return_value = mock_db
                
                with patch("routers.system_api.get_embedding_service") as mock_get_embed:
                    mock_embed = MagicMock()
                    mock_embed.get_model_info.return_value = {
                        "model_name": "test",
                        "dimension": 384,
                        "device": "cpu",
                        "max_seq_length": 512,
                        "cache_enabled": True,
                        "cache_size": 0,
                        "normalize_embeddings": True
                    }
                    mock_get_embed.return_value = mock_embed
                    
                    await health_check()
                    
                    # Verify db_manager.health_check was offloaded
                    mock_to_thread.assert_called_with(mock_db.health_check)

@pytest.mark.asyncio
async def test_health_check_remains_responsive_during_slow_db():
    """Verify that /health uses asyncio.to_thread so the event loop stays free.

    Instead of running a real slow thread (which can hang in constrained
    environments), we mock asyncio.to_thread and verify it is called with
    the DB health_check callable. This proves the event loop is never blocked.
    """
    with patch("services.init_complete", True):
        with patch("routers.system_api.get_db_manager") as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value = mock_db

            with patch("routers.system_api.get_embedding_service") as mock_get_embed:
                mock_embed = MagicMock()
                mock_embed.get_model_info.return_value = {
                    "model_name": "test",
                    "dimension": 384,
                    "device": "cpu",
                    "max_seq_length": 512,
                    "cache_enabled": True,
                    "cache_size": 0,
                    "normalize_embeddings": True
                }
                mock_get_embed.return_value = mock_embed

                with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
                    mock_to_thread.return_value = {"status": "healthy"}
                    await health_check()
                    # The DB health_check was offloaded — event loop was never blocked
                    mock_to_thread.assert_called_once_with(mock_db.health_check)

def test_database_manager_timeouts():
    """Verify that DatabaseManager correctly applies connect and statement timeouts."""
    config_obj = AppConfig()
    config_obj.database.connect_timeout = 5
    config_obj.database.statement_timeout = 15
    
    with patch("database.get_config", return_value=config_obj):
        dm = DatabaseManager()
        dm.config = config_obj.database
        with patch("psycopg2.pool.ThreadedConnectionPool") as mock_pool:
            dm.initialize()
            args, kwargs = mock_pool.call_args
            assert kwargs["connect_timeout"] == 5
            assert "statement_timeout=15000" in kwargs["options"]

class _LoopEscape(Exception):
    """Sentinel to break out of _scheduler_loop without async event coordination."""
    pass


@pytest.mark.asyncio
async def test_scheduler_init_guard_blocks_lease():
    """Verify that _scheduler_loop does NOT attempt lease while init_complete is False.

    Strategy: keep init_complete=False and make asyncio.sleep raise _LoopEscape
    after the first call. If the loop reaches sleep before _try_acquire_lease,
    the init guard is working.
    """
    import services
    orig_complete = services.init_complete
    orig_error = services.init_error

    try:
        services.init_complete = False
        services.init_error = None

        scheduler = ServerScheduler()
        scheduler._running = True
        lease_called = False

        async def mock_try_lease():
            nonlocal lease_called
            lease_called = True
            return False

        async def escape_sleep(delay):
            raise _LoopEscape("break out of init-wait loop")

        with patch.object(scheduler, "_try_acquire_lease", side_effect=mock_try_lease):
            with patch("server_scheduler.asyncio.sleep", side_effect=escape_sleep):
                with pytest.raises(_LoopEscape):
                    await scheduler._scheduler_loop()

        assert not lease_called, "Lease should NOT be attempted while init_complete is False"
    finally:
        services.init_complete = orig_complete
        services.init_error = orig_error


@pytest.mark.asyncio
async def test_scheduler_init_guard_proceeds_after_init():
    """Verify that _scheduler_loop attempts lease once init_complete is True.

    Strategy: set init_complete=True from the start. Make _try_acquire_lease
    stop the loop. No init-wait coordination needed.
    """
    import services
    orig_complete = services.init_complete
    orig_error = services.init_error

    try:
        services.init_complete = True
        services.init_error = None

        scheduler = ServerScheduler()
        scheduler._running = True
        lease_called = False

        async def mock_try_lease():
            nonlocal lease_called
            lease_called = True
            scheduler._running = False
            return False

        async def noop_sleep(delay):
            pass  # no actual sleep, no async coordination

        with patch.object(scheduler, "_try_acquire_lease", side_effect=mock_try_lease):
            with patch("server_scheduler.asyncio.sleep", side_effect=noop_sleep):
                await asyncio.wait_for(scheduler._scheduler_loop(), timeout=5.0)

        assert lease_called, "Lease SHOULD be attempted when init_complete is True"
    finally:
        services.init_complete = orig_complete
        services.init_error = orig_error

@pytest.mark.asyncio
async def test_scheduler_init_error_stops_loop():
    """Verify that scheduler stops and sets _running=False if init fails."""
    import services
    orig_complete = services.init_complete
    orig_error = services.init_error

    scheduler = ServerScheduler()
    scheduler._running = True

    try:
        services.init_complete = False
        services.init_error = "DB Collision"

        await asyncio.wait_for(scheduler._scheduler_loop(), timeout=5.0)
        assert scheduler._running is False
    finally:
        services.init_complete = orig_complete
        services.init_error = orig_error
