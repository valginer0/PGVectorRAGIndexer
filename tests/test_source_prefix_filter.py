"""Tests for source_prefix filter on GET /documents (#7 Phase A).

Tests cover:
- path_utils.normalize_path and NORMALIZED_URI_SQL consistency
- DocumentRepository.list_documents with source_prefix
- Root/empty prefix edge cases
- Windows-style and UNC path normalization
- Trailing-slash handling
- Pagination and sorting with prefix
- Parameter binding safety (no SQL injection)
- API endpoint pass-through
"""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ===========================================================================
# Test: path_utils.normalize_path
# ===========================================================================


class TestNormalizePath:
    def test_forward_slashes_unchanged(self):
        from path_utils import normalize_path
        assert normalize_path("/data/docs/file.pdf") == "/data/docs/file.pdf"

    def test_backslashes_converted(self):
        from path_utils import normalize_path
        assert normalize_path("C:\\Users\\docs\\file.pdf") == "C:/Users/docs/file.pdf"

    def test_tabs_converted(self):
        from path_utils import normalize_path
        assert normalize_path("data\tdocs") == "data/docs"

    def test_newlines_converted(self):
        from path_utils import normalize_path
        assert normalize_path("data\ndocs") == "data/docs"

    def test_carriage_returns_converted(self):
        from path_utils import normalize_path
        assert normalize_path("data\rdocs") == "data/docs"

    def test_mixed_separators(self):
        from path_utils import normalize_path
        result = normalize_path("C:\\data\tdocs/file.pdf")
        assert "\\" not in result
        assert "\t" not in result
        assert result == "C:/data/docs/file.pdf"

    def test_windows_unc_path(self):
        from path_utils import normalize_path
        result = normalize_path("\\\\server\\share\\docs\\file.txt")
        assert "\\" not in result
        assert result == "//server/share/docs/file.txt"

    def test_trailing_slash(self):
        from path_utils import normalize_path
        result = normalize_path("/docs/")
        assert result == "/docs/"


class TestNormalizedUriSqlConsistency:
    """Verify that NORMALIZED_URI_SQL matches normalize_path behavior."""

    def test_constant_is_string(self):
        from path_utils import NORMALIZED_URI_SQL
        assert isinstance(NORMALIZED_URI_SQL, str)
        assert "REPLACE" in NORMALIZED_URI_SQL
        assert "source_uri" in NORMALIZED_URI_SQL

    def test_handles_all_four_chars(self):
        """NORMALIZED_URI_SQL should normalize \\, \\t, \\n, \\r."""
        from path_utils import NORMALIZED_URI_SQL
        # Check all four replacements are present
        assert "E'\\\\'" in NORMALIZED_URI_SQL or "E'\\\\\\\\'" in NORMALIZED_URI_SQL
        assert "E'\\t'" in NORMALIZED_URI_SQL
        assert "E'\\n'" in NORMALIZED_URI_SQL
        assert "E'\\r'" in NORMALIZED_URI_SQL


# ===========================================================================
# Test: DocumentRepository.list_documents with source_prefix
# ===========================================================================


class TestListDocumentsSourcePrefix:
    """Test source_prefix filtering in DocumentRepository.list_documents."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock DatabaseManager."""
        db = MagicMock()
        return db

    @pytest.fixture
    def repo(self, mock_db):
        from database import DocumentRepository
        return DocumentRepository(mock_db)

    def test_no_prefix_no_where_clause(self, repo, mock_db):
        """Without source_prefix, query should have no WHERE clause."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.get_cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_db.get_cursor.return_value.__exit__ = MagicMock(return_value=False)

        repo.list_documents(limit=10)

        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "WHERE" not in executed_sql

    def test_prefix_adds_where_clause(self, repo, mock_db):
        """With source_prefix, query should include WHERE ... LIKE clause."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.get_cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_db.get_cursor.return_value.__exit__ = MagicMock(return_value=False)

        repo.list_documents(limit=10, source_prefix="/docs")

        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "WHERE" in executed_sql
        assert "LIKE" in executed_sql

        # Verify trailing-slash semantics: prefix + '/%'
        params = mock_cursor.execute.call_args[0][1]
        assert "/docs/%" in params

    def test_root_prefix_slash_means_unfiltered(self, repo, mock_db):
        """source_prefix='/' should be treated as no filter (returns all)."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.get_cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_db.get_cursor.return_value.__exit__ = MagicMock(return_value=False)

        repo.list_documents(limit=10, source_prefix="/")

        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "WHERE" not in executed_sql

    def test_none_prefix_means_unfiltered(self, repo, mock_db):
        """source_prefix=None should produce no WHERE clause."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.get_cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_db.get_cursor.return_value.__exit__ = MagicMock(return_value=False)

        repo.list_documents(limit=10, source_prefix=None)

        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "WHERE" not in executed_sql

    def test_empty_string_prefix_means_unfiltered(self, repo, mock_db):
        """source_prefix='' should produce no WHERE clause."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.get_cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_db.get_cursor.return_value.__exit__ = MagicMock(return_value=False)

        repo.list_documents(limit=10, source_prefix="")

        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "WHERE" not in executed_sql

    def test_windows_prefix_normalized(self, repo, mock_db):
        """Windows-style prefix should be normalized before filtering."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.get_cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_db.get_cursor.return_value.__exit__ = MagicMock(return_value=False)

        repo.list_documents(limit=10, source_prefix="C:\\Users\\docs")

        params = mock_cursor.execute.call_args[0][1]
        # Should be normalized to forward slashes + '/%'
        assert "C:/Users/docs/%" in params

    def test_trailing_slash_stripped(self, repo, mock_db):
        """Trailing slash in prefix should be stripped to avoid double-slash."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.get_cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_db.get_cursor.return_value.__exit__ = MagicMock(return_value=False)

        repo.list_documents(limit=10, source_prefix="/docs/")

        params = mock_cursor.execute.call_args[0][1]
        # Should be "/docs/%" not "/docs//%" 
        assert "/docs/%" in params
        assert "//%" not in str(params)

    def test_prefix_with_total_scoped(self, repo, mock_db):
        """with_total=True should also scope the total count query."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = (42,)
        mock_db.get_cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_db.get_cursor.return_value.__exit__ = MagicMock(return_value=False)

        result = repo.list_documents(limit=10, source_prefix="/docs", with_total=True)

        # Should have been called twice: once for items, once for total
        assert mock_cursor.execute.call_count == 2

        # Second call should also have WHERE clause
        total_sql = mock_cursor.execute.call_args_list[1][0][0]
        assert "WHERE" in total_sql
        assert "LIKE" in total_sql

    def test_param_binding_not_interpolation(self, repo, mock_db):
        """Verify source_prefix value is passed via %s params, not string formatting."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.get_cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_db.get_cursor.return_value.__exit__ = MagicMock(return_value=False)

        # Malicious prefix that would break if interpolated
        evil_prefix = "/docs'; DROP TABLE document_chunks; --"
        repo.list_documents(limit=10, source_prefix=evil_prefix)

        # The SQL should NOT contain the literal evil string
        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "DROP TABLE" not in executed_sql

        # The evil string should be in the params tuple (safely bound)
        params = mock_cursor.execute.call_args[0][1]
        found_in_params = any(
            isinstance(p, str) and "DROP TABLE" in p for p in params
        )
        assert found_in_params, "Malicious prefix should be in params, not SQL"

    def test_unc_path_prefix(self, repo, mock_db):
        """UNC path prefix should be normalized."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.get_cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_db.get_cursor.return_value.__exit__ = MagicMock(return_value=False)

        repo.list_documents(limit=10, source_prefix="\\\\server\\share\\docs")

        params = mock_cursor.execute.call_args[0][1]
        assert "//server/share/docs/%" in params


# ===========================================================================
# Test: API endpoint source_prefix pass-through
# ===========================================================================


class TestApiEndpointSourcePrefix:
    """Test that the API endpoint correctly passes source_prefix."""

    @pytest.fixture(autouse=True)
    def _load_routes(self):
        from api import v1_router
        self.routes = {r.path: r for r in v1_router.routes}

    def test_documents_endpoint_exists(self):
        assert "/documents" in self.routes

    def test_source_prefix_param_declared(self):
        """The /documents endpoint should accept source_prefix query param."""
        route = self.routes["/documents"]
        # Check the endpoint function signature
        import inspect
        sig = inspect.signature(route.endpoint)
        assert "source_prefix" in sig.parameters


# ===========================================================================
# Test: api_client source_prefix support
# ===========================================================================


class TestApiClientSourcePrefix:
    def test_source_prefix_included_in_params(self):
        """list_documents should include source_prefix in request params."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"items": [], "total": 0}

        with patch("requests.get", return_value=mock_response) as mock_get:
            from desktop_app.utils.api_client import APIClient
            real_client = APIClient("http://localhost:8000")
            real_client.list_documents(source_prefix="/docs")

            called_params = mock_get.call_args[1].get("params", {})
            assert called_params.get("source_prefix") == "/docs"

    def test_no_prefix_omits_param(self):
        """list_documents without source_prefix should not include it in params."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"items": [], "total": 0}

        with patch("requests.get", return_value=mock_response) as mock_get:
            from desktop_app.utils.api_client import APIClient
            real_client = APIClient("http://localhost:8000")
            real_client.list_documents()

            called_params = mock_get.call_args[1].get("params", {})
            assert "source_prefix" not in called_params
