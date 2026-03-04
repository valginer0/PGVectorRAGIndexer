import pytest
import asyncio
import builtins
import sys
from unittest.mock import patch, MagicMock

from routers.system_api import health_check, _get_system_metrics


def _assert_system_metrics_schema(system_metrics: dict):
    """Shared assertions for the canonical system metrics schema."""
    assert "uptime_seconds" in system_metrics
    assert isinstance(system_metrics["uptime_seconds"], (int, float))

    assert "cpu_load_1m" in system_metrics
    assert system_metrics["cpu_load_1m"] is None or isinstance(system_metrics["cpu_load_1m"], (int, float))

    assert "memory_rss_bytes" in system_metrics
    assert system_metrics["memory_rss_bytes"] is None or isinstance(system_metrics["memory_rss_bytes"], (int, float))


@pytest.mark.asyncio
async def test_health_system_metrics_schema():
    """Verify /health returns safe canonical system metrics via the initializing path.

    Uses init_complete=False to avoid any database or embedding service
    dependencies that could block.
    """
    with patch("services.init_complete", False), \
         patch("services.init_error", None):
        response = await health_check()

    assert response.status == "initializing"
    assert response.system is not None
    _assert_system_metrics_schema(response.system)


@pytest.mark.asyncio
async def test_health_system_metrics_healthy_path():
    """Verify /health returns system metrics in the fully healthy path."""
    mock_db_manager = MagicMock()
    mock_embedding = MagicMock()
    mock_embedding.get_model_info.return_value = {"status": "mocked"}

    async def fake_to_thread(func, *args, **kwargs):
        return {"status": "mocked"}

    with patch("services.init_complete", True), \
         patch("services.init_error", None), \
         patch("routers.system_api.get_db_manager", return_value=mock_db_manager), \
         patch("routers.system_api.get_embedding_service", return_value=mock_embedding), \
         patch("routers.system_api.asyncio.to_thread", side_effect=fake_to_thread):
        response = await health_check()

    assert response.status == "healthy"
    assert response.system is not None
    _assert_system_metrics_schema(response.system)


def test_health_system_metrics_without_psutil():
    """Verify _get_system_metrics falls back to stdlib when psutil is unavailable."""
    saved = sys.modules.pop("psutil", None)
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError("mocked: psutil not installed")
        return real_import(name, *args, **kwargs)

    try:
        with patch.object(builtins, "__import__", side_effect=mock_import):
            metrics = _get_system_metrics()
    finally:
        if saved is not None:
            sys.modules["psutil"] = saved

    _assert_system_metrics_schema(metrics)
