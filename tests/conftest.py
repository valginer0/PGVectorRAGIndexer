"""
Pytest configuration and fixtures for PGVectorRAGIndexer tests.
"""

import os
import pytest
from unittest.mock import Mock, MagicMock, patch
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Set test environment variables before importing config
# Use a SEPARATE test database to avoid polluting development data
os.environ['ENVIRONMENT'] = 'development'  # Use development mode but with test database
os.environ['DB_HOST'] = 'localhost'
os.environ['DB_PORT'] = '5432'
os.environ['POSTGRES_DB'] = 'rag_vector_db_test'  # Separate test database
os.environ['POSTGRES_USER'] = 'rag_user'
os.environ['POSTGRES_PASSWORD'] = 'rag_password'

# Disable auth for all tests by default
os.environ.pop('API_AUTH_FORCE_ALL', None)
os.environ['API_REQUIRE_AUTH'] = 'false'


@pytest.fixture(scope='session')
def test_config():
    """Provide test configuration with forced reload for test database."""
    from config import reload_config
    from database import close_db_manager
    # Ensure environment variables are set before reload
    os.environ['POSTGRES_DB'] = 'rag_vector_db_test'
    close_db_manager()  # Reset any existing manager
    config = reload_config()
    return config


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
        
        # Connect to test database and run migrations
        conn_params['dbname'] = test_db_name
        
        # Ensure environment variables are set for migrations
        os.environ['POSTGRES_DB'] = test_db_name
        
        # Wipe database schema to ensure clean slate for migrations
        wipe_conn = psycopg2.connect(**conn_params)
        wipe_conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        with wipe_conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS public CASCADE")
            cur.execute("CREATE SCHEMA public")
            cur.execute("GRANT ALL ON SCHEMA public TO public")
            cur.execute("GRANT ALL ON SCHEMA public TO rag_user")
        wipe_conn.close()
        
        from config import reload_config
        from database import close_db_manager
        close_db_manager() # Reset manager to use the new DB name
        reload_config()  # Ensure config picks up the test DB
        
        from migrate import run_migrations
        success = run_migrations(auto_backup=False)
        if not success:
            pytest.fail(f"Could not run migrations on test database {test_db_name}")
            
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


@pytest.fixture(autouse=True)
def auto_mock_embeddings(mock_embedding_service):
    """Automatically mock embeddings for all tests to ensure speed and isolation."""
    with patch('embeddings.get_embedding_service', return_value=mock_embedding_service):
        yield mock_embedding_service


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
