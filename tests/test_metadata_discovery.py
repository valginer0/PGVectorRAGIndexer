"""
Tests for metadata discovery and bulk delete functionality.
"""

import pytest
from fastapi.testclient import TestClient
from api import app


class TestMetadataDiscovery:
    """Test metadata discovery endpoints."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)
    
    def test_get_metadata_keys(self, client, db_manager):
        """Test getting all metadata keys."""
        # Upload documents with various metadata
        client.post(
            "/upload-and-index",
            files={"file": ("test1.txt", b"Content 1", "text/plain")},
            data={"document_type": "policy"}
        )
        client.post(
            "/upload-and-index",
            files={"file": ("test2.txt", b"Content 2", "text/plain")},
            data={"document_type": "resume"}
        )
        
        # Get all metadata keys
        response = client.get("/metadata/keys")
        
        assert response.status_code == 200
        keys = response.json()
        
        assert isinstance(keys, list)
        assert 'type' in keys
        # Should also have other keys like 'file_type', 'upload_method', etc.
        assert len(keys) > 1
    
    def test_get_metadata_keys_with_pattern(self, client, db_manager):
        """Test getting metadata keys with pattern filter."""
        # Upload a document
        client.post(
            "/upload-and-index",
            files={"file": ("test.txt", b"Content", "text/plain")},
            data={"document_type": "test"}
        )
        
        # Get keys matching pattern 't%' (starts with 't')
        response = client.get("/metadata/keys?pattern=t%")
        
        assert response.status_code == 200
        keys = response.json()
        
        # Should include 'type' and 'temp_path'
        assert all(k.startswith('t') for k in keys if k)
    
    def test_get_metadata_values(self, client, db_manager):
        """Test getting values for a specific metadata key."""
        # Upload documents with different types
        client.post(
            "/upload-and-index",
            files={"file": ("policy.txt", b"Policy content", "text/plain")},
            data={"document_type": "policy"}
        )
        client.post(
            "/upload-and-index",
            files={"file": ("resume.txt", b"Resume content", "text/plain")},
            data={"document_type": "resume"}
        )
        client.post(
            "/upload-and-index",
            files={"file": ("report.txt", b"Report content", "text/plain")},
            data={"document_type": "report"}
        )
        
        # Get all values for 'type' key
        response = client.get("/metadata/values?key=type")
        
        assert response.status_code == 200
        values = response.json()
        
        assert isinstance(values, list)
        assert 'policy' in values
        assert 'resume' in values
        assert 'report' in values
    
    def test_get_metadata_values_with_limit(self, client, db_manager):
        """Test getting metadata values with limit."""
        # Upload multiple documents
        for i in range(5):
            client.post(
                "/upload-and-index",
                files={"file": (f"test{i}.txt", f"Content {i}".encode(), "text/plain")},
                data={"document_type": f"type{i}"}
            )
        
        # Get values with limit
        response = client.get("/metadata/values?key=type&limit=3")
        
        assert response.status_code == 200
        values = response.json()
        
        assert len(values) <= 3


class TestGenericMetadataFiltering:
    """Test generic metadata filtering in search."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)
    
    def test_search_with_metadata_dot_syntax(self, client, db_manager):
        """Test searching with metadata.* filter syntax."""
        # Upload documents
        client.post(
            "/upload-and-index",
            files={"file": ("policy.txt", b"Security policy document", "text/plain")},
            data={"document_type": "policy"}
        )
        client.post(
            "/upload-and-index",
            files={"file": ("resume.txt", b"Security engineer resume", "text/plain")},
            data={"document_type": "resume"}
        )
        
        # Search with metadata.type filter
        response = client.post(
            "/search",
            json={
                "query": "security",
                "top_k": 10,
                "min_score": 0.0,
                "filters": {"metadata.type": "policy"}
            }
        )
        
        assert response.status_code == 200
        results = response.json()["results"]
        
        # Should only return policy documents
        assert len(results) > 0
        # All results should be from policy documents
        for result in results:
            # Verify by checking the document
            with db_manager.get_cursor(dict_cursor=True) as cursor:
                cursor.execute(
                    "SELECT metadata->>'type' as doc_type FROM document_chunks WHERE document_id = %s LIMIT 1",
                    (result["document_id"],)
                )
                row = cursor.fetchone()
                assert row['doc_type'] == 'policy'


class TestBulkDelete:
    """Test bulk delete functionality."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)
    
    def test_bulk_delete_preview(self, client, db_manager):
        """Test bulk delete preview mode."""
        # Upload test documents
        client.post(
            "/upload-and-index",
            files={"file": ("draft1.txt", b"Draft content 1", "text/plain")},
            data={"document_type": "draft"}
        )
        client.post(
            "/upload-and-index",
            files={"file": ("draft2.txt", b"Draft content 2", "text/plain")},
            data={"document_type": "draft"}
        )
        client.post(
            "/upload-and-index",
            files={"file": ("final.txt", b"Final content", "text/plain")},
            data={"document_type": "final"}
        )
        
        # Preview delete of draft documents
        response = client.post(
            "/documents/bulk-delete",
            json={
                "filters": {"type": "draft"},
                "preview": True
            }
        )
        
        assert response.status_code == 200
        preview = response.json()
        
        assert preview["document_count"] == 2
        assert len(preview["sample_documents"]) == 2
        assert preview["filters_applied"] == {"type": "draft"}
        
        # Verify documents still exist (preview didn't delete)
        with db_manager.get_cursor() as cursor:
            cursor.execute("SELECT COUNT(DISTINCT document_id) FROM document_chunks WHERE metadata->>'type' = 'draft'")
            count = cursor.fetchone()[0]
            assert count == 2
    
    def test_bulk_delete_actual(self, client, db_manager):
        """Test actual bulk delete operation."""
        # Upload test documents
        client.post(
            "/upload-and-index",
            files={"file": ("temp1.txt", b"Temp content 1", "text/plain")},
            data={"document_type": "temp"}
        )
        client.post(
            "/upload-and-index",
            files={"file": ("temp2.txt", b"Temp content 2", "text/plain")},
            data={"document_type": "temp"}
        )
        client.post(
            "/upload-and-index",
            files={"file": ("keep.txt", b"Keep this", "text/plain")},
            data={"document_type": "permanent"}
        )
        
        # Actually delete temp documents
        response = client.post(
            "/documents/bulk-delete",
            json={
                "filters": {"metadata.type": "temp"},
                "preview": False
            }
        )
        
        assert response.status_code == 200
        result = response.json()
        
        assert result["status"] == "success"
        assert result["chunks_deleted"] > 0
        
        # Verify temp documents are gone
        with db_manager.get_cursor() as cursor:
            cursor.execute("SELECT COUNT(DISTINCT document_id) FROM document_chunks WHERE metadata->>'type' = 'temp'")
            count = cursor.fetchone()[0]
            assert count == 0
            
            # Verify permanent document still exists
            cursor.execute("SELECT COUNT(DISTINCT document_id) FROM document_chunks WHERE metadata->>'type' = 'permanent'")
            count = cursor.fetchone()[0]
            assert count == 1
    
    def test_bulk_delete_without_filters_fails(self, client, db_manager):
        """Test that bulk delete without filters is rejected (safety check)."""
        response = client.post(
            "/documents/bulk-delete",
            json={
                "filters": {},
                "preview": False
            }
        )
        
        # Should fail with 400 Bad Request
        assert response.status_code == 400
    
    def test_bulk_delete_with_multiple_filters(self, client, db_manager):
        """Test bulk delete with multiple filter criteria."""
        # Upload documents with multiple metadata fields
        client.post(
            "/upload-and-index",
            files={"file": ("old_draft.txt", b"Old draft", "text/plain")},
            data={"document_type": "draft"}
        )
        client.post(
            "/upload-and-index",
            files={"file": ("new_draft.txt", b"New draft", "text/plain")},
            data={"document_type": "draft"}
        )
        client.post(
            "/upload-and-index",
            files={"file": ("old_final.txt", b"Old final", "text/plain")},
            data={"document_type": "final"}
        )
        
        # Preview delete with multiple filters
        response = client.post(
            "/documents/bulk-delete",
            json={
                "filters": {
                    "type": "draft",
                    "metadata.file_type": "text"
                },
                "preview": True
            }
        )
        
        assert response.status_code == 200
        preview = response.json()
        
        # Should match draft documents with file_type=text
        assert preview["document_count"] >= 2
