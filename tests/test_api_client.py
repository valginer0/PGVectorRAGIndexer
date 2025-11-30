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
        assert api_client.is_api_available() is True
        mock_get.assert_called_with("http://test-api/health", timeout=5)

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
        assert call_args[0][0] == "http://test-api/upload-and-index"
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
            "http://test-api/documents",
            params={"limit": 10, "offset": 0, "sort_by": "indexed_at", "sort_dir": "desc"},
            timeout=300
        )

def test_error_handling(api_client):
    """Test that requests.RequestException is raised on HTTP error."""
    with patch("requests.get") as mock_get:
        mock_get.return_value.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        
        with pytest.raises(requests.RequestException):
            api_client.get_document("missing_id")
