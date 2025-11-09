"""Tests for improved configuration management."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from perplexity_cli.utils.config import (
    _validate_urls_config,
    clear_urls_cache,
    get_urls,
)


class TestConfigValidation:
    """Test configuration validation."""

    def test_validate_urls_config_valid(self):
        """Test validation of valid config."""
        config = {
            "perplexity": {
                "base_url": "https://www.perplexity.ai",
                "query_endpoint": "https://www.perplexity.ai/rest/sse/perplexity_ask",
            }
        }
        # Should not raise
        _validate_urls_config(config)

    def test_validate_urls_config_missing_perplexity(self):
        """Test validation fails when perplexity section missing."""
        config = {}
        with pytest.raises(RuntimeError, match="missing 'perplexity' section"):
            _validate_urls_config(config)

    def test_validate_urls_config_missing_base_url(self):
        """Test validation fails when base_url missing."""
        config = {
            "perplexity": {
                "query_endpoint": "https://www.perplexity.ai/rest/sse/perplexity_ask",
            }
        }
        with pytest.raises(RuntimeError, match="missing 'perplexity.base_url'"):
            _validate_urls_config(config)

    def test_validate_urls_config_empty_base_url(self):
        """Test validation fails when base_url is empty."""
        config = {
            "perplexity": {
                "base_url": "",
                "query_endpoint": "https://www.perplexity.ai/rest/sse/perplexity_ask",
            }
        }
        with pytest.raises(RuntimeError, match="cannot be empty"):
            _validate_urls_config(config)


class TestConfigEnvironmentVariables:
    """Test environment variable overrides."""

    def test_env_var_override_base_url(self, monkeypatch):
        """Test that PERPLEXITY_BASE_URL overrides config."""
        monkeypatch.setenv("PERPLEXITY_BASE_URL", "https://custom.example.com")
        
        # Clear cache to force reload
        clear_urls_cache()
        
        urls = get_urls()
        assert urls["perplexity"]["base_url"] == "https://custom.example.com"

    def test_env_var_override_query_endpoint(self, monkeypatch):
        """Test that PERPLEXITY_QUERY_ENDPOINT overrides config."""
        monkeypatch.setenv("PERPLEXITY_QUERY_ENDPOINT", "https://custom.example.com/api")
        
        # Clear cache to force reload
        clear_urls_cache()
        
        urls = get_urls()
        assert urls["perplexity"]["query_endpoint"] == "https://custom.example.com/api"

    def test_env_var_override_both(self, monkeypatch):
        """Test that both env vars can override config."""
        monkeypatch.setenv("PERPLEXITY_BASE_URL", "https://custom1.example.com")
        monkeypatch.setenv("PERPLEXITY_QUERY_ENDPOINT", "https://custom2.example.com/api")
        
        # Clear cache to force reload
        clear_urls_cache()
        
        urls = get_urls()
        assert urls["perplexity"]["base_url"] == "https://custom1.example.com"
        assert urls["perplexity"]["query_endpoint"] == "https://custom2.example.com/api"


class TestConfigCache:
    """Test configuration caching."""

    def test_clear_urls_cache(self):
        """Test clearing URLs cache."""
        # Should not raise
        clear_urls_cache()
        
        # Cache should be cleared, next call should reload
        urls1 = get_urls()
        clear_urls_cache()
        urls2 = get_urls()
        assert urls1 == urls2

