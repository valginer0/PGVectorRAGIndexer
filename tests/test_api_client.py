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
    with patch.object(api_client._base, "request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "healthy"}
        mock_request.return_value = mock_response
        
        assert api_client.is_api_available() is True
        mock_request.assert_called_with("GET", "http://test-api/health", timeout=5)

def test_is_api_available_failure(api_client):
    """Test API availability check returns False on error."""
    with patch.object(api_client._base, "request") as mock_request:
        mock_request.side_effect = requests.RequestException("Connection refused")
        assert api_client.is_api_available() is False

def test_upload_document_success(api_client):
    """Test successful document upload."""
    file_path = Path("test.txt")
    with patch("builtins.open", new_callable=MagicMock), \
         patch.object(api_client._base, "request") as mock_request:
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_request.return_value = mock_response
        
        response = api_client.upload_document(
            file_path=file_path,
            custom_source_uri="/full/path/test.txt",
            force_reindex=True,
            document_type="resume"
        )
        
        assert response == {"status": "success"}
        mock_request.assert_called_once()
        
        # Verify args
        call_args = mock_request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "http://test-api/api/v1/upload-and-index"
        assert call_args[1]["data"]["force_reindex"] == "true"
        assert call_args[1]["data"]["custom_source_uri"] == "/full/path/test.txt"
        assert call_args[1]["data"]["document_type"] == "resume"

def test_search_success(api_client):
    """Test search functionality."""
    with patch.object(api_client._base, "request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": [{"id": "1"}]}
        mock_request.return_value = mock_response
        
        results = api_client.search(
            query="test query",
            filters={"type": "resume"}
        )
        
        assert len(results) == 1
        assert results[0]["id"] == "1"
        
        # Verify payload
        call_args = mock_request.call_args
        payload = call_args[1]["json"]
        assert payload["query"] == "test query"
        assert payload["filters"] == {"type": "resume"}
        assert payload["top_k"] == 10
        assert payload["min_score"] == 0.5
        assert payload["metric"] == "cosine"
        assert payload["use_hybrid"] is True

def test_list_documents_pagination(api_client):
    """Test list documents with pagination."""
    with patch.object(api_client._base, "request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "items": [{"id": "1"}],
            "total": 10,
            "limit": 10,
            "offset": 0
        }
        mock_request.return_value = mock_response
        
        response = api_client.list_documents(limit=10, offset=0)
        
        assert response["total"] == 10
        assert len(response["items"]) == 1
        
        mock_request.assert_called_with(
            "GET",
            "http://test-api/api/v1/documents",
            params={"limit": 10, "offset": 0, "sort_by": "indexed_at", "sort_dir": "desc"}
        )

def test_error_handling(api_client):
    """Test that requests.RequestException is raised on HTTP error."""
    from desktop_app.utils.errors import APIError
    with patch.object(api_client._base, "request") as mock_request:
        mock_request.side_effect = APIError("API Error (404)")
        
        with pytest.raises(APIError):
            api_client.get_document("missing_id")

def test_check_document_exists_true(api_client):
    """Test check_document_exists returns True when found."""
    with patch.object(api_client._base, "request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "1", "metadata": {"file_hash": "abc"}}
        mock_request.return_value = mock_response
        
        assert api_client.check_document_exists("/path/to/doc") is True
        
        # Verify it called get document
        args = mock_request.call_args
        assert args[0][0] == "GET"
        assert "/documents/" in args[0][1]

def test_check_document_exists_false(api_client):
    """Test check_document_exists returns False when not found."""
    with patch.object(api_client._base, "request") as mock_request:
        # Simulate 404 bubbling up as APIError from base client
        from desktop_app.utils.errors import APIError
        mock_request.side_effect = APIError("HTTP 404 Not Found")
        
        assert api_client.check_document_exists("/path/to/doc") is False

def test_check_document_exists_exception(api_client):
    """Test check_document_exists returns False on error."""
    with patch.object(api_client._base, "request", side_effect=Exception("API Error")):
        assert api_client.check_document_exists("/path/to/doc") is False

def test_list_documents_legacy_response(api_client):
    """Test list_documents handles legacy list response."""
    with patch.object(api_client._base, "request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"id": "1"}, {"id": "2"}]
        mock_request.return_value = mock_response
        
        response = api_client.list_documents()
        
        assert response["total"] == 2
        assert len(response["items"]) == 2
        assert response["_total_estimated"] is True

def test_get_document_success(api_client):
    """Test get_document success."""
    with patch.object(api_client._base, "request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "1", "content": "test"}
        mock_request.return_value = mock_response
        
        doc = api_client.get_document("1")
        assert doc["id"] == "1"
        mock_request.assert_called_with("GET", "http://test-api/api/v1/documents/1")

def test_delete_document_success(api_client):
    """Test delete_document success."""
    with patch.object(api_client._base, "request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "deleted"}
        mock_request.return_value = mock_response
        
        response = api_client.delete_document("1")
        assert response["status"] == "deleted"
        mock_request.assert_called_with("DELETE", "http://test-api/api/v1/documents/1")

def test_get_statistics_success(api_client):
    """Test get_statistics success."""
    with patch.object(api_client._base, "request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"total_documents": 100}
        mock_request.return_value = mock_response
        
        stats = api_client.get_statistics()
        assert stats["total_documents"] == 100
        mock_request.assert_called_with("GET", "http://test-api/api/v1/statistics")

def test_bulk_delete_preview(api_client):
    """Test bulk_delete_preview."""
    filters = {"type": "resume"}
    with patch.object(api_client._base, "request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"count": 5, "preview": []}
        mock_request.return_value = mock_response
        
        response = api_client.bulk_delete_preview(filters)
        assert response["count"] == 5
        
        mock_request.assert_called_with(
            "POST",
            "http://test-api/api/v1/documents/bulk-delete",
            json={"filters": filters, "preview": True}
        )

def test_bulk_delete_execute(api_client):
    """Test bulk_delete execution."""
    filters = {"type": "resume"}
    with patch.object(api_client._base, "request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"chunks_deleted": 10}
        mock_request.return_value = mock_response
        
        response = api_client.bulk_delete(filters)
        assert response["chunks_deleted"] == 10
        
        mock_request.assert_called_with(
            "POST",
            "http://test-api/api/v1/documents/bulk-delete",
            json={"filters": filters, "preview": False}
        )

def test_export_documents(api_client):
    """Test export_documents."""
    filters = {"type": "resume"}
    with patch.object(api_client._base, "request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"backup_data": []}
        mock_request.return_value = mock_response
        
        response = api_client.export_documents(filters)
        assert "backup_data" in response
        
        mock_request.assert_called_with(
            "POST",
            "http://test-api/api/v1/documents/export",
            json={"filters": filters}
        )

def test_restore_documents(api_client):
    """Test restore_documents."""
    backup_data = [{"id": "1"}]
    with patch.object(api_client._base, "request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"chunks_restored": 1}
        mock_request.return_value = mock_response
        
        response = api_client.restore_documents(backup_data)
        assert response["chunks_restored"] == 1
        
        mock_request.assert_called_with(
            "POST",
            "http://test-api/api/v1/documents/restore",
            json={"backup_data": backup_data}
        )

def test_get_metadata_keys(api_client):
    """Test get_metadata_keys."""
    with patch.object(api_client._base, "request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = ["author", "date"]
        mock_request.return_value = mock_response
        
        keys = api_client.get_metadata_keys(pattern="auth%")
        assert keys == ["author", "date"]
        
        mock_request.assert_called_with(
            "GET",
            "http://test-api/api/v1/metadata/keys",
            params={"pattern": "auth%"}
        )

def test_get_metadata_values(api_client):
    """Test get_metadata_values."""
    with patch.object(api_client._base, "request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = ["John", "Jane"]
        mock_request.return_value = mock_response
        
        values = api_client.get_metadata_values("author")
        assert values == ["John", "Jane"]
        
        mock_request.assert_called_with(
            "GET",
            "http://test-api/api/v1/metadata/values",
            params={"key": "author"}
        )

def test_register_client(api_client):
    """Test register_client routes correctly."""
    with patch.object(api_client._base, "request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"client_id": "c1"}
        mock_request.return_value = mock_response
        
        res = api_client.register_client(
            client_id="c1", display_name="Test", os_type="linux", app_version="1.0"
        )
        assert res["client_id"] == "c1"
        
        mock_request.assert_called_with(
            "POST",
            "http://test-api/api/v1/clients/register",
            json={"client_id": "c1", "display_name": "Test", "os_type": "linux", "app_version": "1.0"}
        )

def test_list_watched_folders(api_client):
    """Test list_watched_folders routes correctly."""
    with patch.object(api_client._base, "request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"folder_id": "f1"}]
        mock_request.return_value = mock_response
        
        res = api_client.list_watched_folders(enabled_only=True)
        assert res[0]["folder_id"] == "f1"
        
        mock_request.assert_called_with(
            "GET",
            "http://test-api/api/v1/watched-folders",
            params={"enabled_only": True}
        )

def test_list_users(api_client):
    """Test list_users routes correctly."""
    with patch.object(api_client._base, "request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"user_id": "u1"}]
        mock_request.return_value = mock_response
        
        res = api_client.list_users(role="admin", active_only=True)
        assert res[0]["user_id"] == "u1"
        
        mock_request.assert_called_with(
            "GET",
            "http://test-api/api/v1/users",
            params={"role": "admin", "active_only": True}
        )

def test_get_indexing_runs(api_client):
    """Test get_indexing_runs routes correctly."""
    with patch.object(api_client._base, "request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"total": 5}
        mock_request.return_value = mock_response
        
        res = api_client.get_indexing_runs(limit=50)
        assert res["total"] == 5
        
        mock_request.assert_called_with(
            "GET",
            "http://test-api/api/v1/indexing/runs",
            params={"limit": 50}
        )

def test_close(api_client):
    """Test close delegates to base client."""
    with patch.object(api_client._base, "close") as mock_close:
        api_client.close()
        mock_close.assert_called_once()

