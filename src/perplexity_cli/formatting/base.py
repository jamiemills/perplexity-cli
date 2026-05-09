"""Base formatter interface for output formatting."""

import re
from abc import ABC, abstractmethod

from perplexity_cli.api.models import Answer, WebResult


def _is_structural_line(stripped: str) -> bool:
    """Check whether a line is a structural markdown element.

    Structural elements include headers, list items, blockquotes,
    tables, and horizontal rules.

    Args:
        stripped: The line with leading whitespace removed.

    Returns:
        True if the line is a structural element.
    """
    return bool(
        re.match(r"^#{1,6}\s", stripped)
        or re.match(r"^[-*+]\s", stripped)
        or re.match(r"^\d+\.\s", stripped)
        or re.match(r"^[>\|]", stripped)
        or re.match(r"^[\*\-]{3,}$", stripped)
    )


def _is_continuation_line(next_line: str, next_stripped: str) -> bool:
    """Check whether a line is an indented continuation of a structural block.

    Args:
        next_line: The raw line including leading whitespace.
        next_stripped: The line with leading whitespace removed.

    Returns:
        True if the line should be joined to the preceding structural line.
    """
    if next_line == next_stripped or not next_stripped:
        return False
    if next_stripped.startswith("```"):
        return False
    return not _is_structural_line(next_stripped)


def _is_prose_boundary(next_line: str, next_stripped: str) -> bool:
    """Check whether a line marks the end of a prose paragraph.

    Args:
        next_line: The raw line including whitespace.
        next_stripped: The line with leading whitespace removed.

    Returns:
        True if the line should terminate prose collection.
    """
    if next_line.strip() == "" or next_stripped.startswith("```"):
        return True
    return _is_structural_line(next_stripped)


def _collect_code_block(lines: list[str], i: int, result: list[str]) -> int:
    """Collect a fenced code block verbatim into result.

    Args:
        lines: All source lines.
        i: Index of the opening fence line.
        result: Accumulator list for output lines.

    Returns:
        The index immediately after the closing fence.
    """
    result.append(lines[i])
    i += 1
    while i < len(lines):
        result.append(lines[i])
        if lines[i].lstrip().startswith("```"):
            return i + 1
        i += 1
    return i


def _collect_structural_block(lines: list[str], i: int, result: list[str]) -> int:
    """Collect a structural line and its indented continuations.

    Args:
        lines: All source lines.
        i: Index of the structural line.
        result: Accumulator list for output lines.

    Returns:
        The index of the next unprocessed line.
    """
    paragraph = lines[i]
    i += 1
    while i < len(lines):
        next_line = lines[i]
        next_stripped = next_line.lstrip()
        if not _is_continuation_line(next_line, next_stripped):
            break
        paragraph += " " + next_stripped
        i += 1
    result.append(paragraph)
    return i


def _collect_prose_paragraph(lines: list[str], i: int, result: list[str]) -> int:
    """Collect regular prose lines into a single joined paragraph.

    Args:
        lines: All source lines.
        i: Index of the first prose line.
        result: Accumulator list for output lines.

    Returns:
        The index of the next unprocessed line.
    """
    paragraph = lines[i]
    i += 1
    while i < len(lines):
        next_line = lines[i]
        next_stripped = next_line.lstrip()
        if _is_prose_boundary(next_line, next_stripped):
            break
        paragraph += " " + next_line.strip()
        i += 1
    result.append(paragraph)
    return i


def _dispatch_line(lines: list[str], i: int, result: list[str]) -> int:
    """Route a single line to the appropriate collector.

    Args:
        lines: All source lines.
        i: Index of the current line.
        result: Accumulator list for output lines.

    Returns:
        The index of the next unprocessed line.
    """
    line = lines[i]
    if line.lstrip().startswith("```"):
        return _collect_code_block(lines, i, result)
    if line.strip() == "":
        result.append("")
        return i + 1
    if _is_structural_line(line.lstrip()):
        return _collect_structural_block(lines, i, result)
    return _collect_prose_paragraph(lines, i, result)


class Formatter(ABC):
    """Abstract base class for output formatters."""

    @staticmethod
    def strip_citations(text: str) -> str:
        """Remove citation references from text.

        Removes citation markers like [1], [2], etc. from answer text.

        Args:
            text: The text containing citations to remove.

        Returns:
            Text with citation numbers removed.
        """
        return re.sub(r"\[\d+\]", "", text)

    @staticmethod
    def unwrap_paragraph_lines(text: str) -> str:
        """Unwrap artificial line breaks within paragraphs.

        The Perplexity API often returns prose with hard line breaks at a
        fixed column width. This method joins continuation lines within a
        paragraph while preserving structural elements: code blocks, headers,
        list items, blockquotes, tables, horizontal rules, and blank-line
        paragraph separators.

        Args:
            text: Raw text potentially containing artificial line breaks.

        Returns:
            Text with continuation lines joined, structural elements intact.
        """
        if not text:
            return ""

        lines = text.split("\n")
        result: list[str] = []
        i = 0

        while i < len(lines):
            i = _dispatch_line(lines, i, result)

        return "\n".join(result)

    @abstractmethod
    def format_answer(self, text: str, strip_references: bool = False) -> str:
        """Format answer text.

        Args:
            text: The answer text to format.
            strip_references: If True, remove citation numbers like [1], [2], etc.

        Returns:
            Formatted answer text.
        """
        pass

    @abstractmethod
    def format_references(self, references: list[WebResult]) -> str:
        """Format references list.

        Args:
            references: List of web results to format.

        Returns:
            Formatted references string.
        """
        pass

    def format_complete(self, answer: Answer, strip_references: bool = False) -> str:
        """Format complete answer with references.

        Args:
            answer: Answer object containing text and references.
            strip_references: If True, exclude references section from output.

        Returns:
            Complete formatted output.
        """
        output_parts = []

        # Add formatted answer
        formatted_answer = self.format_answer(answer.text, strip_references=strip_references)
        output_parts.append(formatted_answer)

        # Add formatted references if present (and not stripped)
        if answer.references and not strip_references:
            formatted_refs = self.format_references(answer.references)
            if formatted_refs:
                output_parts.append(formatted_refs)

        return "\n".join(output_parts)

    def render_complete(self, answer: Answer, strip_references: bool = False) -> None:
        """Render complete output directly.

        Formatters that support direct terminal rendering can override this.

        Args:
            answer: Answer object containing text and references.
            strip_references: If True, exclude references section from output.
        """
        raise NotImplementedError("This formatter does not support direct rendering")

    def should_use_colors(self) -> bool:
        """Check if colours should be used based on TTY and NO_COLOR.

        Returns:
            True if colours should be used, False otherwise.
        """
        import os
        import sys

        # NO_COLOR convention: any value (even empty string) disables colour
        if os.environ.get("NO_COLOR") is not None:
            return False
        return sys.stdout.isatty()


def should_use_plain_default() -> bool:
    """Check if output should default to plain format (no ANSI) based on TTY and env.

    Returns:
        True if plain format should be the default, False otherwise.
    """
    import os
    import sys

    if not sys.stdout.isatty():
        return True
    if os.environ.get("NO_COLOR") is not None:
        return True
    return False
