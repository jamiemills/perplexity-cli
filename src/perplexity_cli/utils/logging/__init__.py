"""Logging configuration and utilities for Perplexity CLI."""

from __future__ import annotations

from perplexity_cli.utils.logging.contracts import LoggerFactory as LoggerFactory
from perplexity_cli.utils.logging.contracts import RedactionAgent as RedactionAgent
from perplexity_cli.utils.logging.impl import (
    DynamicStderrHandler as DynamicStderrHandler,
)
from perplexity_cli.utils.logging.impl import (
    JSONLogFormatter as JSONLogFormatter,
)
from perplexity_cli.utils.logging.impl import (
    configure_quiet_mode as configure_quiet_mode,
)
from perplexity_cli.utils.logging.impl import (
    enable_structured_logging as enable_structured_logging,
)
from perplexity_cli.utils.logging.impl import (
    get_default_log_file as get_default_log_file,
)
from perplexity_cli.utils.logging.impl import (
    get_logger as get_logger,
)
from perplexity_cli.utils.logging.impl import (
    redact_mapping_keys as redact_mapping_keys,
)
from perplexity_cli.utils.logging.impl import (
    redact_path as redact_path,
)
from perplexity_cli.utils.logging.impl import (
    redact_response_text as redact_response_text,
)
from perplexity_cli.utils.logging.impl import (
    redact_text as redact_text,
)
from perplexity_cli.utils.logging.impl import (
    redact_url as redact_url,
)
from perplexity_cli.utils.logging.impl import (
    setup_logging as setup_logging,
)

__all__ = [
    "DynamicStderrHandler",
    "JSONLogFormatter",
    "LoggerFactory",
    "RedactionAgent",
    "configure_quiet_mode",
    "enable_structured_logging",
    "get_default_log_file",
    "get_logger",
    "redact_mapping_keys",
    "redact_path",
    "redact_response_text",
    "redact_text",
    "redact_url",
    "setup_logging",
]
