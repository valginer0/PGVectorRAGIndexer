import pytest
from unittest.mock import patch, MagicMock
import services

from routers.system_api import health_check


@pytest.mark.asyncio
async def test_health_during_initialization():
    """Test that /health returns 'initializing' when init_complete is False."""
    services.init_complete = False
    services.init_error = None

    try:
        with patch("services.init_complete", False), \
             patch("services.init_error", None):
            response = await health_check()
        assert response.status == "initializing"
        assert response.database == {"status": "initializing"}
    finally:
        services.init_complete = False
        services.init_error = None


@pytest.mark.asyncio
async def test_health_after_initialization():
    """Test that /health returns 'healthy' when init_complete is True."""
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
