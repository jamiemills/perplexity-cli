"""NDJSON session logger for recording CLI invocations and responses.

Credential-shaped argument keys are recursively redacted before any event is
written, and failure paths are logged through path redaction only.
"""

from __future__ import annotations

import errno
import json
import logging
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO, cast

logger = logging.getLogger(__name__)

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

_CREDENTIAL_KEY_TOKENS = (
    "token",
    "authorization",
    "cookie",
    "password",
    "secret",
    "api_key",
)

_REDACTION_MARKER = "[REDACTED]"

_SESSIONS_DIR_MODE = 0o700
_LOG_FILE_MODE = 0o600


class InvalidSessionIDError(ValueError):
    """Raised when a session ID violates the safe ASCII grammar."""


def _redact_path(value: str | Path) -> str:
    """Redact a local path for logging, keeping only the final component.

    Mirrors the ``utils.logging.redact_path`` convention without importing the
    shared adapter layer from this application-layer module.
    """
    path = Path(value)
    if path.name:
        return str(Path("<redacted>") / path.name)
    return "<redacted-path>"


def _is_credential_key(key: str) -> bool:
    """Return whether a key name is credential-shaped, case-insensitively."""
    normalised = key.lower().replace("-", "_")
    return any(token in normalised for token in _CREDENTIAL_KEY_TOKENS)


def _redact_value(key: str, value: Any) -> Any:
    """Redact a single key/value pair, recursing into nested containers."""
    if _is_credential_key(key):
        return _REDACTION_MARKER
    return _redact_args(value)


def _redact_args(args: object) -> object:
    """Recursively replace values of credential-shaped keys with a marker."""
    if isinstance(args, dict):
        args_map = cast("dict[Any, Any]", args)
        redacted_dict: dict[Any, Any] = {}
        for key, value in args_map.items():
            redacted_dict[key] = _redact_value(str(key), value)
        return redacted_dict
    if isinstance(args, list):
        args_list = cast("list[Any]", args)
        redacted_list: list[Any] = []
        for value in args_list:
            redacted_list.append(_redact_args(value))
        return redacted_list
    return args


class SessionLogger:
    """Writes invocation and response events to an NDJSON session log file.

    The logger is a no-op if session logging is not enabled. Session IDs are
    validated against a strict ASCII grammar even when logging is disabled.
    """

    def __init__(self, session_id: str, *, enabled: str = "disabled") -> None:
        """Initialise the session logger.

        Args:
            session_id: Unique identifier for this session (typically a UUID4).
            enabled: ``"enabled"`` or ``"disabled"``. When ``"disabled"``, all methods are no-ops.

        Raises:
            ValueError: If ``session_id`` is outside the safe ASCII grammar.
        """
        self._validate_session_id(session_id)
        self._session_id = session_id
        self._enabled = enabled == "enabled"

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        """Raise ``ValueError`` for any session ID outside the safe grammar.

        The error is deliberately non-reflective so rejected identifiers are
        never echoed back into logs or caller-facing messages.
        """
        if _SESSION_ID_RE.fullmatch(session_id) is None:
            msg = "Invalid session ID"
            raise InvalidSessionIDError(msg)

    @staticmethod
    def get_sessions_dir() -> Path:
        """Return the sessions directory path.

        Uses $XDG_DATA_HOME/pxcli/sessions/ if set,
        otherwise ~/.local/share/pxcli/sessions/
        """
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg) if xdg else Path.home() / ".local" / "share"
        return base / "pxcli" / "sessions"

    @staticmethod
    def is_enabled() -> bool:
        """Check if session logging is enabled via PXCLI_SESSION_LOG env var."""
        return os.environ.get("PXCLI_SESSION_LOG", "").lower() in {"true", "1", "yes"}

    @classmethod
    def create(cls) -> SessionLogger:
        """Factory method: create a SessionLogger, auto-detecting enabled state."""
        return cls(
            session_id=str(uuid.uuid4()),
            enabled="enabled" if cls.is_enabled() else "disabled",
        )

    def log_invocation(self, command: str, args: dict[str, Any] | None = None) -> None:
        """Log a CLI invocation event with credential-shaped args redacted."""
        if not self._enabled:
            return
        event: dict[str, Any] = {
            "type": "invocation",
            "ts": datetime.now(UTC).isoformat(),
            "session_id": self._session_id,
            "command": command,
            "args": _redact_args(args or {}),
        }
        self._write_event(event)

    def log_response(
        self,
        success: str,
        duration_ms: int,
        result_summary: str | None = None,
    ) -> None:
        """Log a CLI response event."""
        if not self._enabled:
            return
        event: dict[str, Any] = {
            "type": "response",
            "ts": datetime.now(UTC).isoformat(),
            "session_id": self._session_id,
            "ok": success == "ok",
            "duration_ms": duration_ms,
            "result_summary": result_summary,
        }
        self._write_event(event)

    def _write_event(self, event: dict[str, Any]) -> None:
        """Write a single NDJSON event line to the log file."""
        sessions_dir = self.get_sessions_dir()
        log_path = sessions_dir / f"{self._session_id}.ndjson"
        if not self._prepare_sessions_dir(sessions_dir):
            return
        try:
            with self._open_log_file(log_path) as log_file:
                log_file.write(json.dumps(event, ensure_ascii=False) + "\n")
                log_file.flush()
        except OSError as exc:
            logger.warning(
                "Failed to write session log to %s (errno %s)",
                _redact_path(log_path),
                exc.errno,
            )

    @staticmethod
    def _prepare_sessions_dir(sessions_dir: Path) -> bool:
        """Create the sessions directory, refusing a symlinked directory.

        Returns:
            True if the directory is safe and ready, False otherwise.
        """
        if sessions_dir.is_symlink():
            logger.warning(
                "Refusing to write session log through symlinked directory %s",
                _redact_path(sessions_dir),
            )
            return False
        try:
            sessions_dir.mkdir(parents=True, exist_ok=True, mode=_SESSIONS_DIR_MODE)
        except OSError as exc:
            logger.warning(
                "Failed to create session log directory %s (errno %s)",
                _redact_path(sessions_dir),
                exc.errno,
            )
            return False
        return True

    @staticmethod
    def _open_log_file(log_path: Path) -> TextIO:
        """Open the session log append-only at 0600 without following symlinks."""
        if log_path.is_symlink():
            msg = "Refusing to write session log through a symlink"
            raise OSError(errno.ELOOP, msg)
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        no_follow = getattr(  # nosemgrep: getattr-with-string-literal  # owner: security; reason: platform-optional O_NOFOLLOW constant lookup
            os, "O_NOFOLLOW", 0
        )
        descriptor = os.open(log_path, flags | no_follow, _LOG_FILE_MODE)
        return os.fdopen(descriptor, "a", encoding="utf-8")
