"""Component-level tests for attachment URL inclusion in API query requests.

These tests verify the mapping from ``attachment_urls`` in
:class:`~perplexity_cli.api.models.QueryInput` to the ``attachments``
field in the outbound ``QueryRequest`` JSON payload.  The SSE transport
is mocked so the test is deterministic and network-independent.

.. note::

    These are **not** end-to-end tests; they exercise the API-layer
    request-serialization scope only.  For hermetic protocol integration
    through the loopback harness, see
    ``tests/test_attachment_protocol_integration.py``.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import QueryInput

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


def _extract_sent_attachments(mock_client: MagicMock) -> list[str]:
    """Return the ``attachments`` list from the request body captured by
    the mocked ``SSEClient.stream_post`` call."""
    call_args = mock_client.stream_post.call_args
    assert call_args is not None, "stream_post was not called"
    request_data = call_args[0][1]
    return request_data["params"]["attachments"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAttachmentQueryRequestComposition:
    """Tests that attachment URLs flow from QueryInput into the outbound
    query request body at the API endpoint layer."""

    @pytest.fixture(autouse=True)
    def _mock_sse_transport(self) -> Generator[MagicMock, None, None]:
        """Patch SSEClient so API calls never touch the network."""
        patcher = patch("perplexity_cli.api.endpoints.SSEClient")
        mock_client_class = patcher.start()
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        self._mock_client = mock_client
        yield mock_client
        patcher.stop()

    # -- Single file --------------------------------------------------------

    def test_single_attachment_url_included_in_request(self) -> None:
        s3_url = "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/test_single.txt"

        self._mock_client.stream_post.return_value = iter(
            _make_sse_final_with_attachments([s3_url]),
        )

        api = PerplexityAPI(token="test-token")
        list(api.submit_query(QueryInput(query="Test", attachment_urls=[s3_url])))

        attachments = _extract_sent_attachments(self._mock_client)
        assert attachments == [s3_url]

    # -- Multiple files -----------------------------------------------------

    def test_multiple_attachment_urls_included_in_request(self) -> None:
        s3_urls = [
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file1.txt",
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file2.md",
        ]

        self._mock_client.stream_post.return_value = iter(
            _make_sse_final_with_attachments(s3_urls),
        )

        api = PerplexityAPI(token="test-token")
        list(api.submit_query(QueryInput(query="Test", attachment_urls=s3_urls)))

        attachments = _extract_sent_attachments(self._mock_client)
        assert attachments == s3_urls

    # -- Order preservation -------------------------------------------------

    def test_attachment_url_order_preserved(self) -> None:
        ordered_urls = [f"https://s3.example.com/file_{i}.txt" for i in range(3)]

        self._mock_client.stream_post.return_value = iter(
            _make_sse_final_with_attachments(ordered_urls),
        )

        api = PerplexityAPI(token="test-token")
        list(api.submit_query(QueryInput(query="Test", attachment_urls=ordered_urls)))

        attachments = _extract_sent_attachments(self._mock_client)
        assert attachments == ordered_urls
        assert attachments[0] == "https://s3.example.com/file_0.txt"
        assert attachments[2] == "https://s3.example.com/file_2.txt"

    # -- Request structure --------------------------------------------------

    def test_query_request_top_level_keys(self) -> None:
        s3_url = "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/test_api_spec.txt"

        self._mock_client.stream_post.return_value = iter([])

        api = PerplexityAPI(token="test-token")
        try:
            list(api.submit_query(QueryInput(query="Test", attachment_urls=[s3_url])))
        except StopIteration:
            pass

        call_args = self._mock_client.stream_post.call_args
        assert call_args is not None
        request_data = call_args[0][1]

        assert "query_str" in request_data
        assert "params" in request_data
        assert request_data["query_str"] == "Test"

    def test_query_params_structure_with_attachments(self) -> None:
        s3_url = "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/test_api_spec.txt"

        self._mock_client.stream_post.return_value = iter([])

        api = PerplexityAPI(token="test-token")
        try:
            list(api.submit_query(QueryInput(query="Test", attachment_urls=[s3_url])))
        except StopIteration:
            pass

        call_args = self._mock_client.stream_post.call_args
        request_data = call_args[0][1]
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

    def test_empty_attachment_urls_sends_empty_list(self) -> None:
        self._mock_client.stream_post.return_value = iter(
            _make_sse_final_with_attachments([]),
        )

        api = PerplexityAPI(token="test-token")
        list(api.submit_query(QueryInput(query="Test", attachment_urls=[])))

        attachments = _extract_sent_attachments(self._mock_client)
        assert attachments == []
