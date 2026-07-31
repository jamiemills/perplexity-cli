"""Contract protocols for the HTTP error handling subsystem."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from perplexity_cli.envelope import ErrorCode
    from perplexity_cli.utils.exceptions import (
        PerplexityHTTPStatusError,
        PerplexityRequestError,
    )


@runtime_checkable
class HttpErrorClassifier(Protocol):
    """Protocol for classifying HTTP and network errors into structured tuples."""

    def classify_http_error(
        self, error: PerplexityHTTPStatusError
    ) -> tuple[ErrorCode, str, str | None]: ...

    def classify_network_error(
        self, error: PerplexityRequestError
    ) -> tuple[ErrorCode, str, str | None]: ...


@runtime_checkable
class HttpErrorHandler(Protocol):
    """Protocol for top-level CLI error routing."""

    def handle_unexpected_cli_error(
        self,
        error: Exception,
        logger: logging.Logger,
        debug_mode: str = "normal",
        message_tuple: tuple[str, str, bool] = (
            "[ERROR] An unexpected error occurred.",
            "Unexpected error",
            False,
        ),
    ) -> None: ...

    def handle_http_error(
        self,
        error: PerplexityHTTPStatusError,
        logger: logging.Logger,
        debug_mode: str = "normal",
        context: str | None = None,
    ) -> None: ...

    def handle_network_error(
        self,
        error: PerplexityRequestError,
        logger: logging.Logger,
        debug_mode: str = "normal",
        context: str | None = None,
    ) -> None: ...


@runtime_checkable
class HttpStatusClassifier(Protocol):
    """Protocol for converting raw HTTP responses into typed errors."""

    def raise_http_status_error(self, response: object, *, method: str = "POST") -> None: ...


class _CouplingProtocol(Protocol):  # pyright: ignore[reportUnusedClass]
    """Abstract coupling protocol."""

    ...
