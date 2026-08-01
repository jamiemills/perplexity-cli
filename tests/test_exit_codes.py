"""Tests for exit code constants and exception-to-exit-code mapping."""

from perplexity_cli.exit_codes import (
    AUTH_REQUIRED,
    CONFLICT,
    GENERAL_FAILURE,
    INTERRUPTED,
    NOT_FOUND,
    SUCCESS,
    TRANSIENT,
    USAGE_ERROR,
    VALIDATION,
    exit_code_for_exception,
    format_exit_codes_help,
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


class TestExitCodeConstants:
    """Tests for exit code constant values."""

    def test_each_constant_value(self):
        """Test that each exit code constant has the correct value."""
        assert SUCCESS == 0
        assert GENERAL_FAILURE == 1
        assert USAGE_ERROR == 2
        assert NOT_FOUND == 3
        assert AUTH_REQUIRED == 4
        assert CONFLICT == 5
        assert TRANSIENT == 6
        assert VALIDATION == 7
        assert INTERRUPTED == 130


class TestExitCodeMapping:
    """Tests for exit_code_for_exception mapping."""

    def test_authentication_error(self):
        assert exit_code_for_exception(AuthenticationError("bad token")) == 4

    def test_rate_limit_error(self):
        assert exit_code_for_exception(RateLimitError("slow down")) == 6

    def test_http_status_401(self):
        exc = PerplexityHTTPStatusError("err", response=SimpleResponse(status_code=401))
        assert exit_code_for_exception(exc) == 4

    def test_http_status_403(self):
        exc = PerplexityHTTPStatusError("err", response=SimpleResponse(status_code=403))
        assert exit_code_for_exception(exc) == 4

    def test_http_status_429(self):
        exc = PerplexityHTTPStatusError("err", response=SimpleResponse(status_code=429))
        assert exit_code_for_exception(exc) == 6

    def test_http_status_500(self):
        exc = PerplexityHTTPStatusError("err", response=SimpleResponse(status_code=500))
        assert exit_code_for_exception(exc) == 6

    def test_http_status_503(self):
        exc = PerplexityHTTPStatusError("err", response=SimpleResponse(status_code=503))
        assert exit_code_for_exception(exc) == 6

    def test_http_status_other(self):
        exc = PerplexityHTTPStatusError("err", response=SimpleResponse(status_code=400))
        assert exit_code_for_exception(exc) == 1

    def test_request_error(self):
        assert exit_code_for_exception(PerplexityRequestError("timeout")) == 6

    def test_configuration_error(self):
        assert exit_code_for_exception(ConfigurationError("bad config")) == 7

    def test_upstream_schema_error(self):
        assert exit_code_for_exception(UpstreamSchemaError("bad schema")) == 7

    def test_attachment_error(self):
        assert exit_code_for_exception(AttachmentError("bad file")) == 7

    def test_attachment_upload_error(self):
        assert exit_code_for_exception(AttachmentUploadError("upload failed")) == 1

    def test_value_error(self):
        assert exit_code_for_exception(ValueError("invalid")) == 1

    def test_keyboard_interrupt(self):
        assert exit_code_for_exception(KeyboardInterrupt()) == 130

    def test_generic_exception(self):
        assert exit_code_for_exception(Exception("unknown")) == 1


class TestUnifiedTaxonomyConsistency:
    """Human and JSON error paths must agree with exit_code_for_exception."""

    def test_each_error_class_same_code_in_both_modes(self):
        from io import StringIO
        from unittest.mock import patch

        from perplexity_cli.error_handler import handle_error

        exceptions = [
            AuthenticationError("auth"),
            RateLimitError("rate"),
            PerplexityRequestError("network"),
            PerplexityHTTPStatusError("err", response=SimpleResponse(status_code=401)),
            PerplexityHTTPStatusError("err", response=SimpleResponse(status_code=429)),
            PerplexityHTTPStatusError("err", response=SimpleResponse(status_code=500)),
            ConfigurationError("config"),
            UpstreamSchemaError("schema"),
            AttachmentError("file"),
            AttachmentUploadError("upload"),
            ValueError("value"),
            Exception("generic"),
        ]
        expected = [exit_code_for_exception(exc) for exc in exceptions]

        actual = []
        for exc in exceptions:
            codes = []
            for output_format in ("human", "json"):
                stdout = StringIO()
                stderr = StringIO()
                with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
                    try:
                        handle_error(exc, "test", output_format=output_format)
                    except SystemExit as e:
                        codes.append(e.code)
            assert codes[0] == codes[1]
            actual.append(codes[0])

        assert actual == expected


class TestFormatExitCodesHelp:
    """Tests for format_exit_codes_help output."""

    def test_format_returns_string(self):
        result = format_exit_codes_help()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_format_contains_all_codes(self):
        result = format_exit_codes_help()
        for code in ["0", "1", "2", "3", "4", "5", "6", "7", "130"]:
            assert code in result
