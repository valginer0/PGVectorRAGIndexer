"""Tests for role-based collection grants (document-set access control).

Covers grant semantics, identity resolution, the reserved
``allowed_namespaces`` filter key in both engines' filter builders, and the
auto-ownership helper on the indexing endpoints.
"""

import pytest
from unittest.mock import MagicMock, patch

import collection_grants
from collection_grants import (
    allowed_namespaces_for_role,
    grant_collection,
    search_allowed_namespaces_for_key_record,
)
from lancedb_adapter import BackendLanceDBAdapter


def _mock_db(rows):
    """Mock _get_db_connection returning the given fetchall rows."""
    conn = MagicMock()
    cursor = conn.cursor.return_value
    cursor.fetchall.return_value = rows
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=conn)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# Grant semantics
# ---------------------------------------------------------------------------


def test_no_role_is_unrestricted():
    assert allowed_namespaces_for_role(None) is None
    assert allowed_namespaces_for_role("") is None


def test_role_without_grants_is_unrestricted():
    with patch.object(collection_grants, "_get_db_connection", return_value=_mock_db([])):
        assert allowed_namespaces_for_role("researcher") is None


def test_wildcard_grant_is_unrestricted():
    with patch.object(
        collection_grants, "_get_db_connection",
        return_value=_mock_db([("finance",), ("*",)]),
    ):
        assert allowed_namespaces_for_role("researcher") is None


def test_granted_role_is_restricted_to_namespaces():
    with patch.object(
        collection_grants, "_get_db_connection",
        return_value=_mock_db([("finance",), ("legal",)]),
    ):
        assert allowed_namespaces_for_role("researcher") == ["finance", "legal"]


def test_grant_to_unknown_role_fails():
    with patch("role_permissions.get_valid_roles", return_value={"admin", "user"}):
        assert grant_collection("nonexistent", "finance") is False


def test_grant_empty_namespace_raises():
    with patch("role_permissions.get_valid_roles", return_value={"user"}):
        with pytest.raises(ValueError):
            grant_collection("user", "   ")


# ---------------------------------------------------------------------------
# Identity resolution
# ---------------------------------------------------------------------------


def test_no_key_record_is_unrestricted():
    assert search_allowed_namespaces_for_key_record(None) is None


def test_admin_is_unrestricted():
    with patch("users.get_user_by_api_key", return_value={"id": "u1", "role": "admin"}), \
         patch("role_permissions.has_permission", return_value=True):
        assert search_allowed_namespaces_for_key_record({"id": 1}) is None


def test_unlinked_key_is_unrestricted_by_grants():
    with patch("users.get_user_by_api_key", return_value=None):
        assert search_allowed_namespaces_for_key_record({"id": 1}) is None


def test_restricted_role_resolves_namespaces():
    with patch("users.get_user_by_api_key", return_value={"id": "u1", "role": "researcher"}), \
         patch("role_permissions.has_permission", return_value=False), \
         patch.object(collection_grants, "allowed_namespaces_for_role", return_value=["finance"]) as anr:
        assert search_allowed_namespaces_for_key_record({"id": 2}) == ["finance"]
    anr.assert_called_once_with("researcher")


# ---------------------------------------------------------------------------
# Filter builders — allowed_namespaces
# ---------------------------------------------------------------------------


@pytest.fixture
def adapter(tmp_path):
    return BackendLanceDBAdapter(db_path=str(tmp_path / "lancedb"), embedding_dimension=4)


def test_lancedb_clause_allowed_namespaces(adapter):
    clause = adapter._build_lancedb_filter_clause({"allowed_namespaces": ["finance", "legal"]})
    assert clause == "namespace IN ('finance', 'legal')"


def test_lancedb_clause_empty_allowlist_matches_nothing(adapter):
    clause = adapter._build_lancedb_filter_clause({"allowed_namespaces": []})
    assert clause == "document_id IS NULL"


def test_postgres_cte_allowed_namespaces():
    from retriever_v2 import DocumentRetriever

    ret = DocumentRetriever.__new__(DocumentRetriever)
    cte, source, params = ret._build_filtered_docs_context(
        {"allowed_namespaces": ["finance"]}
    )
    assert "metadata->>'namespace' = ANY(%s)" in cte
    assert source == "filtered_docs"
    assert params == [["finance"]]


def test_postgres_cte_empty_allowlist_matches_nothing():
    from retriever_v2 import DocumentRetriever

    ret = DocumentRetriever.__new__(DocumentRetriever)
    cte, source, params = ret._build_filtered_docs_context(
        {"allowed_namespaces": []}
    )
    assert "FALSE" in cte
    assert params == []


def test_lancedb_search_respects_namespace_grants(adapter):
    """End-to-end: a namespace-restricted search only returns granted docs."""
    text = "quarterly budget overview report"
    vec = [0.8, 0.6, 0.0, 0.0]
    for doc_id, namespace in [("doc-fin", "finance"), ("doc-eng", "engineering")]:
        adapter.upsert_document(
            document_id=doc_id,
            source_uri=f"file:///{doc_id}.txt",
            chunks=[(0, text, vec, {})],
            aggregated_text=text,
            doc_metadata={"namespace": namespace},
        )
    adapter.rebuild_fts_index()

    def search_with(allowed):
        results = adapter.search_parent_child(
            query_text="quarterly budget",
            query_vector=vec,
            parent_limit=5,
            child_limit=10,
            filters={"allowed_namespaces": allowed} if allowed is not None else None,
        )
        return {r["document_id"] for r in results}

    assert search_with(["finance"]) == {"doc-fin"}
    assert search_with(["engineering"]) == {"doc-eng"}
    assert search_with([]) == set()


# ---------------------------------------------------------------------------
# Auto-ownership on indexing endpoints
# ---------------------------------------------------------------------------


def test_assign_owner_noop_without_user():
    from routers.indexing_api import _assign_owner_if_authenticated

    with patch("document_visibility.resolve_user_id_for_key_record", return_value=None), \
         patch("document_visibility.set_document_owner") as set_owner:
        _assign_owner_if_authenticated({"id": 1}, "doc-1")
    set_owner.assert_not_called()


def test_assign_owner_sets_owner_for_linked_user():
    from routers.indexing_api import _assign_owner_if_authenticated

    with patch("document_visibility.resolve_user_id_for_key_record", return_value="u-1"), \
         patch("document_visibility.set_document_owner") as set_owner:
        _assign_owner_if_authenticated({"id": 1}, "doc-1")
    set_owner.assert_called_once_with("doc-1", "u-1")


def test_assign_owner_failure_does_not_raise():
    from routers.indexing_api import _assign_owner_if_authenticated

    with patch("document_visibility.resolve_user_id_for_key_record", side_effect=RuntimeError("db down")):
        _assign_owner_if_authenticated({"id": 1}, "doc-1")  # must not raise


def test_assign_owner_noop_without_document_id():
    from routers.indexing_api import _assign_owner_if_authenticated

    with patch("document_visibility.resolve_user_id_for_key_record") as resolve:
        _assign_owner_if_authenticated({"id": 1}, None)
    resolve.assert_not_called()
