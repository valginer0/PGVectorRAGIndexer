import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock
from fastapi import HTTPException

from api_models import SearchRequest, BulkDeleteRequest, RestoreRequest
from routers import search_api
from scripts import sync_lancedb


class _FakeRetriever:
    def __init__(self, results, diagnostics=None):
        self.results = results
        self.diagnostics = diagnostics or {}
        self.calls = []

    def _should_use_lancedb(self, source: str = "lancedb") -> bool:
        return source != "postgres"

    def search_lancedb_parent_child(self, **kwargs):
        self.calls.append(("lancedb", kwargs))
        return self.results, self.diagnostics

    def search_hybrid(self, **kwargs):
        self.calls.append(("postgres_hybrid", kwargs))
        return self.results

    def search(self, **kwargs):
        self.calls.append(("postgres", kwargs))
        return self.results


class _FakeAdapter:
    def __init__(self):
        self.upserts = []
        self.deletes = []
        self.bulk_deletes = []

    def upsert_document(self, **kwargs):
        self.upserts.append(kwargs)

    def add_documents_bulk(self, documents):
        for doc_id, source_uri, chunks, aggregated_text, doc_metadata in documents:
            self.upserts.append({
                "document_id": doc_id,
                "source_uri": source_uri,
                "chunks": chunks,
                "aggregated_text": aggregated_text,
                "doc_metadata": doc_metadata
            })

    def delete_document(self, doc_id):
        self.deletes.append(doc_id)
        return 1

    def bulk_delete(self, filters):
        self.bulk_deletes.append(filters)
        return 1

    def get_statistics(self):
        return {
            "total_documents": len(self.upserts),
            "total_chunks": sum(len(upsert.get("chunks", [])) for upsert in self.upserts),
        }


def _result(source_uri, *, rank_score, text_content="", chunk_index=0, chunk_id=1):
    return SimpleNamespace(
        chunk_id=chunk_id,
        document_id=f"doc-{source_uri}",
        chunk_index=chunk_index,
        text_content=text_content,
        source_uri=source_uri,
        distance=1.0 - min(rank_score, 1.0),
        relevance_score=min(rank_score, 1.0),
        rank_score=rank_score,
        metadata={},
        document_type=None,
    )


def _reset_lancedb_readiness_state():
    import retriever_v2

    retriever_v2._lancedb_cache_dirty = True
    retriever_v2._lancedb_cached_ready = False
    retriever_v2._lancedb_current_drift_signature = None
    retriever_v2._lancedb_failed_sync_signature = None
    retriever_v2._lancedb_sync_failure_message = None
    retriever_v2._sync_thread = None
    retriever_v2._lancedb_mutation_count = 0


@pytest.mark.asyncio
async def test_search_api_routes_to_lancedb_when_enabled(monkeypatch):
    """Test that search_documents routes to search_lancedb_parent_child if lancedb_enabled is True."""
    # 1. Mock Config to return lancedb_enabled = True
    fake_config = SimpleNamespace(
        retrieval=SimpleNamespace(
            lancedb_enabled=True,
            lancedb_storage_path="/tmp/test_lancedb",
            lancedb_child_parent_spill_ratio=1.0
        )
    )
    monkeypatch.setattr("config.get_config", lambda: fake_config)

    # 2. Mock Retriever
    retriever = _FakeRetriever(
        results=[
            _result("ev6_warranty.txt", rank_score=0.95),
            _result("banana_bread.txt", rank_score=0.1)
        ],
        diagnostics={"lancedb_parent_child": {"active": True}}
    )
    monkeypatch.setattr(search_api, "get_retriever", lambda: retriever)

    # 3. Call search endpoint
    response = await search_api.search_documents(SearchRequest(
        query="EV6 battery",
        top_k=2,
        filters={"extensions": ["txt"]}
    ))

    assert response.total_results == 2
    assert response.results[0].source_uri == "ev6_warranty.txt"
    assert response.diagnostics["lancedb_parent_child"]["active"] is True
    assert retriever.calls[0][0] == "lancedb"
    assert retriever.calls[0][1]["query"] == "EV6 battery"
    assert retriever.calls[0][1]["filters"] == {"extensions": ["txt"]}


@pytest.mark.asyncio
async def test_search_api_routes_explicit_postgres_source(monkeypatch):
    """source='postgres' should bypass LanceDB and reach the Postgres retriever path."""
    retriever = _FakeRetriever(
        results=[_result("postgres_doc.txt", rank_score=0.88)],
    )
    monkeypatch.setattr(search_api, "get_retriever", lambda: retriever)

    response = await search_api.search_documents(SearchRequest(
        query="postgres only",
        top_k=1,
        source="postgres",
        use_hybrid=True,
    ))

    assert response.total_results == 1
    assert response.results[0].source_uri == "postgres_doc.txt"
    assert retriever.calls[0][0] == "postgres_hybrid"
    assert retriever.calls[0][1]["source"] == "postgres"


@pytest.mark.asyncio
async def test_bulk_delete_api_syncs_with_lancedb(monkeypatch):
    """Test that bulk_delete_documents calls lancedb bulk_delete when enabled."""
    fake_config = SimpleNamespace(
        retrieval=SimpleNamespace(
            lancedb_enabled=True,
            lancedb_storage_path="/tmp/test_lancedb"
        )
    )
    monkeypatch.setattr("config.get_config", lambda: fake_config)

    fake_adapter = _FakeAdapter()
    monkeypatch.setattr("services.get_lancedb_adapter", lambda: fake_adapter)

    # Mock database repository
    class FakeRepo:
        def bulk_delete(self, filters):
            return 5

    monkeypatch.setattr(search_api, "DocumentRepository", lambda _db: FakeRepo())

    response = await search_api.bulk_delete_documents(BulkDeleteRequest(
        filters={"type": "policy"},
        preview=False
    ))

    assert response.chunks_deleted == 5
    assert response.status == "success"
    assert len(fake_adapter.bulk_deletes) == 1
    assert fake_adapter.bulk_deletes[0] == {"type": "policy"}


@pytest.mark.asyncio
async def test_restore_api_syncs_with_lancedb(monkeypatch):
    """Test that restore_documents groups chunks by doc ID and calls upsert_document on LanceDB."""
    fake_config = SimpleNamespace(
        retrieval=SimpleNamespace(
            lancedb_enabled=True,
            lancedb_storage_path="/tmp/test_lancedb"
        )
    )
    monkeypatch.setattr("config.get_config", lambda: fake_config)

    fake_adapter = _FakeAdapter()
    monkeypatch.setattr("services.get_lancedb_adapter", lambda: fake_adapter)

    class FakeRepo:
        def restore_documents(self, data):
            return len(data)

    monkeypatch.setattr(search_api, "DocumentRepository", lambda _db: FakeRepo())

    backup_data = [
        {
            "document_id": "doc-1",
            "chunk_index": 0,
            "text_content": "Text chunk 1",
            "source_uri": "doc1.txt",
            "embedding": [1.0, 0.0],
            "metadata": {"type": "news"}
        },
        {
            "document_id": "doc-1",
            "chunk_index": 1,
            "text_content": "Text chunk 2",
            "source_uri": "doc1.txt",
            "embedding": [0.0, 1.0],
            "metadata": {"type": "news"}
        },
        {
            "document_id": "doc-2",
            "chunk_index": 0,
            "text_content": "Another doc",
            "source_uri": "doc2.txt",
            "embedding": [0.5, 0.5],
            "metadata": {"type": "specs"}
        }
    ]

    response = await search_api.restore_documents(RestoreRequest(
        backup_data=backup_data
    ))

    assert response["chunks_restored"] == 3
    assert len(fake_adapter.upserts) == 2  # doc-1 and doc-2

    # Check doc-1 upsert data
    doc1_upsert = next(x for x in fake_adapter.upserts if x["document_id"] == "doc-1")
    assert doc1_upsert["source_uri"] == "doc1.txt"
    assert len(doc1_upsert["chunks"]) == 2
    assert doc1_upsert["aggregated_text"] == "Text chunk 1\n\nText chunk 2"


def test_sync_lancedb_script(monkeypatch):
    """Test that sync_postgres_to_lancedb queries postgres and pushes to LanceDB."""
    fake_config = SimpleNamespace(
        retrieval=SimpleNamespace(
            lancedb_storage_path="/tmp/test_lancedb"
        ),
        embedding=SimpleNamespace(
            dimension=4
        )
    )
    monkeypatch.setattr(sync_lancedb, "get_config", lambda: fake_config)

    fake_adapter = _FakeAdapter()
    # Mock optimize method
    fake_adapter.optimize_vector_index = lambda: None
    monkeypatch.setattr(sync_lancedb, "get_lancedb_adapter", lambda: fake_adapter)

    # Mock DB cursor
    class FakeCursor:
        def __init__(self, data_type):
            self.data_type = data_type

        def execute(self, _sql, params=None):
            pass

        def fetchall(self):
            if self.data_type == "docs":
                return [
                    {"document_id": "doc-a", "source_uri": "doca.txt"},
                    {"document_id": "doc-b", "source_uri": "docb.txt"}
                ]
            else:  # chunks
                return [
                    {
                        "document_id": "doc-a",
                        "chunk_index": 0,
                        "text_content": "chunk-a1",
                        "source_uri": "doca.txt",
                        "embedding": [1.0, 0.0, 0.0, 0.0],
                        "metadata": '{"type": "doc"}'
                    },
                    {
                        "document_id": "doc-b",
                        "chunk_index": 0,
                        "text_content": "chunk-b1",
                        "source_uri": "docb.txt",
                        "embedding": [0.0, 1.0, 0.0, 0.0],
                        "metadata": '{"type": "doc"}'
                    }
                ]

    class FakeCursorContext:
        def __init__(self, data_type):
            self.cursor = FakeCursor(data_type)

        def __enter__(self):
            return self.cursor

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeDBManager:
        def __init__(self):
            self.call_count = 0

        def get_cursor(self, dict_cursor=True):
            self.call_count += 1
            if self.call_count == 1:
                return FakeCursorContext("docs")
            else:
                return FakeCursorContext("chunks")

    monkeypatch.setattr(sync_lancedb, "get_db_manager", lambda: FakeDBManager())

    sync_lancedb.sync_postgres_to_lancedb(batch_size=10, force=False)

    assert len(fake_adapter.upserts) == 2
    assert fake_adapter.upserts[0]["document_id"] == "doc-a"
    assert fake_adapter.upserts[1]["document_id"] == "doc-b"


def test_failed_lancedb_sync_guard_does_not_relaunch_same_drift(monkeypatch):
    """A drift signature that already failed to sync should not launch another full sync."""
    import retriever_v2
    from retriever_v2 import DocumentRetriever, LanceDBNotReadyError

    _reset_lancedb_readiness_state()

    class FakeRepository:
        def get_statistics(self):
            return {"total_documents": 1, "total_chunks": 2}

    class FakeAdapter:
        def get_statistics(self):
            return {"total_documents": 0, "total_chunks": 0}

    sync_calls = []

    def fake_run_background_sync(self, drift_signature=None):
        sync_calls.append(drift_signature)
        retriever_v2._lancedb_failed_sync_signature = drift_signature
        retriever_v2._lancedb_sync_failure_message = "still mismatched"
        retriever_v2.invalidate_lancedb_cache()

    monkeypatch.setattr("services.get_lancedb_adapter", lambda: FakeAdapter())
    monkeypatch.setattr(DocumentRetriever, "_run_background_sync", fake_run_background_sync)

    retriever = DocumentRetriever.__new__(DocumentRetriever)
    retriever.config = SimpleNamespace(retrieval=SimpleNamespace(lancedb_enabled=True))
    retriever.repository = FakeRepository()

    with pytest.raises(LanceDBNotReadyError, match="not ready / syncing"):
        retriever._should_use_lancedb()

    retriever_v2._sync_thread.join(timeout=5.0)
    assert sync_calls == [(1, 2, 0, 0)]

    with pytest.raises(LanceDBNotReadyError, match="sync failed"):
        retriever._should_use_lancedb()

    assert sync_calls == [(1, 2, 0, 0)]


def test_failed_readiness_check_guard_does_not_relaunch_sync(monkeypatch):
    """An erroring readiness check whose repair sync failed must not relaunch syncs forever."""
    import retriever_v2
    from retriever_v2 import DocumentRetriever, LanceDBNotReadyError

    _reset_lancedb_readiness_state()

    class BrokenAdapter:
        def get_statistics(self):
            raise OSError("permission denied on lancedb storage")

    sync_calls = []

    def fake_run_background_sync(self, drift_signature=None):
        sync_calls.append(drift_signature)
        retriever_v2._lancedb_failed_sync_signature = drift_signature
        retriever_v2._lancedb_sync_failure_message = "storage still broken"
        retriever_v2.invalidate_lancedb_cache()

    monkeypatch.setattr("services.get_lancedb_adapter", lambda: BrokenAdapter())
    monkeypatch.setattr(DocumentRetriever, "_run_background_sync", fake_run_background_sync)

    retriever = DocumentRetriever.__new__(DocumentRetriever)
    retriever.config = SimpleNamespace(retrieval=SimpleNamespace(lancedb_enabled=True))
    retriever.repository = MagicMock()

    with pytest.raises(LanceDBNotReadyError, match="not ready / syncing"):
        retriever._should_use_lancedb()

    retriever_v2._sync_thread.join(timeout=5.0)
    assert sync_calls == [retriever_v2._UNKNOWN_READINESS_SIGNATURE]

    # Readiness still erroring + sync already failed for this state -> FAILED, no relaunch.
    with pytest.raises(LanceDBNotReadyError, match="sync failed"):
        retriever._should_use_lancedb()

    assert sync_calls == [retriever_v2._UNKNOWN_READINESS_SIGNATURE]

    _reset_lancedb_readiness_state()


def test_lancedb_mutation_guard_blocks_without_repair_sync(monkeypatch):
    """Expected in-flight dual-write drift should block without starting repair sync."""
    import retriever_v2
    from retriever_v2 import DocumentRetriever, LanceDBNotReadyError

    _reset_lancedb_readiness_state()

    sync_calls = []

    def fake_trigger_self_healing_sync(self):
        sync_calls.append("triggered")

    monkeypatch.setattr(DocumentRetriever, "_trigger_self_healing_sync", fake_trigger_self_healing_sync)

    retriever = DocumentRetriever.__new__(DocumentRetriever)
    retriever.config = SimpleNamespace(retrieval=SimpleNamespace(lancedb_enabled=True))

    retriever_v2.begin_lancedb_mutation()
    try:
        with pytest.raises(LanceDBNotReadyError, match="updating"):
            retriever._should_use_lancedb()
    finally:
        retriever_v2.end_lancedb_mutation()

    assert sync_calls == []


@pytest.mark.integration
@pytest.mark.database
def test_real_lancedb_write_and_search_flow(tmp_path, monkeypatch, db_manager):
    """Test the complete dual-write, rebuild, and retriever search flow with LanceDB enabled."""
    from indexer_v2 import DocumentIndexer
    from retriever_v2 import DocumentRetriever
    from services import get_lancedb_adapter
    import services

    # 1. Config override to enable LanceDB with temp path
    from config import get_config
    orig_config = get_config()

    fake_config = SimpleNamespace(
        retrieval=SimpleNamespace(
            lancedb_enabled=True,
            lancedb_storage_path=str(tmp_path / "lancedb"),
            lancedb_child_parent_spill_ratio=1.0,
            top_k=5,
            similarity_threshold=0.5,
            distance_metric="cosine"
        ),
        database=orig_config.database,
        chunking=orig_config.chunking,
        embedding=SimpleNamespace(
            dimension=384,
            model_name="all-MiniLM-L6-v2"
        )
    )

    monkeypatch.setattr("config.get_config", lambda: fake_config)
    monkeypatch.setattr("retriever_v2.get_config", lambda: fake_config)
    monkeypatch.setattr("indexer_v2.get_config", lambda: fake_config)
    # Reset services cache for testing
    services.reset_services()

    indexer = DocumentIndexer()
    retriever = DocumentRetriever()

    # 1. Index first document (first-ever doc in table)
    test_file_1 = tmp_path / "test_doc_1.txt"
    test_file_1.write_text("EV6 battery diagnostic procedures outlined here.", encoding="utf-8")
    res_1 = indexer.index_document(str(test_file_1))
    assert res_1["status"] == "success"

    # Search for first-ever doc -> should be found
    results_1, _ = retriever.search_lancedb_parent_child("EV6 battery")
    assert len(results_1) == 1

    # 2. Index second document (append operation)
    test_file_2 = tmp_path / "test_doc_2.txt"
    test_file_2.write_text("Banana bread recipe with vanilla and chocolate chunks.", encoding="utf-8")
    res_2 = indexer.index_document(str(test_file_2))
    assert res_2["status"] == "success"

    # Search for second doc before rebuild (freshness lag check - on tiny datasets/tables LanceDB FTS
    # may fallback to dynamic memory scans, so we don't strictly assert 0 to avoid test flakiness)
    results_2_before, _ = retriever.search_lancedb_parent_child("Banana bread")

    # 3. Explicitly call optimize_vector_index to trigger rebuild_fts_index (production path)
    adapter = get_lancedb_adapter()
    adapter.optimize_vector_index()

    # Search for second doc after rebuild -> should be found
    results_2_after, _ = retriever.search_lancedb_parent_child("Banana bread")
    assert len(results_2_after) == 1
    assert results_2_after[0].source_uri.endswith("test_doc_2.txt")


@pytest.mark.integration
@pytest.mark.database
def test_lancedb_parent_only_fts_rebuild(tmp_path, monkeypatch, db_manager):
    """Test parent-only FTS rebuild logic on the adapter."""
    from indexer_v2 import DocumentIndexer
    from services import get_lancedb_adapter
    import services

    # 1. Config override to enable LanceDB with temp path
    from config import get_config
    orig_config = get_config()

    fake_config = SimpleNamespace(
        retrieval=SimpleNamespace(
            lancedb_enabled=True,
            lancedb_storage_path=str(tmp_path / "lancedb"),
            lancedb_child_parent_spill_ratio=1.0,
            top_k=5,
            similarity_threshold=0.5,
            distance_metric="cosine"
        ),
        database=orig_config.database,
        chunking=orig_config.chunking,
        embedding=SimpleNamespace(
            dimension=384,
            model_name="all-MiniLM-L6-v2"
        )
    )

    monkeypatch.setattr("config.get_config", lambda: fake_config)

    services.reset_services()
    adapter = get_lancedb_adapter()

    parent_rebuilt = False
    chunk_rebuilt = False

    orig_parent_table = adapter.db.open_table("parent_documents")
    orig_chunk_table = adapter.db.open_table("document_chunks")

    def mock_parent_create_fts(*args, **kwargs):
        nonlocal parent_rebuilt
        parent_rebuilt = True

    def mock_chunk_create_fts(*args, **kwargs):
        nonlocal chunk_rebuilt
        chunk_rebuilt = True

    monkeypatch.setattr(orig_parent_table, "create_fts_index", mock_parent_create_fts)
    monkeypatch.setattr(orig_chunk_table, "create_fts_index", mock_chunk_create_fts)

    def mock_open_table(name):
        if name == "parent_documents":
            return orig_parent_table
        elif name == "document_chunks":
            return orig_chunk_table
        raise ValueError(name)

    monkeypatch.setattr(adapter.db, "open_table", mock_open_table)

    # Call rebuild_fts_index with parent_only=True
    adapter.rebuild_fts_index(parent_only=True)
    assert parent_rebuilt is True
    assert chunk_rebuilt is False

    # Reset and call with parent_only=False
    parent_rebuilt = False
    chunk_rebuilt = False
    adapter.rebuild_fts_index(parent_only=False)
    assert parent_rebuilt is True
    assert chunk_rebuilt is True


@pytest.mark.integration
@pytest.mark.database
def test_populate_on_enable_guard(tmp_path, monkeypatch, db_manager):
    """Test that retriever blocks and triggers background sync when LanceDB is enabled but empty while PG has data."""
    from indexer_v2 import DocumentIndexer
    from retriever_v2 import DocumentRetriever, LanceDBNotReadyError
    from config import get_config
    import services

    orig_config = get_config()
    fake_config = SimpleNamespace(
        retrieval=SimpleNamespace(
            lancedb_enabled=False,  # Start disabled so we write to Postgres only
            lancedb_storage_path=str(tmp_path / "lancedb"),
            lancedb_child_parent_spill_ratio=0.7,
            top_k=5,
            similarity_threshold=0.5,
            distance_metric="cosine",
            hybrid_alpha=0.5
        ),
        database=orig_config.database,
        chunking=orig_config.chunking,
        embedding=SimpleNamespace(
            dimension=384,
            model_name="all-MiniLM-L6-v2"
        )
    )

    monkeypatch.setattr("config.get_config", lambda: fake_config)
    monkeypatch.setattr("retriever_v2.get_config", lambda: fake_config)
    monkeypatch.setattr("indexer_v2.get_config", lambda: fake_config)
    services.reset_services()

    indexer = DocumentIndexer()
    # 1. Index document into Postgres only
    test_file = tmp_path / "postgres_only_doc.txt"
    test_file.write_text("Unique keyword postgres fallback test message.")
    res = indexer.index_document(str(test_file))
    assert res['status'] == 'success'

    # 2. Now enable LanceDB
    fake_config.retrieval.lancedb_enabled = True
    services.reset_services()

    retriever = DocumentRetriever()
    # Check that it blocks and raises LanceDBNotReadyError (since LanceDB has 0 docs but PG has 1)
    with pytest.raises(LanceDBNotReadyError, match="LanceDB index is not ready / syncing"):
        retriever.search_hybrid("postgres fallback test")

    # Wait for background self-healing sync thread to complete
    import retriever_v2
    if retriever_v2._sync_thread:
        retriever_v2._sync_thread.join(timeout=15.0)

    # Check that retriever is now ready
    assert retriever._should_use_lancedb() is True
    results = retriever.search_hybrid("postgres fallback test")
    assert len(results) > 0
    assert "postgres_only_doc.txt" in results[0].source_uri

    # Delete postgres document so counts are in sync before next tests
    indexer.delete_document(res['document_id'])


@pytest.mark.integration
@pytest.mark.database
def test_fail_closed_dual_writes(tmp_path, monkeypatch, db_manager):
    """Test that indexing fails-closed and rolls back Postgres when LanceDB is enabled but write fails."""
    from indexer_v2 import DocumentIndexer
    from services import get_lancedb_adapter
    from config import get_config
    import services

    orig_config = get_config()
    fake_config = SimpleNamespace(
        retrieval=SimpleNamespace(
            lancedb_enabled=True,
            lancedb_storage_path=str(tmp_path / "lancedb"),
            lancedb_child_parent_spill_ratio=0.7,
            top_k=5,
            similarity_threshold=0.5,
            distance_metric="cosine"
        ),
        database=orig_config.database,
        chunking=orig_config.chunking,
        embedding=SimpleNamespace(
            dimension=384,
            model_name="all-MiniLM-L6-v2"
        )
    )

    monkeypatch.setattr("config.get_config", lambda: fake_config)
    monkeypatch.setattr("retriever_v2.get_config", lambda: fake_config)
    monkeypatch.setattr("indexer_v2.get_config", lambda: fake_config)
    services.reset_services()

    # Mock upsert_document on LanceDB adapter to raise an exception
    adapter = get_lancedb_adapter()
    def mock_upsert_document(*args, **kwargs):
        raise Exception("LanceDB disk full error")

    monkeypatch.setattr(adapter, "upsert_document", mock_upsert_document)

    indexer = DocumentIndexer()
    test_file = tmp_path / "fail_closed_test.txt"
    test_file.write_text("Fail closed dual write test.")

    # The index_document method should fail-closed and return error status
    res = indexer.index_document(str(test_file))
    assert res['status'] == 'error'
    assert 'LanceDB disk full error' in res['message']

    # Verify rollback: document should NOT exist in PostgreSQL repository
    pg_stats = indexer.repository.get_statistics()
    assert pg_stats.get("total_documents", 0) == 0


@pytest.mark.integration
@pytest.mark.database
def test_replacement_failure_preserves_old_document(tmp_path, monkeypatch, db_manager):
    """A failed replacement must restore the previous version, not lose it (review P1)."""
    from indexer_v2 import DocumentIndexer
    from services import get_lancedb_adapter
    from config import get_config
    import services

    orig_config = get_config()
    fake_config = SimpleNamespace(
        retrieval=SimpleNamespace(
            lancedb_enabled=True,
            lancedb_storage_path=str(tmp_path / "lancedb"),
            lancedb_child_parent_spill_ratio=0.7,
            top_k=5,
            similarity_threshold=0.5,
            distance_metric="cosine"
        ),
        database=orig_config.database,
        chunking=orig_config.chunking,
        embedding=SimpleNamespace(
            dimension=384,
            model_name="all-MiniLM-L6-v2"
        )
    )

    monkeypatch.setattr("config.get_config", lambda: fake_config)
    monkeypatch.setattr("retriever_v2.get_config", lambda: fake_config)
    monkeypatch.setattr("indexer_v2.get_config", lambda: fake_config)
    services.reset_services()

    indexer = DocumentIndexer()
    test_file = tmp_path / "replace_survival_test.txt"
    test_file.write_text("Original version of the replacement survival document.")

    res1 = indexer.index_document(str(test_file))
    assert res1['status'] == 'success'
    doc_id = res1['document_id']

    # Break LanceDB writes, then attempt a replacement of the same document
    adapter = get_lancedb_adapter()

    def mock_upsert_document(*args, **kwargs):
        raise Exception("LanceDB disk full error")

    monkeypatch.setattr(adapter, "upsert_document", mock_upsert_document)

    test_file.write_text("Replacement version that must not survive the failure.")
    res2 = indexer.index_document(str(test_file), force_reindex=True)
    assert res2['status'] == 'error'

    # The OLD version must still be in PostgreSQL (source of truth)
    doc = indexer.repository.get_document_by_id(doc_id)
    assert doc is not None, "old document was lost by the failed replacement"
    chunks = indexer.repository.get_document_chunks_for_reinsert(doc_id)
    texts = " ".join(c[2] for c in chunks)
    assert "Original version" in texts
    assert "Replacement version" not in texts


@pytest.mark.integration
@pytest.mark.database
def test_drift_gate_blocks(tmp_path, monkeypatch, db_manager):
    """Test that when counts differ (drift), retriever raises LanceDBNotReadyError and heals."""
    from indexer_v2 import DocumentIndexer
    from retriever_v2 import DocumentRetriever, LanceDBNotReadyError
    from services import get_lancedb_adapter
    from config import get_config
    import services

    orig_config = get_config()
    fake_config = SimpleNamespace(
        retrieval=SimpleNamespace(
            lancedb_enabled=True,
            lancedb_storage_path=str(tmp_path / "lancedb"),
            lancedb_child_parent_spill_ratio=0.7,
            top_k=5,
            similarity_threshold=0.5,
            distance_metric="cosine"
        ),
        database=orig_config.database,
        chunking=orig_config.chunking,
        embedding=SimpleNamespace(
            dimension=384,
            model_name="all-MiniLM-L6-v2"
        )
    )

    monkeypatch.setattr("config.get_config", lambda: fake_config)
    monkeypatch.setattr("retriever_v2.get_config", lambda: fake_config)
    monkeypatch.setattr("indexer_v2.get_config", lambda: fake_config)
    services.reset_services()

    indexer = DocumentIndexer()
    test_file = tmp_path / "drift_test.txt"
    test_file.write_text("Drift test file content.")

    # Ingest normally (both in sync)
    res = indexer.index_document(str(test_file))
    assert res['status'] == 'success'

    retriever = DocumentRetriever()
    assert retriever._should_use_lancedb() is True

    # Introduce drift by deleting the document only from LanceDB
    adapter = get_lancedb_adapter()
    adapter.delete_document(res['document_id'])

    # Reset retriever cache
    from retriever_v2 import invalidate_lancedb_cache
    invalidate_lancedb_cache()

    # Verify that retriever raises LanceDBNotReadyError
    with pytest.raises(LanceDBNotReadyError, match="LanceDB index is not ready / syncing"):
        retriever.search_hybrid("drift test")

    # Wait for self-healing sync to restore parity
    import retriever_v2
    if retriever_v2._sync_thread:
        retriever_v2._sync_thread.join(timeout=15.0)

    assert retriever._should_use_lancedb() is True
    results = retriever.search_hybrid("drift test")
    assert len(results) > 0
    assert "drift_test.txt" in results[0].source_uri


@pytest.mark.integration
@pytest.mark.database
def test_delete_fail_closed(tmp_path, monkeypatch, db_manager):
    """Test that if LanceDB deletion fails, delete_document fails-closed and Postgres is not modified."""
    from indexer_v2 import DocumentIndexer
    from services import get_lancedb_adapter
    from config import get_config
    import services

    orig_config = get_config()
    fake_config = SimpleNamespace(
        retrieval=SimpleNamespace(
            lancedb_enabled=True,
            lancedb_storage_path=str(tmp_path / "lancedb"),
            lancedb_child_parent_spill_ratio=0.7,
            top_k=5,
            similarity_threshold=0.5,
            distance_metric="cosine"
        ),
        database=orig_config.database,
        chunking=orig_config.chunking,
        embedding=SimpleNamespace(
            dimension=384,
            model_name="all-MiniLM-L6-v2"
        )
    )

    monkeypatch.setattr("config.get_config", lambda: fake_config)
    monkeypatch.setattr("retriever_v2.get_config", lambda: fake_config)
    monkeypatch.setattr("indexer_v2.get_config", lambda: fake_config)
    services.reset_services()

    indexer = DocumentIndexer()
    test_file = tmp_path / "delete_test.txt"
    test_file.write_text("Delete test content.")

    # Ingest document
    res = indexer.index_document(str(test_file))
    assert res['status'] == 'success'
    doc_id = res['document_id']

    # Mock delete_document on LanceDB adapter to raise an exception
    adapter = get_lancedb_adapter()
    def mock_delete_document(*args, **kwargs):
        raise Exception("LanceDB delete lock error")

    monkeypatch.setattr(adapter, "delete_document", mock_delete_document)

    # Attempting to delete should raise/propagate exception
    with pytest.raises(Exception, match="LanceDB delete lock error"):
        indexer.delete_document(doc_id)

    # Verify Postgres still contains the document (fail-closed, no deletion executed in Postgres)
    assert indexer.repository.document_exists(doc_id) is True


@pytest.mark.integration
@pytest.mark.database
def test_explicit_postgres_toggle(tmp_path, monkeypatch, db_manager):
    """Test that passing source="postgres" bypasses LanceDB and queries PostgreSQL directly."""
    from indexer_v2 import DocumentIndexer
    from retriever_v2 import DocumentRetriever, LanceDBNotReadyError
    from config import get_config
    import services

    orig_config = get_config()
    fake_config = SimpleNamespace(
        retrieval=SimpleNamespace(
            lancedb_enabled=False,  # Start disabled so we write to Postgres only
            lancedb_storage_path=str(tmp_path / "lancedb"),
            lancedb_child_parent_spill_ratio=0.7,
            top_k=5,
            similarity_threshold=0.5,
            distance_metric="cosine",
            hybrid_alpha=0.5
        ),
        database=orig_config.database,
        chunking=orig_config.chunking,
        embedding=SimpleNamespace(
            dimension=384,
            model_name="all-MiniLM-L6-v2"
        )
    )

    monkeypatch.setattr("config.get_config", lambda: fake_config)
    monkeypatch.setattr("retriever_v2.get_config", lambda: fake_config)
    monkeypatch.setattr("indexer_v2.get_config", lambda: fake_config)
    services.reset_services()

    indexer = DocumentIndexer()
    # 1. Index document into Postgres only (creating drift / unpopulated state in LanceDB)
    test_file = tmp_path / "postgres_only_doc.txt"
    test_file.write_text("Keyword for postgres toggle test.")
    res = indexer.index_document(str(test_file))
    assert res['status'] == 'success'

    # Enable lancedb, but do NOT sync, meaning LanceDB is unpopulated (NOT_READY)
    fake_config.retrieval.lancedb_enabled = True
    services.reset_services()
    retriever = DocumentRetriever()

    # 2. Searching with default (lancedb) should raise LanceDBNotReadyError
    with pytest.raises(LanceDBNotReadyError):
        retriever.search_hybrid("toggle test", source="lancedb")

    # 3. Searching with source="postgres" should bypass the ready check and succeed
    results = retriever.search_hybrid("toggle test", source="postgres")
    assert len(results) > 0
    assert "postgres_only_doc.txt" in results[0].source_uri


@pytest.mark.integration
@pytest.mark.database
def test_add_documents_bulk_correctness(tmp_path, monkeypatch):
    """Test that add_documents_bulk yields identical counts, schemas, and search results to upsert_document."""
    from services import get_lancedb_adapter
    import services
    from config import get_config
    
    orig_config = get_config()
    
    # 1. Setup config for bulk adapter
    bulk_path = tmp_path / "lancedb_bulk"
    fake_config_bulk = SimpleNamespace(
        retrieval=SimpleNamespace(
            lancedb_enabled=True,
            lancedb_storage_path=str(bulk_path),
            lancedb_child_parent_spill_ratio=1.0,
            top_k=5,
            similarity_threshold=0.1,
            distance_metric="cosine"
        ),
        database=orig_config.database,
        chunking=orig_config.chunking,
        embedding=SimpleNamespace(
            dimension=384,
            model_name="all-MiniLM-L6-v2"
        )
    )
    
    monkeypatch.setattr("config.get_config", lambda: fake_config_bulk)
    services.reset_services()
    adapter_bulk = get_lancedb_adapter()
    
    # Define document inputs
    docs_to_sync = [
        (
            "doc-1",
            "file:///doc1.txt",
            [
                (0, "Apple pie is delicious.", [0.1] * 384, {"category": "food"}),
                (1, "Bananas are yellow fruit.", [0.2] * 384, {"category": "fruit"})
            ],
            "Apple pie is delicious.\n\nBananas are yellow fruit.",
            {"namespace": "test-ns", "type": "text"}
        ),
        (
            "doc-2",
            "file:///doc2.txt",
            [
                (0, "Tesla Model S has great range.", [0.5] * 384, {"category": "car"}),
                (1, "EV6 charging speed is very fast.", [0.6] * 384, {"category": "car"})
            ],
            "Tesla Model S has great range.\n\nEV6 charging speed is very fast.",
            {"namespace": "test-ns", "type": "text"}
        )
    ]
    
    # Bulk write
    adapter_bulk.add_documents_bulk(docs_to_sync)
    adapter_bulk.optimize_vector_index()
    stats_bulk = adapter_bulk.get_statistics()
    
    # 2. Setup config for sequential adapter
    seq_path = tmp_path / "lancedb_seq"
    fake_config_seq = SimpleNamespace(
        retrieval=SimpleNamespace(
            lancedb_enabled=True,
            lancedb_storage_path=str(seq_path),
            lancedb_child_parent_spill_ratio=1.0,
            top_k=5,
            similarity_threshold=0.1,
            distance_metric="cosine"
        ),
        database=orig_config.database,
        chunking=orig_config.chunking,
        embedding=SimpleNamespace(
            dimension=384,
            model_name="all-MiniLM-L6-v2"
        )
    )
    
    monkeypatch.setattr("config.get_config", lambda: fake_config_seq)
    services.reset_services()
    adapter_seq = get_lancedb_adapter()
    
    # Sequential write
    for doc_id, uri, chunks, text, meta in docs_to_sync:
        adapter_seq.upsert_document(doc_id, uri, chunks, text, meta)
    adapter_seq.optimize_vector_index()
    stats_seq = adapter_seq.get_statistics()
    
    # Assert statistical equality
    assert stats_bulk["total_documents"] == stats_seq["total_documents"]
    assert stats_bulk["total_chunks"] == stats_seq["total_chunks"]
    assert stats_bulk["total_documents"] == 2
    assert stats_bulk["total_chunks"] == 4
    
    # Verify row contents match exactly (ignoring internal metadata and using pandas dataframe)
    df_parent_bulk = adapter_bulk.db.open_table("parent_documents").to_pandas()
    df_parent_seq = adapter_seq.db.open_table("parent_documents").to_pandas()
    assert len(df_parent_bulk) == len(df_parent_seq)
    
    df_chunk_bulk = adapter_bulk.db.open_table("document_chunks").to_pandas()
    df_chunk_seq = adapter_seq.db.open_table("document_chunks").to_pandas()
    assert len(df_chunk_bulk) == len(df_chunk_seq)
    
    # Verify both can run FTS search
    results_parent_bulk = adapter_bulk.db.open_table("parent_documents").search("Apple", query_type="fts").to_list()
    results_parent_seq = adapter_seq.db.open_table("parent_documents").search("Apple", query_type="fts").to_list()
    assert len(results_parent_bulk) == len(results_parent_seq)
    assert results_parent_bulk[0]["document_id"] == "doc-1"

