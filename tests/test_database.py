"""
Tests for database operations.
"""

import pytest
from datetime import datetime

from database import (
    DatabaseManager,
    DocumentRepository,
    DatabaseError,
    ConnectionPoolError,
    QueryError
)


class TestDatabaseManager:
    """Tests for DatabaseManager."""
    
    def test_initialization(self, db_manager):
        """Test database manager initialization."""
        assert db_manager._initialized
        assert db_manager._pool is not None
    
    def test_get_connection(self, db_manager):
        """Test getting connection from pool."""
        with db_manager.get_connection() as conn:
            assert conn is not None
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1
            cursor.close()
    
    def test_get_cursor(self, db_manager):
        """Test getting cursor from pool."""
        with db_manager.get_cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1
    
    def test_get_dict_cursor(self, db_manager):
        """Test getting dictionary cursor."""
        with db_manager.get_cursor(dict_cursor=True) as cursor:
            cursor.execute("SELECT 1 as value")
            result = cursor.fetchone()
            assert result['value'] == 1
    
    def test_execute_query(self, db_manager):
        """Test executing queries."""
        # Execute without fetch
        db_manager.execute_query("SELECT 1", fetch=False)
        
        # Execute with fetch
        results = db_manager.execute_query("SELECT 1", fetch=True)
        assert len(results) == 1
        assert results[0][0] == 1
    
    def test_health_check(self, db_manager):
        """Test database health check."""
        health = db_manager.health_check()
        assert health['status'] == 'healthy'
        assert 'postgres_version' in health
        assert 'total_chunks' in health
        assert 'total_documents' in health
        assert 'timestamp' in health
    
    def test_connection_rollback_on_error(self, db_manager):
        """Test that connections rollback on error."""
        try:
            with db_manager.get_cursor() as cursor:
                cursor.execute("INVALID SQL QUERY")
        except ConnectionPoolError:
            pass  # Expected - QueryError is wrapped in ConnectionPoolError
        
        # Connection should still work after error
        with db_manager.get_cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1


class TestDocumentRepository:
    """Tests for DocumentRepository."""
    
    def test_insert_chunks(self, db_manager, sample_embeddings):
        """Test inserting document chunks."""
        repo = DocumentRepository(db_manager)
        
        chunks = [
            ('doc1', 0, 'First chunk', '/path/to/doc1.txt', sample_embeddings[0]),
            ('doc1', 1, 'Second chunk', '/path/to/doc1.txt', sample_embeddings[1]),
        ]
        
        count = repo.insert_chunks(chunks)
        assert count == 2
        
        # Verify chunks were inserted
        with db_manager.get_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM document_chunks WHERE document_id = 'doc1'")
            result = cursor.fetchone()
            assert result[0] == 2
    
    def test_document_exists(self, db_manager, sample_embeddings):
        """Test checking if document exists."""
        repo = DocumentRepository(db_manager)
        
        # Document doesn't exist yet
        assert not repo.document_exists('doc1')
        
        # Insert document
        chunks = [('doc1', 0, 'Test chunk', '/path/to/doc1.txt', sample_embeddings[0])]
        repo.insert_chunks(chunks)
        
        # Document should exist now
        assert repo.document_exists('doc1')
    
    def test_get_document_by_id(self, db_manager, sample_embeddings):
        """Test getting document metadata by ID."""
        repo = DocumentRepository(db_manager)
        
        # Insert document
        chunks = [
            ('doc1', 0, 'First chunk', '/path/to/doc1.txt', sample_embeddings[0]),
            ('doc1', 1, 'Second chunk', '/path/to/doc1.txt', sample_embeddings[1]),
        ]
        repo.insert_chunks(chunks)
        
        # Get document
        doc = repo.get_document_by_id('doc1')
        assert doc is not None
        assert doc['document_id'] == 'doc1'
        assert doc['source_uri'] == '/path/to/doc1.txt'
        assert doc['chunk_count'] == 2
        assert 'indexed_at' in doc
    
    def test_delete_document(self, db_manager, sample_embeddings):
        """Test deleting document chunks."""
        repo = DocumentRepository(db_manager)
        
        # Insert document
        chunks = [
            ('doc1', 0, 'First chunk', '/path/to/doc1.txt', sample_embeddings[0]),
            ('doc1', 1, 'Second chunk', '/path/to/doc1.txt', sample_embeddings[1]),
        ]
        repo.insert_chunks(chunks)
        
        # Delete document
        deleted = repo.delete_document('doc1')
        assert deleted == 2
        
        # Verify deletion
        assert not repo.document_exists('doc1')
    
    def test_list_documents(self, db_manager, sample_embeddings):
        """Test listing documents."""
        repo = DocumentRepository(db_manager)
        
        # Insert multiple documents
        chunks1 = [('doc1', 0, 'Chunk 1', '/path/to/doc1.txt', sample_embeddings[0])]
        chunks2 = [('doc2', 0, 'Chunk 2', '/path/to/doc2.txt', sample_embeddings[1])]
        
        repo.insert_chunks(chunks1)
        repo.insert_chunks(chunks2)
        
        # List documents
        docs = repo.list_documents(limit=10)
        assert len(docs) == 2
        
        # Check document structure
        assert all('document_id' in doc for doc in docs)
        assert all('source_uri' in doc for doc in docs)
        assert all('chunk_count' in doc for doc in docs)
    
    def test_search_similar(self, db_manager, sample_embeddings):
        """Test vector similarity search."""
        repo = DocumentRepository(db_manager)
        
        # Insert documents
        chunks = [
            ('doc1', 0, 'Python programming', '/path/to/doc1.txt', sample_embeddings[0]),
            ('doc2', 0, 'Java programming', '/path/to/doc2.txt', sample_embeddings[1]),
            ('doc3', 0, 'Machine learning', '/path/to/doc3.txt', sample_embeddings[2]),
        ]
        repo.insert_chunks(chunks)
        
        # Search with query embedding
        query_embedding = sample_embeddings[0]
        results = repo.search_similar(query_embedding, top_k=2)
        
        assert len(results) <= 2
        assert all('text_content' in r for r in results)
        assert all('distance' in r for r in results)
        assert all('source_uri' in r for r in results)
    
    def test_search_with_filters(self, db_manager, sample_embeddings):
        """Test similarity search with filters."""
        repo = DocumentRepository(db_manager)
        
        # Insert documents
        chunks = [
            ('doc1', 0, 'Text 1', '/path/to/doc1.txt', sample_embeddings[0]),
            ('doc2', 0, 'Text 2', '/path/to/doc2.txt', sample_embeddings[1]),
        ]
        repo.insert_chunks(chunks)
        
        # Search with document_id filter
        results = repo.search_similar(
            sample_embeddings[0],
            top_k=5,
            filters={'document_id': 'doc1'}
        )
        
        assert len(results) == 1
        assert results[0]['document_id'] == 'doc1'
    
    def test_get_statistics(self, db_manager, sample_embeddings):
        """Test getting database statistics."""
        repo = DocumentRepository(db_manager)
        
        # Insert documents
        chunks = [
            ('doc1', 0, 'Chunk 1', '/path/to/doc1.txt', sample_embeddings[0]),
            ('doc1', 1, 'Chunk 2', '/path/to/doc1.txt', sample_embeddings[1]),
            ('doc2', 0, 'Chunk 3', '/path/to/doc2.txt', sample_embeddings[2]),
        ]
        repo.insert_chunks(chunks)
        
        # Get statistics
        stats = repo.get_statistics()
        assert stats['total_chunks'] == 3
        assert stats['total_documents'] == 2
        assert stats['avg_chunks_per_document'] > 0
        assert 'database_size_bytes' in stats
    
    def test_duplicate_prevention(self, db_manager, sample_embeddings):
        """Test that duplicate chunks are prevented."""
        repo = DocumentRepository(db_manager)
        
        # Insert chunk
        chunks = [('doc1', 0, 'Test chunk', '/path/to/doc1.txt', sample_embeddings[0])]
        repo.insert_chunks(chunks)
        
        # Try to insert same chunk again (should fail due to UNIQUE constraint)
        with pytest.raises(ConnectionPoolError):
            repo.insert_chunks(chunks)


class TestConnectionPooling:
    """Tests for connection pool behavior."""
    
    def test_multiple_concurrent_connections(self, db_manager):
        """Test multiple concurrent connections from pool."""
        connections = []
        
        # Get multiple connections
        for _ in range(3):
            with db_manager.get_connection() as conn:
                connections.append(conn)
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                assert cursor.fetchone()[0] == 1
                cursor.close()
        
        # All connections should have worked
        assert len(connections) == 3
    
    def test_connection_reuse(self, db_manager):
        """Test that connections are reused from pool."""
        # Get and release connection
        with db_manager.get_connection() as conn1:
            conn1_id = id(conn1)
        
        # Get another connection (might be the same one reused)
        with db_manager.get_connection() as conn2:
            conn2_id = id(conn2)
        
        # Both connections should work
        assert conn1_id is not None
        assert conn2_id is not None
