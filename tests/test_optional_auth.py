"""Tests for optional authentication in query command."""

import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

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

    @patch("perplexity_cli.query_runner.TokenManager")
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
        mock_tm.load_token.assert_called_once_with()

    @patch("perplexity_cli.query_runner.TokenManager")
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
        mock_tm.load_token.assert_called_once_with()

    @patch("perplexity_cli.query_runner.TokenManager")
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
        mock_tm.load_token.assert_called_once_with()


class TestQueryWithoutAuthentication:
    """Tests for query command running without authentication."""

    @patch("perplexity_cli.query_runner.StyleManager")
    @patch("perplexity_cli.query_runner.TokenManager")
    @patch("perplexity_cli.query_runner.PerplexityAPI")
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
        assert result.exception is None
        assert result.stdout.strip() == "Test answer without auth"
        assert "[ERROR]" not in result.stdout
        # Verify API was called with None token and None cookies
        mock_api_class.assert_called_once()
        call_args = mock_api_class.call_args
        assert call_args[0][0] is None  # token is first positional arg
        assert call_args[0][1] is None  # cookies is second positional arg
        mock_api.get_complete_answer.assert_called_once()

    @patch("perplexity_cli.query_runner.StyleManager")
    @patch("perplexity_cli.query_runner.TokenManager")
    @patch("perplexity_cli.query_runner.PerplexityAPI")
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
        assert result.exception is None
        assert result.stdout.strip() == "Test answer with auth"
        assert "[ERROR]" not in result.stdout
        # Verify API was called with token
        mock_api_class.assert_called_once()
        call_args = mock_api_class.call_args
        assert call_args[0][0] == test_token  # token is first positional arg
        assert call_args[0][1] == test_cookies  # cookies is second positional arg
        mock_api.get_complete_answer.assert_called_once()

    @patch("perplexity_cli.query_runner.StyleManager")
    @patch("perplexity_cli.query_runner.TokenManager")
    @patch("perplexity_cli.query_runner.PerplexityAPI")
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
        assert result.exception is None
        assert result.stdout.strip() == "Plain text answer"
        assert "[ERROR]" not in result.stdout
        # Plain format must not emit JSON structure
        assert "{" not in result.stdout

    @patch("perplexity_cli.query_runner.StyleManager")
    @patch("perplexity_cli.query_runner.TokenManager")
    @patch("perplexity_cli.query_runner.PerplexityAPI")
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
        assert result.exception is None
        assert result.stdout.strip() == "# Markdown answer"
        assert "[ERROR]" not in result.stdout

    @patch("perplexity_cli.query_runner.StyleManager")
    @patch("perplexity_cli.query_runner.TokenManager")
    @patch("perplexity_cli.query_runner.PerplexityAPI")
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
        assert result.exception is None
        assert "[ERROR]" not in result.stdout
        # Exact JSON envelope contract: keys, command, result body, and meta.
        envelope = json.loads(result.stdout)
        assert set(envelope) == {"ok", "command", "result", "meta", "next_actions"}
        assert envelope["ok"] is True
        assert envelope["command"] == "pxcli query"
        assert envelope["result"] == {"answer": "JSON answer", "references": []}
        assert envelope["meta"] is None
        assert envelope["next_actions"] == []

    @patch("perplexity_cli.query_runner.StyleManager")
    @patch("perplexity_cli.query_runner.TokenManager")
    @patch("perplexity_cli.query_runner.PerplexityAPI")
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
        assert result.exception is None
        # Citation markers are stripped from the answer body...
        assert "[1]" not in result.stdout
        # ...and the references section is omitted entirely.
        assert "References" not in result.stdout
        # The answer body itself must still be rendered.
        assert "Answer with" in result.stdout


class TestQueryAuthenticationErrors:
    """Tests for error handling when API rejects unauthenticated requests."""

    @patch("perplexity_cli.query_runner.StyleManager")
    @patch("perplexity_cli.query_runner.TokenManager")
    @patch("perplexity_cli.query_runner.PerplexityAPI")
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
        assert isinstance(result.exception, SystemExit)
        assert result.exception.code == 1
        # Exact 401 contract messages go to stderr, never stdout.
        assert "[ERROR] Authentication failed. Token may be expired." in result.stderr
        assert "Re-authenticate with: perplexity-cli auth" in result.stderr
        assert "[ERROR]" not in result.stdout
        assert result.stdout == ""

    @patch("perplexity_cli.query_runner.StyleManager")
    @patch("perplexity_cli.query_runner.TokenManager")
    @patch("perplexity_cli.query_runner.PerplexityAPI")
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
        assert isinstance(result.exception, SystemExit)
        assert result.exception.code == 1
        # Exact 429 contract message goes to stderr, never stdout.
        assert "[ERROR] Rate limit exceeded. Please wait and try again." in result.stderr
        assert "[ERROR]" not in result.stdout
        assert result.stdout == ""


class TestAttachmentAuthentication:
    """Tests for authentication requirements when using file attachments."""

    @patch("perplexity_cli.query_runner.resolve_file_arguments")
    @patch("perplexity_cli.query_runner.TokenManager")
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
        assert isinstance(result.exception, SystemExit)
        assert result.exception.code == 1
        # Exact auth-required contract messages go to stderr, never stdout.
        assert "[ERROR] File attachments require authentication." in result.stderr
        assert "Please authenticate first with: pxcli auth login" in result.stderr
        assert "[ERROR]" not in result.stdout
        assert result.stdout == ""
        # File resolution was attempted before the auth gate tripped.
        mock_resolve_files.assert_called_once()

    @patch("perplexity_cli.query_runner.resolve_file_arguments")
    @patch("perplexity_cli.query_runner.TokenManager")
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
        assert isinstance(result.exception, SystemExit)
        assert result.exception.code == 1
        # Exact auth-required contract messages go to stderr, never stdout.
        assert "[ERROR] File attachments require authentication." in result.stderr
        assert "Please authenticate first with: pxcli auth login" in result.stderr
        assert "[ERROR]" not in result.stdout
        assert result.stdout == ""
        # The inline file path was resolved from the query text before the auth gate.
        mock_resolve_files.assert_called_once()

    @patch("perplexity_cli.query_runner.StyleManager")
    @patch("perplexity_cli.query_runner.run_async")
    @patch("perplexity_cli.query_runner.resolve_file_arguments")
    @patch("perplexity_cli.query_runner.load_attachments")
    @patch("perplexity_cli.attachments.AttachmentUploader")
    @patch("perplexity_cli.query_runner.TokenManager")
    @patch("perplexity_cli.query_runner.PerplexityAPI")
    def test_query_with_attach_flag_and_auth_works(
        self,
        mock_api_class,
        mock_tm_class,
        mock_uploader_class,
        mock_load_attachments,
        mock_resolve_files,
        mock_run_async,
        mock_sm_class,
        runner,
    ):
        """Test query with --attach flag succeeds with authentication."""
        from perplexity_cli.utils.attachment_models import FileAttachment

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
        mock_uploader.upload_files = AsyncMock(return_value=["https://s3.example.com/file.txt"])
        mock_uploader_class.return_value = mock_uploader

        def close_upload_coroutine(coro):
            coro.close()
            return ["https://s3.example.com/file.txt"]

        mock_run_async.side_effect = close_upload_coroutine

        # Mock API response
        mock_answer = Answer(text="Answer with attachment", references=[])
        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = mock_answer
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["--attach", "file.txt", "test question"])

        # Should succeed
        assert result.exit_code == 0
        assert result.exception is None
        assert result.stdout.strip() == "Answer with attachment"
        assert "[ERROR]" not in result.stdout
        # The uploaded attachment URL is forwarded to the query API.
        mock_api.get_complete_answer.assert_called_once()
        api_call = mock_api.get_complete_answer.call_args
        assert api_call[0][0] == "test question"
        assert api_call[1]["extra_params"][0] == ["https://s3.example.com/file.txt"]
        # upload_files coroutine is created and handed to run_async (mocked here).
        mock_uploader.upload_files.assert_called_once()
        mock_run_async.assert_called_once()
