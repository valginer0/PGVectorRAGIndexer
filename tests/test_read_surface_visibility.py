"""
Team-mode visibility filtering on read surfaces (review finding, 2026-06-11).

Read endpoints previously returned global metadata to any authenticated
caller. These tests cover the filtering added to:
- GET /documents, GET /documents/{id}
- document tree (children, stats, search) for both postgres and lancedb sources
- /statistics, /extensions, /metadata/keys, /metadata/values
- /documents/encrypted, /documents/locks, /indexing/runs
"""

import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

VIS_SENTINEL = ("owner_id = %s OR visibility = 'shared'", ["u-sentinel"])


def _hidden_id_for(uri: str) -> str:
    return hashlib.sha256(uri.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# document_visibility helpers
# ---------------------------------------------------------------------------


def test_clause_local_mode_no_filter():
    from document_visibility import visibility_clause_for_key_record
    assert visibility_clause_for_key_record(None) == ("", [])


def test_clause_admin_no_filter():
    from document_visibility import visibility_clause_for_key_record
    with patch("users.get_user_by_api_key", return_value={"id": "u-9", "role": "admin"}), \
         patch("role_permissions.has_permission", return_value=True):
        assert visibility_clause_for_key_record({"id": 9}) == ("", [])


def test_clause_regular_user_scopes_to_shared_plus_own():
    from document_visibility import visibility_clause_for_key_record
    with patch("users.get_user_by_api_key", return_value={"id": "u-1", "role": "user"}), \
         patch("role_permissions.has_permission", return_value=False):
        sql, params = visibility_clause_for_key_record({"id": 1})
    assert "owner_id = %s" in sql
    assert params == ["u-1"]


def test_clause_unlinked_key_sees_shared_only():
    from document_visibility import visibility_clause_for_key_record
    with patch("users.get_user_by_api_key", return_value=None):
        sql, params = visibility_clause_for_key_record({"id": 3})
    assert "visibility = 'shared'" in sql
    assert params == []


def test_is_admin_key_record_local_mode_true():
    from document_visibility import is_admin_key_record
    assert is_admin_key_record(None) is True


def test_is_admin_key_record_regular_user_false():
    from document_visibility import is_admin_key_record
    with patch("users.get_user_by_api_key", return_value={"id": "u-1", "role": "user"}), \
         patch("role_permissions.has_permission", return_value=False):
        assert is_admin_key_record({"id": 1}) is False


def test_is_admin_key_record_unlinked_key_false():
    from document_visibility import is_admin_key_record
    with patch("users.get_user_by_api_key", return_value=None):
        assert is_admin_key_record({"id": 1}) is False


def test_filter_entries_by_hidden_source_drops_hidden():
    from document_visibility import filter_entries_by_hidden_source
    entries = [
        {"source_uri": "/secret/alpha.pdf", "x": 1},
        {"source_uri": "/shared/beta.txt", "x": 2},
    ]
    with patch(
        "document_visibility.search_exclusions_for_key_record",
        return_value=[_hidden_id_for("/secret/alpha.pdf")],
    ):
        out = filter_entries_by_hidden_source(entries, {"id": 1})
    assert [e["x"] for e in out] == [2]


def test_filter_entries_no_hidden_is_noop():
    from document_visibility import filter_entries_by_hidden_source
    entries = [{"source_uri": "/a"}, {"source_uri": "/b"}]
    with patch("document_visibility.search_exclusions_for_key_record", return_value=[]):
        assert filter_entries_by_hidden_source(entries, {"id": 1}) == entries


# ---------------------------------------------------------------------------
# document_tree LanceDB-source filtering
# ---------------------------------------------------------------------------


def _fake_adapter(docs):
    adapter = MagicMock()
    adapter.list_documents.return_value = docs
    adapter.get_statistics.return_value = {
        "total_documents": len(docs),
        "total_chunks": sum(d["chunk_count"] for d in docs),
    }
    return adapter


_LANCEDB_DOCS = [
    {"source_uri": "secret/alpha.pdf", "document_id": "hidden-1", "chunk_count": 3, "indexed_at": None},
    {"source_uri": "shared/beta.txt", "document_id": "vis-1", "chunk_count": 2, "indexed_at": None},
]


def test_tree_children_lancedb_hides_hidden_docs(monkeypatch):
    import document_tree
    monkeypatch.setattr("services.get_lancedb_adapter", lambda: _fake_adapter(_LANCEDB_DOCS))

    result = document_tree.get_tree_children(source="lancedb", hidden_document_ids=["hidden-1"])
    names = [c["name"] for c in result["children"]]
    assert "secret" not in names
    assert "shared" in names


def test_tree_stats_lancedb_counts_only_visible(monkeypatch):
    import document_tree
    monkeypatch.setattr("services.get_lancedb_adapter", lambda: _fake_adapter(_LANCEDB_DOCS))

    stats = document_tree.get_tree_stats(source="lancedb", hidden_document_ids=["hidden-1"])
    assert stats["total_documents"] == 1
    assert stats["total_chunks"] == 2
    assert stats["top_level_items"] == 1


def test_tree_search_lancedb_hides_hidden_docs(monkeypatch):
    import document_tree
    monkeypatch.setattr("services.get_lancedb_adapter", lambda: _fake_adapter(_LANCEDB_DOCS))

    results = document_tree.search_tree("alpha", source="lancedb", hidden_document_ids=["hidden-1"])
    assert results == []
    results = document_tree.search_tree("beta", source="lancedb", hidden_document_ids=["hidden-1"])
    assert len(results) == 1


# ---------------------------------------------------------------------------
# Route wiring (visibility threaded through to the repository/tree)
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_search_api(monkeypatch):
    from routers import search_api
    fake_repo = MagicMock()
    fake_repo.list_documents.return_value = ([], 0)
    fake_repo.get_document_by_id.return_value = None
    fake_repo.get_statistics.return_value = {}
    fake_repo.get_indexed_extensions.return_value = []
    fake_repo.get_metadata_keys.return_value = []
    fake_repo.get_metadata_values.return_value = []
    monkeypatch.setattr(search_api, "get_db_manager", lambda: MagicMock())
    monkeypatch.setattr(search_api, "DocumentRepository", lambda dbm: fake_repo)
    monkeypatch.setattr(
        "document_visibility.visibility_clause_for_key_record", lambda kr: VIS_SENTINEL
    )
    return search_api, fake_repo


async def test_list_documents_route_passes_visibility(patched_search_api):
    search_api, repo = patched_search_api
    await search_api.list_documents(
        limit=10, offset=0, sort_by="indexed_at", sort_dir="desc",
        source_prefix=None, key_record={"id": 1},
    )
    assert repo.list_documents.call_args.kwargs["visibility"] == VIS_SENTINEL


async def test_get_document_route_hides_invisible_as_404(patched_search_api):
    from fastapi import HTTPException
    search_api, repo = patched_search_api
    with pytest.raises(HTTPException) as exc:
        await search_api.get_document("doc-1", key_record={"id": 1})
    assert exc.value.status_code == 404
    assert repo.get_document_by_id.call_args.kwargs["visibility"] == VIS_SENTINEL


async def test_statistics_route_passes_visibility(patched_search_api, monkeypatch):
    search_api, repo = patched_search_api
    monkeypatch.setattr(
        search_api, "get_embedding_service",
        lambda: MagicMock(get_model_info=lambda: {"model_name": "m"}),
    )
    await search_api.get_statistics(key_record={"id": 1})
    assert repo.get_statistics.call_args.kwargs["visibility"] == VIS_SENTINEL


async def test_extensions_route_passes_visibility(patched_search_api):
    search_api, repo = patched_search_api
    await search_api.get_indexed_extensions(key_record={"id": 1})
    assert repo.get_indexed_extensions.call_args.kwargs["visibility"] == VIS_SENTINEL


async def test_metadata_routes_pass_visibility(patched_search_api):
    search_api, repo = patched_search_api
    await search_api.get_metadata_keys(pattern=None, key_record={"id": 1})
    assert repo.get_metadata_keys.call_args.kwargs["visibility"] == VIS_SENTINEL
    await search_api.get_metadata_values(key="type", limit=100, key_record={"id": 1})
    assert repo.get_metadata_values.call_args.kwargs["visibility"] == VIS_SENTINEL


async def test_tree_routes_pass_filters(monkeypatch):
    from routers import search_api

    monkeypatch.setattr(
        "document_visibility.visibility_clause_for_key_record", lambda kr: VIS_SENTINEL
    )
    monkeypatch.setattr(
        "document_visibility.search_exclusions_for_key_record", lambda kr: ["hidden-1"]
    )

    captured = {}

    def fake_children(**kwargs):
        captured["children"] = kwargs
        return {"children": []}

    def fake_stats(**kwargs):
        captured["stats"] = kwargs
        return {}

    def fake_search(**kwargs):
        captured["search"] = kwargs
        return []

    monkeypatch.setattr("document_tree.get_tree_children", fake_children)
    monkeypatch.setattr("document_tree.get_tree_stats", fake_stats)
    monkeypatch.setattr("document_tree.search_tree", fake_search)

    # Postgres source: SQL clause, no hidden-id list
    await search_api.get_document_tree(
        parent_path="", limit=200, offset=0, source="postgres", key_record={"id": 1},
    )
    assert captured["children"]["visibility"] == VIS_SENTINEL
    assert captured["children"]["hidden_document_ids"] is None

    # LanceDB source: hidden-id exclusion list is computed
    await search_api.get_document_tree_stats(source="lancedb", key_record={"id": 1})
    assert captured["stats"]["hidden_document_ids"] == ["hidden-1"]

    await search_api.search_document_tree(
        q="x", limit=50, source="lancedb", key_record={"id": 1},
    )
    assert captured["search"]["hidden_document_ids"] == ["hidden-1"]


# ---------------------------------------------------------------------------
# Encrypted-PDF listing scoped to uploader
# ---------------------------------------------------------------------------


@pytest.fixture
def encrypted_entries(monkeypatch):
    entries = [
        {"source_uri": "/a.pdf", "detected_at": "2026-06-11T00:00:00+00:00", "uploader_key_id": 1},
        {"source_uri": "/b.pdf", "detected_at": "2026-06-11T00:00:00+00:00", "uploader_key_id": 2},
    ]
    import services
    monkeypatch.setattr(services, "encrypted_pdfs_encountered", entries)
    return entries


async def test_encrypted_list_non_admin_sees_only_own(encrypted_entries, monkeypatch):
    from routers import search_api
    monkeypatch.setattr("document_visibility.is_admin_key_record", lambda kr: False)

    res = await search_api.list_encrypted_pdfs(since=None, clear=False, key_record={"id": 1})
    assert res["count"] == 1
    assert res["encrypted_pdfs"][0]["source_uri"] == "/a.pdf"


async def test_encrypted_list_admin_sees_all(encrypted_entries, monkeypatch):
    from routers import search_api
    monkeypatch.setattr("document_visibility.is_admin_key_record", lambda kr: True)

    res = await search_api.list_encrypted_pdfs(since=None, clear=False, key_record={"id": 9})
    assert res["count"] == 2


async def test_encrypted_clear_non_admin_only_clears_own(encrypted_entries, monkeypatch):
    from routers import search_api
    monkeypatch.setattr("document_visibility.is_admin_key_record", lambda kr: False)

    await search_api.list_encrypted_pdfs(since=None, clear=True, key_record={"id": 1})
    assert [e["uploader_key_id"] for e in encrypted_entries] == [2]


# ---------------------------------------------------------------------------
# Locks and indexing runs filtered against hidden documents
# ---------------------------------------------------------------------------


async def test_lock_listing_hides_locks_on_hidden_docs(monkeypatch):
    from routers import indexing_api
    locks = [
        {"source_uri": "/secret/alpha.pdf", "client_id": "c1"},
        {"source_uri": "/shared/beta.txt", "client_id": "c2"},
    ]
    monkeypatch.setattr("document_locks.list_locks", lambda client_id=None: locks)
    monkeypatch.setattr(
        "document_visibility.search_exclusions_for_key_record",
        lambda kr: [_hidden_id_for("/secret/alpha.pdf")],
    )

    res = await indexing_api.list_document_locks(client_id=None, key_record={"id": 1})
    assert res["count"] == 1
    assert res["locks"][0]["source_uri"] == "/shared/beta.txt"


async def test_indexing_runs_listing_hides_runs_for_hidden_docs(monkeypatch):
    from routers import monitoring_api
    runs = [
        {"id": "r1", "source_uri": "/secret/alpha.pdf"},
        {"id": "r2", "source_uri": "/shared/beta.txt"},
    ]
    monkeypatch.setattr("indexing_runs.get_recent_runs", lambda limit=20: runs)
    monkeypatch.setattr(
        "document_visibility.search_exclusions_for_key_record",
        lambda kr: [_hidden_id_for("/secret/alpha.pdf")],
    )

    res = await monitoring_api.list_indexing_runs(limit=20, key_record={"id": 1})
    assert [r["id"] for r in res["runs"]] == ["r2"]


async def test_indexing_run_detail_hidden_doc_404(monkeypatch):
    from fastapi import HTTPException
    from routers import monitoring_api
    monkeypatch.setattr(
        "indexing_runs.get_run_by_id",
        lambda run_id: {"id": run_id, "source_uri": "/secret/alpha.pdf"},
    )
    monkeypatch.setattr(
        "document_visibility.search_exclusions_for_key_record",
        lambda kr: [_hidden_id_for("/secret/alpha.pdf")],
    )

    with pytest.raises(HTTPException) as exc:
        await monitoring_api.get_indexing_run("r1", key_record={"id": 1})
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# DB-backed integration: SQL paths actually filter
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.database
def test_postgres_read_surfaces_filter_hidden_documents(db_manager):
    from database import DocumentRepository
    from document_visibility import visibility_where_clause
    import document_tree

    repo = DocumentRepository(db_manager)

    with db_manager.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, email) VALUES ('test-vis-u1', 'vis-u1@test.local') "
            "ON CONFLICT (id) DO NOTHING"
        )
        conn.commit()

    try:
        emb = [0.0] * 384
        repo.insert_chunks([
            ("vis-doc-a", 0, "alpha private content", "/team/private/alpha.pdf", emb,
             {"type": "secret-type", "secret_key": "x"}),
            ("vis-doc-b", 0, "beta shared content", "/team/shared/beta.txt", emb,
             {"type": "shared-type"}),
        ])
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE document_chunks SET owner_id = 'test-vis-u1', visibility = 'private' "
                "WHERE document_id = 'vis-doc-a'"
            )
            conn.commit()

        stranger = visibility_where_clause("someone-else", False)
        owner = visibility_where_clause("test-vis-u1", False)

        # GET /documents
        docs, total = repo.list_documents(with_total=True, visibility=stranger)
        assert {d["document_id"] for d in docs} == {"vis-doc-b"}
        assert total == 1
        docs, total = repo.list_documents(with_total=True, visibility=owner)
        assert {d["document_id"] for d in docs} == {"vis-doc-a", "vis-doc-b"}
        assert total == 2

        # GET /documents/{id}
        assert repo.get_document_by_id("vis-doc-a", visibility=stranger) is None
        assert repo.get_document_by_id("vis-doc-a", visibility=owner) is not None

        # /statistics
        stats = repo.get_statistics(visibility=stranger)
        assert stats["total_documents"] == 1
        assert stats["total_chunks"] == 1

        # /extensions
        assert repo.get_indexed_extensions(visibility=stranger) == [".txt"]

        # /metadata/keys and /metadata/values
        keys = repo.get_metadata_keys(visibility=stranger)
        assert "secret_key" not in keys
        values = repo.get_metadata_values("type", visibility=stranger)
        assert "secret-type" not in values
        assert "shared-type" in values

        # Document tree (children / stats / search)
        children = document_tree.get_tree_children(parent_path="/team", visibility=stranger)
        names = [c["name"] for c in children["children"]]
        assert "private" not in names
        assert "shared" in names

        tree_stats = document_tree.get_tree_stats(visibility=stranger)
        assert tree_stats["total_documents"] == 1
        assert tree_stats["total_chunks"] == 1

        assert document_tree.search_tree("alpha", visibility=stranger) == []
        assert len(document_tree.search_tree("alpha", visibility=owner)) == 1
    finally:
        with db_manager.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM document_chunks WHERE document_id IN ('vis-doc-a', 'vis-doc-b')")
            cur.execute("DELETE FROM users WHERE id = 'test-vis-u1'")
            conn.commit()
