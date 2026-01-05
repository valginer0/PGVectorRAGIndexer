"""
Email Search Retriever (Provider-Agnostic)

Provides semantic search over the email_chunks table.
This module is independent of any email provider (Gmail, Outlook, IMAP).
"""

import logging
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class EmailSearchResult:
    """Container for email search result data."""
    
    chunk_id: int
    message_id: str
    thread_id: Optional[str]
    sender: Optional[str]
    subject: Optional[str]
    received_at: Optional[str]
    chunk_index: int
    text_content: str
    distance: float
    relevance_score: float
    provider: Optional[str] = None
    folder: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def __str__(self) -> str:
        """Format result as string."""
        date_str = self.received_at[:10] if self.received_at else "Unknown"
        return (
            f"Score: {self.relevance_score:.4f} | "
            f"From: {self.sender or 'Unknown'} | Date: {date_str}\n"
            f"Subject: {self.subject or '(No Subject)'}\n"
            f"Text: {self.text_content[:200]}..."
        )
    
    def to_locator(self) -> str:
        """
        Format as locator string for search results.
        
        Format: <Provider>/<Folder>/<Subject> (<From>, <YYYY-MM-DD>)
        Example: Gmail/Inbox/Re: licensing question (Vitaly, 2026-01-02)
        """
        provider = self.provider or "Email"
        folder = self.folder or "Inbox"
        subject = self.subject or "(No Subject)"
        sender_short = self.sender.split()[0] if self.sender else "Unknown"
        date_str = self.received_at[:10] if self.received_at else "Unknown"
        
        # Truncate subject if too long
        if len(subject) > 40:
            subject = subject[:40] + "..."
        
        return f"{provider}/{folder}/{subject} ({sender_short}, {date_str})"


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
    
    logger.info(f"Searching emails for: '{query}' (top_k={top_k})")
    
    # Generate query embedding
    query_embedding = embedding_service.encode(query)
    
    # Vector search on email_chunks table
    query_sql = """
        SELECT 
            id as chunk_id,
            message_id,
            thread_id,
            sender,
            subject,
            received_at,
            chunk_index,
            text_content,
            provider,
            folder,
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
        # Convert distance to relevance score (cosine: 1 - distance)
        relevance_score = max(0.0, 1.0 - distance)
        
        if relevance_score >= min_score:
            results.append(EmailSearchResult(
                chunk_id=result['chunk_id'],
                message_id=result['message_id'],
                thread_id=result['thread_id'],
                sender=result['sender'],
                subject=result['subject'],
                received_at=str(result['received_at']) if result['received_at'] else None,
                chunk_index=result['chunk_index'],
                text_content=result['text_content'],
                distance=distance,
                relevance_score=relevance_score,
                provider=result.get('provider'),
                folder=result.get('folder'),
                metadata=result.get('metadata')
            ))
    
    results = results[:top_k]
    logger.info(f"Found {len(results)} relevant email chunks")
    return results
