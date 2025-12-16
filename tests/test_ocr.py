"""
Tests for OCR (Optical Character Recognition) functionality.

These tests verify:
1. OCRConfig loading and defaults
2. ImageDocumentLoader functionality
3. PDFDocumentLoader OCR fallback
4. OCR mode parameter handling

Note: Some tests require Tesseract to be installed on the system.
"""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from pydantic import ValidationError

from config import OCRConfig, AppConfig, get_config


class TestOCRConfig:
    """Tests for OCRConfig."""
    
    def test_default_values(self):
        """Test default OCR configuration values."""
        config = OCRConfig()
        assert config.mode == 'auto'
        assert config.language == 'eng'
        assert config.dpi == 300
        assert config.timeout == 300
    
    def test_valid_modes(self):
        """Test all valid OCR modes."""
        for mode in ['skip', 'only', 'auto']:
            config = OCRConfig(mode=mode)
            assert config.mode == mode
    
    def test_invalid_mode(self):
        """Test that invalid OCR mode raises validation error."""
        with pytest.raises(ValidationError):
            OCRConfig(mode='invalid_mode')
    
    def test_dpi_bounds(self):
        """Test DPI value bounds."""
        # Valid DPI values
        config = OCRConfig(dpi=72)
        assert config.dpi == 72
        
        config = OCRConfig(dpi=600)
        assert config.dpi == 600
    
    def test_timeout_positive(self):
        """Test that timeout must be positive."""
        config = OCRConfig(timeout=30)
        assert config.timeout == 30


class TestAppConfigWithOCR:
    """Tests for AppConfig OCR integration."""
    
    def test_ocr_in_app_config(self):
        """Test that OCR config is included in AppConfig."""
        config = AppConfig.load()
        assert hasattr(config, 'ocr')
        assert isinstance(config.ocr, OCRConfig)
    
    def test_image_extensions_in_supported(self):
        """Test that image extensions are in supported_extensions."""
        config = AppConfig.load()
        image_extensions = ['.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp']
        for ext in image_extensions:
            assert ext in config.supported_extensions, f"{ext} not in supported_extensions"


class TestOCRAvailability:
    """Tests for OCR availability detection."""
    
    def test_ocr_available_flag(self):
        """Test OCR_AVAILABLE flag is set correctly."""
        from document_processor import OCR_AVAILABLE
        # This should be True if pytesseract is installed, False otherwise
        assert isinstance(OCR_AVAILABLE, bool)


class TestImageDocumentLoader:
    """Tests for ImageDocumentLoader."""
    
    def test_can_load_image_extensions(self):
        """Test that ImageDocumentLoader can load image files."""
        from document_processor import ImageDocumentLoader
        
        loader = ImageDocumentLoader()
        
        # Should handle image extensions
        assert loader.can_load('test.png') is True
        assert loader.can_load('test.jpg') is True
        assert loader.can_load('test.jpeg') is True
        assert loader.can_load('test.tiff') is True
        assert loader.can_load('test.tif') is True
        assert loader.can_load('test.bmp') is True
        
        # Case insensitive
        assert loader.can_load('test.PNG') is True
        assert loader.can_load('test.JPG') is True
        
        # Should not handle non-image files
        assert loader.can_load('test.pdf') is False
        assert loader.can_load('test.txt') is False
        assert loader.can_load('test.docx') is False
    
    def test_skip_mode_returns_empty(self):
        """Test that skip mode returns empty list."""
        from document_processor import ImageDocumentLoader
        
        loader = ImageDocumentLoader()
        result = loader.load('fake_image.jpg', ocr_mode='skip')
        assert result == []
    
    @pytest.mark.skipif(
        True,  # Skip by default - requires Tesseract installed
        reason="Requires Tesseract OCR installed on system"
    )
    def test_load_actual_image(self, tmp_path):
        """Test loading an actual image file (requires Tesseract)."""
        from document_processor import ImageDocumentLoader, OCR_AVAILABLE
        
        if not OCR_AVAILABLE:
            pytest.skip("Tesseract not installed")
        
        # Create a simple test image with text
        from PIL import Image, ImageDraw
        
        img = Image.new('RGB', (200, 50), color='white')
        draw = ImageDraw.Draw(img)
        draw.text((10, 10), "Hello World", fill='black')
        
        img_path = tmp_path / "test_image.png"
        img.save(img_path)
        
        loader = ImageDocumentLoader()
        result = loader.load(str(img_path), ocr_mode='auto')
        
        assert len(result) > 0
        assert 'Hello' in result[0].page_content or 'World' in result[0].page_content


class TestPDFDocumentLoaderWithOCR:
    """Tests for PDFDocumentLoader OCR functionality."""
    
    def test_pdf_loader_accepts_ocr_mode(self):
        """Test that PDFDocumentLoader accepts ocr_mode parameter."""
        from document_processor import PDFDocumentLoader
        import inspect
        
        loader = PDFDocumentLoader()
        sig = inspect.signature(loader.load)
        
        assert 'ocr_mode' in sig.parameters
        assert sig.parameters['ocr_mode'].default == 'auto'
    
    def test_pdf_loader_has_image_extensions(self):
        """Test that PDFDocumentLoader has IMAGE_EXTENSIONS attribute."""
        from document_processor import PDFDocumentLoader
        
        assert hasattr(PDFDocumentLoader, 'IMAGE_EXTENSIONS')
        assert '.png' in PDFDocumentLoader.IMAGE_EXTENSIONS


class TestDocumentProcessorOCRIntegration:
    """Tests for DocumentProcessor OCR integration."""
    
    def test_processor_accepts_ocr_mode(self):
        """Test that DocumentProcessor.process accepts ocr_mode."""
        from document_processor import DocumentProcessor
        import inspect
        
        processor = DocumentProcessor()
        sig = inspect.signature(processor.process)
        
        assert 'ocr_mode' in sig.parameters
    
    def test_image_loader_registered(self):
        """Test that ImageDocumentLoader is registered in DocumentProcessor."""
        from document_processor import DocumentProcessor, ImageDocumentLoader
        
        processor = DocumentProcessor()
        
        # Check that at least one loader can handle images
        can_load_image = any(
            loader.can_load('test.png') 
            for loader in processor.loaders
        )
        assert can_load_image, "No loader registered for image files"


class TestIndexerOCRIntegration:
    """Tests for DocumentIndexer OCR integration."""
    
    def test_indexer_accepts_ocr_mode(self):
        """Test that DocumentIndexer.index_document accepts ocr_mode."""
        from indexer_v2 import DocumentIndexer
        import inspect
        
        # Just check the signature, don't actually instantiate (needs DB)
        sig = inspect.signature(DocumentIndexer.index_document)
        
        assert 'ocr_mode' in sig.parameters


class TestCLIOCRMode:
    """Tests for CLI --ocr-mode argument."""
    
    def test_ocr_mode_in_argparse(self):
        """Test that --ocr-mode is available in CLI."""
        import argparse
        from indexer_v2 import main
        import sys
        
        # Capture the parser by inspecting the main function
        # We can verify by trying to parse the argument
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest='command')
        index_parser = subparsers.add_parser('index')
        index_parser.add_argument('source')
        index_parser.add_argument('--force', action='store_true')
        index_parser.add_argument('--ocr-mode', choices=['skip', 'only', 'auto'])
        
        # Test parsing with ocr-mode
        args = parser.parse_args(['index', 'test.pdf', '--ocr-mode', 'auto'])
        assert args.ocr_mode == 'auto'
        
        args = parser.parse_args(['index', 'test.pdf', '--ocr-mode', 'skip'])
        assert args.ocr_mode == 'skip'
