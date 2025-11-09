"""Plain text formatter for simple, unformatted output."""

import re

from perplexity_cli.api.models import WebResult
from perplexity_cli.formatting.base import Formatter


class PlainTextFormatter(Formatter):
    """Formatter that outputs plain text without any formatting."""

    def format_answer(self, text: str) -> str:
        """Format answer text as plain text with underlined headers.

        Args:
            text: The answer text (possibly containing markdown).

        Returns:
            Plain text answer with headers underlined instead of using markdown syntax.
        """
        lines = text.split('\n')
        result = []

        for line in lines:
            # Check for headers (###, ##, #)
            header_match = re.match(r'^(#{1,6})\s+(.+)$', line)
            if header_match:
                content = header_match.group(2)
                # Remove any markdown bold/italic from header
                content = re.sub(r'\*\*(.+?)\*\*', r'\1', content)
                content = re.sub(r'\*(.+?)\*', r'\1', content)

                # Add header with underline
                result.append('')
                result.append(content)
                result.append('=' * len(content))
                result.append('')
            else:
                # Remove markdown bold and italic from regular text
                line = re.sub(r'\*\*(.+?)\*\*', r'\1', line)
                line = re.sub(r'\*(.+?)\*', r'\1', line)
                result.append(line)

        return '\n'.join(result).rstrip()

    def format_references(self, references: list[WebResult]) -> str:
        """Format references as a simple numbered list.

        Args:
            references: List of web results.

        Returns:
            Numbered reference list.
        """
        if not references:
            return ""

        lines = ["References"]
        for i, ref in enumerate(references, 1):
            lines.append(f"[{i}] {ref.url}")

        return "\n".join(lines)
