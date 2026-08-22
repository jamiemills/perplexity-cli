"""Tests for optional authentication in query command."""

import json
from unittest.mock import AsyncMock, MagicMock, Mock

from perplexity_cli.api.models import Answer
from perplexity_cli.auth.utils import load_token_optional
from perplexity_cli.cli import query
from tests.helpers.query_deps import patch_query_deps


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

    def test_load_token_optional_no_token_exists(self):
        """Test load_token_optional returns (None, None) when no token exists."""
        from perplexity_cli.utils.logging import get_logger

        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)

        logger = get_logger()
        token, cookies = load_token_optional(mock_tm, logger)

        assert token is None
        assert cookies is None
        mock_tm.load_token.assert_called_once_with()

    def test_load_token_optional_token_exists(self):
        """Test load_token_optional returns token and cookies when they exist."""
        from perplexity_cli.utils.logging import get_logger

        mock_tm = Mock()
        test_token = "test-token-123"
        test_cookies = {"session": "abc123", "cf_clearance": "xyz"}
        mock_tm.load_token.return_value = (test_token, test_cookies)

        logger = get_logger()
        token, cookies = load_token_optional(mock_tm, logger)

        assert token == test_token
        assert cookies == test_cookies
        mock_tm.load_token.assert_called_once_with()

    def test_load_token_optional_no_exit_on_missing_token(self):
        """Test load_token_optional does not exit when token is missing."""
        from perplexity_cli.utils.logging import get_logger

        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)

        logger = get_logger()
        # Should not raise SystemExit
        token, cookies = load_token_optional(mock_tm, logger)

        assert token is None
        assert cookies is None
        mock_tm.load_token.assert_called_once_with()


class TestQueryWithoutAuthentication:
    """Tests for query command running without authentication."""

    def test_query_without_token(self, monkeypatch, runner):
        mock_api_class = Mock()
        mock_tm_class = Mock()
        mock_sm_class = Mock()
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        patch_query_deps(
            monkeypatch,
            PerplexityAPI=mock_api_class,
            TokenManager=mock_tm_class,
            StyleManager=mock_sm_class,
            load_token_optional=lambda _tm, _logger: mock_tm.load_token(),
        )
        """Test query command succeeds without authentication token."""
        # Mock token manager - no token
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)

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

    def test_query_with_token_still_works(self, monkeypatch, runner):
        mock_api_class = Mock()
        mock_tm_class = Mock()
        mock_sm_class = Mock()
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        patch_query_deps(
            monkeypatch,
            PerplexityAPI=mock_api_class,
            TokenManager=mock_tm_class,
            StyleManager=mock_sm_class,
            load_token_optional=lambda _tm, _logger: mock_tm.load_token(),
        )
        """Test query command still works with authentication token (regression test)."""
        # Mock token manager - with token
        mock_tm = Mock()
        test_token = "test-token-123"
        test_cookies = {"session": "abc123"}
        mock_tm.load_token.return_value = (test_token, test_cookies)

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

    def test_query_format_plain_without_auth(self, monkeypatch, runner):
        mock_api_class = Mock()
        mock_tm_class = Mock()
        mock_sm_class = Mock()
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        patch_query_deps(
            monkeypatch,
            PerplexityAPI=mock_api_class,
            TokenManager=mock_tm_class,
            StyleManager=mock_sm_class,
            load_token_optional=lambda _tm, _logger: mock_tm.load_token(),
        )
        """Test query with --format plain works without authentication."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)

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

    def test_query_format_markdown_without_auth(self, monkeypatch, runner):
        mock_api_class = Mock()
        mock_tm_class = Mock()
        mock_sm_class = Mock()
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        patch_query_deps(
            monkeypatch,
            PerplexityAPI=mock_api_class,
            TokenManager=mock_tm_class,
            StyleManager=mock_sm_class,
            load_token_optional=lambda _tm, _logger: mock_tm.load_token(),
        )
        """Test query with --format markdown works without authentication."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)

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

    def test_query_format_json_without_auth(self, monkeypatch, runner):
        mock_api_class = Mock()
        mock_tm_class = Mock()
        mock_sm_class = Mock()
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        patch_query_deps(
            monkeypatch,
            PerplexityAPI=mock_api_class,
            TokenManager=mock_tm_class,
            StyleManager=mock_sm_class,
            load_token_optional=lambda _tm, _logger: mock_tm.load_token(),
        )
        """Test query with --format json works without authentication."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)

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

    def test_query_strip_references_without_auth(self, monkeypatch, runner):
        mock_api_class = Mock()
        mock_tm_class = Mock()
        mock_sm_class = Mock()
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        patch_query_deps(
            monkeypatch,
            PerplexityAPI=mock_api_class,
            TokenManager=mock_tm_class,
            StyleManager=mock_sm_class,
            load_token_optional=lambda _tm, _logger: mock_tm.load_token(),
        )
        """Test query with --strip-references works without authentication."""
        from perplexity_cli.api.models import WebResult

        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)

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

    def test_query_unauthenticated_api_rejection(self, monkeypatch, runner):
        mock_api_class = Mock()
        mock_tm_class = Mock()
        mock_sm_class = Mock()
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        patch_query_deps(
            monkeypatch,
            PerplexityAPI=mock_api_class,
            TokenManager=mock_tm_class,
            StyleManager=mock_sm_class,
            load_token_optional=lambda _tm, _logger: mock_tm.load_token(),
        )
        """Test query handles 401 error gracefully when API rejects unauthenticated request."""
        from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError

        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)

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

        # Should exit with error code 4 (authentication required)
        assert result.exit_code == 4
        assert isinstance(result.exception, SystemExit)
        assert result.exception.code == 4
        # The unified handler reports the HTTP error to stderr, never stdout.
        assert "Error: Unauthorized" in result.stderr
        assert "[ERROR]" not in result.stdout
        assert result.stdout == ""

    def test_query_rate_limit_without_auth(self, monkeypatch, runner):
        mock_api_class = Mock()
        mock_tm_class = Mock()
        mock_sm_class = Mock()
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        patch_query_deps(
            monkeypatch,
            PerplexityAPI=mock_api_class,
            TokenManager=mock_tm_class,
            StyleManager=mock_sm_class,
            load_token_optional=lambda _tm, _logger: mock_tm.load_token(),
        )
        """Test query handles 429 rate limit error without authentication."""
        from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError

        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)

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

        # Should exit with error code 6 (transient error)
        assert result.exit_code == 6
        assert isinstance(result.exception, SystemExit)
        assert result.exception.code == 6
        # The unified handler reports the HTTP error to stderr, never stdout.
        assert "Error: Rate limit exceeded" in result.stderr
        assert "[ERROR]" not in result.stdout
        assert result.stdout == ""


class TestAttachmentAuthentication:
    """Tests for authentication requirements when using file attachments."""

    def test_query_with_attach_flag_requires_auth(self, monkeypatch, runner):
        """Test query with --attach flag fails without authentication."""
        mock_resolve_files = Mock(return_value=["/path/to/file.txt"])
        patch_query_deps(
            monkeypatch,
            TokenManager=Mock(),
            load_token_optional=lambda _tm, _logger: (None, None),
            resolve_file_arguments=mock_resolve_files,
        )

        result = runner.invoke(query, ["--attach", "file.txt", "test question"])

        # Should exit with error code 4 (authentication required)
        assert result.exit_code == 4
        assert isinstance(result.exception, SystemExit)
        assert result.exception.code == 4
        # Exact auth-required contract messages go to stderr, never stdout.
        assert "Error: File attachments require authentication." in result.stderr
        assert "Fix: Run `pxcli auth login` to authenticate." in result.stderr
        assert "[ERROR]" not in result.stdout
        assert result.stdout == ""
        # File resolution was attempted before the auth gate tripped.
        mock_resolve_files.assert_called_once()

    def test_query_with_inline_file_path_requires_auth(self, monkeypatch, runner):
        """Test query with inline file path in query text fails without authentication."""
        mock_resolve_files = Mock(return_value=["/path/to/file.txt"])
        patch_query_deps(
            monkeypatch,
            TokenManager=Mock(),
            load_token_optional=lambda _tm, _logger: (None, None),
            resolve_file_arguments=mock_resolve_files,
        )

        result = runner.invoke(query, ["Tell me about ./README.md"])

        # Should exit with error code 4 (authentication required)
        assert result.exit_code == 4
        assert isinstance(result.exception, SystemExit)
        assert result.exception.code == 4
        # Exact auth-required contract messages go to stderr, never stdout.
        assert "Error: File attachments require authentication." in result.stderr
        assert "Fix: Run `pxcli auth login` to authenticate." in result.stderr
        assert "[ERROR]" not in result.stdout
        assert result.stdout == ""
        # The inline file path was resolved from the query text before the auth gate.
        mock_resolve_files.assert_called_once()

    def test_query_with_attach_flag_and_auth_works(self, monkeypatch, runner):
        """Test query with --attach flag succeeds with authentication."""
        from unittest.mock import MagicMock

        from perplexity_cli.utils.attachment_models import FileAttachment

        mock_api_class = MagicMock()
        mock_tm_class = Mock()
        mock_sm_class = Mock()
        mock_uploader_class = MagicMock()
        mock_load_attachments = Mock()
        mock_run_async = Mock()

        mock_tm = Mock()
        test_token = "test-token-123"
        mock_tm.load_token.return_value = (test_token, None)
        mock_tm_class.return_value = mock_tm

        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        mock_resolve_files = Mock(return_value=["/path/to/file.txt"])
        patch_query_deps(
            monkeypatch,
            PerplexityAPI=mock_api_class,
            TokenManager=mock_tm_class,
            StyleManager=mock_sm_class,
            AttachmentUploader=mock_uploader_class,
            run_async=mock_run_async,
            load_attachments=mock_load_attachments,
            resolve_file_arguments=mock_resolve_files,
        )

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
