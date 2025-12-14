"""JSON formatter for structured JSON output."""

import json
import re
from typing import Any

from perplexity_cli.api.models import Answer, WebResult
from perplexity_cli.formatting.base import Formatter


class JSONFormatter(Formatter):
    """Formatter that outputs response as structured JSON."""

    def format_answer(self, text: str, strip_references: bool = False) -> str:
        """Format answer text (not used in JSON formatter).

        This method is not used by the JSON formatter as it works with
        complete Answer objects instead.

        Args:
            text: The answer text.
            strip_references: If True, remove citation numbers like [1], [2], etc.

        Returns:
            The text (passed through).
        """
        if strip_references:
            text = re.sub(r"\[\d+\]", "", text)
        return text.rstrip()

    def format_references(self, references: list[WebResult]) -> str:
        """Format references (not used in JSON formatter).

        This method is not used by the JSON formatter as it works with
        complete Answer objects instead.

        Args:
            references: List of web results.

        Returns:
            Empty string.
        """
        return ""

    def format_complete(self, answer: Answer, strip_references: bool = False) -> str:
        """Format complete answer as JSON.

        Args:
            answer: Answer object containing text and references.
            strip_references: If True, exclude references from JSON output.

        Returns:
            Complete JSON formatted output.
        """
        # Build the output dictionary
        output: dict[str, Any] = {
            "format_version": "1.0",
            "answer": self.format_answer(answer.text, strip_references=strip_references),
        }

        # Add references if present and not stripped
        if answer.references and not strip_references:
            output["references"] = [
                {
                    "index": i,
                    "title": ref.name,
                    "url": ref.url,
                    "snippet": ref.snippet if ref.snippet else None,
                }
                for i, ref in enumerate(answer.references, 1)
            ]
        else:
            output["references"] = []

        # Convert to JSON and return
        return json.dumps(output, indent=2, ensure_ascii=False)
