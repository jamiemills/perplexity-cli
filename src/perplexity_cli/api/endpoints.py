"""Perplexity API endpoint abstractions.

This module provides high-level interfaces to Perplexity's private APIs.
All API-specific code is isolated here to enable rapid adaptation if APIs change.
"""

import uuid
from collections.abc import Iterator
from types import TracebackType

from ..auth.models import AuthContext
from ..utils.config import get_query_endpoint
from ..utils.exceptions import UpstreamSchemaError
from .client import SSEClient
from .models import Answer, QueryInput, QueryParams, QueryRequest, SSEMessage


class PerplexityAPI:
    """High-level interface to Perplexity API."""

    def __init__(
        self, token: str | None, cookies: dict[str, str] | None = None, timeout: int | None = None
    ) -> None:
        """Initialise Perplexity API client.

        Args:
            token: Optional authentication JWT token.
            cookies: Optional browser cookies for Cloudflare bypass.
            timeout: Request timeout in seconds (default from config/defaults).
        """
        self.client = SSEClient(auth=AuthContext(token=token, cookies=cookies), timeout=timeout)

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
        query_input: QueryInput,
        search_implementation_mode: str = "standard",
    ) -> Iterator[SSEMessage]:
        """Submit a query to Perplexity and stream responses.

        Args:
            query_input: The query text, optional attachment URLs, and
                optional model preference.
            search_implementation_mode: Search mode ('standard' or
                'multi_step' for deep research).

        Yields:
            SSEMessage objects from the streaming response.

        Raises:
            PerplexityHTTPStatusError: For HTTP errors (401, 403, 429, etc.).
            PerplexityRequestError: For network/connection errors.
            UpstreamSchemaError: For malformed responses.
        """
        if not query_input.query.strip():
            raise ValueError("Query must not be empty")

        # Generate UUIDs for request tracking
        frontend_uuid = str(uuid.uuid4())
        frontend_context_uuid = str(uuid.uuid4())

        # Build query parameters
        effective_model = query_input.model_preference or "pplx_pro"
        params = QueryParams(
            frontend_uuid=frontend_uuid,
            frontend_context_uuid=frontend_context_uuid,
            search_implementation_mode=search_implementation_mode,
            attachments=query_input.attachment_urls or [],
            model_preference=effective_model,
        )

        # Build request
        request = QueryRequest(query_str=query_input.query, params=params)

        # Submit query and stream responses
        query_endpoint = get_query_endpoint()
        for message_data in self.client.stream_post(query_endpoint, request.to_dict()):
            yield SSEMessage.model_validate(message_data)

    def get_complete_answer(  # nosemgrep: too-many-parameters
        self,
        query: str,
        search_implementation_mode: str = "standard",
        attachments: list[str] | None = None,
        *,
        model_preference: str | None = None,
    ) -> Answer:
        """Submit a query and return the complete answer with references.

        Args:
            query: The user's query text.
            search_implementation_mode: Search mode ('standard' or
                'multi_step' for deep research).
            attachments: Optional list of S3 URLs for file attachments.
            model_preference: Optional model ID override.

        Returns:
            Answer object containing text and references list.

        Raises:
            PerplexityHTTPStatusError: For HTTP errors.
            PerplexityRequestError: For network errors.
            UpstreamSchemaError: For malformed responses or if no answer is found.
        """
        query_input = QueryInput(
            query=query,
            attachment_urls=attachments or [],
            model_preference=model_preference,
        )
        final_message = self._collect_final_message(
            query_input,
            search_implementation_mode,
        )
        return self._extract_answer_from_final(final_message)

    def _collect_final_message(
        self,
        query_input: QueryInput,
        search_implementation_mode: str,
    ) -> SSEMessage | None:
        """Consume the SSE stream and return the final message, if any."""
        for message in self.submit_query(
            query_input,
            search_implementation_mode=search_implementation_mode,
        ):
            if message.final_sse_message:
                return message
        return None

    @staticmethod
    def _extract_answer_from_final(final_message: SSEMessage | None) -> Answer:
        """Extract answer text and references from the final SSE message.

        Raises:
            UpstreamSchemaError: If no final message or no answer text is found.
        """
        if final_message is None:
            raise UpstreamSchemaError("No final SSE message found in upstream response")

        final_answer = final_message.extract_answer_text()
        references = final_message.web_results or []

        if final_answer is not None:
            return Answer(text=final_answer, references=references)

        status = getattr(final_message, "status", "<missing>")
        block_usages = final_message.describe_block_usages()
        raise UpstreamSchemaError(
            "No answer found in final upstream response: "
            f"status={status}, "
            f"block_usages={block_usages}"
        )
