"""HTTP error handling utilities for CLI commands."""

from __future__ import annotations

from typing import Protocol

from perplexity_cli.utils.http_errors.contracts import (
    HttpErrorClassifier as HttpErrorClassifier,
)
from perplexity_cli.utils.http_errors.contracts import (
    HttpErrorHandler as HttpErrorHandler,
)
from perplexity_cli.utils.http_errors.contracts import (
    HttpStatusClassifier as HttpStatusClassifier,
)
from perplexity_cli.utils.http_errors.impl import (
    classify_http_error as classify_http_error,
)
from perplexity_cli.utils.http_errors.impl import (
    classify_network_error as classify_network_error,
)
from perplexity_cli.utils.http_errors.impl import (
    handle_http_error as handle_http_error,
)
from perplexity_cli.utils.http_errors.impl import (
    handle_network_error as handle_network_error,
)
from perplexity_cli.utils.http_errors.impl import (
    handle_unexpected_cli_error as handle_unexpected_cli_error,
)
from perplexity_cli.utils.http_errors.impl import (
    raise_http_status_error as raise_http_status_error,
)

__all__ = [
    "HttpErrorClassifier",
    "HttpErrorHandler",
    "HttpStatusClassifier",
    "classify_http_error",
    "classify_network_error",
    "handle_http_error",
    "handle_network_error",
    "handle_unexpected_cli_error",
    "raise_http_status_error",
]


class _CouplingProtocol(Protocol):  # pyright: ignore[reportUnusedClass]
    """Abstract coupling protocol."""

    ...
