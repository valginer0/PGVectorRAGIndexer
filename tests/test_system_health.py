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
        # Must be "healthy": the endpoint now derives its top-level status from
        # this. The old stub said "mocked" and the test still asserted healthy,
        # because the status was hardcoded — the bug this file now guards.
        return {"status": "healthy"}

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


# ---------------------------------------------------------------------------
# The endpoint must report what the database says, not what we hope
# ---------------------------------------------------------------------------

def _mock_embedding():
    m = MagicMock()
    m.get_model_info.return_value = {"status": "mocked"}
    return m


def _db_returning(db_health):
    """Patch context where db_manager.health_check RETURNS db_health."""
    async def fake_to_thread(func, *args, **kwargs):
        return db_health

    return (
        patch("services.init_complete", True),
        patch("services.init_error", None),
        patch("routers.system_api.get_db_manager", return_value=MagicMock()),
        patch("routers.system_api.get_embedding_service", return_value=_mock_embedding()),
        patch("routers.system_api.asyncio.to_thread", side_effect=fake_to_thread),
    )


@pytest.mark.asyncio
async def test_health_reports_degraded_when_database_is_unhealthy():
    """A broken database must not be announced as healthy.

    db_manager.health_check() REPORTS failure by returning a dict; it does not
    raise. The endpoint used to hardcode status="healthy", so a database with
    no tables at all — which is what the first-run recovery bug produced —
    was reported as healthy to everything that asked.
    """
    unhealthy = {"status": "unhealthy", "error": 'relation "document_chunks" does not exist'}
    patches = _db_returning(unhealthy)
    for p in patches:
        p.start()
    try:
        response = await health_check()
    finally:
        for p in patches:
            p.stop()

    assert response.status == "degraded"
    # The reason has to survive into the payload — it is the only thing telling
    # a user what went wrong.
    assert response.database["status"] == "unhealthy"
    assert "document_chunks" in response.database["error"]


@pytest.mark.asyncio
async def test_health_is_degraded_for_any_non_healthy_database_status():
    """Anything that is not exactly "healthy" is not healthy."""
    for db_status in ("unhealthy", "unknown", "mocked", "", "degraded"):
        patches = _db_returning({"status": db_status})
        for p in patches:
            p.start()
        try:
            response = await health_check()
        finally:
            for p in patches:
                p.stop()
        assert response.status == "degraded", f"db status {db_status!r} was treated as healthy"


@pytest.mark.asyncio
async def test_ready_returns_503_when_database_is_unhealthy():
    """/ready must FAIL, in the HTTP status, so Docker and Compose can act on it.

    /health stays 200 whenever the process can reply — the desktop client reads
    the body to explain the problem. /ready is the machine-readable signal, and
    it did not exist: nothing could distinguish "alive" from "able to work".
    """
    from fastapi import HTTPException
    from routers.system_api import readiness_check

    patches = _db_returning({"status": "unhealthy", "error": "no tables"})
    for p in patches:
        p.start()
    try:
        with pytest.raises(HTTPException) as exc:
            await readiness_check()
    finally:
        for p in patches:
            p.stop()

    assert exc.value.status_code == 503
    assert "no tables" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_ready_returns_503_while_initializing():
    """Still loading the embedding model is not ready.

    This is the state that wasted the best question in the demo walkthrough:
    /health answered 200 with status "initializing" and the caller took it as
    a go-ahead.
    """
    from fastapi import HTTPException
    from routers.system_api import readiness_check

    with patch("services.init_complete", False), patch("services.init_error", None):
        with pytest.raises(HTTPException) as exc:
            await readiness_check()

    assert exc.value.status_code == 503
    assert "initializing" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_ready_returns_200_when_everything_works():
    from routers.system_api import readiness_check

    patches = _db_returning({"status": "healthy"})
    for p in patches:
        p.start()
    try:
        result = await readiness_check()
    finally:
        for p in patches:
            p.stop()

    assert result["status"] == "ready"
