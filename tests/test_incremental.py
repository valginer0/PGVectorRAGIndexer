"""
Tests for incremental indexing logic.
Verifies that:
1. New files are indexed.
2. Unchanged files are skipped (based on xxHash).
3. Changed files are re-indexed.
4. Force reindex overrides the skipper.
"""

import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from indexer_v2 import DocumentIndexer
from desktop_app.utils.hashing import calculate_file_hash
from database import DocumentRepository

@pytest.fixture
def temp_workspace():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

@pytest.fixture
def mock_db_manager():
    """Create a mock database manager."""
    return MagicMock()

@pytest.fixture
def indexer(mock_db_manager):
    """Initialize DocumentIndexer with mocked DB manager."""
    # We need to mock get_config if it's used during init, or ensure we have env vars set.
    # Assuming standard test env handles config.
    with patch('indexer_v2.get_db_manager', return_value=mock_db_manager):
        indexer = DocumentIndexer()
        # Mock the embedding service to avoid heavy lifting / model loading
        indexer.embedding_service = MagicMock()
        indexer.embedding_service.encode_batch.return_value = [[0.1]*1536] # Dummy embedding
        return indexer

@pytest.fixture
def mock_repository(indexer):
    """Mock the repository to control DB state simulation."""
    indexer.repository = MagicMock(spec=DocumentRepository)
    return indexer.repository

def test_incremental_indexing_flow(indexer, mock_repository, temp_workspace):
    """
    Test the full lifecycle of incremental indexing:
    New -> Unchanged (Skip) -> Changed (Update) -> Force (Update)
    """
    
    # 1. Setup Test File
    test_file = temp_workspace / "test_doc.txt"
    test_file.write_text("v1 content")
    
    source_uri = str(test_file.resolve())
    doc_id = "mock_doc_id"
    
    # Mock processor to return a document with v1 hash
    # (Real processor calls calculate_file_hash, we can let it run or mock it)
    # Let's let the real processor run to verify integration, 
    # but we need to mock repository methods.
    
    # --- PHASE 1: New File (Should Index) ---
    # Setup: Document does not exist in DB
    mock_repository.get_document_by_id.return_value = None
    mock_repository.document_exists.return_value = False # Indexer uses this first sometimes
    
    result = indexer.index_document(source_uri)
    
    assert result['status'] == 'success'
    assert mock_repository.insert_chunks.called
    
    # Capture the hash that would have been stored
    # The processor calculates it.
    # In a real integration test we'd check DB. Here we simulate the state.
    v1_hash = calculate_file_hash(test_file)
    
    # --- PHASE 2: Unchanged File (Should Skip) ---
    # Setup: Document exists in DB with v1_hash
    mock_repository.get_document_by_id.return_value = {
        'document_id': doc_id,
        'metadata': {'file_hash': v1_hash}
    }
    mock_repository.insert_chunks.reset_mock()
    
    result = indexer.index_document(source_uri)
    
    assert result['status'] == 'skipped'
    assert result['reason'] == 'unchanged'
    assert not mock_repository.insert_chunks.called
    
    # --- PHASE 3: Changed File (Should Update) ---
    # Update file content
    test_file.write_text("v2 content changed")
    v2_hash = calculate_file_hash(test_file)
    assert v1_hash != v2_hash
    
    # Repository still returns OLD hash (v1)
    mock_repository.insert_chunks.reset_mock()
    mock_repository.delete_document.reset_mock()
    
    result = indexer.index_document(source_uri)
    
    assert result['status'] == 'success'
    # Should delete old doc and insert new chunks
    assert mock_repository.delete_document.called
    assert mock_repository.insert_chunks.called
    
    # --- PHASE 4: Force Reindex (Should Update even if hash matches) ---
    # Setup: DB has v2 hash now (simulated)
    mock_repository.get_document_by_id.return_value = {
        'document_id': doc_id,
        'metadata': {'file_hash': v2_hash}
    }
    mock_repository.insert_chunks.reset_mock()
    mock_repository.delete_document.reset_mock()
    
    # Note: File on disk is still v2 content, so hashes match.
    # Without force, it would skip.
    
    result = indexer.index_document(source_uri, force_reindex=True)
    
    assert result['status'] == 'success'
    assert mock_repository.delete_document.called
    assert mock_repository.insert_chunks.called

