"""Direct tests for query runner orchestration helpers."""

import json
import logging
import sys
from unittest.mock import Mock, patch

import pytest

from perplexity_cli.api.models import Answer, QueryInput, TraceContext, WebResult
from perplexity_cli.auth.models import AuthContext
from perplexity_cli.query_runner import (
    QueryOptions,
    _build_json_envelope,
    _detect_execution_environment,
    _do_s3_upload,
    _load_and_upload_attachments,
    _QueryOutputOptionsData,
    _QueryRenderContextData,
    _read_ctx_options,
    _require_auth_for_attachments,
    _resolve_and_upload,
    build_final_query,
    get_query_formatter,
    log_query_debug_context,
    parse_request_param_overrides,
    render_complete_answer,
    resolve_attachment_urls,
    run_query_command,
)
from perplexity_cli.utils.attachment_models import FileAttachment
from perplexity_cli.utils.exceptions import AuthenticationError, UpstreamSchemaError


def _make_api_mock(answer: Answer | None = None):
    """Create a context-manager-compatible PerplexityAPI mock."""
    mock_api = Mock()
    mock_api.__enter__ = Mock(return_value=mock_api)
    mock_api.__exit__ = Mock(return_value=False)
    if answer is not None:
        mock_api.get_complete_answer.return_value = answer
    return mock_api


def _default_options(**overrides: object) -> QueryOptions:
    """Build a QueryOptions with sensible test defaults."""
    defaults: dict[str, object] = {
        "output_format": "plain",
        "strip_references": False,
        "stream": False,
        "attachments": (),
        "model_preference": None,
        "request_param_overrides": (),
    }
    defaults.update(overrides)
    return QueryOptions(**defaults)  # type: ignore[arg-type]  # owner: test-infrastructure; reason: dynamic override helper intentionally assembles typed QueryOptions fields


def test_build_final_query_appends_style():
    """Configured style text is appended to the outgoing query."""
    with patch("perplexity_cli.query_runner.StyleManager", autospec=True) as mock_sm_class:
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
    with (
        patch("perplexity_cli.query_runner.TokenManager", return_value=Mock(), autospec=True),
        patch(
            "perplexity_cli.query_runner.load_token_optional",
            return_value=("token-123", None),
            autospec=True,
        ),
        patch(
            "perplexity_cli.query_runner.resolve_attachment_urls", return_value=[], autospec=True
        ),
    ):
        with pytest.raises(SystemExit) as exc_info:
            run_query_command(
                ctx_obj={"debug": False},
                query_text="What is Python?",
                options=_default_options(output_format="invalid-format"),
            )

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "Available:" in captured.err


def test_read_ctx_options_normalises_missing_and_present_values():
    """Context flags produce the expected JSON, timeout and schema tuple."""
    assert _read_ctx_options(None) == (False, None, False)
    assert _read_ctx_options({}) == (False, None, False)
    assert _read_ctx_options({"json": True, "timeout": 30, "schema": True}) == (
        True,
        30,
        True,
    )
    assert _read_ctx_options({"json": 1, "timeout": "30", "schema": 0}) == (
        True,
        None,
        False,
    )


def test_detect_execution_environment_distinguishes_uvx_venv_virtualenv_unknown(monkeypatch):
    """Environment detection prioritises uvx, then venv, then prefix differences."""
    monkeypatch.delenv("UV_ACTIVE", raising=False)
    monkeypatch.delenv("UVXENV", raising=False)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(sys, "base_prefix", "/usr")
    monkeypatch.setattr(sys, "prefix", "/usr")
    assert _detect_execution_environment() == "unknown"

    monkeypatch.setattr(sys, "prefix", "/tmp/virtualenv")
    assert _detect_execution_environment() == "virtualenv"

    monkeypatch.setenv("VIRTUAL_ENV", "/tmp/venv")
    assert _detect_execution_environment() == "venv"

    monkeypatch.setenv("UV_ACTIVE", "1")
    assert _detect_execution_environment() == "uvx"


def test_log_query_debug_context_logs_redacted_environment_context(monkeypatch, caplog, tmp_path):
    """Debug context logs environment details without sensitive values."""
    logger = logging.getLogger("perplexity_cli")
    logger.setLevel(logging.DEBUG)
    token_path = tmp_path / "token.json"
    token_path.write_text("secret", encoding="utf-8")
    paths = Mock(token_path=token_path)
    monkeypatch.setattr("perplexity_cli.query_runner.get_config_paths", lambda: paths)
    monkeypatch.setattr("perplexity_cli.query_runner.get_save_cookies_enabled", lambda: False)
    monkeypatch.setattr("perplexity_cli.query_runner.redact_path", lambda value: "<path>")
    monkeypatch.setattr(
        "perplexity_cli.query_runner.redact_text",
        lambda value: "<query>",
    )
    monkeypatch.setattr("perplexity_cli.query_runner.socket.gethostname", lambda: "runner")

    with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
        log_query_debug_context("sensitive query", "plain", "batch")

    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert (
        bool(caplog.records),
        "<path>" in combined,
        "<query>" in combined,
        "sensitive query" not in combined,
        str(token_path) not in combined,
    ) == (True, True, True, True, True)


def test_log_query_debug_context_handles_hostname_failure(monkeypatch, caplog):
    """Hostname lookup errors become a safe debug fallback."""
    logger = logging.getLogger("perplexity_cli")
    logger.setLevel(logging.DEBUG)
    monkeypatch.setattr(
        "perplexity_cli.query_runner.socket.gethostname",
        Mock(side_effect=OSError("hostname unavailable")),
    )
    monkeypatch.setattr(
        "perplexity_cli.query_runner.get_config_paths",
        lambda: Mock(token_path=Mock(exists=lambda: False)),
    )
    monkeypatch.setattr("perplexity_cli.query_runner.get_save_cookies_enabled", lambda: True)
    monkeypatch.setattr("perplexity_cli.query_runner.redact_path", lambda value: "<path>")
    monkeypatch.setattr("perplexity_cli.query_runner.redact_text", lambda value: "<query>")

    with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
        log_query_debug_context("query", None, "stream")

    assert caplog.records
    assert "hostname unavailable" not in "\n".join(record.getMessage() for record in caplog.records)


def test_build_json_envelope_contains_answer_references_and_trace(monkeypatch):
    """JSON mode serialises result fields, metadata and schema selection."""
    answer = Answer(
        text="Answer",
        references=[WebResult(name="Source", url="https://source.test", snippet="Snippet")],
    )
    trace = TraceContext(trace_id="trace-123", start_time=100.0)
    monkeypatch.setattr("perplexity_cli.query_runner.time.monotonic", lambda: 101.25)
    monkeypatch.setattr("perplexity_cli.query_runner.get_version", lambda: "1.2.3")

    payload = json.loads(_build_json_envelope(answer, trace, "no_schema"))

    assert payload == {
        "ok": True,
        "command": "pxcli query --json",
        "result": {
            "answer": "Answer",
            "references": [{"name": "Source", "url": "https://source.test", "snippet": "Snippet"}],
        },
        "meta": {
            "trace_id": "trace-123",
            "version": "1.2.3",
            "duration_ms": 1250,
            "truncated": False,
        },
        "next_actions": [],
    }


def test_build_json_envelope_includes_schema_and_normalises_missing_trace(monkeypatch):
    """Schema requests are honoured and absent trace IDs remain empty strings."""
    monkeypatch.setattr("perplexity_cli.query_runner.time.monotonic", lambda: 101.0)

    payload = json.loads(
        _build_json_envelope(
            Answer(text="Answer", references=[]),
            TraceContext(trace_id=None, start_time=100.0),
            "with_schema",
        )
    )

    assert "$schema" in payload
    assert payload["meta"]["trace_id"] == ""


def test_resolve_attachment_urls_skips_ordinary_text_without_files(monkeypatch):
    """Ordinary query text does not resolve or upload attachments."""
    resolver = Mock()
    monkeypatch.setattr("perplexity_cli.query_runner._resolve_and_upload", resolver)

    result = resolve_attachment_urls("Tell me about Python", (), AuthContext(token="token"))

    assert result == []
    resolver.assert_not_called()


def test_resolve_attachment_urls_passes_explicit_attachments(monkeypatch):
    """Explicit attachment values reach the resolver with authentication."""
    resolver = Mock(return_value=["https://file.test/one"])
    monkeypatch.setattr("perplexity_cli.query_runner._resolve_and_upload", resolver)

    result = resolve_attachment_urls(
        "Analyse these files", ("one.txt",), AuthContext(token="token")
    )

    assert result == ["https://file.test/one"]
    resolver.assert_called_once()
    assert resolver.call_args.args[:3] == (
        "Analyse these files",
        ["one.txt"],
        AuthContext(token="token"),
    )


def test_resolve_and_upload_forwards_validated_auth_and_cookies(monkeypatch, tmp_path):
    """Resolved attachments use the validated token and original browser cookies."""
    file_path = tmp_path / "one.txt"
    logger = Mock()
    cookies = {"session": "cookie-value"}
    resolver = Mock(return_value=[file_path])
    auth_validator = Mock(return_value="validated-token")
    loader = Mock(return_value=["https://file.test/one"])
    monkeypatch.setattr("perplexity_cli.query_runner.resolve_file_arguments", resolver)
    monkeypatch.setattr("perplexity_cli.query_runner._require_auth_for_attachments", auth_validator)
    monkeypatch.setattr("perplexity_cli.query_runner._load_and_upload_attachments", loader)

    result = _resolve_and_upload(
        "Analyse this",
        ["one.txt"],
        AuthContext(token="raw-token", cookies=cookies),
        logger,
    )

    assert result == ["https://file.test/one"]
    resolver.assert_called_once_with(["Analyse this"], attach_args=["one.txt"])
    auth_validator.assert_called_once_with("raw-token", logger)
    loader.assert_called_once_with([file_path], "validated-token", cookies, logger)


def test_require_auth_for_attachments_rejects_missing_token():
    """Attachment uploads fail before file loading when no token exists."""
    logger = Mock()

    with pytest.raises(AuthenticationError, match="require authentication"):
        _require_auth_for_attachments(None, logger)

    logger.error.assert_called_once_with("Attachment upload attempted without authentication")


def test_load_and_upload_attachments_returns_empty_without_files(monkeypatch):
    """No loaded attachments means no uploader call and an empty URL list."""
    loader = Mock(return_value=[])
    uploader = Mock()
    monkeypatch.setattr("perplexity_cli.query_runner.load_attachments", loader)
    monkeypatch.setattr("perplexity_cli.query_runner._do_s3_upload", uploader)

    result = _load_and_upload_attachments([], "token", None, Mock())

    assert result == []
    loader.assert_called_once_with([])
    uploader.assert_not_called()


def test_do_s3_upload_constructs_uploader_with_token_and_cookies(monkeypatch):
    """S3 upload authentication includes both the token and browser cookies."""
    attachment = FileAttachment(filename="one.txt", content_type="text/plain", data="dGVzdA==")
    uploader = Mock()
    uploader.upload_files.return_value = Mock()
    uploader_class = Mock(return_value=uploader)
    async_runner = Mock(return_value=["https://file.test/one"])
    monkeypatch.setattr("perplexity_cli.query_runner.AttachmentUploader", uploader_class)
    monkeypatch.setattr("perplexity_cli.query_runner.run_async", async_runner)

    result = _do_s3_upload(
        [attachment],
        "token-123",
        {"session": "cookie-value"},
        Mock(),
    )

    assert result == ["https://file.test/one"]
    uploader_class.assert_called_once_with(
        token="token-123",
        cookies={"session": "cookie-value"},
    )
    uploader.upload_files.assert_called_once_with([attachment])
    async_runner.assert_called_once_with(uploader.upload_files.return_value)


def test_render_complete_answer_uses_plain_formatter_output(monkeypatch):
    """Non-rich rendering writes the formatter's complete output plus newline."""
    formatter = Mock()
    formatter.format_complete.return_value = "formatted"
    render = _QueryRenderContextData(
        formatter=formatter,
        options=_QueryOutputOptionsData("plain", True, False, False),
    )
    output = Mock()
    monkeypatch.setattr("perplexity_cli.query_runner._write_stdout", output)
    answer = Answer(text="answer", references=[])

    render_complete_answer(answer, render)

    formatter.format_complete.assert_called_once_with(answer, strip_references=True)
    output.assert_called_once_with("formatted\n")


def test_run_query_command_non_streaming_renders_answer(capsys):
    """Query runner executes batch mode and renders the formatted answer."""
    answer = Answer(text="Test answer", references=[])
    mock_api = _make_api_mock(answer)

    with (
        patch("perplexity_cli.query_runner.TokenManager", return_value=Mock(), autospec=True),
        patch(
            "perplexity_cli.query_runner.load_token_optional",
            return_value=("token-123", None),
            autospec=True,
        ),
        patch(
            "perplexity_cli.query_runner.resolve_attachment_urls", return_value=[], autospec=True
        ),
        patch("perplexity_cli.query_runner.PerplexityAPI", return_value=mock_api, autospec=True),
        patch(
            "perplexity_cli.query_runner.build_final_query",
            return_value="final query",
            autospec=True,
        ),
    ):
        run_query_command(
            ctx_obj={"debug": False},
            query_text="What is Python?",
            options=_default_options(),
        )

    captured = capsys.readouterr()
    assert "Test answer" in captured.out
    assert "ERROR" not in captured.err
    mock_api.get_complete_answer.assert_called_once_with(
        "final query",
        extra_params=([], None, {}),
    )


def test_run_query_command_streaming_delegates_to_stream_handler():
    """Streaming mode delegates to the streaming helper with resolved inputs."""
    mock_api = _make_api_mock()

    with (
        patch("perplexity_cli.query_runner.TokenManager", return_value=Mock(), autospec=True),
        patch(
            "perplexity_cli.query_runner.load_token_optional",
            return_value=("token-123", None),
            autospec=True,
        ),
        patch(
            "perplexity_cli.query_runner.resolve_attachment_urls",
            return_value=["https://s3/file"],
            autospec=True,
        ),
        patch("perplexity_cli.query_runner.PerplexityAPI", return_value=mock_api, autospec=True),
        patch(
            "perplexity_cli.query_runner.build_final_query",
            return_value="final query",
            autospec=True,
        ),
        patch("perplexity_cli.query_runner.stream_query_response", autospec=True) as mock_stream,
    ):
        run_query_command(
            ctx_obj={"debug": False},
            query_text="What is Python?",
            options=_default_options(
                strip_references=True,
                stream=True,
                model_preference="sonar-pro",
            ),
        )

    mock_stream.assert_called_once()
    # Second arg is now a QueryInput object
    query_input_arg = mock_stream.call_args.args[1]
    assert query_input_arg == QueryInput(
        query="final query",
        attachment_urls=["https://s3/file"],
        model_preference="sonar-pro",
    )
    # Third arg is the structural render context, fourth is TraceContext
    render_arg = mock_stream.call_args.args[2]
    assert (render_arg.options.output_format, render_arg.options.strip_references) == (
        "plain",
        True,
    )
    trace_arg = mock_stream.call_args.args[3]
    assert (mock_stream.call_args.args[0] is mock_api, isinstance(trace_arg, TraceContext)) == (
        True,
        True,
    )


def test_run_query_command_reports_upstream_schema_error(capsys):
    """Upstream schema failures map to a clean exit and message."""
    mock_api = _make_api_mock()
    mock_api.get_complete_answer.side_effect = UpstreamSchemaError("bad payload")

    with (
        patch("perplexity_cli.query_runner.TokenManager", return_value=Mock(), autospec=True),
        patch(
            "perplexity_cli.query_runner.load_token_optional",
            return_value=("token-123", None),
            autospec=True,
        ),
        patch(
            "perplexity_cli.query_runner.resolve_attachment_urls", return_value=[], autospec=True
        ),
        patch("perplexity_cli.query_runner.PerplexityAPI", return_value=mock_api, autospec=True),
        patch(
            "perplexity_cli.query_runner.build_final_query",
            return_value="final query",
            autospec=True,
        ),
    ):
        with pytest.raises(SystemExit) as exc_info:
            run_query_command(
                ctx_obj={"debug": False},
                query_text="What is Python?",
                options=_default_options(),
            )

    captured = capsys.readouterr()
    assert exc_info.value.code == 7
    assert "Error: bad payload" in captured.err


def test_parse_request_param_overrides_parses_multiple_values():
    """Repeated ``key=value`` overrides are parsed into a request mapping."""
    parsed = parse_request_param_overrides(("workflow_key=deep_research", "search_mode=research"))

    assert parsed == {
        "workflow_key": "deep_research",
        "search_mode": "research",
    }


def test_parse_request_param_overrides_rejects_duplicates():
    """Duplicate override keys fail fast with a clear error."""
    with pytest.raises(ValueError, match="Duplicate request parameter override"):
        parse_request_param_overrides(("workflow_key=deep_research", "workflow_key=wide_research"))


def test_parse_request_param_overrides_rejects_invalid_shape():
    """Malformed overrides must use ``key=value`` format."""
    with pytest.raises(ValueError, match="key=value"):
        parse_request_param_overrides(("workflow_key",))


def test_run_query_command_passes_request_param_overrides_to_api():
    """Batch queries pass parsed request overrides to the API layer."""
    answer = Answer(text="Test answer", references=[])
    mock_api = _make_api_mock(answer)

    with (
        patch("perplexity_cli.query_runner.TokenManager", return_value=Mock(), autospec=True),
        patch(
            "perplexity_cli.query_runner.load_token_optional",
            return_value=("token-123", None),
            autospec=True,
        ),
        patch(
            "perplexity_cli.query_runner.resolve_attachment_urls", return_value=[], autospec=True
        ),
        patch("perplexity_cli.query_runner.PerplexityAPI", return_value=mock_api, autospec=True),
        patch(
            "perplexity_cli.query_runner.build_final_query",
            return_value="final query",
            autospec=True,
        ),
    ):
        run_query_command(
            ctx_obj={"debug": False},
            query_text="What is Python?",
            options=_default_options(
                request_param_overrides=("workflow_key=deep_research", "search_mode=research"),
            ),
        )

    mock_api.get_complete_answer.assert_called_once_with(
        "final query",
        extra_params=([], None, {"workflow_key": "deep_research", "search_mode": "research"}),
    )


def test_run_query_command_json_includes_requested_schema(capsys):
    """JSON command orchestration carries the schema flag through rendering."""
    mock_api = _make_api_mock(Answer(text="Test answer", references=[]))

    with (
        patch("perplexity_cli.query_runner.TokenManager", return_value=Mock(), autospec=True),
        patch(
            "perplexity_cli.query_runner.load_token_optional",
            return_value=("token-123", None),
            autospec=True,
        ),
        patch(
            "perplexity_cli.query_runner.resolve_attachment_urls", return_value=[], autospec=True
        ),
        patch("perplexity_cli.query_runner.PerplexityAPI", return_value=mock_api, autospec=True),
        patch(
            "perplexity_cli.query_runner.build_final_query",
            return_value="final query",
            autospec=True,
        ),
    ):
        run_query_command(
            ctx_obj={"json": True, "schema": True},
            query_text="What is Python?",
            options=_default_options(),
        )

    payload = json.loads(capsys.readouterr().out)
    assert "$schema" in payload


def test_run_query_command_keyboard_interrupt_json_mode(capsys):
    """KeyboardInterrupt in json mode delegates to the json error handler."""
    mock_api = _make_api_mock()
    mock_api.get_complete_answer.side_effect = KeyboardInterrupt()

    with (
        patch("perplexity_cli.query_runner.TokenManager", return_value=Mock(), autospec=True),
        patch(
            "perplexity_cli.query_runner.load_token_optional",
            return_value=("token-123", None),
            autospec=True,
        ),
        patch(
            "perplexity_cli.query_runner.resolve_attachment_urls", return_value=[], autospec=True
        ),
        patch("perplexity_cli.query_runner.PerplexityAPI", return_value=mock_api, autospec=True),
        patch(
            "perplexity_cli.query_runner.build_final_query",
            return_value="final query",
            autospec=True,
        ),
    ):
        with pytest.raises(SystemExit) as exc_info:
            run_query_command(
                ctx_obj={"json": True},
                query_text="What is Python?",
                options=_default_options(output_format=None),
            )

    assert exc_info.value.code == 130
