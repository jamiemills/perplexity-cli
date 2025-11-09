"""Tests for CLI commands."""

from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from perplexity_cli.api.models import Answer
from perplexity_cli.cli import auth, logout, main, query, status


class TestCLICommands:
    """Test CLI command functionality."""

    @pytest.fixture
    def runner(self):
        """Create CLI test runner."""
        return CliRunner()

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
        assert "0.1.0" in result.output

    @patch("perplexity_cli.cli.TokenManager")
    def test_status_not_authenticated(self, mock_tm_class, runner):
        """Test status when not authenticated."""
        mock_tm = Mock()
        mock_tm.token_exists.return_value = False
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(status)

        assert result.exit_code == 0
        assert "Not authenticated" in result.output
        assert "perplexity-cli auth" in result.output

    @patch("perplexity_cli.cli.TokenManager")
    def test_status_authenticated(self, mock_tm_class, runner):
        """Test status when authenticated."""
        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.load_token.return_value = "test-token-123"
        mock_tm.token_path = "/path/to/token.json"
        mock_tm_class.return_value = mock_tm

        # Mock the API verification
        with patch("perplexity_cli.cli.httpx.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "username": "testuser",
                "email": "test@example.com",
            }
            mock_get.return_value = mock_response

            result = runner.invoke(status)

        assert result.exit_code == 0
        assert "Authenticated" in result.output
        assert "testuser" in result.output
        assert "test@example.com" in result.output

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

    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_query_success(self, mock_api_class, mock_tm_class, runner):
        """Test successful query."""
        # Mock token manager
        mock_tm = Mock()
        mock_tm.load_token.return_value = "test-token"
        mock_tm_class.return_value = mock_tm

        # Mock API
        mock_api = Mock()
        mock_api.get_complete_answer.return_value = Answer(text="Test answer", references=[])
        mock_api._format_references.return_value = ""
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["What is Python?"])

        assert result.exit_code == 0
        assert "Test answer" in result.output
        mock_api.get_complete_answer.assert_called_once_with("What is Python?")

    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_query_success_with_references(self, mock_api_class, mock_tm_class, runner):
        """Test successful query with references."""
        from perplexity_cli.api.models import WebResult

        # Mock token manager
        mock_tm = Mock()
        mock_tm.load_token.return_value = "test-token"
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

        # Mock API
        mock_api = Mock()
        mock_api.get_complete_answer.return_value = Answer(text="Test answer", references=refs)
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["What is Python?"])

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
        mock_tm.load_token.return_value = None
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(query, ["test query"])

        assert result.exit_code == 1
        assert "Not authenticated" in result.output
        assert "perplexity-cli auth" in result.output

    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_query_network_error(self, mock_api_class, mock_tm_class, runner):
        """Test query with network error."""
        import httpx

        # Mock token manager
        mock_tm = Mock()
        mock_tm.load_token.return_value = "test-token"
        mock_tm_class.return_value = mock_tm

        # Mock API to raise network error
        mock_api = Mock()
        mock_api.get_complete_answer.side_effect = httpx.RequestError("Connection failed")
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["test"])

        assert result.exit_code == 1
        assert "Network error" in result.output

    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.authenticate_sync")
    def test_auth_success(self, mock_auth, mock_tm_class, runner):
        """Test successful authentication."""
        # Mock authentication
        mock_auth.return_value = "new-token-123"

        # Mock token manager
        mock_tm = Mock()
        mock_tm.token_path = "/path/to/token.json"
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(auth)

        assert result.exit_code == 0
        assert "Authentication successful" in result.output
        mock_tm.save_token.assert_called_once_with("new-token-123")

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

    @pytest.fixture
    def runner(self):
        """Create CLI test runner."""
        return CliRunner()

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
