"""
Tests for encrypted PDF detection and handling.
"""
import io
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from document_processor import EncryptedPDFError, PDFDocumentLoader


class TestEncryptedPDFDetection:
    """Tests for encrypted PDF detection in document processor."""
    
    def test_encrypted_pdf_error_is_document_processing_error(self):
        """EncryptedPDFError should be a DocumentProcessingError subclass."""
        from document_processor import DocumentProcessingError
        assert issubclass(EncryptedPDFError, DocumentProcessingError)
    
    def test_encrypted_pdf_raises_error(self):
        """Should raise EncryptedPDFError for encrypted PDFs."""
        # Mock at the pypdf module level since it's imported inside the function
        with patch('pypdf.PdfReader') as mock_pdf_reader:
            # Mock an encrypted PDF
            mock_reader = MagicMock()
            mock_reader.is_encrypted = True
            mock_pdf_reader.return_value = mock_reader
            
            loader = PDFDocumentLoader()
            
            with pytest.raises(EncryptedPDFError) as exc_info:
                loader.load("/fake/path/encrypted.pdf")
            
            assert "password-protected" in str(exc_info.value).lower()
    
    def test_unencrypted_pdf_loads_normally(self):
        """Unencrypted PDFs should load normally."""
        with patch('pypdf.PdfReader') as mock_pdf_reader, \
             patch('document_processor.PyPDFLoader') as mock_pypdf_loader:
            # Mock an unencrypted PDF
            mock_reader = MagicMock()
            mock_reader.is_encrypted = False
            mock_pdf_reader.return_value = mock_reader
            
            # Mock the actual loader
            mock_loader = MagicMock()
            mock_loader.load.return_value = [MagicMock(page_content="Test content" * 20)]
            mock_pypdf_loader.return_value = mock_loader
            
            loader = PDFDocumentLoader()
            result = loader.load("/fake/path/normal.pdf")
            
            assert len(result) > 0


@pytest.mark.database
class TestEncryptedPDFAPI:
    """Tests for encrypted PDF API endpoints (requires database)."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        from api import app
        return TestClient(app)
    
    def test_list_encrypted_pdfs_endpoint(self, client):
        """GET /documents/encrypted should return list of encrypted PDFs."""
        response = client.get("/documents/encrypted")
        
        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert "encrypted_pdfs" in data
        assert isinstance(data["encrypted_pdfs"], list)
    
    def test_clear_encrypted_pdfs_list(self, client):
        """clear=true should clear the encrypted PDFs list."""
        # First add an entry directly to the list
        import api
        api.encrypted_pdfs_encountered.append({
            "source_uri": "test_clear.pdf",
            "filename": "test_clear.pdf",
            "detected_at": "2025-01-01T00:00:00"
        })
        
        # Clear the list
        response = client.get("/documents/encrypted?clear=true")
        
        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 1  # Should have returned our entry
        
        # Verify list is now empty
        response2 = client.get("/documents/encrypted")
        assert response2.json()["count"] == 0
    
    def test_upload_encrypted_pdf_returns_403(self, client):
        """Uploading encrypted PDF should return 403 with error_type."""
        # Create a minimal encrypted PDF mock
        with patch('pypdf.PdfReader') as mock_reader:
            mock_instance = MagicMock()
            mock_instance.is_encrypted = True
            mock_reader.return_value = mock_instance
            
            # Upload a fake PDF
            response = client.post(
                "/upload-and-index",
                files={"file": ("test.pdf", b"%PDF-1.4 encrypted", "application/pdf")}
            )
            
            assert response.status_code == 403
            data = response.json()
            assert data["detail"]["error_type"] == "encrypted_pdf"


class TestIndexerCLI:
    """Tests for encrypted PDF handling in indexer_v2.py CLI."""
    
    def test_index_document_returns_encrypted_pdf_error(self):
        """indexer.index_document should return error_type: encrypted_pdf."""
        with patch('pypdf.PdfReader') as mock_pdf_reader:
            mock_reader = MagicMock()
            mock_reader.is_encrypted = True
            mock_pdf_reader.return_value = mock_reader
            
            from indexer_v2 import DocumentIndexer
            
            # Mock the dependencies to avoid DB connection
            with patch.object(DocumentIndexer, '__init__', lambda self: None):
                indexer = DocumentIndexer()
                indexer.processor = MagicMock()
                indexer.processor.process.side_effect = EncryptedPDFError("Encrypted")
                
                # Mock the log method
                indexer._log_encrypted_pdf = MagicMock()
                
                result = indexer.index_document("/fake/encrypted.pdf")
                
                assert result['status'] == 'error'
                assert result['error_type'] == 'encrypted_pdf'
                indexer._log_encrypted_pdf.assert_called_once()
    
    def test_log_encrypted_pdf_writes_to_file(self, tmp_path):
        """_log_encrypted_pdf should write to encrypted_pdfs.log."""
        import os
        
        # Change to temp directory so log file is created there
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        
        try:
            from indexer_v2 import DocumentIndexer
            
            with patch.object(DocumentIndexer, '__init__', lambda self: None):
                indexer = DocumentIndexer()
                indexer._log_encrypted_pdf("/test/encrypted.pdf")
                
                log_file = tmp_path / "encrypted_pdfs.log"
                assert log_file.exists()
                
                content = log_file.read_text()
                assert "/test/encrypted.pdf" in content
        finally:
            os.chdir(original_cwd)
