"""Tests for data models."""

from perplexity_cli.api.models import Answer, SSEMessage, WebResult


class TestWebResult:
    """Test WebResult model."""

    def test_web_result_creation(self):
        """Test WebResult creation with all fields."""
        result = WebResult(
            name="Example",
            url="https://example.com",
            snippet="Example snippet",
            timestamp="2025-11-09T00:00:00Z",
        )
        assert result.name == "Example"
        assert result.url == "https://example.com"
        assert result.snippet == "Example snippet"
        assert result.timestamp == "2025-11-09T00:00:00Z"

    def test_web_result_creation_without_optional(self):
        """Test WebResult creation without optional timestamp."""
        result = WebResult(name="Test", url="https://test.com", snippet="Test snippet")
        assert result.name == "Test"
        assert result.url == "https://test.com"
        assert result.snippet == "Test snippet"
        assert result.timestamp is None

    def test_web_result_from_dict(self):
        """Test WebResult creation from dictionary."""
        data = {
            "name": "Python.org",
            "url": "https://www.python.org",
            "snippet": "Official Python website",
            "timestamp": "2025-11-09",
        }
        result = WebResult.from_dict(data)
        assert result.name == "Python.org"
        assert result.url == "https://www.python.org"
        assert result.snippet == "Official Python website"
        assert result.timestamp == "2025-11-09"

    def test_web_result_from_dict_missing_optional(self):
        """Test WebResult from_dict with missing optional fields."""
        data = {"name": "Test", "url": "https://test.com", "snippet": "Test"}
        result = WebResult.from_dict(data)
        assert result.name == "Test"
        assert result.url == "https://test.com"
        assert result.timestamp is None

    def test_web_result_from_dict_missing_required(self):
        """Test WebResult from_dict with missing required fields."""
        data = {"name": "Test"}
        result = WebResult.from_dict(data)
        assert result.name == "Test"
        assert result.url == ""
        assert result.snippet == ""


class TestAnswer:
    """Test Answer model."""

    def test_answer_creation_with_text_only(self):
        """Test Answer creation with text only."""
        answer = Answer(text="This is the answer")
        assert answer.text == "This is the answer"
        assert answer.references == []

    def test_answer_creation_with_references(self):
        """Test Answer creation with text and references."""
        refs = [
            WebResult(name="Ref1", url="https://ref1.com", snippet="First reference"),
            WebResult(name="Ref2", url="https://ref2.com", snippet="Second reference"),
        ]
        answer = Answer(text="Answer text", references=refs)
        assert answer.text == "Answer text"
        assert len(answer.references) == 2
        assert answer.references[0].url == "https://ref1.com"
        assert answer.references[1].url == "https://ref2.com"


class TestSSEMessageWithWebResults:
    """Test SSEMessage web results extraction."""

    def test_sse_message_without_web_results(self):
        """Test SSEMessage creation without web results."""
        data = {
            "backend_uuid": "uuid1",
            "context_uuid": "ctx1",
            "uuid": "msg1",
            "frontend_context_uuid": "fctx1",
            "display_model": "gpt4",
            "mode": "copilot",
            "thread_url_slug": None,
            "status": "COMPLETE",
            "text_completed": True,
            "blocks": [],
            "final_sse_message": True,
        }
        msg = SSEMessage.from_dict(data)
        assert msg.web_results is None

    def test_sse_message_with_web_results(self):
        """Test SSEMessage creation with web results."""
        data = {
            "backend_uuid": "uuid1",
            "context_uuid": "ctx1",
            "uuid": "msg1",
            "frontend_context_uuid": "fctx1",
            "display_model": "gpt4",
            "mode": "copilot",
            "thread_url_slug": None,
            "status": "COMPLETE",
            "text_completed": True,
            "blocks": [
                {
                    "intended_usage": "web_results",
                    "web_result_block": {
                        "web_results": [
                            {
                                "name": "Wikipedia",
                                "url": "https://wikipedia.org",
                                "snippet": "Wikipedia article",
                            },
                            {
                                "name": "Example",
                                "url": "https://example.com",
                                "snippet": "Example website",
                            },
                        ]
                    },
                }
            ],
            "final_sse_message": True,
        }
        msg = SSEMessage.from_dict(data)
        assert msg.web_results is not None
        assert len(msg.web_results) == 2
        assert msg.web_results[0].url == "https://wikipedia.org"
        assert msg.web_results[1].url == "https://example.com"
        assert msg.web_results[0].name == "Wikipedia"
        assert msg.web_results[1].name == "Example"

    def test_sse_message_with_empty_web_results(self):
        """Test SSEMessage with empty web results array."""
        data = {
            "backend_uuid": "uuid1",
            "context_uuid": "ctx1",
            "uuid": "msg1",
            "frontend_context_uuid": "fctx1",
            "display_model": "gpt4",
            "mode": "copilot",
            "thread_url_slug": None,
            "status": "COMPLETE",
            "text_completed": True,
            "blocks": [
                {
                    "intended_usage": "web_results",
                    "web_result_block": {"web_results": []},
                }
            ],
            "final_sse_message": True,
        }
        msg = SSEMessage.from_dict(data)
        # Should set web_results to empty list
        assert msg.web_results == []

    def test_sse_message_multiple_blocks_only_web_results(self):
        """Test SSEMessage extracts only from web_results block."""
        data = {
            "backend_uuid": "uuid1",
            "context_uuid": "ctx1",
            "uuid": "msg1",
            "frontend_context_uuid": "fctx1",
            "display_model": "gpt4",
            "mode": "copilot",
            "thread_url_slug": None,
            "status": "COMPLETE",
            "text_completed": True,
            "blocks": [
                {
                    "intended_usage": "ask_text",
                    "markdown_block": {"chunks": ["Text"]},
                },
                {
                    "intended_usage": "web_results",
                    "web_result_block": {
                        "web_results": [
                            {
                                "name": "Source",
                                "url": "https://source.com",
                                "snippet": "Source content",
                            }
                        ]
                    },
                },
            ],
            "final_sse_message": True,
        }
        msg = SSEMessage.from_dict(data)
        assert msg.web_results is not None
        assert len(msg.web_results) == 1
        assert msg.web_results[0].url == "https://source.com"
