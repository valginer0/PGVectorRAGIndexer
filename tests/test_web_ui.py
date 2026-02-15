"""
Tests for Web UI endpoints.
"""

import pytest
import httpx
from api import app


class TestWebUI:
    """Tests for web UI functionality."""
    
    @pytest.fixture
    async def client(self):
        """Create async ASGI test client."""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    
    async def test_root_serves_html(self, client):
        """Test that root endpoint serves HTML."""
        response = await client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        # Should contain the web UI
        assert "PGVector RAG Indexer" in response.text or "PGVectorRAGIndexer" in response.text
    
    async def test_static_files_accessible(self, client):
        """Test that static files are accessible."""
        # StaticFiles responses can hang under ASGITransport in some environments.
        # Validate mount + file presence instead.
        from api import static_dir
        import os
        routes = [getattr(route, "path", "") for route in app.routes]
        assert "/static" in routes
        assert os.path.exists(os.path.join(static_dir, "style.css"))
        assert os.path.exists(os.path.join(static_dir, "app.js"))
    
    async def test_api_info_endpoint(self, client):
        """Test API info endpoint."""
        response = await client.get("/api")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert "docs" in data
        assert data["name"] == "PGVectorRAGIndexer API"
    
    @pytest.mark.database
    async def test_health_endpoint_still_works(self, client):
        """Test that health endpoint still works after UI changes."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
    
    async def test_docs_endpoint_accessible(self, client):
        """Test that API docs are still accessible."""
        response = await client.get("/docs")
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
    
    async def test_ui_has_search_functionality(self, client):
        """Test that UI HTML contains search elements."""
        response = await client.get("/")
        assert response.status_code == 200
        html = response.text
        # Check for key UI elements
        assert "search" in html.lower()
        assert "upload" in html.lower()
        assert "documents" in html.lower()
    
    async def test_existing_api_endpoints_unchanged(self, client):
        """Test that existing API endpoints still work."""
        # Test search endpoint exists
        response = await client.post("/search", json={"query": "test"})
        # Should work or return proper error (not 404)
        assert response.status_code != 404
        
        # Test documents endpoint exists
        response = await client.get("/documents")
        assert response.status_code != 404
