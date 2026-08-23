"""Tests for the NDJSON writer module."""

import io
import json
from datetime import datetime

import pytest

from perplexity_cli.ndjson import (
    ChunkEvent,
    NDJSONWriter,
    ProgressEvent,
    ResultEvent,
    StartEvent,
)


class TestNDJSONEventModels:
    """Tests for NDJSON event Pydantic models."""

    def test_start_event_type(self) -> None:
        event = StartEvent(command="search")
        assert event.type == "start"

    def test_chunk_event_type(self) -> None:
        event = ChunkEvent(text="hello")
        assert event.type == "chunk"

    def test_progress_event_type(self) -> None:
        event = ProgressEvent(message="Loading")
        assert event.type == "progress"

    def test_result_event_type(self) -> None:
        event = ResultEvent(ok=True, command="search", result={"key": "val"})
        assert event.type == "result"

    def test_event_has_timestamp(self) -> None:
        events = [
            StartEvent(command="search"),
            ChunkEvent(text="hello"),
            ProgressEvent(message="Loading"),
            ResultEvent(ok=True, command="search", result={}),
        ]
        for event in events:
            assert event.ts is not None
            assert isinstance(event.ts, str)

    def test_timestamp_is_iso8601(self) -> None:
        event = StartEvent(command="search")
        parsed = datetime.fromisoformat(event.ts)
        assert parsed is not None


class TestNDJSONWriter:
    """Tests for the NDJSONWriter class."""

    def test_write_event_produces_single_line(self) -> None:
        buf = io.StringIO()
        writer = NDJSONWriter(output=buf)
        writer.start("cmd")
        output = buf.getvalue()
        assert output.endswith("\n")
        assert output.count("\n") == 1

    def test_write_event_is_valid_json(self) -> None:
        buf = io.StringIO()
        writer = NDJSONWriter(output=buf)
        writer.chunk("hello")
        line = buf.getvalue().strip()
        parsed = json.loads(line)
        assert isinstance(parsed, dict)

    def test_start_writes_start_event(self) -> None:
        buf = io.StringIO()
        writer = NDJSONWriter(output=buf)
        writer.start("cmd")
        data = json.loads(buf.getvalue().strip())
        assert data["type"] == "start"
        assert data["command"] == "cmd"

    def test_chunk_writes_chunk_event(self) -> None:
        buf = io.StringIO()
        writer = NDJSONWriter(output=buf)
        writer.chunk("hello")
        data = json.loads(buf.getvalue().strip())
        assert data["type"] == "chunk"
        assert data["text"] == "hello"

    def test_progress_writes_progress_event(self) -> None:
        buf = io.StringIO()
        writer = NDJSONWriter(output=buf)
        writer.progress("Loading", 50.0)
        data = json.loads(buf.getvalue().strip())
        assert data["type"] == "progress"
        assert data["message"] == "Loading"
        assert data["percent"] == pytest.approx(50.0)

    def test_result_writes_result_event(self) -> None:
        buf = io.StringIO()
        writer = NDJSONWriter(output=buf)
        writer.result(ok=True, command="cmd", result={"key": "val"})
        data = json.loads(buf.getvalue().strip())
        assert data["type"] == "result"
        assert data["ok"] is True
        assert data["command"] == "cmd"
        assert data["result"] == {"key": "val"}

    def test_multiple_events_produce_multiple_lines(self) -> None:
        buf = io.StringIO()
        writer = NDJSONWriter(output=buf)
        writer.start("cmd")
        writer.chunk("a")
        writer.chunk("b")
        lines = buf.getvalue().strip().split("\n")
        assert len(lines) == 3

    def test_event_order_convention(self) -> None:
        buf = io.StringIO()
        writer = NDJSONWriter(output=buf)
        writer.start("cmd")
        writer.chunk("a")
        writer.chunk("b")
        writer.result(ok=True, command="cmd", result={})
        lines = buf.getvalue().strip().split("\n")
        types = [json.loads(line)["type"] for line in lines]
        assert types == ["start", "chunk", "chunk", "result"]


class TestNDJSONTimestampsUTC:
    """Event timestamps are UTC-stamped ISO 8601 strings."""

    def test_event_timestamp_carries_utc_offset(self) -> None:
        """Serialised timestamps resolve to a zero UTC offset."""
        from datetime import timedelta

        buf = io.StringIO()
        writer = NDJSONWriter(output=buf)
        writer.write_event(StartEvent(command="pxcli"))
        event = json.loads(buf.getvalue().splitlines()[0])
        parsed = datetime.fromisoformat(event["ts"])
        assert parsed.utcoffset() == timedelta(0)


class TestNDJSONWriterResultExtras:
    """Tests for the result event's meta/next_actions/schema handling."""

    def test_result_includes_meta_and_next_actions(self) -> None:
        """Provided meta and next actions are serialised on the result line."""
        meta = {"duration_ms": 5}
        actions = [{"command": "follow-up"}]
        buf = io.StringIO()
        writer = NDJSONWriter(output=buf)
        writer.result(
            ok=True,
            command="pxcli ask",
            result={"a": 1},
            extras=(meta, actions, False),
        )
        payload = json.loads(buf.getvalue())
        assert payload["meta"] == meta
        assert payload["next_actions"] == actions
        assert payload["ok"] is True

    def test_result_defaults_next_actions_to_empty_list(self) -> None:
        """Missing next actions fall back to an empty list."""
        buf = io.StringIO()
        writer = NDJSONWriter(output=buf)
        writer.result(ok=False, command="cmd", result={}, extras=(None, None, False))
        payload = json.loads(buf.getvalue())
        assert payload["next_actions"] == []
        assert payload["meta"] is None

    def test_result_with_schema_prepends_schema_key(self) -> None:
        """Schema inclusion embeds a $schema key ahead of the event fields."""
        buf = io.StringIO()
        writer = NDJSONWriter(output=buf)
        writer.result(ok=True, command="cmd", result={}, extras=(None, None, True))
        payload = json.loads(buf.getvalue())
        assert next(iter(payload)) == "$schema"
