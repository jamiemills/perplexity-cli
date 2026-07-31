"""Contract protocols for the logging subsystem."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class LoggerFactory(Protocol):
    """Protocol for obtaining logger instances and configuring logging."""

    def get_logger(self, name: str | None = None) -> logging.Logger:
        """Return a logger instance, optionally child-scoped."""
        ...

    def setup_logging(
        self,
        verbosity: str = "warning",
        log_file: Path | None = None,
    ) -> logging.Logger:
        """Configure logging for the application."""
        ...


@runtime_checkable
class RedactionAgent(Protocol):
    """Protocol for redacting sensitive values before logging."""

    def redact_path(self, value: str | Path | None) -> str:
        """Redact a local path for logging."""
        ...

    def redact_text(self, value: str | None, max_length: int = 32) -> str:
        """Redact free-form text while preserving a short preview."""
        ...

    def redact_url(self, value: str | None) -> str:
        """Redact a URL for logging."""
        ...

    def redact_mapping_keys(self, mapping: Mapping[str, object] | None) -> str:
        """Redact mapping contents but keep the key count."""
        ...

    def redact_response_text(self, value: str | None) -> str:
        """Redact HTTP response text for logs."""
        ...
