"""
Tests for document metadata (type/namespace) filtering functionality.
"""

import pytest
from pathlib import Path
import tempfile
from fastapi.testclient import TestClient
from api import app


class TestMetadataUpload:
    """Test uploading documents with metadata."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)
    
    def test_upload_with_document_type(self, client, db_manager):
        """Test uploading a document with a type."""
        # Create test file
        content = b"This is a policy document about data retention."
        
        response = client.post(
            "/upload-and-index",
            files={"file": ("policy.txt", content, "text/plain")},
            data={
                "document_type": "policy",
                "force_reindex": "false"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["chunks_indexed"] > 0
        
        # Verify metadata was stored
        doc_id = data["document_id"]
        with db_manager.get_cursor(dict_cursor=True) as cursor:
            # First check if document exists at all
            cursor.execute(
                "SELECT COUNT(*) as count FROM document_chunks WHERE document_id = %s",
                (doc_id,)
            )
            count_result = cursor.fetchone()
            assert count_result is not None, f"Query returned None for document_id: {doc_id}"
            assert count_result['count'] > 0, f"No chunks found for document_id: {doc_id}"
            
            # Now get metadata
            cursor.execute(
                "SELECT metadata FROM document_chunks WHERE document_id = %s LIMIT 1",
                (doc_id,)
            )
            result = cursor.fetchone()
            assert result is not None, f"No metadata found for document_id: {doc_id}"
            assert result['metadata'].get('type') == 'policy', f"Expected type='policy', got: {result['metadata']}"
    
    def test_upload_without_document_type(self, client, db_manager):
        """Test uploading a document without a type (should work)."""
        content = b"This is a document without a type."
        
        response = client.post(
            "/upload-and-index",
            files={"file": ("no_type.txt", content, "text/plain")},
            data={"force_reindex": "false"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        
        # Verify no type in metadata
        doc_id = data["document_id"]
        with db_manager.get_cursor(dict_cursor=True) as cursor:
            cursor.execute(
                "SELECT metadata FROM document_chunks WHERE document_id = %s LIMIT 1",
                (doc_id,)
            )
            result = cursor.fetchone()
            assert result is not None
            # Type should not be present or should be None
            assert result['metadata'].get('type') is None
    
    def test_upload_multiple_types(self, client, db_manager):
        """Test uploading documents with different types."""
        types_and_content = [
            ("resume", b"John Doe - Senior Software Engineer"),
            ("policy", b"Company policy on remote work"),
            ("report", b"Q4 2024 Financial Report")
        ]
        
        uploaded_docs = []
        
        for doc_type, content in types_and_content:
            response = client.post(
                "/upload-and-index",
                files={"file": (f"{doc_type}.txt", content, "text/plain")},
                data={"document_type": doc_type}
            )
            assert response.status_code == 200
            uploaded_docs.append((doc_type, response.json()["document_id"]))
        
        # Verify each document has correct type
        for expected_type, doc_id in uploaded_docs:
            with db_manager.get_cursor(dict_cursor=True) as cursor:
                cursor.execute(
                    "SELECT metadata->>'type' as doc_type FROM document_chunks WHERE document_id = %s LIMIT 1",
                    (doc_id,)
                )
                result = cursor.fetchone()
                assert result['doc_type'] == expected_type


class TestMetadataSearch:
    """Test searching with metadata filters."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)
    
    def test_search_with_type_filter(self, client, db_manager):
        """Test searching filtered by document type."""
        # Upload documents with different types
        client.post(
            "/upload-and-index",
            files={"file": ("policy1.txt", b"Security policy about passwords", "text/plain")},
            data={"document_type": "policy"}
        )
        client.post(
            "/upload-and-index",
            files={"file": ("resume1.txt", b"Software engineer with password experience", "text/plain")},
            data={"document_type": "resume"}
        )
        
        # Search with type filter for "policy"
        response = client.post(
            "/search",
            json={
                "query": "password",
                "top_k": 10,
                "min_score": 0.0,
                "filters": {"type": "policy"}
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        results = data["results"]
        
        # Should only return policy documents
        assert len(results) > 0
        
        # Verify all results are from policy documents
        for result in results:
            doc_id = result["document_id"]
            with db_manager.get_cursor(dict_cursor=True) as cursor:
                cursor.execute(
                    "SELECT metadata->>'type' as doc_type FROM document_chunks WHERE document_id = %s LIMIT 1",
                    (doc_id,)
                )
                row = cursor.fetchone()
                assert row['doc_type'] == 'policy'
    
    def test_search_without_type_filter(self, client, db_manager):
        """Test searching without type filter returns all types."""
        # Upload documents with different types
        client.post(
            "/upload-and-index",
            files={"file": ("policy2.txt", b"Data retention policy", "text/plain")},
            data={"document_type": "policy"}
        )
        client.post(
            "/upload-and-index",
            files={"file": ("report2.txt", b"Data analysis report", "text/plain")},
            data={"document_type": "report"}
        )
        
        # Search without type filter
        response = client.post(
            "/search",
            json={
                "query": "data",
                "top_k": 10,
                "min_score": 0.0
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        results = data["results"]
        
        # Should return documents of different types
        assert len(results) >= 2
        
        # Get unique types from results
        types = set()
        for result in results:
            doc_id = result["document_id"]
            with db_manager.get_cursor(dict_cursor=True) as cursor:
                cursor.execute(
                    "SELECT metadata->>'type' as doc_type FROM document_chunks WHERE document_id = %s LIMIT 1",
                    (doc_id,)
                )
                row = cursor.fetchone()
                if row['doc_type']:
                    types.add(row['doc_type'])
        
        # Should have multiple types
        assert len(types) >= 2
    
    def test_search_nonexistent_type(self, client, db_manager):
        """Test searching for a type that doesn't exist."""
        # Upload a document
        client.post(
            "/upload-and-index",
            files={"file": ("test.txt", b"Test content", "text/plain")},
            data={"document_type": "policy"}
        )
        
        # Search for non-existent type
        response = client.post(
            "/search",
            json={
                "query": "test",
                "top_k": 10,
                "filters": {"type": "nonexistent_type"}
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        # Should return no results
        assert len(data["results"]) == 0


class TestMetadataListDocuments:
    """Test listing documents with metadata."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)
    
    def test_list_documents_includes_type(self, client, db_manager):
        """Test that list_documents includes document_type."""
        # Upload documents with types
        client.post(
            "/upload-and-index",
            files={"file": ("policy3.txt", b"Policy content", "text/plain")},
            data={"document_type": "policy"}
        )
        client.post(
            "/upload-and-index",
            files={"file": ("resume3.txt", b"Resume content", "text/plain")},
            data={"document_type": "resume"}
        )
        
        # List documents
        response = client.get("/documents")
        
        assert response.status_code == 200
        payload = response.json()
        documents = payload.get("items", [])
        
        assert len(documents) >= 2
        
        # Debug: print what we got
        print(f"\nDocuments returned: {len(documents)}")
        for doc in documents:
            print(f"  - {doc.get('document_id')}: type={doc.get('document_type')}, keys={list(doc.keys())}")
        
        # Debug: Check what's actually in the database
        with db_manager.get_cursor(dict_cursor=True) as cursor:
            cursor.execute("SELECT document_id, metadata FROM document_chunks ORDER BY indexed_at DESC LIMIT 5")
            db_results = cursor.fetchall()
            print(f"\nDatabase contents:")
            for row in db_results:
                print(f"  - {row['document_id']}: metadata={row['metadata']}")
        
        # Check that document_type is included
        types_found = [doc.get('document_type') for doc in documents if doc.get('document_type')]
        print(f"Types found: {types_found}")
        assert 'policy' in types_found, f"Expected 'policy' in {types_found}"
        assert 'resume' in types_found, f"Expected 'resume' in {types_found}"
    
    def test_list_documents_without_type(self, client, db_manager):
        """Test listing documents that don't have a type."""
        # Upload document without type
        client.post(
            "/upload-and-index",
            files={"file": ("no_type2.txt", b"Content without type", "text/plain")}
        )
        
        # List documents
        response = client.get("/documents")
        
        assert response.status_code == 200
        payload = response.json()
        documents = payload.get("items", [])
        
        # Should include documents without type (document_type will be None)
        assert len(documents) > 0
        # At least one document should have None or missing type
        has_none_type = any(doc.get('document_type') is None for doc in documents)
        assert has_none_type


class TestMetadataIntegration:
    """Integration tests for metadata functionality."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)
    
    def test_end_to_end_workflow(self, client, db_manager):
        """Test complete workflow: upload with type, search by type, list with type."""
        # 1. Upload documents with different types
        policy_response = client.post(
            "/upload-and-index",
            files={"file": ("security_policy.txt", b"Password must be 12 characters", "text/plain")},
            data={"document_type": "policy"}
        )
        assert policy_response.status_code == 200
        policy_doc_id = policy_response.json()["document_id"]
        
        resume_response = client.post(
            "/upload-and-index",
            files={"file": ("engineer_resume.txt", b"Expert in security and passwords", "text/plain")},
            data={"document_type": "resume"}
        )
        assert resume_response.status_code == 200
        
        # 2. Search filtered by type
        search_response = client.post(
            "/search",
            json={
                "query": "password security",
                "top_k": 5,
                "min_score": 0.0,  # Accept any relevance score
                "filters": {"type": "policy"}
            }
        )
        assert search_response.status_code == 200
        search_results = search_response.json()["results"]
        
        # Should only return policy documents
        assert len(search_results) > 0
        assert all(r["document_id"] == policy_doc_id for r in search_results)
        
        # 3. List documents and verify types
        list_response = client.get("/documents")
        assert list_response.status_code == 200
        payload = list_response.json()
        documents = payload.get("items", [])

        # Find our uploaded documents
        policy_doc = next((d for d in documents if d["document_id"] == policy_doc_id), None)
        assert policy_doc is not None
        assert policy_doc["document_type"] == "policy"
