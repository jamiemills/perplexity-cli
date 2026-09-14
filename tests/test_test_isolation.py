"""Tests for default test-suite config and network isolation."""

import os
from pathlib import Path

from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.utils.config import get_config_dir
from tests.support import git_isolation, network_guard


def test_default_test_run_uses_isolated_config_dir() -> None:
    """Default test selection must not point TokenManager at the real home dir."""
    config_dir = get_config_dir()
    token_path = TokenManager().token_path
    real_home_token_path = Path.home() / ".config" / "perplexity-cli" / "token.json"

    assert token_path.parent == config_dir
    assert token_path != real_home_token_path


def test_network_guard_active_in_default_lane() -> None:
    """Ordinary tests run with the fail-closed network guard installed."""
    assert network_guard.is_guard_active()
    network_guard.assert_guard_active()


def test_proxy_and_endpoint_environment_scrubbed() -> None:
    """Inherited proxy and Perplexity endpoint overrides are removed."""
    for var in network_guard._SCRUBBED_VARS:
        assert var not in os.environ


def test_git_location_environment_scrubbed() -> None:
    """Inherited git location variables must not redirect test repositories.

    Running pytest from a linked-worktree hook exports ``GIT_DIR`` and
    ``GIT_INDEX_FILE``; if they survive, tests that ``git init`` a temporary
    repository mutate the invoking worktree instead.
    """
    for var in git_isolation.GIT_LOCATION_VARS:
        assert var not in os.environ


def test_scrub_git_location_env_removes_only_location_vars(monkeypatch) -> None:
    """The scrubber clears git location variables and preserves others."""
    for var in git_isolation.GIT_LOCATION_VARS:
        monkeypatch.setenv(var, "decoy")
    monkeypatch.setenv("KEEP_ME", "1")

    git_isolation.scrub_git_location_env()

    for var in git_isolation.GIT_LOCATION_VARS:
        assert var not in os.environ
    assert os.environ["KEEP_ME"] == "1"
