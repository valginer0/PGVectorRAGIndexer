"""
Tests for Dockerfile configuration.
"""

import pytest
import os


class TestDockerfile:
    """Tests for Dockerfile."""
    
    def test_dockerfile_exists(self):
        """Test that Dockerfile exists."""
        assert os.path.exists("Dockerfile"), "Dockerfile should exist"
    
    def test_dockerfile_copies_static_directory(self):
        """Test that Dockerfile includes COPY command for static directory."""
        with open("Dockerfile", 'r') as f:
            content = f.read()
        
        # Check that static directory is copied
        assert "COPY static/" in content or "COPY static " in content, \
            "Dockerfile must copy static/ directory for Web UI"
    
    def test_dockerfile_copies_python_files(self):
        """Test that Dockerfile copies Python files."""
        with open("Dockerfile", 'r') as f:
            content = f.read()
        
        assert "COPY *.py" in content, "Dockerfile must copy Python files"
    
    def test_dockerfile_exposes_port_8000(self):
        """Test that Dockerfile exposes port 8000."""
        with open("Dockerfile", 'r') as f:
            content = f.read()
        
        assert "EXPOSE 8000" in content, "Dockerfile must expose port 8000"
    
    def test_dockerfile_has_healthcheck(self):
        """Test that Dockerfile includes health check."""
        with open("Dockerfile", 'r') as f:
            content = f.read()
        
        assert "HEALTHCHECK" in content, "Dockerfile should include health check"
    
    def test_dockerfile_uses_uvicorn(self):
        """Test that Dockerfile uses uvicorn to run the app."""
        with open("Dockerfile", 'r') as f:
            content = f.read()
        
        assert "uvicorn" in content.lower(), "Dockerfile should use uvicorn"
        assert "api:app" in content, "Dockerfile should run api:app"
