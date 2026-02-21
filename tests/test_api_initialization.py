import pytest
import time
from fastapi.testclient import TestClient
from api import app
import services

def test_health_during_initialization():
    """Test that /health returns 'initializing' when init_complete is False."""
    # Reset state
    services.init_complete = False
    services.init_error = None
    
    with TestClient(app) as client:
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
