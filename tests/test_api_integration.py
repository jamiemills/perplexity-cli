"""Integration tests for Perplexity API client."""

import httpx
import pytest

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import Answer
from perplexity_cli.auth.token_manager import TokenManager


@pytest.mark.integration
class TestPerplexityAPIIntegration:
    """Integration tests with actual Perplexity API."""

    @pytest.fixture
    def api(self):
        """Create PerplexityAPI instance with real token and cookies."""
        tm = TokenManager()
        token, cookies = tm.load_token()

        if not token:
            pytest.skip("No token found. Run: python tests/save_auth_token.py")

        return PerplexityAPI(token=token, cookies=cookies)

    def test_submit_query_returns_messages(self, api):
        """Test that submit_query returns SSE messages."""
        messages = list(api.submit_query("What is 2+2?"))

        assert len(messages) > 0, "Should receive at least one SSE message"

        # Check first message structure
        first_msg = messages[0]
        assert hasattr(first_msg, "backend_uuid")
        assert hasattr(first_msg, "status")
        assert hasattr(first_msg, "blocks")

    def test_submit_query_completes(self, api):
        """Test that query stream completes with final message."""
        messages = list(api.submit_query("What is the capital of France?"))

        # Should receive multiple messages
        assert len(messages) > 0, "Should receive at least one message"

        # At least one message should have final_sse_message: true
        has_final = any(msg.final_sse_message for msg in messages)
        assert has_final, "At least one message should be marked as final"

    def test_get_complete_answer_simple_query(self, api):
        """Test getting complete answer for simple query."""
        answer = api.get_complete_answer("What is 2+2?")

        assert isinstance(answer, Answer)
        assert len(answer.text) > 0, "Answer should not be empty"
        # The answer should mention "4" or "four"
        assert "4" in answer.text or "four" in answer.text.lower()

    def test_get_complete_answer_returns_text(self, api):
        """Test that get_complete_answer returns answer text."""
        answer = api.get_complete_answer("What is the capital of France?")

        assert isinstance(answer, Answer)
        assert len(answer.text) > 0
        # Answer should mention Paris
        assert "Paris" in answer.text or "paris" in answer.text.lower()

    def test_streaming_messages_have_blocks(self, api):
        """Test that streaming messages contain blocks."""
        has_blocks = False

        for message in api.submit_query("What is machine learning?"):
            if message.blocks and len(message.blocks) > 0:
                has_blocks = True
                break

        assert has_blocks, "At least one message should contain blocks"

    def test_query_with_different_language(self, api):
        """Test query works with default parameters."""
        # Test with simple query
        answer = api.get_complete_answer("What is Python?")

        assert isinstance(answer, Answer)
        assert len(answer.text) > 0

    def test_multiple_queries_same_client(self, api):
        """Test multiple queries with same API client instance."""
        answer1 = api.get_complete_answer("What is 1+1?")
        answer2 = api.get_complete_answer("What is 2+2?")

        assert isinstance(answer1, Answer)
        assert isinstance(answer2, Answer)
        assert len(answer1.text) > 0
        assert len(answer2.text) > 0


@pytest.mark.integration
class TestAPIErrorHandling:
    """Test error handling with actual API."""

    def test_empty_query_handling(self):
        """Test handling of empty query."""
        tm = TokenManager()
        token = tm.load_token()

        if not token:
            pytest.skip("No token found")

        api = PerplexityAPI(token=token)

        # Empty query should either return empty answer or raise error
        try:
            answer = api.get_complete_answer("")
            # If it succeeds, answer should be an Answer object
            assert isinstance(answer, Answer)
        except (ValueError, httpx.HTTPStatusError):
            # Or it might raise an error, which is also acceptable
            pass
