"""Tests for logging utilities."""

from __future__ import annotations

import io
import locale
import logging
import re
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from perplexity_cli.utils.logging import (
    DynamicStderrHandler,
    JSONLogFormatter,
    enable_structured_logging,
    get_logger,
    redact_mapping_keys,
    redact_path,
    redact_response_text,
    redact_text,
    redact_url,
    setup_logging,
)

_CONSOLE_LINE_FORMAT = (
    r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
    r" - perplexity_cli - WARNING - boom\n"
)


@contextmanager
def _non_utf8_locale() -> Iterator[None]:
    """Force a non-UTF-8 preferred encoding so explicit encodings are distinguished."""
    previous = locale.setlocale(locale.LC_CTYPE)
    locale.setlocale(locale.LC_CTYPE, "C")
    try:
        yield
    finally:
        locale.setlocale(locale.LC_CTYPE, previous)


def _make_record(message: str = "hello") -> logging.LogRecord:
    """Create a minimal log record for direct handler emission."""
    return logging.LogRecord(
        name="perplexity_cli",
        level=logging.WARNING,
        pathname="test.py",
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


class TestLoggingSetup:
    """Test logging setup and configuration."""

    def test_setup_logging_default_level(self):
        """Test logging setup with default level."""
        logger = setup_logging()
        assert logger.level == logging.WARNING

    def test_setup_logging_verbose(self):
        """Test logging setup with verbose flag."""
        logger = setup_logging(verbosity="info")
        assert logger.level == logging.INFO

    def test_setup_logging_debug(self):
        """Test logging setup with debug flag."""
        logger = setup_logging(verbosity="debug")
        assert logger.level == logging.DEBUG

    def test_setup_logging_with_file(self):
        """Test logging setup with log file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            logger = setup_logging(log_file=log_file)
            assert logger.level == logging.WARNING
            # File handler is added, but file is created when first log message is written
            # Log something to ensure file is created
            logger.info("Test message")
            assert log_file.exists() is True

    def test_get_logger(self):
        """Test getting logger instance."""
        logger = get_logger()
        assert isinstance(logger, logging.Logger)
        assert logger.name == "perplexity_cli"

    def test_get_logger_with_name(self):
        """Test getting logger with custom name."""
        logger = get_logger("test_module")
        assert logger.name == "perplexity_cli.test_module"


class TestLogRedaction:
    """Test logging redaction helpers."""

    def test_redact_path_keeps_only_filename(self):
        assert redact_path("/Users/example/secrets/token.json") == "<redacted>/token.json"

    def test_redact_text_hides_content(self):
        redacted = redact_text("very sensitive query text")
        assert "sensitive" not in redacted
        assert redacted.startswith("<redacted:")

    def test_redact_url_hides_path_and_query(self):
        redacted = redact_url("https://example.com/secret/path?token=abc")
        assert redacted == "https://example.com/<redacted>"

    def test_redact_mapping_keys_hides_cookie_names(self):
        redacted = redact_mapping_keys({"cf_clearance": "x", "csrftoken": "y"})
        assert redacted == "<redacted:2 keys>"

    def test_redact_response_text_hides_body(self):
        redacted = redact_response_text('{"token":"secret"}')
        assert "secret" not in redacted

    def test_redact_path_none(self):
        """Return '<none>' for None input."""
        assert redact_path(None) == "<none>"

    def test_redact_path_no_parts(self):
        """Return '<path>' for an empty-string path."""
        assert redact_path("") == "<path>"

    def test_redact_path_no_name(self):
        """Return '<redacted-path>' when path has parts but no name (root)."""
        assert redact_path("/") == "<redacted-path>"

    def test_redact_text_falsy(self):
        """Return '<empty>' for empty or None text."""
        assert redact_text(None) == "<empty>"
        assert redact_text("") == "<empty>"

    def test_redact_url_falsy(self):
        """Return '<empty-url>' for empty or None URL."""
        assert redact_url(None) == "<empty-url>"
        assert redact_url("") == "<empty-url>"

    def test_redact_url_no_match(self):
        """Return '<redacted-url>' for non-HTTP URLs."""
        assert redact_url("ftp://example.com/file") == "<redacted-url>"

    def test_redact_mapping_keys_falsy(self):
        """Return '<none>' for None or empty mapping."""
        assert redact_mapping_keys(None) == "<none>"
        assert redact_mapping_keys({}) == "<none>"


class TestDynamicStderrHandler:
    """Test DynamicStderrHandler edge cases."""

    def test_emit_reraises_recursion_error(self):
        """RecursionError must propagate without being swallowed."""
        handler = DynamicStderrHandler()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        with patch.object(handler, "format", side_effect=RecursionError):
            import pytest

            with pytest.raises(RecursionError):
                handler.emit(record)

    def test_emit_handles_type_error(self):
        handler = DynamicStderrHandler()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        with (
            patch.object(handler, "format", side_effect=TypeError("boom")),
            patch.object(handler, "handleError") as mock_handle,
        ):
            handler.emit(record)
            mock_handle.assert_called_once_with(record)

    def test_flush_without_lock(self):
        """Flush works when lock is None."""
        handler = DynamicStderrHandler()
        handler.lock = None
        # Should not raise
        handler.flush()

    def test_flush_current_stderr_value_error(self):
        """ValueError from stderr.flush is silently caught."""
        handler = DynamicStderrHandler()
        mock_stderr = type(
            "FakeStderr",
            (),
            {"flush": staticmethod(lambda: (_ for _ in ()).throw(ValueError("closed")))},
        )()
        with patch("sys.stderr", mock_stderr):
            # Should not raise
            handler._flush_current_stderr()


class TestEnableStructuredLogging:
    """Test enable_structured_logging function."""

    def test_sets_json_formatter_on_dynamic_handler(self):
        """JSON formatter is applied to DynamicStderrHandler instances."""
        logger = setup_logging()
        enable_structured_logging(trace_id="abc-123")
        for h in logger.handlers:
            if isinstance(h, DynamicStderrHandler):
                assert isinstance(h.formatter, JSONLogFormatter)
                assert h.formatter.trace_id == "abc-123"


class TestDynamicStderrHandlerEmission:
    """Test that emit writes the formatted message plus terminator to stderr."""

    def test_emit_writes_message_and_terminator_to_current_stderr(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """emit writes '<message>\\n' to whichever stream sys.stderr holds."""
        buffer = io.StringIO()
        monkeypatch.setattr(sys, "stderr", buffer)

        DynamicStderrHandler().emit(_make_record("hello"))

        assert buffer.getvalue() == "hello\n"


class TestSetupLoggingVerbosity:
    """Test verbosity handling in setup_logging."""

    def test_unknown_verbosity_falls_back_to_warning(self):
        """Unrecognised verbosity values configure WARNING, not an error."""
        logger = setup_logging(verbosity="not-a-level")
        assert logger.level == logging.WARNING


class TestSetupLoggingConsoleFormat:
    """Test the exact rendered console line produced by setup_logging."""

    def test_console_output_matches_configured_format(self, monkeypatch: pytest.MonkeyPatch):
        """A warning renders as 'asctime - name - LEVELNAME - message'."""
        buffer = io.StringIO()
        monkeypatch.setattr(sys, "stderr", buffer)

        logger = setup_logging(verbosity="warning")
        logger.warning("boom")

        assert re.fullmatch(_CONSOLE_LINE_FORMAT, buffer.getvalue())


class TestSetupLoggingFileHandler:
    """Test file-handler creation in setup_logging."""

    def test_log_file_parent_directories_are_created(self, tmp_path: Path):
        """setup_logging creates every missing ancestor of the log file."""
        log_file = tmp_path / "logs" / "deep" / "app.log"

        logger = setup_logging(log_file=log_file)
        _close_file_handlers(logger)

        assert log_file.exists()

    def test_log_file_content_is_utf8_encoded(self, tmp_path: Path):
        """Non-ASCII messages reach the log file as UTF-8 under any locale."""
        log_file = tmp_path / "app.log"
        with _non_utf8_locale():
            logger = setup_logging(log_file=log_file)
            logger.warning("café")
            for handler in logger.handlers:
                handler.flush()

        assert b"caf\xc3\xa9" in log_file.read_bytes()


def _close_file_handlers(logger: logging.Logger) -> None:
    """Close any FileHandlers owned by the logger so temp files are released."""
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler):
            handler.close()


class TestRedactionPreviewLengths:
    """Test exact redaction preview lengths."""

    def test_redact_response_text_keeps_zero_char_preview(self):
        """HTTP response text never leaks even a preview of its length."""
        assert redact_response_text("abc") == "<redacted:0 chars>"


def test_logging_contracts_module_re_exports_protocols() -> None:
    """The logging contracts shim re-exports the facade protocols identically."""
    from perplexity_cli.utils.logging import LoggerFactory, RedactionAgent
    from perplexity_cli.utils.logging.contracts import (
        LoggerFactory as ContractsLoggerFactory,
    )
    from perplexity_cli.utils.logging.contracts import (
        RedactionAgent as ContractsRedactionAgent,
    )

    assert ContractsLoggerFactory is LoggerFactory
    assert ContractsRedactionAgent is RedactionAgent
