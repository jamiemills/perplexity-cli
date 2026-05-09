"""Tests for CLI commands."""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from perplexity_cli.api.models import Answer
from perplexity_cli.cli import (
    auth,
    clear_style,
    configure,
    doctor_security,
    export_threads,
    logout,
    main,
    query,
    show_config,
    status,
    view_style,
)
from perplexity_cli.config.models import FeatureConfig
from perplexity_cli.utils.exceptions import AuthenticationError


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
        # Assert dynamically using the CLI's version resolver
        from perplexity_cli.utils.version import get_version

        expected_version = get_version()
        assert expected_version in result.output

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_status_not_authenticated(self, mock_tm_class, runner):
        """Test status when not authenticated."""
        mock_tm = Mock()
        mock_tm.token_exists.return_value = False
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(status)

        assert result.exit_code == 0
        assert "Not authenticated" in result.output
        assert "pxcli auth" in result.output

    @patch("perplexity_cli.utils.config.set_feature")
    def test_set_config_handles_configuration_error(self, mock_set_feature, runner):
        """Test set-config surfaces configuration errors consistently."""
        from perplexity_cli.utils.exceptions import ConfigurationError

        mock_set_feature.side_effect = ConfigurationError("bad config")

        result = runner.invoke(main, ["set-config", "save_cookies", "true"])

        assert result.exit_code == 1
        assert "Failed to update configuration: bad config" in result.output

    @patch("perplexity_cli.utils.config.get_feature_config")
    @patch("perplexity_cli.threads.cache_manager.ThreadCacheManager")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_doctor_security_reports_storage_risk(
        self, mock_tm_class, mock_cache_manager_class, mock_get_feature_config, runner
    ):
        """Test doctor security reports the current file-storage threat model."""
        from pathlib import Path

        mock_tm = Mock()
        mock_tm.token_path = Path("/tmp/token.json")
        mock_tm.SECURE_PERMISSIONS = 0o600
        mock_tm_class.return_value = mock_tm

        mock_cache_manager = Mock()
        mock_cache_manager.cache_path = Path("/tmp/threads-cache.json")
        mock_cache_manager.SECURE_PERMISSIONS = 0o600
        mock_cache_manager_class.return_value = mock_cache_manager

        mock_get_feature_config.return_value = FeatureConfig(save_cookies=True, debug_mode=False)

        result = runner.invoke(doctor_security)

        assert result.exit_code == 0
        assert "machine-bound encrypted file storage" in result.output
        assert "not against other local processes or users" in result.output
        assert "Cookie storage warning" in result.output

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI")
    def test_status_authenticated(self, mock_api_class, mock_tm_class, runner):
        """Test status shows local authentication details by default."""
        from pathlib import Path

        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.load_token.return_value = ("test-token-123", None)
        mock_tm.token_path = Path("/path/to/token.json")
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
        assert "Live verification not run" in result.output
        mock_api_class.assert_not_called()

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI")
    def test_status_authenticated_with_verify(self, mock_api_class, mock_tm_class, runner):
        """Test status --verify performs a live verification call."""
        from pathlib import Path

        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.load_token.return_value = ("test-token-123", {"csrftoken": "abc"})
        mock_tm.token_path = Path("/path/to/token.json")
        mock_tm_class.return_value = mock_tm

        mock_answer = Mock()
        mock_answer.text = "test answer"
        mock_answer.references = []
        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = mock_answer
        mock_api_class.return_value = mock_api

        result = runner.invoke(status, ["--verify"])

        assert result.exit_code == 0
        assert "Token is valid and working" in result.output
        mock_api_class.assert_called_once_with(
            token="test-token-123", cookies={"csrftoken": "abc"}, timeout=10
        )

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_logout_no_token(self, mock_tm_class, runner):
        """Test logout when no token exists."""
        mock_tm = Mock()
        mock_tm.token_exists.return_value = False
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(logout)

        assert result.exit_code == 0
        assert "No stored credentials" in result.output

    @patch("perplexity_cli.auth.token_manager.TokenManager")
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

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_logout_failure(self, mock_tm_class, runner):
        """Test logout surfaces unexpected token deletion failures."""
        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.clear_token.side_effect = OSError("permission denied")
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(logout)

        assert result.exit_code == 1
        assert "Error during logout: permission denied" in result.output

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI")
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
        mock_api.get_complete_answer.assert_called_once_with("What is Python?", attachments=[])

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI")
    def test_query_debug_logging_redacts_sensitive_values(
        self,
        mock_api_class,
        mock_tm_class,
        mock_sm_class,
        runner,
        caplog,
    ):
        """Test query debug logs do not include raw query, style, or token path."""
        import logging
        from pathlib import Path

        from perplexity_cli.utils.logging import setup_logging

        mock_sm = Mock()
        mock_sm.load_style.return_value = "private style instructions"
        mock_sm_class.return_value = mock_sm

        mock_tm = Mock()
        mock_tm.load_token.return_value = ("test-token", None)
        mock_tm_class.return_value = mock_tm

        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = Answer(text="Test answer", references=[])
        mock_api_class.return_value = mock_api

        setup_logging(debug=True)

        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            result = runner.invoke(
                main, ["--debug", "query", "--no-stream", "my bank password is 123"]
            )

        assert result.exit_code == 0
        combined = "\n".join(record.getMessage() for record in caplog.records)
        assert "my bank password is 123" not in combined
        assert "private style instructions" not in combined
        assert str(Path.home() / ".config" / "perplexity-cli" / "token.json") not in combined
        assert "<redacted:" in combined

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI")
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

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI")
    def test_query_not_authenticated(self, mock_api_class, mock_tm_class, mock_sm_class, runner):
        """Test query when not authenticated - should attempt to run without token."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        mock_tm_class.return_value = mock_tm

        # Mock style manager
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        # Mock API response
        mock_answer = Mock()
        mock_answer.text = "test answer"
        mock_answer.references = []
        mock_api = MagicMock()
        mock_api.__enter__ = Mock(return_value=mock_api)
        mock_api.__exit__ = Mock(return_value=False)
        mock_api.get_complete_answer.return_value = mock_answer
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["test query"])

        # Should succeed - query no longer requires authentication
        assert result.exit_code == 0
        assert "test answer" in result.output
        # Verify API was called with None token
        mock_api_class.assert_called_once()
        call_kwargs = mock_api_class.call_args[1]
        assert call_kwargs["token"] is None

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI")
    def test_query_network_error(self, mock_api_class, mock_tm_class, mock_sm_class, runner):
        """Test query with network error."""
        from perplexity_cli.utils.exceptions import PerplexityRequestError

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
        mock_api.get_complete_answer.side_effect = PerplexityRequestError("Connection failed")
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["--no-stream", "test"])

        assert result.exit_code == 1
        assert "Network error" in result.output

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.auth.oauth_handler.authenticate_sync")
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

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.auth.oauth_handler.authenticate_sync")
    def test_auth_failure(self, mock_auth, mock_tm_class, runner):
        """Test authentication failure."""
        # Mock authentication failure
        mock_auth.side_effect = AuthenticationError("Chrome not found")

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

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    def test_configure_style(self, mock_sm_class, runner):
        """Test configure command saves style."""
        mock_sm = Mock()
        mock_sm_class.return_value = mock_sm

        result = runner.invoke(configure, ["be brief and concise"])
        assert result.exit_code == 0
        assert "Style configured successfully" in result.output
        mock_sm.save_style.assert_called_once_with("be brief and concise")

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    def test_configure_style_error(self, mock_sm_class, runner):
        """Test configure command handles save errors."""
        mock_sm = Mock()
        mock_sm.save_style.side_effect = ValueError("Invalid style")
        mock_sm_class.return_value = mock_sm

        result = runner.invoke(configure, [""])
        assert result.exit_code == 1
        assert "Invalid style" in result.output

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    def test_view_style_when_set(self, mock_sm_class, runner):
        """Test view-style shows configured style."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = "be brief"
        mock_sm_class.return_value = mock_sm

        result = runner.invoke(view_style)
        assert result.exit_code == 0
        assert "Current style:" in result.output
        assert "be brief" in result.output

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    def test_view_style_when_not_set(self, mock_sm_class, runner):
        """Test view-style when no style configured."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        result = runner.invoke(view_style)
        assert result.exit_code == 0
        assert "No style configured" in result.output

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    def test_clear_style_when_set(self, mock_sm_class, runner):
        """Test clear-style removes style."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = "old style"
        mock_sm_class.return_value = mock_sm

        result = runner.invoke(clear_style)
        assert result.exit_code == 0
        assert "Style cleared successfully" in result.output
        mock_sm.clear_style.assert_called_once()

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    def test_clear_style_when_not_set(self, mock_sm_class, runner):
        """Test clear-style when no style configured."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        result = runner.invoke(clear_style)
        assert result.exit_code == 0
        assert "No style is currently configured" in result.output

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
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

    @patch("perplexity_cli.auth.token_manager.TokenManager")
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

    @patch("perplexity_cli.auth.token_manager.TokenManager")
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

    @patch("perplexity_cli.threads.scraper.ThreadScraper")
    @patch("perplexity_cli.threads.cache_manager.ThreadCacheManager")
    @patch("perplexity_cli.utils.config.get_rate_limiting_config")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_export_threads_passes_cookies_to_scraper(
        self,
        mock_tm_class,
        mock_get_rl_config,
        mock_cache_manager_class,
        mock_scraper_class,
        runner,
    ):
        """Test export_threads forwards stored cookies into ThreadScraper."""
        from perplexity_cli.config.models import RateLimitConfig

        mock_tm = Mock()
        mock_tm.load_token.return_value = ("token-123", {"cf_clearance": "cookie-1"})
        mock_tm_class.return_value = mock_tm

        mock_get_rl_config.return_value = RateLimitConfig(
            enabled=False, requests_per_period=20, period_seconds=60.0
        )

        mock_cache_manager = Mock()
        mock_cache_manager.cache_exists.return_value = False
        mock_cache_manager_class.return_value = mock_cache_manager

        mock_scraper = Mock()
        mock_scraper.scrape_all_threads = AsyncMock(return_value=[])
        mock_scraper_class.return_value = mock_scraper

        result = runner.invoke(export_threads)

        assert result.exit_code == 1
        assert "No threads found matching criteria" in result.output
        mock_scraper_class.assert_called_once_with(
            token="token-123",
            cookies={"cf_clearance": "cookie-1"},
            rate_limiter=None,
            cache_manager=mock_cache_manager,
            force_refresh=False,
        )


class TestStreamingDefault:
    """Tests for batch mode as the default query mode."""

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI")
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

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI")
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
        mock_message.extract_answer_text.return_value = "Streamed answer"

        mock_block = Mock(spec=Block)
        mock_block.intended_usage = "ask_text"
        mock_block.content = {"markdown_block": {"chunks": ["Streamed answer"]}}
        mock_message.blocks = [mock_block]

        mock_api = _make_api_mock()
        mock_api.submit_query.return_value = iter([mock_message])
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
