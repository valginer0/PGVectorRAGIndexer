"""
Integration tests for Web UI functionality with actual API calls.
"""

import pytest
import io
from fastapi.testclient import TestClient
from api import app
import api as api_module
import embeddings
import retriever_v2


class TestWebUIIntegration:
    """Integration tests for Web UI with real data."""
    
    @pytest.fixture(autouse=True)
    def reset_embeddings(self, monkeypatch, mock_embedding_service):
        """Ensure embedding service uses deterministic vectors between tests."""
        mock_service = mock_embedding_service

        def encode(text, **kwargs):
            if isinstance(text, str):
                return [0.05] * mock_service.config.dimension
            return [[0.05] * mock_service.config.dimension for _ in text]

        def encode_batch(texts, **kwargs):
            return [[0.05] * mock_service.config.dimension for _ in texts]

        mock_service.encode = encode
        mock_service.encode_batch = encode_batch

        monkeypatch.setattr(embeddings, '_embedding_service', mock_service, raising=False)
        monkeypatch.setattr(embeddings, 'get_embedding_service', lambda: mock_service, raising=False)
        monkeypatch.setattr(retriever_v2, 'get_embedding_service', lambda: mock_service, raising=False)

        previous_retriever = getattr(api_module, 'retriever', None)
        previous_indexer = getattr(api_module, 'indexer', None)
        api_module.retriever = None
        api_module.indexer = None
        yield
        api_module.retriever = previous_retriever
        api_module.indexer = previous_indexer
        embeddings._embedding_service = None

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)
    
    def test_upload_and_search_workflow(self, client, db_manager):
        """Test complete workflow: upload document, then search for content."""
        # Step 1: Upload a document
        file_content = b"The principal architect designed the system with scalability in mind."
        file_data = io.BytesIO(file_content)
        filename = "architect_doc.txt"
        
        upload_response = client.post(
            "/upload-and-index",
            files={"file": (filename, file_data, "text/plain")}
        )
        
        assert upload_response.status_code == 200
        upload_data = upload_response.json()
        assert upload_data["status"] == "success"
        assert upload_data["source_uri"] == filename
        document_id = upload_data["document_id"]
        
        # Diagnostic: ensure DB shows chunks before searching
        stats_pre_search = client.get("/statistics")
        assert stats_pre_search.status_code == 200
        stats_payload = stats_pre_search.json()
        assert stats_payload.get("total_chunks", 0) > 0, "Stats should reflect inserted chunk before search"

        # Step 2: Search for content that exists in the document
        search_response = client.post(
            "/search",
            json={
                "query": "principal architect",
                "top_k": 5,
                "min_score": 0.0  # Accept any relevance score
            }
        )
        
        assert search_response.status_code == 200
        search_data = search_response.json()
        
        # Should find at least one result
        assert len(search_data["results"]) > 0, "Search should return results for uploaded content"
        
        # Verify result structure
        first_result = search_data["results"][0]
        assert "source_uri" in first_result
        assert "text_content" in first_result
        assert "relevance_score" in first_result
        assert "chunk_index" in first_result
        assert "document_id" in first_result
        
        # Verify the result contains relevant content (may be from our document or similar ones)
        # Just check that we got results with the expected structure
        assert first_result["source_uri"] is not None
        assert len(first_result["text_content"]) > 0
        
        # Step 3: Verify document appears in list
        docs_response = client.get("/documents")
        assert docs_response.status_code == 200
        docs = docs_response.json()
        
        uploaded_doc = next((d for d in docs if d["document_id"] == document_id), None)
        assert uploaded_doc is not None
        assert uploaded_doc["source_uri"] == filename
        assert uploaded_doc["chunk_count"] > 0
        
        # Step 4: Verify statistics are updated
        stats_response = client.get("/statistics")
        assert stats_response.status_code == 200
        stats = stats_response.json()
        
        assert stats["total_documents"] > 0, "Statistics should show documents"
        assert stats["total_chunks"] > 0, "Statistics should show chunks"
        assert "embedding_model" in stats
        
        # Cleanup
        client.delete(f"/documents/{document_id}")
    
    def test_search_with_different_thresholds(self, client):
        """Test that search respects min_score threshold."""
        # Upload test document
        file_content = b"Machine learning is a subset of artificial intelligence."
        file_data = io.BytesIO(file_content)
        
        upload_response = client.post(
            "/upload-and-index",
            files={"file": ("ml_doc.txt", file_data, "text/plain")}
        )
        assert upload_response.status_code == 200
        document_id = upload_response.json()["document_id"]
        
        # Search with very low threshold (should return results)
        response_low = client.post(
            "/search",
            json={"query": "machine learning", "top_k": 5, "min_score": 0.0}
        )
        assert response_low.status_code == 200
        results_low = response_low.json()["results"]
        
        # Search with very high threshold (should return fewer or no results)
        response_high = client.post(
            "/search",
            json={"query": "machine learning", "top_k": 5, "min_score": 0.99}
        )
        assert response_high.status_code == 200
        results_high = response_high.json()["results"]
        
        # Low threshold should return at least as many results as high threshold
        assert len(results_low) >= len(results_high)
        
        # Cleanup
        client.delete(f"/documents/{document_id}")
    
    def test_documents_list_shows_source_uri(self, client):
        """Test that documents list includes source_uri field."""
        # Upload a document
        file_content = b"Test document for source URI verification."
        file_data = io.BytesIO(file_content)
        filename = "source_uri_test.txt"
        
        upload_response = client.post(
            "/upload-and-index",
            files={"file": (filename, file_data, "text/plain")}
        )
        assert upload_response.status_code == 200
        document_id = upload_response.json()["document_id"]
        
        # Get documents list
        docs_response = client.get("/documents")
        assert docs_response.status_code == 200
        docs = docs_response.json()
        
        # Find our document
        our_doc = next((d for d in docs if d["document_id"] == document_id), None)
        assert our_doc is not None
        
        # Verify source_uri is present and correct
        assert "source_uri" in our_doc
        assert our_doc["source_uri"] == filename
        assert our_doc["source_uri"] != ""
        
        # Cleanup
        client.delete(f"/documents/{document_id}")
    
    def test_search_results_include_all_required_fields(self, client):
        """Test that search results include all fields needed by Web UI."""
        # Upload a document
        file_content = b"Testing search result fields for web UI display."
        file_data = io.BytesIO(file_content)
        
        upload_response = client.post(
            "/upload-and-index",
            files={"file": ("fields_test.txt", file_data, "text/plain")}
        )
        assert upload_response.status_code == 200
        document_id = upload_response.json()["document_id"]
        
        # Perform search
        search_response = client.post(
            "/search",
            json={"query": "testing search", "top_k": 5, "min_score": 0.0}
        )
        assert search_response.status_code == 200
        results = search_response.json()["results"]
        
        assert len(results) > 0, "Should find results"
        
        # Check all required fields are present
        result = results[0]
        required_fields = [
            "source_uri",
            "text_content",
            "relevance_score",
            "chunk_index",
            "document_id",
            "chunk_id",
            "distance"
        ]
        
        for field in required_fields:
            assert field in result, f"Search result missing required field: {field}"
        
        # Verify field types
        assert isinstance(result["source_uri"], str)
        assert isinstance(result["text_content"], str)
        assert isinstance(result["relevance_score"], (int, float))
        assert isinstance(result["chunk_index"], int)
        assert isinstance(result["document_id"], str)
        
        # Cleanup
        client.delete(f"/documents/{document_id}")
    
    def test_statistics_endpoint_returns_valid_data(self, client):
        """Test that statistics endpoint returns all required fields."""
        response = client.get("/statistics")
        assert response.status_code == 200
        
        stats = response.json()
        
        # Check all required fields
        required_fields = [
            "total_documents",
            "total_chunks",
            "database_size_bytes",
            "embedding_model"
        ]
        
        for field in required_fields:
            assert field in stats, f"Statistics missing required field: {field}"
        
        # Verify field types
        assert isinstance(stats["total_documents"], int)
        assert isinstance(stats["total_chunks"], int)
        assert isinstance(stats["database_size_bytes"], int)
        assert isinstance(stats["embedding_model"], str)
        
        # Values should be non-negative
        assert stats["total_documents"] >= 0
        assert stats["total_chunks"] >= 0
        assert stats["database_size_bytes"] >= 0
