"""Perplexity API endpoint abstractions.

This module provides high-level interfaces to Perplexity's private APIs.
All API-specific code is isolated here to enable rapid adaptation if APIs change.
"""

import uuid
from collections.abc import Iterator

from ..utils.config import get_query_endpoint
from .client import SSEClient
from .models import Answer, QueryParams, QueryRequest, SSEMessage, WebResult


class PerplexityAPI:
    """High-level interface to Perplexity API."""

    def __init__(
        self, token: str, cookies: dict[str, str] | None = None, timeout: int = 60
    ) -> None:
        """Initialise Perplexity API client.

        Args:
            token: Authentication JWT token.
            cookies: Optional browser cookies for Cloudflare bypass.
            timeout: Request timeout in seconds.
        """
        self.client = SSEClient(token=token, cookies=cookies, timeout=timeout)

    def submit_query(
        self,
        query: str,
        language: str = "en-US",
        timezone: str = "Europe/London",
    ) -> Iterator[SSEMessage]:
        """Submit a query to Perplexity and stream responses.

        Args:
            query: The user's query text.
            language: Language code (default: en-US).
            timezone: Timezone string (default: Europe/London).

        Yields:
            SSEMessage objects from the streaming response.

        Raises:
            httpx.HTTPStatusError: For HTTP errors (401, 403, 429, etc.).
            httpx.RequestError: For network/connection errors.
            ValueError: For malformed responses.
        """
        # Generate UUIDs for request tracking
        frontend_uuid = str(uuid.uuid4())
        frontend_context_uuid = str(uuid.uuid4())

        # Build query parameters
        params = QueryParams(
            language=language,
            timezone=timezone,
            frontend_uuid=frontend_uuid,
            frontend_context_uuid=frontend_context_uuid,
        )

        # Build request
        request = QueryRequest(query_str=query, params=params)

        # Submit query and stream responses
        query_endpoint = get_query_endpoint()
        for message_data in self.client.stream_post(query_endpoint, request.to_dict()):
            yield SSEMessage.from_dict(message_data)

    def get_complete_answer(self, query: str) -> Answer:
        """Submit a query and return the complete answer with references.

        This is a convenience method that handles the streaming response
        and returns the final answer text along with any web references.

        Args:
            query: The user's query text.

        Returns:
            Answer object containing text and references list.

        Raises:
            httpx.HTTPStatusError: For HTTP errors.
            httpx.RequestError: For network errors.
            ValueError: For malformed responses or if no answer is found.
        """
        final_answer = None
        references: list[WebResult] = []

        for message in self.submit_query(query):
            # Only extract from final message to avoid duplicates
            if message.final_sse_message:
                # Extract text from blocks in final message
                for block in message.blocks:
                    # Only get text from answer blocks (intended_usage: "ask_text")
                    if block.intended_usage == "ask_text":
                        text = self._extract_text_from_block(block.content)
                        if text:
                            final_answer = text
                            break

                # Extract web references from final message
                if message.web_results:
                    references = message.web_results

                break

        if final_answer is None:
            raise ValueError("No answer found in response")

        return Answer(text=final_answer, references=references)

    def _extract_text_from_block(self, block_content: dict) -> str | None:
        """Extract text from a block's content.

        Args:
            block_content: The block content dictionary.

        Returns:
            Extracted text, or None if no text found.
        """
        # Try different block structures based on actual API response

        # 1. Markdown block with chunks (most common for answers)
        if "markdown_block" in block_content:
            markdown_block = block_content["markdown_block"]
            if isinstance(markdown_block, dict) and "chunks" in markdown_block:
                chunks = markdown_block["chunks"]
                if isinstance(chunks, list):
                    # Join all chunks into complete text
                    return "".join(str(chunk) for chunk in chunks)

        # 2. Direct text field
        if "text" in block_content:
            return block_content["text"]

        # 3. Web results block (skip - these are sources, not answers)
        if "web_result_block" in block_content:
            # Don't extract snippets as answer text
            pass

        # 4. Diff block with patches
        if "diff_block" in block_content:
            diff_block = block_content["diff_block"]
            if isinstance(diff_block, dict) and "patches" in diff_block:
                for patch in diff_block["patches"]:
                    if isinstance(patch, dict) and "value" in patch:
                        value = patch["value"]
                        if isinstance(value, str):
                            return value
                        elif isinstance(value, dict) and "text" in value:
                            return value["text"]

        # 5. Answer block
        if "answer_block" in block_content:
            answer_block = block_content["answer_block"]
            if isinstance(answer_block, dict) and "text" in answer_block:
                return answer_block["text"]

        return None

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
