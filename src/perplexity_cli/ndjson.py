"""NDJSON (Newline-Delimited JSON) writer for streaming structured output.

When ``--json --stream`` are used together, the CLI outputs one JSON object per line
instead of a single buffered envelope. Each line is a typed event.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import IO, Any

from pydantic import BaseModel, Field


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()


class NDJSONEvent(BaseModel):
    """Base event with type and timestamp."""

    type: str
    ts: str = Field(default_factory=_now_iso)


class StartEvent(NDJSONEvent):
    """Emitted when a command begins execution."""

    type: str = "start"
    command: str


class ProgressEvent(NDJSONEvent):
    """Emitted to report progress during execution."""

    type: str = "progress"
    message: str
    percent: float | None = None


class ChunkEvent(NDJSONEvent):
    """Emitted for each chunk of streamed text."""

    type: str = "chunk"
    text: str


class ResultEvent(NDJSONEvent):
    """Emitted as the final event containing the full result envelope."""

    type: str = "result"
    ok: bool
    command: str
    result: dict[str, Any]
    meta: dict[str, Any] | None = None
    next_actions: list[dict[str, Any]] = []


class NDJSONWriter:
    """Writes typed NDJSON events to a file-like object."""

    def __init__(self, output: IO[str] | None = None) -> None:
        """Initialise with output stream (defaults to sys.stdout)."""
        self._output = output if output is not None else sys.stdout

    def write_event(self, event: NDJSONEvent) -> None:
        """Serialise event as JSON and write as a single line."""
        line = json.dumps(event.model_dump(mode="json"))
        self._output.write(line + "\n")
        self._output.flush()

    def start(self, command: str) -> None:
        """Write a start event."""
        self.write_event(StartEvent(command=command))

    def progress(self, message: str, percent: float | None = None) -> None:
        """Write a progress event."""
        self.write_event(ProgressEvent(message=message, percent=percent))

    def chunk(self, text: str) -> None:
        """Write a chunk event."""
        self.write_event(ChunkEvent(text=text))

    def result(
        self,
        ok: bool,
        command: str,
        result: dict[str, Any],
        meta: dict[str, Any] | None = None,
        next_actions: list[dict[str, Any]] | None = None,
        include_schema: bool = False,
    ) -> None:
        """Write a result event (final line).

        When *include_schema* is ``True``, a ``$schema`` key containing the
        ResultEvent JSON Schema is prepended to the serialised output.
        """
        event = ResultEvent(
            ok=ok,
            command=command,
            result=result,
            meta=meta,
            next_actions=next_actions if next_actions is not None else [],
        )
        data = event.model_dump(mode="json")
        if include_schema:
            data = {"$schema": ResultEvent.model_json_schema(), **data}
        line = json.dumps(data)
        self._output.write(line + "\n")
        self._output.flush()
