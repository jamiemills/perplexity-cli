"""Shared test fixtures for the perplexity-cli test suite."""

import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from perplexity_cli.threads.cache_manager import ThreadCacheManager


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
