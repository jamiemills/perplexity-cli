"""Direct tests for query runner orchestration helpers."""

from unittest.mock import Mock, patch

import pytest

from perplexity_cli.api.models import Answer
from perplexity_cli.query_runner import build_final_query, get_query_formatter, run_query_command
from perplexity_cli.utils.exceptions import UpstreamSchemaError


def _make_api_mock(answer: Answer | None = None):
    """Create a context-manager-compatible PerplexityAPI mock."""
    mock_api = Mock()
    mock_api.__enter__ = Mock(return_value=mock_api)
    mock_api.__exit__ = Mock(return_value=False)
    if answer is not None:
        mock_api.get_complete_answer.return_value = answer
    return mock_api


def test_build_final_query_appends_style():
    """Configured style text is appended to the outgoing query."""
    with patch("perplexity_cli.utils.style_manager.StyleManager") as mock_sm_class:
        mock_sm_class.return_value.load_style.return_value = "be concise"

        result = build_final_query("What is Python?")

    assert result == "What is Python?\n\nbe concise"


def test_get_query_formatter_defaults_to_rich():
    """Formatter lookup defaults to the rich formatter."""
    resolved, formatter = get_query_formatter(None)

    assert resolved == "rich"
    assert formatter is not None


def test_get_query_formatter_invalid_format_exits(capsys):
    """Invalid formatter names produce a clean user-facing failure."""
    with pytest.raises(SystemExit) as exc_info:
        get_query_formatter("invalid-format")

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "Available formats:" in captured.err


def test_run_query_command_non_streaming_renders_answer(capsys):
    """Query runner executes batch mode and renders the formatted answer."""
    answer = Answer(text="Test answer", references=[])
    mock_api = _make_api_mock(answer)

    with (
        patch("perplexity_cli.auth.token_manager.TokenManager", return_value=Mock()),
        patch("perplexity_cli.auth.utils.load_token_optional", return_value=("token-123", None)),
        patch("perplexity_cli.query_runner.resolve_attachment_urls", return_value=[]),
        patch("perplexity_cli.api.endpoints.PerplexityAPI", return_value=mock_api),
        patch("perplexity_cli.query_runner.build_final_query", return_value="final query"),
    ):
        run_query_command(
            ctx_obj={"debug": False},
            query_text="What is Python?",
            output_format="plain",
            strip_references=False,
            stream=False,
            attachments_str=(),
        )

    captured = capsys.readouterr()
    assert "Test answer" in captured.out
    mock_api.get_complete_answer.assert_called_once_with("final query", attachments=[])


def test_run_query_command_streaming_delegates_to_stream_handler():
    """Streaming mode delegates to the streaming helper with resolved inputs."""
    mock_api = _make_api_mock()

    with (
        patch("perplexity_cli.auth.token_manager.TokenManager", return_value=Mock()),
        patch("perplexity_cli.auth.utils.load_token_optional", return_value=("token-123", None)),
        patch(
            "perplexity_cli.query_runner.resolve_attachment_urls", return_value=["https://s3/file"]
        ),
        patch("perplexity_cli.api.endpoints.PerplexityAPI", return_value=mock_api),
        patch("perplexity_cli.query_runner.build_final_query", return_value="final query"),
        patch("perplexity_cli.api.streaming.stream_query_response") as mock_stream,
    ):
        run_query_command(
            ctx_obj={"debug": False},
            query_text="What is Python?",
            output_format="plain",
            strip_references=True,
            stream=True,
            attachments_str=(),
        )

    mock_stream.assert_called_once()
    assert mock_stream.call_args.args[0] is mock_api
    assert mock_stream.call_args.args[1] == "final query"
    assert mock_stream.call_args.args[3] == "plain"
    assert mock_stream.call_args.args[4] is True
    assert mock_stream.call_args.kwargs["attachments"] == ["https://s3/file"]


def test_run_query_command_reports_upstream_schema_error(capsys):
    """Upstream schema failures map to a clean exit and message."""
    mock_api = _make_api_mock()
    mock_api.get_complete_answer.side_effect = UpstreamSchemaError("bad payload")

    with (
        patch("perplexity_cli.auth.token_manager.TokenManager", return_value=Mock()),
        patch("perplexity_cli.auth.utils.load_token_optional", return_value=("token-123", None)),
        patch("perplexity_cli.query_runner.resolve_attachment_urls", return_value=[]),
        patch("perplexity_cli.api.endpoints.PerplexityAPI", return_value=mock_api),
        patch("perplexity_cli.query_runner.build_final_query", return_value="final query"),
    ):
        with pytest.raises(SystemExit) as exc_info:
            run_query_command(
                ctx_obj={"debug": False},
                query_text="What is Python?",
                output_format="plain",
                strip_references=False,
                stream=False,
                attachments_str=(),
            )

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "Upstream response format changed: bad payload" in captured.err
