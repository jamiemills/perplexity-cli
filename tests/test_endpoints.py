"""Tests for Perplexity API endpoints."""

from unittest.mock import Mock, patch

import pytest

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import Answer, SSEMessage, WebResult


class TestPerplexityAPIGetCompleteAnswer:
    """Test get_complete_answer method."""

    @patch("perplexity_cli.api.endpoints.PerplexityAPI.submit_query")
    def test_get_complete_answer_text_only(self, mock_submit):
        """Test get_complete_answer returns text without references."""
        # Create mock SSE message with text but no web results
        mock_message = Mock(spec=SSEMessage)
        mock_message.final_sse_message = True
        mock_message.blocks = [
            Mock(
                intended_usage="ask_text",
                content={"markdown_block": {"chunks": ["This is ", "the answer"]}},
            )
        ]
        mock_message.web_results = None

        mock_submit.return_value = [mock_message]

        api = PerplexityAPI(token="test-token")
        result = api.get_complete_answer("test query")

        assert isinstance(result, Answer)
        assert result.text == "This is the answer"
        assert result.references == []

    @patch("perplexity_cli.api.endpoints.PerplexityAPI.submit_query")
    def test_get_complete_answer_with_references(self, mock_submit):
        """Test get_complete_answer returns text with references."""
        web_refs = [
            WebResult(name="Wiki", url="https://wiki.org", snippet="Wikipedia"),
            WebResult(
                name="Official",
                url="https://official.org",
                snippet="Official site",
            ),
        ]

        mock_message = Mock(spec=SSEMessage)
        mock_message.final_sse_message = True
        mock_message.blocks = [
            Mock(
                intended_usage="ask_text",
                content={"markdown_block": {"chunks": ["Complete answer"]}},
            )
        ]
        mock_message.web_results = web_refs

        mock_submit.return_value = [mock_message]

        api = PerplexityAPI(token="test-token")
        result = api.get_complete_answer("test query")

        assert isinstance(result, Answer)
        assert result.text == "Complete answer"
        assert len(result.references) == 2
        assert result.references[0].url == "https://wiki.org"
        assert result.references[1].url == "https://official.org"

    @patch("perplexity_cli.api.endpoints.PerplexityAPI.submit_query")
    def test_get_complete_answer_ignores_non_final_messages(self, mock_submit):
        """Test that non-final messages are ignored."""
        # Create mock messages - intermediate and final
        intermediate_message = Mock(spec=SSEMessage)
        intermediate_message.final_sse_message = False

        final_message = Mock(spec=SSEMessage)
        final_message.final_sse_message = True
        final_message.blocks = [
            Mock(
                intended_usage="ask_text",
                content={"markdown_block": {"chunks": ["Final answer"]}},
            )
        ]
        final_message.web_results = None

        mock_submit.return_value = [intermediate_message, final_message]

        api = PerplexityAPI(token="test-token")
        result = api.get_complete_answer("test query")

        assert result.text == "Final answer"

    @patch("perplexity_cli.api.endpoints.PerplexityAPI.submit_query")
    def test_get_complete_answer_no_answer_raises_error(self, mock_submit):
        """Test that ValueError is raised when no answer is found."""
        mock_message = Mock(spec=SSEMessage)
        mock_message.final_sse_message = True
        mock_message.blocks = []  # No blocks

        mock_submit.return_value = [mock_message]

        api = PerplexityAPI(token="test-token")
        with pytest.raises(ValueError, match="No answer found"):
            api.get_complete_answer("test query")

    @patch("perplexity_cli.api.endpoints.PerplexityAPI.submit_query")
    def test_get_complete_answer_extracts_from_multiple_chunks(self, mock_submit):
        """Test text extraction from multiple chunks."""
        mock_message = Mock(spec=SSEMessage)
        mock_message.final_sse_message = True
        mock_message.blocks = [
            Mock(
                intended_usage="ask_text",
                content={
                    "markdown_block": {"chunks": ["This ", "is ", "a ", "multi-chunk ", "answer"]}
                },
            )
        ]
        mock_message.web_results = None

        mock_submit.return_value = [mock_message]

        api = PerplexityAPI(token="test-token")
        result = api.get_complete_answer("test query")

        assert result.text == "This is a multi-chunk answer"


class TestPerplexityAPIFormatReferences:
    """Test _format_references method."""

    def test_format_references_empty_list(self):
        """Test formatting empty references list."""
        api = PerplexityAPI(token="test-token")
        result = api._format_references([])
        assert result == ""

    def test_format_references_single_reference(self):
        """Test formatting single reference."""
        ref = WebResult(name="Example", url="https://example.com", snippet="Example")
        api = PerplexityAPI(token="test-token")
        result = api._format_references([ref])
        assert result == "[1] https://example.com"

    def test_format_references_multiple_references(self):
        """Test formatting multiple references."""
        refs = [
            WebResult(name="First", url="https://first.com", snippet="First"),
            WebResult(name="Second", url="https://second.com", snippet="Second"),
            WebResult(name="Third", url="https://third.com", snippet="Third"),
        ]
        api = PerplexityAPI(token="test-token")
        result = api._format_references(refs)

        lines = result.split("\n")
        assert len(lines) == 3
        assert lines[0] == "[1] https://first.com"
        assert lines[1] == "[2] https://second.com"
        assert lines[2] == "[3] https://third.com"

    def test_format_references_preserves_urls(self):
        """Test that URLs are preserved exactly as provided."""
        refs = [
            WebResult(
                name="Complex",
                url="https://example.com/path?query=value&other=test#anchor",
                snippet="Complex URL",
            ),
        ]
        api = PerplexityAPI(token="test-token")
        result = api._format_references(refs)

        assert result == "[1] https://example.com/path?query=value&other=test#anchor"

    def test_format_references_duplicate_urls(self):
        """Test formatting with duplicate URLs (should keep all)."""
        refs = [
            WebResult(name="First", url="https://duplicate.com", snippet="First"),
            WebResult(name="Second", url="https://duplicate.com", snippet="Second"),
        ]
        api = PerplexityAPI(token="test-token")
        result = api._format_references(refs)

        lines = result.split("\n")
        assert len(lines) == 2
        assert lines[0] == "[1] https://duplicate.com"
        assert lines[1] == "[2] https://duplicate.com"
