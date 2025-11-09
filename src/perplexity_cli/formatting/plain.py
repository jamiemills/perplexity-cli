"""Plain text formatter for simple, unformatted output."""

from perplexity_cli.api.models import WebResult
from perplexity_cli.formatting.base import Formatter


class PlainTextFormatter(Formatter):
    """Formatter that outputs plain text without any formatting."""

    def format_answer(self, text: str) -> str:
        """Format answer text as plain text.

        Args:
            text: The answer text.

        Returns:
            Plain text answer (unchanged).
        """
        return text.rstrip()

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
