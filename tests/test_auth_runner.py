"""Tests for auth command routing."""

from unittest.mock import Mock, patch

from perplexity_cli.cli import auth_login, auth_logout, auth_status


class TestAuthLogin:
    """Test auth login command routing."""

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.auth.oauth_handler.authenticate_sync")
    def test_auth_login_invokes_run_auth_command(self, mock_auth, mock_tm_class, runner):
        mock_cookies = {"__cf_bm": "test"}
        mock_auth.return_value = ("token-abc", mock_cookies)
        mock_tm = Mock()
        mock_tm.token_path = "/path/to/token.json"
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(auth_login)

        assert result.exit_code == 0
        assert "Authentication successful" in result.output

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.auth.oauth_handler.authenticate_sync")
    def test_auth_login_custom_port(self, mock_auth, mock_tm_class, runner):
        mock_auth.return_value = ("token-abc", {})
        mock_tm = Mock()
        mock_tm.token_path = "/path/to/token.json"
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(auth_login, ["--port", "9223"])

        assert result.exit_code == 0
        mock_auth.assert_called_once_with(port=9223)

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.auth.oauth_handler.authenticate_sync")
    def test_auth_login_default_port(self, mock_auth, mock_tm_class, runner):
        from perplexity_cli.config.defaults import DEFAULT_CHROME_DEBUG_PORT

        mock_auth.return_value = ("token-abc", {})
        mock_tm = Mock()
        mock_tm.token_path = "/path/to/token.json"
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(auth_login)

        assert result.exit_code == 0
        mock_auth.assert_called_once_with(port=DEFAULT_CHROME_DEBUG_PORT)


class TestAuthLogout:
    """Test auth logout command routing."""

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_auth_logout_invokes_run_logout_command(self, mock_tm_class, runner):
        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.clear_token.return_value = None
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(auth_logout)

        assert result.exit_code == 0
        assert "Logged out successfully" in result.output
        mock_tm.clear_token.assert_called_once()


class TestAuthStatus:
    """Test auth status command routing."""

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_auth_status_invokes_run_status_command(self, mock_tm_class, runner):
        mock_tm = Mock()
        mock_tm.token_exists.return_value = False
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(auth_status)

        assert result.exit_code == 0
        assert "Not authenticated" in result.output

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI")
    def test_auth_status_verify(self, mock_api_class, mock_tm_class, runner):
        from pathlib import Path
        from unittest.mock import MagicMock

        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.load_token.return_value = ("test-token", {"csrftoken": "abc"})
        mock_tm.token_path = Path("/path/to/token.json")
        mock_tm_class.return_value = mock_tm

        mock_api = MagicMock()
        mock_api.__enter__ = Mock(return_value=mock_api)
        mock_api.__exit__ = Mock(return_value=False)
        mock_answer = Mock()
        mock_answer.text = "test"
        mock_answer.references = []
        mock_api.get_complete_answer.return_value = mock_answer
        mock_api_class.return_value = mock_api

        result = runner.invoke(auth_status, ["--verify"])

        assert result.exit_code == 0
        assert "Token is valid and working" in result.output
