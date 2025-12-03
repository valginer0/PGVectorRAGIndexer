"""
Tests for null byte sanitization.
"""

import pytest
from document_processor import DocumentProcessor

class TestNullByteSanitization:
    """Test sanitization of null bytes in documents."""
    
    def test_process_file_with_null_bytes(self, tmp_path):
        """Test processing a file containing null bytes."""
        file_path = tmp_path / "null_bytes.txt"
        # Create content with null bytes
        content = b"Text with \x00 null bytes \x00 inside"
        file_path.write_bytes(content)
        
        processor = DocumentProcessor()
        result = processor.process(str(file_path))
        
        assert result is not None
        assert len(result.chunks) > 0
        # Null bytes should be removed
        assert "\x00" not in result.chunks[0].page_content
        assert "Text with  null bytes  inside" in result.chunks[0].page_content
