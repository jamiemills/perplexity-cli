"""Tests for the NDJSON session logger."""

from __future__ import annotations

import json
import logging
import stat
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from perplexity_cli.session_log import SessionLogger

_POSIX = sys.platform != "win32"


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

    def test_default_logger_is_disabled(self) -> None:
        from perplexity_cli.session_log import SessionLogger

        logger = SessionLogger("test-session")

        assert logger._enabled is False


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
        assert datetime.fromisoformat(ts).utcoffset().total_seconds() == 0

    def test_invocation_preserves_unicode_and_writes_one_ndjson_line(
        self, logger: SessionLogger
    ) -> None:
        logger.log_invocation("ask", {"query": "cafe\N{LATIN SMALL LETTER E WITH ACUTE}"})

        log_file = logger.get_sessions_dir() / "test-session-123.ndjson"
        raw = log_file.read_text()
        assert raw.endswith("\n")
        assert "cafe\N{LATIN SMALL LETTER E WITH ACUTE}" in raw
        assert json.loads(raw) == {
            "type": "invocation",
            "ts": json.loads(raw)["ts"],
            "session_id": "test-session-123",
            "command": "ask",
            "args": {"query": "cafe\N{LATIN SMALL LETTER E WITH ACUTE}"},
        }

    def test_response_boundary_preserves_summary_and_boolean_status(
        self, logger: SessionLogger
    ) -> None:
        logger.log_response(success="not-ok", duration_ms=0, result_summary="")

        event = json.loads((logger.get_sessions_dir() / "test-session-123.ndjson").read_text())
        assert event["type"] == "response"
        assert event["ok"] is False
        assert event["duration_ms"] == 0
        assert event["result_summary"] == ""
        assert datetime.fromisoformat(event["ts"]).utcoffset().total_seconds() == 0


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

    def test_sessions_dir_xdg(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from perplexity_cli.session_log import SessionLogger

        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert SessionLogger.get_sessions_dir() == tmp_path / "pxcli" / "sessions"


class TestSessionIdValidation:
    """Tests for the safe ASCII session ID grammar, enforced even when disabled."""

    @pytest.mark.parametrize(
        "invalid_id",
        [
            "",
            ".",
            "..",
            "abc.def",
            "abc/def",
            "abc\\def",
            "abc def",
            "abc\tdef",
            "abc\ndef",
            "h\u00e9llo",
            "\u043f\u0440\u0438\u0432\u0435\u0442",
            "a" * 65,
            "-leading-dash",
            "_leading-underscore",
        ],
    )
    def test_invalid_session_id_rejected_even_when_disabled(self, invalid_id: str) -> None:
        from perplexity_cli.session_log import SessionLogger

        with pytest.raises(ValueError, match="Invalid session ID") as exc_info:
            SessionLogger(invalid_id, enabled="disabled")
        if invalid_id:
            assert invalid_id not in str(exc_info.value)

    @pytest.mark.parametrize(
        "valid_id",
        [
            "a",
            "0",
            "Z",
            "abc123",
            "a-b_c",
            "A_B-c0",
            "a" * 64,
        ],
    )
    def test_valid_session_id_accepted(self, valid_id: str) -> None:
        from perplexity_cli.session_log import SessionLogger

        logger = SessionLogger(valid_id, enabled="disabled")
        assert logger._session_id == valid_id


@pytest.mark.skipif(not _POSIX, reason="POSIX mode bits are not asserted on Windows")
class TestSessionFilePermissions:
    """Tests for 0700 sessions dir and 0600 log file modes."""

    def test_sessions_dir_mode_0700(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from perplexity_cli.session_log import SessionLogger

        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        logger = SessionLogger("perm-session", enabled="enabled")
        logger.log_invocation("ask")
        sessions_dir = logger.get_sessions_dir()
        assert stat.S_IMODE(sessions_dir.stat().st_mode) == 0o700

    def test_session_file_mode_0600(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from perplexity_cli.session_log import SessionLogger

        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        logger = SessionLogger("perm-session", enabled="enabled")
        logger.log_invocation("ask")
        log_file = logger.get_sessions_dir() / "perm-session.ndjson"
        assert stat.S_IMODE(log_file.stat().st_mode) == 0o600


class TestSymlinkRejection:
    """Tests that pre-existing symlinks are never followed."""

    @staticmethod
    def _make_symlink(source: Path, target: Path) -> None:
        try:
            source.symlink_to(target)
        except (OSError, NotImplementedError, PermissionError):
            pytest.skip("symlink creation is not supported on this platform")

    def test_log_file_symlink_not_followed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        from perplexity_cli.session_log import SessionLogger

        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        sessions_dir = tmp_path / "pxcli" / "sessions"
        sessions_dir.mkdir(parents=True)
        target = tmp_path / "target.ndjson"
        target.write_text("ORIGINAL")
        log_path = sessions_dir / "symlink-session.ndjson"
        self._make_symlink(log_path, target)

        with caplog.at_level(logging.WARNING):
            logger = SessionLogger("symlink-session", enabled="enabled")
            logger.log_invocation("ask")

        assert target.read_text() == "ORIGINAL"
        assert log_path.is_symlink()
        assert "Failed to write" in caplog.text
        assert "<redacted>" in caplog.text
        assert str(tmp_path) not in caplog.text

    def test_sessions_dir_symlink_not_followed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        from perplexity_cli.session_log import SessionLogger

        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        real_dir = tmp_path / "real-sessions"
        real_dir.mkdir()
        sessions_dir = tmp_path / "pxcli" / "sessions"
        sessions_dir.parent.mkdir(parents=True)
        self._make_symlink(sessions_dir, real_dir)

        with caplog.at_level(logging.WARNING):
            logger = SessionLogger("dir-symlink-session", enabled="enabled")
            logger.log_invocation("ask")

        assert list(real_dir.iterdir()) == []
        assert "Refusing" in caplog.text
        assert "<redacted>" in caplog.text
        assert str(tmp_path) not in caplog.text


class TestWriteFailureRedacted:
    """Tests that write failures warn with a redacted path and never raise."""

    def test_write_failure_warns_with_redacted_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        from perplexity_cli.session_log import SessionLogger

        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        logger = SessionLogger("fail-session", enabled="enabled")

        def _raise(*_args, **_kwargs):
            raise OSError(13, "Permission denied")

        monkeypatch.setattr(
            "perplexity_cli.session_log.SessionLogger._open_log_file",
            staticmethod(_raise),
        )
        with caplog.at_level(logging.WARNING):
            logger.log_invocation("ask")  # must not raise

        assert caplog.records[0].message == (
            "Failed to write session log to <redacted>/fail-session.ndjson (errno 13)"
        )
        assert str(tmp_path) not in caplog.text
        assert not (logger.get_sessions_dir() / "fail-session.ndjson").exists()

    def test_empty_path_uses_generic_redaction_marker(self) -> None:
        from perplexity_cli.session_log import _redact_path

        assert _redact_path(Path()) == "<redacted-path>"


class TestCredentialRedaction:
    """Tests for recursive redaction of credential-shaped argument keys."""

    def _write_and_read(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        session_id: str,
        args: dict[str, object],
    ) -> dict[str, object]:
        from perplexity_cli.session_log import SessionLogger

        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        logger = SessionLogger(session_id, enabled="enabled")
        logger.log_invocation("ask", args)
        log_file = logger.get_sessions_dir() / f"{session_id}.ndjson"
        return json.loads(log_file.read_text().strip())

    def test_credential_keys_redacted_but_query_preserved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        event = self._write_and_read(
            tmp_path,
            monkeypatch,
            "redact-session",
            {"query": "how do I use the api", "token": "sk-abc123", "api_key": "key-456"},
        )
        args = event["args"]
        assert args["query"] == "how do I use the api"
        assert args["token"] == "[REDACTED]"
        assert args["api_key"] == "[REDACTED]"

    def test_nested_credential_redaction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        event = self._write_and_read(
            tmp_path,
            monkeypatch,
            "nested-session",
            {
                "user": {
                    "name": "bob",
                    "password": "hunter2",
                    "settings": {"cookie": "a=1"},
                }
            },
        )
        user = event["args"]["user"]
        assert user["name"] == "bob"
        assert user["password"] == "[REDACTED]"
        assert user["settings"]["cookie"] == "[REDACTED]"

    def test_case_insensitive_redaction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        event = self._write_and_read(
            tmp_path,
            monkeypatch,
            "case-session",
            {"Authorization": "Bearer xyz", "API_KEY": "abc", "Cookie": "sid=1"},
        )
        args = event["args"]
        assert args["Authorization"] == "[REDACTED]"
        assert args["API_KEY"] == "[REDACTED]"
        assert args["Cookie"] == "[REDACTED]"

    def test_list_values_redacted_recursively(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        event = self._write_and_read(
            tmp_path,
            monkeypatch,
            "list-session",
            {"headers": [{"cookie": "sid=1"}, {"x": "y"}]},
        )
        headers = event["args"]["headers"]
        assert headers[0]["cookie"] == "[REDACTED]"
        assert headers[1]["x"] == "y"

    def test_ordinary_text_remains_untouched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        event = self._write_and_read(
            tmp_path,
            monkeypatch,
            "text-session",
            {"query": "what is tokenization and cookies"},
        )
        assert event["args"]["query"] == "what is tokenization and cookies"

    @pytest.mark.parametrize(
        "key",
        ["token", "TOKEN", "api-key", "authorization", "COOKIE", "password", "secret"],
    )
    def test_all_credential_key_forms_are_redacted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
    ) -> None:
        event = self._write_and_read(tmp_path, monkeypatch, "credential-forms", {key: "sensitive"})
        assert event["args"][key] == "[REDACTED]"

    def test_nested_tuple_and_scalar_values_are_preserved(self) -> None:
        from perplexity_cli.session_log import _redact_args

        value = {"items": ("plain", 3), "none": None}
        assert _redact_args(value) == value

    def test_response_failure_is_written_as_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from perplexity_cli.session_log import SessionLogger

        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        logger = SessionLogger("failed-response", enabled="enabled")
        logger.log_response(success="error", duration_ms=7, result_summary="failed")
        event = json.loads(
            (logger.get_sessions_dir() / "failed-response.ndjson").read_text().strip()
        )
        assert event["ok"] is False
        assert event["duration_ms"] == 7
        assert event["result_summary"] == "failed"
