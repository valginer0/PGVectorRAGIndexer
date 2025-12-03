"""
Tests for YAML and extensionless file support.
"""

import pytest
from pathlib import Path
from config import get_config
from document_processor import DocumentProcessor, UnsupportedFormatError


class TestYamlSupport:
    """Test support for YAML files."""
    
    def test_yaml_extension_in_config(self):
        """Test that .yaml and .yml are in supported extensions."""
        config = get_config()
        assert '.yaml' in config.supported_extensions
        assert '.yml' in config.supported_extensions
    
    def test_process_yaml_file(self, tmp_path):
        """Test processing a YAML file."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("key: value\nlist:\n  - item1\n  - item2")
        
        processor = DocumentProcessor()
        result = processor.process(str(yaml_file))
        
        assert result is not None
        assert len(result.chunks) > 0
        assert "key: value" in result.chunks[0].page_content

    def test_process_yml_file(self, tmp_path):
        """Test processing a YML file."""
        yml_file = tmp_path / "config.yml"
        yml_file.write_text("key: value")
        
        processor = DocumentProcessor()
        result = processor.process(str(yml_file))
        
        assert result is not None
        assert len(result.chunks) > 0


class TestExtensionlessFileSupport:
    """Test support for specific extensionless files (LICENSE, Dockerfile, etc.)."""
    
    def test_supported_filenames_in_config(self):
        """Test that supported_filenames list exists and contains expected values."""
        config = get_config()
        assert hasattr(config, 'supported_filenames')
        assert 'LICENSE' in config.supported_filenames
        assert 'Dockerfile' in config.supported_filenames
    
    def test_process_license_file(self, tmp_path):
        """Test processing a LICENSE file."""
        license_file = tmp_path / "LICENSE"
        license_file.write_text("MIT License\n\nCopyright (c) 2023")
        
        processor = DocumentProcessor()
        result = processor.process(str(license_file))
        
        assert result is not None
        assert len(result.chunks) > 0
        assert "MIT License" in result.chunks[0].page_content
    
    def test_process_dockerfile(self, tmp_path):
        """Test processing a Dockerfile."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM python:3.9\nRUN pip install .")
        
        processor = DocumentProcessor()
        result = processor.process(str(dockerfile))
        
        assert result is not None
        assert len(result.chunks) > 0
        assert "FROM python:3.9" in result.chunks[0].page_content
    
    def test_unsupported_extensionless_file(self, tmp_path):
        """Test that unsupported extensionless files are rejected."""
        unknown_file = tmp_path / "UNKNOWN_FILE"
        unknown_file.write_text("Some content")
        
        processor = DocumentProcessor()
        with pytest.raises(UnsupportedFormatError):
            processor.process(str(unknown_file))
