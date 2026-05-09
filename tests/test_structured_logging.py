"""Tests for structured JSON logging, quiet mode, and HTTP error classification."""

import json
import logging

from perplexity_cli.envelope import ErrorCode
from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError, SimpleRequest, SimpleResponse
from perplexity_cli.utils.http_errors import classify_http_error, classify_network_error
from perplexity_cli.utils.logging import (
    DynamicStderrHandler,
    JSONLogFormatter,
    configure_quiet_mode,
)


def _make_log_record(message: str = "test message", level: int = logging.INFO) -> logging.LogRecord:
    """Create a log record for testing."""
    return logging.LogRecord(
        name="perplexity_cli",
        level=level,
        pathname="test.py",
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def _make_http_error(status_code: int) -> PerplexityHTTPStatusError:
    """Create a PerplexityHTTPStatusError with the given status code."""
    request = SimpleRequest(method="GET", url="https://example.com")
    response = SimpleResponse(
        status_code=status_code,
        headers={},
        text="error",
        request=request,
    )
    return PerplexityHTTPStatusError(
        f"HTTP {status_code}",
        request=request,
        response=response,
    )


class TestJSONLogFormatter:
    """Test structured JSON log formatting."""

    def test_formats_as_json(self):
        """Output is valid JSON."""
        formatter = JSONLogFormatter()
        record = _make_log_record()
        result = formatter.format(record)
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_contains_ts(self):
        """JSON output has 'ts' field."""
        formatter = JSONLogFormatter()
        record = _make_log_record()
        parsed = json.loads(formatter.format(record))
        assert "ts" in parsed

    def test_contains_level(self):
        """JSON output has 'level' field."""
        formatter = JSONLogFormatter()
        record = _make_log_record()
        parsed = json.loads(formatter.format(record))
        assert parsed["level"] == "INFO"

    def test_contains_message(self):
        """JSON output has 'message' field."""
        formatter = JSONLogFormatter()
        record = _make_log_record("hello world")
        parsed = json.loads(formatter.format(record))
        assert parsed["message"] == "hello world"

    def test_contains_trace_id(self):
        """JSON output has 'trace_id' when provided."""
        formatter = JSONLogFormatter(trace_id="abc-123")
        record = _make_log_record()
        parsed = json.loads(formatter.format(record))
        assert parsed["trace_id"] == "abc-123"

    def test_no_trace_id_when_not_provided(self):
        """JSON output has no 'trace_id' when not provided."""
        formatter = JSONLogFormatter()
        record = _make_log_record()
        parsed = json.loads(formatter.format(record))
        assert "trace_id" not in parsed


class TestQuietMode:
    """Test quiet mode suppresses stderr."""

    def test_configure_quiet_removes_stderr_handler(self):
        """After configure_quiet_mode, no DynamicStderrHandler remains."""
        logger = logging.getLogger("test_quiet_mode")
        logger.handlers.clear()
        logger.addHandler(DynamicStderrHandler())
        logger.addHandler(logging.FileHandler("/dev/null"))

        configure_quiet_mode(logger)

        stderr_handlers = [h for h in logger.handlers if isinstance(h, DynamicStderrHandler)]
        assert len(stderr_handlers) == 0
        # File handler should remain
        file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 1


class TestClassifyHttpError:
    """Test structured HTTP error classification."""

    def test_401_returns_auth_required(self):
        """401 maps to authentication_required."""
        error = _make_http_error(401)
        code, message, fix = classify_http_error(error)
        assert code == ErrorCode.authentication_required
        assert "Authentication" in message
        assert fix is not None

    def test_403_returns_permission_denied(self):
        """403 maps to permission_denied."""
        error = _make_http_error(403)
        code, _, fix = classify_http_error(error)
        assert code == ErrorCode.permission_denied
        assert fix is None

    def test_429_returns_rate_limited(self):
        """429 maps to rate_limited."""
        error = _make_http_error(429)
        code, _message, _fix = classify_http_error(error)
        assert code == ErrorCode.rate_limited

    def test_500_returns_network_error(self):
        """5xx maps to network_error."""
        error = _make_http_error(500)
        code, message, _fix = classify_http_error(error)
        assert code == ErrorCode.network_error
        assert "Server error" in message

    def test_unknown_status_returns_network_error(self):
        """Unknown status codes map to network_error."""
        error = _make_http_error(418)
        code, message, _fix = classify_http_error(error)
        assert code == ErrorCode.network_error
        assert "418" in message


class TestClassifyNetworkError:
    """Test structured network error classification."""

    def test_returns_network_error(self):
        """Network errors map to network_error."""
        from perplexity_cli.utils.exceptions import PerplexityRequestError

        error = PerplexityRequestError("connection failed")
        code, _, fix = classify_network_error(error)
        assert code == ErrorCode.network_error
        assert fix is not None
