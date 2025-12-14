"""Output formatting module for different output styles."""

from perplexity_cli.formatting.base import Formatter
from perplexity_cli.formatting.json import JSONFormatter
from perplexity_cli.formatting.markdown import MarkdownFormatter
from perplexity_cli.formatting.plain import PlainTextFormatter
from perplexity_cli.formatting.registry import (
    FormatterRegistry,
    get_formatter,
    list_formatters,
    register_formatter,
)
from perplexity_cli.formatting.rich import RichFormatter

__all__ = [
    "Formatter",
    "PlainTextFormatter",
    "MarkdownFormatter",
    "RichFormatter",
    "JSONFormatter",
    "FormatterRegistry",
    "register_formatter",
    "get_formatter",
    "list_formatters",
]

# Auto-register built-in formatters
register_formatter("plain", PlainTextFormatter)
register_formatter("markdown", MarkdownFormatter)
register_formatter("rich", RichFormatter)
register_formatter("json", JSONFormatter)
