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
