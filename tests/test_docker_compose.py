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
    
    def test_db_port_is_loopback_only(self, docker_compose_config):
        """The DB port must be bound to loopback, never to all interfaces.

        A bare '5432:5432' publishes Postgres on every interface, which
        combined with the default credentials exposed the whole index to the
        local network. The app itself reaches the DB over the internal docker
        network (DB_HOST: db), so this mapping is only ever for local psql.
        """
        db_service = docker_compose_config['services']['db']
        assert 'ports' in db_service
        assert '127.0.0.1:5432:5432' in db_service['ports']
        assert '5432:5432' not in db_service['ports']
    
    def test_api_port_is_loopback_by_default(self, docker_compose_config):
        """The API port must default to loopback, like the DB port.

        v2.17.0 turned auth on by default and published the API on every
        interface. A request from the host to a published container port
        arrives from the docker gateway, never 127.0.0.1, so the loopback
        exemption in auth.py cannot fire and every default install 401'd
        against its own machine. The single-machine stack is safe without a
        key only because nothing off the machine can reach it.
        """
        app_service = docker_compose_config['services']['app']
        ports = [str(p) for p in app_service['ports']]
        assert any(p.startswith('${API_BIND_ADDRESS:-127.0.0.1}:') for p in ports), \
            f"API port must publish on 127.0.0.1 by default, got {ports}"
        assert '${API_PORT:-8000}:8000' not in ports, \
            "bare port mapping publishes the API on every interface"

    def test_auth_defaults_off_for_the_single_machine_stack(self, docker_compose_config):
        """Auth off is what makes the loopback-published stack usable.

        Paired with the test above: off is only acceptable while the port is
        published on loopback. If one changes, the other must change with it.
        """
        env = docker_compose_config['services']['app']['environment']
        assert 'API_REQUIRE_AUTH' in env
        assert str(env['API_REQUIRE_AUTH']).endswith(':-false}'), \
            f"expected an overridable default of false, got {env['API_REQUIRE_AUTH']}"

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


class TestInstallScriptIntents:
    """The two install paths must configure opposite, self-consistent defaults.

    docker-run.sh sets up one machine; server-setup.sh sets up a server other
    machines connect to. Publishing on every interface without auth is the
    combination that must never ship (27ad599), and loopback-published with
    auth on is the combination that locks a user out of their own install.
    """

    @pytest.fixture
    def docker_run(self):
        with open("docker-run.sh") as f:
            return f.read()

    @pytest.fixture
    def server_setup(self):
        with open("server-setup.sh") as f:
            return f.read()

    def test_docker_run_is_loopback_and_keyless(self, docker_run):
        assert "API_BIND_ADDRESS=127.0.0.1" in docker_run
        assert "API_REQUIRE_AUTH=false" in docker_run
        assert '"${API_PORT}:8000"' not in docker_run, \
            "the inline compose would publish the API on every interface"

    def test_server_setup_is_networked_and_authenticated(self, server_setup):
        assert "set_env_var API_BIND_ADDRESS 0.0.0.0" in server_setup
        assert "set_env_var API_REQUIRE_AUTH true" in server_setup

    def test_server_setup_bootstraps_its_key_in_container(self, server_setup):
        """The key endpoint is itself authenticated, so HTTP bootstrap 401s."""
        assert "create_api_key_record" in server_setup
        assert "api/v1/api-keys" not in server_setup, \
            "bootstrapping the first key over HTTP cannot work with auth on"
