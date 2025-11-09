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
        i = 0
        skip_next_blank = False

        while i < len(lines):
            line = lines[i]

            # Skip markdown horizontal rules (*** or ---)
            if re.match(r'^[\*\-]{3,}$', line.strip()):
                i += 1
                continue

            # Check for headers (###, ##, #)
            header_match = re.match(r'^(#{1,6})\s+(.+)$', line)
            if header_match:
                content = header_match.group(2)
                # Remove any markdown bold/italic from header
                content = re.sub(r'\*\*(.+?)\*\*', r'\1', content)
                content = re.sub(r'\*(.+?)\*', r'\1', content)

                # Add double blank line before header if result isn't empty
                if result:
                    result.append('')
                    result.append('')

                # Add header with underline
                result.append(content)
                result.append('=' * len(content))
                # Skip the next blank line after header
                skip_next_blank = True
            elif line.strip() == '':
                # Skip blank line immediately after header underline
                if skip_next_blank:
                    skip_next_blank = False
                else:
                    result.append('')
            else:
                skip_next_blank = False
                # Remove markdown bold and italic from regular text
                line = re.sub(r'\*\*(.+?)\*\*', r'\1', line)
                line = re.sub(r'\*(.+?)\*', r'\1', line)
                result.append(line)

            i += 1

        return '\n'.join(result).rstrip()

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
