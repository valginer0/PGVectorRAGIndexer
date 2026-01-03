"""
Configuration management for PGVectorRAGIndexer.

This module provides centralized configuration with validation using Pydantic.
All configuration values are loaded from environment variables with sensible defaults.
"""

import os
from typing import Optional, Literal
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfig(BaseSettings):
    """Database connection and pool configuration."""
    
    model_config = SettingsConfigDict(env_prefix='DB_', case_sensitive=False)
    
    host: str = Field(default='localhost', description='Database host')
    port: int = Field(default=5432, description='Database port')
    name: str = Field(default='rag_vector_db', alias='POSTGRES_DB', description='Database name')
    user: str = Field(default='rag_user', alias='POSTGRES_USER', description='Database user')
    password: str = Field(default='rag_password', alias='POSTGRES_PASSWORD', description='Database password')
    
    # Connection pool settings
    pool_size: int = Field(default=10, description='Connection pool size')
    max_overflow: int = Field(default=20, description='Max overflow connections')
    pool_timeout: int = Field(default=30, description='Pool timeout in seconds')
    pool_recycle: int = Field(default=3600, description='Connection recycle time in seconds')
    
    @property
    def connection_string(self) -> str:
        """Generate PostgreSQL connection string."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"
    
    @property
    def async_connection_string(self) -> str:
        """Generate async PostgreSQL connection string."""
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class EmailConfig(BaseSettings):
    """
    Email Connector configuration (Opt-in).
    
    Uses MSAL device-code flow (public client).
    No client_secret required.
    """
    model_config = SettingsConfigDict(env_prefix='EMAIL_', case_sensitive=False)
    
    enabled: bool = Field(default=False, description='Enable email connector')
    client_id: Optional[str] = Field(default=None, description='Azure App Client ID')
    tenant_id: Optional[str] = Field(default='common', description='Azure Tenant ID (or common)')


class EmbeddingConfig(BaseSettings):
    """Embedding model configuration."""
    
    model_config = SettingsConfigDict(env_prefix='EMBEDDING_', case_sensitive=False)
    
    model_name: str = Field(
        default='all-MiniLM-L6-v2',
        description='Sentence transformer model name'
    )
    dimension: int = Field(default=384, description='Embedding vector dimension')
    batch_size: int = Field(default=32, description='Batch size for embedding generation')
    device: Optional[str] = Field(default=None, description='Device for model (cpu, cuda, mps)')
    normalize_embeddings: bool = Field(default=True, description='Normalize embeddings to unit length')
    
    @field_validator('dimension')
    @classmethod
    def validate_dimension(cls, v: int) -> int:
        """Validate embedding dimension is positive."""
        if v <= 0:
            raise ValueError('Embedding dimension must be positive')
        return v
    
    @model_validator(mode='after')
    def validate_model_dimension(self) -> 'EmbeddingConfig':
        """Validate model name matches expected dimension."""
        model_dimensions = {
            'all-MiniLM-L6-v2': 384,
            'all-mpnet-base-v2': 768,
            'paraphrase-multilingual-MiniLM-L12-v2': 384,
            'multi-qa-MiniLM-L6-cos-v1': 384,
        }
        
        if self.model_name in model_dimensions:
            expected_dim = model_dimensions[self.model_name]
            if self.dimension != expected_dim:
                raise ValueError(
                    f"Model {self.model_name} has dimension {expected_dim}, "
                    f"but config specifies {self.dimension}"
                )
        
        return self


class ChunkingConfig(BaseSettings):
    """Document chunking configuration."""
    
    model_config = SettingsConfigDict(env_prefix='CHUNK_', case_sensitive=False)
    
    size: int = Field(default=250, description='Chunk size in characters')
    overlap: int = Field(default=25, description='Overlap between chunks')
    separators: list[str] = Field(
        default=["\n\n", "\n", ". ", " ", ""],
        description='Text separators for chunking'
    )
    
    @field_validator('size', 'overlap')
    @classmethod
    def validate_positive(cls, v: int) -> int:
        """Validate size and overlap are positive."""
        if v < 0:
            raise ValueError('Chunk size and overlap must be non-negative')
        return v
    
    @model_validator(mode='after')
    def validate_overlap_size(self) -> 'ChunkingConfig':
        """Validate overlap is smaller than chunk size."""
        if self.overlap >= self.size:
            raise ValueError('Chunk overlap must be smaller than chunk size')
        return self


class RetrievalConfig(BaseSettings):
    """Retrieval and search configuration."""
    
    model_config = SettingsConfigDict(env_prefix='RETRIEVAL_', case_sensitive=False)
    
    top_k: int = Field(default=5, description='Number of top results to retrieve')
    similarity_threshold: float = Field(
        default=0.7,
        description='Minimum similarity score (0-1) for results'
    )
    distance_metric: Literal['cosine', 'l2', 'inner_product'] = Field(
        default='cosine',
        description='Distance metric for vector search'
    )
    enable_hybrid_search: bool = Field(
        default=False,
        description='Enable hybrid vector + full-text search'
    )
    hybrid_alpha: float = Field(
        default=0.5,
        description='Weight for vector search in hybrid mode (0=full-text only, 1=vector only)'
    )
    
    @field_validator('top_k')
    @classmethod
    def validate_top_k(cls, v: int) -> int:
        """Validate top_k is positive."""
        if v <= 0:
            raise ValueError('top_k must be positive')
        return v
    
    @field_validator('similarity_threshold', 'hybrid_alpha')
    @classmethod
    def validate_range(cls, v: float) -> float:
        """Validate values are in [0, 1] range."""
        if not 0 <= v <= 1:
            raise ValueError('Value must be between 0 and 1')
        return v


class OCRConfig(BaseSettings):
    """OCR (Optical Character Recognition) configuration."""
    
    model_config = SettingsConfigDict(env_prefix='OCR_', case_sensitive=False)
    
    mode: Literal['skip', 'only', 'auto'] = Field(
        default='auto',
        description='OCR processing mode: skip=no OCR, only=OCR files only, auto=smart fallback'
    )
    language: str = Field(
        default='eng',
        description='Tesseract language code (e.g., eng, fra, deu)'
    )
    timeout: int = Field(
        default=300,
        description='Timeout in seconds for OCR processing per file'
    )
    dpi: int = Field(
        default=300,
        description='DPI for PDF to image conversion'
    )
    
    @field_validator('timeout', 'dpi')
    @classmethod
    def validate_positive(cls, v: int) -> int:
        """Validate timeout and dpi are positive."""
        if v <= 0:
            raise ValueError('Value must be positive')
        return v


class APIConfig(BaseSettings):
    """API server configuration."""
    
    model_config = SettingsConfigDict(env_prefix='API_', case_sensitive=False)
    
    host: str = Field(default='0.0.0.0', description='API host')
    port: int = Field(default=8000, description='API port')
    workers: int = Field(default=4, description='Number of worker processes')
    reload: bool = Field(default=False, description='Enable auto-reload for development')
    log_level: Literal['debug', 'info', 'warning', 'error', 'critical'] = Field(
        default='info',
        description='Logging level'
    )
    cors_origins: list[str] = Field(
        default=['*'],
        description='CORS allowed origins'
    )
    rate_limit_per_minute: int = Field(
        default=60,
        description='Rate limit per minute per IP'
    )


class AppConfig(BaseSettings):
    """Main application configuration."""
    
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore'
    )
    
    # Environment
    environment: Literal['development', 'staging', 'production'] = Field(
        default='development',
        description='Application environment'
    )
    debug: bool = Field(default=False, description='Debug mode')
    
    # Sub-configurations
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    ocr: OCRConfig = Field(default_factory=OCRConfig)
    
    # Application settings
    max_file_size_mb: int = Field(default=50, description='Maximum file size in MB')
    supported_extensions: list[str] = Field(
        default=['.txt', '.md', '.markdown', '.pdf', '.doc', '.docx', '.xlsx', '.csv', '.html', '.pptx', '.yaml', '.yml', '.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp'],
        description='Supported file extensions'
    )
    supported_filenames: list[str] = Field(
        default=['LICENSE', 'Dockerfile', 'Makefile', 'Jenkinsfile'],
        description='Supported filenames without extensions'
    )
    cache_embeddings: bool = Field(default=True, description='Cache embeddings in memory')
    enable_deduplication: bool = Field(default=True, description='Enable document deduplication')
    
    @classmethod
    def load(cls) -> 'AppConfig':
        """Load configuration from environment."""
        return cls(
            database=DatabaseConfig(),
            embedding=EmbeddingConfig(),
            chunking=ChunkingConfig(),
            retrieval=RetrievalConfig(),
            api=APIConfig(),
            ocr=OCRConfig()
        )
    
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment == 'production'
    
    def is_development(self) -> bool:
        """Check if running in development."""
        return self.environment == 'development'


# Global configuration instance
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Get or create global configuration instance."""
    global _config
    if _config is None:
        _config = AppConfig.load()
    return _config


def reload_config() -> AppConfig:
    """Reload configuration from environment."""
    global _config
    _config = AppConfig.load()
    return _config
