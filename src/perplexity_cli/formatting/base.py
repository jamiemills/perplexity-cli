"""Base formatter interface for output formatting."""

from abc import ABC, abstractmethod

from perplexity_cli.api.models import Answer, WebResult


class Formatter(ABC):
    """Abstract base class for output formatters."""

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
