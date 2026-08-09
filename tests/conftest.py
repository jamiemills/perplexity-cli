"""Shared test fixtures for the perplexity-cli test suite."""

import logging
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

if os.environ.get("MUTANT_UNDER_TEST"):
    collect_ignore_glob = [
        "test_agent_check_edge_cases.py",
        "test_analyser_contracts.py",
        "test_architecture.py",
        "test_architecture_model.py",
        "test_coupling_metrics.py",
        "test_coverage_policy.py",
        "test_differential_context.py",
        "test_dynamic_imports.py",
        "test_gitleaks.py",
        "test_gitleaks_integration.py",
        "test_gitleaks_prepush.py",
        "test_import_graph.py",
        "test_init_policy.py",
        "test_make_policy.py",
        "test_mutate_diff_files.py",
        "test_mutation_policy.py",
        "test_quality_pipeline_configuration.py",
        "test_quality_ratchets.py",
        "test_removed_plan_gate.py",
        "test_semgrep_wrapper.py",
        "test_suppression_reasons.py",
        "test_suppressions.py",
        "test_workflow_policy.py",
    ]

import pytest
from click.testing import CliRunner
from hypothesis import settings
from hypothesis.database import DirectoryBasedExampleDatabase

from perplexity_cli.threads.cache_manager import ThreadCacheManager
from perplexity_cli.utils.config import clear_feature_config_cache, clear_urls_cache

# Fail-closed network isolation for non-live lanes (installed in
# pytest_configure, before test-module collection).
pytest_plugins = ["tests.support.network_guard"]

# ---------------------------------------------------------------------------
# Hypothesis profiles
# ---------------------------------------------------------------------------

_NORMAL_DB = DirectoryBasedExampleDatabase(".hypothesis")

settings.register_profile(
    "dev",
    max_examples=10,
    deadline=500,
    database=_NORMAL_DB,
    derandomize=False,
    print_blob=False,
)
settings.register_profile(
    "push",
    max_examples=50,
    deadline=500,
    database=_NORMAL_DB,
    derandomize=False,
    print_blob=False,
)
settings.register_profile(
    "ci",
    max_examples=1000,
    deadline=500,
    database=_NORMAL_DB,
    derandomize=False,
    print_blob=False,
)
settings.register_profile(
    "fast",
    max_examples=3,
    deadline=500,
    database=_NORMAL_DB,
    derandomize=False,
    print_blob=False,
)

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


@pytest.fixture(autouse=True, scope="session")
def _wire_query_runner_seams() -> Iterator[None]:
    """Import the composition root so query_runner seams are always bound.

    query_runner's collaborators (get_logger, TokenManager, and friends)
    are injected by cli.py at import time. Without this fixture, tests
    that call run_query_command directly depend on whichever xdist
    worker happened to import cli.py first — a nondeterministic ordering
    dependency that surfaces as ``TypeError: 'NoneType' object is not
    callable`` on unlucky schedules.
    """
    import perplexity_cli.cli  # noqa: F401

    yield


@pytest.fixture(autouse=True)
def _reset_perplexity_logger() -> Iterator[None]:
    """Restore the perplexity_cli logger state around every test.

    setup_logging() mutates the shared logger's level and handlers.
    Without restoration, a DEBUG-level stderr handler leaks into later
    tests on the same worker: it writes debug lines into their captured
    stderr and triggers feature-config materialisation (config.json) at
    unexpected times, which breaks directory-attachment expectations.
    """
    logger = logging.getLogger("perplexity_cli")
    previous_level = logger.level
    previous_handlers = list(logger.handlers)
    previous_propagate = logger.propagate
    yield
    logger.setLevel(previous_level)
    logger.handlers = previous_handlers
    logger.propagate = previous_propagate


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
