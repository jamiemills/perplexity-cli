"""Shared test fixtures for the perplexity-cli test suite."""

import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from perplexity_cli.threads.cache_manager import ThreadCacheManager
from perplexity_cli.utils.config import clear_feature_config_cache, clear_urls_cache


@pytest.fixture
def runner():
    """Create a Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_cache_path():
    """Provide a temporary cache file path in a temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test-cache.json"


@pytest.fixture
def cache_manager(temp_cache_path):
    """Provide a ThreadCacheManager instance with a temporary cache path."""
    return ThreadCacheManager(cache_path=temp_cache_path)


@pytest.fixture(autouse=True)
def isolate_config_dir(tmp_path, monkeypatch, request):
    """Route config-backed tests to an isolated temp directory by default."""
    clear_urls_cache()
    clear_feature_config_cache()

    if request.node.get_closest_marker("real_user_config"):
        yield
    else:
        config_dir = tmp_path / "perplexity-cli-config"
        monkeypatch.setenv("PERPLEXITY_CONFIG_DIR", str(config_dir))
        yield

    clear_urls_cache()
    clear_feature_config_cache()
