"""Perplexity API endpoint abstractions.

This module provides high-level interfaces to Perplexity's private APIs.
All API-specific code is isolated here to enable rapid adaptation if APIs change.
"""

import uuid
from collections.abc import Iterator

import httpx

from ..utils.config import get_perplexity_base_url, get_query_endpoint
from ..utils.logging import get_logger
from ..utils.retry import is_retryable_error
from .client import SSEClient
from .models import Answer, Collection, QueryParams, QueryRequest, SSEMessage, Thread, ThreadContext, WebResult


class PerplexityAPI:
    """High-level interface to Perplexity API."""

    def __init__(self, token: str, timeout: int = 60) -> None:
        """Initialise Perplexity API client.

        Args:
            token: Authentication JWT token.
            timeout: Request timeout in seconds.
        """
        self.client = SSEClient(token=token, timeout=timeout)

    def submit_query(
        self,
        query: str,
        language: str = "en-US",
        timezone: str = "Europe/London",
        auto_save_context: bool = False,
    ) -> Iterator[SSEMessage]:
        """Submit a query to Perplexity and stream responses.

        Args:
            query: The user's query text.
            language: Language code (default: en-US).
            timezone: Timezone string (default: Europe/London).
            auto_save_context: If True, automatically save thread context after final message (default: False, disabled).

        Yields:
            SSEMessage objects from the streaming response.

        Raises:
            httpx.HTTPStatusError: For HTTP errors (401, 403, 429, etc.).
            httpx.RequestError: For network/connection errors.
            ValueError: For malformed responses.
        """
        logger = get_logger()
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
            message = SSEMessage.from_dict(message_data)
            yield message

    def extract_thread_context(self, messages: list[SSEMessage]) -> ThreadContext | None:
        """Extract thread context from a list of SSE messages.

        Args:
            messages: List of SSEMessage objects from a query.

        Returns:
            ThreadContext if found in final message, None otherwise.
        """
        for message in messages:
            if message.final_sse_message and message.thread_url_slug:
                return ThreadContext(
                    thread_url_slug=message.thread_url_slug,
                    frontend_context_uuid=message.frontend_context_uuid,
                    context_uuid=message.context_uuid,
                    read_write_token=message.read_write_token,
                )
        return None

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

    def list_threads(
        self,
        limit: int = 20,
        offset: int = 0,
        ascending: bool = False,
        search_term: str = "",
    ) -> list[Thread]:
        """List threads from Perplexity library.

        Args:
            limit: Maximum number of threads to return (default: 20).
            offset: Offset for pagination (default: 0).
            ascending: Sort order - True for oldest first, False for newest first (default: False).
            search_term: Search term to filter threads (default: "").

        Returns:
            List of Thread objects.

        Raises:
            httpx.HTTPStatusError: For HTTP errors (401, 403, 429, etc.).
            httpx.RequestError: For network/connection errors.
            ValueError: For malformed responses.
        """
        logger = get_logger()
        base_url = get_perplexity_base_url()
        endpoint = f"{base_url}/rest/thread/list_ask_threads?version=2.18&source=default"

        # Get headers from SSE client (includes auth)
        headers = self.client.get_headers()
        # Update Accept header for JSON response (not SSE)
        headers["Accept"] = "application/json"
        # Add library-specific headers
        headers["x-app-apiversion"] = "2.18"
        headers["x-app-apiclient"] = "default"

        # Request body
        request_data = {
            "limit": limit,
            "ascending": ascending,
            "offset": offset,
            "search_term": search_term,
        }

        logger.debug(f"Listing threads: limit={limit}, offset={offset}, search={search_term}")

        # Use regular HTTP client (not SSE) for library endpoints
        with httpx.Client(timeout=self.client.timeout) as http_client:
            try:
                response = http_client.post(endpoint, headers=headers, json=request_data)
                response.raise_for_status()

                # Parse response array
                data = response.json()
                if not isinstance(data, list):
                    raise ValueError(f"Expected list response, got {type(data)}")

                threads = [Thread.from_dict(thread_data) for thread_data in data]
                logger.debug(f"Retrieved {len(threads)} threads")
                return threads

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    logger.error("Authentication failed. Token may be invalid or expired.")
                    raise
                logger.error(f"HTTP error listing threads: {e.response.status_code}")
                raise
            except httpx.RequestError as e:
                logger.error(f"Network error listing threads: {e}")
                raise
            except ValueError as e:
                logger.error(f"Invalid response format: {e}")
                raise

    def list_collections(self, limit: int = 30, offset: int = 0) -> list[Collection]:
        """List collections from Perplexity library.

        Args:
            limit: Maximum number of collections to return (default: 30).
            offset: Offset for pagination (default: 0).

        Returns:
            List of Collection objects.

        Raises:
            httpx.HTTPStatusError: For HTTP errors (401, 403, 429, etc.).
            httpx.RequestError: For network/connection errors.
            ValueError: For malformed responses.
        """
        logger = get_logger()
        base_url = get_perplexity_base_url()
        endpoint = f"{base_url}/rest/collections/list_user_collections?limit={limit}&offset={offset}&version=2.18&source=default"

        # Get headers from SSE client (includes auth)
        headers = self.client.get_headers()
        # Update Accept header for JSON response
        headers["Accept"] = "application/json"
        # Add library-specific headers
        headers["x-app-apiversion"] = "2.18"
        headers["x-app-apiclient"] = "default"

        logger.debug(f"Listing collections: limit={limit}, offset={offset}")

        # Use regular HTTP client (not SSE) for library endpoints
        with httpx.Client(timeout=self.client.timeout) as http_client:
            try:
                response = http_client.get(endpoint, headers=headers)
                response.raise_for_status()

                # Parse response array
                data = response.json()
                if not isinstance(data, list):
                    raise ValueError(f"Expected list response, got {type(data)}")

                collections = [Collection.from_dict(collection_data) for collection_data in data]
                logger.debug(f"Retrieved {len(collections)} collections")
                return collections

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    logger.error("Authentication failed. Token may be invalid or expired.")
                    raise
                logger.error(f"HTTP error listing collections: {e.response.status_code}")
                raise
            except httpx.RequestError as e:
                logger.error(f"Network error listing collections: {e}")
                raise
            except ValueError as e:
                logger.error(f"Invalid response format: {e}")
                raise

    def delete_thread(self, thread_slug: str) -> bool:
        """Delete a thread (if endpoint is available).

        Note: This method is a placeholder. The actual delete endpoint
        needs to be discovered via API inspection.

        Args:
            thread_slug: The thread slug to delete.

        Returns:
            True if deletion was successful, False otherwise.

        Raises:
            NotImplementedError: If delete endpoint is not yet discovered.
        """
        logger = get_logger()
        logger.warning("Delete thread endpoint not yet discovered. This is a placeholder.")
        raise NotImplementedError(
            "Thread deletion endpoint has not been discovered yet. "
            "Use the web interface to delete threads, or help discover the endpoint "
            "by inspecting network traffic when deleting a thread in the browser."
        )

    def submit_followup_query(
        self,
        query: str,
        thread_context: ThreadContext,
        language: str = "en-US",
        timezone: str = "Europe/London",
        auto_save_context: bool = False,
    ) -> Iterator[SSEMessage]:
        """Submit a follow-up query to an existing thread.

        Args:
            query: The follow-up query text.
            thread_context: ThreadContext from previous query in the thread.
            language: Language code (default: en-US).
            timezone: Timezone string (default: Europe/London).
            auto_save_context: If True, automatically update thread context after final message (default: True).

        Yields:
            SSEMessage objects from the streaming response.

        Raises:
            httpx.HTTPStatusError: For HTTP errors (401, 403, 429, etc.).
            httpx.RequestError: For network/connection errors.
            ValueError: For malformed responses or missing required context fields.
        """
        logger = get_logger()
        
        # Validate required context fields
        if not thread_context.frontend_context_uuid:
            raise ValueError(
                "ThreadContext must have frontend_context_uuid for follow-up queries"
            )
        
        # Generate new frontend_uuid for this query, but reuse frontend_context_uuid
        frontend_uuid = str(uuid.uuid4())
        
        logger.debug(
            f"Submitting follow-up query with context UUID: {thread_context.frontend_context_uuid}"
        )
        if thread_context.context_uuid:
            logger.debug(f"Using backend context UUID: {thread_context.context_uuid}")
        else:
            logger.warning("No context_uuid in thread context - follow-up may not link correctly")
        if thread_context.read_write_token:
            logger.debug("Using read_write_token for thread operations")
        else:
            logger.warning("No read_write_token in thread context - follow-up may not link correctly")
        if thread_context.thread_url_slug:
            logger.debug(f"Using thread URL slug: {thread_context.thread_url_slug}")
        else:
            logger.warning("No thread_url_slug in thread context - follow-up may not link correctly")

        # Build query parameters with is_related_query=True and all context fields
        params = QueryParams(
            language=language,
            timezone=timezone,
            frontend_uuid=frontend_uuid,
            frontend_context_uuid=thread_context.frontend_context_uuid,
            context_uuid=thread_context.context_uuid if thread_context.context_uuid else None,
            read_write_token=thread_context.read_write_token if thread_context.read_write_token else None,
            thread_url_slug=thread_context.thread_url_slug if thread_context.thread_url_slug else None,
            is_related_query=True,
        )

        # Build request
        request = QueryRequest(query_str=query, params=params)

        # Submit query and stream responses
        query_endpoint = get_query_endpoint()
        
        for message_data in self.client.stream_post(query_endpoint, request.to_dict()):
            message = SSEMessage.from_dict(message_data)
            yield message
