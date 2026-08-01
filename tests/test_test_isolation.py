"""Tests for default test-suite config and network isolation."""

import os
from pathlib import Path

from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.utils.config import get_config_dir
from tests.support import network_guard


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
