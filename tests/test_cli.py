"""Tests for CLI commands."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from perplexity_cli.api.models import Answer
from perplexity_cli.cli import (
    auth,
    clear_style,
    configure,
    export_threads,
    logout,
    main,
    query,
    show_config,
    status,
    view_style,
)


def _make_api_mock(**kwargs):
    """Create a Mock for PerplexityAPI that supports context manager protocol.

    Returns a mock that can be used with ``with PerplexityAPI(...) as api:``.
    Any keyword arguments are set as attributes on the mock instance.
    """
    mock_api = MagicMock()
    mock_api.__enter__ = Mock(return_value=mock_api)
    mock_api.__exit__ = Mock(return_value=False)
    for key, value in kwargs.items():
        setattr(mock_api, key, value)
    return mock_api


class TestCLICommands:
    """Test CLI command functionality."""

    def test_main_help(self, runner):
        """Test main command shows help."""
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Perplexity CLI" in result.output
        assert "auth" in result.output
        assert "query" in result.output
        assert "logout" in result.output
        assert "status" in result.output

    def test_main_version(self, runner):
        """Test version option."""
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.4.4" in result.output

    @patch("perplexity_cli.cli.TokenManager")
    def test_status_not_authenticated(self, mock_tm_class, runner):
        """Test status when not authenticated."""
        mock_tm = Mock()
        mock_tm.token_exists.return_value = False
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(status)

        assert result.exit_code == 0
        assert "Not authenticated" in result.output
        assert "pxcli auth" in result.output

    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_status_authenticated(self, mock_api_class, mock_tm_class, runner):
        """Test status when authenticated."""
        from datetime import datetime
        from pathlib import Path

        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.load_token.return_value = ("test-token-123", None)
        mock_token_path = MagicMock(spec=Path)
        mock_token_path.__str__ = lambda x: "/path/to/token.json"
        mock_token_path.exists.return_value = True
        # Mock stat() method
        mock_stat = Mock()
        mock_stat.st_mtime = datetime.now().timestamp()
        mock_token_path.stat.return_value = mock_stat
        mock_tm.token_path = mock_token_path
        mock_tm_class.return_value = mock_tm

        # Mock the API verification with context manager support
        mock_answer = Mock()
        mock_answer.text = "test answer"
        mock_answer.references = []
        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = mock_answer
        mock_api_class.return_value = mock_api

        result = runner.invoke(status)

        assert result.exit_code == 0
        assert "Authenticated" in result.output
        assert "Token is valid and working" in result.output

    @patch("perplexity_cli.cli.TokenManager")
    def test_logout_no_token(self, mock_tm_class, runner):
        """Test logout when no token exists."""
        mock_tm = Mock()
        mock_tm.token_exists.return_value = False
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(logout)

        assert result.exit_code == 0
        assert "No stored credentials" in result.output

    @patch("perplexity_cli.cli.TokenManager")
    def test_logout_success(self, mock_tm_class, runner):
        """Test successful logout."""
        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.clear_token.return_value = None
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(logout)

        assert result.exit_code == 0
        assert "Logged out successfully" in result.output
        mock_tm.clear_token.assert_called_once()

    @patch("perplexity_cli.cli.StyleManager")
    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_query_success(self, mock_api_class, mock_tm_class, mock_sm_class, runner):
        """Test successful query."""
        # Mock style manager (no style configured)
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        # Mock token manager
        mock_tm = Mock()
        mock_tm.load_token.return_value = ("test-token", None)
        mock_tm_class.return_value = mock_tm

        # Mock API with context manager support
        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = Answer(text="Test answer", references=[])
        mock_api._format_references.return_value = ""
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["--no-stream", "What is Python?"])

        assert result.exit_code == 0
        assert "Test answer" in result.output
        mock_api.get_complete_answer.assert_called_once_with(
            "What is Python?", search_implementation_mode="standard"
        )

    @patch("perplexity_cli.cli.StyleManager")
    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_query_success_with_references(
        self, mock_api_class, mock_tm_class, mock_sm_class, runner
    ):
        """Test successful query with references."""
        from perplexity_cli.api.models import WebResult

        # Mock style manager (no style configured)
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        # Mock token manager
        mock_tm = Mock()
        mock_tm.load_token.return_value = ("test-token", None)
        mock_tm_class.return_value = mock_tm

        # Create web results
        refs = [
            WebResult(
                name="Wikipedia",
                url="https://en.wikipedia.org/wiki/Python",
                snippet="Python programming language",
            ),
            WebResult(
                name="Python.org", url="https://www.python.org", snippet="Official Python website"
            ),
        ]

        # Mock API with context manager support
        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = Answer(text="Test answer", references=refs)
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["--no-stream", "What is Python?"])

        assert result.exit_code == 0
        assert "Test answer" in result.output
        # Rich table format is now used by default
        assert "Wikipedia" in result.output or "#" in result.output  # References table
        assert "https://en.wikipedia.org/wiki/Python" in result.output
        assert "https://www.python.org" in result.output

    @patch("perplexity_cli.cli.TokenManager")
    def test_query_not_authenticated(self, mock_tm_class, runner):
        """Test query when not authenticated."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(query, ["test query"])

        assert result.exit_code == 1
        assert "Not authenticated" in result.output
        assert "pxcli auth" in result.output

    @patch("perplexity_cli.cli.StyleManager")
    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_query_network_error(self, mock_api_class, mock_tm_class, mock_sm_class, runner):
        """Test query with network error."""
        import httpx

        # Mock style manager (no style configured)
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        # Mock token manager
        mock_tm = Mock()
        mock_tm.load_token.return_value = ("test-token", None)
        mock_tm_class.return_value = mock_tm

        # Mock API with context manager support
        mock_api = _make_api_mock()
        mock_api.get_complete_answer.side_effect = httpx.RequestError("Connection failed")
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["--no-stream", "test"])

        assert result.exit_code == 1
        assert "Network error" in result.output

    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.authenticate_sync")
    def test_auth_success(self, mock_auth, mock_tm_class, runner):
        """Test successful authentication."""
        # Mock authentication - returns (token, cookies) tuple
        mock_cookies = {"__cf_bm": "test", "__cflb": "test2"}
        mock_auth.return_value = ("new-token-123", mock_cookies)

        # Mock token manager
        mock_tm = Mock()
        mock_tm.token_path = "/path/to/token.json"
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(auth)

        assert result.exit_code == 0
        assert "Authentication successful" in result.output
        mock_tm.save_token.assert_called_once_with("new-token-123", cookies=mock_cookies)

    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.authenticate_sync")
    def test_auth_failure(self, mock_auth, mock_tm_class, runner):
        """Test authentication failure."""
        # Mock authentication failure
        mock_auth.side_effect = RuntimeError("Chrome not found")

        result = runner.invoke(auth)

        assert result.exit_code == 1
        assert "Authentication failed" in result.output
        assert "Troubleshooting" in result.output


@pytest.mark.integration
class TestCLIIntegration:
    """Integration tests for CLI with real components."""

    def test_status_with_real_token(self, runner):
        """Test status command with real token if available."""
        result = runner.invoke(status)
        assert result.exit_code == 0
        # Should show either authenticated or not authenticated
        assert "Status:" in result.output

    def test_logout_and_status(self, runner):
        """Test logout followed by status check."""
        # First logout
        result1 = runner.invoke(logout)
        assert result1.exit_code == 0

        # Then check status
        result2 = runner.invoke(status)
        assert result2.exit_code == 0

    @patch("perplexity_cli.cli.StyleManager")
    def test_configure_style(self, mock_sm_class, runner):
        """Test configure command saves style."""
        mock_sm = Mock()
        mock_sm_class.return_value = mock_sm

        result = runner.invoke(configure, ["be brief and concise"])
        assert result.exit_code == 0
        assert "Style configured successfully" in result.output
        mock_sm.save_style.assert_called_once_with("be brief and concise")

    @patch("perplexity_cli.cli.StyleManager")
    def test_configure_style_error(self, mock_sm_class, runner):
        """Test configure command handles save errors."""
        mock_sm = Mock()
        mock_sm.save_style.side_effect = ValueError("Invalid style")
        mock_sm_class.return_value = mock_sm

        result = runner.invoke(configure, [""])
        assert result.exit_code == 1
        assert "Invalid style" in result.output

    @patch("perplexity_cli.cli.StyleManager")
    def test_view_style_when_set(self, mock_sm_class, runner):
        """Test view-style shows configured style."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = "be brief"
        mock_sm_class.return_value = mock_sm

        result = runner.invoke(view_style)
        assert result.exit_code == 0
        assert "Current style:" in result.output
        assert "be brief" in result.output

    @patch("perplexity_cli.cli.StyleManager")
    def test_view_style_when_not_set(self, mock_sm_class, runner):
        """Test view-style when no style configured."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        result = runner.invoke(view_style)
        assert result.exit_code == 0
        assert "No style configured" in result.output

    @patch("perplexity_cli.cli.StyleManager")
    def test_clear_style_when_set(self, mock_sm_class, runner):
        """Test clear-style removes style."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = "old style"
        mock_sm_class.return_value = mock_sm

        result = runner.invoke(clear_style)
        assert result.exit_code == 0
        assert "Style cleared successfully" in result.output
        mock_sm.clear_style.assert_called_once()

    @patch("perplexity_cli.cli.StyleManager")
    def test_clear_style_when_not_set(self, mock_sm_class, runner):
        """Test clear-style when no style configured."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        result = runner.invoke(clear_style)
        assert result.exit_code == 0
        assert "No style is currently configured" in result.output

    @patch("perplexity_cli.cli.StyleManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    @patch("perplexity_cli.cli.TokenManager")
    def test_query_with_style_appended(self, mock_tm_class, mock_api_class, mock_sm_class, runner):
        """Test query appends style to query text."""
        # Mock token manager
        mock_tm = Mock()
        mock_tm.load_token.return_value = ("test_token", None)
        mock_tm_class.return_value = mock_tm

        # Mock style manager
        mock_sm = Mock()
        mock_sm.load_style.return_value = "be brief"
        mock_sm_class.return_value = mock_sm

        # Mock API with context manager support
        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = Answer(text="Test answer", references=[])
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["--no-stream", "What is Python?"])
        assert result.exit_code == 0
        assert "Test answer" in result.output

        # Verify style was appended to query
        called_query = mock_api.get_complete_answer.call_args[0][0]
        assert "What is Python?" in called_query
        assert "be brief" in called_query
        assert "\n\n" in called_query


class TestShowConfig:
    """Test show-config command with Pydantic model returns."""

    @patch("perplexity_cli.utils.config.get_feature_config_path")
    @patch("perplexity_cli.utils.config.get_feature_config")
    def test_show_config_uses_attribute_access(self, mock_get_config, mock_get_path, runner):
        """Test that show_config accesses Pydantic model attributes, not dict keys."""
        from pathlib import Path

        from perplexity_cli.config.models import FeatureConfig

        mock_get_config.return_value = FeatureConfig(save_cookies=True, debug_mode=False)
        mock_get_path.return_value = Path("/tmp/test-config.json")

        result = runner.invoke(show_config)

        assert result.exit_code == 0
        assert "save_cookies: True" in result.output
        assert "debug_mode:   False" in result.output

    @patch("perplexity_cli.utils.config.get_feature_config_path")
    @patch("perplexity_cli.utils.config.get_feature_config")
    def test_show_config_default_values(self, mock_get_config, mock_get_path, runner):
        """Test show_config with default FeatureConfig values."""
        from pathlib import Path

        from perplexity_cli.config.models import FeatureConfig

        mock_get_config.return_value = FeatureConfig()
        mock_get_path.return_value = Path("/tmp/test-config.json")

        result = runner.invoke(show_config)

        assert result.exit_code == 0
        assert "save_cookies: False" in result.output
        assert "debug_mode:   False" in result.output


class TestExportThreadsRateLimitConfig:
    """Test export-threads command uses Pydantic model attribute access for rate limiting."""

    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.utils.config.get_rate_limiting_config")
    def test_export_threads_rate_limit_attribute_access(
        self, mock_get_rl_config, mock_tm_class, runner
    ):
        """Test that export_threads accesses RateLimitConfig attributes, not dict keys."""
        from perplexity_cli.config.models import RateLimitConfig

        # Mock token manager - not authenticated to exit early after rate limit setup
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        mock_tm_class.return_value = mock_tm

        mock_get_rl_config.return_value = RateLimitConfig(
            enabled=True, requests_per_period=10, period_seconds=30.0
        )

        result = runner.invoke(export_threads)

        # Should exit with auth error, but the rate limit config access should not raise TypeError
        assert "Not authenticated" in result.output

    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.utils.config.get_rate_limiting_config")
    def test_export_threads_rate_limit_disabled(self, mock_get_rl_config, mock_tm_class, runner):
        """Test export_threads when rate limiting is disabled."""
        from perplexity_cli.config.models import RateLimitConfig

        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        mock_tm_class.return_value = mock_tm

        mock_get_rl_config.return_value = RateLimitConfig(
            enabled=False, requests_per_period=20, period_seconds=60.0
        )

        result = runner.invoke(export_threads)

        # Should exit with auth error, no TypeError on rate limit config
        assert "Not authenticated" in result.output


class TestStreamingDefault:
    """Tests for batch mode as the default query mode."""

    @patch("perplexity_cli.cli.StyleManager")
    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_query_default_batch_mode(self, mock_api_class, mock_tm_class, mock_sm_class, runner):
        """Test that invoking query without flags uses batch (non-streaming) path."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        mock_tm = Mock()
        mock_tm.load_token.return_value = ("test-token", None)
        mock_tm_class.return_value = mock_tm

        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = Answer(text="Batch answer", references=[])
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["What is 2+2?"])

        assert result.exit_code == 0
        assert "Batch answer" in result.output
        # Verify batch path was used (get_complete_answer), not streaming path (submit_query)
        mock_api.get_complete_answer.assert_called_once()
        mock_api.submit_query.assert_not_called()

    @patch("perplexity_cli.cli.StyleManager")
    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_query_explicit_stream_uses_streaming(
        self, mock_api_class, mock_tm_class, mock_sm_class, runner
    ):
        """Test that --stream explicitly uses the streaming path."""
        from perplexity_cli.api.models import Block, SSEMessage

        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        mock_tm = Mock()
        mock_tm.load_token.return_value = ("test-token", None)
        mock_tm_class.return_value = mock_tm

        # Build a minimal final SSE message with answer text
        mock_message = Mock(spec=SSEMessage)
        mock_message.status = "COMPLETE"
        mock_message.final_sse_message = True
        mock_message.web_results = []

        mock_block = Mock(spec=Block)
        mock_block.intended_usage = "ask_text"
        mock_block.content = {"markdown_block": {"chunks": ["Streamed answer"]}}
        mock_message.blocks = [mock_block]

        mock_api = _make_api_mock()
        mock_api.submit_query.return_value = iter([mock_message])
        mock_api._extract_text_from_block.return_value = "Streamed answer"
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["--stream", "What is 2+2?"])

        assert result.exit_code == 0
        assert "Streamed answer" in result.output
        # Verify streaming path was used (submit_query), not batch path (get_complete_answer)
        mock_api.submit_query.assert_called_once()
        mock_api.get_complete_answer.assert_not_called()

    def test_query_help_shows_stream_option(self, runner):
        """Test that --help output mentions --stream and --no-stream options."""
        result = runner.invoke(query, ["--help"])

        assert result.exit_code == 0
        assert "--stream" in result.output
        assert "--no-stream" in result.output
