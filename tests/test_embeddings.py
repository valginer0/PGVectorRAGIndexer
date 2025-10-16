"""
Tests for embedding service.
"""

import pytest
import numpy as np

from embeddings import EmbeddingService, EmbeddingError, ModelLoadError


class TestEmbeddingService:
    """Tests for EmbeddingService."""
    
    @pytest.fixture
    def embedding_service(self):
        """Create embedding service instance."""
        return EmbeddingService()
    
    def test_model_loading(self, embedding_service):
        """Test that model loads successfully."""
        model = embedding_service.model
        assert model is not None
        assert embedding_service._model is not None
    
    def test_encode_single_text(self, embedding_service):
        """Test encoding a single text."""
        text = "This is a test sentence."
        embedding = embedding_service.encode(text)
        
        assert isinstance(embedding, list)
        assert len(embedding) == embedding_service.config.dimension
        assert all(isinstance(x, float) for x in embedding)
    
    def test_single_text_returns_1d_list(self, embedding_service):
        """Test that single text returns 1D list, not 2D nested list.
        
        Bug: embeddings.tolist() on single text was returning [[...]] instead of [...]
        This caused PostgreSQL vector type errors in search queries.
        """
        text = "Machine learning is a subset of artificial intelligence."
        embedding = embedding_service.encode(text)
        
        # Should be a list
        assert isinstance(embedding, list), f"Expected list, got {type(embedding)}"
        
        # Should have correct dimension
        assert len(embedding) == embedding_service.config.dimension, \
            f"Expected dimension {embedding_service.config.dimension}, got {len(embedding)}"
        
        # First element should be a float, NOT a list (this is the key test)
        assert isinstance(embedding[0], (int, float)), \
            f"Expected first element to be float, got {type(embedding[0])}. " \
            f"This indicates a 2D list [[...]] instead of 1D list [...]"
        
        # All elements should be numbers
        assert all(isinstance(x, (int, float)) for x in embedding), \
            "All elements should be numbers, not nested lists"
    
    def test_encode_multiple_texts(self, embedding_service):
        """Test encoding multiple texts."""
        texts = [
            "First test sentence.",
            "Second test sentence.",
            "Third test sentence."
        ]
        embeddings = embedding_service.encode(texts)
        
        assert isinstance(embeddings, list)
        assert len(embeddings) == 3
        assert all(len(emb) == embedding_service.config.dimension for emb in embeddings)
    
    def test_encode_empty_list(self, embedding_service):
        """Test encoding empty list."""
        embeddings = embedding_service.encode([])
        assert embeddings == []
    
    def test_embedding_caching(self, embedding_service):
        """Test that embeddings are cached."""
        if not embedding_service._cache_enabled:
            pytest.skip("Caching is disabled")
        
        text = "Test sentence for caching."
        
        # First call - should generate embedding
        embedding1 = embedding_service.encode(text)
        cache_size_1 = embedding_service.get_cache_size()
        
        # Second call - should use cache
        embedding2 = embedding_service.encode(text)
        cache_size_2 = embedding_service.get_cache_size()
        
        assert embedding1 == embedding2
        assert cache_size_1 == cache_size_2  # Cache size shouldn't increase
    
    def test_clear_cache(self, embedding_service):
        """Test clearing embedding cache."""
        if not embedding_service._cache_enabled:
            pytest.skip("Caching is disabled")
        
        # Generate some embeddings
        texts = ["Text 1", "Text 2", "Text 3"]
        embedding_service.encode(texts)
        
        initial_size = embedding_service.get_cache_size()
        assert initial_size > 0
        
        # Clear cache
        cleared = embedding_service.clear_cache()
        assert cleared == initial_size
        assert embedding_service.get_cache_size() == 0
    
    def test_batch_encoding(self, embedding_service):
        """Test batch encoding."""
        texts = [f"Test sentence {i}" for i in range(10)]
        embeddings = embedding_service.encode_batch(texts, batch_size=5)
        
        assert len(embeddings) == 10
        assert all(len(emb) == embedding_service.config.dimension for emb in embeddings)
    
    def test_similarity_cosine(self, embedding_service):
        """Test cosine similarity calculation."""
        emb1 = [1.0, 0.0, 0.0]
        emb2 = [1.0, 0.0, 0.0]
        emb3 = [0.0, 1.0, 0.0]
        
        # Identical vectors should have similarity 1.0
        sim1 = embedding_service.similarity(emb1, emb2, metric='cosine')
        assert abs(sim1 - 1.0) < 1e-6
        
        # Orthogonal vectors should have similarity 0.0
        sim2 = embedding_service.similarity(emb1, emb3, metric='cosine')
        assert abs(sim2 - 0.0) < 1e-6
    
    def test_similarity_dot_product(self, embedding_service):
        """Test dot product similarity."""
        emb1 = [1.0, 2.0, 3.0]
        emb2 = [4.0, 5.0, 6.0]
        
        sim = embedding_service.similarity(emb1, emb2, metric='dot')
        expected = 1*4 + 2*5 + 3*6  # 32
        assert abs(sim - expected) < 1e-6
    
    def test_similarity_euclidean(self, embedding_service):
        """Test euclidean distance similarity."""
        emb1 = [0.0, 0.0, 0.0]
        emb2 = [0.0, 0.0, 0.0]
        
        # Identical vectors should have distance 0 (similarity 0)
        sim = embedding_service.similarity(emb1, emb2, metric='euclidean')
        assert abs(sim - 0.0) < 1e-6
    
    def test_similarity_invalid_metric(self, embedding_service):
        """Test invalid similarity metric."""
        emb1 = [1.0, 0.0, 0.0]
        emb2 = [0.0, 1.0, 0.0]
        
        with pytest.raises(ValueError):
            embedding_service.similarity(emb1, emb2, metric='invalid')
    
    def test_get_model_info(self, embedding_service):
        """Test getting model information."""
        # Trigger model loading
        _ = embedding_service.model
        
        info = embedding_service.get_model_info()
        assert 'model_name' in info
        assert 'dimension' in info
        assert 'device' in info
        assert 'max_seq_length' in info
        assert 'cache_enabled' in info
        assert info['dimension'] == embedding_service.config.dimension
    
    def test_normalization(self, embedding_service):
        """Test embedding normalization."""
        text = "Test sentence for normalization."
        
        # Get normalized embedding
        embedding = embedding_service.encode(text, normalize=True)
        
        # Check that it's normalized (L2 norm should be ~1.0)
        norm = np.linalg.norm(embedding)
        assert abs(norm - 1.0) < 1e-5
    
    def test_semantic_similarity(self, embedding_service):
        """Test that semantically similar texts have similar embeddings."""
        text1 = "The cat sits on the mat."
        text2 = "A cat is sitting on a mat."
        text3 = "Python is a programming language."
        
        emb1 = embedding_service.encode(text1)
        emb2 = embedding_service.encode(text2)
        emb3 = embedding_service.encode(text3)
        
        # Similar sentences should have higher similarity
        sim_similar = embedding_service.similarity(emb1, emb2, metric='cosine')
        sim_different = embedding_service.similarity(emb1, emb3, metric='cosine')
        
        assert sim_similar > sim_different


class TestEmbeddingServiceGlobalInstance:
    """Tests for global embedding service instance."""
    
    def test_get_embedding_service(self):
        """Test getting global service instance."""
        from embeddings import get_embedding_service
        
        service1 = get_embedding_service()
        service2 = get_embedding_service()
        
        # Should return same instance
        assert service1 is service2
    
    def test_encode_text_convenience_function(self):
        """Test convenience function for encoding."""
        from embeddings import encode_text
        
        text = "Test sentence."
        embedding = encode_text(text)
        
        assert isinstance(embedding, list)
        assert len(embedding) > 0


class TestEmbeddingDimensions:
    """Tests for different embedding dimensions."""
    
    @pytest.fixture
    def embedding_service(self):
        """Create embedding service instance."""
        return EmbeddingService()
    
    def test_correct_dimension(self, embedding_service):
        """Test that embeddings have correct dimension."""
        text = "Test sentence."
        embedding = embedding_service.encode(text)
        
        expected_dim = embedding_service.config.dimension
        assert len(embedding) == expected_dim
    
    def test_consistent_dimensions(self, embedding_service):
        """Test that all embeddings have consistent dimensions."""
        texts = ["Text 1", "Text 2", "Text 3"]
        embeddings = embedding_service.encode(texts)
        
        dimensions = [len(emb) for emb in embeddings]
        assert len(set(dimensions)) == 1  # All should have same dimension
