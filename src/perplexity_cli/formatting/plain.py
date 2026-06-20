"""Plain text formatter for simple, unformatted output."""

from __future__ import annotations

import re

from perplexity_cli.api.models import Answer, WebResult
from perplexity_cli.formatting.base import Formatter

_MAX_CONSECUTIVE_BLANK_LINES = 2


def _strip_markdown_emphasis(text: str) -> str:
    """Remove markdown bold and italic markers from text.

    Args:
        text: Text possibly containing markdown emphasis markers.

    Returns:
        Text with bold/italic markers removed.
    """
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    return re.sub(r"\*(.+?)\*", r"\1", text)


def _process_header(line: str, result: list[str]) -> tuple[bool, int]:
    """Process a markdown header line, appending an underlined version to result.

    Args:
        line: The source line to check for a header pattern.
        result: Accumulator list for output lines.

    Returns:
        A tuple of (was_header, blank_count). If the line was a header,
        was_header is True and blank_count is reset to 0.
    """
    header_match = re.match(r"^(#{1,6})\s+(\S.*)$", line)
    if not header_match:
        return False, 0
    content = _strip_markdown_emphasis(header_match.group(2))
    if result:
        result.append("")
    result.append(content)
    result.append("=" * len(content))
    return True, 0


def _process_blank_line(
    result: list[str],
    skip_next_blank: bool,
    blank_count: int,
) -> tuple[bool, int]:
    """Handle a blank line in plain-text formatting.

    Args:
        result: Accumulator list for output lines.
        skip_next_blank: Whether this blank line should be suppressed.
        blank_count: Running count of consecutive blank lines.

    Returns:
        Updated (skip_next_blank, blank_count) state.
    """
    if skip_next_blank:
        return False, blank_count
    blank_count += 1
    if blank_count <= _MAX_CONSECUTIVE_BLANK_LINES:
        result.append("")
    return False, blank_count


def _process_plain_line(
    line: str,
    result: list[str],
    skip_next_blank: bool,
    blank_count: int,
) -> tuple[bool, int]:
    """Process a single line for plain-text formatting.

    Args:
        line: The current source line.
        result: Accumulator list for output lines.
        skip_next_blank: Whether to skip the next blank line.
        blank_count: Running count of consecutive blank lines.

    Returns:
        Updated (skip_next_blank, blank_count) state.
    """
    if re.match(r"^[\*\-]{3,}$", line.strip()):
        return skip_next_blank, blank_count

    was_header, blank_count_new = _process_header(line, result)
    if was_header:
        return True, blank_count_new

    if not line.strip():
        return _process_blank_line(result, skip_next_blank, blank_count)

    result.append(_strip_markdown_emphasis(line))
    return False, 0


class PlainTextFormatter(Formatter):
    """Formatter that outputs plain text without any formatting."""

    def format_answer(self, text: str, strip_references: bool = False) -> str:
        """Format answer text as plain text with underlined headers.

        Args:
            text: The answer text (possibly containing markdown).
            strip_references: If True, remove citation numbers like [1], [2], etc.

        Returns:
            Plain text answer with headers underlined instead of using markdown syntax.
        """
        # Strip citation references if requested
        if strip_references:
            text = self.strip_citations(text)

        # Unwrap artificial line breaks from the API response
        text = self.unwrap_paragraph_lines(text)

        lines = text.split("\n")
        result: list[str] = []
        skip_next_blank = False
        blank_count = 0

        for line in lines:
            skip_next_blank, blank_count = _process_plain_line(
                line, result, skip_next_blank, blank_count
            )

        return "\n".join(result).rstrip()

    def format_complete(self, answer: Answer, strip_references: bool = False) -> str:
        """Format complete answer with references.

        Args:
            answer: Answer object containing text and references.
            strip_references: If True, exclude references section from output.

        Returns:
            Complete formatted output with proper spacing.
        """
        output_parts: list[str] = []

        # Add formatted answer
        formatted_answer = self.format_answer(answer.text, strip_references=strip_references)
        output_parts.append(formatted_answer)

        # Add formatted references if present (and not stripped)
        if answer.references and not strip_references:
            # Add blank line before references section
            output_parts.append("")
            formatted_refs = self.format_references(answer.references)
            if formatted_refs:
                output_parts.append(formatted_refs)

        return "\n".join(output_parts)

    def format_references(self, references: list[WebResult]) -> str:
        """Format references as a simple numbered list with underlined header.

        Args:
            references: List of web results.

        Returns:
            Numbered reference list with ruler above and underlined header.
        """
        if not references:
            return ""

        lines: list[str] = []
        # Add ruler above references (at least 30 characters)
        lines.append("─" * 50)
        # Add References header with underline
        lines.append("References")
        lines.append("=" * len("References"))
        # Add references
        for i, ref in enumerate(references, 1):
            lines.append(f"[{i}] {ref.url}")

        return "\n".join(lines)
