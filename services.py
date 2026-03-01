"""
Shared service instances and helpers for the PGVectorRAGIndexer API.
"""

import os
import logging
from typing import Optional, List, Dict, Any
from indexer_v2 import DocumentIndexer
from retriever_v2 import DocumentRetriever

from fastapi import Response

logger = logging.getLogger(__name__)

def _add_deprecation_headers(response: Response) -> None:
    """Add RFC 8594 deprecation headers to a response."""
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "Sat, 01 Nov 2026 00:00:00 GMT"
    response.headers["Link"] = '</api/v1/retention/run>; rel="successor-version"'

# Singletons for services
indexer: Optional[DocumentIndexer] = None
retriever: Optional[DocumentRetriever] = None

# Track encrypted PDFs encountered (in-memory, cleared on restart)
encrypted_pdfs_encountered: List[Dict[str, Any]] = []

# Initialization state
init_complete = False
init_error = None


def get_indexer() -> DocumentIndexer:
    """Get or create singleton indexer instance."""
    global indexer
    if indexer is None:
        indexer = DocumentIndexer()
    return indexer


def get_retriever() -> DocumentRetriever:
    """Get or create singleton retriever instance."""
    global retriever
    if retriever is None:
        retriever = DocumentRetriever()
    return retriever


def reset_services():
    """Reset service singletons (primarily for testing)."""
    global indexer, retriever
    indexer = None
    retriever = None


def set_init_failed(error_msg: str):
    """Force an initialization failure state (primarily for testing)."""
    global init_complete, init_error
    init_complete = False
    init_error = error_msg
