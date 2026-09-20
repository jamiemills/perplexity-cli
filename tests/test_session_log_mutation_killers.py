"""Mutation-killer tests for session logging in the query runner.

These tests assert exact call arguments, sequences and payloads so that
mutmut mutations of the session-logging seam cannot survive.
"""

from __future__ import annotations

from unittest.mock import Mock, call, patch

import pytest

from perplexity_cli import query_runner
from perplexity_cli.query_runner import (
    _create_session_logger_safely,
    _log_session_invocation,
    _log_session_response,
)


def _disabled_logger_spy() -> tuple[Mock, Mock, Mock]:
    """Return (SessionLogger class mock, instance, is_enabled) wired for the disabled path."""
    instance = Mock(name="session-logger-instance")
    cls = Mock(name="SessionLogger", return_value=instance)
    cls.is_enabled.return_value = False
    return cls, instance, cls.is_enabled


class TestCreateSessionLoggerSafelyDisabledPath:
    """The disabled path must construct the exact disabled logger."""

    def test_disabled_path_constructs_disabled_logger_without_create(self, monkeypatch):
        cls, _instance, _flag = _disabled_logger_spy()
        monkeypatch.setattr(query_runner, "SessionLogger", cls)
        result = _create_session_logger_safely()
        cls.assert_called_once_with(session_id="disabled", enabled="disabled")
        cls.create.assert_not_called()
        assert result is _instance

    def test_disabled_path_uses_is_enabled_gate(self, monkeypatch):
        cls, _instance, _flag = _disabled_logger_spy()
        monkeypatch.setattr(query_runner, "SessionLogger", cls)
        _create_session_logger_safely()
        cls.is_enabled.assert_called_once_with()


class TestCreateSessionLoggerSafelyEnabledPath:
    """The enabled path must call the factory and use its product."""

    def test_enabled_path_calls_create(self, monkeypatch):
        instance = Mock(name="enabled-logger")
        cls = Mock(name="SessionLogger")
        cls.is_enabled.return_value = True
        cls.create.return_value = instance
        monkeypatch.setattr(query_runner, "SessionLogger", cls)
        result = _create_session_logger_safely()
        cls.create.assert_called_once_with()
        cls.assert_not_called()
        assert result is instance


class TestCreateSessionLoggerSafelyFailurePath:
    """An OSError from the factory degrades to the disabled logger with a warning."""

    def test_oserror_degrades_to_disabled_logger_with_exact_warning(self, monkeypatch):
        exc = OSError("disk unavailable")
        instance = Mock(name="fallback-logger")
        cls = Mock(name="SessionLogger", return_value=instance)
        cls.is_enabled.return_value = True
        cls.create.side_effect = exc
        monkeypatch.setattr(query_runner, "SessionLogger", cls)
        logger = Mock(name="module-logger")
        monkeypatch.setattr(query_runner, "logger", logger)
        result = _create_session_logger_safely()
        cls.assert_called_once_with(session_id="disabled", enabled="disabled")
        logger.warning.assert_called_once_with("Session logging failed: %s", exc)
        assert result is instance


class TestLogSessionInvocationContract:
    """The invocation event must forward the exact command and payload."""

    def _run(self, session_logger: Mock, event_args: dict[str, object]) -> Mock:
        logger = Mock(name="module-logger")
        with patch.object(query_runner, "logger", logger):
            _log_session_invocation(session_logger, event_args)
        return logger

    def test_forwards_exact_command_and_args(self):
        session_logger = Mock(name="session-logger")
        args = {"mode": "stream", "json": True, "stream": True}
        self._run(session_logger, args)
        session_logger.log_invocation.assert_called_once_with("query", args)

    def test_oserror_warns_with_exact_message(self):
        session_logger = Mock(name="session-logger")
        session_logger.log_invocation.side_effect = OSError("closed")
        logger = self._run(session_logger, {"mode": "batch"})
        session_logger.log_invocation.assert_called_once_with("query", {"mode": "batch"})
        assert logger.warning.call_count == 1
        assert logger.warning.call_args == call(
            "Session logging failed: %s", session_logger.log_invocation.side_effect
        )


class TestLogSessionResponseContract:
    """The response event must carry the exact outcome and duration."""

    def _run(
        self, session_logger: Mock, outcome: str, times: list[float], start: float | None
    ) -> Mock:
        clock = Mock(name="clock", monotonic=Mock(side_effect=times))
        logger = Mock(name="module-logger")
        with (
            patch.object(query_runner.time, "monotonic", clock.monotonic),
            patch.object(query_runner, "logger", logger),
        ):
            _log_session_response(session_logger, outcome, start)
        return logger

    def test_known_start_computes_exact_duration(self):
        session_logger = Mock(name="session-logger")
        self._run(session_logger, "ok", [10.5], 10.0)
        session_logger.log_response.assert_called_once_with("ok", 500, result_summary=None)

    def test_none_start_falls_back_to_clock(self):
        session_logger = Mock(name="session-logger")
        self._run(session_logger, "error", [20.0, 20.25], None)
        session_logger.log_response.assert_called_once_with("error", 250, result_summary=None)

    def test_outcome_string_is_forwarded_unchanged(self):
        session_logger = Mock(name="session-logger")
        self._run(session_logger, "ok", [3.0], 1.0)
        assert session_logger.log_response.call_args.args[0] == "ok"

    def test_oserror_warns_with_exact_arguments(self):
        session_logger = Mock(name="session-logger")
        exc = OSError("gone")
        session_logger.log_response.side_effect = exc
        logger = self._run(session_logger, "ok", [2.0], 1.0)
        session_logger.log_response.assert_called_once_with("ok", 1000, result_summary=None)
        logger.warning.assert_called_once_with("Session logging failed: %s", exc)


class TestRunQueryCommandSessionOutcome:
    """run_query_command must record ok/error outcomes with the exact strings."""

    def _run_command(self, api: Mock, handle_error_mock: Mock) -> None:
        from tests.helpers.query_deps import patched_dep
        from tests.test_query_runner import _default_options

        with (
            patched_dep("TokenManager", Mock(return_value=Mock(name="tm"))),
            patched_dep("load_token_optional", Mock(return_value=("token-123", None))),
            patched_dep("PerplexityAPI", Mock(return_value=api)),
            patched_dep("handle_error", handle_error_mock),
            patch(
                "perplexity_cli.query_runner.resolve_attachment_urls",
                return_value=[],
                autospec=True,
            ),
            patch("perplexity_cli.query_runner.build_final_query", return_value="final query"),
        ):
            query_runner.run_query_command({"debug": False}, "question", _default_options())

    def test_success_records_ok_outcome(self, monkeypatch):
        api = Mock(name="api")
        api.__enter__ = Mock(return_value=api)
        api.__exit__ = Mock(return_value=False)
        api.get_complete_answer.return_value = Mock(text="answer text", references=[])

        def _real_call(fn, *_args, **_kwargs):
            fn()

        captured: list[str] = []
        monkeypatch.setattr(
            query_runner,
            "_log_session_response",
            lambda logger, outcome, start: captured.append(outcome),
        )
        self._run_command(api, Mock(side_effect=_real_call))
        assert captured == ["ok"]

    def test_failure_records_error_outcome(self, monkeypatch):
        api = Mock(name="api")
        api.__enter__ = Mock(return_value=api)
        api.__exit__ = Mock(return_value=False)

        def _failing_call(_fn, *_args, **_kwargs):
            raise SystemExit(7)

        captured: list[str] = []
        monkeypatch.setattr(
            query_runner,
            "_log_session_response",
            lambda logger, outcome, start: captured.append(outcome),
        )
        with pytest.raises(SystemExit):
            self._run_command(api, Mock(side_effect=_failing_call))
        assert captured == ["error"]


class TestRunQueryCommandStreamAndDebugContext:
    """Stream-mode payloads and debug-context labels must be exact."""

    def _run(self, stream: bool):
        from tests.helpers.query_deps import patched_dep
        from tests.test_query_runner import _default_options

        invocation: list[dict[str, object]] = []
        response_args: list[tuple[object, ...]] = []
        debug_calls: list[tuple[object, ...]] = []
        api = Mock(name="api")
        api.__enter__ = Mock(return_value=api)
        api.__exit__ = Mock(return_value=False)
        api.get_complete_answer.return_value = Mock(text="answer text", references=[])

        def _real_call(fn, *_args, **_kwargs):
            fn()

        def _capture_invoke(_logger, args):
            invocation.append(args)

        def _capture_response(_logger, outcome, start):
            response_args.append((outcome, start))

        def _capture_debug(query, fmt, mode):
            debug_calls.append((query, fmt, mode))

        with (
            patched_dep("TokenManager", Mock(return_value=Mock(name="tm"))),
            patched_dep("load_token_optional", Mock(return_value=("token-123", None))),
            patched_dep("PerplexityAPI", Mock(return_value=api)),
            patched_dep("handle_error", Mock(side_effect=_real_call)),
            patch(
                "perplexity_cli.query_runner.resolve_attachment_urls",
                return_value=[],
                autospec=True,
            ),
            patch(
                "perplexity_cli.query_runner.log_query_debug_context", side_effect=_capture_debug
            ),
            patch("perplexity_cli.query_runner.build_final_query", return_value="final query"),
        ):
            try:
                query_runner.run_query_command(
                    {"debug": False, "json": False, "timeout": 60, "schema": "no_schema"},
                    "question",
                    _default_options(stream=stream),
                )
            except SystemExit:
                pass
        return invocation, response_args, debug_calls

    def _run_with_capture(self, stream: bool):
        from tests.helpers.query_deps import patched_dep
        from tests.test_query_runner import _default_options

        invocation: list[dict[str, object]] = []
        response_args: list[tuple[object, ...]] = []
        api = Mock(name="api")
        api.__enter__ = Mock(return_value=api)
        api.__exit__ = Mock(return_value=False)
        api.get_complete_answer.return_value = Mock(text="answer text", references=[])
        api.submit_query.return_value = iter([])

        def _real_call(fn, *_args, **_kwargs):
            fn()

        monkey_patches = [
            patched_dep("TokenManager", Mock(return_value=Mock(name="tm"))),
            patched_dep("load_token_optional", Mock(return_value=("token-123", None))),
            patched_dep("PerplexityAPI", Mock(return_value=api)),
            patched_dep("handle_error", Mock(side_effect=_real_call)),
        ]
        import contextlib

        with contextlib.ExitStack() as stack:
            for ctx in monkey_patches:
                stack.enter_context(ctx)
            stack.enter_context(
                patch(
                    "perplexity_cli.query_runner.resolve_attachment_urls",
                    return_value=[],
                    autospec=True,
                )
            )
            stack.enter_context(
                patch("perplexity_cli.query_runner.build_final_query", return_value="final query")
            )
            stack.enter_context(
                patch.object(
                    query_runner,
                    "_log_session_invocation",
                    side_effect=lambda _logger, args: invocation.append(args),
                )
            )
            stack.enter_context(
                patch.object(
                    query_runner,
                    "_log_session_response",
                    side_effect=lambda _logger, outcome, start: response_args.append(
                        (outcome, start)
                    ),
                )
            )
            try:
                query_runner.run_query_command(
                    {"debug": False, "json": False, "timeout": 60, "schema": "no_schema"},
                    "question",
                    _default_options(stream=stream),
                )
            except SystemExit:
                pass
        return invocation, response_args

    def test_stream_mode_invocation_payload_is_exact(self):
        invocation, _response = self._run_with_capture(stream=True)
        assert invocation == [{"mode": "stream", "json": False, "stream": True}]

    def test_batch_mode_invocation_payload_is_exact(self):
        invocation, _response = self._run_with_capture(stream=False)
        assert invocation == [{"mode": "batch", "json": False, "stream": False}]

    def test_response_receives_real_start_time(self):
        _invocation, response = self._run_with_capture(stream=False)
        outcome, start = response[0]
        assert outcome == "ok"
        assert isinstance(start, float)
        assert start > 0.0

    def test_debug_context_mode_labels_are_exact(self):
        _invocation, _response, debug_batch = self._run(stream=False)
        assert debug_batch[0][2] == "batch"


class TestRunQueryCommandOptionPlumbing:
    """Every option must flow from QueryOptions to its consumer unchanged."""

    def test_all_options_reach_their_consumers(self, monkeypatch):
        from tests.helpers.query_deps import patched_dep
        from tests.test_query_runner import _default_options

        monkeypatch.setattr(query_runner, "_create_session_logger_safely", Mock(name="factory"))
        monkeypatch.setattr(query_runner, "_log_session_invocation", Mock(name="invocation"))
        monkeypatch.setattr(query_runner, "_log_session_response", Mock(name="response"))

        seen: dict[str, object] = {}

        def _capture_attachments(_query, attachments_str, _auth):
            seen["attachments_str"] = attachments_str
            return ["https://resolved.example/upload"]

        api = Mock(name="api")
        api.__enter__ = Mock(return_value=api)
        api.__exit__ = Mock(return_value=False)
        api.get_complete_answer.return_value = Mock(text="answer text", references=[])

        formatter = Mock(name="formatter")
        formatter.format_complete.return_value = "formatted answer"

        def _capture_formatter(output_format):
            seen["output_format"] = output_format
            return output_format, formatter

        def _real_call(fn, *_args, **_kwargs):
            fn()

        with (
            patched_dep("TokenManager", Mock(return_value=Mock(name="tm"))),
            patched_dep("load_token_optional", Mock(return_value=("token-123", None))),
            patched_dep("PerplexityAPI", Mock(return_value=api)),
            patched_dep("handle_error", Mock(side_effect=_real_call)),
            patch(
                "perplexity_cli.query_runner.resolve_attachment_urls",
                side_effect=_capture_attachments,
            ),
            patch(
                "perplexity_cli.query_runner.get_query_formatter", side_effect=_capture_formatter
            ),
            patch(
                "perplexity_cli.query_runner.parse_request_param_overrides",
                side_effect=lambda raw: (
                    seen.setdefault("request_param_overrides", raw),
                    {"parsed": True},
                )[1],
            ),
        ):
            options = _default_options(
                output_format="text",
                attachments="doc.pdf",
                model_preference="sonar-pro",
                request_param_overrides="mode=deep",
            )
            query_runner.run_query_command({"debug": False}, "question", options)

        assert seen["attachments_str"] == "doc.pdf"
        assert seen["output_format"] == "text"
        assert seen["request_param_overrides"] == "mode=deep"
        extra_params = api.get_complete_answer.call_args.kwargs["extra_params"]
        assert extra_params == (["https://resolved.example/upload"], "sonar-pro", {"parsed": True})
