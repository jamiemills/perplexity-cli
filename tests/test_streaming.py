"""Direct tests for streaming query orchestration."""

from __future__ import annotations

import ast
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from perplexity_cli.api.models import QueryInput, TraceContext, WebResult
from perplexity_cli.formatting.context import OutputOptions, RenderContext
from perplexity_cli.query_streaming import (
    _get_stream_logger,
    _handle_stream_error,
    _handle_stream_http_status_error,
    _handle_stream_keyboard_interrupt,
    _handle_stream_network_error,
    _handle_stream_output_error,
    _handle_stream_unexpected_error,
    _handle_stream_upstream_schema_error,
    _init_stream_error_handlers,
    _process_stream_message,
    _render_stream_references,
    _run_stream_loop,
    _StreamErrorHandlers,
    _write_ndjson_result,
    stream_query_response,
)
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    UpstreamSchemaError,
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


def test_stream_query_response_plain_rendering_distinguishes_empty_and_nonempty_refs(capsys):
    """Plain output adds references only when formatting produces content."""
    api = Mock()
    refs = [WebResult(name="Ref", url="https://example.com", snippet="Example")]
    api.submit_query.return_value = iter([_make_message("Answer", references=refs)])
    render = _make_render_context(output_format="plain", strip_references=False)
    render.formatter.format_references.return_value = ""

    stream_query_response(api, QueryInput(query="test"), render, TraceContext())

    assert capsys.readouterr().out == "Answer\n\n"
    render.formatter.format_references.assert_called_once()


def test_stream_query_response_strips_references_without_calling_formatter(capsys):
    """The strip option suppresses both reference formatting and output."""
    api = Mock()
    refs = [WebResult(name="Ref", url="https://example.com", snippet="Example")]
    api.submit_query.return_value = iter([_make_message("Answer", references=refs)])
    render = _make_render_context(output_format="plain", strip_references=True)

    stream_query_response(api, QueryInput(query="test"), render, TraceContext())

    assert capsys.readouterr().out == "Answer\n"
    render.formatter.format_references.assert_not_called()


def test_stream_query_response_uses_references_only_from_final_message():
    """References on intermediate snapshots do not leak into the final result."""
    api = Mock()
    intermediate_refs = [WebResult(name="Early", url="https://early.example", snippet="Early")]
    final_refs = [WebResult(name="Final", url="https://final.example", snippet="Final")]
    api.submit_query.return_value = iter(
        [
            _make_message("Answer", final=False, references=intermediate_refs),
            _make_message("Answer", final=True, references=final_refs),
        ]
    )
    render = _make_render_context(output_format="plain", strip_references=False)
    render.formatter.format_references.return_value = "final refs"

    stream_query_response(api, QueryInput(query="test"), render, TraceContext())

    render.formatter.format_references.assert_called_once_with(final_refs)


def test_stream_query_response_json_mode_preserves_incremental_chunks_and_final_refs():
    """JSON streaming exposes each suffix and only the final reference set."""
    import json

    api = Mock()
    early_refs = [WebResult(name="Early", url="https://early.example", snippet="Early")]
    final_refs = [WebResult(name="Final", url="https://final.example", snippet="Final")]
    api.submit_query.return_value = iter(
        [
            _make_message("A", final=False, references=early_refs),
            _make_message("Answer", final=True, references=final_refs),
        ]
    )
    render = _make_render_context(json_mode=True, strip_references=True)
    output = StringIO()

    with patch("perplexity_cli.query_streaming.sys") as mock_sys:
        mock_sys.stdout = output
        stream_query_response(api, QueryInput(query="test"), render, TraceContext())

    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [event["type"] for event in events] == ["start", "chunk", "chunk", "result"]
    assert [event["text"] for event in events[1:3]] == ["A", "nswer"]
    assert events[-1]["result"]["references"][0]["url"] == "https://final.example"
    assert events[0]["command"] == "pxcli query --json --stream"
    render.formatter.format_references.assert_not_called()


@pytest.mark.parametrize(
    ("error", "expected", "exit_code"),
    [
        (PerplexityRequestError("offline"), "internet connection", 6),
        (UpstreamSchemaError("bad snapshot"), "bad snapshot", 7),
        (OSError("closed stdout"), "Failed to render streaming output: closed stdout", 1),
        (RuntimeError("private detail"), "unexpected error occurred", 1),
    ],
)
def test_stream_query_response_keeps_stream_error_boundaries(error, expected, exit_code, capsys):
    """Public streaming errors retain their type-specific user-facing contract."""
    api = Mock()
    api.submit_query.side_effect = error
    render = _make_render_context(strip_references=True)

    with pytest.raises(SystemExit) as exc_info:
        stream_query_response(api, QueryInput(query="test"), render, TraceContext())

    captured = capsys.readouterr()
    assert exc_info.value.code == exit_code
    assert expected in captured.err
    if isinstance(error, RuntimeError):
        assert "private detail" not in captured.err


@pytest.mark.parametrize(
    ("status", "expected", "extra", "exit_code"),
    [
        (401, "Authentication failed", "perplexity-cli auth", 4),
        (403, "Access forbidden", None, 4),
        (429, "Rate limit exceeded", None, 6),
        (418, "HTTP error 418", None, 1),
    ],
)
def test_stream_query_response_keeps_http_status_guidance(
    status, expected, extra, exit_code, capsys
):
    """HTTP status classes retain status-specific guidance at the public boundary."""
    response = Mock(status_code=status)
    api = Mock()
    api.submit_query.side_effect = PerplexityHTTPStatusError("request failed", response=response)
    render = _make_render_context(strip_references=True)

    with pytest.raises(SystemExit) as exc_info:
        stream_query_response(api, QueryInput(query="test"), render, TraceContext())

    captured = capsys.readouterr()
    assert exc_info.value.code == exit_code
    assert captured.out == ""
    assert expected in captured.err
    if extra is not None:
        assert extra in captured.err


def test_stream_query_response_surfaces_output_failure(capsys):
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

    with pytest.raises(SystemExit) as exc_info:
        stream_query_response(api, query_input, render, trace)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "[ERROR] Failed to render streaming output: stdout closed" in captured.err


def test_stream_query_response_uses_unexpected_stream_error_handler():
    """Unexpected streaming failures route through the local fallback handler."""
    api = Mock()
    api.submit_query.side_effect = RuntimeError("boom")
    render = _make_render_context(output_format="plain", strip_references=True)
    query_input = QueryInput(query="test query")
    trace = TraceContext()

    with patch("perplexity_cli.query_streaming._handle_stream_unexpected_error") as mock_unexpected:
        mock_unexpected.side_effect = SystemExit(1)
        with pytest.raises(SystemExit):
            stream_query_response(api, query_input, render, trace)

    mock_unexpected.assert_called_once()
    assert mock_unexpected.call_args.args[0].args[0] == "boom"


def test_stream_query_response_maps_output_oserror_to_render_failure(capsys):
    """Output OSErrors stay on the dedicated render-failure path."""
    with pytest.raises(SystemExit) as exc_info:
        _handle_stream_error(OSError("bad tty"))

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "[ERROR] Failed to render streaming output: bad tty" in captured.err


def test_stream_network_error_has_exact_stable_boundary_output(capsys):
    """Network failures retain the documented guidance and line boundaries."""
    logger = Mock()

    with pytest.raises(SystemExit) as exc_info:
        _handle_stream_network_error(PerplexityRequestError("offline"), logger)

    assert exc_info.value.code == 6
    assert capsys.readouterr().err == (
        "[ERROR] Network error. Please check your internet connection.\n"
    )


def test_stream_http_error_preserves_authentication_extra_line(capsys):
    """Authentication failures include the re-authentication instruction."""
    error = PerplexityHTTPStatusError("request failed", response=Mock(status_code=401))

    with pytest.raises(SystemExit):
        _handle_stream_http_status_error(error, Mock())

    assert capsys.readouterr().err == (
        "[ERROR] Authentication failed. Token may be expired.\n"
        "\nRe-authenticate with: perplexity-cli auth\n"
    )


def test_stream_error_handlers_dispatch_keyboard_interrupt_to_handler(monkeypatch):
    """The lazily-built dispatch table invokes the interrupt handler with its logger."""
    handler = Mock()
    monkeypatch.setattr("perplexity_cli.query_streaming._handle_stream_keyboard_interrupt", handler)

    handlers = _init_stream_error_handlers()
    keyboard_handler = next(callback for types, callback in handlers if types is KeyboardInterrupt)
    logger = Mock()
    keyboard_handler(KeyboardInterrupt(), logger)

    handler.assert_called_once_with(logger, None)


def test_stream_loop_ignores_intermediate_references():
    """Only final SSE messages can replace the reference collection."""
    early = [WebResult(name="early", url="https://early", snippet="early")]
    api = Mock()
    api.submit_query.return_value = iter(
        [
            _make_message("Answer", final=False, references=early),
            _make_message("Answer", final=True),
        ]
    )

    text, references = _run_stream_loop(api, QueryInput(query="query"), None)

    assert text == "Answer"
    assert references == []


def test_write_ndjson_result_uses_json_metadata_and_millisecond_duration(monkeypatch):
    """The result event serialises metadata in JSON mode with millisecond timing."""
    writer = Mock()
    trace = TraceContext(start_time=10.0, trace_id="trace-sentinel")
    monkeypatch.setattr("perplexity_cli.query_streaming.time.monotonic", lambda: 11.234)
    monkeypatch.setattr("perplexity_cli.query_streaming.get_version", lambda: "version-sentinel")

    _write_ndjson_result(writer, "answer", [], trace)

    kwargs = writer.result.call_args.kwargs
    assert kwargs["ok"] is True
    assert kwargs["command"] == "pxcli query --json --stream"
    assert kwargs["result"] == {"answer": "answer", "references": []}
    assert kwargs["extras"][0] == {
        "duration_ms": 1234,
        "version": "version-sentinel",
        "trace_id": "trace-sentinel",
        "truncated": False,
    }


def test_stream_query_response_forwards_query_and_emits_final_answer(monkeypatch):
    """The public stream boundary forwards its input and preserves final text."""
    api = Mock()
    message = _make_message("answer", references=[])
    api.submit_query.side_effect = lambda query_input: iter(
        [message] if query_input == QueryInput(query="query") else []
    )
    render = _make_render_context(output_format="plain", strip_references=True)

    stream_query_response(api, QueryInput(query="query"), render, TraceContext())

    api.submit_query.assert_called_once_with(QueryInput(query="query"))
    assert message.extract_answer_text.called


def test_stream_query_response_json_result_preserves_accumulated_text(monkeypatch):
    """JSON streaming passes the accumulated answer to the final result event."""
    api = Mock()
    api.submit_query.return_value = iter([_make_message("answer")])
    render = _make_render_context(json_mode=True)
    result = Mock()
    monkeypatch.setattr("perplexity_cli.query_streaming._write_ndjson_result", result)
    monkeypatch.setattr("perplexity_cli.query_streaming.NDJSONWriter.start", Mock())

    stream_query_response(api, QueryInput(query="query"), render, TraceContext())

    assert result.call_args.args[1] == "answer"


def test_stream_query_response_divergent_snapshot_emits_no_garbage(capsys):
    """A divergent snapshot stops streaming without emitting partial text."""
    api = Mock()
    api.submit_query.return_value = iter(
        [
            _make_message("Hello"),
            _make_message("Hallo"),
        ]
    )
    render = _make_render_context(output_format="plain", strip_references=True)
    query_input = QueryInput(query="test query")
    trace = TraceContext()

    with pytest.raises(SystemExit) as exc_info:
        stream_query_response(api, query_input, render, trace)

    assert exc_info.value.code == 7
    captured = capsys.readouterr()
    assert captured.out.strip() == "Hello"
    assert "Upstream response format changed" in captured.err


class TestProcessStreamMessage:
    """Tests for _process_stream_message snapshot contract."""

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

    def test_returns_accumulated_when_empty_snapshot(self):
        """An empty snapshot emits no output and leaves text unchanged."""
        message = _make_message("")
        result = _process_stream_message(message, "Hello", None)
        assert result == "Hello"

    def test_prefix_extension_emits_suffix_human_path(self, capsys):
        """A strict prefix extension emits exactly the suffix (human path)."""
        message = _make_message("Hello world")
        result = _process_stream_message(message, "Hello", None)
        assert result == "Hello world"
        captured = capsys.readouterr()
        assert captured.out == " world"

    def test_writes_to_ndjson_writer_when_present(self):
        """A strict prefix extension emits exactly the suffix (NDJSON path)."""
        writer = Mock()
        message = _make_message("Hello world")
        result = _process_stream_message(message, "Hello", writer)
        writer.chunk.assert_called_once_with(" world")
        assert result == "Hello world"

    def test_divergent_snapshot_raises_without_output(self, capsys):
        """A non-prefix snapshot raises UpstreamSchemaError before output."""
        message = _make_message("Help")
        with pytest.raises(UpstreamSchemaError):
            _process_stream_message(message, "Hello", None)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_shortened_snapshot_raises_without_output(self, capsys):
        """A shortened snapshot raises UpstreamSchemaError before output."""
        message = _make_message("He")
        with pytest.raises(UpstreamSchemaError):
            _process_stream_message(message, "Hello", None)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_divergent_snapshot_raises_before_ndjson_output(self):
        """A non-prefix snapshot raises before any NDJSON chunk is written."""
        writer = Mock()
        message = _make_message("Help")
        with pytest.raises(UpstreamSchemaError):
            _process_stream_message(message, "Hello", writer)
        writer.chunk.assert_not_called()

    def test_identical_snapshot_does_not_write_to_ndjson(self):
        """Repeated snapshots do not emit duplicate JSON chunks."""
        writer = Mock()
        result = _process_stream_message(_make_message("Hello"), "Hello", writer)

        assert result == "Hello"
        writer.chunk.assert_not_called()

    def test_falsey_writer_uses_human_output(self, capsys):
        """A falsey writer follows the human output branch without a chunk call."""
        writer = Mock()
        writer.__bool__ = Mock(return_value=False)

        result = _process_stream_message(_make_message("Hello world"), "Hello", writer)

        assert result == "Hello world"
        assert capsys.readouterr().out == " world"
        writer.chunk.assert_not_called()

    def test_prefix_extension_from_empty_accumulator_writes_all_text(self, capsys):
        """The first non-empty snapshot emits its complete text."""
        result = _process_stream_message(_make_message("Hello"), "", None)

        assert result == "Hello"
        assert capsys.readouterr().out == "Hello"


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

    def test_serializes_all_reference_fields(self):
        """NDJSON references preserve names, URLs, and snippets independently."""
        from perplexity_cli.ndjson import NDJSONWriter

        output = StringIO()
        writer = NDJSONWriter(output)
        reference = WebResult(name="Name", url="https://url", snippet="Snippet")

        _write_ndjson_result(writer, "Answer", [reference], TraceContext())

        import json

        result = json.loads(output.getvalue())["result"]
        assert result == {
            "answer": "Answer",
            "references": [{"name": "Name", "url": "https://url", "snippet": "Snippet"}],
        }


class TestHandleStreamError:
    """Tests for _handle_stream_error dispatch table."""

    def test_returns_after_matched_handler(self):
        """Handler returns (does not fall through) for a matched error type."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.headers = {}
        error = PerplexityHTTPStatusError("test", request=Mock(), response=mock_response)

        with patch(
            "perplexity_cli.query_streaming._handle_stream_unexpected_error"
        ) as mock_unexpected:
            with pytest.raises(SystemExit) as exc_info:
                _handle_stream_error(error)

        assert exc_info.value.code == 6
        mock_unexpected.assert_not_called()

    @pytest.mark.parametrize(
        ("status", "expected", "exit_code"),
        [
            (401, "Authentication failed", 4),
            (403, "Access forbidden", 4),
            (429, "Rate limit exceeded", 6),
            (500, "HTTP error 500", 6),
        ],
    )
    def test_http_status_messages_are_status_specific(self, status, expected, exit_code, capsys):
        """HTTP status classes retain their distinct user-facing guidance."""
        error = PerplexityHTTPStatusError("request failed", response=Mock(status_code=status))
        logger = Mock()

        with pytest.raises(SystemExit) as exc_info:
            _handle_stream_http_status_error(error, logger)

        assert exc_info.value.code == exit_code
        assert expected in capsys.readouterr().err
        logger.error.assert_called_once_with("HTTP error %s during streaming: %s", status, error)

    def test_network_error_has_network_guidance(self, capsys):
        """Network failures produce actionable connection guidance."""
        error = PerplexityRequestError("offline")
        logger = Mock()
        with pytest.raises(SystemExit) as exc_info:
            _handle_stream_network_error(error, logger)

        assert exc_info.value.code == 6
        assert "internet connection" in capsys.readouterr().err
        logger.error.assert_called_once_with("Network error during streaming: %s", error)

    def test_keyboard_interrupt_uses_interrupt_exit_code(self, capsys):
        """Streaming interruption exits with the shell interrupt status."""
        with pytest.raises(SystemExit) as exc_info:
            _handle_stream_keyboard_interrupt(Mock())

        assert exc_info.value.code == 130
        assert "Streaming interrupted" in capsys.readouterr().err

    def test_upstream_schema_error_includes_original_detail(self, capsys):
        """Malformed upstream data keeps the diagnostic detail visible."""
        with pytest.raises(SystemExit) as exc_info:
            _handle_stream_upstream_schema_error(UpstreamSchemaError("missing text"), Mock())

        assert exc_info.value.code == 7
        assert "missing text" in capsys.readouterr().err

    def test_output_error_includes_original_detail(self, capsys):
        """Local output failures use the dedicated rendering message."""
        with pytest.raises(SystemExit) as exc_info:
            _handle_stream_output_error(OSError("closed"), Mock())

        assert exc_info.value.code == 1
        assert "closed" in capsys.readouterr().err

    def test_unexpected_error_hides_internal_detail(self, capsys):
        """Unexpected failures expose safe guidance rather than exception data."""
        with pytest.raises(SystemExit) as exc_info:
            _handle_stream_unexpected_error(RuntimeError("secret detail"), Mock())

        assert exc_info.value.code == 1
        captured = capsys.readouterr().err
        assert "unexpected error" in captured
        assert "secret detail" not in captured

    def test_unknown_error_uses_unexpected_handler(self):
        """Errors outside the dispatch table use the safe fallback handler."""
        error = ValueError("bad value")

        with patch(
            "perplexity_cli.query_streaming._handle_stream_unexpected_error",
            side_effect=SystemExit(1),
        ) as unexpected:
            with pytest.raises(SystemExit):
                _handle_stream_error(error)

        unexpected.assert_called_once()
        assert unexpected.call_args.args[0] is error

    def test_http_handler_writes_extra_guidance_only_for_known_status(self, capsys):
        """Only statuses with extra guidance receive a second error line."""
        error = PerplexityHTTPStatusError("request failed", response=Mock(status_code=500))

        with pytest.raises(SystemExit):
            _handle_stream_http_status_error(error, Mock())

        assert "Re-authenticate" not in capsys.readouterr().err


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


class TestStreamFailureContract:
    """Terminal failure events and taxonomy exit codes for streaming."""

    @pytest.mark.parametrize(
        ("error", "code", "exit_code"),
        [
            (
                PerplexityHTTPStatusError("denied", response=Mock(status_code=401)),
                "authentication_required",
                4,
            ),
            (
                PerplexityHTTPStatusError("slow down", response=Mock(status_code=429)),
                "rate_limited",
                6,
            ),
            (UpstreamSchemaError("bad snapshot"), "upstream_schema_error", 7),
        ],
    )
    def test_json_mode_failure_emits_terminal_result_event(self, error, code, exit_code):
        """JSON streaming failures end with an ok=false result event and taxonomy code."""
        import json

        api = Mock()
        api.submit_query.side_effect = error
        render = _make_render_context(json_mode=True, strip_references=True)
        output = StringIO()

        with patch("perplexity_cli.query_streaming.sys") as mock_sys:
            mock_sys.stdout = output
            with pytest.raises(SystemExit) as exc_info:
                stream_query_response(api, QueryInput(query="test"), render, TraceContext())

        assert exc_info.value.code == exit_code
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        assert [event["type"] for event in events] == ["start", "result"]
        assert events[-1]["ok"] is False
        assert events[-1]["command"] == "pxcli query --json --stream"
        assert events[-1]["result"]["error"]["code"] == code
        assert events[-1]["result"]["error"]["message"]

    def test_json_mode_interrupt_emits_failure_event_and_exits_130(self):
        """A mid-stream interrupt in JSON mode emits an ok=false event and exits 130."""
        import json

        api = Mock()
        api.submit_query.side_effect = KeyboardInterrupt
        render = _make_render_context(json_mode=True, strip_references=True)
        output = StringIO()

        with patch("perplexity_cli.query_streaming.sys") as mock_sys:
            mock_sys.stdout = output
            with pytest.raises(SystemExit) as exc_info:
                stream_query_response(api, QueryInput(query="test"), render, TraceContext())

        assert exc_info.value.code == 130
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        assert events[-1]["ok"] is False
        assert events[-1]["result"]["error"]["code"] == "interrupted"

    def test_json_mode_failure_stdout_contains_only_ndjson_events(self):
        """JSON failure output stays pure NDJSON with no corrupting blank lines."""
        import json

        api = Mock()
        api.submit_query.side_effect = PerplexityRequestError("offline")
        render = _make_render_context(json_mode=True, strip_references=True)
        output = StringIO()

        with patch("perplexity_cli.query_streaming.sys") as mock_sys:
            mock_sys.stdout = output
            with pytest.raises(SystemExit) as exc_info:
                stream_query_response(api, QueryInput(query="test"), render, TraceContext())

        assert exc_info.value.code == 6
        raw = output.getvalue()
        assert raw.endswith("}\n")
        events = [json.loads(line) for line in raw.splitlines()]
        assert [event["type"] for event in events] == ["start", "result"]

    def test_human_mode_failure_is_stderr_only(self, capsys):
        """Human-mode failures write guidance to stderr only, with no stdout newline."""
        api = Mock()
        api.submit_query.side_effect = PerplexityRequestError("offline")
        render = _make_render_context(strip_references=True)

        with pytest.raises(SystemExit) as exc_info:
            stream_query_response(api, QueryInput(query="test"), render, TraceContext())

        assert exc_info.value.code == 6
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "internet connection" in captured.err

    def test_json_mode_stream_without_final_message_emits_schema_failure_event(self):
        """A stream lacking a final SSE message ends in an upstream_schema_error event."""
        import json

        api = Mock()
        api.submit_query.return_value = iter(
            [
                _make_message("Partial", final=False),
                _make_message("Partial answer", final=False),
            ]
        )
        render = _make_render_context(json_mode=True, strip_references=True)
        output = StringIO()

        with patch("perplexity_cli.query_streaming.sys") as mock_sys:
            mock_sys.stdout = output
            with pytest.raises(SystemExit) as exc_info:
                stream_query_response(api, QueryInput(query="test"), render, TraceContext())

        assert exc_info.value.code == 7
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        assert [event["type"] for event in events] == ["start", "chunk", "chunk", "result"]
        assert events[-1]["ok"] is False
        assert events[-1]["result"]["error"]["code"] == "upstream_schema_error"
        assert (
            "No final SSE message found in upstream response"
            in events[-1]["result"]["error"]["message"]
        )

    def test_human_mode_stream_without_final_message_errors_to_stderr(self, capsys):
        """A human-mode stream lacking a final SSE message reports the error and exits 7."""
        api = Mock()
        api.submit_query.return_value = iter([_make_message("Partial", final=False)])
        render = _make_render_context(strip_references=True)

        with pytest.raises(SystemExit) as exc_info:
            stream_query_response(api, QueryInput(query="test"), render, TraceContext())

        assert exc_info.value.code == 7
        captured = capsys.readouterr()
        assert "Partial" in captured.out
        assert "Upstream response format changed" in captured.err
        assert "No final SSE message found in upstream response" in captured.err

    def test_failure_event_broken_pipe_does_not_mask_original_error(self):
        """A dead output pipe never masks the original streaming failure."""
        writer = Mock()
        writer.result.side_effect = BrokenPipeError("pipe closed")

        with pytest.raises(SystemExit) as exc_info:
            _handle_stream_error(UpstreamSchemaError("bad snapshot"), writer)

        assert exc_info.value.code == 7
        writer.result.assert_called_once()


def test_run_stream_loop_ignores_nonfinal_references():
    """Only references attached to a final snapshot are returned."""
    early = [WebResult(name="Early", url="https://early", snippet="early")]
    api = Mock()
    api.submit_query.return_value = iter(
        [_make_message("Answer", final=False, references=early), _make_message("Answer")]
    )

    text, references = _run_stream_loop(api, QueryInput(query="test"), None)

    assert text == "Answer"
    assert references == []


def test_run_stream_loop_without_final_message_raises_upstream_schema_error():
    """A stream ending without a final SSE message raises the canonical error."""
    api = Mock()
    api.submit_query.return_value = iter([_make_message("Partial", final=False)])

    with pytest.raises(UpstreamSchemaError) as exc_info:
        _run_stream_loop(api, QueryInput(query="test"), None)

    assert str(exc_info.value) == "No final SSE message found in upstream response"


@pytest.mark.parametrize(
    ("output_format", "strip_references", "formatted", "expected"),
    [
        ("plain", False, "refs", "\n\nrefs\n"),
        ("plain", False, "", "\n\n"),
        ("plain", True, "refs", "\n"),
    ],
)
def test_render_stream_references_plain_boundaries(
    output_format, strip_references, formatted, expected, capsys
):
    """Plain reference rendering distinguishes stripped and empty output."""
    render = _make_render_context(output_format, strip_references)
    render.formatter.format_references.return_value = formatted

    _render_stream_references(render, "Answer", [WebResult(name="Ref", url="url", snippet="")])

    assert capsys.readouterr().out == expected
    if strip_references:
        render.formatter.format_references.assert_not_called()
    else:
        render.formatter.format_references.assert_called_once()


def test_render_stream_references_rich_passes_complete_answer(capsys):
    """Rich rendering receives the accumulated answer and references."""
    render = _make_render_context("rich", False)
    references = [WebResult(name="Ref", url="url", snippet="snippet")]

    _render_stream_references(render, "Answer", references)

    assert capsys.readouterr().out == "\n\n"
    answer = render.formatter.render_complete.call_args.args[0]
    assert answer.text == "Answer"
    assert answer.references == references


def test_query_streaming_keeps_application_layer_imports():
    """query_streaming must not import adapter, presentation, or framework modules."""
    source_path = (
        Path(__file__).resolve().parents[1] / "src" / "perplexity_cli" / "query_streaming.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    banned_prefixes = (
        "click",
        "perplexity_cli.utils.http_errors",
        "perplexity_cli.utils.logging",
        "perplexity_cli.formatting",
    )
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)
    offenders = [name for name in imported_modules if name.startswith(banned_prefixes)]
    assert offenders == []


def test_stream_logger_uses_the_module_namespace():
    """Streaming diagnostics remain isolated under the streaming logger name."""
    assert _get_stream_logger().name == "perplexity_cli.query_streaming"


def test_stream_error_handlers_are_cached_and_cover_known_error_types():
    """The dispatch table is stable and reuses its lazy cache."""
    _StreamErrorHandlers._cache = None

    handlers = _StreamErrorHandlers.get()

    assert handlers is _StreamErrorHandlers.get()
    assert len(handlers) == 5


def test_process_stream_message_reports_snapshot_contract_exactly():
    """Malformed snapshots expose the diagnostic contract, not a blank error."""
    with pytest.raises(UpstreamSchemaError) as exc_info:
        _process_stream_message(_make_message("Help"), "Hello", None)

    assert str(exc_info.value) == (
        "Streaming snapshot is not a strict prefix extension of the accumulated text "
        "(accumulated 5 characters, received 4)"
    )


def test_write_ndjson_result_forwards_exact_writer_contract(monkeypatch):
    """Final stream metadata uses milliseconds and the canonical result arguments."""
    writer = Mock()
    trace = TraceContext(start_time=100.0, trace_id="trace")
    monkeypatch.setattr("perplexity_cli.query_streaming.time.monotonic", lambda: 100.25)

    _write_ndjson_result(writer, "answer", [], trace)

    writer.result.assert_called_once()
    kwargs = writer.result.call_args.kwargs
    assert kwargs["ok"] is True
    assert kwargs["command"] == "pxcli query --json --stream"
    assert kwargs["result"] == {"answer": "answer", "references": []}
    assert kwargs["extras"][0]["duration_ms"] == 250
    assert kwargs["extras"][2] is False


def test_run_stream_loop_forwards_input_and_records_final_references():
    """The gateway receives the original input and final references only."""
    api = Mock()
    refs = [WebResult(name="Final", url="url", snippet="snippet")]
    api.submit_query.return_value = iter([_make_message("Answer", references=refs)])
    query_input = QueryInput(query="original")

    text, references = _run_stream_loop(api, query_input, None)

    assert (text, references) == ("Answer", refs)
    api.submit_query.assert_called_once_with(query_input)


@pytest.mark.parametrize(
    ("handler", "error", "level", "message"),
    [
        (
            _handle_stream_network_error,
            PerplexityRequestError("offline"),
            "error",
            "Network error during streaming: %s",
        ),
        (
            _handle_stream_upstream_schema_error,
            UpstreamSchemaError("bad"),
            "error",
            "Malformed upstream response during streaming: %s",
        ),
        (_handle_stream_output_error, OSError("closed"), "error", "Streaming output failed: %s"),
    ],
)
def test_stream_error_handlers_log_the_original_error(handler, error, level, message, capsys):
    """Streaming handlers preserve lazy logger format strings and values."""
    logger = Mock()
    with pytest.raises(SystemExit):
        handler(error, logger)

    getattr(logger, level).assert_called_once_with(message, error)
    assert capsys.readouterr().out == ""


def test_stream_http_error_logs_and_writes_exact_lines(capsys):
    """HTTP streaming failures preserve status logging and line boundaries."""
    error = PerplexityHTTPStatusError("failed", response=Mock(status_code=401))
    logger = Mock()

    with pytest.raises(SystemExit):
        _handle_stream_http_status_error(error, logger)

    logger.error.assert_called_once_with("HTTP error %s during streaming: %s", 401, error)
    assert capsys.readouterr().out == ""


def test_stream_keyboard_interrupt_logs_exactly_once(capsys):
    """Interrupts retain both the informational log and terminal error line."""
    logger = Mock()
    with pytest.raises(SystemExit):
        _handle_stream_keyboard_interrupt(logger)

    logger.info.assert_called_once_with("Streaming interrupted by user")
    assert capsys.readouterr().err == "\n[ERROR] Streaming interrupted.\n"


def test_stream_unexpected_error_logs_safe_message_and_hides_detail(capsys):
    """Unexpected errors log detail but expose only safe terminal guidance."""
    logger = Mock()
    error = RuntimeError("private sentinel")

    with pytest.raises(SystemExit):
        _handle_stream_unexpected_error(error, logger)

    logger.error.assert_called_once_with("Unexpected error during streaming: %s", error)
    assert capsys.readouterr().err == (
        "[ERROR] An unexpected error occurred.\nRun with --debug for more information.\n"
    )


def test_stream_loop_logs_message_and_reference_counts(caplog):
    """Streaming diagnostics record each message and extracted reference count."""
    api = Mock()
    api.submit_query.return_value = iter(
        [_make_message("Answer", references=[WebResult(name="R", url="u", snippet="s")])]
    )

    with caplog.at_level("DEBUG", logger="perplexity_cli.query_streaming"):
        _run_stream_loop(api, QueryInput(query="q"), None)

    messages = [record.getMessage() for record in caplog.records]
    assert "Received SSE message: status=COMPLETE, final=True" in messages
    assert "Extracted 1 references" in messages


def test_stream_error_handler_table_has_canonical_order_and_types():
    """Known exception classes are dispatched in the documented order."""
    streaming = __import__(
        "perplexity_cli.query_streaming", fromlist=["_init_stream_error_handlers"]
    )
    handlers = streaming._init_stream_error_handlers()
    assert [types for types, _handler in handlers] == [
        PerplexityHTTPStatusError,
        PerplexityRequestError,
        UpstreamSchemaError,
        KeyboardInterrupt,
        OSError,
    ]
