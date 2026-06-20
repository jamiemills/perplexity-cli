"""Tests for shared CLI error handling helpers."""

import logging

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
                debug_mode=True,
                message_tuple=("[ERROR] Failed.", "Unexpected test error", True),
            )

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "Debug info:" in captured.err
    assert "RuntimeError: boom" in captured.err
