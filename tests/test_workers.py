import pytest

# Mark all tests in this file as slow (UI tests with QApplication)
pytestmark = pytest.mark.slow
from unittest.mock import MagicMock, call
from pathlib import Path
from PySide6.QtWidgets import QApplication

from desktop_app.ui.workers import SearchWorker, DocumentsWorker, UploadWorker

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
