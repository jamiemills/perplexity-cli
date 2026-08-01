"""Hermetic integration tests for the Perplexity API client protocol chain.

Exercises the full client→SSE protocol stack against the local loopback
harness server.  No real network and no real credentials; every test is
loopback-only and therefore marked ``hermetic_integration``.
"""

from __future__ import annotations

import json

import pytest

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import Answer, QueryInput, SSEMessage
from tests.support.protocol_server import ProtocolServer, QueryResponse

pytestmark = [pytest.mark.hermetic_integration]


class TestHermeticAPIIntegration:
    """Integration tests using the loopback harness (no network)."""

    @pytest.mark.usefixtures("harness_config")
    def test_submit_query_returns_messages(self, harness_server: ProtocolServer) -> None:
        """Test that submit_query returns SSE messages from the harness."""
        harness_server.query_response = QueryResponse(
            sse_chunks=harness_server.make_query_sse_chunks("Hello from harness"),
        )

        api = PerplexityAPI(token=None)
        messages = list(api.submit_query(QueryInput(query="What is 2+2?")))

        assert len(messages) == 2
        first_msg = messages[0]
        assert isinstance(first_msg, SSEMessage)
        assert first_msg.backend_uuid == "be-1"
        assert first_msg.status == "IN_PROGRESS"
        assert first_msg.blocks == []
        assert first_msg.final_sse_message is False

        assert harness_server.request_count == 1
        request_body = json.loads(harness_server.last_request_body)
        assert request_body["query_str"] == "What is 2+2?"
        assert request_body["params"]["model_preference"] == "pplx_pro"
        assert request_body["params"]["search_implementation_mode"] == "standard"
        assert request_body["params"]["attachments"] == []

    @pytest.mark.usefixtures("harness_config")
    def test_submit_query_completes(self, harness_server: ProtocolServer) -> None:
        """Test that query stream completes with final message."""
        harness_server.query_response = QueryResponse(
            sse_chunks=harness_server.make_query_sse_chunks("Paris is the capital"),
        )

        api = PerplexityAPI(token=None)
        messages = list(api.submit_query(QueryInput(query="What is the capital of France?")))

        assert len(messages) == 2
        assert messages[-1].final_sse_message is True

    @pytest.mark.usefixtures("harness_config")
    def test_get_complete_answer_simple_query(self, harness_server: ProtocolServer) -> None:
        """Test getting complete answer for simple query."""
        harness_server.query_response = QueryResponse(
            sse_chunks=harness_server.make_query_sse_chunks("2+2 equals 4"),
        )

        api = PerplexityAPI(token=None)
        answer = api.get_complete_answer("What is 2+2?")

        assert isinstance(answer, Answer)
        assert "4" in answer.text

    @pytest.mark.usefixtures("harness_config")
    def test_get_complete_answer_returns_text(self, harness_server: ProtocolServer) -> None:
        """Test that get_complete_answer returns answer text."""
        harness_server.query_response = QueryResponse(
            sse_chunks=harness_server.make_query_sse_chunks("The capital is Paris"),
        )

        api = PerplexityAPI(token=None)
        answer = api.get_complete_answer("What is the capital of France?")

        assert isinstance(answer, Answer)
        assert "Paris" in answer.text

    @pytest.mark.usefixtures("harness_config")
    def test_streaming_messages_have_blocks(self, harness_server: ProtocolServer) -> None:
        """Test that streaming messages contain blocks."""
        harness_server.query_response = QueryResponse(
            sse_chunks=harness_server.make_query_sse_chunks("machine learning answer"),
        )

        api = PerplexityAPI(token=None)
        messages = list(api.submit_query(QueryInput(query="What is machine learning?")))
        blocks = [block for message in messages for block in message.blocks]

        assert len(messages) == 2
        assert len(blocks) == 1
        assert [block.intended_usage for block in blocks] == ["ask_text"]
        assert [block.extract_text() for block in blocks] == ["machine learning answer"]

    @pytest.mark.usefixtures("harness_config")
    def test_get_complete_answer_different_model_preference(
        self, harness_server: ProtocolServer
    ) -> None:
        """Test query with a model preference parameter."""
        harness_server.query_response = QueryResponse(
            sse_chunks=harness_server.make_query_sse_chunks("Python is a programming language"),
        )

        api = PerplexityAPI(token=None)
        answer = api.get_complete_answer("What is Python?")

        assert isinstance(answer, Answer)
        assert answer.text == "Python is a programming language"

    @pytest.mark.usefixtures("harness_config")
    def test_multiple_queries_same_client(self, harness_server: ProtocolServer) -> None:
        """Test multiple queries with same API client instance."""
        harness_server.query_response = QueryResponse(
            sse_chunks=harness_server.make_query_sse_chunks("answer 1"),
        )

        api = PerplexityAPI(token=None)
        answer1 = api.get_complete_answer("What is 1+1?")

        assert isinstance(answer1, Answer)
        assert answer1.text == "answer 1"

        harness_server.query_response = QueryResponse(
            sse_chunks=harness_server.make_query_sse_chunks("answer 2"),
        )
        answer2 = api.get_complete_answer("What is 2+2?")

        assert isinstance(answer2, Answer)
        assert answer2.text == "answer 2"
        assert harness_server.request_count == 2

    @pytest.mark.usefixtures("harness_config")
    def test_empty_query_raises_valueerror(self, harness_server: ProtocolServer) -> None:
        """Empty query raises ValueError before making any request."""
        harness_server.query_response = QueryResponse(
            sse_chunks=harness_server.make_query_sse_chunks("unused"),
        )

        api = PerplexityAPI(token=None)
        with pytest.raises(ValueError, match="Query must not be empty"):
            api.get_complete_answer("")

        assert harness_server.request_count == 0
