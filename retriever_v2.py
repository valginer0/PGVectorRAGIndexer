"""
Improved retriever with hybrid search, filtering, and better result formatting.

This is the v2 retriever that uses the new modular architecture.
"""

import argparse
import logging
import sys
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from config import get_config
from database import get_db_manager, DocumentRepository
from embeddings import get_embedding_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Container for search result data."""
    
    chunk_id: int
    document_id: str
    chunk_index: int
    text_content: str
    source_uri: str
    distance: float
    relevance_score: float
    metadata: Optional[Dict[str, Any]] = None
    document_type: Optional[str] = None
    
    def __str__(self) -> str:
        """Format result as string."""
        return (
            f"Score: {self.relevance_score:.4f} | "
            f"Source: {self.source_uri} (Chunk #{self.chunk_index})\n"
            f"Text: {self.text_content[:200]}..."
        )


class DocumentRetriever:
    """
    Main retriever class for semantic search.
    
    Supports vector search, hybrid search, and filtering.
    """
    
    def __init__(self):
        """Initialize retriever with required services."""
        self.config = get_config()
        self.db_manager = get_db_manager()
        self.repository = DocumentRepository(self.db_manager)
        self.embedding_service = get_embedding_service()
    
    def _calculate_relevance_score(self, distance: float, metric: str = 'cosine') -> float:
        """
        Convert distance to relevance score (0-1, higher is better).
        
        Args:
            distance: Distance value from database
            metric: Distance metric used
            
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
    
    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        min_score: Optional[float] = None
    ) -> List[SearchResult]:
        """
        Search for relevant document chunks.
        
        Args:
            query: Search query text
            top_k: Number of results to return (uses config default if None)
            filters: Optional filters (e.g., {'document_id': 'abc123'})
            min_score: Minimum relevance score (0-1)
            
        Returns:
            List of SearchResult objects
        """
        # Use config defaults if not specified
        top_k = top_k if top_k is not None else self.config.retrieval.top_k
        min_score = min_score if min_score is not None else self.config.retrieval.similarity_threshold
        distance_metric = self.config.retrieval.distance_metric
        
        logger.info(f"Searching for: '{query}' (top_k={top_k}, metric={distance_metric})")
        
        # Generate query embedding
        query_embedding = self.embedding_service.encode(query)
        
        # Perform vector search
        raw_results = self.repository.search_similar(
            query_embedding=query_embedding,
            top_k=top_k * 2,  # Get more results for filtering
            distance_metric=distance_metric,
            filters=filters
        )
        
        # Convert to SearchResult objects with relevance scores
        results = []
        for result in raw_results:
            relevance_score = self._calculate_relevance_score(
                result['distance'],
                distance_metric
            )
            
            # Filter by minimum score
            if relevance_score >= min_score:
                results.append(SearchResult(
                    chunk_id=result['chunk_id'],
                    document_id=result['document_id'],
                    chunk_index=result['chunk_index'],
                    text_content=result['text_content'],
                    source_uri=result['source_uri'],
                    distance=result['distance'],
                    relevance_score=relevance_score,
                    metadata=result.get('metadata'),
                    document_type=result.get('metadata', {}).get('type')
                ))
        
        # Limit to top_k after filtering
        results = results[:top_k]
        
        logger.info(f"Found {len(results)} relevant chunks")
        return results
    
    def search_hybrid(
        self,
        query: str,
        top_k: Optional[int] = None,
        alpha: Optional[float] = None
    ) -> List[SearchResult]:
        """
        Hybrid search combining vector and full-text search.
        
        Args:
            query: Search query text
            top_k: Number of results to return
            alpha: Weight for vector search (0=full-text only, 1=vector only)
            
        Returns:
            List of SearchResult objects
        """
        top_k = top_k or self.config.retrieval.top_k
        alpha = alpha if alpha is not None else self.config.retrieval.hybrid_alpha
        
        logger.info(f"Hybrid search for: '{query}' (alpha={alpha})")
        
        # Generate query embedding for vector search
        query_embedding = self.embedding_service.encode(query)
        
        # Perform hybrid search using PostgreSQL
        query_sql = """
        WITH vector_search AS (
            SELECT 
                chunk_id,
                document_id,
                chunk_index,
                text_content,
                source_uri,
                embedding <=> %s AS vector_distance,
                ROW_NUMBER() OVER (ORDER BY embedding <=> %s) AS vector_rank
            FROM document_chunks
        ),
        fulltext_search AS (
            SELECT 
                chunk_id,
                ts_rank_cd(to_tsvector('english', text_content), plainto_tsquery('english', %s)) AS text_score,
                ROW_NUMBER() OVER (ORDER BY ts_rank_cd(to_tsvector('english', text_content), plainto_tsquery('english', %s)) DESC) AS text_rank
            FROM document_chunks
            WHERE to_tsvector('english', text_content) @@ plainto_tsquery('english', %s)
        )
        SELECT 
            v.chunk_id,
            v.document_id,
            v.chunk_index,
            v.text_content,
            v.source_uri,
            v.vector_distance,
            COALESCE(f.text_score, 0) AS text_score,
            (%s * (1.0 / NULLIF(v.vector_rank, 0)) + %s * (1.0 / NULLIF(f.text_rank, 0))) AS combined_score
        FROM vector_search v
        LEFT JOIN fulltext_search f ON v.chunk_id = f.chunk_id
        ORDER BY combined_score DESC
        LIMIT %s
        """
        
        with self.db_manager.get_cursor(dict_cursor=True) as cursor:
            cursor.execute(
                query_sql,
                (query_embedding, query_embedding, query, query, query, alpha, 1 - alpha, top_k)
            )
            raw_results = cursor.fetchall()
        
        # Convert to SearchResult objects
        results = []
        for result in raw_results:
            relevance_score = self._calculate_relevance_score(
                result['vector_distance'],
                self.config.retrieval.distance_metric
            )
            
            results.append(SearchResult(
                chunk_id=result['chunk_id'],
                document_id=result['document_id'],
                chunk_index=result['chunk_index'],
                text_content=result['text_content'],
                source_uri=result['source_uri'],
                distance=result['vector_distance'],
                relevance_score=relevance_score
            ))
        
        logger.info(f"Found {len(results)} relevant chunks (hybrid)")
        return results
    
    def get_context(
        self,
        query: str,
        top_k: Optional[int] = None,
        use_hybrid: bool = False
    ) -> str:
        """
        Get concatenated context from search results for RAG.
        
        Args:
            query: Search query
            top_k: Number of results
            use_hybrid: Use hybrid search
            
        Returns:
            Concatenated context string
        """
        if use_hybrid and self.config.retrieval.enable_hybrid_search:
            results = self.search_hybrid(query, top_k)
        else:
            results = self.search(query, top_k)
        
        if not results:
            return ""
        
        # Build context with source attribution
        context_parts = []
        for i, result in enumerate(results, 1):
            context_parts.append(
                f"[Source {i}: {result.source_uri}, Chunk {result.chunk_index}]\n"
                f"{result.text_content}\n"
            )
        
        return "\n".join(context_parts)


def format_results(results: List[SearchResult], verbose: bool = False) -> str:
    """
    Format search results for display.
    
    Args:
        results: List of SearchResult objects
        verbose: Show full text if True
        
    Returns:
        Formatted string
    """
    if not results:
        return "\nNo relevant results found."
    
    output = [f"\nFound {len(results)} relevant results:\n"]
    output.append("=" * 80)
    
    for i, result in enumerate(results, 1):
        output.append(f"\n[Result {i}]")
        output.append(f"Relevance Score: {result.relevance_score:.4f}")
        output.append(f"Source: {result.source_uri}")
        output.append(f"Chunk: #{result.chunk_index}")
        output.append(f"Distance: {result.distance:.4f}")
        
        if verbose:
            output.append(f"\nFull Text:\n{result.text_content}")
        else:
            preview = result.text_content[:300].replace('\n', ' ')
            output.append(f"\nPreview: {preview}...")
        
        output.append("-" * 80)
    
    return "\n".join(output)


def main():
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description='PGVectorRAGIndexer v2 - Search indexed documents',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic search
  python retriever_v2.py "What is machine learning?"
  
  # Search with custom top_k
  python retriever_v2.py "Python programming" --top-k 10
  
  # Hybrid search (vector + full-text)
  python retriever_v2.py "database optimization" --hybrid
  
  # Search with minimum score threshold
  python retriever_v2.py "neural networks" --min-score 0.8
  
  # Verbose output (show full text)
  python retriever_v2.py "data science" --verbose
  
  # Get context for RAG
  python retriever_v2.py "explain transformers" --context
        """
    )
    
    parser.add_argument(
        'query',
        type=str,
        help='Search query text'
    )
    parser.add_argument(
        '--top-k',
        type=int,
        help='Number of results to return (default: from config)'
    )
    parser.add_argument(
        '--min-score',
        type=float,
        help='Minimum relevance score 0-1 (default: from config)'
    )
    parser.add_argument(
        '--hybrid',
        action='store_true',
        help='Use hybrid search (vector + full-text)'
    )
    parser.add_argument(
        '--alpha',
        type=float,
        help='Hybrid search weight for vector search (0-1, default: 0.5)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show full text of results'
    )
    parser.add_argument(
        '--context',
        action='store_true',
        help='Output as concatenated context for RAG'
    )
    parser.add_argument(
        '--filter-doc',
        type=str,
        help='Filter by document ID'
    )
    
    args = parser.parse_args()
    
    # Initialize retriever
    try:
        retriever = DocumentRetriever()
    except Exception as e:
        logger.error(f"Failed to initialize retriever: {e}")
        sys.exit(1)
    
    # Execute search
    try:
        # Build filters
        filters = {}
        if args.filter_doc:
            filters['document_id'] = args.filter_doc
        
        # Perform search
        if args.context:
            # Get context for RAG
            context = retriever.get_context(
                args.query,
                top_k=args.top_k,
                use_hybrid=args.hybrid
            )
            print(context)
        else:
            # Regular search
            if args.hybrid:
                results = retriever.search_hybrid(
                    args.query,
                    top_k=args.top_k,
                    alpha=args.alpha
                )
            else:
                results = retriever.search(
                    args.query,
                    top_k=args.top_k,
                    filters=filters if filters else None,
                    min_score=args.min_score
                )
            
            # Display results
            output = format_results(results, verbose=args.verbose)
            print(output)
    
    except KeyboardInterrupt:
        print("\n\nSearch cancelled by user.")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Search failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
