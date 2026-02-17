"""Tests for Phase 6b.2: Canonical Identity + Lock Key Migration.

Covers:
  - Canonical key format for client and server scopes
  - extract_relative_path edge cases
  - resolve_canonical_key round-trip
  - Dual-key lock resolution (root_id + relative_path vs source_uri)
  - Lock race: client and server locking same relative path under different roots
  - _backfill_canonical_keys flow
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# ── Canonical Identity ─────────────────────────────────────────────────────


class TestBuildCanonicalKey:
    """build_canonical_key() produces scope:identity:relative_path format."""

    def test_client_scope(self):
        from canonical_identity import build_canonical_key

        key = build_canonical_key("client", "abc123", "/docs/readme.md")
        assert key == "client:abc123:/docs/readme.md"

    def test_server_scope(self):
        from canonical_identity import build_canonical_key

        root_id = str(uuid.uuid4())
        key = build_canonical_key("server", root_id, "/data/report.pdf")
        assert key == f"server:{root_id}:/data/report.pdf"

    def test_normalizes_separators(self):
        from canonical_identity import build_canonical_key

        key = build_canonical_key("client", "c1", "docs\\sub\\file.txt")
        assert "\\" not in key
        assert key == "client:c1:/docs/sub/file.txt"

    def test_collapses_double_slashes(self):
        from canonical_identity import build_canonical_key

        key = build_canonical_key("server", "r1", "//docs//file.txt")
        assert "//" not in key
        assert key == "server:r1:/docs/file.txt"

    def test_strips_trailing_slash(self):
        from canonical_identity import build_canonical_key

        key = build_canonical_key("client", "c1", "/docs/folder/")
        assert key == "client:c1:/docs/folder"

    def test_preserves_root_slash(self):
        from canonical_identity import build_canonical_key

        key = build_canonical_key("client", "c1", "/")
        assert key == "client:c1:/"


class TestResolveCanonicalKey:
    """resolve_canonical_key() round-trips with build_canonical_key()."""

    def test_round_trip_client(self):
        from canonical_identity import build_canonical_key, resolve_canonical_key

        key = build_canonical_key("client", "abc", "/sub/file.md")
        result = resolve_canonical_key(key)
        assert result == {
            "scope": "client",
            "identity": "abc",
            "relative_path": "/sub/file.md",
        }

    def test_round_trip_server(self):
        from canonical_identity import build_canonical_key, resolve_canonical_key

        rid = str(uuid.uuid4())
        key = build_canonical_key("server", rid, "/report.pdf")
        result = resolve_canonical_key(key)
        assert result == {
            "scope": "server",
            "identity": rid,
            "relative_path": "/report.pdf",
        }

    def test_malformed_key(self):
        from canonical_identity import resolve_canonical_key

        assert resolve_canonical_key("") is None
        assert resolve_canonical_key("no-colons") is None
        assert resolve_canonical_key("invalid:scope:path") is None

    def test_none_key(self):
        from canonical_identity import resolve_canonical_key

        assert resolve_canonical_key(None) is None


class TestExtractRelativePath:
    """extract_relative_path() computes relative path within a root."""

    def test_simple_subtree(self):
        from canonical_identity import extract_relative_path

        result = extract_relative_path("/data/docs", "/data/docs/sub/readme.md")
        assert result == "/sub/readme.md"

    def test_root_equals_path(self):
        from canonical_identity import extract_relative_path

        result = extract_relative_path("/data/docs", "/data/docs")
        assert result == "/"

    def test_trailing_slash_root(self):
        from canonical_identity import extract_relative_path

        result = extract_relative_path("/data/docs/", "/data/docs/file.txt")
        assert result == "/file.txt"

    def test_windows_backslashes(self):
        from canonical_identity import extract_relative_path

        result = extract_relative_path(
            "C:\\Users\\alice\\docs", "C:\\Users\\alice\\docs\\sub\\file.txt"
        )
        assert result == "/sub/file.txt"

    def test_not_under_root(self):
        from canonical_identity import extract_relative_path

        result = extract_relative_path("/data/docs", "/other/path/file.txt")
        assert result == "/other/path/file.txt"

    def test_nested_deep(self):
        from canonical_identity import extract_relative_path

        result = extract_relative_path(
            "/data", "/data/a/b/c/d/file.txt"
        )
        assert result == "/a/b/c/d/file.txt"


# ── Dual-Key Lock Resolution ───────────────────────────────────────────────


class TestBuildLockWhere:
    """_build_lock_where() builds correct SQL WHERE clause."""

    def test_source_uri_only(self):
        from document_locks import _build_lock_where

        where, params = _build_lock_where("/data/file.txt")
        assert "source_uri = %s" in where
        assert params == ("/data/file.txt",)

    def test_dual_key(self):
        from document_locks import _build_lock_where

        where, params = _build_lock_where(
            "/data/file.txt", root_id="r1", relative_path="/file.txt"
        )
        assert "root_id = %s" in where
        assert "relative_path = %s" in where
        assert "source_uri = %s" in where
        assert params == ("r1", "/file.txt", "/data/file.txt")

    def test_root_id_without_relative_path_falls_back(self):
        from document_locks import _build_lock_where

        where, params = _build_lock_where("/data/file.txt", root_id="r1")
        # Falls back to source_uri only
        assert params == ("/data/file.txt",)


class TestAcquireLockDualKey:
    """acquire_lock() with root_id + relative_path."""

    @patch("document_locks._get_db_connection")
    def test_acquire_with_root_id(self, mock_conn):
        from document_locks import acquire_lock

        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [
            None,  # No existing lock
            (  # INSERT RETURNING
                "lock-1", "/data/file.txt", "client-1",
                datetime.now(timezone.utc),
                datetime.now(timezone.utc),
                "indexing", "root-1", "/file.txt",
            ),
        ]
        mock_conn.return_value.cursor.return_value = mock_cur

        result = acquire_lock(
            source_uri="/data/file.txt",
            client_id="client-1",
            root_id="root-1",
            relative_path="/file.txt",
        )

        assert result["ok"] is True
        lock = result["lock"]
        assert lock["root_id"] == "root-1"
        assert lock["relative_path"] == "/file.txt"

    @patch("document_locks._get_db_connection")
    def test_acquire_backward_compatible(self, mock_conn):
        """Old callers not passing root_id still work."""
        from document_locks import acquire_lock

        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [
            None,  # No existing lock
            (  # INSERT RETURNING
                "lock-2", "/data/file.txt", "client-1",
                datetime.now(timezone.utc),
                datetime.now(timezone.utc),
                "indexing", None, None,
            ),
        ]
        mock_conn.return_value.cursor.return_value = mock_cur

        result = acquire_lock(
            source_uri="/data/file.txt",
            client_id="client-1",
        )

        assert result["ok"] is True
        lock = result["lock"]
        assert lock["root_id"] is None
        assert lock["relative_path"] is None


class TestCheckLockDualKey:
    """check_lock() with dual-key resolution."""

    @patch("document_locks._get_db_connection")
    def test_check_with_root_id(self, mock_conn):
        from document_locks import check_lock

        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (
            "lock-1", "/data/file.txt", "client-1",
            datetime.now(timezone.utc),
            datetime.now(timezone.utc),
            "indexing", "root-1", "/file.txt",
        )
        mock_conn.return_value.cursor.return_value = mock_cur

        result = check_lock(
            source_uri="/data/file.txt",
            root_id="root-1",
            relative_path="/file.txt",
        )

        assert result is not None
        assert result["root_id"] == "root-1"

    @patch("document_locks._get_db_connection")
    def test_check_backward_compatible(self, mock_conn):
        from document_locks import check_lock

        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None
        mock_conn.return_value.cursor.return_value = mock_cur

        result = check_lock(source_uri="/data/file.txt")
        assert result is None


class TestReleaseLockDualKey:
    """release_lock() with dual-key resolution."""

    @patch("document_locks._get_db_connection")
    def test_release_with_root_id(self, mock_conn):
        from document_locks import release_lock

        mock_cur = MagicMock()
        mock_cur.rowcount = 1
        mock_conn.return_value.cursor.return_value = mock_cur

        result = release_lock(
            source_uri="/data/file.txt",
            client_id="client-1",
            root_id="root-1",
            relative_path="/file.txt",
        )
        assert result is True


# ── Canonical Key Backfill ─────────────────────────────────────────────────


class TestBulkSetCanonicalKeys:
    """bulk_set_canonical_keys() backfills keys for chunks under a root."""

    @patch("canonical_identity._get_db_connection")
    def test_backfill_sets_keys(self, mock_conn):
        from canonical_identity import bulk_set_canonical_keys

        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            (1, "/data/docs/readme.md"),
            (2, "/data/docs/sub/notes.txt"),
        ]
        mock_cur.rowcount = 1
        mock_conn.return_value.cursor.return_value = mock_cur

        count = bulk_set_canonical_keys(
            root_id="root-1",
            folder_path="/data/docs",
            scope="server",
            identity="root-1",
        )

        assert count == 2
        # Verify UPDATE calls were made
        assert mock_cur.execute.call_count >= 3  # SELECT + 2 UPDATEs

    @patch("canonical_identity._get_db_connection")
    def test_backfill_no_chunks(self, mock_conn):
        from canonical_identity import bulk_set_canonical_keys

        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = []
        mock_conn.return_value.cursor.return_value = mock_cur

        count = bulk_set_canonical_keys(
            root_id="root-1",
            folder_path="/data/docs",
            scope="server",
            identity="root-1",
        )
        assert count == 0


class TestFindByCanonicalKey:
    """find_by_canonical_key() queries chunks by canonical key."""

    @patch("canonical_identity._get_db_connection")
    def test_finds_chunks(self, mock_conn):
        from canonical_identity import find_by_canonical_key

        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            (1, "doc-1", "/data/docs/readme.md", "server:r1:/readme.md"),
            (2, "doc-1", "/data/docs/readme.md", "server:r1:/readme.md"),
        ]
        mock_conn.return_value.cursor.return_value = mock_cur

        results = find_by_canonical_key("server:r1:/readme.md")
        assert len(results) == 2
        assert results[0]["canonical_source_key"] == "server:r1:/readme.md"

    @patch("canonical_identity._get_db_connection")
    def test_no_matches(self, mock_conn):
        from canonical_identity import find_by_canonical_key

        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = []
        mock_conn.return_value.cursor.return_value = mock_cur

        results = find_by_canonical_key("server:r1:/nonexistent.md")
        assert results == []


# ── Backfill in scan_folder ────────────────────────────────────────────────


class TestScanFolderCanonicalBackfill:
    """scan_folder() triggers _backfill_canonical_keys when root_id is provided."""

    @patch("watched_folders._backfill_canonical_keys")
    @patch("os.walk", return_value=[("/data/docs", [], ["f.txt"])])
    @patch("os.path.isdir", return_value=True)
    def test_backfill_called_with_root_id(
        self, mock_isdir, mock_walk, mock_backfill,
    ):
        from watched_folders import scan_folder

        # Mock all lazy imports inside scan_folder
        mock_db = MagicMock()
        mock_embed = MagicMock()
        mock_indexer_cls = MagicMock()

        with patch.dict("sys.modules", {
            "indexing_runs": MagicMock(start_run=MagicMock(return_value="run-1")),
            "indexer_v2": MagicMock(DocumentIndexer=mock_indexer_cls),
            "database": MagicMock(get_db_manager=MagicMock(return_value=mock_db)),
            "embeddings": MagicMock(get_embedding_service=MagicMock(return_value=mock_embed)),
        }):
            result = scan_folder("/data/docs", root_id="root-1")

        assert result["status"] == "success"
        mock_backfill.assert_called_once_with("root-1", "/data/docs")

    @patch("watched_folders._backfill_canonical_keys")
    @patch("os.walk", return_value=[("/data/docs", [], ["f.txt"])])
    @patch("os.path.isdir", return_value=True)
    def test_backfill_not_called_without_root_id(
        self, mock_isdir, mock_walk, mock_backfill,
    ):
        from watched_folders import scan_folder

        mock_db = MagicMock()
        mock_embed = MagicMock()
        mock_indexer_cls = MagicMock()

        with patch.dict("sys.modules", {
            "indexing_runs": MagicMock(start_run=MagicMock(return_value="run-1")),
            "indexer_v2": MagicMock(DocumentIndexer=mock_indexer_cls),
            "database": MagicMock(get_db_manager=MagicMock(return_value=mock_db)),
            "embeddings": MagicMock(get_embedding_service=MagicMock(return_value=mock_embed)),
        }):
            result = scan_folder("/data/docs")

        assert result["status"] == "success"
        mock_backfill.assert_not_called()


# ── Migration 014 metadata ────────────────────────────────────────────────


class TestMigration014Metadata:
    """Basic structural checks for migration 014."""

    def test_revision_chain(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration_014",
            "/home/valginer0/projects/PGVectorRAGIndexer/alembic/versions/014_canonical_identity.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.revision == "014"
        assert mod.down_revision == "013"

    def test_has_upgrade_downgrade(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration_014",
            "/home/valginer0/projects/PGVectorRAGIndexer/alembic/versions/014_canonical_identity.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)
