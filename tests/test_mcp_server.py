"""
Tests for the MCP Server (mcp_server.py).

These tests verify the *_impl functions (the actual tool logic) without
needing the MCP library or a running database.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime


class MockSearchResult:
    """Mock search result object."""
    def __init__(self, text: str, score: float = 0.9, source: str = "/path/to/doc.txt"):
        self.text_content = text
        self.relevance_score = score
        self.distance = 1 - score
        self.metadata = {"source_uri": source}


class TestSearchDocumentsImpl:
    """Tests for search_documents_impl function."""

    @patch('mcp_server._get_retriever')
    def test_search_returns_results(self, mock_get_retriever):
        """Test that search returns formatted results."""
        from mcp_server import search_documents_impl
        
        # Setup mock retriever
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = [
            MockSearchResult("This is test content", 0.95, "/docs/test.txt"),
            MockSearchResult("Another result", 0.85, "/docs/other.md"),
        ]
        mock_get_retriever.return_value = mock_retriever
        
        # Call the function
        result = search_documents_impl("test query", top_k=5, use_hybrid=False)
        
        # Verify
        assert "Found 2 relevant results" in result
        assert "test query" in result
        assert "This is test content" in result
        assert "/docs/test.txt" in result
        mock_retriever.search.assert_called_once_with(query="test query", top_k=5)

    @patch('mcp_server._get_retriever')
    def test_search_no_results(self, mock_get_retriever):
        """Test that search handles empty results gracefully."""
        from mcp_server import search_documents_impl
        
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = []
        mock_get_retriever.return_value = mock_retriever
        
        result = search_documents_impl("nonexistent query")
        
        assert "No matching documents found" in result

    @patch('mcp_server._get_retriever')
    def test_search_hybrid(self, mock_get_retriever):
        """Test hybrid search is called when requested."""
        from mcp_server import search_documents_impl
        
        mock_retriever = MagicMock()
        mock_retriever.search_hybrid.return_value = [MockSearchResult("Hybrid result")]
        mock_get_retriever.return_value = mock_retriever
        
        result = search_documents_impl("query", top_k=3, use_hybrid=True)
        
        mock_retriever.search_hybrid.assert_called_once_with(query="query", top_k=3)
        assert "Hybrid result" in result

    @patch('mcp_server._get_retriever')
    def test_search_error_handling(self, mock_get_retriever):
        """Test that search handles errors gracefully."""
        from mcp_server import search_documents_impl
        
        mock_get_retriever.side_effect = Exception("Database connection failed")
        
        result = search_documents_impl("test")
        
        assert "Error performing search" in result
        assert "Database connection failed" in result


class TestIndexDocumentImpl:
    """Tests for index_document_impl function."""

    @patch('mcp_server._get_indexer')
    @patch('mcp_server.os.path.exists')
    def test_index_success(self, mock_exists, mock_get_indexer):
        """Test successful document indexing."""
        from mcp_server import index_document_impl
        
        mock_exists.return_value = True
        mock_indexer = MagicMock()
        mock_indexer.index_document.return_value = {
            'status': 'success',
            'document_id': 'abc123',
            'chunks_indexed': 10
        }
        mock_get_indexer.return_value = mock_indexer
        
        result = index_document_impl("/path/to/file.pdf", force=False)
        
        assert "Successfully indexed" in result
        assert "abc123" in result
        assert "10" in result
        mock_indexer.index_document.assert_called_once_with(
            source_uri="/path/to/file.pdf",
            force_reindex=False
        )

    @patch('mcp_server._get_indexer')
    @patch('mcp_server.os.path.exists')
    def test_index_file_not_found(self, mock_exists, mock_get_indexer):
        """Test indexing a non-existent file."""
        from mcp_server import index_document_impl
        
        mock_exists.return_value = False
        
        result = index_document_impl("/nonexistent/file.txt")
        
        assert "Error: File not found" in result

    @patch('mcp_server._get_indexer')
    @patch('mcp_server.os.path.exists')
    def test_index_error(self, mock_exists, mock_get_indexer):
        """Test indexing error handling."""
        from mcp_server import index_document_impl
        
        mock_exists.return_value = True
        mock_indexer = MagicMock()
        mock_indexer.index_document.return_value = {
            'status': 'error',
            'message': 'Unsupported file type'
        }
        mock_get_indexer.return_value = mock_indexer
        
        result = index_document_impl("/path/to/file.xyz")
        
        assert "Failed to index" in result
        assert "Unsupported file type" in result


class TestListDocumentsImpl:
    """Tests for list_documents_impl function."""

    @patch('mcp_server._get_document_repository')
    @patch('mcp_server._get_db_manager')
    def test_list_success(self, mock_get_db, mock_get_repo_class):
        """Test listing documents."""
        from mcp_server import list_documents_impl
        
        mock_repo = MagicMock()
        mock_repo.list_documents.return_value = (
            [
                {
                    'document_id': 'doc1',
                    'source_uri': '/path/to/doc1.pdf',
                    'document_type': 'report',
                    'chunk_count': 5,
                    'indexed_at': datetime(2024, 1, 15, 10, 30)
                },
                {
                    'document_id': 'doc2',
                    'source_uri': '/path/to/doc2.txt',
                    'document_type': None,
                    'chunk_count': 2,
                    'indexed_at': "2024-01-16T14:00:00"
                }
            ],
            2  # total
        )
        mock_get_repo_class.return_value.return_value = mock_repo
        
        result = list_documents_impl(limit=10)
        
        assert "Total Documents: 2" in result
        assert "/path/to/doc1.pdf" in result
        assert "doc1" in result
        assert "report" in result

    @patch('mcp_server._get_document_repository')
    @patch('mcp_server._get_db_manager')
    def test_list_empty(self, mock_get_db, mock_get_repo_class):
        """Test listing when no documents exist."""
        from mcp_server import list_documents_impl
        
        mock_repo = MagicMock()
        mock_repo.list_documents.return_value = ([], 0)
        mock_get_repo_class.return_value.return_value = mock_repo
        
        result = list_documents_impl()
        
        assert "No documents found" in result

    @patch('mcp_server._get_document_repository')
    @patch('mcp_server._get_db_manager')
    def test_list_error(self, mock_get_db, mock_get_repo_class):
        """Test list error handling."""
        from mcp_server import list_documents_impl
        
        mock_get_repo_class.side_effect = Exception("Connection timeout")
        
        result = list_documents_impl()
        
        assert "Error listing documents" in result
        assert "Connection timeout" in result
