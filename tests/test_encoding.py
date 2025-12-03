"""
Tests for file encoding support.
"""

import pytest
from document_processor import TextDocumentLoader

class TestEncodingSupport:
    """Test support for various file encodings."""
    
    def test_load_utf8_file(self, tmp_path):
        """Test loading a standard UTF-8 file."""
        file_path = tmp_path / "utf8.txt"
        file_path.write_text("Hello World", encoding="utf-8")
        
        loader = TextDocumentLoader()
        docs = loader.load(str(file_path))
        
        assert len(docs) > 0
        assert "Hello World" in docs[0].page_content

    def test_load_latin1_file(self, tmp_path):
        """Test loading a Latin-1 (cp1252) file."""
        # Create a file with latin-1 characters (e.g. 'é' as 0xE9)
        content = b"Log entry: \xe9v\xe9nement" 
        file_path = tmp_path / "latin1.txt"
        file_path.write_bytes(content)
        
        loader = TextDocumentLoader()
        docs = loader.load(str(file_path))
        
        assert len(docs) > 0
        assert "Log entry:" in docs[0].page_content
        # The loader should have decoded it correctly
        assert "événement" in docs[0].page_content

    def test_load_mixed_content(self, tmp_path):
        """Test loading content that might trigger autodetect."""
        content = b"Simple ASCII content"
        file_path = tmp_path / "ascii.txt"
        file_path.write_bytes(content)
        
        loader = TextDocumentLoader()
        docs = loader.load(str(file_path))
        
        assert len(docs) > 0
        assert "Simple ASCII content" in docs[0].page_content
