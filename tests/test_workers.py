import pytest

# Mark all tests in this file as slow (UI tests with QApplication)
pytestmark = pytest.mark.slow
from unittest.mock import MagicMock, call
from pathlib import Path
from PySide6.QtWidgets import QApplication

from desktop_app.ui.workers import (
    DocumentsWorker,
    LocalLanceDBIngestWorker,
    LocalLanceDBSearchWorker,
    SearchWorker,
    UploadWorker,
    clear_lancedb_embedder_cache,
    get_lancedb_embedder,
)

@pytest.fixture(scope="session")
def qapp():
    """Create the QApplication instance for the test session."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

@pytest.fixture
def mock_api_client():
    return MagicMock()

def test_search_worker_success(qapp, mock_api_client):
    """Test SearchWorker emits results on success."""
    mock_api_client.search.return_value = [{"id": "1"}]
    
    worker = SearchWorker(
        mock_api_client, 
        query="test", 
        top_k=5, 
        min_score=0.5, 
        metric="cosine"
    )
    
    # Connect signal
    results = []
    worker.finished.connect(lambda success, data: results.append((success, data)))
    
    # Run synchronously
    worker.run()
    
    assert len(results) == 1
    success, data = results[0]
    assert success is True
    assert data == [{"id": "1"}]
    mock_api_client.search.assert_called_once()
    assert mock_api_client.search.call_args.kwargs["group_by_document"] is False
    assert mock_api_client.search.call_args.kwargs["literal_tail_suppression"] is None


def test_search_worker_passes_document_level_options(qapp, mock_api_client):
    """SearchWorker passes backend document-grouping options when enabled."""
    mock_api_client.search.return_value = [{"id": "1"}]

    worker = SearchWorker(
        mock_api_client,
        query="EV6",
        top_k=5,
        min_score=0.3,
        metric="cosine",
        group_by_document=True,
        literal_tail_suppression="identifier-token",
    )

    results = []
    worker.finished.connect(lambda success, data: results.append((success, data)))

    worker.run()

    assert results == [(True, [{"id": "1"}])]
    assert mock_api_client.search.call_args.kwargs["group_by_document"] is True
    assert mock_api_client.search.call_args.kwargs["literal_tail_suppression"] == "identifier-token"


def test_lancedb_embedder_cache_reuses_model(monkeypatch):
    from desktop_app import lancedb_engine

    created = []

    class FakeEmbedder:
        def __init__(self, model_name):
            self.model_name = model_name
            created.append(model_name)

    monkeypatch.setattr(lancedb_engine, "SentenceTransformerEmbedder", FakeEmbedder)
    clear_lancedb_embedder_cache()

    first = get_lancedb_embedder("model-a")
    second = get_lancedb_embedder("model-a")
    third = get_lancedb_embedder("model-b")

    assert first is second
    assert third is not first
    assert created == ["model-a", "model-b"]

    clear_lancedb_embedder_cache()


def test_local_lancedb_search_worker_uses_cached_embedder(qapp, monkeypatch):
    from desktop_app import lancedb_engine

    cached_embedder = object()
    captured = {}

    class FakeEngine:
        def __init__(self, db_path, embedder=None):
            captured["db_path"] = db_path
            captured["embedder"] = embedder

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def search_parent_child(self, query, parent_limit, child_limit):
            captured["query"] = query
            captured["parent_limit"] = parent_limit
            captured["child_limit"] = child_limit
            result = MagicMock(
                score=0.9,
                source_uri="/docs/ev6.txt",
                text="EV6 result",
                chunk_index=0,
                score_label="Cosine similarity: 0.9000",
                parent_rank=1,
            )
            return [result], None

    monkeypatch.setattr("desktop_app.ui.workers.get_lancedb_embedder", lambda: cached_embedder)
    monkeypatch.setattr(lancedb_engine, "LocalLanceDBEngine", FakeEngine)

    worker = LocalLanceDBSearchWorker("EV6", 5, "/tmp/lancedb", parent_limit=2)
    results = []
    worker.finished.connect(lambda success, data: results.append((success, data)))

    worker.run()

    assert captured == {
        "db_path": "/tmp/lancedb",
        "embedder": cached_embedder,
        "query": "EV6",
        "parent_limit": 2,
        "child_limit": 5,
    }
    assert results[0][0] is True
    assert results[0][1][0]["source_uri"] == "/docs/ev6.txt"


def test_local_lancedb_ingest_worker_uses_cached_embedder(qapp, monkeypatch):
    from desktop_app import lancedb_engine, lancedb_ingestion

    cached_embedder = object()
    captured = {}

    class FakeEngine:
        def __init__(self, db_path, embedder=None):
            captured["db_path"] = db_path
            captured["embedder"] = embedder

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

    class FakeResult:
        def to_dict(self):
            return {"indexed_documents": 1}

    def fake_ingest(engine, paths, recursive=True):
        captured["engine"] = engine
        captured["paths"] = paths
        captured["recursive"] = recursive
        return FakeResult()

    monkeypatch.setattr("desktop_app.ui.workers.get_lancedb_embedder", lambda: cached_embedder)
    monkeypatch.setattr(lancedb_engine, "LocalLanceDBEngine", FakeEngine)
    monkeypatch.setattr(lancedb_ingestion, "ingest_local_text_paths", fake_ingest)

    worker = LocalLanceDBIngestWorker(["/docs"], "/tmp/lancedb", recursive=False)
    results = []
    worker.finished.connect(lambda success, data: results.append((success, data)))

    worker.run()

    assert captured["db_path"] == "/tmp/lancedb"
    assert captured["embedder"] is cached_embedder
    assert captured["paths"] == ["/docs"]
    assert captured["recursive"] is False
    assert results == [(True, {"indexed_documents": 1})]


def test_search_worker_failure(qapp, mock_api_client):
    """Test SearchWorker emits error on failure."""
    mock_api_client.search.side_effect = Exception("Search failed")
    
    worker = SearchWorker(
        mock_api_client, 
        query="test", 
        top_k=5, 
        min_score=0.5, 
        metric="cosine"
    )
    
    results = []
    worker.finished.connect(lambda success, data: results.append((success, data)))
    
    worker.run()
    
    assert len(results) == 1
    success, error = results[0]
    assert success is False
    assert "Search failed" in str(error)

def test_documents_worker_success(qapp, mock_api_client):
    """Test DocumentsWorker emits results on success."""
    mock_data = {"items": [], "total": 0}
    mock_api_client.list_documents.return_value = mock_data
    
    worker = DocumentsWorker(mock_api_client, params={"limit": 10})
    
    results = []
    worker.finished.connect(lambda success, data: results.append((success, data)))
    
    worker.run()
    
    assert len(results) == 1
    success, data = results[0]
    assert success is True
    assert data == mock_data

def test_upload_worker_workflow(qapp, mock_api_client):
    """Test UploadWorker processes files and emits signals."""
    files_data = [
        {
            "path": Path("file1.txt"),
            "full_path": "/path/file1.txt",
            "force_reindex": False,
            "document_type": None
        },
        {
            "path": Path("file2.txt"),
            "full_path": "/path/file2.txt",
            "force_reindex": True,
            "document_type": "resume"
        }
    ]
    
    # Mock get_document_metadata to return None (so it proceeds to upload without hash check)
    mock_api_client.get_document_metadata.return_value = None
    
    worker = UploadWorker(mock_api_client, files_data)
    
    # Track signals
    file_finished_signals = []
    all_finished_signals = []
    
    worker.file_finished.connect(lambda i, s, m: file_finished_signals.append((i, s, m)))
    worker.all_finished.connect(lambda: all_finished_signals.append(True))
    
    worker.run()
    
    # Verify signals - both files should have finished (though may have failed)
    assert len(file_finished_signals) == 2
    assert len(all_finished_signals) == 1
    
    # Verify API calls - at least upload_document should be called for both files
    # (first file: no existing doc, so upload; second file: force_reindex so upload)
    assert mock_api_client.upload_document.call_count == 2

def test_upload_worker_cancellation(qapp, mock_api_client):
    """Test UploadWorker stops when cancelled."""
    files_data = [
        {"path": Path("f1"), "full_path": "f1", "force_reindex": False},
        {"path": Path("f2"), "full_path": "f2", "force_reindex": False}
    ]
    
    worker = UploadWorker(mock_api_client, files_data)
    
    # Cancel immediately
    worker.cancel()
    
    file_finished_signals = []
    worker.file_finished.connect(lambda i, s, m: file_finished_signals.append((i, s, m)))
    
    worker.run()
    
    # Should not process any files
    assert len(file_finished_signals) == 0
    assert mock_api_client.upload_document.call_count == 0
