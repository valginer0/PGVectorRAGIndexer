"""
Tests for #16 Enterprise Foundations Phase 2 — SAML/SSO.

Tests cover:
- Migration 011: saml_sessions table structure
- saml_auth.py: configuration, session helpers, auto-provisioning, request prep
- API endpoint registration
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = Path(__file__).parent.parent


# ===========================================================================
# Test: Migration 011
# ===========================================================================


class TestMigration011:
    def test_migration_file_exists(self):
        assert (PROJECT_ROOT / "alembic" / "versions" / "011_saml_sessions.py").exists()

    def test_migration_has_correct_revision(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration_011",
            str(PROJECT_ROOT / "alembic" / "versions" / "011_saml_sessions.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.revision == "011"
        assert mod.down_revision == "010"

    def test_migration_has_upgrade_and_downgrade(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration_011",
            str(PROJECT_ROOT / "alembic" / "versions" / "011_saml_sessions.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(getattr(mod, "upgrade", None))
        assert callable(getattr(mod, "downgrade", None))


# ===========================================================================
# Test: saml_auth.py configuration
# ===========================================================================


class TestSamlConfig:
    def test_saml_disabled_by_default(self):
        from saml_auth import SAML_ENABLED
        # Unless SAML_ENABLED env var is set, should be False
        if os.environ.get("SAML_ENABLED", "").lower() not in ("true", "1", "yes"):
            assert SAML_ENABLED is False

    def test_saml_available_checks_both(self):
        from saml_auth import is_saml_available, SAML_ENABLED, _saml_available
        # is_saml_available requires BOTH enabled AND library installed
        result = is_saml_available()
        assert result == (SAML_ENABLED and _saml_available)

    def test_session_lifetime_default(self):
        from saml_auth import SAML_SESSION_LIFETIME_HOURS
        assert SAML_SESSION_LIFETIME_HOURS == int(
            os.environ.get("SAML_SESSION_LIFETIME_HOURS", "8")
        )

    def test_auto_provision_default(self):
        from saml_auth import SAML_AUTO_PROVISION
        if "SAML_AUTO_PROVISION" not in os.environ:
            assert SAML_AUTO_PROVISION is True

    def test_default_role(self):
        from saml_auth import SAML_DEFAULT_ROLE
        if "SAML_DEFAULT_ROLE" not in os.environ:
            assert SAML_DEFAULT_ROLE == "user"


# ===========================================================================
# Test: saml_auth.py settings builder
# ===========================================================================


class TestSamlSettingsBuilder:
    def test_build_saml_settings_structure(self):
        from saml_auth import _build_saml_settings
        settings = _build_saml_settings()
        assert "sp" in settings
        assert "idp" in settings
        assert "security" in settings
        assert "strict" in settings
        assert settings["strict"] is True

    def test_sp_settings_have_entity_id(self):
        from saml_auth import _build_saml_settings, SAML_SP_ENTITY_ID
        settings = _build_saml_settings()
        assert settings["sp"]["entityId"] == SAML_SP_ENTITY_ID

    def test_idp_settings_have_entity_id(self):
        from saml_auth import _build_saml_settings, SAML_IDP_ENTITY_ID
        settings = _build_saml_settings()
        assert settings["idp"]["entityId"] == SAML_IDP_ENTITY_ID

    def test_security_wants_signed_assertions(self):
        from saml_auth import _build_saml_settings
        settings = _build_saml_settings()
        assert settings["security"]["wantAssertionsSigned"] is True
        assert settings["security"]["wantMessagesSigned"] is True


# ===========================================================================
# Test: prepare_request_from_fastapi
# ===========================================================================


class TestPrepareRequest:
    def test_basic_request_conversion(self):
        from saml_auth import prepare_request_from_fastapi

        mock_request = MagicMock()
        mock_url = MagicMock()
        mock_url.hostname = "example.com"
        mock_url.path = "/api/v1/saml/acs"
        mock_url.scheme = "https"
        mock_url.port = 443
        mock_request.url = mock_url
        mock_request.query_params = {}

        result = prepare_request_from_fastapi(mock_request)
        assert result["http_host"] == "example.com"
        assert result["script_name"] == "/api/v1/saml/acs"
        assert result["https"] == "on"
        assert result["server_port"] == "443"

    def test_http_request(self):
        from saml_auth import prepare_request_from_fastapi

        mock_request = MagicMock()
        mock_url = MagicMock()
        mock_url.hostname = "localhost"
        mock_url.path = "/api/v1/saml/login"
        mock_url.scheme = "http"
        mock_url.port = 8000
        mock_request.url = mock_url
        mock_request.query_params = {"return_to": "/dashboard"}

        result = prepare_request_from_fastapi(mock_request)
        assert result["https"] == "off"
        assert result["server_port"] == "8000"
        assert result["get_data"] == {"return_to": "/dashboard"}


# ===========================================================================
# Test: session row conversion
# ===========================================================================


class TestSessionRowToDict:
    def test_basic_conversion(self):
        from saml_auth import _session_row_to_dict
        now = datetime.now(timezone.utc)
        row = ("s1", "u1", "idx1", "user@example.com", "email", "https://idp.example.com", now, now, True)
        d = _session_row_to_dict(row)
        assert d["id"] == "s1"
        assert d["user_id"] == "u1"
        assert d["name_id"] == "user@example.com"
        assert d["is_active"] is True
        assert isinstance(d["created_at"], str)
        assert isinstance(d["expires_at"], str)


# ===========================================================================
# Test: session DB resilience
# ===========================================================================


class TestSessionDBResilience:
    @patch("saml_auth._get_db_connection", side_effect=Exception("DB down"))
    def test_create_session_returns_none(self, _mock):
        from saml_auth import create_session
        assert create_session(user_id="u1", name_id="x@y.com") is None

    @patch("saml_auth._get_db_connection", side_effect=Exception("DB down"))
    def test_get_session_returns_none(self, _mock):
        from saml_auth import get_session
        assert get_session("s1") is None

    @patch("saml_auth._get_db_connection", side_effect=Exception("DB down"))
    def test_expire_session_returns_false(self, _mock):
        from saml_auth import expire_session
        assert expire_session("s1") is False

    @patch("saml_auth._get_db_connection", side_effect=Exception("DB down"))
    def test_expire_user_sessions_returns_zero(self, _mock):
        from saml_auth import expire_user_sessions
        assert expire_user_sessions("u1") == 0

    @patch("saml_auth._get_db_connection", side_effect=Exception("DB down"))
    def test_cleanup_expired_sessions_returns_zero(self, _mock):
        from saml_auth import cleanup_expired_sessions
        assert cleanup_expired_sessions() == 0


# ===========================================================================
# Test: auto-provisioning logic
# ===========================================================================


class TestAutoProvisioning:
    @patch("saml_auth.SAML_AUTO_PROVISION", False)
    @patch("users.get_user_by_email", return_value=None)
    def test_no_provision_when_disabled(self, _mock_get):
        from saml_auth import provision_or_get_user
        result = provision_or_get_user("new@example.com")
        assert result is None

    @patch("users.get_user_by_email", return_value={"id": "u1", "email": "existing@example.com", "role": "user"})
    @patch("users.record_login")
    def test_returns_existing_user(self, _mock_login, _mock_get):
        from saml_auth import provision_or_get_user
        result = provision_or_get_user("existing@example.com")
        assert result is not None
        assert result["id"] == "u1"

    @patch("saml_auth.SAML_AUTO_PROVISION", True)
    @patch("users.get_user_by_email", return_value=None)
    @patch("users.create_user", return_value={"id": "u2", "email": "new@example.com", "role": "user"})
    @patch("users.record_login")
    def test_provisions_new_user(self, _mock_login, _mock_create, _mock_get):
        from saml_auth import provision_or_get_user
        result = provision_or_get_user("new@example.com", display_name="New User")
        assert result is not None
        assert result["email"] == "new@example.com"


# ===========================================================================
# Test: API endpoint registration
# ===========================================================================


class TestSamlEndpoints:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from api import app
        self.routes = {r.path for r in app.routes if hasattr(r, "path")}

    def test_saml_metadata_endpoint(self):
        assert "/api/v1/saml/metadata" in self.routes

    def test_saml_login_endpoint(self):
        assert "/api/v1/saml/login" in self.routes

    def test_saml_acs_endpoint(self):
        assert "/api/v1/saml/acs" in self.routes

    def test_saml_logout_endpoint(self):
        assert "/api/v1/saml/logout" in self.routes

    def test_saml_status_endpoint(self):
        assert "/api/v1/saml/status" in self.routes

    def test_saml_sessions_cleanup_endpoint(self):
        assert "/api/v1/saml/sessions/cleanup" in self.routes
