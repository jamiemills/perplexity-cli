"""Component-level tests for attachment URL inclusion in API query requests.

These tests verify the mapping from ``attachment_urls`` in
:class:`~perplexity_cli.api.models.QueryInput` to the ``attachments``
field in the outbound ``QueryRequest`` JSON payload.  The SSE transport
is replaced with a typed outer-boundary fake so the test is deterministic
and network-independent.

.. note::

    These are **not** end-to-end tests; they exercise the API-layer
    request-serialization scope only.  For hermetic protocol integration
    through the loopback harness, see
    ``tests/test_attachment_protocol_integration.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import QueryInput

_SSE_CLIENT_TARGET = "perplexity_cli.api.endpoints.SSEClient"


class FakeSSEClient:
    """Typed outer-boundary fake for ``SSEClient`` used by the API layer.

    Records every outbound ``stream_post`` request body and yields a
    configurable iterable of SSE message payloads.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialise the fake with no captured requests yet."""
        self.stream_posts: list[tuple[str, dict[str, object]]] = []
        self.messages: list[dict[str, object]] = []

    def set_messages(self, messages: list[dict[str, object]]) -> None:
        """Configure the SSE message payloads yielded by ``stream_post``."""
        self.messages = list(messages)

    def stream_post(self, url: str, json_data: dict[str, object]) -> object:
        """Record the request and yield the configured SSE messages."""
        self.stream_posts.append((url, json_data))
        return iter(self.messages)

    def close(self) -> None:
        """No-op close to satisfy the real client interface."""


@pytest.fixture
def mock_sse_client(monkeypatch: pytest.MonkeyPatch) -> FakeSSEClient:
    """Patch ``SSEClient`` at the endpoint boundary with a typed fake."""
    fake_client = FakeSSEClient()
    monkeypatch.setattr(_SSE_CLIENT_TARGET, lambda *args, **kwargs: fake_client)
    return fake_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sse_final_with_attachments(
    attachment_urls: list[str],
) -> list[dict[str, object]]:
    """Return a single SSE final message with the given *attachment_urls*."""
    return [
        {
            "backend_uuid": "be-1",
            "context_uuid": "ctx-1",
            "uuid": "req-1",
            "frontend_context_uuid": "fctx-1",
            "display_model": "turbo",
            "mode": "COPILOT",
            "status": "COMPLETED",
            "text_completed": True,
            "final_sse_message": True,
            "blocks": [
                {
                    "intended_usage": "ask_text",
                    "markdown_block": {
                        "chunks": ["Test response"],
                        "answer": "Test response",
                    },
                }
            ],
            "attachments": attachment_urls,
        },
    ]


def _extract_sent_attachments(fake_client: FakeSSEClient) -> list[str]:
    """Return the ``attachments`` list from the last captured request body."""
    assert fake_client.stream_posts, "stream_post was not called"
    request_data = fake_client.stream_posts[-1][1]
    return request_data["params"]["attachments"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAttachmentQueryRequestComposition:
    """Tests that attachment URLs flow from QueryInput into the outbound
    query request body at the API endpoint layer."""

    # -- Single file --------------------------------------------------------

    def test_single_attachment_url_included_in_request(self, mock_sse_client) -> None:
        """A single S3 URL is serialized into the query request body."""
        s3_url = "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/test_single.txt"
        mock_sse_client.set_messages(_make_sse_final_with_attachments([s3_url]))

        api = PerplexityAPI(token="test-token")
        list(api.submit_query(QueryInput(query="Test", attachment_urls=[s3_url])))

        attachments = _extract_sent_attachments(mock_sse_client)
        assert attachments == [s3_url]

    # -- Multiple files -----------------------------------------------------

    def test_multiple_attachment_urls_included_in_request(self, mock_sse_client) -> None:
        """Multiple S3 URLs are serialized in order into the query request."""
        s3_urls = [
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file1.txt",
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file2.md",
        ]
        mock_sse_client.set_messages(_make_sse_final_with_attachments(s3_urls))

        api = PerplexityAPI(token="test-token")
        list(api.submit_query(QueryInput(query="Test", attachment_urls=s3_urls)))

        attachments = _extract_sent_attachments(mock_sse_client)
        assert attachments == s3_urls

    # -- Order preservation -------------------------------------------------

    def test_attachment_url_order_preserved(self, mock_sse_client) -> None:
        """Attachment URL ordering is preserved through request serialization."""
        ordered_urls = [f"https://s3.example.com/file_{i}.txt" for i in range(3)]
        mock_sse_client.set_messages(_make_sse_final_with_attachments(ordered_urls))

        api = PerplexityAPI(token="test-token")
        list(api.submit_query(QueryInput(query="Test", attachment_urls=ordered_urls)))

        attachments = _extract_sent_attachments(mock_sse_client)
        assert attachments == ordered_urls
        assert attachments[0] == "https://s3.example.com/file_0.txt"
        assert attachments[2] == "https://s3.example.com/file_2.txt"

    # -- Request structure --------------------------------------------------

    def test_query_request_top_level_keys(self, mock_sse_client) -> None:
        """The outbound request carries query_str and params top-level keys."""
        s3_url = "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/test_api_spec.txt"

        api = PerplexityAPI(token="test-token")
        list(api.submit_query(QueryInput(query="Test", attachment_urls=[s3_url])))

        assert mock_sse_client.stream_posts
        request_data = mock_sse_client.stream_posts[-1][1]
        assert "query_str" in request_data
        assert "params" in request_data
        assert request_data["query_str"] == "Test"

    def test_query_params_structure_with_attachments(self, mock_sse_client) -> None:
        """params.attachments holds plain https URL strings."""
        s3_url = "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/test_api_spec.txt"

        api = PerplexityAPI(token="test-token")
        list(api.submit_query(QueryInput(query="Test", attachment_urls=[s3_url])))

        request_data = mock_sse_client.stream_posts[-1][1]
        params = request_data["params"]

        assert "attachments" in params
        assert isinstance(params["attachments"], list)
        assert "language" in params
        assert "timezone" in params

        attachment = params["attachments"][0]
        assert isinstance(attachment, str)
        assert attachment == s3_url
        assert attachment.startswith("https://")

    # -- Empty attachments --------------------------------------------------

    def test_empty_attachment_urls_sends_empty_list(self, mock_sse_client) -> None:
        """No attachment URLs serialize as an empty attachments list."""
        mock_sse_client.set_messages(_make_sse_final_with_attachments([]))

        api = PerplexityAPI(token="test-token")
        list(api.submit_query(QueryInput(query="Test", attachment_urls=[])))

        attachments = _extract_sent_attachments(mock_sse_client)
        assert attachments == []
