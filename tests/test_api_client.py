import pytest
from unittest.mock import MagicMock, patch
import requests
from pathlib import Path

from desktop_app.utils.api_client import APIClient

@pytest.fixture
def api_client():
    return APIClient(base_url="http://test-api")

def test_is_api_available_success(api_client):
    """Test API availability check returns True on 200 OK."""
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"status": "healthy"}
        assert api_client.is_api_available() is True
        mock_get.assert_called_with("http://test-api/health", timeout=5, headers={})

def test_is_api_available_failure(api_client):
    """Test API availability check returns False on error."""
    with patch("requests.get") as mock_get:
        mock_get.side_effect = requests.RequestException("Connection refused")
        assert api_client.is_api_available() is False

def test_upload_document_success(api_client):
    """Test successful document upload."""
    file_path = Path("test.txt")
    with patch("builtins.open", new_callable=MagicMock), \
         patch("requests.post") as mock_post:
        
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"status": "success"}
        
        response = api_client.upload_document(
            file_path=file_path,
            custom_source_uri="/full/path/test.txt",
            force_reindex=True,
            document_type="resume"
        )
        
        assert response == {"status": "success"}
        mock_post.assert_called_once()
        
        # Verify args
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://test-api/api/v1/upload-and-index"
        assert call_args[1]["data"]["force_reindex"] == "true"
        assert call_args[1]["data"]["custom_source_uri"] == "/full/path/test.txt"
        assert call_args[1]["data"]["document_type"] == "resume"

def test_search_success(api_client):
    """Test search functionality."""
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"results": [{"id": "1"}]}
        
        results = api_client.search(
            query="test query",
            filters={"type": "resume"}
        )
        
        assert len(results) == 1
        assert results[0]["id"] == "1"
        
        # Verify payload
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        assert payload["query"] == "test query"
        assert payload["filters"] == {"type": "resume"}

def test_list_documents_pagination(api_client):
    """Test list documents with pagination."""
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "items": [{"id": "1"}],
            "total": 10,
            "limit": 10,
            "offset": 0
        }
        
        response = api_client.list_documents(limit=10, offset=0)
        
        assert response["total"] == 10
        assert len(response["items"]) == 1
        
        mock_get.assert_called_with(
            "http://test-api/api/v1/documents",
            params={"limit": 10, "offset": 0, "sort_by": "indexed_at", "sort_dir": "desc"},
            headers={},
            timeout=7200
        )

def test_error_handling(api_client):
    """Test that requests.RequestException is raised on HTTP error."""
    with patch("requests.get") as mock_get:
        mock_get.return_value.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        
        with pytest.raises(requests.RequestException):
            api_client.get_document("missing_id")

def test_check_document_exists_true(api_client):
    """Test check_document_exists returns True when found."""
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"id": "1", "metadata": {"file_hash": "abc"}}
        
        assert api_client.check_document_exists("/path/to/doc") is True
        
        # Verify it called get document
        args = mock_get.call_args
        assert "/documents/" in args[0][0]

def test_check_document_exists_false(api_client):
    """Test check_document_exists returns False when not found."""
    with patch("requests.get") as mock_get:
        mock_get.return_value.raise_for_status.side_effect = requests.HTTPError(response=MagicMock(status_code=404))
        
        assert api_client.check_document_exists("/path/to/doc") is False

def test_check_document_exists_exception(api_client):
    """Test check_document_exists returns False on error."""
    with patch("requests.get", side_effect=Exception("API Error")):
        assert api_client.check_document_exists("/path/to/doc") is False

def test_list_documents_legacy_response(api_client):
    """Test list_documents handles legacy list response."""
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = [{"id": "1"}, {"id": "2"}]
        
        response = api_client.list_documents()
        
        assert response["total"] == 2
        assert len(response["items"]) == 2
        assert response["_total_estimated"] is True

def test_get_document_success(api_client):
    """Test get_document success."""
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"id": "1", "content": "test"}
        
        doc = api_client.get_document("1")
        assert doc["id"] == "1"
        mock_get.assert_called_with("http://test-api/api/v1/documents/1", headers={}, timeout=7200)

def test_delete_document_success(api_client):
    """Test delete_document success."""
    with patch("requests.delete") as mock_delete:
        mock_delete.return_value.status_code = 200
        mock_delete.return_value.json.return_value = {"status": "deleted"}
        
        response = api_client.delete_document("1")
        assert response["status"] == "deleted"
        mock_delete.assert_called_with("http://test-api/api/v1/documents/1", headers={}, timeout=7200)

def test_get_statistics_success(api_client):
    """Test get_statistics success."""
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"total_documents": 100}
        
        stats = api_client.get_statistics()
        assert stats["total_documents"] == 100
        mock_get.assert_called_with("http://test-api/api/v1/statistics", headers={}, timeout=7200)

def test_bulk_delete_preview(api_client):
    """Test bulk_delete_preview."""
    filters = {"type": "resume"}
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"count": 5, "preview": []}
        
        response = api_client.bulk_delete_preview(filters)
        assert response["count"] == 5
        
        mock_post.assert_called_with(
            "http://test-api/api/v1/documents/bulk-delete",
            json={"filters": filters, "preview": True},
            headers={},
            timeout=7200
        )

def test_bulk_delete_execute(api_client):
    """Test bulk_delete execution."""
    filters = {"type": "resume"}
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"chunks_deleted": 10}
        
        response = api_client.bulk_delete(filters)
        assert response["chunks_deleted"] == 10
        
        mock_post.assert_called_with(
            "http://test-api/api/v1/documents/bulk-delete",
            json={"filters": filters, "preview": False},
            headers={},
            timeout=7200
        )

def test_export_documents(api_client):
    """Test export_documents."""
    filters = {"type": "resume"}
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"backup_data": []}
        
        response = api_client.export_documents(filters)
        assert "backup_data" in response
        
        mock_post.assert_called_with(
            "http://test-api/api/v1/documents/export",
            json={"filters": filters},
            headers={},
            timeout=7200
        )

def test_restore_documents(api_client):
    """Test restore_documents."""
    backup_data = [{"id": "1"}]
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"chunks_restored": 1}
        
        response = api_client.restore_documents(backup_data)
        assert response["chunks_restored"] == 1
        
        mock_post.assert_called_with(
            "http://test-api/api/v1/documents/restore",
            json={"backup_data": backup_data},
            headers={},
            timeout=7200
        )

def test_get_metadata_keys(api_client):
    """Test get_metadata_keys."""
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = ["author", "date"]
        
        keys = api_client.get_metadata_keys(pattern="auth%")
        assert keys == ["author", "date"]
        
        mock_get.assert_called_with(
            "http://test-api/api/v1/metadata/keys",
            params={"pattern": "auth%"},
            headers={},
            timeout=7200
        )

def test_get_metadata_values(api_client):
    """Test get_metadata_values."""
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = ["John", "Jane"]
        
        values = api_client.get_metadata_values("author")
        assert values == ["John", "Jane"]
        
        mock_get.assert_called_with(
            "http://test-api/api/v1/metadata/values",
            params={"key": "author"},
            headers={},
            timeout=7200
        )

