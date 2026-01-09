
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from desktop_app.ui.workers import UploadWorker

class TestMetadataUpdateSkip:
    """
    Reproduction test for the issue where metadata updates (like Document Type)
    are ignored if the file content (hash) hasn't changed.
    """

    @pytest.fixture
    def mock_api_client(self):
        return MagicMock()

    def test_upload_skipped_when_hash_matches_but_type_differs(self, mock_api_client):
        """
        Scenario:
        1. User has a file 'resume.pdf' already indexed (Hash: ABC, Type: None/Old).
        2. User selects 'resume.pdf' and sets Type to 'Resume' in the UI.
        3. User clicks Upload.
        
        Expected: Worker should call upload_document to update the type.
        Actual (Bug): Worker sees Hash ABC == ABC and skips, so Type is never updated.
        """
        
        # Setup existing document on server
        mock_doc = {
            'document_id': '123',
            'metadata': {
                'file_hash': 'hash_abc_123',
                'type': 'old_type'  # or None
            }
        }
        mock_api_client.get_document_metadata.return_value = mock_doc
        
        # Setup file to upload (Same Content, New Type)
        files_data = [{
            'path': Path("resume.pdf"),
            'full_path': "/abs/resume.pdf",
            'force_reindex': False,
            'document_type': 'Resume',  # User wants to set this!
        }]
        
        worker = UploadWorker(mock_api_client, files_data)
        
        # Mock hash calculation to match the "remote" hash
        with patch('desktop_app.ui.workers.calculate_file_hash') as mock_hash:
            mock_hash.return_value = 'hash_abc_123'  # MATCHES remote hash
            
            # Capture signals
            results = []
            worker.file_finished.connect(lambda i, success, msg: results.append(msg))
            
            # Run worker
            worker.run()
            
            # --- VERIFICATION ---
            
            # Ideally, we WANT upload_document to be called to update the type.
            # But the bug is that it IS NOT called.
            
            # If the bug exists (and we are reproducing it), this assertion should FAIL 
            # if we assert "called".
            # Or if we want to confirm the bug, we assert "not called".
            
            # Let's assert what *should* happen (it should be called), 
            # so the test FAILS, proving the specific defect.
            
            mock_api_client.upload_document.assert_called()

    def test_force_reindex_set_when_hash_differs(self, mock_api_client):
        """
        Regression test for bug: changed files not re-indexed.
        
        Scenario:
        1. User has a file 'document.txt' already indexed with hash 'old_hash'.
        2. User edits the file locally (hash becomes 'new_hash').
        3. User runs folder indexing WITHOUT checking "Force Reindex".
        
        Expected: Worker should detect hash mismatch and call upload_document 
                  with force_reindex=True so the server actually updates.
        Bug (fixed): Worker was passing force_reindex=False, so server skipped.
        """
        
        # Setup existing document on server with OLD hash
        mock_doc = {
            'document_id': '456',
            'metadata': {
                'file_hash': 'old_hash_from_server',
                'type': None
            }
        }
        mock_api_client.get_document_metadata.return_value = mock_doc
        
        # Setup file to upload (user did NOT check Force Reindex)
        files_data = [{
            'path': Path("document.txt"),
            'full_path': "/abs/document.txt",
            'force_reindex': False,  # User did NOT check "Force Reindex"
            'document_type': None,
        }]
        
        worker = UploadWorker(mock_api_client, files_data)
        
        # Mock hash calculation to return DIFFERENT hash (file was edited)
        with patch('desktop_app.ui.workers.calculate_file_hash') as mock_hash:
            mock_hash.return_value = 'new_hash_after_edit'  # DIFFERS from server
            
            # Run worker
            worker.run()
            
            # --- VERIFICATION ---
            # upload_document MUST be called with force_reindex=True
            # because the hash differs (content changed)
            mock_api_client.upload_document.assert_called_once()
            call_kwargs = mock_api_client.upload_document.call_args.kwargs
            
            assert call_kwargs['force_reindex'] is True, (
                "Bug regression: When hash differs, force_reindex should be True "
                "so the server actually updates the document instead of skipping."
            )

