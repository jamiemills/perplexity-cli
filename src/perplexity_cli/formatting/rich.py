"""Advanced terminal formatter using Rich library with colours and tables."""

import re

from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from perplexity_cli.api.models import Answer, WebResult
from perplexity_cli.formatting.base import Formatter


class RichFormatter(Formatter):
    """Formatter using Rich library for advanced terminal output."""

    def __init__(self) -> None:
        """Initialize Rich formatter."""
        # Console for direct output to terminal with styling
        # width=200 allows long URLs to not be truncated
        self.console = Console(force_terminal=True, legacy_windows=False, width=200)

    def format_answer(self, text: str, strip_references: bool = False) -> str:
        """Format answer text with Rich styling.

        Args:
            text: The answer text.
            strip_references: If True, remove citation numbers like [1], [2], etc.

        Returns:
            Rich-formatted answer with syntax highlighting for code.
        """
        # Strip citation references if requested
        if strip_references:
            text = re.sub(r"\[\d+\]", "", text)

        # Process the text to highlight code blocks
        formatted_text = self._process_answer_text(text)
        return formatted_text.rstrip()

    def format_references(self, references: list[WebResult]) -> str:
        """Format references as a Rich table.

        Args:
            references: List of web results.

        Returns:
            Rich-formatted references table.
        """
        if not references:
            return ""

        # Create table with text wrapping
        table = Table(
            title="References", show_header=True, header_style="bold cyan", padding=(0, 1)
        )
        table.add_column("#", style="cyan", width=3, no_wrap=True)
        table.add_column("Source", style="white", no_wrap=False, max_width=40)
        table.add_column("URL", style="bright_blue", no_wrap=False, max_width=120)

        # Add rows
        for i, ref in enumerate(references, 1):
            table.add_row(str(i), ref.name, ref.url)

        # Render table to string with ANSI codes
        from io import StringIO

        string_buffer = StringIO()
        temp_console = Console(file=string_buffer, force_terminal=True, legacy_windows=False)
        temp_console.print(table)
        return string_buffer.getvalue().rstrip()

    def render_complete(self, answer: Answer, strip_references: bool = False) -> None:
        """Render complete answer directly to Rich Console.

        Args:
            answer: Answer object with text and references.
            strip_references: If True, exclude references section from output.
        """
        # Answer section - render markdown with left alignment
        # Parse and style markdown while keeping text left-aligned
        answer_text = answer.text
        if strip_references:
            answer_text = re.sub(r"\[\d+\]", "", answer_text)

        self._print_formatted_text(answer_text)

        # References section (only if not stripped)
        if answer.references and not strip_references:
            self.console.print()
            self.console.print("─" * 50, style="dim")
            self.console.print()
            self.console.print(Text("References", style="bold cyan"))
            self.console.print()

            # Create and print references table with text wrapping
            # Use no_wrap=True for # column, but allow wrapping for others
            table = Table(show_header=True, header_style="bold cyan", padding=(0, 1))
            table.add_column("#", style="cyan", width=3, no_wrap=True)
            table.add_column("Source", style="white", no_wrap=False, max_width=40)
            table.add_column("URL", style="bright_blue", no_wrap=False, max_width=120)

            for i, ref in enumerate(answer.references, 1):
                table.add_row(str(i), ref.name, ref.url)

            self.console.print(table)

    def format_complete(self, answer: Answer, strip_references: bool = False) -> str:
        """Format complete answer with Rich styling.

        Args:
            answer: Answer object with text and references.
            strip_references: If True, exclude references section from output.

        Returns:
            Complete Rich-formatted output (with ANSI codes for terminal).
        """
        from io import StringIO

        string_buffer = StringIO()
        # Force terminal mode to preserve ANSI colour codes
        output_console = Console(file=string_buffer, force_terminal=True, legacy_windows=False)

        # Answer section
        answer_text = answer.text
        if strip_references:
            answer_text = re.sub(r"\[\d+\]", "", answer_text)

        formatted_answer = self._process_answer_text(answer_text)
        output_console.print(formatted_answer)

        # References section (only if not stripped)
        if answer.references and not strip_references:
            output_console.print()
            output_console.print("─" * 50, style="dim")
            output_console.print()

            # Create and print references table
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("#", style="cyan", width=3)
            table.add_column("Source", style="white")
            table.add_column("URL", style="bright_blue")

            for i, ref in enumerate(answer.references, 1):
                table.add_row(str(i), ref.name, ref.url)

            output_console.print(table)

        return string_buffer.getvalue().rstrip()

    def _print_formatted_text(self, text: str) -> None:
        """Print text with markdown styling but left-aligned.

        Args:
            text: Text possibly containing markdown syntax.
        """
        import re

        lines = text.split("\n")
        for line in lines:
            # Check for headers (###, ##, #)
            header_match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if header_match:
                hashes = header_match.group(1)
                content = header_match.group(2)
                level = len(hashes)
                # Style based on header level
                if level == 1:
                    style = "bold bright_cyan"
                elif level == 2:
                    style = "bold cyan"
                else:
                    style = "bold white"
                self.console.print(Text(content, style=style))
            else:
                # Regular text - handle inline markdown
                # Simple approach: just print as-is (Rich will still render markdown markup)
                self.console.print(line)

    def _process_answer_text(self, text: str) -> str:
        """Process answer text to add syntax highlighting and formatting.

        Args:
            text: Raw answer text.

        Returns:
            Processed text with syntax highlighting applied.
        """
        # Find code blocks and highlight them
        result_parts = []
        pattern = r"```(\w*)\n(.*?)\n```"
        last_end = 0

        for match in re.finditer(pattern, text, re.DOTALL):
            # Add text before code block
            before_text = text[last_end : match.start()]
            if before_text:
                result_parts.append(before_text)

            # Add highlighted code block
            language = match.group(1) or "text"
            code_content = match.group(2)
            try:
                syntax = Syntax(code_content, language, theme="monokai", line_numbers=False)
                from io import StringIO

                code_buffer = StringIO()
                code_console = Console(file=code_buffer, legacy_windows=False)
                code_console.print(syntax)
                result_parts.append(code_buffer.getvalue().rstrip())
            except Exception:
                # Fallback to plain code if syntax highlighting fails
                result_parts.append(f"```{language}\n{code_content}\n```")

            last_end = match.end()

        # Add remaining text
        if last_end < len(text):
            result_parts.append(text[last_end:])

        return "".join(result_parts)
