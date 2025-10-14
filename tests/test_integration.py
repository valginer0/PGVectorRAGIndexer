"""
Integration tests for PGVectorRAGIndexer.

Tests the full workflow: index document -> search -> retrieve results.
"""

import pytest
import os
import tempfile
from pathlib import Path

from config import get_config
from database import get_db_manager, DocumentRepository
from document_processor import DocumentProcessor
from embeddings import EmbeddingService


@pytest.fixture(scope="module")
def config():
    """Load configuration."""
    return get_config()


@pytest.fixture(scope="module")
def db_manager():
    """Create database manager."""
    manager = get_db_manager()
    yield manager
    manager.close()


@pytest.fixture(scope="module")
def repository(db_manager):
    """Create document repository."""
    return DocumentRepository(db_manager)


@pytest.fixture(scope="module")
def processor():
    """Create document processor."""
    return DocumentProcessor()


@pytest.fixture(scope="module")
def embedding_service():
    """Create embedding service."""
    return EmbeddingService()


@pytest.fixture
def test_document():
    """Create a temporary test document."""
    content = """
    Machine Learning and Artificial Intelligence
    
    Machine learning is a subset of artificial intelligence that enables
    computers to learn from data without being explicitly programmed.
    
    Deep learning is a type of machine learning that uses neural networks
    with multiple layers to process complex patterns in data.
    
    Natural language processing (NLP) is a field of AI that focuses on
    the interaction between computers and human language.
    """
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(content)
        temp_path = f.name
    
    yield temp_path
    
    # Cleanup
    if os.path.exists(temp_path):
        os.unlink(temp_path)


class TestIndexAndRetrieve:
    """Test full indexing and retrieval workflow."""
    
    def test_index_document(self, processor, repository, embedding_service, test_document):
        """Test indexing a document."""
        # Process document
        processed_doc = processor.process(test_document)
        
        assert processed_doc is not None
        assert processed_doc.document_id is not None
        assert len(processed_doc.chunks) > 0
        assert processed_doc.source_uri == test_document
        
        # Generate embeddings
        embeddings = embedding_service.encode(
            [chunk.text_content for chunk in processed_doc.chunks]
        )
        
        assert len(embeddings) == len(processed_doc.chunks)
        assert all(len(emb) == 384 for emb in embeddings)  # all-MiniLM-L6-v2 dimension
        
        # Store in database
        for chunk, embedding in zip(processed_doc.chunks, embeddings):
            chunk.embedding = embedding
        
        repository.insert_chunks(processed_doc.chunks)
        
        # Verify document exists
        assert repository.document_exists(processed_doc.document_id)
        
        # Store document_id for cleanup
        self.test_doc_id = processed_doc.document_id
    
    def test_search_indexed_document(self, repository, embedding_service):
        """Test searching for the indexed document."""
        # Generate query embedding
        query = "machine learning and neural networks"
        query_embedding = embedding_service.encode([query])[0]
        
        # Search
        results = repository.search_similar(
            query_embedding=query_embedding,
            top_k=5,
            distance_metric='cosine'
        )
        
        assert len(results) > 0
        assert results[0]['distance'] < 1.0  # Should have reasonable similarity
        
        # Verify result contains expected content
        found_ml_content = any(
            'machine learning' in result['text_content'].lower()
            for result in results
        )
        assert found_ml_content, "Should find content about machine learning"
    
    def test_search_with_filters(self, repository, embedding_service):
        """Test searching with document filters."""
        query = "artificial intelligence"
        query_embedding = embedding_service.encode([query])[0]
        
        # Search with document_id filter
        results = repository.search_similar(
            query_embedding=query_embedding,
            top_k=5,
            filters={'document_id': self.test_doc_id}
        )
        
        assert len(results) > 0
        assert all(r['document_id'] == self.test_doc_id for r in results)
    
    def test_hybrid_search(self, repository, embedding_service):
        """Test hybrid search (vector + full-text)."""
        query = "deep learning neural"
        query_embedding = embedding_service.encode([query])[0]
        
        # Hybrid search
        results = repository.hybrid_search(
            query_text=query,
            query_embedding=query_embedding,
            top_k=5,
            alpha=0.5
        )
        
        assert len(results) > 0
        assert 'score' in results[0]
    
    def test_get_document_chunks(self, repository):
        """Test retrieving all chunks for a document."""
        chunks = repository.get_document_chunks(self.test_doc_id)
        
        assert len(chunks) > 0
        assert all(c['document_id'] == self.test_doc_id for c in chunks)
    
    def test_delete_document(self, repository):
        """Test deleting the indexed document."""
        # Delete
        deleted = repository.delete_document(self.test_doc_id)
        assert deleted > 0
        
        # Verify deletion
        assert not repository.document_exists(self.test_doc_id)
        chunks = repository.get_document_chunks(self.test_doc_id)
        assert len(chunks) == 0


class TestDatabaseQueries:
    """Test database query functionality."""
    
    def test_list_documents(self, repository):
        """Test listing all documents."""
        docs = repository.list_documents()
        assert isinstance(docs, list)
    
    def test_get_statistics(self, repository):
        """Test getting database statistics."""
        stats = repository.get_statistics()
        
        assert 'total_documents' in stats
        assert 'total_chunks' in stats
        assert isinstance(stats['total_documents'], int)
        assert isinstance(stats['total_chunks'], int)


class TestEmbeddingConsistency:
    """Test embedding generation consistency."""
    
    def test_same_text_same_embedding(self, embedding_service):
        """Test that same text produces same embedding."""
        text = "This is a test sentence."
        
        emb1 = embedding_service.encode([text])[0]
        emb2 = embedding_service.encode([text])[0]
        
        # Should be identical (or very close due to floating point)
        import numpy as np
        assert np.allclose(emb1, emb2, rtol=1e-5)
    
    def test_embedding_dimension(self, embedding_service):
        """Test embedding has correct dimension."""
        text = "Test text"
        embedding = embedding_service.encode([text])[0]
        
        assert len(embedding) == 384  # all-MiniLM-L6-v2 dimension
    
    def test_batch_embedding(self, embedding_service):
        """Test batch embedding generation."""
        texts = [
            "First sentence",
            "Second sentence",
            "Third sentence"
        ]
        
        embeddings = embedding_service.encode(texts)
        
        assert len(embeddings) == 3
        assert all(len(emb) == 384 for emb in embeddings)
