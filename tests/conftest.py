"""Shared test fixtures for the perplexity-cli test suite."""

import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner
from hypothesis import settings

from perplexity_cli.threads.cache_manager import ThreadCacheManager
from perplexity_cli.utils.config import clear_feature_config_cache, clear_urls_cache

# ---------------------------------------------------------------------------
# Hypothesis profiles
# ---------------------------------------------------------------------------

settings.register_profile("dev", max_examples=10, print_blob=False)
settings.register_profile("push", max_examples=50, print_blob=False)
settings.register_profile("ci", max_examples=1000, deadline=500)
settings.register_profile("fast", max_examples=3, print_blob=False)

# ---------------------------------------------------------------------------


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
def _clear_config_caches():
    """Clear config caches before and after every test.

    This ensures no stale URL or feature-config state leaks between tests,
    regardless of whether the test uses real or isolated config paths.
    """
    clear_urls_cache()
    clear_feature_config_cache()
    yield
    clear_urls_cache()
    clear_feature_config_cache()


@pytest.fixture(autouse=True)
def isolate_config_dir(tmp_path, monkeypatch, request):
    """Route config-backed tests to an isolated temp directory.

    Tests marked with ``@pytest.mark.real_user_config`` opt out of path
    isolation, allowing them to exercise the real config-loading path while
    ``_clear_config_caches`` still prevents state leakage.
    """
    if request.node.get_closest_marker("real_user_config"):
        yield
    else:
        config_dir = tmp_path / "perplexity-cli-config"
        monkeypatch.setenv("PERPLEXITY_CONFIG_DIR", str(config_dir))
        yield


# ---------------------------------------------------------------------------
# Integration harness fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def harness_server():
    """Provide a started local loopback ProtocolServer and stop it after.

    Binds to a random free port on 127.0.0.1.  Tests configure canned
    responses via ``server.query_response``, ``server.upload_url_response``,
    and ``server.upload_put_response`` before issuing requests.
    """
    from tests.support.protocol_server import ProtocolServer

    srv = ProtocolServer()
    srv.start()
    try:
        yield srv
    finally:
        srv.stop()


@pytest.fixture
def fake_time(harness_server):
    """Provide the harness server's fake clock for retry-timing tests.

    Sets ``fake_now`` to a known epoch so tests can advance time
    deterministically through ``harness_server.advance_clock()``.
    """
    from tests.support.protocol_server import fake_time_monotonic

    return lambda: fake_time_monotonic(harness_server)


@pytest.fixture
def harness_config(harness_server, monkeypatch):
    """Point the query endpoint at the local harness server.

    Overrides ``PERPLEXITY_QUERY_ENDPOINT``, ``PERPLEXITY_UPLOAD_URL_ENDPOINT``,
    and ``PERPLEXITY_S3_BUCKET_URL`` so integration tests never reach the
    real internet.  The ``_guard_network`` fixture provides a second layer.
    """
    monkeypatch.setenv("PERPLEXITY_QUERY_ENDPOINT", f"{harness_server.url}/api/query")
    monkeypatch.setenv(
        "PERPLEXITY_UPLOAD_URL_ENDPOINT",
        f"{harness_server.url}/api/upload-url",
    )
    monkeypatch.setenv("PERPLEXITY_S3_BUCKET_URL", f"{harness_server.url}/upload")
    return harness_server
