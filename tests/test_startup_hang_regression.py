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
    """Verify that /health releases the event loop even if the DB check is slow."""
    import time
    def slow_health():
        time.sleep(0.5) 
        return {"status": "healthy"}

    with patch("services.init_complete", True):
        with patch("routers.system_api.get_db_manager") as mock_get_db:
            mock_db = MagicMock()
            mock_db.health_check = slow_health
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
                
                start_time = asyncio.get_event_loop().time()
                
                async def ping_loop():
                    hits = 0
                    while asyncio.get_event_loop().time() - start_time < 0.3:
                        hits += 1
                        await asyncio.sleep(0.01)
                    return hits

                ping_task = asyncio.create_task(ping_loop())
                health_task = asyncio.create_task(health_check())
                
                results = await asyncio.gather(ping_task, health_task)
                assert results[0] > 10

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

@pytest.mark.asyncio
async def test_scheduler_init_guard_liveness():
    """Verify that scheduler loop correctly polls live 'services' module values deterministically."""
    import services
    import sys
    
    # Ensure module identity
    services_module = sys.modules.get('services')
    assert services_module is not None
    
    # Save original state for isolation
    orig_complete = services_module.init_complete
    orig_error = services_module.init_error
    
    scheduler = ServerScheduler()
    scheduler._running = True
    
    try:
        # Initialize state for test
        services_module.init_complete = False
        services_module.init_error = None
        
        # Track lease calls
        lease_called = asyncio.Event()
        async def mock_try_lease():
            # Set running to False immediately to prevent the loop from spinning
            # while the test evaluates the assertion.
            scheduler._running = False
            lease_called.set()
            return False

        # Track sleep calls using events for perfect synchronization
        original_sleep = asyncio.sleep
        init_wait_reached = asyncio.Event()
        proceed_with_init_poll = asyncio.Event()

        async def deterministic_sleep(delay):
            if not services_module.init_complete:
                init_wait_reached.set()
                await proceed_with_init_poll.wait()
                proceed_with_init_poll.clear() 
            else:
                await original_sleep(0) # Yield control safely
                return

        with patch.object(scheduler, "_try_acquire_lease", side_effect=mock_try_lease):
            with patch("server_scheduler.asyncio.sleep", side_effect=deterministic_sleep):
                # Start loop
                loop_task = asyncio.create_task(scheduler._scheduler_loop())
                
                # 1. Wait until the loop definitely reaches the init-wait sleep
                await asyncio.wait_for(init_wait_reached.wait(), timeout=1.0)
                
                # verify it hasn't called lease yet
                assert not lease_called.is_set()
                
                # 2. Flip the switch and allow the sleep to resolve
                services_module.init_complete = True
                proceed_with_init_poll.set()
                
                # 3. Wait for the lease call event
                await asyncio.wait_for(lease_called.wait(), timeout=1.0)
                
                # Check if task crashed
                if loop_task.done() and loop_task.exception():
                    raise loop_task.exception()
                
                assert lease_called.is_set(), "Scheduler loop did not call lease after init_complete"
                
                # Cleanup task
                if not loop_task.done():
                    loop_task.cancel()
                    try:
                        await loop_task
                    except asyncio.CancelledError:
                        pass
    finally:
        # Restore global state for other tests
        services_module.init_complete = orig_complete
        services_module.init_error = orig_error

@pytest.mark.asyncio
async def test_scheduler_init_error_stops_loop():
    """Verify that scheduler stops and sets _running=False if init fails."""
    import services
    scheduler = ServerScheduler()
    scheduler._running = True
    
    services.init_complete = False
    services.init_error = "DB Collision"
    
    await scheduler._scheduler_loop()
    assert scheduler._running is False
