"""
Integration tests for the License API endpoint.
"""

import os
import sys
import time
import pytest
from fastapi.testclient import TestClient

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api import app
from license import Edition, LicenseInfo, set_current_license, reset_license

client = TestClient(app)

def setup_module(module):
    """Reset license state before tests and wait for background init."""
    import services
    reset_license()
    
    # Wait for the background initialization in api.py to finish 
    # to avoid it stomping on our test license state later
    with TestClient(app) as client:
        timeout = 10
        start = time.time()
        while not getattr(services, 'init_complete', False) and time.time() - start < timeout:
            time.sleep(0.1)

def teardown_module(module):
    """Reset license state after tests."""
    reset_license()

def test_get_license_community():
    """Verify that the API returns the community edition by default."""
    reset_license()
    response = client.get("/license")
    assert response.status_code == 200
    data = response.json()
    assert data["edition"] == "community"
    assert data["org_name"] == ""
    assert data["seats"] == 0
    assert data["expired"] is False
    assert data["days_until_expiry"] is None
    assert "warning" not in data

def test_get_license_team():
    """Verify that the API returns team edition details when loaded."""
    info = LicenseInfo(
        Edition.TEAM,
        org_name="Team Org",
        seats=5,
        expiry_timestamp=time.time() + 90 * 86400 + 60,
        key_id="team-key"
    )
    set_current_license(info)
    
    response = client.get("/license")
    assert response.status_code == 200
    data = response.json()
    assert data["edition"] == "team"
    assert data["org_name"] == "Team Org"
    assert data["seats"] == 5
    assert 89 <= data["days_until_expiry"] <= 90
    assert data["key_id"] == "team-key"
    assert data["expired"] is False

def test_get_license_organization():
    """Verify that the API returns organization edition details when loaded."""
    info = LicenseInfo(
        Edition.ORGANIZATION,
        org_name="Global Corp",
        seats=100,
        expiry_timestamp=time.time() + 365 * 86400 + 60,
        key_id="org-key"
    )
    set_current_license(info)
    
    response = client.get("/license")
    assert response.status_code == 200
    data = response.json()
    assert data["edition"] == "organization"
    assert data["org_name"] == "Global Corp"
    assert data["seats"] == 100
    assert 364 <= data["days_until_expiry"] <= 365
    assert data["key_id"] == "org-key"
    assert data["expired"] is False

def test_get_license_warning():
    """Verify that warnings are included in the API response."""
    info = LicenseInfo(
        Edition.TEAM,
        warning="License expiring soon"
    )
    set_current_license(info)
    
    response = client.get("/license")
    assert response.status_code == 200
    data = response.json()
    assert data["warning"] == "License expiring soon"
