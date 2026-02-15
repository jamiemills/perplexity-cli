"""Tests for optional authentication in query command."""

from unittest.mock import MagicMock, Mock, patch

from perplexity_cli.api.models import Answer
from perplexity_cli.auth.utils import load_token_optional
from perplexity_cli.cli import query


def _make_api_mock(**kwargs):
    """Create a Mock for PerplexityAPI that supports context manager protocol."""
    mock_api = MagicMock()
    mock_api.__enter__ = Mock(return_value=mock_api)
    mock_api.__exit__ = Mock(return_value=False)
    for key, value in kwargs.items():
        setattr(mock_api, key, value)
    return mock_api


class TestLoadTokenOptional:
    """Tests for load_token_optional() utility function."""

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_load_token_optional_no_token_exists(self, mock_tm_class):
        """Test load_token_optional returns (None, None) when no token exists."""
        from perplexity_cli.utils.logging import get_logger

        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        mock_tm_class.return_value = mock_tm

        logger = get_logger()
        token, cookies = load_token_optional(mock_tm, logger)

        assert token is None
        assert cookies is None

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_load_token_optional_token_exists(self, mock_tm_class):
        """Test load_token_optional returns token and cookies when they exist."""
        from perplexity_cli.utils.logging import get_logger

        mock_tm = Mock()
        test_token = "test-token-123"
        test_cookies = {"session": "abc123", "cf_clearance": "xyz"}
        mock_tm.load_token.return_value = (test_token, test_cookies)
        mock_tm_class.return_value = mock_tm

        logger = get_logger()
        token, cookies = load_token_optional(mock_tm, logger)

        assert token == test_token
        assert cookies == test_cookies

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_load_token_optional_no_exit_on_missing_token(self, mock_tm_class):
        """Test load_token_optional does not exit when token is missing."""
        from perplexity_cli.utils.logging import get_logger

        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        mock_tm_class.return_value = mock_tm

        logger = get_logger()
        # Should not raise SystemExit
        token, cookies = load_token_optional(mock_tm, logger)

        assert token is None
        assert cookies is None


class TestQueryWithoutAuthentication:
    """Tests for query command running without authentication."""

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI")
    def test_query_without_token(self, mock_api_class, mock_tm_class, mock_sm_class, runner):
        """Test query command succeeds without authentication token."""
        # Mock token manager - no token
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        mock_tm_class.return_value = mock_tm

        # Mock style manager - no style configured
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        # Mock API response
        mock_answer = Answer(
            text="Test answer without auth",
            references=[],
        )
        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = mock_answer
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["test question"])

        assert result.exit_code == 0
        assert "Test answer without auth" in result.output
        # Verify API was called with None token
        mock_api_class.assert_called_once()
        call_kwargs = mock_api_class.call_args[1]
        assert call_kwargs["token"] is None

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI")
    def test_query_with_token_still_works(
        self, mock_api_class, mock_tm_class, mock_sm_class, runner
    ):
        """Test query command still works with authentication token (regression test)."""
        # Mock token manager - with token
        mock_tm = Mock()
        test_token = "test-token-123"
        test_cookies = {"session": "abc123"}
        mock_tm.load_token.return_value = (test_token, test_cookies)
        mock_tm_class.return_value = mock_tm

        # Mock style manager - no style configured
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        # Mock API response
        mock_answer = Answer(
            text="Test answer with auth",
            references=[],
        )
        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = mock_answer
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["test question"])

        assert result.exit_code == 0
        assert "Test answer with auth" in result.output
        # Verify API was called with token
        mock_api_class.assert_called_once()
        call_kwargs = mock_api_class.call_args[1]
        assert call_kwargs["token"] == test_token
        assert call_kwargs["cookies"] == test_cookies

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI")
    def test_query_format_plain_without_auth(
        self, mock_api_class, mock_tm_class, mock_sm_class, runner
    ):
        """Test query with --format plain works without authentication."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        mock_tm_class.return_value = mock_tm

        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        mock_answer = Answer(text="Plain text answer", references=[])
        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = mock_answer
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["--format", "plain", "test question"])

        assert result.exit_code == 0
        assert "Plain text answer" in result.output

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI")
    def test_query_format_markdown_without_auth(
        self, mock_api_class, mock_tm_class, mock_sm_class, runner
    ):
        """Test query with --format markdown works without authentication."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        mock_tm_class.return_value = mock_tm

        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        mock_answer = Answer(text="# Markdown answer", references=[])
        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = mock_answer
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["--format", "markdown", "test question"])

        assert result.exit_code == 0
        assert "Markdown answer" in result.output

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI")
    def test_query_format_json_without_auth(
        self, mock_api_class, mock_tm_class, mock_sm_class, runner
    ):
        """Test query with --format json works without authentication."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        mock_tm_class.return_value = mock_tm

        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        mock_answer = Answer(text="JSON answer", references=[])
        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = mock_answer
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["--format", "json", "test question"])

        assert result.exit_code == 0
        assert "JSON answer" in result.output

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI")
    def test_query_strip_references_without_auth(
        self, mock_api_class, mock_tm_class, mock_sm_class, runner
    ):
        """Test query with --strip-references works without authentication."""
        from perplexity_cli.api.models import WebResult

        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        mock_tm_class.return_value = mock_tm

        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        mock_answer = Answer(
            text="Answer with [1] citations",
            references=[
                WebResult(name="Example", url="https://example.com", snippet=None, timestamp=None)
            ],
        )
        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = mock_answer
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["--strip-references", "test question"])

        assert result.exit_code == 0
        # References should be stripped
        assert "[1]" not in result.output or "References" not in result.output.split("[1]")[0]


class TestQueryAuthenticationErrors:
    """Tests for error handling when API rejects unauthenticated requests."""

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI")
    def test_query_unauthenticated_api_rejection(
        self, mock_api_class, mock_tm_class, mock_sm_class, runner
    ):
        """Test query handles 401 error gracefully when API rejects unauthenticated request."""
        from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError

        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        mock_tm_class.return_value = mock_tm

        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        # Mock API to raise 401 error (unauthenticated)
        mock_api = _make_api_mock()
        mock_response = Mock()
        mock_response.status_code = 401
        mock_api.get_complete_answer.side_effect = PerplexityHTTPStatusError(
            message="Unauthorized",
            response=mock_response,
            request=Mock(),
        )
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["test question"])

        # Should exit with error code
        assert result.exit_code == 1
        # Should show authentication error message
        assert "Unauthorized" in result.output or "ERROR" in result.output

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI")
    def test_query_rate_limit_without_auth(
        self, mock_api_class, mock_tm_class, mock_sm_class, runner
    ):
        """Test query handles 429 rate limit error without authentication."""
        from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError

        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        mock_tm_class.return_value = mock_tm

        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        # Mock API to raise 429 error (rate limit)
        mock_api = _make_api_mock()
        mock_response = Mock()
        mock_response.status_code = 429
        mock_api.get_complete_answer.side_effect = PerplexityHTTPStatusError(
            message="Rate limit exceeded",
            response=mock_response,
            request=Mock(),
        )
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["test question"])

        # Should exit with error code
        assert result.exit_code == 1
        # Should show rate limit error
        assert "Rate limit" in result.output or "429" in result.output or "ERROR" in result.output


class TestAttachmentAuthentication:
    """Tests for authentication requirements when using file attachments."""

    @patch("perplexity_cli.utils.file_handler.resolve_file_arguments")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_query_with_attach_flag_requires_auth(self, mock_tm_class, mock_resolve_files, runner):
        """Test query with --attach flag fails without authentication."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        mock_tm_class.return_value = mock_tm

        # Mock file resolution to find a file
        mock_resolve_files.return_value = ["/path/to/file.txt"]

        result = runner.invoke(query, ["--attach", "file.txt", "test question"])

        # Should exit with error code
        assert result.exit_code == 1
        # Should show authentication error
        assert "File attachments require authentication" in result.output
        assert "pxcli auth" in result.output

    @patch("perplexity_cli.utils.file_handler.resolve_file_arguments")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_query_with_inline_file_path_requires_auth(
        self, mock_tm_class, mock_resolve_files, runner
    ):
        """Test query with inline file path in query text fails without authentication."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        mock_tm_class.return_value = mock_tm

        # Mock file resolution to find a file (path detected in query)
        mock_resolve_files.return_value = ["/path/to/file.txt"]

        result = runner.invoke(query, ["Tell me about ./README.md"])

        # Should exit with error code
        assert result.exit_code == 1
        # Should show authentication error
        assert "File attachments require authentication" in result.output
        assert "pxcli auth" in result.output

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    @patch("perplexity_cli.utils.file_handler.resolve_file_arguments")
    @patch("perplexity_cli.utils.file_handler.load_attachments")
    @patch("perplexity_cli.attachments.AttachmentUploader")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI")
    def test_query_with_attach_flag_and_auth_works(
        self,
        mock_api_class,
        mock_tm_class,
        mock_uploader_class,
        mock_load_attachments,
        mock_resolve_files,
        mock_sm_class,
        runner,
    ):
        """Test query with --attach flag succeeds with authentication."""
        from perplexity_cli.api.models import FileAttachment

        mock_tm = Mock()
        test_token = "test-token-123"
        mock_tm.load_token.return_value = (test_token, None)
        mock_tm_class.return_value = mock_tm

        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        # Mock file resolution and loading
        mock_resolve_files.return_value = ["/path/to/file.txt"]
        attachment = FileAttachment(
            filename="file.txt",
            content_type="text/plain",
            data="dGVzdCBjb250ZW50",
        )
        mock_load_attachments.return_value = [attachment]

        # Mock attachment uploader
        mock_uploader = Mock()
        mock_uploader.upload_files = Mock(return_value=[{"url": "https://s3.example.com/file.txt"}])
        mock_uploader_class.return_value = mock_uploader

        # Mock API response
        mock_answer = Answer(text="Answer with attachment", references=[])
        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = mock_answer
        mock_api_class.return_value = mock_api

        # Need to mock asyncio.run
        with patch("asyncio.run", return_value=["https://s3.example.com/file.txt"]):
            result = runner.invoke(query, ["--attach", "file.txt", "test question"])

        # Should succeed
        assert result.exit_code == 0
        assert "Answer with attachment" in result.output
