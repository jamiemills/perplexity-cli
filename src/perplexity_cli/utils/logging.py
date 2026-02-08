"""Logging configuration and utilities for Perplexity CLI."""

import logging
import sys
from pathlib import Path

from perplexity_cli.utils.config import get_config_dir


def setup_logging(
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
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

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
    return get_config_dir() / "perplexity-cli.log"
