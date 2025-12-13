"""
Tests for Web UI endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from api import app


class TestWebUI:
    """Tests for web UI functionality."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)
    
    def test_root_serves_html(self, client):
        """Test that root endpoint serves HTML."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        # Should contain the web UI
        assert "PGVector RAG Indexer" in response.text or "PGVectorRAGIndexer" in response.text
    
    def test_static_files_accessible(self, client):
        """Test that static files are accessible."""
        # Test CSS file
        response = client.get("/static/style.css")
        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]
        
        # Test JS file
        response = client.get("/static/app.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"] or "application/javascript" in response.headers["content-type"]
    
    def test_api_info_endpoint(self, client):
        """Test API info endpoint."""
        response = client.get("/api")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert "docs" in data
        assert data["name"] == "PGVectorRAGIndexer API"
    
    @pytest.mark.database
    def test_health_endpoint_still_works(self, client):
        """Test that health endpoint still works after UI changes."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
    
    def test_docs_endpoint_accessible(self, client):
        """Test that API docs are still accessible."""
        response = client.get("/docs")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
    
    def test_static_directory_exists(self):
        """Test that static directory exists."""
        import os
        from api import static_dir
        assert os.path.exists(static_dir), "Static directory should exist"
        assert os.path.isdir(static_dir), "Static path should be a directory"
    
    def test_index_html_exists(self):
        """Test that index.html exists."""
        import os
        from api import static_dir
        index_path = os.path.join(static_dir, "index.html")
        assert os.path.exists(index_path), "index.html should exist"
    
    def test_css_file_exists(self):
        """Test that style.css exists."""
        import os
        from api import static_dir
        css_path = os.path.join(static_dir, "style.css")
        assert os.path.exists(css_path), "style.css should exist"
    
    def test_js_file_exists(self):
        """Test that app.js exists."""
        import os
        from api import static_dir
        js_path = os.path.join(static_dir, "app.js")
        assert os.path.exists(js_path), "app.js should exist"
    
    def test_ui_has_search_functionality(self, client):
        """Test that UI HTML contains search elements."""
        response = client.get("/")
        assert response.status_code == 200
        html = response.text
        # Check for key UI elements
        assert "search" in html.lower()
        assert "upload" in html.lower()
        assert "documents" in html.lower()
    
    def test_existing_api_endpoints_unchanged(self, client):
        """Test that existing API endpoints still work."""
        # Test search endpoint exists
        response = client.post("/search", json={"query": "test"})
        # Should work or return proper error (not 404)
        assert response.status_code != 404
        
        # Test documents endpoint exists
        response = client.get("/documents")
        assert response.status_code != 404
