"""Contract protocols for the HTTP error handling subsystem."""

from __future__ import annotations

from perplexity_cli.utils.http_errors import (
    HttpErrorClassifier,
    HttpErrorHandler,
    HttpStatusClassifier,
)

__all__ = ["HttpErrorClassifier", "HttpErrorHandler", "HttpStatusClassifier"]
