"""Base formatter interface for output formatting."""

import re
from abc import ABC, abstractmethod

from perplexity_cli.api.models import Answer, WebResult


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
            line = lines[i]

            # Fenced code block: pass through verbatim until closing fence
            if line.lstrip().startswith("```"):
                result.append(line)
                i += 1
                while i < len(lines):
                    result.append(lines[i])
                    if lines[i].lstrip().startswith("```") and i > 0:
                        i += 1
                        break
                    i += 1
                continue

            # Blank line: preserve as paragraph separator
            if line.strip() == "":
                result.append("")
                i += 1
                continue

            # Structural lines that must stay on their own line
            stripped = line.lstrip()
            is_structural = (
                re.match(r"^#{1,6}\s", stripped)  # Header
                or re.match(r"^[-*+]\s", stripped)  # Unordered list item
                or re.match(r"^\d+\.\s", stripped)  # Ordered list item
                or re.match(r"^[>\|]", stripped)  # Blockquote or table
                or re.match(r"^[\*\-]{3,}$", stripped)  # Horizontal rule
            )

            if is_structural:
                # Start collecting this structural line and any indented
                # continuation lines beneath it
                paragraph = line
                i += 1
                while i < len(lines):
                    next_line = lines[i]
                    next_stripped = next_line.lstrip()
                    # A continuation of a list item: indented, non-empty,
                    # and not itself a new structural element
                    if (
                        next_line != next_stripped  # has leading whitespace
                        and next_stripped  # non-empty
                        and not re.match(r"^[-*+]\s", next_stripped)
                        and not re.match(r"^\d+\.\s", next_stripped)
                        and not re.match(r"^#{1,6}\s", next_stripped)
                        and not re.match(r"^[>\|]", next_stripped)
                        and not next_stripped.startswith("```")
                    ):
                        paragraph += " " + next_stripped
                        i += 1
                    else:
                        break
                result.append(paragraph)
                continue

            # Regular prose line: collect and join continuation lines
            paragraph = line
            i += 1
            while i < len(lines):
                next_line = lines[i]
                next_stripped = next_line.lstrip()
                # Stop joining at blank lines, structural lines, or code fences
                if (
                    next_line.strip() == ""
                    or re.match(r"^#{1,6}\s", next_stripped)
                    or re.match(r"^[-*+]\s", next_stripped)
                    or re.match(r"^\d+\.\s", next_stripped)
                    or re.match(r"^[>\|]", next_stripped)
                    or re.match(r"^[\*\-]{3,}$", next_stripped)
                    or next_stripped.startswith("```")
                ):
                    break
                paragraph += " " + next_line.strip()
                i += 1
            result.append(paragraph)

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

    def should_use_colors(self) -> bool:
        """Check if colours should be used based on TTY.

        Returns:
            True if colours should be used, False otherwise.
        """
        import sys

        # Check if stdout is a TTY
        return sys.stdout.isatty()
