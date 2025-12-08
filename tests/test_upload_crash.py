
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from desktop_app.ui.workers import UploadWorker

class TestUploadWorkerRegression:
    """Regression tests for UploadWorker."""

    @pytest.fixture
    def mock_api_client(self):
        return MagicMock()

    @pytest.fixture
    def worker(self, mock_api_client):
        files_data = [{
            'path': Path("test.txt"),
            'full_path': "/abs/test.txt",
            'force_reindex': False,
            'document_type': 'resume'
        }]
        return UploadWorker(mock_api_client, files_data)

    def test_handle_none_metadata_safely(self, worker, mock_api_client):
        """
        Test that UploadWorker does not crash when get_document_metadata 
        returns a document with None metadata.
        User reported: 'NoneType' object has no attribute 'get'
        """
        # Mock api_client to return a doc with metadata=None
        mock_doc = {
            'document_id': '123',
            'metadata': None  # This was causing the crash
        }
        mock_api_client.get_document_metadata.return_value = mock_doc
        
        # We also need to mock calculate_file_hash since the code calls it
        with patch('desktop_app.ui.workers.calculate_file_hash') as mock_hash:
            mock_hash.return_value = "new_hash_123"
            
            # Use a slot to capture signals
            finished_signals = []
            worker.file_finished.connect(lambda i, success, msg: finished_signals.append((success, msg)))
            
            # Run the worker logic synchronously (bypass QThread.start)
            worker.run()
            
            # Should have proceeded to upload (because hashes/metadata didn't match validation)
            # causing the upload_document call.
            mock_api_client.upload_document.assert_called()
            
            # Verify we got a success signal (meaning no crash)
            assert len(finished_signals) == 1
            success, msg = finished_signals[0]
            assert success is True
            assert "Upload successful" in msg

    def test_handle_missing_metadata_key_safely(self, worker, mock_api_client):
        """Test safe handling when 'metadata' key is completely missing."""
        mock_doc = {
            'document_id': '123'
             # No 'metadata' key
        }
        mock_api_client.get_document_metadata.return_value = mock_doc
        
        with patch('desktop_app.ui.workers.calculate_file_hash') as mock_hash:
            mock_hash.return_value = "new_hash_123"
            
            finished_signals = []
            worker.file_finished.connect(lambda i, success, msg: finished_signals.append((success, msg)))
            
            worker.run()
            
            mock_api_client.upload_document.assert_called()
            assert len(finished_signals) == 1
            assert finished_signals[0][0] is True
