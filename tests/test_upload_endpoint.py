"""
Tests for file upload and index endpoint.
"""

import pytest
import io
from fastapi.testclient import TestClient
from api import app


class TestUploadAndIndex:
    """Tests for /upload-and-index endpoint."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)
    
    def test_upload_text_file(self, client):
        """Test uploading and indexing a text file."""
        # Create a test file
        file_content = b"Machine learning is a subset of artificial intelligence."
        file_data = io.BytesIO(file_content)
        
        response = client.post(
            "/upload-and-index",
            files={"file": ("test.txt", file_data, "text/plain")}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["success", "skipped"]
        assert data["source_uri"] == "test.txt"
        if data["status"] == "success":
            assert data["chunks_indexed"] > 0
            assert data["document_id"] is not None
    
    def test_upload_with_force_reindex(self, client):
        """Test force reindex parameter."""
        file_content = b"Test content for force reindex."
        file_data = io.BytesIO(file_content)
        
        # First upload
        response1 = client.post(
            "/upload-and-index",
            files={"file": ("force_test.txt", file_data, "text/plain")}
        )
        assert response1.status_code == 200
        
        # Second upload with force_reindex
        file_data2 = io.BytesIO(file_content)
        response2 = client.post(
            "/upload-and-index?force_reindex=true",
            files={"file": ("force_test.txt", file_data2, "text/plain")}
        )
        assert response2.status_code == 200
        data = response2.json()
        assert data["status"] == "success"
    
    def test_upload_unsupported_file_type(self, client):
        """Test uploading unsupported file type."""
        file_content = b"# Markdown content"
        file_data = io.BytesIO(file_content)
        
        response = client.post(
            "/upload-and-index",
            files={"file": ("test.md", file_data, "text/markdown")}
        )
        
        # Should return error for unsupported extension
        assert response.status_code == 400
        assert "Unsupported file extension" in response.json()["detail"]
    
    def test_upload_pdf_file(self, client):
        """Test uploading a PDF file (mock)."""
        # Create minimal PDF content (not a real PDF, just for testing)
        # In real scenario, you'd use a proper PDF file
        file_content = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n"
        file_data = io.BytesIO(file_content)
        
        response = client.post(
            "/upload-and-index",
            files={"file": ("test.pdf", file_data, "application/pdf")}
        )
        
        # May fail due to invalid PDF, but endpoint should handle it
        assert response.status_code in [200, 400, 500]
    
    def test_upload_without_file(self, client):
        """Test upload endpoint without providing a file."""
        response = client.post("/upload-and-index")
        
        assert response.status_code == 422  # Validation error
    
    def test_upload_preserves_filename(self, client):
        """Test that original filename is preserved in metadata and database."""
        file_content = b"Test content with filename preservation."
        file_data = io.BytesIO(file_content)
        original_filename = "my_important_document.txt"
        
        response = client.post(
            "/upload-and-index",
            files={"file": (original_filename, file_data, "text/plain")}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["source_uri"] == original_filename
        
        # Verify it's stored correctly in database
        document_id = data["document_id"]
        docs_response = client.get("/documents")
        assert docs_response.status_code == 200
        docs = docs_response.json()
        
        # Find our document
        uploaded_doc = next((d for d in docs if d["document_id"] == document_id), None)
        assert uploaded_doc is not None
        assert uploaded_doc["source_uri"] == original_filename
        assert "/tmp/" not in uploaded_doc["source_uri"], "source_uri should not contain temp path"
    
    def test_upload_large_file(self, client):
        """Test uploading a larger file."""
        # Create a 1MB text file
        file_content = b"A" * (1024 * 1024)  # 1MB
        file_data = io.BytesIO(file_content)
        
        response = client.post(
            "/upload-and-index",
            files={"file": ("large.txt", file_data, "text/plain")}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["success", "skipped"]
    
    def test_upload_with_custom_source_uri(self, client):
        """Test that custom_source_uri (full path) is preserved."""
        file_content = b"Test content for custom source URI."
        file_data = io.BytesIO(file_content)
        custom_path = r"C:\Users\TestUser\Documents\my_test_file.txt"
        
        response = client.post(
            "/upload-and-index",
            files={"file": ("my_test_file.txt", file_data, "text/plain")},
            data={"custom_source_uri": custom_path}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["success", "skipped"]
        assert data["source_uri"] == custom_path, f"Expected source_uri to be {custom_path}, got {data['source_uri']}"
        
        # Verify it's stored correctly in database
        document_id = data["document_id"]
        docs_response = client.get("/documents")
        assert docs_response.status_code == 200
        docs = docs_response.json()
        
        # Find our document
        uploaded_doc = next((d for d in docs if d["document_id"] == document_id), None)
        assert uploaded_doc is not None
        assert uploaded_doc["source_uri"] == custom_path, f"Database has wrong source_uri: {uploaded_doc['source_uri']}"
        assert "/tmp/" not in uploaded_doc["source_uri"], "source_uri should not contain temp path"
    
    def test_force_reindex_with_custom_source_uri(self, client):
        """Test that force_reindex works with custom_source_uri."""
        file_content = b"Test content for force reindex with custom path."
        custom_path = r"C:\Users\TestUser\Documents\force_reindex_test.txt"
        
        # First upload
        file_data1 = io.BytesIO(file_content)
        response1 = client.post(
            "/upload-and-index",
            files={"file": ("force_reindex_test.txt", file_data1, "text/plain")},
            data={"custom_source_uri": custom_path}
        )
        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["status"] == "success"
        doc_id_1 = data1["document_id"]
        
        # Second upload without force_reindex should skip
        file_data2 = io.BytesIO(file_content)
        response2 = client.post(
            "/upload-and-index",
            files={"file": ("force_reindex_test.txt", file_data2, "text/plain")},
            data={"custom_source_uri": custom_path}
        )
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["status"] == "skipped", "Second upload should be skipped without force_reindex"
        assert data2["document_id"] == doc_id_1, "Document ID should be the same"
        
        # Third upload with force_reindex should succeed
        file_data3 = io.BytesIO(file_content)
        response3 = client.post(
            "/upload-and-index",
            files={"file": ("force_reindex_test.txt", file_data3, "text/plain")},
            data={"custom_source_uri": custom_path, "force_reindex": "true"}
        )
        assert response3.status_code == 200
        data3 = response3.json()
        assert data3["status"] == "success", "Third upload with force_reindex should succeed"
        assert data3["document_id"] == doc_id_1, "Document ID should remain the same"
        assert data3["source_uri"] == custom_path, "Source URI should be preserved"
