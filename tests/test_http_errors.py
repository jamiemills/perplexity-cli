"""Tests for shared CLI error handling helpers."""

import logging
from typing import ClassVar

import pytest

from perplexity_cli.utils.http_errors import handle_unexpected_cli_error


def test_handle_unexpected_cli_error_prints_debug_hint(capsys):
    """Unexpected CLI helper includes the debug hint when requested."""
    logger = logging.getLogger("test-http-errors")

    with pytest.raises(SystemExit) as exc_info:
        try:
            raise RuntimeError("boom")
        except RuntimeError as error:
            handle_unexpected_cli_error(
                error,
                logger,
                message_tuple=("[ERROR] Failed.", "Unexpected test error", True),
            )

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "[ERROR] Failed." in captured.err
    assert "Run with --debug for more information." in captured.err


def test_handle_unexpected_cli_error_prints_traceback_in_debug_mode(capsys):
    """Unexpected CLI helper prints traceback details when debug is enabled."""
    logger = logging.getLogger("test-http-errors")

    with pytest.raises(SystemExit) as exc_info:
        try:
            raise RuntimeError("boom")
        except RuntimeError as error:
            handle_unexpected_cli_error(
                error,
                logger,
                debug_mode="debug",
                message_tuple=("[ERROR] Failed.", "Unexpected test error", True),
            )

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "Debug info:" in captured.err
    assert "RuntimeError: boom" in captured.err


def test_raise_http_status_error_missing_content() -> None:
    """A response without usable content falls back to an empty body."""
    from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError
    from perplexity_cli.utils.http_errors import raise_http_status_error

    class _ContentlessResponse:
        url = "https://example.com"
        status_code = 500
        headers: ClassVar[dict[str, str]] = {"x-test": "1"}

        @property
        def content(self) -> bytes:
            raise AttributeError("no content")

    with pytest.raises(PerplexityHTTPStatusError) as exc_info:
        raise_http_status_error(_ContentlessResponse(), method="GET")

    assert exc_info.value.response.text == ""
    assert exc_info.value.request.method == "GET"
    assert exc_info.value.response.headers == {"x-test": "1"}


def test_handle_http_error_real_body(capsys) -> None:
    """HTTP error handler prints the mapped message and exits 1."""
    from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError
    from perplexity_cli.utils.http_errors import handle_http_error

    logger = logging.getLogger("test-http-errors-real")

    class _Resp:
        status_code = 429

    error = PerplexityHTTPStatusError("Rate limit", request=None, response=_Resp())
    with pytest.raises(SystemExit) as exc_info:
        handle_http_error(error, logger)
    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "Rate limit" in captured.err

    error_500 = PerplexityHTTPStatusError(
        "boom", request=None, response=type("R", (), {"status_code": 500})()
    )
    with pytest.raises(SystemExit):
        handle_http_error(error_500, logger, debug_mode="debug", context="during export")
    captured = capsys.readouterr()
    assert "Details:" in captured.err


def test_handle_network_error_real_body(capsys) -> None:
    """Network error handler prints the standard message and exits 1."""
    from perplexity_cli.utils.exceptions import PerplexityRequestError
    from perplexity_cli.utils.http_errors import handle_network_error

    logger = logging.getLogger("test-http-errors-network")
    error = PerplexityRequestError("connection reset")
    with pytest.raises(SystemExit) as exc_info:
        handle_network_error(error, logger)
    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "Network error" in captured.err

    with pytest.raises(SystemExit):
        handle_network_error(error, logger, debug_mode="debug")
    captured = capsys.readouterr()
    assert "Details:" in captured.err
