"""
Tests for filtering bugs found during user testing.
These tests should FAIL initially, demonstrating the bugs.
"""

import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import tempfile
from api import app


class TestDocumentTypeUpload:
    """Test that document_type is properly saved during upload."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)
    
    def test_upload_with_document_type_saves_to_db(self, client, setup_test_database):
        """Test that document_type parameter is saved to metadata."""
        # Create a test file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("This is a test resume document about principal architect.")
            temp_path = Path(f.name)
        
        try:
            # Upload with document_type
            with open(temp_path, 'rb') as f:
                response = client.post(
                    "/upload-and-index",
                    files={"file": (temp_path.name, f, "text/plain")},
                    data={"document_type": "resume"}
                )
            
            assert response.status_code == 200
            data = response.json()
            document_id = data["document_id"]
            
            # Verify document_type is in metadata by searching with type filter
            search_response = client.post(
                "/search",
                json={
                    "query": "principal architect",
                    "top_k": 5,
                    "min_score": 0.0,
                    "filters": {"type": "resume"}
                }
            )
            
            assert search_response.status_code == 200
            search_data = search_response.json()
            assert len(search_data["results"]) > 0, "Should find document with type filter"
            
            # Verify the document has the correct type in metadata
            result = search_data["results"][0]
            assert result["document_id"] == document_id
            # Check if metadata contains type
            # Note: This assumes the API returns metadata in results
            
        finally:
            temp_path.unlink(missing_ok=True)
    
    def test_search_with_type_filter_returns_results(self, client, setup_test_database):
        """Test that searching with type filter returns matching documents."""
        # Upload a document with type
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Principal architect job description.")
            temp_path = Path(f.name)
        
        try:
            with open(temp_path, 'rb') as f:
                upload_response = client.post(
                    "/upload-and-index",
                    files={"file": (temp_path.name, f, "text/plain")},
                    data={"document_type": "resume"}
                )
            
            assert upload_response.status_code == 200
            
            # Search WITH type filter - should find it
            search_with_filter = client.post(
                "/search",
                json={
                    "query": "principal architect",
                    "top_k": 5,
                    "min_score": 0.0,
                    "filters": {"type": "resume"}
                }
            )
            
            assert search_with_filter.status_code == 200
            results_with_filter = search_with_filter.json()["results"]
            
            # Search WITHOUT type filter - should also find it
            search_without_filter = client.post(
                "/search",
                json={
                    "query": "principal architect",
                    "top_k": 5,
                    "min_score": 0.0
                }
            )
            
            assert search_without_filter.status_code == 200
            results_without_filter = search_without_filter.json()["results"]
            
            # Both should return results
            assert len(results_with_filter) > 0, "Search WITH type filter should return results"
            assert len(results_without_filter) > 0, "Search WITHOUT type filter should return results"
            
        finally:
            temp_path.unlink(missing_ok=True)


class TestBulkDeleteAPI:
    """Test bulk delete API endpoint."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)
    
    def test_bulk_delete_preview_endpoint_exists(self, client, setup_test_database):
        """Test that bulk-delete endpoint accepts POST requests."""
        # Try to preview delete with a filter
        response = client.post(
            "/documents/bulk-delete",
            json={
                "filters": {"type": "test"},
                "preview": True
            }
        )
        
        # Should not return 405 Method Not Allowed
        assert response.status_code != 405, "bulk-delete endpoint should accept POST"
        # Should return 200 (even if no documents match)
        assert response.status_code == 200
    
    def test_bulk_delete_preview_with_type_filter(self, client, setup_test_database):
        """Test bulk delete preview with document type filter."""
        # Upload a test document
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test document for deletion.")
            temp_path = Path(f.name)
        
        try:
            with open(temp_path, 'rb') as f:
                upload_response = client.post(
                    "/upload-and-index",
                    files={"file": (temp_path.name, f, "text/plain")},
                    data={"document_type": "draft"}
                )
            
            assert upload_response.status_code == 200
            
            # Preview delete with type filter
            preview_response = client.post(
                "/documents/bulk-delete",
                json={
                    "filters": {"type": "draft"},
                    "preview": True
                }
            )
            
            assert preview_response.status_code == 200
            preview_data = preview_response.json()
            assert "document_count" in preview_data
            assert preview_data["document_count"] > 0, "Should find documents to delete"
            
        finally:
            temp_path.unlink(missing_ok=True)


class TestDocumentsListAPI:
    """Test that documents list includes document_type."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)
    
    def test_list_documents_includes_document_type(self, client, setup_test_database):
        """Test that /documents endpoint returns document_type field."""
        # Upload a document with type
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test document with type.")
            temp_path = Path(f.name)
        
        try:
            with open(temp_path, 'rb') as f:
                upload_response = client.post(
                    "/upload-and-index",
                    files={"file": (temp_path.name, f, "text/plain")},
                    data={"document_type": "policy"}
                )
            
            assert upload_response.status_code == 200
            document_id = upload_response.json()["document_id"]
            
            # List documents
            list_response = client.get("/documents")
            assert list_response.status_code == 200
            
            documents = list_response.json()  # Returns list directly, not wrapped
            assert len(documents) > 0
            
            # Find our document
            our_doc = next((d for d in documents if d["document_id"] == document_id), None)
            assert our_doc is not None, "Should find uploaded document in list"
            
            # Check if document_type field exists
            assert "document_type" in our_doc, "Document should have document_type field"
            assert our_doc["document_type"] == "policy", "Document type should match uploaded value"
            
        finally:
            temp_path.unlink(missing_ok=True)
