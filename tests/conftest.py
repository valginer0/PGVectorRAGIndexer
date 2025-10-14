"""
Pytest configuration and fixtures for PGVectorRAGIndexer tests.
"""

import os
import pytest
from unittest.mock import Mock, MagicMock
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Set test environment variables before importing config
# Use the existing development database for integration tests
os.environ['ENVIRONMENT'] = 'development'
os.environ['DB_HOST'] = 'localhost'
os.environ['DB_PORT'] = '5432'
os.environ['POSTGRES_DB'] = 'rag_vector_db'  # Use existing dev database
os.environ['POSTGRES_USER'] = 'rag_user'
os.environ['POSTGRES_PASSWORD'] = 'rag_password'


@pytest.fixture(scope='session')
def test_config():
    """Provide test configuration."""
    from config import AppConfig
    return AppConfig.load()


@pytest.fixture(scope='session')
def db_connection_params(test_config):
    """Provide database connection parameters."""
    return {
        'host': test_config.database.host,
        'port': test_config.database.port,
        'dbname': test_config.database.name,
        'user': test_config.database.user,
        'password': test_config.database.password
    }


@pytest.fixture(scope='session')
def setup_test_database(db_connection_params):
    """Create test database if it doesn't exist."""
    # Connect to default postgres database to create test database
    conn_params = db_connection_params.copy()
    test_db_name = conn_params.pop('dbname')
    conn_params['dbname'] = 'postgres'
    
    try:
        conn = psycopg2.connect(**conn_params)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        # Check if test database exists
        cursor.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (test_db_name,)
        )
        exists = cursor.fetchone()
        
        if not exists:
            cursor.execute(f"CREATE DATABASE {test_db_name}")
            print(f"Created test database: {test_db_name}")
        
        cursor.close()
        conn.close()
        
        yield test_db_name
        
        # Cleanup: Drop test database after all tests
        # Uncomment if you want to drop the test database after tests
        # conn = psycopg2.connect(**conn_params)
        # conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        # cursor = conn.cursor()
        # cursor.execute(f"DROP DATABASE IF EXISTS {test_db_name}")
        # cursor.close()
        # conn.close()
        
    except psycopg2.OperationalError as e:
        pytest.skip(f"Could not connect to PostgreSQL: {e}")


@pytest.fixture(scope='function')
def db_manager(setup_test_database):
    """Provide database manager for tests."""
    from database import DatabaseManager
    
    manager = DatabaseManager()
    manager.initialize()
    
    yield manager
    
    # Cleanup: Clear all data after each test
    with manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("TRUNCATE TABLE document_chunks CASCADE")
        conn.commit()
        cursor.close()
    
    manager.close()


@pytest.fixture
def mock_embedding_service():
    """Provide mock embedding service."""
    mock_service = Mock()
    mock_service.config = Mock()
    mock_service.config.dimension = 384
    mock_service.config.model_name = 'all-MiniLM-L6-v2'
    
    # Mock encode to return fake embeddings
    def mock_encode(text, **kwargs):
        if isinstance(text, str):
            return [0.1] * 384
        else:
            return [[0.1] * 384 for _ in text]
    
    mock_service.encode = mock_encode
    mock_service.get_model_info.return_value = {
        'model_name': 'all-MiniLM-L6-v2',
        'dimension': 384,
        'device': 'cpu'
    }
    
    return mock_service


@pytest.fixture
def sample_documents():
    """Provide sample documents for testing."""
    return [
        {
            'document_id': 'doc1',
            'source_uri': '/path/to/doc1.txt',
            'chunks': [
                'This is the first chunk of document 1.',
                'This is the second chunk of document 1.'
            ]
        },
        {
            'document_id': 'doc2',
            'source_uri': '/path/to/doc2.pdf',
            'chunks': [
                'This is the first chunk of document 2.',
                'This is the second chunk of document 2.',
                'This is the third chunk of document 2.'
            ]
        }
    ]


@pytest.fixture
def sample_embeddings():
    """Provide sample embeddings for testing."""
    import random
    return [[random.random() for _ in range(384)] for _ in range(5)]
