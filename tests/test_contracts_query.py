"""Tests for contracts.query types."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from perplexity_cli.contracts.query import QueryInput, TraceContext


class TestQueryInput:
    """Test QueryInput dataclass."""

    def test_basic_construction(self) -> None:
        qi = QueryInput("hello")
        assert qi.query == "hello"
        assert qi.attachment_urls == []
        assert qi.model_preference is None
        assert qi.request_params == {}

    def test_with_attachments_and_model(self) -> None:
        qi = QueryInput(
            "query",
            attachment_urls=["s3://foo"],
            model_preference="pplx_pro",
        )
        assert qi.attachment_urls == ["s3://foo"]
        assert qi.model_preference == "pplx_pro"

    def test_with_request_params(self) -> None:
        qi = QueryInput("query", request_params={"key": "val"})
        assert qi.request_params == {"key": "val"}

    def test_defensive_copy(self) -> None:
        urls = ["a", "b"]
        qi = QueryInput("q", attachment_urls=urls)
        urls.append("c")
        assert qi.attachment_urls == ["a", "b"]


class TestTraceContext:
    """Test TraceContext dataclass."""

    def test_defaults(self) -> None:
        tc = TraceContext()
        assert tc.trace_id is None
        assert tc.start_time is None

    def test_with_values(self) -> None:
        tc = TraceContext(trace_id="abc123", start_time=42.0)
        assert tc.trace_id == "abc123"
        assert tc.start_time == 42.0

    def test_frozen(self) -> None:
        tc = TraceContext(trace_id="x")
        with pytest.raises(FrozenInstanceError):
            tc.trace_id = "y"


__all__ = [
    "TestQueryInput",
    "TestTraceContext",
]
