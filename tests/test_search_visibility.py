"""Tests for per-user document visibility filtering in search.

Covers the reserved ``excluded_document_ids`` filter key across the LanceDB
and Postgres filter builders, plus the identity-resolution helper that turns
an API key record into an exclusion list.
"""

import pytest
from unittest.mock import patch

from lancedb_adapter import BackendLanceDBAdapter
import document_visibility
from document_visibility import (
    get_hidden_document_ids,
    search_exclusions_for_key_record,
)


# ---------------------------------------------------------------------------
# LanceDB filter clause
# ---------------------------------------------------------------------------


@pytest.fixture
def adapter(tmp_path):
    return BackendLanceDBAdapter(db_path=str(tmp_path / "lancedb"), embedding_dimension=4)


def test_lancedb_clause_excludes_document_ids(adapter):
    clause = adapter._build_lancedb_filter_clause(
        {"excluded_document_ids": ["doc-1", "doc-2"]}
    )
    assert clause == "document_id NOT IN ('doc-1', 'doc-2')"


def test_lancedb_clause_empty_exclusion_is_noop(adapter):
    assert adapter._build_lancedb_filter_clause({"excluded_document_ids": []}) is None


def test_lancedb_clause_escapes_quotes(adapter):
    clause = adapter._build_lancedb_filter_clause(
        {"excluded_document_ids": ["doc'1"]}
    )
    assert clause == "document_id NOT IN ('doc''1')"


def test_lancedb_clause_combines_with_other_filters(adapter):
    clause = adapter._build_lancedb_filter_clause(
        {"type": "story", "excluded_document_ids": ["doc-1"]}
    )
    assert "document_type = 'story'" in clause
    assert "document_id NOT IN ('doc-1')" in clause
    assert " AND " in clause


def test_lancedb_search_respects_exclusion(adapter):
    """End-to-end on real LanceDB tables: an excluded doc never returns chunks."""
    text = "EV6 charging port diagnostics manual"
    vec = [0.8, 0.6, 0.0, 0.0]
    for doc_id in ("doc-public", "doc-private"):
        adapter.upsert_document(
            document_id=doc_id,
            source_uri=f"file:///{doc_id}.txt",
            chunks=[(0, text, vec, {})],
            aggregated_text=text,
            doc_metadata={},
        )
    adapter.rebuild_fts_index()

    # Excluding one doc must leave only the other — in both directions,
    # which proves both docs are searchable and the filter decides the outcome.
    def search_excluding(excluded):
        results = adapter.search_parent_child(
            query_text="EV6 charging",
            query_vector=vec,
            parent_limit=5,
            child_limit=10,
            filters={"excluded_document_ids": [excluded]},
        )
        return {r["document_id"] for r in results}

    assert search_excluding("doc-private") == {"doc-public"}
    assert search_excluding("doc-public") == {"doc-private"}


# ---------------------------------------------------------------------------
# Postgres filter builders (no live DB needed — SQL/params construction only)
# ---------------------------------------------------------------------------


def _make_retriever():
    """Build a retriever instance without touching the DB."""
    from retriever_v2 import DocumentRetriever

    return DocumentRetriever.__new__(DocumentRetriever)


def test_filtered_docs_cte_excludes_document_ids():
    ret = _make_retriever()
    cte, source, params = ret._build_filtered_docs_context(
        {"excluded_document_ids": ["doc-1", "doc-2"]}
    )
    assert "document_id != ALL(%s)" in cte
    assert source == "filtered_docs"
    assert params == [["doc-1", "doc-2"]]


def test_filtered_docs_cte_empty_exclusion_is_noop():
    ret = _make_retriever()
    cte, source, params = ret._build_filtered_docs_context(
        {"excluded_document_ids": []}
    )
    assert cte == ""
    assert source == "document_chunks"
    assert params == []


def test_filtered_docs_cte_unknown_key_still_raises():
    ret = _make_retriever()
    with pytest.raises(ValueError, match="Unsupported filter key"):
        ret._build_filtered_docs_context({"bogus_key": "x"})


# ---------------------------------------------------------------------------
# Identity resolution → exclusion list
# ---------------------------------------------------------------------------


def test_no_key_record_means_no_filtering():
    """Local / auth-disabled mode: no visibility filtering at all."""
    assert search_exclusions_for_key_record(None) == []


def test_admin_user_sees_everything():
    with patch("users.get_user_by_api_key", return_value={"id": "u-admin", "role": "admin"}), \
         patch("role_permissions.has_permission", return_value=True) as has_perm, \
         patch.object(document_visibility, "get_hidden_document_ids") as hidden:
        hidden.return_value = []
        result = search_exclusions_for_key_record({"id": 1})
    has_perm.assert_called_once_with("admin", "system.admin")
    hidden.assert_called_once_with(user_id="u-admin", is_admin=True)
    assert result == []


def test_regular_user_hides_other_private_docs():
    with patch("users.get_user_by_api_key", return_value={"id": "u-1", "role": "user"}), \
         patch("role_permissions.has_permission", return_value=False), \
         patch.object(document_visibility, "get_hidden_document_ids") as hidden:
        hidden.return_value = ["doc-private"]
        result = search_exclusions_for_key_record({"id": 2})
    hidden.assert_called_once_with(user_id="u-1", is_admin=False)
    assert result == ["doc-private"]


def test_unlinked_key_hides_all_private_docs():
    with patch("users.get_user_by_api_key", return_value=None), \
         patch.object(document_visibility, "get_hidden_document_ids") as hidden:
        hidden.return_value = ["doc-a", "doc-b"]
        result = search_exclusions_for_key_record({"id": 3})
    hidden.assert_called_once_with(user_id=None, is_admin=False)
    assert result == ["doc-a", "doc-b"]


def test_get_hidden_document_ids_admin_short_circuits():
    """Admin path must not touch the database."""
    with patch.object(document_visibility, "_get_db_connection") as conn:
        assert get_hidden_document_ids(user_id="u-admin", is_admin=True) == []
    conn.assert_not_called()


def test_get_hidden_document_ids_reraises_on_db_error():
    """A DB failure must raise (fail closed), not silently return []."""
    with patch.object(document_visibility, "_get_db_connection", side_effect=RuntimeError("db down")):
        with pytest.raises(RuntimeError, match="db down"):
            get_hidden_document_ids(user_id="u-1", is_admin=False)


# ---------------------------------------------------------------------------
# /context endpoint access filtering (review fix 2026-06-10)
# ---------------------------------------------------------------------------


def test_context_endpoint_applies_access_filters():
    """/context must inject the same visibility/grant filters as /search."""
    import asyncio
    from unittest.mock import MagicMock
    import routers.search_api as search_api

    fake_ret = MagicMock()
    fake_ret.get_context.return_value = "ctx"

    with patch.object(search_api, "get_retriever", return_value=fake_ret), \
         patch("document_visibility.search_exclusions_for_key_record",
               return_value=["doc-hidden"]), \
         patch("collection_grants.search_allowed_namespaces_for_key_record",
               return_value=["finance"]):
        asyncio.get_event_loop().run_until_complete(
            search_api.get_context(query="q", top_k=5, use_hybrid=False,
                                   source="lancedb", key_record={"id": 1})
        )

    _, kwargs = fake_ret.get_context.call_args
    assert kwargs["filters"] == {
        "excluded_document_ids": ["doc-hidden"],
        "allowed_namespaces": ["finance"],
    }


def test_context_endpoint_local_mode_unfiltered():
    import asyncio
    from unittest.mock import MagicMock
    import routers.search_api as search_api

    fake_ret = MagicMock()
    fake_ret.get_context.return_value = "ctx"

    with patch.object(search_api, "get_retriever", return_value=fake_ret):
        asyncio.get_event_loop().run_until_complete(
            search_api.get_context(query="q", top_k=5, use_hybrid=False,
                                   source="lancedb", key_record=None)
        )

    _, kwargs = fake_ret.get_context.call_args
    assert kwargs["filters"] is None


def test_apply_access_filters_client_cannot_widen_namespaces():
    """A client-supplied allowed_namespaces must never survive unrestricted."""
    from routers.search_api import _apply_access_filters

    with patch("document_visibility.search_exclusions_for_key_record", return_value=[]), \
         patch("collection_grants.search_allowed_namespaces_for_key_record", return_value=None):
        result = _apply_access_filters({"id": 1}, {"allowed_namespaces": ["anything"]})
    assert result is None


def test_visibility_writers_reraise_on_db_error():
    """DB failure must surface as an error, not as 'document not found' (0)."""
    from document_visibility import set_document_owner, set_document_visibility

    with patch.object(document_visibility, "_get_db_connection", side_effect=RuntimeError("db down")):
        with pytest.raises(RuntimeError):
            set_document_owner("doc-1", "u-1")
        with pytest.raises(RuntimeError):
            set_document_visibility("doc-1", "private")


# ---------------------------------------------------------------------------
# Visibility-change ownership check (enforcement audit 2026-06-11)
# ---------------------------------------------------------------------------


def test_may_change_visibility_local_mode_allows():
    from routers.visibility_api import _may_change_visibility
    assert _may_change_visibility(None, "doc-1") is True


def test_may_change_visibility_owner_allowed():
    from routers.visibility_api import _may_change_visibility
    with patch("users.get_user_by_api_key", return_value={"id": "u-1", "role": "user"}), \
         patch("role_permissions.has_permission", return_value=False), \
         patch("document_visibility.get_document_visibility",
               return_value={"owner_id": "u-1"}):
        assert _may_change_visibility({"id": 1}, "doc-1") is True


def test_may_change_visibility_non_owner_denied():
    """The bypass the audit closed: flipping someone else's private doc."""
    from routers.visibility_api import _may_change_visibility
    with patch("users.get_user_by_api_key", return_value={"id": "u-2", "role": "user"}), \
         patch("role_permissions.has_permission", return_value=False), \
         patch("document_visibility.get_document_visibility",
               return_value={"owner_id": "u-1"}):
        assert _may_change_visibility({"id": 2}, "doc-1") is False


def test_may_change_visibility_unowned_requires_all():
    from routers.visibility_api import _may_change_visibility
    with patch("users.get_user_by_api_key", return_value={"id": "u-2", "role": "user"}), \
         patch("role_permissions.has_permission", return_value=False), \
         patch("document_visibility.get_document_visibility",
               return_value={"owner_id": None}):
        assert _may_change_visibility({"id": 2}, "doc-1") is False


def test_may_change_visibility_all_permission_allows_any():
    from routers.visibility_api import _may_change_visibility
    with patch("users.get_user_by_api_key", return_value={"id": "u-2", "role": "sre"}), \
         patch("role_permissions.has_permission", return_value=True):
        assert _may_change_visibility({"id": 2}, "doc-1") is True


def test_delete_endpoints_require_delete_permission():
    """Route-level guard: deletes must carry the documents.delete dependency."""
    import os
    os.environ.setdefault('DB_HOST', 'localhost')
    from api import app

    found = {}
    for route in app.routes:
        if getattr(route, "path", "") in ("/documents/{document_id}", "/documents/bulk-delete"):
            methods = getattr(route, "methods", set())
            if "DELETE" in methods or route.path.endswith("bulk-delete"):
                dep_names = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
                found[f"{sorted(methods)} {route.path}"] = dep_names

    assert found, "delete routes not found"
    for key, deps in found.items():
        assert "_check_permission" in deps, f"{key} missing permission dependency: {deps}"
