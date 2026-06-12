"""
Filter-key SQL-injection guard + delete/stat visibility scoping
(ultrareview local pass, 2026-06-12).

Covers:
1. DocumentRepository.search_similar / preview_delete / bulk_delete reject
   unknown filter keys (the keys were interpolated into SQL via f-string,
   allowing injection and voiding the AND-joined visibility clauses).
2. preview_delete / bulk_delete apply a caller visibility clause.
3. Route wiring: GET /stats scopes counts; bulk-delete threads visibility to
   both stores; quarantine restore/purge are admin-gated.
"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

VIS = ("(visibility = 'shared' OR owner_id = %s)", ["u-1"])


class _FakeCursor:
    """Captures executed SQL + params; returns benign rows."""

    rowcount = 0

    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return {"count": 0}

    def fetchall(self):
        return []


def _repo_with_capture():
    from database import DocumentRepository

    cursor = _FakeCursor()

    @contextmanager
    def fake_get_cursor(dict_cursor=False):
        yield cursor

    db = MagicMock()
    db.get_cursor.side_effect = fake_get_cursor
    repo = DocumentRepository(db)
    return repo, cursor


# ---------------------------------------------------------------------------
# SQL-injection guard on filter keys
# ---------------------------------------------------------------------------

INJECTION_KEY = "1=1 OR document_id IS NOT NULL OR 1"


def test_search_similar_rejects_unknown_filter_key():
    repo, cursor = _repo_with_capture()
    with pytest.raises(ValueError, match="Unsupported filter key"):
        repo.search_similar([0.0, 0.1], filters={INJECTION_KEY: "x"})
    assert cursor.calls == []  # rejected before any SQL ran


def test_preview_delete_rejects_unknown_filter_key():
    repo, cursor = _repo_with_capture()
    with pytest.raises(ValueError, match="Unsupported filter key"):
        repo.preview_delete({INJECTION_KEY: "x"})
    assert cursor.calls == []


def test_bulk_delete_rejects_unknown_filter_key():
    repo, cursor = _repo_with_capture()
    with pytest.raises(ValueError, match="Unsupported filter key"):
        repo.bulk_delete({INJECTION_KEY: "x"})
    assert cursor.calls == []


@pytest.mark.parametrize("key", sorted(__import__("database").DocumentRepository.ALLOWED_FILTER_COLUMNS))
def test_allowed_direct_columns_pass(key):
    repo, cursor = _repo_with_capture()
    # Should not raise; the key reaches a parameterized clause.
    repo.preview_delete({key: "val"})
    assert cursor.calls, "expected SQL to execute for an allowed key"
    sql = cursor.calls[0][0]
    assert f"{key} = %s" in sql


def test_explicit_branches_still_work_without_injection():
    """metadata.*, type/namespace/category, extensions, excluded_document_ids
    keep working and never interpolate a raw key."""
    repo, cursor = _repo_with_capture()
    repo.search_similar(
        [0.0, 0.1],
        filters={
            "metadata.author": "bob",
            "type": "policy",
            "extensions": [".pdf"],
            "excluded_document_ids": ["d1"],
        },
    )
    assert cursor.calls, "expected SQL to execute"
    sql = cursor.calls[0][0]
    # No raw key leaked into SQL; metadata key is bound as a parameter.
    assert "author" not in sql
    assert "metadata->>%s = %s" in sql


# ---------------------------------------------------------------------------
# Visibility scoping on preview_delete / bulk_delete
# ---------------------------------------------------------------------------


def test_preview_delete_appends_visibility_clause():
    repo, cursor = _repo_with_capture()
    repo.preview_delete({"document_id": "x"}, visibility=VIS)
    sql, params = cursor.calls[0]
    assert VIS[0] in sql
    assert "u-1" in params


def test_bulk_delete_appends_visibility_clause():
    repo, cursor = _repo_with_capture()
    repo.bulk_delete({"document_id": "x"}, visibility=VIS)
    sql, params = cursor.calls[0]
    assert VIS[0] in sql
    assert "u-1" in params


def test_bulk_delete_safety_check_unaffected_by_visibility():
    """Visibility alone must not satisfy the 'filters required' safety check."""
    repo, cursor = _repo_with_capture()
    with pytest.raises(ValueError, match="Filters are required"):
        repo.bulk_delete({}, visibility=VIS)
    assert cursor.calls == []


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


def _patch_runs(monkeypatch):
    monkeypatch.setattr("indexing_runs.start_run", lambda **kw: 1, raising=False)
    monkeypatch.setattr("indexing_runs.complete_run", lambda *a, **k: None, raising=False)


async def test_stats_route_scopes_counts_to_caller(monkeypatch):
    from routers import system_api

    captured = {}
    fake_idx = MagicMock()
    fake_idx.get_statistics.side_effect = lambda visibility=None: captured.update(
        {"visibility": visibility}
    ) or {
        "database": {
            "total_documents": 1,
            "total_chunks": 2,
            "avg_chunks_per_document": 2,
            "database_size": "1 MB",
        },
        "embedding_model": {"model_name": "m", "dimension": 384},
    }
    monkeypatch.setattr(system_api, "get_indexer", lambda: fake_idx)
    monkeypatch.setattr(
        "document_visibility.visibility_clause_for_key_record", lambda kr: VIS
    )

    await system_api.get_statistics(key_record={"id": 1})
    assert captured["visibility"] == VIS


async def test_bulk_delete_route_threads_visibility_to_both_stores(monkeypatch):
    from routers import search_api
    from api_models import BulkDeleteRequest

    repo = MagicMock()
    repo.bulk_delete.return_value = 3
    monkeypatch.setattr(search_api, "get_db_manager", lambda: MagicMock())
    monkeypatch.setattr(search_api, "DocumentRepository", lambda dbm: repo)
    monkeypatch.setattr(
        "document_visibility.visibility_clause_for_key_record", lambda kr: VIS
    )
    monkeypatch.setattr(
        "document_visibility.search_exclusions_for_key_record", lambda kr: ["hidden-1"]
    )
    monkeypatch.setattr(
        "config.get_config",
        lambda: SimpleNamespace(retrieval=SimpleNamespace(lancedb_enabled=True)),
    )
    fake_adapter = MagicMock()
    monkeypatch.setattr("services.get_lancedb_adapter", lambda: fake_adapter)
    monkeypatch.setattr("retriever_v2.begin_lancedb_mutation", lambda: None)
    monkeypatch.setattr("retriever_v2.end_lancedb_mutation", lambda: None)
    monkeypatch.setattr("retriever_v2.invalidate_lancedb_cache", lambda: None)

    req = BulkDeleteRequest(filters={"namespace": "finance"}, preview=False)
    await search_api.bulk_delete_documents(req, key_record={"id": 1})

    # Postgres delete got the visibility clause
    assert repo.bulk_delete.call_args.kwargs["visibility"] == VIS
    # LanceDB delete got the hidden-id exclusion merged in (no drift)
    lancedb_filters = fake_adapter.bulk_delete.call_args.args[0]
    assert "hidden-1" in lancedb_filters["excluded_document_ids"]
    assert lancedb_filters["namespace"] == "finance"


async def test_bulk_delete_preview_is_visibility_scoped(monkeypatch):
    from routers import search_api
    from api_models import BulkDeleteRequest

    repo = MagicMock()
    repo.preview_delete.return_value = {
        "document_count": 0,
        "sample_documents": [],
        "filters_applied": {},
    }
    monkeypatch.setattr(search_api, "get_db_manager", lambda: MagicMock())
    monkeypatch.setattr(search_api, "DocumentRepository", lambda dbm: repo)
    monkeypatch.setattr(
        "document_visibility.visibility_clause_for_key_record", lambda kr: VIS
    )

    req = BulkDeleteRequest(filters={"namespace": "finance"}, preview=True)
    await search_api.bulk_delete_documents(req, key_record={"id": 1})
    assert repo.preview_delete.call_args.kwargs["visibility"] == VIS


def test_quarantine_restore_and_purge_require_admin():
    """Restore/purge must be admin-gated (existence-oracle + mutation guard)."""
    import os
    os.environ.setdefault("DB_HOST", "localhost")
    from api import app

    targets = {
        "/api/v1/quarantine/{source_uri:path}/restore",
        "/api/v1/quarantine/purge",
    }
    checked = 0
    for route in app.routes:
        path = getattr(route, "path", "")
        if any(path.endswith(t.replace("/api/v1", "")) or path == t for t in targets):
            dep_names = {
                getattr(d.call, "__name__", "") for d in route.dependant.dependencies
            }
            assert "require_admin" in dep_names, f"{path} not admin-gated: {dep_names}"
            checked += 1
    assert checked >= 2, f"expected to check 2 routes, checked {checked}"
