"""Tests for centralised error handling.

The handler must produce the same taxonomy exit code in both JSON and human
modes, emit on a single channel (JSON on stdout, human text on stderr) and
never mix output across channels.
"""

import json
from io import StringIO
from unittest.mock import patch

from perplexity_cli.error_handler import handle_error
from perplexity_cli.exit_codes import (
    AUTH_REQUIRED,
    GENERAL_FAILURE,
    TRANSIENT,
    VALIDATION,
)
from perplexity_cli.utils.exceptions import (
    AttachmentError,
    AttachmentUploadError,
    AuthenticationError,
    ConfigurationError,
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    RateLimitError,
    SimpleResponse,
    UpstreamSchemaError,
)

_AUTH_FIX = "Fix: Run `pxcli auth login` to authenticate.\n"


def _capture_handle_error(exc, *, output_format="human", command="test"):
    """Run handle_error, capturing stdout, stderr, and the exit code."""
    stdout = StringIO()
    stderr = StringIO()
    exit_code = None
    with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
        try:
            handle_error(exc, command, output_format=output_format)
        except SystemExit as e:
            exit_code = e.code
    return stdout.getvalue(), stderr.getvalue(), exit_code


class TestUnifiedExitCodePolicy:
    """Both modes must agree on the taxonomy exit code for the same exception."""

    def test_authentication_error_same_code_both_modes(self):
        _, _, json_code = _capture_handle_error(
            AuthenticationError("bad token"), output_format="json"
        )
        _, _, human_code = _capture_handle_error(AuthenticationError("bad token"))
        assert json_code == human_code == AUTH_REQUIRED

    def test_http_500_same_code_both_modes(self):
        exc = PerplexityHTTPStatusError("err", response=SimpleResponse(status_code=500))
        _, _, json_code = _capture_handle_error(exc, output_format="json")
        _, _, human_code = _capture_handle_error(exc)
        assert json_code == human_code == TRANSIENT

    def test_configuration_error_same_code_both_modes(self):
        _, _, json_code = _capture_handle_error(
            ConfigurationError("bad config"), output_format="json"
        )
        _, _, human_code = _capture_handle_error(ConfigurationError("bad config"))
        assert json_code == human_code == VALIDATION

    def test_generic_error_same_code_both_modes(self):
        _, _, json_code = _capture_handle_error(Exception("unknown"), output_format="json")
        _, _, human_code = _capture_handle_error(Exception("unknown"))
        assert json_code == human_code == GENERAL_FAILURE


class TestHandleErrorJsonMode:
    """Tests for handle_error in JSON mode: clean JSON on stdout only."""

    def test_authentication_error_json(self):
        stdout, stderr, code = _capture_handle_error(
            AuthenticationError("bad token"), output_format="json"
        )
        data = json.loads(stdout)
        assert data["error"]["code"] == "authentication_required"
        assert data["ok"] is False
        assert stderr == ""
        assert code == AUTH_REQUIRED

    def test_rate_limit_error_json(self):
        stdout, stderr, code = _capture_handle_error(
            RateLimitError("slow down"), output_format="json"
        )
        data = json.loads(stdout)
        assert data["error"]["code"] == "rate_limited"
        assert stderr == ""
        assert code == TRANSIENT

    def test_network_error_json(self):
        stdout, _, code = _capture_handle_error(
            PerplexityRequestError("timeout"), output_format="json"
        )
        data = json.loads(stdout)
        assert data["error"]["code"] == "network_error"
        assert code == TRANSIENT

    def test_http_401_json(self):
        exc = PerplexityHTTPStatusError("err", response=SimpleResponse(status_code=401))
        stdout, _, code = _capture_handle_error(exc, output_format="json")
        data = json.loads(stdout)
        assert data["error"]["code"] == "authentication_required"
        assert code == AUTH_REQUIRED

    def test_http_429_json(self):
        exc = PerplexityHTTPStatusError("err", response=SimpleResponse(status_code=429))
        stdout, _, code = _capture_handle_error(exc, output_format="json")
        data = json.loads(stdout)
        assert data["error"]["code"] == "rate_limited"
        assert code == TRANSIENT

    def test_http_500_json(self):
        exc = PerplexityHTTPStatusError("err", response=SimpleResponse(status_code=500))
        stdout, _, code = _capture_handle_error(exc, output_format="json")
        data = json.loads(stdout)
        assert data["error"]["code"] == "network_error"
        assert code == TRANSIENT

    def test_configuration_error_json(self):
        stdout, _, code = _capture_handle_error(
            ConfigurationError("bad config"), output_format="json"
        )
        data = json.loads(stdout)
        assert data["error"]["code"] == "configuration_error"
        assert code == VALIDATION

    def test_attachment_error_json(self):
        stdout, _, code = _capture_handle_error(AttachmentError("bad file"), output_format="json")
        data = json.loads(stdout)
        assert data["error"]["code"] == "attachment_error"
        assert code == VALIDATION

    def test_attachment_upload_error_json(self):
        stdout, _, code = _capture_handle_error(
            AttachmentUploadError("upload failed"), output_format="json"
        )
        data = json.loads(stdout)
        assert data["error"]["code"] == "attachment_error"
        assert code == GENERAL_FAILURE

    def test_upstream_schema_error_json(self):
        stdout, _, code = _capture_handle_error(
            UpstreamSchemaError("bad schema"), output_format="json"
        )
        data = json.loads(stdout)
        assert data["error"]["code"] == "upstream_schema_error"
        assert code == VALIDATION

    def test_generic_error_json(self):
        stdout, _, code = _capture_handle_error(Exception("unknown"), output_format="json")
        data = json.loads(stdout)
        assert data["error"]["code"] == "internal_error"
        assert code == GENERAL_FAILURE

    def test_json_output_is_valid_json(self):
        stdout, _, _ = _capture_handle_error(ValueError("bad input"), output_format="json")
        data = json.loads(stdout)
        assert data["ok"] is False

    def test_nothing_on_stderr_in_json_mode(self):
        _, stderr, _ = _capture_handle_error(Exception("fail"), output_format="json")
        assert stderr == ""

    def test_empty_message_falls_back_to_class_name(self):
        stdout, _, _ = _capture_handle_error(Exception(), output_format="json")
        data = json.loads(stdout)
        assert data["error"]["message"] == "Exception"


class TestHandleErrorHumanMode:
    """Tests for handle_error in human mode: text on stderr only."""

    def test_authentication_error_human(self):
        stdout, stderr, code = _capture_handle_error(AuthenticationError("bad token"))
        assert stderr == f"Error: bad token\n{_AUTH_FIX}"
        assert stdout == ""
        assert code == AUTH_REQUIRED

    def test_rate_limit_error_human(self):
        stdout, stderr, code = _capture_handle_error(RateLimitError("slow down"))
        assert stderr == "Error: slow down\nFix: Wait a moment and try again.\n"
        assert stdout == ""
        assert code == TRANSIENT

    def test_configuration_error_human(self):
        stdout, stderr, code = _capture_handle_error(ConfigurationError("bad config"))
        assert stderr == "Error: bad config\n"
        assert stdout == ""
        assert code == VALIDATION

    def test_generic_error_human(self):
        stdout, stderr, code = _capture_handle_error(Exception("unknown"))
        assert stderr == "Error: unknown\n"
        assert stdout == ""
        assert code == GENERAL_FAILURE

    def test_nothing_on_stdout_in_human_mode(self):
        stdout, _, _ = _capture_handle_error(Exception("fail"))
        assert stdout == ""

    def test_fix_suggestion_included(self):
        _, stderr, _ = _capture_handle_error(AuthenticationError("bad token"))
        assert "pxcli auth login" in stderr
