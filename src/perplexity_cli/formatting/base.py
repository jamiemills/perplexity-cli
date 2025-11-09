"""Base formatter interface for output formatting."""

from abc import ABC, abstractmethod

from perplexity_cli.api.models import Answer, WebResult


class Formatter(ABC):
    """Abstract base class for output formatters."""

    @abstractmethod
    def format_answer(self, text: str) -> str:
        """Format answer text.

        Args:
            text: The answer text to format.

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

    def format_complete(self, answer: Answer) -> str:
        """Format complete answer with references.

        Args:
            answer: Answer object containing text and references.

        Returns:
            Complete formatted output.
        """
        output_parts = []

        # Add formatted answer
        formatted_answer = self.format_answer(answer.text)
        output_parts.append(formatted_answer)

        # Add formatted references if present
        if answer.references:
            formatted_refs = self.format_references(answer.references)
            if formatted_refs:
                output_parts.append(formatted_refs)

        return "\n".join(output_parts)

    def should_use_colors(self) -> bool:
        """Check if colours should be used based on TTY and environment.

        Returns:
            True if colours should be used, False otherwise.
        """
        import os
        import sys

        # Respect NO_COLOR environment variable
        if os.environ.get("NO_COLOR"):
            return False

        # Check if stdout is a TTY
        return sys.stdout.isatty()
