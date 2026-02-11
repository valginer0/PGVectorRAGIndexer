"""
Tests for #3 Multi-User Support Phase 2 — Document Visibility.

Tests cover:
- Migration 012: owner_id and visibility columns
- document_visibility.py: constants, SQL filter generation, DB resilience, validation
- API endpoint registration
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = Path(__file__).parent.parent


# ===========================================================================
# Test: Migration 012
# ===========================================================================


class TestMigration012:
    def test_migration_file_exists(self):
        assert (PROJECT_ROOT / "alembic" / "versions" / "012_document_visibility.py").exists()

    def test_migration_has_correct_revision(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration_012",
            str(PROJECT_ROOT / "alembic" / "versions" / "012_document_visibility.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.revision == "012"
        assert mod.down_revision == "011"

    def test_migration_has_upgrade_and_downgrade(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration_012",
            str(PROJECT_ROOT / "alembic" / "versions" / "012_document_visibility.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(getattr(mod, "upgrade", None))
        assert callable(getattr(mod, "downgrade", None))


# ===========================================================================
# Test: Constants
# ===========================================================================


class TestVisibilityConstants:
    def test_valid_visibilities(self):
        from document_visibility import VALID_VISIBILITIES, VISIBILITY_SHARED, VISIBILITY_PRIVATE
        assert VISIBILITY_SHARED in VALID_VISIBILITIES
        assert VISIBILITY_PRIVATE in VALID_VISIBILITIES
        assert len(VALID_VISIBILITIES) == 2

    def test_shared_is_default(self):
        from document_visibility import VISIBILITY_SHARED
        assert VISIBILITY_SHARED == "shared"

    def test_private_value(self):
        from document_visibility import VISIBILITY_PRIVATE
        assert VISIBILITY_PRIVATE == "private"


# ===========================================================================
# Test: SQL filter generation
# ===========================================================================


class TestVisibilityWhereClause:
    def test_admin_sees_everything(self):
        from document_visibility import visibility_where_clause
        sql, params = visibility_where_clause(user_id="u1", is_admin=True)
        assert sql == ""
        assert params == []

    def test_no_user_sees_shared_only(self):
        from document_visibility import visibility_where_clause
        sql, params = visibility_where_clause(user_id=None, is_admin=False)
        assert "shared" in sql
        assert "owner_id IS NULL" in sql
        assert params == []

    def test_regular_user_sees_shared_and_own(self):
        from document_visibility import visibility_where_clause
        sql, params = visibility_where_clause(user_id="u1", is_admin=False)
        assert "shared" in sql
        assert "owner_id = %s" in sql
        assert params == ["u1"]

    def test_admin_no_user_id_still_sees_all(self):
        from document_visibility import visibility_where_clause
        sql, params = visibility_where_clause(user_id=None, is_admin=True)
        assert sql == ""
        assert params == []


class TestVisibilityWhereClauseForDocument:
    def test_admin_document_check(self):
        from document_visibility import visibility_where_clause_for_document
        sql, params = visibility_where_clause_for_document("doc1", user_id="u1", is_admin=True)
        assert "document_id = %s" in sql
        assert params == ["doc1"]

    def test_regular_user_document_check(self):
        from document_visibility import visibility_where_clause_for_document
        sql, params = visibility_where_clause_for_document("doc1", user_id="u1", is_admin=False)
        assert "document_id = %s" in sql
        assert "owner_id = %s" in sql
        assert "doc1" in params
        assert "u1" in params


# ===========================================================================
# Test: DB resilience
# ===========================================================================


class TestVisibilityDBResilience:
    @patch("document_visibility._get_db_connection", side_effect=Exception("DB down"))
    def test_set_document_owner_returns_zero(self, _mock):
        from document_visibility import set_document_owner
        assert set_document_owner("doc1", "u1") == 0

    @patch("document_visibility._get_db_connection", side_effect=Exception("DB down"))
    def test_set_document_visibility_returns_zero(self, _mock):
        from document_visibility import set_document_visibility
        assert set_document_visibility("doc1", "shared") == 0

    @patch("document_visibility._get_db_connection", side_effect=Exception("DB down"))
    def test_set_owner_and_visibility_returns_zero(self, _mock):
        from document_visibility import set_document_owner_and_visibility
        assert set_document_owner_and_visibility("doc1", "u1", "shared") == 0

    @patch("document_visibility._get_db_connection", side_effect=Exception("DB down"))
    def test_get_document_visibility_returns_none(self, _mock):
        from document_visibility import get_document_visibility
        assert get_document_visibility("doc1") is None

    @patch("document_visibility._get_db_connection", side_effect=Exception("DB down"))
    def test_list_user_documents_returns_empty(self, _mock):
        from document_visibility import list_user_documents
        assert list_user_documents("u1") == []

    @patch("document_visibility._get_db_connection", side_effect=Exception("DB down"))
    def test_bulk_set_visibility_returns_zero(self, _mock):
        from document_visibility import bulk_set_visibility
        assert bulk_set_visibility(["doc1"], "shared") == 0

    @patch("document_visibility._get_db_connection", side_effect=Exception("DB down"))
    def test_transfer_ownership_returns_zero(self, _mock):
        from document_visibility import transfer_ownership
        assert transfer_ownership("doc1", "u2") == 0


# ===========================================================================
# Test: Validation
# ===========================================================================


class TestVisibilityValidation:
    def test_set_visibility_rejects_invalid(self):
        from document_visibility import set_document_visibility
        assert set_document_visibility("doc1", "secret") == -1

    def test_set_owner_and_visibility_rejects_invalid(self):
        from document_visibility import set_document_owner_and_visibility
        assert set_document_owner_and_visibility("doc1", "u1", "secret") == -1

    def test_bulk_set_rejects_invalid(self):
        from document_visibility import bulk_set_visibility
        assert bulk_set_visibility(["doc1"], "secret") == -1

    def test_bulk_set_empty_list_returns_zero(self):
        from document_visibility import bulk_set_visibility
        assert bulk_set_visibility([], "shared") == 0


# ===========================================================================
# Test: API endpoint registration
# ===========================================================================


class TestVisibilityEndpoints:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from api import app
        self.routes = {r.path for r in app.routes if hasattr(r, "path")}

    def test_get_visibility_endpoint(self):
        assert "/api/v1/documents/{document_id}/visibility" in self.routes

    def test_set_visibility_endpoint(self):
        assert "/api/v1/documents/{document_id}/visibility" in self.routes

    def test_transfer_ownership_endpoint(self):
        assert "/api/v1/documents/{document_id}/transfer" in self.routes

    def test_list_user_documents_endpoint(self):
        assert "/api/v1/users/{user_id}/documents" in self.routes

    def test_bulk_visibility_endpoint(self):
        assert "/api/v1/documents/bulk-visibility" in self.routes
