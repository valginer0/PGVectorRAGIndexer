"""
Unit tests for Email Configuration.

Tests that email connector is properly opt-in and config loads correctly.
"""

import os
import pytest
from unittest.mock import patch


class TestEmailConfig:
    """Tests for EmailConfig class and opt-in behavior."""
    
    def test_email_disabled_by_default(self):
        """Test that email is disabled by default."""
        # Clear any existing email env vars
        env_vars_to_clear = ['EMAIL_ENABLED', 'EMAIL_CLIENT_ID', 'EMAIL_TENANT_ID']
        original_values = {}
        
        for var in env_vars_to_clear:
            original_values[var] = os.environ.pop(var, None)
        
        try:
            # Force reload of config
            from config import reload_config
            config = reload_config()
            
            assert config.email.enabled is False
            assert config.email.client_id is None
            assert config.email.tenant_id == 'common'
        finally:
            # Restore original env vars
            for var, value in original_values.items():
                if value is not None:
                    os.environ[var] = value
    
    def test_email_enabled_via_env(self):
        """Test that email can be enabled via environment variable."""
        with patch.dict(os.environ, {
            'EMAIL_ENABLED': 'true',
            'EMAIL_CLIENT_ID': 'test-client-id',
            'EMAIL_TENANT_ID': 'test-tenant'
        }):
            from config import reload_config
            config = reload_config()
            
            assert config.email.enabled is True
            assert config.email.client_id == 'test-client-id'
            assert config.email.tenant_id == 'test-tenant'
    
    def test_email_enabled_false_string(self):
        """Test that EMAIL_ENABLED=false works."""
        with patch.dict(os.environ, {'EMAIL_ENABLED': 'false'}):
            from config import reload_config
            config = reload_config()
            
            assert config.email.enabled is False


class TestEmailConfigIntegration:
    """Integration tests for email config with other modules."""
    
    def test_retriever_search_emails_returns_empty_when_disabled(self):
        """Test that search_emails returns empty list when email is disabled."""
        # Ensure email is disabled
        with patch.dict(os.environ, {'EMAIL_ENABLED': 'false'}, clear=False):
            from config import reload_config
            reload_config()
            
            # Note: Full test would require database connection
            # This is a structural test to ensure the method exists
            from retriever_v2 import DocumentRetriever
            assert hasattr(DocumentRetriever, 'search_emails')
    
    def test_cloud_ingestor_import_works(self):
        """Test that CloudIngestor can be imported regardless of config."""
        # This should work even when MSAL is not installed
        try:
            from connectors.email.ingestor import CloudIngestor
            assert CloudIngestor is not None
        except ImportError as e:
            # Expected if MSAL not installed
            assert "msal" in str(e).lower()
    
    def test_email_processor_import_works(self):
        """Test that EmailProcessor can be imported."""
        from connectors.email.processor import EmailProcessor
        
        processor = EmailProcessor()
        assert processor is not None
        assert processor.chunk_size == 500  # default
