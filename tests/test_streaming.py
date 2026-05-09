"""Direct tests for streaming query orchestration."""

from unittest.mock import Mock, patch

import pytest
from click import ClickException

from perplexity_cli.api.models import WebResult
from perplexity_cli.api.streaming import stream_query_response


def _make_message(
    text: str, *, final: bool = True, references: list[WebResult] | None = None
) -> Mock:
    """Create a simple streaming message mock."""
    message = Mock()
    message.status = "COMPLETE"
    message.final_sse_message = final
    message.web_results = references or []
    message.extract_answer_text.return_value = text
    return message


def test_stream_query_response_outputs_incremental_text(capsys):
    """Streaming helper prints only new text chunks."""
    api = Mock()
    api.submit_query.return_value = iter(
        [
            _make_message("Hello"),
            _make_message("Hello world"),
        ]
    )
    formatter = Mock()

    stream_query_response(
        api, "test query", formatter, output_format="plain", strip_references=True
    )

    captured = capsys.readouterr()
    assert "Hello world" in captured.out
    formatter.format_references.assert_not_called()


def test_stream_query_response_renders_plain_references(capsys):
    """Plain streaming renders references after the final answer text."""
    api = Mock()
    api.submit_query.return_value = iter(
        [
            _make_message(
                "Answer text",
                references=[WebResult(name="Ref", url="https://example.com", snippet="Example")],
            )
        ]
    )
    formatter = Mock()
    formatter.format_references.return_value = "[1] https://example.com"

    stream_query_response(
        api, "test query", formatter, output_format="plain", strip_references=False
    )

    captured = capsys.readouterr()
    assert "Answer text" in captured.out
    assert "https://example.com" in captured.out
    formatter.format_references.assert_called_once()


def test_stream_query_response_renders_rich_references_via_formatter():
    """Rich streaming reuses render_complete for references after text output."""
    api = Mock()
    refs = [WebResult(name="Ref", url="https://example.com", snippet="Example")]
    api.submit_query.return_value = iter([_make_message("Answer text", references=refs)])
    formatter = Mock()

    stream_query_response(
        api, "test query", formatter, output_format="rich", strip_references=False
    )

    formatter.render_complete.assert_called_once()
    answer_arg = formatter.render_complete.call_args.args[0]
    assert answer_arg.text == "Answer text"
    assert answer_arg.references == refs
    assert formatter.render_complete.call_args.kwargs["strip_references"] is True


def test_stream_query_response_surfaces_output_failure():
    """Local render failures produce the dedicated streaming output error."""
    api = Mock()
    api.submit_query.return_value = iter(
        [
            _make_message(
                "Answer text",
                references=[WebResult(name="Ref", url="https://example.com", snippet="Example")],
            )
        ]
    )
    formatter = Mock()
    formatter.format_references.side_effect = OSError("stdout closed")

    with patch("perplexity_cli.api.streaming.click.echo") as mock_echo:
        mock_echo.side_effect = [None, None, None, None, None]

        with pytest.raises(SystemExit) as exc_info:
            stream_query_response(
                api, "test query", formatter, output_format="plain", strip_references=False
            )

    assert exc_info.value.code == 1
    assert any(
        call.args and call.args[0] == "[ERROR] Failed to render streaming output: stdout closed"
        for call in mock_echo.call_args_list
    )


def test_stream_query_response_uses_shared_unexpected_error_handler():
    """Unexpected streaming failures route through the shared CLI fallback helper."""
    api = Mock()
    api.submit_query.side_effect = RuntimeError("boom")
    formatter = Mock()

    with patch("perplexity_cli.api.streaming.handle_unexpected_cli_error") as mock_handle:
        with pytest.raises(SystemExit):
            mock_handle.side_effect = SystemExit(1)
            stream_query_response(
                api, "test query", formatter, output_format="plain", strip_references=True
            )

    mock_handle.assert_called_once()
    assert mock_handle.call_args.args[0].args[0] == "boom"
    assert mock_handle.call_args.kwargs["include_debug_hint"] is True


def test_stream_query_response_maps_click_exception_to_render_failure():
    """Click output failures stay on the dedicated render-failure path."""
    api = Mock()
    api.submit_query.return_value = iter([_make_message("Answer text")])
    formatter = Mock()

    with patch("perplexity_cli.api.streaming.click.echo") as mock_echo:
        mock_echo.side_effect = [ClickException("bad tty"), None, None]

        with pytest.raises(SystemExit) as exc_info:
            stream_query_response(
                api, "test query", formatter, output_format="plain", strip_references=True
            )

    assert exc_info.value.code == 1
    assert any(
        call.args and call.args[0] == "[ERROR] Failed to render streaming output: bad tty"
        for call in mock_echo.call_args_list
    )
