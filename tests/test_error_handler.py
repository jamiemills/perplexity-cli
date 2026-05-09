"""Tests for centralised error handling."""

import json
from io import StringIO
from unittest.mock import patch

from perplexity_cli.error_handler import handle_error
from perplexity_cli.utils.exceptions import (
    AuthenticationError,
    ConfigurationError,
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    RateLimitError,
    SimpleResponse,
)


def _capture_handle_error(exc, *, json_mode=False, debug_mode=False, command="test"):
    """Run handle_error, capturing stdout, stderr, and the exit code."""
    stdout = StringIO()
    stderr = StringIO()
    exit_code = None
    with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
        try:
            handle_error(exc, command=command, json_mode=json_mode, debug_mode=debug_mode)
        except SystemExit as e:
            exit_code = e.code
    return stdout.getvalue(), stderr.getvalue(), exit_code


class TestHandleErrorJsonMode:
    """Tests for handle_error in JSON mode."""

    def test_authentication_error_json(self):
        stdout, _, code = _capture_handle_error(AuthenticationError("bad token"), json_mode=True)
        data = json.loads(stdout)
        assert data["error"]["code"] == "authentication_required"
        assert code == 4

    def test_rate_limit_error_json(self):
        stdout, _, code = _capture_handle_error(RateLimitError("slow down"), json_mode=True)
        data = json.loads(stdout)
        assert data["error"]["code"] == "rate_limited"
        assert code == 6

    def test_network_error_json(self):
        stdout, _, code = _capture_handle_error(PerplexityRequestError("timeout"), json_mode=True)
        data = json.loads(stdout)
        assert data["error"]["code"] == "network_error"
        assert code == 6

    def test_http_401_json(self):
        exc = PerplexityHTTPStatusError("err", response=SimpleResponse(status_code=401))
        stdout, _, code = _capture_handle_error(exc, json_mode=True)
        data = json.loads(stdout)
        assert data["error"]["code"] == "authentication_required"
        assert code == 4

    def test_http_429_json(self):
        exc = PerplexityHTTPStatusError("err", response=SimpleResponse(status_code=429))
        stdout, _, code = _capture_handle_error(exc, json_mode=True)
        data = json.loads(stdout)
        assert data["error"]["code"] == "rate_limited"
        assert code == 6

    def test_http_500_json(self):
        exc = PerplexityHTTPStatusError("err", response=SimpleResponse(status_code=500))
        stdout, _, code = _capture_handle_error(exc, json_mode=True)
        data = json.loads(stdout)
        assert data["error"]["code"] == "network_error"
        assert code == 6

    def test_configuration_error_json(self):
        stdout, _, code = _capture_handle_error(ConfigurationError("bad config"), json_mode=True)
        data = json.loads(stdout)
        assert data["error"]["code"] == "configuration_error"
        assert code == 7

    def test_generic_error_json(self):
        stdout, _, code = _capture_handle_error(Exception("unknown"), json_mode=True)
        data = json.loads(stdout)
        assert data["error"]["code"] == "internal_error"
        assert code == 1

    def test_json_output_is_valid_json(self):
        stdout, _, _ = _capture_handle_error(ValueError("bad input"), json_mode=True)
        data = json.loads(stdout)
        assert data["ok"] is False

    def test_nothing_on_stderr_in_json_mode(self):
        _, stderr, _ = _capture_handle_error(Exception("fail"), json_mode=True)
        assert stderr == ""


class TestHandleErrorHumanMode:
    """Tests for handle_error in human-readable mode."""

    def test_authentication_error_human(self):
        _, stderr, code = _capture_handle_error(AuthenticationError("bad token"), json_mode=False)
        assert "bad token" in stderr or "authentication" in stderr.lower()
        assert code == 4

    def test_rate_limit_error_human(self):
        _, stderr, code = _capture_handle_error(RateLimitError("slow down"), json_mode=False)
        assert len(stderr) > 0
        assert code == 6

    def test_generic_error_human(self):
        _, stderr, code = _capture_handle_error(Exception("unknown"), json_mode=False)
        assert len(stderr) > 0
        assert code == 1

    def test_nothing_on_stdout_in_human_mode(self):
        stdout, _, _ = _capture_handle_error(Exception("fail"), json_mode=False)
        assert stdout == ""

    def test_fix_suggestion_included(self):
        _, stderr, _ = _capture_handle_error(AuthenticationError("bad token"), json_mode=False)
        assert "pxcli auth login" in stderr
