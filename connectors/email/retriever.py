"""
Email Search Retriever (Provider-Agnostic)

Provides semantic search over the email_chunks table.
This module is independent of any email provider (Gmail, Outlook, IMAP).

Design: Emails are treated like documents - source_uri contains the locator string
that was built at index time. No provider-specific logic needed at search time.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


def _calculate_relevance_score(distance: float, metric: str = 'cosine') -> float:
    """
    Convert distance to relevance score (0-1, higher is better).
    
    This is the same logic used by DocumentRetriever to ensure
    consistent threshold behavior across documents and emails.
    
    Args:
        distance: Distance value from database
        metric: Distance metric used ('cosine', 'l2', etc.)
        
    Returns:
        Relevance score between 0 and 1
    """
    if metric == 'cosine':
        # Cosine distance is 1 - cosine_similarity
        # So similarity = 1 - distance
        return max(0.0, min(1.0, 1.0 - distance))
    elif metric == 'l2':
        # Convert L2 distance to similarity (inverse relationship)
        # Use exponential decay
        return max(0.0, min(1.0, 1.0 / (1.0 + distance)))
    else:
        # Default: assume lower distance is better
        return max(0.0, min(1.0, 1.0 / (1.0 + distance)))


@dataclass
class EmailSearchResult:
    """
    Container for email search result data.
    
    Follows the same pattern as SearchResult for documents.
    source_uri is the locator (built at index time).
    """
    
    chunk_id: int
    message_id: str
    source_uri: str  # Locator: Provider/Folder/Subject (Sender, Date)
    chunk_index: int
    text_content: str
    distance: float
    relevance_score: float
    thread_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def __str__(self) -> str:
        """Format result as string (same format as document results)."""
        return (
            f"Score: {self.relevance_score:.4f} | "
            f"Source: {self.source_uri} (Chunk #{self.chunk_index})\n"
            f"Text: {self.text_content[:200]}..."
        )


def search_emails(
    db_manager,
    embedding_service,
    config,
    query: str,
    top_k: Optional[int] = None,
    min_score: Optional[float] = None
) -> List[EmailSearchResult]:
    """
    Search for relevant email chunks.
    
    This queries the email_chunks table (separate from documents).
    Only works if EMAIL_ENABLED=true.
    
    Args:
        db_manager: Database connection manager
        embedding_service: Embedding service for query encoding
        config: Application configuration
        query: Search query text
        top_k: Number of results to return
        min_score: Minimum relevance score (0-1)
        
    Returns:
        List of EmailSearchResult objects
    """
    # Check if email is enabled
    if not config.email.enabled:
        logger.warning("Email search called but EMAIL_ENABLED=false")
        return []
    
    top_k = top_k if top_k is not None else config.retrieval.top_k
    min_score = min_score if min_score is not None else config.retrieval.similarity_threshold
    distance_metric = config.retrieval.distance_metric
    
    logger.info(f"Searching emails for: '{query}' (top_k={top_k})")
    
    # Generate query embedding
    query_embedding = embedding_service.encode(query)
    
    # Vector search on email_chunks table
    # Note: source_uri is the locator, built at index time
    query_sql = """
        SELECT 
            id as chunk_id,
            message_id,
            thread_id,
            source_uri,
            chunk_index,
            text_content,
            embedding <=> %s::vector AS distance,
            metadata
        FROM email_chunks
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    
    with db_manager.get_cursor(dict_cursor=True) as cursor:
        cursor.execute(query_sql, [query_embedding, query_embedding, top_k * 2])
        raw_results = cursor.fetchall()
    
    # Convert to EmailSearchResult objects
    results = []
    for result in raw_results:
        distance = result['distance']
        # Use same conversion as DocumentRetriever for consistent thresholds
        relevance_score = _calculate_relevance_score(distance, distance_metric)
        
        if relevance_score >= min_score:
            results.append(EmailSearchResult(
                chunk_id=result['chunk_id'],
                message_id=result['message_id'],
                thread_id=result['thread_id'],
                source_uri=result['source_uri'],
                chunk_index=result['chunk_index'],
                text_content=result['text_content'],
                distance=distance,
                relevance_score=relevance_score,
                metadata=result.get('metadata')
            ))
    
    results = results[:top_k]
    logger.info(f"Found {len(results)} relevant email chunks")
    return results
