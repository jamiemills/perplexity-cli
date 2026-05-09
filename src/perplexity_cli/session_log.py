"""NDJSON session logger for recording CLI invocations and responses."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SessionLogger:
    """Writes invocation and response events to an NDJSON session log file.

    The logger is a no-op if session logging is not enabled.
    """

    def __init__(self, session_id: str, *, enabled: bool = False) -> None:
        """Initialise the session logger.

        Args:
            session_id: Unique identifier for this session (typically a UUID4).
            enabled: Whether logging is active. When False, all methods are no-ops.
        """
        self._session_id = session_id
        self._enabled = enabled

    @staticmethod
    def get_sessions_dir() -> Path:
        """Return the sessions directory path.

        Uses $XDG_DATA_HOME/pxcli/sessions/ if set,
        otherwise ~/.local/share/pxcli/sessions/
        """
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            base = Path(xdg)
        else:
            base = Path.home() / ".local" / "share"
        return base / "pxcli" / "sessions"

    @staticmethod
    def is_enabled() -> bool:
        """Check if session logging is enabled via PXCLI_SESSION_LOG env var."""
        return os.environ.get("PXCLI_SESSION_LOG", "").lower() in ("true", "1", "yes")

    @classmethod
    def create(cls) -> SessionLogger:
        """Factory method: create a SessionLogger, auto-detecting enabled state."""
        return cls(
            session_id=str(uuid.uuid4()),
            enabled=cls.is_enabled(),
        )

    def log_invocation(self, command: str, args: dict[str, Any] | None = None) -> None:
        """Log a CLI invocation event."""
        if not self._enabled:
            return
        event: dict[str, Any] = {
            "type": "invocation",
            "ts": datetime.now(UTC).isoformat(),
            "session_id": self._session_id,
            "command": command,
            "args": args or {},
        }
        self._write_event(event)

    def log_response(
        self,
        ok: bool,
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
            "ok": ok,
            "duration_ms": duration_ms,
            "result_summary": result_summary,
        }
        self._write_event(event)

    def _write_event(self, event: dict[str, Any]) -> None:
        """Write a single NDJSON event line to the log file."""
        sessions_dir = self.get_sessions_dir()
        log_path = sessions_dir / f"{self._session_id}.ndjson"
        try:
            sessions_dir.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
                f.flush()
        except OSError:
            logger.warning("Failed to write session log to %s", log_path, exc_info=True)
