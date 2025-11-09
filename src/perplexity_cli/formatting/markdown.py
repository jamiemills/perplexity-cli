"""GitHub-flavoured Markdown formatter for structured output."""

from datetime import datetime

from perplexity_cli.api.models import WebResult
from perplexity_cli.formatting.base import Formatter


class MarkdownFormatter(Formatter):
    """Formatter that outputs GitHub-flavoured Markdown."""

    def format_answer(self, text: str) -> str:
        """Format answer as Markdown section.

        Args:
            text: The answer text.

        Returns:
            Markdown formatted answer.
        """
        return text.rstrip()

    def format_references(self, references: list[WebResult]) -> str:
        """Format references as Markdown list with links.

        Args:
            references: List of web results.

        Returns:
            Markdown formatted references section.
        """
        if not references:
            return ""

        lines = ["## References"]
        for i, ref in enumerate(references, 1):
            # Format: [number]. [Name](URL) - "Snippet"
            snippet_text = f' - "{self._escape_markdown(ref.snippet)}"' if ref.snippet else ""
            escaped_url = self._escape_markdown(ref.url)
            escaped_name = self._escape_markdown(ref.name)
            lines.append(f"{i}. [{escaped_name}]({escaped_url}){snippet_text}")

        return "\n".join(lines)

    def format_complete(self, answer) -> str:  # type: ignore
        """Format complete answer with Markdown structure.

        Args:
            answer: Answer object with text and references.

        Returns:
            Complete Markdown document.
        """
        lines = []

        # Answer section
        formatted_answer = self.format_answer(answer.text)
        lines.append(formatted_answer)

        # References section
        if answer.references:
            lines.append("")
            formatted_refs = self.format_references(answer.references)
            lines.append(formatted_refs)

        return "\n".join(lines)

    @staticmethod
    def _escape_markdown(text: str) -> str:
        """Escape special Markdown characters.

        Args:
            text: Text to escape.

        Returns:
            Escaped text.
        """
        # Escape special Markdown characters
        special_chars = ["\\", "`", "*", "_", "{", "}", "[", "]", "(", ")", "#", "+", "-", ".", "!"]
        escaped = text
        for char in special_chars:
            escaped = escaped.replace(char, f"\\{char}")
        return escaped
