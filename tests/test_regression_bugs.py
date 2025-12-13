"""
Regression tests for bug fixes.

These tests ensure that previously fixed bugs don't reoccur.
"""

import pytest
from pathlib import Path
from config import get_config
from indexer_v2 import DocumentIndexer
from document_processor import DocumentProcessor


class TestMarkdownFileSupport:
    """
    Regression test for Bug #1: Missing .md and .markdown support.
    
    Issue: Desktop app advertised support for Markdown files but config.py
    was missing .md and .markdown from supported_extensions list, causing
    400 Bad Request errors during upload.
    
    Fixed in commit: 12bab51
    """
    
    def test_md_extension_in_supported_list(self):
        """Test that .md extension is in supported extensions."""
        config = get_config()
        assert '.md' in config.supported_extensions, \
            ".md extension must be in supported_extensions"
    
    def test_markdown_extension_in_supported_list(self):
        """Test that .markdown extension is in supported extensions."""
        config = get_config()
        assert '.markdown' in config.supported_extensions, \
            ".markdown extension must be in supported_extensions"
    
    def test_markdown_file_validation_passes(self, tmp_path):
        """Test that markdown files pass validation."""
        # Create a test markdown file
        md_file = tmp_path / "test.md"
        md_file.write_text("# Test Document\n\nThis is a test.")
        
        # Processor should not raise UnsupportedFormatError
        processor = DocumentProcessor()
        try:
            result = processor.process(str(md_file))
            assert result is not None
            assert len(result.chunks) > 0
        except Exception as e:
            pytest.fail(f"Markdown file validation failed: {e}")
    
    def test_markdown_extension_file_validation_passes(self, tmp_path):
        """Test that .markdown files pass validation."""
        # Create a test .markdown file
        markdown_file = tmp_path / "test.markdown"
        markdown_file.write_text("# Test Document\n\nThis is a test.")
        
        # Processor should not raise UnsupportedFormatError
        processor = DocumentProcessor()
        try:
            result = processor.process(str(markdown_file))
            assert result is not None
            assert len(result.chunks) > 0
        except Exception as e:
            pytest.fail(f".markdown file validation failed: {e}")


@pytest.mark.database
class TestIndexerMetadataTuple:
    """
    Regression test for Bug #2: Metadata tuple mismatch.
    
    Issue: indexer_v2.py was sending 5-tuple to database.py insert_chunks()
    but database.py expected 6-tuple (including metadata), causing
    "not enough values to unpack (expected 6, got 5)" error.
    
    Fixed in commit: 6f53324
    """
    
    def test_chunks_data_has_six_elements(self, tmp_path):
        """Test that chunks_data tuples have exactly 6 elements including metadata."""
        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("This is a test document for metadata tuple validation.")
        
        # Mock the database operations to capture chunks_data
        from unittest.mock import Mock, patch
        
        captured_chunks = []
        
        def mock_insert_chunks(chunks):
            captured_chunks.extend(chunks)
            return len(chunks)
        
        with patch('indexer_v2.DocumentRepository.insert_chunks', side_effect=mock_insert_chunks):
            with patch('indexer_v2.DocumentRepository.document_exists', return_value=False):
                indexer = DocumentIndexer()
                result = indexer.index_document(str(test_file))
        
        # Verify chunks were captured
        assert len(captured_chunks) > 0, "No chunks were captured"
        
        # Verify each chunk has exactly 6 elements
        for i, chunk in enumerate(captured_chunks):
            assert len(chunk) == 6, \
                f"Chunk {i} has {len(chunk)} elements, expected 6 (doc_id, idx, text, uri, embedding, metadata)"
            
            # Verify the 6th element (metadata) exists and is a dict
            metadata = chunk[5]
            assert isinstance(metadata, dict), \
                f"Chunk {i} metadata (element 6) must be a dict, got {type(metadata)}"
    
    def test_metadata_element_is_dict_not_none(self, tmp_path):
        """Test that metadata element is always a dict, never None."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Test content")
        
        from unittest.mock import Mock, patch
        
        captured_chunks = []
        
        def mock_insert_chunks(chunks):
            captured_chunks.extend(chunks)
            return len(chunks)
        
        with patch('indexer_v2.DocumentRepository.insert_chunks', side_effect=mock_insert_chunks):
            with patch('indexer_v2.DocumentRepository.document_exists', return_value=False):
                indexer = DocumentIndexer()
                result = indexer.index_document(str(test_file))
        
        for i, chunk in enumerate(captured_chunks):
            metadata = chunk[5]
            assert metadata is not None, f"Chunk {i} metadata must not be None"
            assert isinstance(metadata, dict), f"Chunk {i} metadata must be a dict"
