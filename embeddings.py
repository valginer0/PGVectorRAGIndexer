"""
Embedding generation service with caching and batch processing.

Provides efficient embedding generation using sentence transformers
with optional caching and batch processing capabilities.
"""

import logging
import hashlib
from typing import List, Optional, Union
from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

from config import get_config

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """Base exception for embedding errors."""
    pass


class ModelLoadError(EmbeddingError):
    """Exception for model loading errors."""
    pass


class EmbeddingService:
    """
    Service for generating text embeddings.
    
    Provides caching, batch processing, and normalization for
    efficient embedding generation.
    """
    
    def __init__(self):
        """Initialize embedding service."""
        self.config = get_config().embedding
        self._model: Optional[SentenceTransformer] = None
        self._cache_enabled = get_config().cache_embeddings
        self._embedding_cache = {}
    
    @property
    def model(self) -> SentenceTransformer:
        """Lazy load and return the embedding model."""
        if self._model is None:
            self._load_model()
        return self._model
    
    def _load_model(self) -> None:
        """Load the sentence transformer model."""
        try:
            logger.info(f"Loading embedding model: {self.config.model_name}")
            self._model = SentenceTransformer(
                self.config.model_name,
                device=self.config.device
            )
            logger.info(
                f"Model loaded successfully "
                f"(dimension={self.config.dimension}, device={self._model.device})"
            )
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise ModelLoadError(f"Model loading failed: {e}")
    
    def _get_cache_key(self, text: str) -> str:
        """Generate cache key for text."""
        return hashlib.md5(text.encode()).hexdigest()
    
    def _get_from_cache(self, text: str) -> Optional[List[float]]:
        """Get embedding from cache if available."""
        if not self._cache_enabled:
            return None
        
        cache_key = self._get_cache_key(text)
        return self._embedding_cache.get(cache_key)
    
    def _add_to_cache(self, text: str, embedding: List[float]) -> None:
        """Add embedding to cache."""
        if not self._cache_enabled:
            return
        
        cache_key = self._get_cache_key(text)
        self._embedding_cache[cache_key] = embedding
    
    def encode(
        self,
        text: Union[str, List[str]],
        batch_size: Optional[int] = None,
        show_progress: bool = False,
        normalize: Optional[bool] = None
    ) -> Union[List[float], List[List[float]]]:
        """
        Generate embeddings for text or list of texts.
        
        Args:
            text: Single text string or list of texts
            batch_size: Batch size for processing (uses config default if None)
            show_progress: Show progress bar for batch processing
            normalize: Normalize embeddings (uses config default if None)
            
        Returns:
            Single embedding or list of embeddings
            
        Raises:
            EmbeddingError: If embedding generation fails
        """
        is_single = isinstance(text, str)
        texts = [text] if is_single else text
        
        if not texts:
            return [] if not is_single else []
        
        # Use config defaults if not specified
        batch_size = batch_size or self.config.batch_size
        normalize = normalize if normalize is not None else self.config.normalize_embeddings
        
        # Check cache for single text
        if is_single and self._cache_enabled:
            cached = self._get_from_cache(texts[0])
            if cached is not None:
                logger.debug(f"Cache hit for text: {texts[0][:50]}...")
                return cached
        
        try:
            # Generate embeddings
            embeddings = self.model.encode(
                texts,
                batch_size=batch_size,
                show_progress_bar=show_progress,
                normalize_embeddings=normalize,
                convert_to_numpy=True
            )
            
            # Convert to list format
            if is_single:
                embedding = embeddings.tolist()
                self._add_to_cache(texts[0], embedding)
                return embedding
            else:
                embedding_list = embeddings.tolist()
                # Cache individual embeddings
                for text, emb in zip(texts, embedding_list):
                    self._add_to_cache(text, emb)
                return embedding_list
                
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            raise EmbeddingError(f"Failed to generate embeddings: {e}")
    
    def encode_batch(
        self,
        texts: List[str],
        batch_size: Optional[int] = None,
        show_progress: bool = True
    ) -> List[List[float]]:
        """
        Generate embeddings for a batch of texts.
        
        Args:
            texts: List of text strings
            batch_size: Batch size for processing
            show_progress: Show progress bar
            
        Returns:
            List of embeddings
        """
        return self.encode(texts, batch_size=batch_size, show_progress=show_progress)
    
    def similarity(
        self,
        embedding1: Union[List[float], np.ndarray],
        embedding2: Union[List[float], np.ndarray],
        metric: str = 'cosine'
    ) -> float:
        """
        Calculate similarity between two embeddings.
        
        Args:
            embedding1: First embedding
            embedding2: Second embedding
            metric: Similarity metric ('cosine', 'dot', 'euclidean')
            
        Returns:
            Similarity score
        """
        emb1 = np.array(embedding1)
        emb2 = np.array(embedding2)
        
        if metric == 'cosine':
            # Cosine similarity
            return float(np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2)))
        elif metric == 'dot':
            # Dot product
            return float(np.dot(emb1, emb2))
        elif metric == 'euclidean':
            # Negative euclidean distance (higher is more similar)
            return float(-np.linalg.norm(emb1 - emb2))
        else:
            raise ValueError(f"Unknown metric: {metric}")
    
    def clear_cache(self) -> int:
        """
        Clear embedding cache.
        
        Returns:
            Number of cached items cleared
        """
        count = len(self._embedding_cache)
        self._embedding_cache.clear()
        logger.info(f"Cleared {count} cached embeddings")
        return count
    
    def get_cache_size(self) -> int:
        """Get number of cached embeddings."""
        return len(self._embedding_cache)
    
    def get_model_info(self) -> dict:
        """
        Get information about the loaded model.
        
        Returns:
            Dictionary with model information
        """
        return {
            "model_name": self.config.model_name,
            "dimension": self.config.dimension,
            "device": str(self.model.device) if self._model else None,
            "max_seq_length": self.model.max_seq_length if self._model else None,
            "cache_enabled": self._cache_enabled,
            "cache_size": self.get_cache_size(),
            "normalize_embeddings": self.config.normalize_embeddings
        }


# Global embedding service instance
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Get or create global embedding service instance."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


def encode_text(text: Union[str, List[str]], **kwargs) -> Union[List[float], List[List[float]]]:
    """
    Convenience function to encode text using global service.
    
    Args:
        text: Text or list of texts to encode
        **kwargs: Additional arguments passed to encode()
        
    Returns:
        Embedding or list of embeddings
    """
    service = get_embedding_service()
    return service.encode(text, **kwargs)
