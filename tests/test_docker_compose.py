"""
Tests for docker-compose.yml configuration.
"""

import pytest
import os
import yaml


class TestDockerCompose:
    """Tests for docker-compose.yml."""
    
    @pytest.fixture
    def docker_compose_config(self):
        """Load docker-compose.yml configuration."""
        with open("docker-compose.yml", 'r') as f:
            return yaml.safe_load(f)
    
    def test_docker_compose_exists(self):
        """Test that docker-compose.yml exists."""
        assert os.path.exists("docker-compose.yml"), "docker-compose.yml should exist"
    
    def test_has_db_service(self, docker_compose_config):
        """Test that docker-compose.yml defines db service."""
        assert 'services' in docker_compose_config
        assert 'db' in docker_compose_config['services']
    
    def test_has_app_service(self, docker_compose_config):
        """Test that docker-compose.yml defines app service."""
        assert 'services' in docker_compose_config
        assert 'app' in docker_compose_config['services'], \
            "docker-compose.yml must include app service for complete deployment"
    
    def test_db_uses_pgvector_image(self, docker_compose_config):
        """Test that db service uses pgvector image."""
        db_service = docker_compose_config['services']['db']
        assert 'pgvector' in db_service['image'].lower()
    
    def test_app_uses_correct_image(self, docker_compose_config):
        """Test that production docker-compose uses GHCR image."""
        app_service = docker_compose_config['services']['app']
        # Production docker-compose.yml must pull from GHCR
        assert 'image' in app_service, "Production docker-compose.yml must use 'image:', not 'build:'"
        assert 'ghcr.io/valginer0/pgvectorragindexer' in app_service['image']
    
    def test_app_depends_on_db(self, docker_compose_config):
        """Test that app service depends on db."""
        app_service = docker_compose_config['services']['app']
        assert 'depends_on' in app_service
        assert 'db' in app_service['depends_on']
    
    def test_db_has_healthcheck(self, docker_compose_config):
        """Test that db service has healthcheck."""
        db_service = docker_compose_config['services']['db']
        assert 'healthcheck' in db_service
    
    def test_app_exposes_port_8000(self, docker_compose_config):
        """Test that app service exposes port 8000."""
        app_service = docker_compose_config['services']['app']
        assert 'ports' in app_service
        ports = app_service['ports']
        # Check if any port mapping includes 8000
        assert any('8000' in str(port) for port in ports)
    
    def test_db_exposes_port_5432(self, docker_compose_config):
        """Test that db service exposes port 5432."""
        db_service = docker_compose_config['services']['db']
        assert 'ports' in db_service
        assert '5432:5432' in db_service['ports']
    
    def test_has_named_volumes(self, docker_compose_config):
        """Test that docker-compose.yml defines named volumes."""
        assert 'volumes' in docker_compose_config
        assert 'postgres_data' in docker_compose_config['volumes']
    
    def test_has_network(self, docker_compose_config):
        """Test that docker-compose.yml defines network."""
        assert 'networks' in docker_compose_config
        assert 'rag_network' in docker_compose_config['networks']
    
    def test_app_connects_to_db_via_network(self, docker_compose_config):
        """Test that both services use the same network."""
        db_service = docker_compose_config['services']['db']
        app_service = docker_compose_config['services']['app']
        
        assert 'networks' in db_service
        assert 'networks' in app_service
        assert 'rag_network' in db_service['networks']
        assert 'rag_network' in app_service['networks']
    
    def test_app_has_db_environment_variables(self, docker_compose_config):
        """Test that app service has database connection environment variables."""
        app_service = docker_compose_config['services']['app']
        assert 'environment' in app_service
        env = app_service['environment']
        
        # Check for database connection variables
        assert 'DB_HOST' in env
        assert 'POSTGRES_USER' in env
        assert 'POSTGRES_PASSWORD' in env
        assert 'POSTGRES_DB' in env
