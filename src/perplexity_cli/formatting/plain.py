"""Plain text formatter for simple, unformatted output."""

import re

from perplexity_cli.api.models import Answer, WebResult
from perplexity_cli.formatting.base import Formatter


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
            text = re.sub(r"\[\d+\]", "", text)

        lines = text.split("\n")
        result = [""]  # Start with blank line
        i = 0
        skip_next_blank = False
        blank_count = 0

        while i < len(lines):
            line = lines[i]

            # Skip markdown horizontal rules (*** or ---)
            if re.match(r"^[\*\-]{3,}$", line.strip()):
                i += 1
                continue

            # Check for headers (###, ##, #)
            header_match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if header_match:
                content = header_match.group(2)
                # Remove any markdown bold/italic from header
                content = re.sub(r"\*\*(.+?)\*\*", r"\1", content)
                content = re.sub(r"\*(.+?)\*", r"\1", content)

                # Add single blank line before header if result has content
                if len(result) > 1:  # More than just the initial blank line
                    result.append("")

                # Add header with underline
                result.append(content)
                result.append("=" * len(content))
                # Skip the next blank line after header
                skip_next_blank = True
                blank_count = 0
            elif line.strip() == "":
                # Skip blank line immediately after header underline
                if skip_next_blank:
                    skip_next_blank = False
                else:
                    # Only add blank line if we haven't just added multiple
                    blank_count += 1
                    if blank_count <= 2:  # Allow max 2 consecutive blanks
                        result.append("")
            else:
                skip_next_blank = False
                blank_count = 0
                # Remove markdown bold and italic from regular text
                line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
                line = re.sub(r"\*(.+?)\*", r"\1", line)
                result.append(line)

            i += 1

        return "\n".join(result).rstrip()

    def format_complete(self, answer: Answer, strip_references: bool = False) -> str:
        """Format complete answer with references.

        Args:
            answer: Answer object containing text and references.
            strip_references: If True, exclude references section from output.

        Returns:
            Complete formatted output with proper spacing.
        """
        output_parts = []

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

        lines = []
        # Add ruler above references (at least 30 characters)
        lines.append("─" * 50)
        # Add References header with underline
        lines.append("References")
        lines.append("=" * len("References"))
        # Add references
        for i, ref in enumerate(references, 1):
            lines.append(f"[{i}] {ref.url}")

        return "\n".join(lines)
