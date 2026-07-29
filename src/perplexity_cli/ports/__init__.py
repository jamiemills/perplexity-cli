"""Port protocols defining the application layer's required interfaces.

These protocols follow hexagonal architecture principles: the application
layer owns its required interfaces, and concrete adapters satisfy them
structurally without explicit subclassing.
"""

from __future__ import annotations

from collections.abc import Coroutine, Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable

from perplexity_cli.api.models import Answer, QueryInput, SSEMessage
from perplexity_cli.models.model_config import ModelConfigEntry
from perplexity_cli.utils.attachment_models import FileAttachment


@runtime_checkable
class QueryGateway(Protocol):
    """Port for submitting queries to the Perplexity backend.

    Satisfied structurally by ``api.endpoints.PerplexityAPI``.
    """

    def submit_query(self, query_input: QueryInput) -> Iterator[SSEMessage]:
        """Submit a query and stream SSE responses.

        Args:
            query_input: Query text, attachments, and model preference.

        Yields:
            SSEMessage objects from the streaming response.
        """
        ...

    def get_complete_answer(
        self,
        query: str,
        search_implementation_mode: str = "standard",
        *,
        extra_params: tuple[list[str] | None, str | None, dict[str, object] | None] = (
            None,
            None,
            None,
        ),
    ) -> Answer:
        """Submit a query and return the complete answer.

        Args:
            query: The user's query text.
            search_implementation_mode: Search mode identifier.
            extra_params: Tuple of (attachments, model_preference, request_params).

        Returns:
            Answer object containing text and references.
        """
        ...

    def close(self) -> None:
        """Release underlying HTTP resources."""
        ...


@runtime_checkable
class AuthTokenStore(Protocol):
    """Port for loading and persisting authentication tokens.

    Satisfied structurally by ``auth.token_manager.TokenManager``.
    """

    def load_token(self) -> tuple[str | None, dict[str, str] | None]:
        """Load the stored authentication token and cookies.

        Returns:
            Tuple of (token, cookies); either or both may be None.
        """
        ...

    def save_token(self, token: str, cookies: dict[str, str] | None = None) -> None:
        """Persist an authentication token and optional cookies.

        Args:
            token: The authentication token to store.
            cookies: Optional browser cookies to store alongside the token.
        """
        ...


@runtime_checkable
class AttachmentUploader(Protocol):
    """Port for uploading file attachments to remote storage.

    Satisfied structurally by ``attachments.upload_manager.AttachmentUploader``.
    """

    def upload_files(
        self, attachments: list[FileAttachment]
    ) -> Coroutine[object, object, list[str]]:
        """Upload files and return their remote URLs.

        Args:
            attachments: File attachment objects to upload.

        Returns:
            Coroutine resolving to a list of uploaded URLs.
        """
        ...


@runtime_checkable
class ThreadRecordPort(Protocol):
    """Structural protocol for a single thread record.

    Satisfied by any object exposing title, url, and created_at attributes.
    """

    @property
    def title(self) -> str:
        """Thread title or question text."""
        ...

    @property
    def url(self) -> str:
        """Full URL to the thread."""
        ...

    @property
    def created_at(self) -> str:
        """ISO 8601 creation timestamp."""
        ...


@runtime_checkable
class ThreadRepository(Protocol):
    """Port for fetching and caching thread history.

    Satisfied structurally by ``threads.scraper.ThreadScraper`` combined
    with ``threads.cache_manager.ThreadCacheManager``.
    """

    def fetch_threads(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[ThreadRecordPort]:
        """Fetch threads within an optional date range.

        Args:
            from_date: Inclusive start date (ISO 8601), or None for unbounded.
            to_date: Inclusive end date (ISO 8601), or None for unbounded.

        Returns:
            List of thread records, newest first.
        """
        ...


@runtime_checkable
class ModelCatalog(Protocol):
    """Port for querying available model metadata.

    Satisfied structurally by ``services.model_service.ModelService``.
    """

    def list_available_models(self) -> list[ModelConfigEntry]:
        """Return models accessible to the current user.

        Returns:
            List of model configuration entries.
        """
        ...

    def validate_model_id(self, model_id: str) -> bool:
        """Check whether a model identifier is valid and accessible.

        Args:
            model_id: The model identifier to validate.

        Returns:
            True if the model is available.
        """
        ...


@runtime_checkable
class ConfigStore(Protocol):
    """Port for reading and writing CLI configuration.

    Satisfied structurally by module-level functions in ``utils.config``
    when wrapped in an adapter class.
    """

    def get_config_dir(self) -> Path:
        """Return the resolved configuration directory path.

        Returns:
            Path to the configuration directory.
        """
        ...

    def get_token_path(self) -> Path:
        """Return the path to the authentication token file.

        Returns:
            Path to the token file.
        """
        ...

    def get_cache_path(self) -> Path:
        """Return the path to the thread cache file.

        Returns:
            Path to the cache file.
        """
        ...
