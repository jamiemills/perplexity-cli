"""Tests for default test-suite config isolation."""

from pathlib import Path

from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.utils.config import get_config_dir


def test_default_test_run_uses_isolated_config_dir() -> None:
    """Default test selection must not point TokenManager at the real home dir."""
    config_dir = get_config_dir()
    token_path = TokenManager().token_path
    real_home_token_path = Path.home() / ".config" / "perplexity-cli" / "token.json"

    assert token_path.parent == config_dir
    assert token_path != real_home_token_path
