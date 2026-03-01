import pytest
import time
from fastapi.testclient import TestClient
from api import app
import services

from unittest.mock import patch

def test_health_during_initialization():
    """Test that /health returns 'initializing' when init_complete is False."""
    # Reset state
    services.init_complete = False
    services.init_error = None
    
    # Mock _run_startup to ensure background initialization doesn't finish too fast (race condition fix)
    # We patch it in api module where it's used by the background thread
    with patch("api._run_startup"), TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "initializing"
        assert "database" in data
        assert data["database"]["status"] == "initializing"

def test_health_after_initialization():
    """Test that /health returns 'healthy' when init_complete is True."""
    # Manually set init_complete to True
    services.init_complete = True
    services.init_error = None
    
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        # Note: If database connection fails it might be 'healthy' but with unhealthy db
        assert data["status"] == "healthy"
