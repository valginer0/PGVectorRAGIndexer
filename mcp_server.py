#!/usr/bin/env python3
"""
MCP Server for PGVectorRAGIndexer.

This script implements the Model Context Protocol (MCP) to allow AI agents
(like Claude Desktop, Cursor, etc.) to securely interact with the local
PGVectorRAGIndexer instance via stdio.

It exposes tools to:
1. Search documents (semantic/hybrid)
2. Index new documents
3. List available documents
"""

import sys
import os
import logging
from typing import List, Optional, Any

# Configure logging to stderr so it doesn't interfere with JSON-RPC on stdout
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger("mcp_server")

# Lazy imports - only loaded when actually running the server
_retriever = None
_indexer = None
_db_manager = None
_DocumentRepository = None


def _get_retriever():
    """Lazy import and get retriever."""
    global _retriever
    if _retriever is None:
        from api import get_retriever
        _retriever = get_retriever
    return _retriever()


def _get_indexer():
    """Lazy import and get indexer."""
    global _indexer
    if _indexer is None:
        from api import get_indexer
        _indexer = get_indexer
    return _indexer()


def _get_db_manager():
    """Lazy import and get db manager."""
    global _db_manager
    if _db_manager is None:
        from api import get_db_manager
        _db_manager = get_db_manager
    return _db_manager()


def _get_document_repository():
    """Lazy import DocumentRepository class."""
    global _DocumentRepository
    if _DocumentRepository is None:
        from core.database import DocumentRepository
        _DocumentRepository = DocumentRepository
    return _DocumentRepository


# ================ TOOL IMPLEMENTATIONS ================
# These are the actual functions that can be tested independently


def search_documents_impl(query: str, top_k: int = 5, use_hybrid: bool = False) -> str:
    """
    Search for relevant documents using semantic or hybrid search.
    
    Args:
        query: The search query string
        top_k: Number of results to return (default: 5)
        use_hybrid: Whether to use hybrid search (vector + keyword) (default: False)
        
    Returns:
        A formatted string containing the top matching document chunks.
    """
    logger.info(f"Searching: query='{query}', top_k={top_k}, hybrid={use_hybrid}")
    
    try:
        ret = _get_retriever()
        
        if use_hybrid:
            results = ret.search_hybrid(query=query, top_k=top_k)
        else:
            results = ret.search(query=query, top_k=top_k)
            
        if not results:
            return "No matching documents found."
            
        # Format results for the LLM
        output = [f"Found {len(results)} relevant results for '{query}':\n"]
        
        for i, res in enumerate(results, 1):
            source = res.metadata.get('source_uri', 'Unknown source')
            score = res.relevance_score if res.relevance_score else res.distance
            
            output.append(f"--- Result {i} (Score: {score:.3f}) ---")
            output.append(f"Source: {source}")
            output.append(f"Content: {res.text_content.strip()}")
            output.append("")
            
        return "\n".join(output)
        
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return f"Error performing search: {str(e)}"


def index_document_impl(path: str, force: bool = False) -> str:
    """
    Index a local document (PDF, TXT, MD, etc.).
    
    Args:
        path: Absolute path to the file to index
        force: Whether to force re-indexing if already exists (default: False)
        
    Returns:
        Status message about the indexing operation.
    """
    logger.info(f"Indexing: path='{path}', force={force}")
    
    try:
        idx = _get_indexer()
        
        # Check if file exists
        if not os.path.exists(path):
            return f"Error: File not found at {path}"
            
        result = idx.index_document(
            source_uri=path,
            force_reindex=force
        )
        
        if result['status'] == 'error':
            return f"Failed to index: {result.get('message', 'Unknown error')}"
            
        chunks = result.get('chunks_indexed', 0)
        doc_id = result.get('document_id', 'unknown')
        
        return f"Successfully indexed '{path}'. Document ID: {doc_id}. Chunks: {chunks}."
        
    except Exception as e:
        logger.error(f"Indexing failed: {e}")
        return f"Error indexing document: {str(e)}"


def list_documents_impl(limit: int = 20) -> str:
    """
    List recently indexed documents.
    
    Args:
        limit: Maximum number of documents to list (default: 20)
        
    Returns:
        Formatted list of documents.
    """
    logger.info(f"Listing documents: limit={limit}")
    
    try:
        db = _get_db_manager()
        DocumentRepository = _get_document_repository()
        repo = DocumentRepository(db)
        
        docs, total = repo.list_documents(limit=limit, with_total=True)
        
        if not docs:
            return "No documents found in the index."
            
        output = [f"Total Documents: {total} (Showing top {len(docs)})", ""]
        
        for doc in docs:
            # Clean up timestamp
            indexed_at = doc['indexed_at']
            if hasattr(indexed_at, 'isoformat'):
                indexed_at = indexed_at.isoformat()
            
            output.append(f"- {doc['source_uri']}")
            output.append(f"  ID: {doc['document_id']} | Type: {doc.get('document_type', 'N/A')} | Chunks: {doc['chunk_count']}")
            output.append("")
            
        return "\n".join(output)
        
    except Exception as e:
        logger.error(f"Listing failed: {e}")
        return f"Error listing documents: {str(e)}"


# ================ MCP SERVER SETUP ================
# Only executed when running as main script (not during imports/tests)

def create_mcp_server():
    """Create and configure the MCP server with tools."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        logger.error("Failed to import 'mcp'. Please install it: pip install mcp")
        sys.exit(1)
    
    mcp = FastMCP("PGVectorRAGIndexer")
    
    # Register tools by wrapping the impl functions
    @mcp.tool()
    def search_documents(query: str, top_k: int = 5, use_hybrid: bool = False) -> str:
        """Search for relevant documents using semantic or hybrid search."""
        return search_documents_impl(query, top_k, use_hybrid)
    
    @mcp.tool()
    def index_document(path: str, force: bool = False) -> str:
        """Index a local document (PDF, TXT, MD, etc.)."""
        return index_document_impl(path, force)
    
    @mcp.tool()
    def list_documents(limit: int = 20) -> str:
        """List recently indexed documents."""
        return list_documents_impl(limit)
    
    return mcp


if __name__ == "__main__":
    logger.info("Starting MCP Server...")
    mcp = create_mcp_server()
    # Run the server using stdio transport (default for run())
    mcp.run()
