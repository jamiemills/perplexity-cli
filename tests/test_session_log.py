"""Tests for the NDJSON session logger."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from perplexity_cli.session_log import SessionLogger


class TestSessionLoggerDisabled:
    """Tests for disabled session logger (no-op behaviour)."""

    def test_disabled_does_not_create_file(self, tmp_path: Path) -> None:
        from perplexity_cli.session_log import SessionLogger

        logger = SessionLogger("test-session", enabled="disabled")
        logger.log_invocation("ask", {"query": "hello"})
        sessions_dir = tmp_path / "pxcli" / "sessions"
        assert not sessions_dir.exists()

    def test_disabled_log_invocation_is_noop(self) -> None:
        from perplexity_cli.session_log import SessionLogger

        logger = SessionLogger("test-session", enabled="disabled")
        logger.log_invocation("ask", {"query": "hello"})  # should not raise

    def test_disabled_log_response_is_noop(self) -> None:
        from perplexity_cli.session_log import SessionLogger

        logger = SessionLogger("test-session", enabled="disabled")
        logger.log_response(
            success="ok", duration_ms=100, result_summary="done"
        )  # should not raise


class TestSessionLoggerEnabled:
    """Tests for enabled session logger."""

    @pytest.fixture()
    def logger(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SessionLogger:
        from perplexity_cli.session_log import SessionLogger

        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        return SessionLogger("test-session-123", enabled="enabled")

    def test_creates_session_file(self, logger: SessionLogger) -> None:
        logger.log_invocation("ask")
        log_file = logger.get_sessions_dir() / "test-session-123.ndjson"
        assert log_file.exists()

    def test_log_invocation_writes_valid_ndjson(self, logger: SessionLogger) -> None:
        logger.log_invocation("ask", {"query": "hello"})
        log_file = logger.get_sessions_dir() / "test-session-123.ndjson"
        line = log_file.read_text().strip()
        event = json.loads(line)
        assert event["type"] == "invocation"
        assert event["command"] == "ask"
        assert event["args"] == {"query": "hello"}
        assert event["session_id"] == "test-session-123"

    def test_log_response_writes_valid_ndjson(self, logger: SessionLogger) -> None:
        logger.log_response(success="ok", duration_ms=150, result_summary="completed")
        log_file = logger.get_sessions_dir() / "test-session-123.ndjson"
        line = log_file.read_text().strip()
        event = json.loads(line)
        assert event["type"] == "response"
        assert event["ok"] is True
        assert event["duration_ms"] == 150
        assert event["result_summary"] == "completed"
        assert event["session_id"] == "test-session-123"

    def test_both_events_recorded(self, logger: SessionLogger) -> None:
        logger.log_invocation("ask", {"query": "hello"})
        logger.log_response(success="ok", duration_ms=200)
        log_file = logger.get_sessions_dir() / "test-session-123.ndjson"
        lines = [line for line in log_file.read_text().strip().split("\n") if line]
        assert len(lines) == 2

    def test_event_has_timestamp(self, logger: SessionLogger) -> None:
        logger.log_invocation("ask")
        log_file = logger.get_sessions_dir() / "test-session-123.ndjson"
        event = json.loads(log_file.read_text().strip())
        ts = event["ts"]
        # Should parse as ISO 8601
        datetime.fromisoformat(ts)


class TestSessionLoggerFactory:
    """Tests for factory method and environment detection."""

    def test_is_enabled_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from perplexity_cli.session_log import SessionLogger

        monkeypatch.setenv("PXCLI_SESSION_LOG", "true")
        assert SessionLogger.is_enabled() is True

    def test_is_enabled_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from perplexity_cli.session_log import SessionLogger

        monkeypatch.delenv("PXCLI_SESSION_LOG", raising=False)
        assert SessionLogger.is_enabled() is False

    def test_sessions_dir_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from perplexity_cli.session_log import SessionLogger

        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        expected = Path.home() / ".local" / "share" / "pxcli" / "sessions"
        assert SessionLogger.get_sessions_dir() == expected

    def test_sessions_dir_xdg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from perplexity_cli.session_log import SessionLogger

        monkeypatch.setenv("XDG_DATA_HOME", "/tmp/test")
        assert SessionLogger.get_sessions_dir() == Path("/tmp/test/pxcli/sessions")
