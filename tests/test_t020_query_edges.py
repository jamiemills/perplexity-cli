"""Focused edge-boundary tests for query runner orchestration."""

import os
from unittest.mock import Mock

import pytest

from perplexity_cli.api.models import Answer
from perplexity_cli.auth.models import AuthContext
from perplexity_cli.query_runner import (
    _handle_broken_pipe,
    _handle_query_error,
    _QueryOutputOptionsData,
    _QueryRenderContextData,
    build_final_query,
    get_query_formatter,
    parse_request_param_overrides,
    render_complete_answer,
    resolve_attachment_urls,
)
from tests.helpers.query_deps import patch_query_deps


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
    """A path-like query triggers resolution even without an attachment flag."""
    resolver = Mock(return_value=["https://file.test/one"])
    monkeypatch.setattr("perplexity_cli.query_runner._resolve_and_upload", resolver)

    result = resolve_attachment_urls("Summarise ./one.txt", (), AuthContext(token="token"))

    assert result == ["https://file.test/one"]
    resolver.assert_called_once()


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
