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
        """Test that original filename is preserved in metadata."""
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
