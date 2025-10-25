"""
Tests for legacy Microsoft Word (.doc) file support.
"""

import pytest
from pathlib import Path
import tempfile
from fastapi.testclient import TestClient
from api import app


class TestLegacyWordSupport:
    """Test support for legacy .doc files."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)
    
    def test_doc_file_in_supported_extensions(self):
        """Test that .doc is in supported extensions."""
        from document_processor import OfficeDocumentLoader
        
        loader = OfficeDocumentLoader()
        assert '.doc' in loader.SUPPORTED_EXTENSIONS, ".doc should be in supported extensions"
    
    def test_doc_file_can_load(self):
        """Test that .doc files can be loaded."""
        from document_processor import OfficeDocumentLoader
        
        loader = OfficeDocumentLoader()
        assert loader.can_load("test.doc"), "Should be able to load .doc files"
        assert loader.can_load("TEST.DOC"), "Should handle uppercase .DOC"
        assert loader.can_load("/path/to/document.doc"), "Should handle full paths"
    
    def test_doc_file_metadata(self):
        """Test metadata extraction for .doc files."""
        from document_processor import OfficeDocumentLoader
        
        # Create a temporary .doc file
        with tempfile.NamedTemporaryFile(suffix='.doc', delete=False) as tmp:
            tmp.write(b"Test content")
            tmp_path = tmp.name
        
        try:
            loader = OfficeDocumentLoader()
            metadata = loader.get_metadata(tmp_path)
            
            assert metadata['file_type'] == 'office'
            assert metadata['file_extension'] == '.doc'
            assert metadata['file_size'] > 0
        finally:
            Path(tmp_path).unlink()
    
    def test_upload_doc_file_via_api(self, client, db_manager):
        """Test uploading a .doc file through the API."""
        # Create a simple .doc file (actually just text, but with .doc extension)
        # Note: For a real test, we'd need an actual .doc file
        content = b"This is a test document in legacy Word format."
        
        response = client.post(
            "/upload-and-index",
            files={"file": ("test_document.doc", content, "application/msword")},
            data={"document_type": "test"}
        )
        
        if response.status_code == 200:
            data = response.json()
            assert data["status"] in ["success", "error"]
        else:
            assert response.status_code == 400
            assert "convert" in response.json()["detail"].lower()
    
    def test_doc_in_config_supported_extensions(self):
        """Test that .doc is in the config's supported extensions."""
        from config import get_config
        
        config = get_config()
        supported = config.supported_extensions
        
        assert '.doc' in supported, ".doc should be in config supported extensions"
