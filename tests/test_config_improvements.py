"""Tests for improved configuration management."""

from perplexity_cli.utils.config import (
    clear_urls_cache,
    get_urls,
)


class TestConfigEnvironmentVariables:
    """Test environment variable overrides."""

    def test_env_var_override_base_url(self, monkeypatch):
        """Test that PERPLEXITY_BASE_URL overrides config."""
        monkeypatch.setenv("PERPLEXITY_BASE_URL", "https://custom.example.com")

        # Clear cache to force reload
        clear_urls_cache()

        urls = get_urls()
        assert urls.base_url == "https://custom.example.com"

    def test_env_var_override_query_endpoint(self, monkeypatch):
        """Test that PERPLEXITY_QUERY_ENDPOINT overrides config."""
        monkeypatch.setenv("PERPLEXITY_QUERY_ENDPOINT", "https://custom.example.com/api")

        # Clear cache to force reload
        clear_urls_cache()

        urls = get_urls()
        assert urls.query_endpoint == "https://custom.example.com/api"

    def test_env_var_override_both(self, monkeypatch):
        """Test that both env vars can override config."""
        monkeypatch.setenv("PERPLEXITY_BASE_URL", "https://custom1.example.com")
        monkeypatch.setenv("PERPLEXITY_QUERY_ENDPOINT", "https://custom2.example.com/api")

        # Clear cache to force reload
        clear_urls_cache()

        urls = get_urls()
        assert urls.base_url == "https://custom1.example.com"
        assert urls.query_endpoint == "https://custom2.example.com/api"


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
