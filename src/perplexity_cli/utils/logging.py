"""Logging configuration and utilities for Perplexity CLI."""

import logging
import re
import sys
from collections.abc import Mapping
from datetime import UTC
from pathlib import Path

from perplexity_cli.utils.config import get_config_paths


class DynamicStderrHandler(logging.StreamHandler):
    """Stream handler that always writes to the current stderr stream."""

    def emit(self, record: logging.LogRecord) -> None:
        """Write a formatted log record to the current stderr stream."""
        try:  # nosemgrep: except-broad-exception
            message = self.format(record)
            stream = sys.stderr
            stream.write(message + self.terminator)
            self.flush()
        except RecursionError:
            raise
        except (OSError, TypeError, ValueError):
            self.handleError(record)

    def flush(self) -> None:
        """Flush the current stderr stream without touching stale captures."""
        if self.lock is None:
            self._flush_current_stderr()
            return

        with self.lock:
            self._flush_current_stderr()

    @staticmethod
    def _flush_current_stderr() -> None:
        """Flush the active stderr stream if it is still valid."""
        stream = sys.stderr
        try:
            if stream:
                stream.flush()
        except (ValueError, AttributeError):
            # pytest capture can replace and close previous stderr objects;
            # flushing a closed stream raises ValueError — safe to ignore
            return


class JSONLogFormatter(logging.Formatter):
    """Formatter that outputs log records as JSON objects (one per line).

    Used when --json --verbose is active, so stderr log output is also
    machine-parseable.
    """

    def __init__(self, trace_id: str | None = None):
        super().__init__()
        self.trace_id = trace_id

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a single-line JSON object."""
        import json
        from datetime import datetime

        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        if self.trace_id:
            entry["trace_id"] = self.trace_id
        return json.dumps(entry)


def configure_quiet_mode(logger: logging.Logger) -> None:
    """Remove all stderr handlers from the logger to suppress output."""
    logger.handlers = [
        h
        for h in logger.handlers
        if not isinstance(h, (logging.StreamHandler, DynamicStderrHandler))
        or isinstance(h, logging.FileHandler)
    ]


def enable_structured_logging(trace_id: str | None = None) -> None:
    """Switch stderr logging to JSON format.

    Replaces the formatter on all stderr handlers with JSONLogFormatter.
    """
    logger = get_logger()
    json_formatter = JSONLogFormatter(trace_id=trace_id)
    for handler in logger.handlers:
        if isinstance(handler, DynamicStderrHandler):
            handler.setFormatter(json_formatter)


def setup_logging(  # nosemgrep: boolean-flag-argument
    level: int = logging.WARNING,
    log_file: Path | None = None,
    verbose: bool = False,
    debug: bool = False,
) -> logging.Logger:
    """Configure logging for the application.

    Args:
        level: Logging level (default: WARNING).
        log_file: Optional path to log file.
        verbose: If True, set level to INFO.
        debug: If True, set level to DEBUG.

    Returns:
        Configured logger instance.
    """
    # Determine log level
    if debug:
        log_level = logging.DEBUG
    elif verbose:
        log_level = logging.INFO
    else:
        log_level = level

    # Create logger
    logger = logging.getLogger("perplexity_cli")
    logger.setLevel(log_level)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = DynamicStderrHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    logger.propagate = True

    # File handler (if specified)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Get a logger instance.

    Args:
        name: Optional logger name (defaults to 'perplexity_cli').

    Returns:
        Logger instance.
    """
    if name:
        return logging.getLogger(f"perplexity_cli.{name}")
    return logging.getLogger("perplexity_cli")


def get_default_log_file() -> Path:
    """Get the default log file path.

    Returns:
        Path to default log file in config directory.
    """
    return get_config_paths().log_file_path


def redact_path(value: str | Path | None) -> str:
    """Redact a local path for logging."""
    if value is None:
        return "<none>"

    path = Path(value)
    parts = path.parts
    if not parts:
        return "<path>"
    if path.name:
        return str(Path("<redacted>") / path.name)
    return "<redacted-path>"


def redact_text(value: str | None, max_length: int = 32) -> str:
    """Redact free-form text while preserving a short preview length."""
    if not value:
        return "<empty>"
    return f"<redacted:{min(len(value), max_length)} chars>"


def redact_url(value: str | None) -> str:
    """Redact a URL for logging."""
    if not value:
        return "<empty-url>"

    match = re.match(r"^(https?://[^/]+)", value)
    if match:
        return f"{match.group(1)}/<redacted>"
    return "<redacted-url>"


def redact_mapping_keys(mapping: Mapping[str, object] | None) -> str:
    """Redact mapping contents but keep the key count."""
    if not mapping:
        return "<none>"
    return f"<redacted:{len(mapping)} keys>"


def redact_response_text(value: str | None) -> str:
    """Redact HTTP response text for logs."""
    return redact_text(value, max_length=0)
