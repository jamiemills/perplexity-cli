"""Perplexity API endpoint abstractions.

This module provides high-level interfaces to Perplexity's private APIs.
All API-specific code is isolated here to enable rapid adaptation if APIs change.
"""

import uuid
from collections.abc import Iterator
from types import TracebackType

from ..utils.config import get_query_endpoint
from ..utils.exceptions import UpstreamSchemaError
from .client import SSEClient
from .models import Answer, Block, QueryParams, QueryRequest, SSEMessage, WebResult


class PerplexityAPI:
    """High-level interface to Perplexity API."""

    def __init__(
        self, token: str | None, cookies: dict[str, str] | None = None, timeout: int = 60
    ) -> None:
        """Initialise Perplexity API client.

        Args:
            token: Optional authentication JWT token.
            cookies: Optional browser cookies for Cloudflare bypass.
            timeout: Request timeout in seconds.
        """
        self.client = SSEClient(token=token, cookies=cookies, timeout=timeout)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self.client.close()

    def __enter__(self) -> "PerplexityAPI":
        """Enter context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit context manager, closing the HTTP client."""
        self.close()

    def submit_query(
        self,
        query: str,
        language: str = "en-US",
        timezone: str = "Europe/London",
        search_implementation_mode: str = "standard",
        attachments: list[str] | None = None,
    ) -> Iterator[SSEMessage]:
        """Submit a query to Perplexity and stream responses.

        Args:
            query: The user's query text.
            language: Language code (default: en-US).
            timezone: Timezone string (default: Europe/London).
            search_implementation_mode: Search mode ('standard' or 'multi_step' for deep research).
            attachments: Optional list of S3 URLs for file attachments.

        Yields:
            SSEMessage objects from the streaming response.

        Raises:
            PerplexityHTTPStatusError: For HTTP errors (401, 403, 429, etc.).
            PerplexityRequestError: For network/connection errors.
            UpstreamSchemaError: For malformed responses.
        """
        if not query.strip():
            raise ValueError("Query must not be empty")

        # Generate UUIDs for request tracking
        frontend_uuid = str(uuid.uuid4())
        frontend_context_uuid = str(uuid.uuid4())

        # Build query parameters
        params = QueryParams(
            language=language,
            timezone=timezone,
            frontend_uuid=frontend_uuid,
            frontend_context_uuid=frontend_context_uuid,
            search_implementation_mode=search_implementation_mode,
            attachments=attachments or [],
        )

        # Build request
        request = QueryRequest(query_str=query, params=params)

        # Submit query and stream responses
        query_endpoint = get_query_endpoint()
        for message_data in self.client.stream_post(query_endpoint, request.to_dict()):
            yield SSEMessage.from_dict(message_data)

    def get_complete_answer(
        self,
        query: str,
        search_implementation_mode: str = "standard",
        attachments: list[str] | None = None,
    ) -> Answer:
        """Submit a query and return the complete answer with references.

        This is a convenience method that handles the streaming response
        and returns the final answer text along with any web references.

        Args:
            query: The user's query text.
            search_implementation_mode: Search mode ('standard' or 'multi_step' for deep research).
            attachments: Optional list of S3 URLs for file attachments.

        Returns:
            Answer object containing text and references list.

        Raises:
            PerplexityHTTPStatusError: For HTTP errors.
            PerplexityRequestError: For network errors.
            UpstreamSchemaError: For malformed responses or if no answer is found.
        """
        final_answer = None
        references: list[WebResult] = []
        final_message: SSEMessage | None = None

        for message in self.submit_query(
            query,
            search_implementation_mode=search_implementation_mode,
            attachments=attachments,
        ):
            # Only extract from final message to avoid duplicates
            if message.final_sse_message:
                final_message = message
                final_answer = message.extract_answer_text()

                # Extract web references from final message
                if message.web_results:
                    references = message.web_results

                break

        if final_answer is None:
            if final_message is None:
                raise UpstreamSchemaError("No final SSE message found in upstream response")
            status = getattr(final_message, "status", "<missing>")
            if hasattr(final_message, "describe_block_usages"):
                block_usages = final_message.describe_block_usages()
            else:
                blocks = getattr(final_message, "blocks", [])
                block_usages = (
                    ",".join(getattr(block, "intended_usage", "<missing>") for block in blocks)
                    or "none"
                )
            raise UpstreamSchemaError(
                "No answer found in final upstream response: "
                f"status={status}, "
                f"block_usages={block_usages}"
            )

        return Answer(text=final_answer, references=references)

    def _extract_plan_block_info(self, block) -> dict | None:
        """Extract progress information from a plan block.

        Args:
            block: Block object that may contain plan information.

        Returns:
            Dictionary with progress info if this is a plan block, None otherwise.
        """
        return Block(
            intended_usage=getattr(block, "intended_usage", ""),
            content=getattr(block, "content", {}),
        ).extract_plan_info()

    def _extract_text_from_block(self, block_content: dict) -> str | None:
        """Extract text from a block's content.

        Args:
            block_content: The block content dictionary.

        Returns:
            Extracted text, or None if no text found.
        """
        return Block(intended_usage="", content=block_content).extract_text()

    def _format_references(self, references: list[WebResult]) -> str:
        """Format references for display.

        Args:
            references: List of WebResult objects to format.

        Returns:
            Formatted references string with numbered URLs.
        """
        if not references:
            return ""

        lines = []
        for i, ref in enumerate(references, 1):
            lines.append(f"[{i}] {ref.url}")

        return "\n".join(lines)
