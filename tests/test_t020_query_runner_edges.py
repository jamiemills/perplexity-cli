"""Additional public-boundary mutation tests for query orchestration."""

import json
import logging
import os
from unittest.mock import ANY, Mock, patch

import pytest

from perplexity_cli import query_deps
from perplexity_cli.api.models import Answer, QueryInput, TraceContext, WebResult
from perplexity_cli.auth.models import AuthContext
from perplexity_cli.query_runner import (
    _build_json_envelope,
    _detect_execution_environment,
    _do_s3_upload,
    _handle_broken_pipe,
    _handle_keyboard_interrupt,
    _handle_query_error,
    _has_potential_file_references,
    _load_and_upload_attachments,
    _QueryOutputOptionsData,
    _QueryRenderContextData,
    _read_ctx_options,
    _read_query_from_stdin,
    _resolve_and_upload,
    build_final_query,
    get_query_formatter,
    log_query_debug_context,
    parse_request_param_overrides,
    render_complete_answer,
    resolve_attachment_urls,
    run_query_command,
)
from perplexity_cli.query_streaming import _run_stream_loop
from perplexity_cli.utils.attachment_models import FileAttachment
from perplexity_cli.utils.exceptions import (
    AttachmentError,
    AttachmentUploadError,
)
from tests.helpers.query_deps import patch_query_deps, patched_dep
from tests.test_query_runner import _default_options, _make_api_mock


def test_build_final_query_preserves_query_when_style_is_unconfigured():
    """An absent style does not alter the user's query."""
    with patched_dep("StyleManager", Mock(autospec=True)) as mock_sm_class:
        mock_sm_class.return_value.load_style.return_value = None

        result = build_final_query("What is Python?")

    assert result == "What is Python?"


def test_get_query_formatter_forwards_explicit_format(monkeypatch):
    """An explicit formatter name is resolved without replacing it with the default."""
    formatter = Mock()
    get_formatter = Mock(return_value=formatter)
    patch_query_deps(monkeypatch, get_formatter=get_formatter)

    resolved, result = get_query_formatter("markdown")

    assert (resolved, result) == ("markdown", formatter)
    get_formatter.assert_called_once_with("markdown")


def test_read_ctx_options_defaults_both_boolean_flags_to_false():
    """Missing Click flags are false rather than null or truthy."""
    assert _read_ctx_options({"timeout": None}) == (False, None, False)


def test_detect_execution_environment_recognises_both_uvx_markers(monkeypatch):
    """Either supported uvx environment marker selects the uvx branch."""
    monkeypatch.delenv("UV_ACTIVE", raising=False)
    monkeypatch.setenv("UVXENV", "1")
    assert _detect_execution_environment() == "uvx"
    monkeypatch.delenv("UVXENV")
    monkeypatch.setenv("UV_ACTIVE", "1")
    assert _detect_execution_environment() == "uvx"


def test_log_query_debug_context_redacts_each_sensitive_debug_value(monkeypatch):
    """Debug logging passes the real sensitive values through redactors."""
    logger = Mock()
    logger.isEnabledFor.return_value = True
    token_path = Mock()
    token_path.exists.return_value = True
    redact_path = Mock(return_value="PATH_SENTINEL")
    redact_text = Mock(return_value="TEXT_SENTINEL")
    patch_query_deps(monkeypatch, get_logger=lambda: logger)
    patch_query_deps(monkeypatch, get_config_paths=lambda: Mock(token_path=token_path))
    patch_query_deps(monkeypatch, get_save_cookies_enabled=lambda: False)
    patch_query_deps(monkeypatch, redact_path=redact_path, redact_text=redact_text)
    monkeypatch.setattr("perplexity_cli.query_runner.socket.gethostname", lambda: "host")

    log_query_debug_context("private query", "plain", "batch")

    redact_path.assert_called_once_with(token_path)
    redact_text.assert_called_once_with("private query")


def test_log_query_debug_context_preserves_batch_mode_value(monkeypatch):
    """Debug context retains the structured batch-mode value for diagnostics."""
    logger = Mock()
    logger.isEnabledFor.return_value = True
    patch_query_deps(monkeypatch, get_logger=lambda: logger)
    patch_query_deps(
        monkeypatch, get_config_paths=lambda: Mock(token_path=Mock(exists=lambda: False))
    )
    patch_query_deps(monkeypatch, get_save_cookies_enabled=lambda: False)
    patch_query_deps(monkeypatch, redact_path=lambda value: "path")
    patch_query_deps(monkeypatch, redact_text=lambda value: "text")
    monkeypatch.setattr("perplexity_cli.query_runner.socket.gethostname", lambda: "host")

    log_query_debug_context("query", "plain", "batch")

    assert logger.debug.call_args_list[-1].args[1:] == ("text", "plain", "batch")


def test_has_potential_file_references_detects_windows_paths():
    """Windows separators are treated as file references even without attachments."""
    assert _has_potential_file_references(r"C:\\docs\\report.txt", [])


def test_load_and_upload_attachments_preserves_cookies_for_upload(monkeypatch):
    """The uploader receives browser cookies needed by the upload boundary."""
    attachments = [FileAttachment(filename="one.txt", content_type="text/plain", data="data")]
    loader = Mock(return_value=attachments)
    upload = Mock(return_value=["https://file.test/one"])
    patch_query_deps(monkeypatch, load_attachments=loader)
    monkeypatch.setattr("perplexity_cli.query_runner._do_s3_upload", upload)
    cookies = {"session": "cookie-sentinel"}

    result = _load_and_upload_attachments(["one.txt"], "token", cookies, Mock())

    assert result == ["https://file.test/one"]
    assert upload.call_args.args[:3] == (attachments, "token", cookies)


def test_query_dependency_public_seam_reports_complete_unbound_guidance(monkeypatch):
    """The dependency seam fails with actionable composition-root guidance."""
    monkeypatch.setattr(query_deps, "_deps", None)

    with pytest.raises(RuntimeError) as exc_info:
        query_deps.require_query_deps()

    assert str(exc_info.value) == (
        "query dependencies are not bound; the composition root "
        "(perplexity_cli.cli) must call bind_query_deps()"
    )


def test_query_dependency_placeholders_keep_their_failure_contract():
    """Unconfigured collaborators fail loudly instead of becoming no-ops."""
    container = query_deps.make_query_deps()

    for field in query_deps.fields(query_deps.QueryDeps):
        with pytest.raises(AssertionError) as exc_info:
            getattr(container, field.name)()
        assert str(exc_info.value) == "placeholder collaborator must not be invoked"


def test_query_dependency_override_uses_bound_base_and_applies_overrides(monkeypatch):
    """Overrides replace the bound container while returning its previous value."""
    original = query_deps.make_query_deps()
    monkeypatch.setattr(query_deps, "_deps", original)
    replacement_value = Mock()

    previous = query_deps.override_query_deps(None, PerplexityAPI=replacement_value)

    assert previous is original
    assert query_deps.require_query_deps().PerplexityAPI is replacement_value


def test_build_final_query_redacts_the_applied_style(monkeypatch):
    """Applied style prompts are redacted before entering debug logs."""
    logger = Mock()
    redact = Mock(return_value="STYLE_SENTINEL")
    style_manager = Mock(return_value=Mock(load_style=Mock(return_value="private style")))
    patch_query_deps(
        monkeypatch, get_logger=lambda: logger, redact_text=redact, StyleManager=style_manager
    )

    assert build_final_query("query") == "query\n\nprivate style"
    redact.assert_called_once_with("private style")


def test_read_ctx_options_defaults_missing_values_to_false():
    """Missing context flags resolve to false regardless of equivalent falsey defaults."""
    assert _read_ctx_options({}) == (False, None, False)
    assert _read_ctx_options({"json": None, "schema": None}) == (False, None, False)


def test_run_query_command_preserves_trace_uuid_and_human_error_mode(monkeypatch):
    """The runner creates a UUID trace and passes the documented human mode."""
    logger = Mock()
    logger.isEnabledFor.return_value = False
    trace_uuid = "trace-sentinel"
    uuid_factory = Mock(return_value=trace_uuid)
    error_handler = Mock(side_effect=SystemExit(1))
    patch_query_deps(monkeypatch, get_logger=lambda: logger, handle_error=error_handler)
    monkeypatch.setattr("perplexity_cli.query_runner.uuid.uuid4", uuid_factory)
    monkeypatch.setattr(
        "perplexity_cli.query_runner.resolve_attachment_urls", Mock(side_effect=ValueError("bad"))
    )

    with pytest.raises(SystemExit):
        run_query_command(None, "query", _default_options())

    uuid_factory.assert_called_once_with()
    assert error_handler.call_args.kwargs == {"output_format": "human"}
    assert error_handler.call_args.args[1] == "pxcli query --json"


def test_run_query_command_forwards_cookies_to_attachment_boundary(monkeypatch):
    """Authentication cookies survive the runner-to-attachment boundary."""
    logger = Mock()
    logger.isEnabledFor.return_value = False
    cookies = {"session": "cookie-sentinel"}
    resolver = Mock(return_value=[])
    api = _make_api_mock(Answer(text="answer", references=[]))
    with (
        patched_dep("TokenManager", Mock(return_value=Mock())),
        patched_dep("load_token_optional", Mock(return_value=("token", cookies))),
        patched_dep("PerplexityAPI", Mock(return_value=api)),
        patch("perplexity_cli.query_runner.resolve_attachment_urls", resolver),
    ):
        run_query_command(None, "query", _default_options())

    resolver.assert_called_once_with("query", (), AuthContext(token="token", cookies=cookies))


def test_run_query_command_logs_stream_start_and_passes_human_mode(monkeypatch):
    """Streaming execution emits its stable operational log event."""
    logger = Mock()
    logger.isEnabledFor.return_value = False
    api = _make_api_mock()
    stream = Mock()
    with (
        patched_dep("TokenManager", Mock(return_value=Mock())),
        patched_dep("load_token_optional", Mock(return_value=("token", None))),
        patched_dep("PerplexityAPI", Mock(return_value=api)),
        patch("perplexity_cli.query_runner.resolve_attachment_urls", return_value=[]),
        patch("perplexity_cli.query_runner.stream_query_response", stream),
        patch("perplexity_cli.query_runner.log_query_debug_context"),
    ):
        patch_query_deps(monkeypatch, get_logger=lambda: logger)
        run_query_command(None, "query", _default_options(stream=True))

    logger.info.assert_called_once_with("Streaming query response")


def test_query_runner_stream_loop_keeps_references_from_final_message_only():
    """Intermediate references are not exposed as the completed answer's sources."""
    early = [WebResult(name="early", url="https://early", snippet="early")]
    api = Mock()
    api.submit_query.return_value = iter(
        [
            Mock(
                extract_answer_text=Mock(return_value="answer"),
                status="COMPLETE",
                final_sse_message=False,
                web_results=early,
            )
        ]
    )

    assert _run_stream_loop(api, QueryInput(query="query"), None) == ("answer", [])


def test_query_runner_legacy_reads_delegate_only_known_seam_names(monkeypatch):
    """PEP 562 compatibility reads resolve known names and reject unknown ones."""
    from perplexity_cli import query_runner

    sentinel = Mock()
    container = query_deps.make_query_deps(get_logger=sentinel)
    monkeypatch.setattr(query_deps, "_deps", container)
    monkeypatch.delattr(query_runner, "get_logger", raising=False)

    assert query_runner.get_logger is sentinel
    with pytest.raises(AttributeError):
        query_runner.__getattr__("not_a_dependency")


def test_log_query_debug_context_is_noop_when_debug_is_disabled(monkeypatch):
    """Non-debug invocations do not resolve or log diagnostic dependencies."""
    logger = Mock()
    logger.isEnabledFor.return_value = False
    get_logger = Mock(return_value=logger)
    config_paths = Mock()
    patch_query_deps(monkeypatch, get_logger=get_logger, get_config_paths=config_paths)

    log_query_debug_context("query", "plain", "batch")

    get_logger.assert_called_once_with()
    config_paths.assert_not_called()
    logger.debug.assert_not_called()


def test_build_json_envelope_uses_string_fallback_for_serialisation(monkeypatch):
    """JSON output explicitly supports stringifying non-standard values."""
    from perplexity_cli import query_runner

    dumps = Mock(wraps=json.dumps)
    monkeypatch.setattr(query_runner.json, "dumps", dumps)

    _build_json_envelope(Answer(text="Answer", references=[]), TraceContext(), "no_schema")

    assert dumps.call_args.kwargs["default"] is str


def test_resolve_attachment_urls_wraps_local_resolution_errors():
    """Attachment resolution exposes a stable domain error at the boundary."""
    with patch(
        "perplexity_cli.query_runner._resolve_and_upload",
        side_effect=FileNotFoundError("missing.txt"),
    ):
        with pytest.raises(AttachmentError, match="Failed to load attachments"):
            resolve_attachment_urls("Analyse ./missing.txt", (), AuthContext(token="token"))


def test_resolve_and_upload_returns_empty_without_resolved_files(monkeypatch):
    """A resolver returning no files skips authentication and upload work."""
    resolver = Mock(return_value=[])
    validator = Mock()
    loader = Mock()
    patch_query_deps(monkeypatch, resolve_file_arguments=resolver)
    monkeypatch.setattr("perplexity_cli.query_runner._require_auth_for_attachments", validator)
    monkeypatch.setattr("perplexity_cli.query_runner._load_and_upload_attachments", loader)

    result = _resolve_and_upload("No files", ["missing"], AuthContext(token=None), Mock())

    assert result == []
    resolver.assert_called_once_with(["No files"], attach_args=["missing"])
    validator.assert_not_called()
    loader.assert_not_called()


def test_read_query_from_stdin_returns_trimmed_input(monkeypatch):
    """The stdin sentinel reads and trims piped query input."""
    stdin = Mock(isatty=lambda: False, read=lambda: "  query text  \n")
    monkeypatch.setattr("perplexity_cli.query_runner.sys.stdin", stdin)

    assert _read_query_from_stdin("-") == "query text"


def test_read_query_from_stdin_rejects_empty_input(monkeypatch, capsys):
    """Empty piped input is rejected before any API dependency is used."""
    stdin = Mock(isatty=lambda: False, read=lambda: " \n")
    monkeypatch.setattr("perplexity_cli.query_runner.sys.stdin", stdin)

    with pytest.raises(SystemExit) as exc_info:
        _read_query_from_stdin("-")

    assert exc_info.value.code == 2
    assert capsys.readouterr().err == "Error: empty input from stdin.\n"


def test_read_query_from_stdin_rejects_terminal_stdin(monkeypatch, capsys):
    """The stdin sentinel gives a pipe hint when stdin is interactive."""
    monkeypatch.setattr("perplexity_cli.query_runner.sys.stdin", Mock(isatty=lambda: True))

    with pytest.raises(SystemExit) as exc_info:
        _read_query_from_stdin("-")

    assert exc_info.value.code == 2
    assert capsys.readouterr().err == "Error: stdin is a terminal; pipe input or provide a query.\n"


def test_read_query_from_stdin_passes_non_sentinel_without_reading(monkeypatch):
    """Ordinary query arguments bypass stdin entirely."""
    stdin = Mock()
    monkeypatch.setattr("perplexity_cli.query_runner.sys.stdin", stdin)

    assert _read_query_from_stdin("literal query") == "literal query"
    stdin.isatty.assert_not_called()
    stdin.read.assert_not_called()


def test_resolve_and_upload_logs_resolved_file_count(monkeypatch, tmp_path):
    """Attachment resolution logs the count before authentication and upload."""
    file_path = tmp_path / "one.txt"
    resolver = Mock(return_value=[file_path])
    validator = Mock(return_value="token")
    loader = Mock(return_value=[])
    logger = Mock()
    patch_query_deps(monkeypatch, resolve_file_arguments=resolver)
    monkeypatch.setattr("perplexity_cli.query_runner._require_auth_for_attachments", validator)
    monkeypatch.setattr("perplexity_cli.query_runner._load_and_upload_attachments", loader)

    assert _resolve_and_upload("query", ["one.txt"], AuthContext(token="raw"), logger) == []

    logger.debug.assert_called_once_with("Resolving attachments: found %s file(s)", 1)


def test_load_and_upload_attachments_loads_files_before_uploading(monkeypatch):
    """Loaded attachments are passed as one ordered batch to the uploader."""
    attachments = [
        FileAttachment(filename="one.txt", content_type="text/plain", data="b25l"),
        FileAttachment(filename="two.txt", content_type="text/plain", data="dHdv"),
    ]
    loader = Mock(return_value=attachments)
    uploader = Mock(return_value=["https://file.test/one", "https://file.test/two"])
    patch_query_deps(monkeypatch, load_attachments=loader)
    monkeypatch.setattr("perplexity_cli.query_runner._do_s3_upload", uploader)

    logger = Mock()
    result = _load_and_upload_attachments(["one", "two"], "token", None, logger)

    assert result == ["https://file.test/one", "https://file.test/two"]
    loader.assert_called_once_with(["one", "two"])
    uploader.assert_called_once_with(attachments, "token", None, uploader.call_args.args[3])
    assert logger.debug.call_args_list[0].args == (
        "Attachment loading complete: %s file(s) loaded",
        2,
    )
    assert logger.debug.call_args_list[1].args == (
        "  - %s (%s, %s bytes base64)",
        "<redacted>/one.txt",
        "text/plain",
        4,
    )
    assert logger.debug.call_args_list[2].args == (
        "  - %s (%s, %s bytes base64)",
        "<redacted>/two.txt",
        "text/plain",
        4,
    )


def test_do_s3_upload_propagates_upload_error_and_logs_exception(monkeypatch):
    """Uploader failures remain upload errors and are logged with traceback context."""
    attachment = FileAttachment(filename="one.txt", content_type="text/plain", data="dGVzdA==")
    uploader = Mock()
    uploader.upload_files.return_value = Mock()
    error = AttachmentUploadError("upload failed")
    patch_query_deps(monkeypatch, AttachmentUploader=Mock(return_value=uploader))
    patch_query_deps(monkeypatch, run_async=Mock(side_effect=error))
    logger = Mock()

    with pytest.raises(AttachmentUploadError, match="upload failed"):
        _do_s3_upload([attachment], "token", None, logger)

    logger.exception.assert_called_once_with("Attachment upload failed: %s", error)


def test_fetch_and_render_logs_answer_shape(monkeypatch):
    """Batch rendering logs the fetch operation and answer dimensions."""
    from perplexity_cli.query_runner import _fetch_and_render

    logger = Mock()
    patch_query_deps(monkeypatch, get_logger=lambda: logger)
    api = _make_api_mock(
        Answer(text="Answer", references=[WebResult(name="R", url="u", snippet="s")])
    )
    render = _QueryRenderContextData(
        formatter=Mock(),
        options=_QueryOutputOptionsData("plain", False, False, False),
    )
    render.formatter.format_complete.return_value = "formatted"

    _fetch_and_render(api, QueryInput(query="query"), render, TraceContext())

    assert logger.info.call_args.args == ("Fetching complete answer",)
    assert logger.debug.call_args_list[0].args == (
        "Received answer: %s characters, %s references",
        6,
        1,
    )


@pytest.mark.parametrize("raw", ("=value", "key=", "="))
def test_parse_request_param_overrides_rejects_empty_key_or_value(raw):
    """Overrides require both a non-empty key and a non-empty value."""
    with pytest.raises(ValueError, match="key=value"):
        parse_request_param_overrides((raw,))


def test_run_query_command_forwards_timeout_model_and_attachments():
    """The public runner boundary preserves timeout, model and attachment inputs."""
    mock_api = _make_api_mock(Answer(text="Answer", references=[]))
    attachments = ["https://file.test/one"]

    with (
        patched_dep("TokenManager", Mock(return_value=Mock())),
        patched_dep("load_token_optional", Mock(return_value=("token-123", None))),
        patch(
            "perplexity_cli.query_runner.resolve_attachment_urls", return_value=attachments
        ) as resolve,
        patched_dep("PerplexityAPI", Mock(return_value=mock_api)) as api_class,
        patch("perplexity_cli.query_runner.build_final_query", return_value="final query"),
    ):
        run_query_command(
            ctx_obj={"timeout": 17},
            query_text="What is Python?",
            options=_default_options(model_preference="sonar-pro", attachments=("one.txt",)),
        )

    resolve.assert_called_once_with("What is Python?", ("one.txt",), AuthContext(token="token-123"))
    api_class.assert_called_once_with("token-123", None, timeout=17)
    mock_api.get_complete_answer.assert_called_once_with(
        "final query",
        extra_params=(attachments, "sonar-pro", {}),
    )


def test_keyboard_interrupt_human_mode_writes_human_error(capsys):
    """Human-mode interruption writes the terminal message and exits 130."""
    logger = Mock()
    with pytest.raises(SystemExit) as exc_info:
        _handle_keyboard_interrupt("human", logger)

    assert exc_info.value.code == 130
    assert capsys.readouterr().err == "\n[ERROR] Query interrupted.\n"
    logger.info.assert_called_once_with("Query interrupted by user")


def test_keyboard_interrupt_json_mode_uses_json_error_boundary(monkeypatch):
    """JSON interruptions are handed to the JSON error policy before exit."""
    handler = Mock(side_effect=SystemExit(130))
    patch_query_deps(monkeypatch, handle_error=handler)

    with pytest.raises(SystemExit) as exc_info:
        _handle_keyboard_interrupt("json", logging.getLogger("test-query"))

    assert exc_info.value.code == 130
    handler.assert_called_once()
    assert isinstance(handler.call_args.args[0], KeyboardInterrupt)
    assert handler.call_args.kwargs == {"output_format": "json"}


def test_broken_pipe_handles_devnull_failure_and_still_exits(monkeypatch):
    """Failure to redirect stdout does not change the broken-pipe exit code."""
    open_mock = Mock(side_effect=OSError("no devnull"))
    logger = Mock()
    patch_query_deps(monkeypatch, get_logger=lambda: logger)
    monkeypatch.setattr("perplexity_cli.query_runner.os.open", open_mock)

    with pytest.raises(SystemExit) as exc_info:
        _handle_broken_pipe()

    assert exc_info.value.code == 1
    logger.debug.assert_called_once_with("Could not redirect stdout to devnull after broken pipe")


def test_query_deps_factory_and_override_boundaries_are_exercised(monkeypatch):
    """Included runner tests cover the dependency seam used by the query boundary."""
    container = query_deps.make_query_deps(PerplexityAPI=Mock())
    assert container.PerplexityAPI is not container.handle_error

    previous = query_deps.override_query_deps(monkeypatch, PerplexityAPI=container.PerplexityAPI)
    assert previous is not query_deps.require_query_deps()


def test_query_dependency_binding_round_trips_through_the_runner_seam(monkeypatch):
    """Binding and requiring dependencies preserve identity for composition."""
    container = query_deps.make_query_deps()
    monkeypatch.setattr(query_deps, "_deps", None)

    query_deps.bind_query_deps(container)

    assert query_deps.require_query_deps() is container


def test_broken_pipe_redirects_stdout_before_exiting(monkeypatch):
    """Broken-pipe handling redirects final interpreter flushes to devnull."""
    open_mock = Mock(return_value=41)
    dup_mock = Mock()
    monkeypatch.setattr("perplexity_cli.query_runner.os.open", open_mock)
    monkeypatch.setattr("perplexity_cli.query_runner.os.dup2", dup_mock)
    monkeypatch.setattr("perplexity_cli.query_runner.sys.stdout.fileno", lambda: 1)

    with pytest.raises(SystemExit) as exc_info:
        _handle_broken_pipe()

    assert exc_info.value.code == 1
    open_mock.assert_called_once_with(os.devnull, os.O_WRONLY)
    dup_mock.assert_called_once_with(41, 1)


def test_handle_query_error_passes_logger_to_interrupt_handler(monkeypatch):
    """The query error wrapper preserves its logger dependency on interruption."""
    logger = Mock()
    patch_query_deps(monkeypatch, get_logger=lambda: logger)
    interrupt = Mock(side_effect=SystemExit(130))
    monkeypatch.setattr("perplexity_cli.query_runner._handle_keyboard_interrupt", interrupt)

    with pytest.raises(SystemExit):
        _handle_query_error(lambda: (_ for _ in ()).throw(KeyboardInterrupt()), "human")

    interrupt.assert_called_once_with("human", logger)


def test_run_query_command_preserves_cookies_and_mode_log_contract(monkeypatch):
    """The public runner forwards cookies and the documented stream log context."""
    mock_api = _make_api_mock()
    logger = Mock()
    logger.isEnabledFor.return_value = False
    cookies = {"session": "cookie-sentinel"}
    debug = Mock()
    stream = Mock()
    with (
        patched_dep("TokenManager", Mock(return_value=Mock())),
        patched_dep("load_token_optional", Mock(return_value=("token", cookies))),
        patched_dep("get_logger", logger),
        patched_dep("PerplexityAPI", Mock(return_value=mock_api)),
        patch("perplexity_cli.query_runner.resolve_attachment_urls", return_value=[]),
        patch("perplexity_cli.query_runner.build_final_query", return_value="final"),
        patch("perplexity_cli.query_runner.log_query_debug_context", debug),
        patch("perplexity_cli.query_runner.stream_query_response", stream),
    ):
        run_query_command(None, "query", _default_options(stream=True))

    debug.assert_called_once_with("query", "plain", "stream")
    stream.assert_called_once()
    assert stream.call_args.args[1].query == "final"
    assert stream.call_args.args[1].request_params == {}
    assert mock_api is not None


def test_fetch_and_render_json_distinguishes_schema_selection(monkeypatch):
    """The JSON fetch boundary sends the exact schema selector to serialization."""
    from perplexity_cli.query_runner import _fetch_and_render

    api = _make_api_mock(Answer(text="answer", references=[]))
    render = _QueryRenderContextData(
        formatter=Mock(), options=_QueryOutputOptionsData("plain", False, True, False)
    )
    output = Mock()
    envelope = Mock(return_value="{}\n")
    monkeypatch.setattr("perplexity_cli.query_runner._write_stdout", output)
    monkeypatch.setattr("perplexity_cli.query_runner._build_json_envelope", envelope)
    patch_query_deps(monkeypatch, get_logger=lambda: Mock())

    _fetch_and_render(api, QueryInput(query="query"), render, TraceContext())

    envelope.assert_called_once_with(api.get_complete_answer.return_value, ANY, "no_schema")


def test_render_complete_answer_uses_rich_renderer_without_stdout(monkeypatch):
    """Rich output uses the formatter's direct renderer rather than text output."""
    formatter = Mock()
    output = Mock()
    monkeypatch.setattr("perplexity_cli.query_runner._write_stdout", output)
    answer = Answer(text="answer", references=[])
    render = _QueryRenderContextData(
        formatter=formatter,
        options=_QueryOutputOptionsData("rich", False, False, False),
    )

    render_complete_answer(answer, render)

    formatter.render_complete.assert_called_once_with(answer, strip_references=False)
    formatter.format_complete.assert_not_called()
    output.assert_not_called()


def test_parse_request_param_overrides_preserves_equals_in_value():
    """Only the first equals sign separates an override key from its value."""
    assert parse_request_param_overrides(("query=a=b",)) == {"query": "a=b"}


def test_resolve_attachment_urls_detects_file_reference_in_query(monkeypatch):
    """A path-like query triggers resolution even without an explicit attachment flag."""
    resolver = Mock(return_value=["https://file.test/one"])
    monkeypatch.setattr("perplexity_cli.query_runner._resolve_and_upload", resolver)

    result = resolve_attachment_urls("Summarise ./one.txt", (), AuthContext(token="token"))

    assert result == ["https://file.test/one"]
    resolver.assert_called_once()


def test_handle_query_error_routes_unexpected_errors_to_dependency_handler(monkeypatch):
    """Unexpected query failures are delegated with the selected output mode."""
    handler = Mock()
    patch_query_deps(monkeypatch, handle_error=handler)

    _handle_query_error(lambda: (_ for _ in ()).throw(ValueError("bad query")), "json")

    handler.assert_called_once()
    assert handler.call_args.args[0].args == ("bad query",)
    assert handler.call_args.kwargs == {"output_format": "json"}


def test_handle_query_error_routes_keyboard_interrupt(monkeypatch):
    """Keyboard interrupts use the dedicated interruption handler."""
    interrupt = Mock()
    monkeypatch.setattr("perplexity_cli.query_runner._handle_keyboard_interrupt", interrupt)

    def fail() -> None:
        raise KeyboardInterrupt

    _handle_query_error(fail, "human")

    interrupt.assert_called_once()
    assert interrupt.call_args.args[0] == "human"


def test_handle_query_error_routes_broken_pipe(monkeypatch):
    """Broken pipes use the quiet pipe handler rather than generic errors."""
    broken_pipe = Mock()
    monkeypatch.setattr("perplexity_cli.query_runner._handle_broken_pipe", broken_pipe)

    def fail() -> None:
        raise BrokenPipeError

    _handle_query_error(fail, "human")

    broken_pipe.assert_called_once_with()


def test_query_runner_legacy_readthrough_delegates_every_seam(monkeypatch):
    """Legacy module reads resolve to the exact bound collaborator values."""
    previous = query_deps.require_query_deps()
    values = {
        field.name: Mock(name=field.name) for field in query_deps.fields(query_deps.QueryDeps)
    }
    container = query_deps.make_query_deps(**values)
    try:
        query_deps.set_query_deps(container)

        from perplexity_cli import query_runner

        for field in query_deps.fields(query_deps.QueryDeps):
            assert getattr(query_runner, field.name) is values[field.name]

        with pytest.raises(AttributeError, match="no attribute 'not_a_seam'"):
            query_runner.__getattr__("not_a_seam")
    finally:
        query_deps.set_query_deps(previous)


def test_build_final_query_logs_redacted_style(monkeypatch):
    """Configured styles are logged through the redaction collaborator."""
    logger = Mock()
    patch_query_deps(monkeypatch, get_logger=lambda: logger)
    patch_query_deps(monkeypatch, redact_text=lambda value: "REDACTED_STYLE")
    style_manager = Mock()
    style_manager.return_value.load_style.return_value = "private style"
    patch_query_deps(monkeypatch, StyleManager=style_manager)

    assert build_final_query("query") == "query\n\nprivate style"
    logger.debug.assert_called_once_with("Applied style: %s", "REDACTED_STYLE")


def test_get_query_formatter_logs_invalid_format_with_value(monkeypatch):
    """Invalid formatter errors retain the requested format in diagnostics."""
    logger = Mock()
    patch_query_deps(monkeypatch, get_logger=lambda: logger)
    patch_query_deps(monkeypatch, get_formatter=Mock(side_effect=ValueError("bad")))

    with pytest.raises(ValueError):
        get_query_formatter("invalid")

    logger.exception.assert_called_once_with("Invalid formatter: %s", "invalid")
