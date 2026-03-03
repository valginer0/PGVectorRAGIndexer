import pytest
import time
from fastapi.testclient import TestClient
import services

from unittest.mock import patch
from routers.system_api import system_app_router

@pytest.fixture(scope="function")
def isolated_app():
    """Create a fully isolated, lightweight app instance just for this test."""
    from fastapi import FastAPI
    app = FastAPI(title="Test App")
    app.include_router(system_app_router)
    return app

@patch("server_scheduler.ServerScheduler.is_enabled", return_value=False)
@patch("retention_maintenance.RetentionMaintenanceRunner.is_enabled", return_value=False)
def test_health_during_initialization(mock_retention_enabled, mock_scheduler_enabled, isolated_app):
    """Test that /health returns 'initializing' when init_complete is False."""
    # Reset state
    services.init_complete = False
    services.init_error = None
    
    # Mock _run_startup to ensure background initialization doesn't finish too fast (race condition fix)
    # We patch it in api module where it's used by the background thread
    with patch("api._run_startup"), TestClient(isolated_app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "initializing"
        assert "database" in data
        assert data["database"]["status"] == "initializing"

@patch("api._run_startup")
@patch("server_scheduler.ServerScheduler.is_enabled", return_value=False)
@patch("retention_maintenance.RetentionMaintenanceRunner.is_enabled", return_value=False)
def test_health_after_initialization(mock_retention_enabled, mock_scheduler_enabled, mock_run_startup, isolated_app):
    """Test that /health returns 'healthy' when init_complete is True."""
    # Manually set init_complete to True
    services.init_complete = True
    services.init_error = None
    
    with TestClient(isolated_app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        # Note: If database connection fails it might be 'healthy' but with unhealthy db
        assert data["status"] == "healthy"
