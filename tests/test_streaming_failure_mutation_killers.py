"""Mutation-killer tests for the streaming failure contract and hardening.

Exact payload, exit-code and message assertions so mutations of the failure
event emission, taxonomy mapping, MCP bind warning, cookie scoping and CSV
writer cannot survive.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from perplexity_cli.auth.oauth_handler import _is_perplexity_domain
from perplexity_cli.mcp_server import ServerConfig, _warn_non_loopback_bind
from perplexity_cli.query_streaming import (
    _emit_stream_failure_event,
    _handle_stream_http_status_error,
    _handle_stream_keyboard_interrupt,
    _handle_stream_network_error,
    _handle_stream_output_error,
    _handle_stream_unexpected_error,
    _handle_stream_upstream_schema_error,
    _stream_error_code,
)
from perplexity_cli.threads.exporter import write_threads_csv
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    UpstreamSchemaError,
)


def _http_error(status: int) -> PerplexityHTTPStatusError:
    response = Mock(name="response", status_code=status)
    return PerplexityHTTPStatusError(f"HTTP {status}", response=response)


def _writer() -> Mock:
    return Mock(name="ndjson-writer")


def _logger() -> Mock:
    return Mock(name="logger")


class TestStreamErrorCodeTaxonomy:
    """Every error class maps to its exact taxonomy code."""

    @pytest.mark.parametrize(
        ("status", "code"),
        [(401, "authentication_required"), (403, "permission_denied"), (429, "rate_limited")],
    )
    def test_http_status_codes(self, status, code):
        assert _stream_error_code(_http_error(status)) == code

    @pytest.mark.parametrize(
        ("status", "code"), [(418, "network_error"), (500, "network_error"), (400, "network_error")]
    )
    def test_other_http_statuses(self, status, code):
        assert _stream_error_code(_http_error(status)) == code

    def test_class_codes(self):
        assert _stream_error_code(PerplexityRequestError("x")) == "network_error"
        assert _stream_error_code(UpstreamSchemaError("x")) == "upstream_schema_error"
        assert _stream_error_code(KeyboardInterrupt()) == "interrupted"
        assert _stream_error_code(OSError("x")) == "output_error"

    def test_unexpected_defaults_to_internal(self):
        assert _stream_error_code(RuntimeError("x")) == "internal_error"


class TestEmitStreamFailureEvent:
    """The terminal event must carry the exact payload shape."""

    def test_payload_with_fix(self):
        writer = _writer()
        _emit_stream_failure_event(writer, "rate_limited", "[ERROR] Rate limited.", "Wait.")
        writer.result.assert_called_once_with(
            ok=False,
            command="pxcli query --json --stream",
            result={"error": {"code": "rate_limited", "message": "Rate limited.", "fix": "Wait."}},
        )

    def test_payload_without_fix_omits_key(self):
        writer = _writer()
        _emit_stream_failure_event(writer, "network_error", "[ERROR] Network down.", None)
        payload = writer.result.call_args.kwargs["result"]
        assert payload == {"error": {"code": "network_error", "message": "Network down."}}

    def test_human_mode_writer_none_is_noop(self):
        _emit_stream_failure_event(None, "internal_error", "msg", None)

    def test_broken_pipe_is_swallowed(self):
        writer = _writer()
        writer.result.side_effect = BrokenPipeError("closed")
        _emit_stream_failure_event(writer, "output_error", "msg", None)


class TestHandlerContracts:
    """Each handler must emit the exact event, stderr text and exit code."""

    def _capture(self, invoke, error, json_mode):
        writer = _writer() if json_mode else None
        with pytest.raises(SystemExit) as exc_info:
            invoke(error, _logger(), writer)
        return exc_info.value.code, writer

    def test_http_401_contract(self, capsys):
        code, writer = self._capture(_handle_stream_http_status_error, _http_error(401), True)
        assert code == 4
        writer.result.assert_called_once_with(
            ok=False,
            command="pxcli query --json --stream",
            result={
                "error": {
                    "code": "authentication_required",
                    "message": "Authentication failed. Token may be expired.",
                    "fix": "Re-authenticate with: perplexity-cli auth",
                }
            },
        )
        assert capsys.readouterr().out == ""

    def test_http_401_human_stderr_exact(self, capsys):
        code, _writer = self._capture(_handle_stream_http_status_error, _http_error(401), False)
        assert code == 4
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == (
            "[ERROR] Authentication failed. Token may be expired.\n"
            "\nRe-authenticate with: perplexity-cli auth\n"
        )

    def test_http_429_contract(self, capsys):
        code, writer = self._capture(_handle_stream_http_status_error, _http_error(429), True)
        assert code == 6
        payload = writer.result.call_args.kwargs["result"]
        assert payload["error"]["code"] == "rate_limited"
        assert payload["error"]["message"] == "Rate limit exceeded. Please wait and try again."
        assert "fix" not in payload["error"]

    def test_http_unknown_status_message(self, capsys):
        code, writer = self._capture(_handle_stream_http_status_error, _http_error(418), True)
        assert code == 1
        payload = writer.result.call_args.kwargs["result"]
        assert payload["error"]["message"] == "HTTP error 418."

    def test_network_error_contract(self, capsys):
        code, writer = self._capture(
            _handle_stream_network_error, PerplexityRequestError("no route"), True
        )
        assert code == 6
        payload = writer.result.call_args.kwargs["result"]
        assert payload["error"] == {
            "code": "network_error",
            "message": "Network error. Please check your internet connection.",
        }

    def test_upstream_schema_error_contract(self, capsys):
        code, writer = self._capture(
            _handle_stream_upstream_schema_error, UpstreamSchemaError("bad shape"), True
        )
        assert code == 7
        payload = writer.result.call_args.kwargs["result"]
        assert payload["error"] == {
            "code": "upstream_schema_error",
            "message": "Upstream response format changed: bad shape",
        }

    def test_keyboard_interrupt_contract(self, capsys):
        code, writer = self._capture(
            lambda _e, logger, w: _handle_stream_keyboard_interrupt(logger, w),
            KeyboardInterrupt(),
            True,
        )
        assert code == 130
        payload = writer.result.call_args.kwargs["result"]
        assert payload["error"]["code"] == "interrupted"

    def test_output_error_contract(self, capsys):
        code, writer = self._capture(_handle_stream_output_error, OSError("pipe"), True)
        assert code == 1
        payload = writer.result.call_args.kwargs["result"]
        assert payload["error"] == {
            "code": "output_error",
            "message": "Failed to render streaming output: pipe",
        }

    def test_unexpected_error_contract(self, capsys):
        code, writer = self._capture(_handle_stream_unexpected_error, RuntimeError("boom"), True)
        assert code == 1
        payload = writer.result.call_args.kwargs["result"]
        assert payload["error"] == {
            "code": "internal_error",
            "message": "An unexpected error occurred.",
            "fix": "Run with --debug for more information.",
        }


class TestJsonModeChannelDiscipline:
    """JSON mode must stay silent on stderr for every handler class."""

    def _assert_stderr_silent(self, invoke, error):
        writer = Mock(name="ndjson-writer")
        with pytest.raises(SystemExit):
            invoke(error, Mock(name="logger"), writer)

    def test_network_error_json_mode_stderr_silent(self, capsys):
        from perplexity_cli.query_streaming import _handle_stream_network_error

        self._assert_stderr_silent(_handle_stream_network_error, PerplexityRequestError("down"))
        assert capsys.readouterr().err == ""

    def test_upstream_schema_error_json_mode_stderr_silent(self, capsys):
        from perplexity_cli.query_streaming import _handle_stream_upstream_schema_error

        self._assert_stderr_silent(_handle_stream_upstream_schema_error, UpstreamSchemaError("bad"))
        assert capsys.readouterr().err == ""

    def test_keyboard_interrupt_json_mode_stderr_silent(self, capsys):
        from perplexity_cli.query_streaming import _handle_stream_keyboard_interrupt

        writer = Mock(name="ndjson-writer")
        with pytest.raises(SystemExit):
            _handle_stream_keyboard_interrupt(Mock(name="logger"), writer)
        assert capsys.readouterr().err == ""

    def test_output_error_json_mode_stderr_silent(self, capsys):
        from perplexity_cli.query_streaming import _handle_stream_output_error

        self._assert_stderr_silent(_handle_stream_output_error, OSError("pipe"))
        assert capsys.readouterr().err == ""

    def test_unexpected_error_json_mode_stderr_silent(self, capsys):
        from perplexity_cli.query_streaming import _handle_stream_unexpected_error

        self._assert_stderr_silent(_handle_stream_unexpected_error, RuntimeError("boom"))
        assert capsys.readouterr().err == ""

    def test_http_status_json_mode_stderr_silent(self, capsys):
        self._assert_stderr_silent(_handle_stream_http_status_error, _http_error(429))
        assert capsys.readouterr().err == ""


class TestHumanModeStderrExactness:
    """Human mode must print the exact stderr text for every handler."""

    def test_network_error_human_stderr_exact(self, capsys):
        with pytest.raises(SystemExit):
            _handle_stream_network_error(PerplexityRequestError("down"), Mock(), None)
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "[ERROR] Network error. Please check your internet connection.\n"

    def test_upstream_schema_error_human_stderr_exact(self, capsys):
        with pytest.raises(SystemExit):
            _handle_stream_upstream_schema_error(UpstreamSchemaError("bad shape"), Mock(), None)
        captured = capsys.readouterr()
        assert captured.err == "[ERROR] Upstream response format changed: bad shape\n"

    def test_keyboard_interrupt_human_stderr_exact(self, capsys):
        from perplexity_cli.query_streaming import _handle_stream_keyboard_interrupt

        with pytest.raises(SystemExit):
            _handle_stream_keyboard_interrupt(Mock(), None)
        captured = capsys.readouterr()
        assert captured.err == "\n[ERROR] Streaming interrupted.\n"

    def test_output_error_human_stderr_exact(self, capsys):
        with pytest.raises(SystemExit):
            _handle_stream_output_error(OSError("broken pipe"), Mock(), None)
        captured = capsys.readouterr()
        assert captured.err == "[ERROR] Failed to render streaming output: broken pipe\n"

    def test_unexpected_error_human_stderr_exact(self, capsys):
        with pytest.raises(SystemExit):
            _handle_stream_unexpected_error(RuntimeError("boom"), Mock(), None)
        captured = capsys.readouterr()
        assert captured.err == (
            "[ERROR] An unexpected error occurred.\nRun with --debug for more information.\n"
        )


class TestDispatchAndBrokenPipeDebug:
    """Dispatch must forward the writer, and pipe-closure logs exactly."""

    def test_dispatch_json_writer_reaches_unexpected_handler(self):
        from perplexity_cli.query_streaming import _handle_stream_error

        writer = Mock(name="ndjson-writer")
        with pytest.raises(SystemExit):
            _handle_stream_error(RuntimeError("boom"), ndjson_writer=writer)
        writer.result.assert_called_once()

    def test_broken_pipe_logs_exact_debug_message(self, caplog):
        import logging

        writer = Mock(name="ndjson-writer")
        writer.result.side_effect = BrokenPipeError("closed")
        with caplog.at_level(logging.DEBUG, logger="perplexity_cli.query_streaming"):
            _emit_stream_failure_event(writer, "output_error", "msg", None)
        record = caplog.records[-1]
        assert record.message == "Skipped failure event; output pipe already closed"
        assert record.levelname == "DEBUG"


class TestMcpBindWarning:
    """The non-loopback warning must be exact and correctly gated."""

    def _config(self, transport: str, host: str) -> ServerConfig:
        return ServerConfig(transport=transport, host=host)

    def test_non_loopback_http_warns_with_exact_text(self, capsys):
        _warn_non_loopback_bind(self._config("streamable-http", "0.0.0.0"))
        err = capsys.readouterr().err
        assert err.startswith(
            "[WARNING] Binding to non-loopback host '0.0.0.0': the MCP endpoint has "
            "no authentication and DNS-rebinding protection is disabled for non-loopback "
            "binds. Anyone who can reach this address can use your stored Perplexity "
            "credentials.\n"
        )

    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
    def test_loopback_hosts_are_silent(self, capsys, host):
        _warn_non_loopback_bind(self._config("streamable-http", host))
        assert capsys.readouterr().err == ""

    def test_stdio_transport_is_silent(self, capsys):
        _warn_non_loopback_bind(self._config("stdio", "0.0.0.0"))
        assert capsys.readouterr().err == ""


class TestPerplexityDomainPredicate:
    """The cookie scoping predicate must match exactly the Perplexity domains."""

    @pytest.mark.parametrize(
        ("domain", "expected"),
        [
            ("perplexity.ai", True),
            (".perplexity.ai", True),
            ("www.perplexity.ai", True),
            ("api.perplexity.ai", True),
            ("", False),
            ("google.com", False),
            (".google.com", False),
            ("notperplexity.ai", False),
            ("perplexity.ai.evil.com", False),
            ("PERPLEXITY.AI", False),
        ],
    )
    def test_predicate_boundaries(self, domain, expected):
        assert _is_perplexity_domain(domain) is expected


class TestWriteThreadsCsvContract:
    """The CSV writer must keep 0600 mode, header order and formula neutralising."""

    def _record(self, title: str) -> object:
        from perplexity_cli.threads.exporter import ThreadRecord

        return ThreadRecord(title=title, url="https://perplexity.ai/t/1", created_at="2026-09-20")

    def test_mode_header_and_rows(self, tmp_path):
        import stat

        out = tmp_path / "out.csv"
        write_threads_csv([self._record("=SUM(A1)")], out)
        mode = stat.S_IMODE(out.stat().st_mode)
        content = out.read_text(encoding="utf-8").splitlines()
        assert mode == 0o600
        assert content[0] == "created_at,title,url"
        assert content[1] == "2026-09-20,'=SUM(A1),https://perplexity.ai/t/1"
