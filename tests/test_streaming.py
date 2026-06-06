"""Direct tests for streaming query orchestration."""

from __future__ import annotations

from io import StringIO
from unittest.mock import Mock, patch

import pytest
from click import ClickException

from perplexity_cli.api.models import QueryInput, TraceContext, WebResult
from perplexity_cli.formatting.context import OutputOptions, RenderContext
from perplexity_cli.query_streaming import (
    _handle_stream_error,
    _process_stream_message,
    _write_ndjson_result,
    stream_query_response,
)


def _make_render_context(
    output_format: str = "plain",
    strip_references: bool = False,
    json_mode: bool = False,
) -> RenderContext:
    """Build a RenderContext with a Mock formatter and given options."""
    formatter = Mock()
    opts = OutputOptions(
        output_format=output_format,
        strip_references=strip_references,
        json_mode=json_mode,
    )
    return RenderContext(formatter=formatter, options=opts)


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
    render = _make_render_context(output_format="plain", strip_references=True)
    query_input = QueryInput(query="test query")
    trace = TraceContext()

    stream_query_response(api, query_input, render, trace)

    captured = capsys.readouterr()
    assert "Hello world" in captured.out
    render.formatter.format_references.assert_not_called()


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
    render = _make_render_context(output_format="plain", strip_references=False)
    render.formatter.format_references.return_value = "[1] https://example.com"
    query_input = QueryInput(query="test query")
    trace = TraceContext()

    stream_query_response(api, query_input, render, trace)

    captured = capsys.readouterr()
    assert "Answer text" in captured.out
    assert captured.out.count("https://example.com") >= 1
    render.formatter.format_references.assert_called_once()


def test_stream_query_response_renders_rich_references_via_formatter():
    """Rich streaming reuses render_complete for references after text output."""
    api = Mock()
    refs = [WebResult(name="Ref", url="https://example.com", snippet="Example")]
    api.submit_query.return_value = iter([_make_message("Answer text", references=refs)])
    render = _make_render_context(output_format="rich", strip_references=False)
    query_input = QueryInput(query="test query")
    trace = TraceContext()

    stream_query_response(api, query_input, render, trace)

    render.formatter.render_complete.assert_called_once()
    answer_arg = render.formatter.render_complete.call_args.args[0]
    assert answer_arg.text == "Answer text"
    assert answer_arg.references == refs
    assert render.formatter.render_complete.call_args.kwargs["strip_references"] is True


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
    render = _make_render_context(output_format="plain", strip_references=False)
    render.formatter.format_references.side_effect = OSError("stdout closed")
    query_input = QueryInput(query="test query")
    trace = TraceContext()

    with patch("perplexity_cli.query_streaming.click.echo") as mock_echo:
        mock_echo.side_effect = [None, None, None, None, None]

        with pytest.raises(SystemExit) as exc_info:
            stream_query_response(api, query_input, render, trace)

    assert exc_info.value.code == 1
    assert any(
        call.args and call.args[0] == "[ERROR] Failed to render streaming output: stdout closed"
        for call in mock_echo.call_args_list
    )


def test_stream_query_response_uses_shared_unexpected_error_handler():
    """Unexpected streaming failures route through the shared CLI fallback helper."""
    api = Mock()
    api.submit_query.side_effect = RuntimeError("boom")
    render = _make_render_context(output_format="plain", strip_references=True)
    query_input = QueryInput(query="test query")
    trace = TraceContext()

    with patch("perplexity_cli.query_streaming.handle_unexpected_cli_error") as mock_handle:
        with pytest.raises(SystemExit):
            mock_handle.side_effect = SystemExit(1)
            stream_query_response(api, query_input, render, trace)

    mock_handle.assert_called_once()
    assert mock_handle.call_args.args[0].args[0] == "boom"
    assert mock_handle.call_args.kwargs["include_debug_hint"] is True


def test_stream_query_response_maps_click_exception_to_render_failure():
    """Click output failures stay on the dedicated render-failure path."""
    api = Mock()
    api.submit_query.return_value = iter([_make_message("Answer text")])
    render = _make_render_context(output_format="plain", strip_references=True)
    query_input = QueryInput(query="test query")
    trace = TraceContext()

    with patch("perplexity_cli.query_streaming.click.echo") as mock_echo:
        mock_echo.side_effect = [ClickException("bad tty"), None, None]

        with pytest.raises(SystemExit) as exc_info:
            stream_query_response(api, query_input, render, trace)

    assert exc_info.value.code == 1
    assert any(
        call.args and call.args[0] == "[ERROR] Failed to render streaming output: bad tty"
        for call in mock_echo.call_args_list
    )


class TestProcessStreamMessage:
    """Tests for _process_stream_message edge cases."""

    def test_returns_accumulated_when_text_unchanged(self):
        """When extracted text equals accumulated text, no output is emitted."""
        message = _make_message("Hello")
        result = _process_stream_message(message, "Hello", None)
        assert result == "Hello"

    def test_returns_accumulated_when_no_text(self):
        """When extract_answer_text returns None, accumulated text is unchanged."""
        message = Mock()
        message.extract_answer_text.return_value = None
        result = _process_stream_message(message, "existing", None)
        assert result == "existing"

    def test_returns_accumulated_when_new_text_empty(self):
        """When text slice produces empty new_text, accumulated text is unchanged."""
        message = Mock()
        # text is non-None and != accumulated, but slicing gives empty string
        message.extract_answer_text.return_value = "He"
        result = _process_stream_message(message, "Hello", None)
        # "He"[len("Hello"):] would be empty because "He" is shorter
        # Actually "He" != "Hello" and "He"[5:] == "" so returns "Hello"
        assert result == "Hello"

    def test_writes_to_ndjson_writer_when_present(self):
        """When ndjson_writer is provided, chunk is called instead of click.echo."""
        writer = Mock()
        message = _make_message("Hello world")
        result = _process_stream_message(message, "Hello", writer)
        writer.chunk.assert_called_once_with(" world")
        assert result == "Hello world"


class TestWriteNdjsonResult:
    """Tests for _write_ndjson_result."""

    def test_writes_result_with_meta_envelope(self):
        """NDJSON result event contains answer, references, and meta."""
        from perplexity_cli.ndjson import NDJSONWriter

        output = StringIO()
        writer = NDJSONWriter(output)
        refs = [WebResult(name="Ref", url="https://example.com", snippet="Snippet")]

        import time

        start = time.monotonic()
        trace = TraceContext(start_time=start, trace_id="trace-123")
        _write_ndjson_result(writer, "Answer text", refs, trace)

        import json

        line = output.getvalue().strip()
        data = json.loads(line)
        assert data["type"] == "result"
        assert data["ok"] is True
        assert data["result"]["answer"] == "Answer text"
        assert len(data["result"]["references"]) == 1
        assert data["result"]["references"][0]["url"] == "https://example.com"
        assert data["meta"]["trace_id"] == "trace-123"
        assert "duration_ms" in data["meta"]

    def test_writes_result_with_none_start_time(self):
        """When start_time is None, a fallback is used."""
        from perplexity_cli.ndjson import NDJSONWriter

        output = StringIO()
        writer = NDJSONWriter(output)

        trace = TraceContext(start_time=None, trace_id=None)
        _write_ndjson_result(writer, "text", [], trace)

        import json

        data = json.loads(output.getvalue().strip())
        assert data["ok"] is True
        assert data["meta"]["trace_id"] == ""


class TestHandleStreamError:
    """Tests for _handle_stream_error dispatch table."""

    def test_returns_after_matched_handler(self):
        """Handler returns (does not fall through) for a matched error type."""
        import perplexity_cli.query_streaming as streaming_mod

        # Reset the handler cache so it reinitialises
        streaming_mod._STREAM_ERROR_HANDLERS = []

        from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError

        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.headers = {}
        error = PerplexityHTTPStatusError("test", request=Mock(), response=mock_response)

        with patch("perplexity_cli.query_streaming.handle_http_error"):
            with patch("perplexity_cli.query_streaming.click.echo"):
                # Should return without calling handle_unexpected_cli_error
                with patch(
                    "perplexity_cli.query_streaming.handle_unexpected_cli_error"
                ) as mock_unexpected:
                    _handle_stream_error(error)
                    mock_unexpected.assert_not_called()


class TestStreamQueryResponseJsonMode:
    """Tests for stream_query_response with json_mode=True."""

    def test_json_mode_creates_ndjson_writer_and_writes_result(self):
        """json_mode=True creates NDJSONWriter and writes start + result events."""
        api = Mock()
        api.submit_query.return_value = iter([_make_message("Answer")])
        render = _make_render_context(
            output_format="plain",
            strip_references=True,
            json_mode=True,
        )
        query_input = QueryInput(query="test")
        trace = TraceContext(trace_id="t-1")

        with patch("perplexity_cli.query_streaming.sys") as mock_sys:
            output = StringIO()
            mock_sys.stdout = output

            stream_query_response(api, query_input, render, trace)

        import json

        lines = [line for line in output.getvalue().strip().split("\n") if line]
        assert len(lines) == 3  # start, chunk, result
        start = json.loads(lines[0])
        assert start["type"] == "start"
        result = json.loads(lines[-1])
        assert result["type"] == "result"
        assert result["ok"] is True
