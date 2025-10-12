"""
Tests for configuration management.
"""

import pytest
import os
from pydantic import ValidationError

from config import (
    DatabaseConfig,
    EmbeddingConfig,
    ChunkingConfig,
    RetrievalConfig,
    APIConfig,
    AppConfig,
    get_config,
    reload_config
)


class TestDatabaseConfig:
    """Tests for DatabaseConfig."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = DatabaseConfig()
        assert config.host == 'localhost'
        assert config.port == 5432
        assert config.pool_size == 10
    
    def test_connection_string(self):
        """Test connection string generation."""
        config = DatabaseConfig(
            host='testhost',
            port=5433,
            user='testuser',
            password='testpass',
            name='testdb'
        )
        expected = 'postgresql://testuser:testpass@testhost:5433/testdb'
        assert config.connection_string == expected
    
    def test_async_connection_string(self):
        """Test async connection string generation."""
        config = DatabaseConfig()
        assert config.async_connection_string.startswith('postgresql+asyncpg://')


class TestEmbeddingConfig:
    """Tests for EmbeddingConfig."""
    
    def test_default_values(self):
        """Test default embedding configuration."""
        config = EmbeddingConfig()
        assert config.model_name == 'all-MiniLM-L6-v2'
        assert config.dimension == 384
        assert config.batch_size == 32
    
    def test_invalid_dimension(self):
        """Test validation for invalid dimension."""
        with pytest.raises(ValidationError):
            EmbeddingConfig(dimension=-1)
    
    def test_model_dimension_validation(self):
        """Test model and dimension compatibility."""
        # Valid combination
        config = EmbeddingConfig(
            model_name='all-MiniLM-L6-v2',
            dimension=384
        )
        assert config.dimension == 384
        
        # Invalid combination
        with pytest.raises(ValidationError):
            EmbeddingConfig(
                model_name='all-MiniLM-L6-v2',
                dimension=768
            )


class TestChunkingConfig:
    """Tests for ChunkingConfig."""
    
    def test_default_values(self):
        """Test default chunking configuration."""
        config = ChunkingConfig()
        assert config.size == 500
        assert config.overlap == 50
        assert len(config.separators) > 0
    
    def test_invalid_overlap(self):
        """Test validation for overlap >= size."""
        with pytest.raises(ValidationError):
            ChunkingConfig(size=100, overlap=100)
        
        with pytest.raises(ValidationError):
            ChunkingConfig(size=100, overlap=150)
    
    def test_negative_values(self):
        """Test validation for negative values."""
        with pytest.raises(ValidationError):
            ChunkingConfig(size=-1)
        
        with pytest.raises(ValidationError):
            ChunkingConfig(overlap=-1)


class TestRetrievalConfig:
    """Tests for RetrievalConfig."""
    
    def test_default_values(self):
        """Test default retrieval configuration."""
        config = RetrievalConfig()
        assert config.top_k == 5
        assert config.similarity_threshold == 0.7
        assert config.distance_metric == 'cosine'
    
    def test_invalid_top_k(self):
        """Test validation for invalid top_k."""
        with pytest.raises(ValidationError):
            RetrievalConfig(top_k=0)
        
        with pytest.raises(ValidationError):
            RetrievalConfig(top_k=-1)
    
    def test_invalid_threshold(self):
        """Test validation for invalid similarity threshold."""
        with pytest.raises(ValidationError):
            RetrievalConfig(similarity_threshold=1.5)
        
        with pytest.raises(ValidationError):
            RetrievalConfig(similarity_threshold=-0.1)
    
    def test_distance_metrics(self):
        """Test valid distance metrics."""
        for metric in ['cosine', 'l2', 'inner_product']:
            config = RetrievalConfig(distance_metric=metric)
            assert config.distance_metric == metric


class TestAPIConfig:
    """Tests for APIConfig."""
    
    def test_default_values(self):
        """Test default API configuration."""
        config = APIConfig()
        assert config.host == '0.0.0.0'
        assert config.port == 8000
        assert config.workers == 4
        assert config.log_level == 'info'
    
    def test_log_levels(self):
        """Test valid log levels."""
        for level in ['debug', 'info', 'warning', 'error', 'critical']:
            config = APIConfig(log_level=level)
            assert config.log_level == level


class TestAppConfig:
    """Tests for AppConfig."""
    
    def test_load_config(self):
        """Test loading application configuration."""
        config = AppConfig.load()
        assert config.database is not None
        assert config.embedding is not None
        assert config.chunking is not None
        assert config.retrieval is not None
        assert config.api is not None
    
    def test_environment_detection(self):
        """Test environment detection methods."""
        config = AppConfig(environment='development')
        assert config.is_development()
        assert not config.is_production()
        
        config = AppConfig(environment='production')
        assert config.is_production()
        assert not config.is_development()
    
    def test_supported_extensions(self):
        """Test supported file extensions."""
        config = AppConfig.load()
        assert '.pdf' in config.supported_extensions
        assert '.txt' in config.supported_extensions
        assert '.docx' in config.supported_extensions


class TestConfigSingleton:
    """Tests for global configuration singleton."""
    
    def test_get_config(self):
        """Test getting global config instance."""
        config1 = get_config()
        config2 = get_config()
        assert config1 is config2
    
    def test_reload_config(self):
        """Test reloading configuration."""
        config1 = get_config()
        config2 = reload_config()
        # After reload, we should have a new instance
        assert config1 is not config2
