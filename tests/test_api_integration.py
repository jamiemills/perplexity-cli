"""Integration tests for Perplexity API client.

Contains two categories:
1. **Hermetic** (``TestHermeticAPIIntegration``) — uses the loopback harness
   server to test the full client→SSE protocol stack without network access.
2. **Real API** (``TestPerplexityAPIIntegration``, ``TestAPIErrorHandling``) —
   exercises the live Perplexity API; skipped unless
   ``RUN_REAL_API_TESTS=1``.
"""

from __future__ import annotations

import os

import pytest

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import Answer, QueryInput
from tests.support.protocol_server import ProtocolServer, QueryResponse


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

        assert len(messages) > 0
        first_msg = messages[0]
        assert hasattr(first_msg, "backend_uuid")
        assert hasattr(first_msg, "status")
        assert hasattr(first_msg, "blocks")

    @pytest.mark.usefixtures("harness_config")
    def test_submit_query_completes(self, harness_server: ProtocolServer) -> None:
        """Test that query stream completes with final message."""
        harness_server.query_response = QueryResponse(
            sse_chunks=harness_server.make_query_sse_chunks("Paris is the capital"),
        )

        api = PerplexityAPI(token=None)
        messages = list(api.submit_query(QueryInput(query="What is the capital of France?")))

        assert len(messages) > 0
        has_final = any(msg.final_sse_message for msg in messages)
        assert has_final

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
        has_blocks = False
        for message in api.submit_query(QueryInput(query="What is machine learning?")):
            if message.blocks and len(message.blocks) > 0:
                has_blocks = True
                break

        assert has_blocks

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
        assert len(answer.text) > 0

    @pytest.mark.usefixtures("harness_config")
    def test_multiple_queries_same_client(self, harness_server: ProtocolServer) -> None:
        """Test multiple queries with same API client instance."""
        harness_server.query_response = QueryResponse(
            sse_chunks=harness_server.make_query_sse_chunks("answer 1"),
        )

        api = PerplexityAPI(token=None)
        answer1 = api.get_complete_answer("What is 1+1?")

        assert isinstance(answer1, Answer)
        assert len(answer1.text) > 0

        harness_server.query_response = QueryResponse(
            sse_chunks=harness_server.make_query_sse_chunks("answer 2"),
        )
        answer2 = api.get_complete_answer("What is 2+2?")

        assert isinstance(answer2, Answer)
        assert len(answer2.text) > 0

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


@pytest.mark.real_api
@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("RUN_REAL_API_TESTS") != "1",
    reason="Skipped: set RUN_REAL_API_TESTS=1 to run real API tests",
)
class TestPerplexityAPIIntegration:
    """Integration tests with actual Perplexity API."""

    @pytest.fixture
    def api(self) -> PerplexityAPI:
        """Create PerplexityAPI instance with real token and cookies."""
        from perplexity_cli.auth.token_manager import TokenManager

        tm = TokenManager()
        token, cookies = tm.load_token()

        if not token:
            pytest.skip("No token found. Run: python tests/save_auth_token.py")

        return PerplexityAPI(token=token, cookies=cookies)

    def test_submit_query_returns_messages(self, api: PerplexityAPI) -> None:
        """Test that submit_query returns SSE messages."""
        messages = list(api.submit_query(QueryInput(query="What is 2+2?")))

        assert len(messages) > 0

        first_msg = messages[0]
        assert hasattr(first_msg, "backend_uuid")
        assert hasattr(first_msg, "status")
        assert hasattr(first_msg, "blocks")

    def test_submit_query_completes(self, api: PerplexityAPI) -> None:
        """Test that query stream completes with final message."""
        messages = list(api.submit_query(QueryInput(query="What is the capital of France?")))

        assert len(messages) > 0

        has_final = any(msg.final_sse_message for msg in messages)
        assert has_final

    def test_get_complete_answer_simple_query(self, api: PerplexityAPI) -> None:
        """Test getting complete answer for simple query."""
        answer = api.get_complete_answer("What is 2+2?")

        assert isinstance(answer, Answer)
        assert len(answer.text) > 0
        assert "4" in answer.text or "four" in answer.text.lower()

    def test_get_complete_answer_returns_text(self, api: PerplexityAPI) -> None:
        """Test that get_complete_answer returns answer text."""
        answer = api.get_complete_answer("What is the capital of France?")

        assert isinstance(answer, Answer)
        assert len(answer.text) > 0
        assert "Paris" in answer.text or "paris" in answer.text.lower()

    def test_streaming_messages_have_blocks(self, api: PerplexityAPI) -> None:
        """Test that streaming messages contain blocks."""
        has_blocks = False

        for message in api.submit_query(QueryInput(query="What is machine learning?")):
            if message.blocks and len(message.blocks) > 0:
                has_blocks = True
                break

        assert has_blocks

    def test_query_with_default_parameters(self, api: PerplexityAPI) -> None:
        """Test query works with default parameters."""
        answer = api.get_complete_answer("What is Python?")

        assert isinstance(answer, Answer)
        assert len(answer.text) > 0

    def test_multiple_queries_same_client(self, api: PerplexityAPI) -> None:
        """Test multiple queries with same API client instance."""
        answer1 = api.get_complete_answer("What is 1+1?")
        answer2 = api.get_complete_answer("What is 2+2?")

        assert isinstance(answer1, Answer)
        assert isinstance(answer2, Answer)
        assert len(answer1.text) > 0
        assert len(answer2.text) > 0


@pytest.mark.real_api
@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("RUN_REAL_API_TESTS") != "1",
    reason="Skipped: set RUN_REAL_API_TESTS=1 to run real API tests",
)
class TestAPIErrorHandling:
    """Test error handling with actual API."""

    def test_empty_query_handling(self) -> None:
        """Test handling of empty query."""
        from perplexity_cli.auth.token_manager import TokenManager

        tm = TokenManager()
        token, cookies = tm.load_token()

        if not token:
            pytest.skip("No token found")

        api = PerplexityAPI(token=token, cookies=cookies)

        with pytest.raises(ValueError, match="Query must not be empty"):
            api.get_complete_answer("")
