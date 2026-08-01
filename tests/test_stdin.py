"""Tests for stdin reading via the '-' argument."""

from contextlib import ExitStack
from io import StringIO
from unittest.mock import Mock, patch

import pytest

from perplexity_cli._types import QueryOptions
from perplexity_cli.api.models import Answer
from perplexity_cli.query_runner import run_query_command
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    SimpleResponse,
)

_QUERY_OPTIONS = QueryOptions(
    output_format="plain",
    strip_references=False,
    stream=False,
    attachments=(),
    model_preference=None,
    request_param_overrides=(),
)


def _make_api_mock(answer: Answer | None = None):
    """Create a context-manager-compatible PerplexityAPI mock."""
    mock_api = Mock()
    mock_api.__enter__ = Mock(return_value=mock_api)
    mock_api.__exit__ = Mock(return_value=False)
    if answer is not None:
        mock_api.get_complete_answer.return_value = answer
    return mock_api


def _apply_standard_patches(stack, mock_api):
    """Apply standard patches to an ExitStack and return nothing."""
    stack.enter_context(patch("perplexity_cli.query_runner.TokenManager", return_value=Mock()))
    stack.enter_context(
        patch(
            "perplexity_cli.query_runner.load_token_optional",
            return_value=("token-123", None),
        )
    )
    stack.enter_context(
        patch("perplexity_cli.query_runner.resolve_attachment_urls", return_value=[])
    )
    stack.enter_context(patch("perplexity_cli.query_runner.PerplexityAPI", return_value=mock_api))
    stack.enter_context(
        patch("perplexity_cli.query_runner.build_final_query", side_effect=lambda q: q)
    )


class TestStdinSupport:
    """Test stdin reading via the '-' argument."""

    def test_dash_reads_stdin(self, capsys):
        """When query_text is '-', reads from stdin."""
        answer = Answer(text="Stdin answer", references=[])
        mock_api = _make_api_mock(answer)
        stdin_mock = StringIO("What is stdin?\n")
        stdin_mock.isatty = lambda: False

        with ExitStack() as stack:
            _apply_standard_patches(stack, mock_api)
            stack.enter_context(patch("perplexity_cli.query_runner.sys.stdin", stdin_mock))
            run_query_command(
                ctx_obj={"debug": False},
                query_text="-",
                options=_QUERY_OPTIONS,
            )

        mock_api.get_complete_answer.assert_called_once()
        call_args = mock_api.get_complete_answer.call_args
        assert call_args.args[0] == "What is stdin?"

    def test_dash_tty_stdin_exits_2(self, capsys):
        """When stdin is a TTY and query_text is '-', exits with code 2."""
        stdin_mock = StringIO()
        stdin_mock.isatty = lambda: True

        with (
            patch("perplexity_cli.query_runner.sys.stdin", stdin_mock),
            pytest.raises(SystemExit) as exc_info,
        ):
            run_query_command(
                ctx_obj={"debug": False},
                query_text="-",
                options=_QUERY_OPTIONS,
            )

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "stdin is a terminal" in captured.err

    def test_dash_empty_stdin_exits_2(self, capsys):
        """When stdin is empty and query_text is '-', exits with code 2."""
        stdin_mock = StringIO("   \n  ")
        stdin_mock.isatty = lambda: False

        with (
            patch("perplexity_cli.query_runner.sys.stdin", stdin_mock),
            pytest.raises(SystemExit) as exc_info,
        ):
            run_query_command(
                ctx_obj={"debug": False},
                query_text="-",
                options=_QUERY_OPTIONS,
            )

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "empty input from stdin" in captured.err

    def test_normal_query_still_works(self, capsys):
        """A normal query string is not treated as stdin."""
        answer = Answer(text="Normal answer", references=[])
        mock_api = _make_api_mock(answer)

        with ExitStack() as stack:
            _apply_standard_patches(stack, mock_api)
            run_query_command(
                ctx_obj={"debug": False},
                query_text="What is Python?",
                options=_QUERY_OPTIONS,
            )

        captured = capsys.readouterr()
        assert captured.out.strip() == "Normal answer"
        assert captured.err == ""

    def test_dash_with_piped_input(self, capsys):
        """Piped stdin content is used as the query."""
        answer = Answer(text="Piped answer", references=[])
        mock_api = _make_api_mock(answer)
        stdin_mock = StringIO("Tell me about pipes\n")
        stdin_mock.isatty = lambda: False

        with ExitStack() as stack:
            _apply_standard_patches(stack, mock_api)
            stack.enter_context(patch("perplexity_cli.query_runner.sys.stdin", stdin_mock))
            run_query_command(
                ctx_obj={"debug": False},
                query_text="-",
                options=_QUERY_OPTIONS,
            )

        captured = capsys.readouterr()
        assert captured.out.strip() == "Piped answer"
        assert captured.err == ""


class TestUnifiedQueryExitCodes:
    """Query failures route through the taxonomy in both modes."""

    def _run_with_http_500(self, capsys, *, json_mode):
        """Run a query whose gateway raises HTTP 500 and return the exit code."""
        mock_api = Mock()
        mock_api.__enter__ = Mock(return_value=mock_api)
        mock_api.__exit__ = Mock(return_value=False)
        mock_api.get_complete_answer.side_effect = PerplexityHTTPStatusError(
            "HTTP 500",
            response=SimpleResponse(status_code=500),
        )

        ctx_obj = {"debug": False}
        if json_mode:
            ctx_obj["json"] = True

        with ExitStack() as stack:
            _apply_standard_patches(stack, mock_api)
            with pytest.raises(SystemExit) as exc_info:
                run_query_command(
                    ctx_obj=ctx_obj,
                    query_text="What is Python?",
                    options=_QUERY_OPTIONS,
                )
        return exc_info.value.code

    def test_human_mode_http_500_exits_6(self, capsys):
        """HTTP 500 maps to the transient exit code (6) in human mode."""
        code = self._run_with_http_500(capsys, json_mode=False)
        assert code == 6
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Error: HTTP 500" in captured.err

    def test_json_mode_http_500_exits_6(self, capsys):
        """HTTP 500 maps to the transient exit code (6) in JSON mode."""
        code = self._run_with_http_500(capsys, json_mode=True)
        assert code == 6
        captured = capsys.readouterr()
        assert captured.err == ""
