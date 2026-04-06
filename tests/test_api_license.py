"""
Integration tests for the License API endpoint.
"""

import os
import sys
import time
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DEBUG"] = "false"
os.environ["API_REQUIRE_AUTH"] = "false"

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from httpx import AsyncClient, ASGITransport
from routers.system_api import system_app_router, system_v1_router
from license import Edition, LicenseInfo, set_current_license, reset_license, COMMUNITY_LICENSE
from tests.test_license import _make_key, TEST_SECRET

# Construct a minimal app for testing these specific routes
# This avoids the full api.py startup background thread and migrations
app = FastAPI()

# Add exception handlers for parity with production api.py
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    detail = exc.detail
    error_code = "GENERIC_HTTP_ERROR"
    message = str(detail)
    details = None
    if isinstance(detail, dict):
        error_code = detail.get("error_code", error_code)
        message = detail.get("message", message)
        details = detail.get("details")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": error_code, "message": message, "details": details}
    )

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    import logging
    logging.getLogger(__name__).error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "SYS_1001",
            "message": "An unexpected internal server error occurred.",
            "details": {"exception": str(exc)}
        }
    )

app.include_router(system_app_router)
app.include_router(system_v1_router, prefix="/api/v1")

@pytest.fixture
async def client():
    """Yield an async client with symmetric license reset."""
    reset_license()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    reset_license()

@pytest.mark.asyncio
async def test_get_license_community(client):
    """Verify that the API returns the community edition by default."""
    set_current_license(COMMUNITY_LICENSE)
    response = await client.get("/license")
    assert response.status_code == 200
    data = response.json()
    assert data["edition"] == "community"
    assert data["org_name"] == ""
    assert data["seats"] == 0
    assert data["expired"] is False
    assert data["days_until_expiry"] is None
    assert "warning" not in data

@pytest.mark.asyncio
async def test_get_license_team(client):
    """Verify that the API returns team edition details when loaded."""
    info = LicenseInfo(
        Edition.TEAM,
        org_name="Team Org",
        seats=5,
        expiry_timestamp=time.time() + 90 * 86400 + 60,
        key_id="team-key"
    )
    set_current_license(info)
    
    response = await client.get("/license")
    assert response.status_code == 200
    data = response.json()
    assert data["edition"] == "team"
    assert data["org_name"] == "Team Org"
    assert data["seats"] == 5
    assert 89 <= data["days_until_expiry"] <= 90
    assert data["key_id"] == "team-key"
    assert data["expired"] is False

@pytest.mark.asyncio
async def test_get_license_organization(client):
    """Verify that the API returns organization edition details when loaded."""
    info = LicenseInfo(
        Edition.ORGANIZATION,
        org_name="Global Corp",
        seats=100,
        expiry_timestamp=time.time() + 365 * 86400 + 60,
        key_id="org-key"
    )
    set_current_license(info)
    
    response = await client.get("/license")
    assert response.status_code == 200
    data = response.json()
    assert data["edition"] == "organization"
    assert data["org_name"] == "Global Corp"
    assert data["seats"] == 100
    assert 364 <= data["days_until_expiry"] <= 365
    assert data["key_id"] == "org-key"
    assert data["expired"] is False

@pytest.mark.asyncio
async def test_get_license_warning(client):
    """Verify that warnings are included in the API response."""
    info = LicenseInfo(
        Edition.TEAM,
        warning="License expiring soon"
    )
    set_current_license(info)
    
    response = await client.get("/license")
    assert response.status_code == 200
    data = response.json()
    assert data["warning"] == "License expiring soon"

@pytest.mark.asyncio
async def test_install_server_license_endpoint_stores_key(client):
    from license import AggregatedLicense, Edition
    agg = AggregatedLicense(edition=Edition.TEAM, seats=5, active_key_ids=["k1"])
    with patch("routers.system_api.is_loopback_request", return_value=True), \
         patch("license.resolve_verification_context", return_value=(TEST_SECRET, ["HS256"])), \
         patch("license.validate_license_key") as mock_validate, \
         patch("server_settings_store.add_server_license_key") as mock_add, \
         patch("license.load_all_licenses", return_value=agg), \
         patch("license.reset_license"), \
         patch("license.set_current_license"), \
         patch("server_settings_store.get_server_license_keys", return_value=["k1"]):
        key = _make_key(secret=TEST_SECRET)
        response = await client.post("/api/v1/license/install", json={"license_key": key})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "stored"
    assert data["action"] == "add"
    mock_validate.assert_called_once_with(key, TEST_SECRET, ["HS256"])
    mock_add.assert_called_once_with(key)

@pytest.mark.asyncio
async def test_install_server_license_endpoint_rejects_non_loopback(client):
    with patch("routers.system_api.is_loopback_request", return_value=False), \
         patch("license.resolve_verification_context", return_value=(TEST_SECRET, ["HS256"])), \
         patch("license.validate_license_key") as mock_validate, \
         patch("server_settings_store.set_server_license_key") as mock_store:
        key = _make_key(secret=TEST_SECRET)
        response = await client.post("/api/v1/license/install", json={"license_key": key})

    assert response.status_code == 403
    detail = response.json()
    assert detail["error_code"] == "AUTH_2002"
    assert detail["details"]["loopback_required"] is True
    mock_validate.assert_not_called()
    mock_store.assert_not_called()
