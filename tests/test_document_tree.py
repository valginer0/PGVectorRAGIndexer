"""
Tests for Hierarchical Document Browser (#7).

Tests cover:
- _normalize_path helper
- get_tree_children logic (with mocked DB)
- get_tree_stats resilience
- search_tree resilience
- API endpoint registration
"""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ===========================================================================
# Test: _normalize_path
# ===========================================================================


class TestNormalizePath:
    def test_forward_slashes_unchanged(self):
        from document_tree import _normalize_path
        assert _normalize_path("/data/docs/file.pdf") == "/data/docs/file.pdf"

    def test_backslashes_converted(self):
        from document_tree import _normalize_path
        assert _normalize_path("C:\\Users\\docs\\file.pdf") == "C:/Users/docs/file.pdf"

    def test_tabs_converted(self):
        from document_tree import _normalize_path
        assert _normalize_path("data\tdocs") == "data/docs"

    def test_mixed(self):
        from document_tree import _normalize_path
        result = _normalize_path("C:\\data\tdocs/file.pdf")
        assert "\\" not in result
        assert "\t" not in result


# ===========================================================================
# Test: get_tree_children
# ===========================================================================


class TestGetTreeChildren:
    @patch("document_tree._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_empty_on_db_failure(self, _mock):
        from document_tree import get_tree_children
        result = get_tree_children()
        assert result["children"] == []
        assert result["total"] == 0

    @patch("document_tree._get_db_connection")
    def test_root_level_with_files_and_folders(self, mock_conn):
        now = datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc)
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            ("docs/report.pdf", "doc-1", 3, now, now),
            ("docs/notes.txt", "doc-2", 1, now, now),
            ("images/photo.jpg", "doc-3", 1, now, now),
            ("readme.md", "doc-4", 1, now, now),
        ]
        mock_conn.return_value.cursor.return_value = mock_cur

        from document_tree import get_tree_children
        result = get_tree_children("")

        assert result["total_folders"] == 2  # docs, images
        assert result["total_files"] == 1    # readme.md
        assert result["total"] == 3

        # Check folder aggregation
        folders = [c for c in result["children"] if c["type"] == "folder"]
        docs_folder = next(f for f in folders if f["name"] == "docs")
        assert docs_folder["document_count"] == 2

    @patch("document_tree._get_db_connection")
    def test_subfolder_level(self, mock_conn):
        now = datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc)
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            ("docs/report.pdf", "doc-1", 3, now, now),
            ("docs/sub/deep.txt", "doc-5", 1, now, now),
        ]
        mock_conn.return_value.cursor.return_value = mock_cur

        from document_tree import get_tree_children
        result = get_tree_children("docs")

        assert result["parent_path"] == "docs"
        files = [c for c in result["children"] if c["type"] == "file"]
        folders = [c for c in result["children"] if c["type"] == "folder"]
        assert len(files) == 1
        assert files[0]["name"] == "report.pdf"
        assert len(folders) == 1
        assert folders[0]["name"] == "sub"

    @patch("document_tree._get_db_connection")
    def test_pagination(self, mock_conn):
        now = datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc)
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            ("a.txt", "d1", 1, now, now),
            ("b.txt", "d2", 1, now, now),
            ("c.txt", "d3", 1, now, now),
        ]
        mock_conn.return_value.cursor.return_value = mock_cur

        from document_tree import get_tree_children
        result = get_tree_children("", limit=2, offset=0)
        assert len(result["children"]) == 2
        assert result["total"] == 3

        result2 = get_tree_children("", limit=2, offset=2)
        assert len(result2["children"]) == 1


# ===========================================================================
# Test: get_tree_stats
# ===========================================================================


class TestGetTreeStats:
    @patch("document_tree._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_zeros_on_db_failure(self, _mock):
        from document_tree import get_tree_stats
        result = get_tree_stats()
        assert result["total_documents"] == 0
        assert result["total_chunks"] == 0
        assert result["top_level_items"] == 0


# ===========================================================================
# Test: search_tree
# ===========================================================================


class TestSearchTree:
    @patch("document_tree._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_empty_on_db_failure(self, _mock):
        from document_tree import search_tree
        assert search_tree("test") == []

    @patch("document_tree._get_db_connection")
    def test_returns_matching_documents(self, mock_conn):
        now = datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc)
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            ("docs/report.pdf", "doc-1", 3, now),
        ]
        mock_conn.return_value.cursor.return_value = mock_cur

        from document_tree import search_tree
        results = search_tree("report")
        assert len(results) == 1
        assert results[0]["document_id"] == "doc-1"
        assert results[0]["path"] == "docs/report.pdf"


# ===========================================================================
# Test: API endpoint registration
# ===========================================================================


class TestDocumentTreeEndpoints:
    @pytest.fixture(autouse=True)
    def _load_app(self):
        from api import v1_router
        self.routes = {r.path for r in v1_router.routes}

    def test_tree_endpoint(self):
        assert "/documents/tree" in self.routes

    def test_stats_endpoint(self):
        assert "/documents/tree/stats" in self.routes

    def test_search_endpoint(self):
        assert "/documents/tree/search" in self.routes
