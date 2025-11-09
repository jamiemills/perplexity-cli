"""Tests for output formatters."""

import pytest

from perplexity_cli.api.models import Answer, WebResult
from perplexity_cli.formatting import get_formatter, list_formatters
from perplexity_cli.formatting.markdown import MarkdownFormatter
from perplexity_cli.formatting.plain import PlainTextFormatter
from perplexity_cli.formatting.rich import RichFormatter


class TestPlainTextFormatter:
    """Test PlainTextFormatter."""

    def test_format_answer(self):
        """Test formatting answer text."""
        formatter = PlainTextFormatter()
        result = formatter.format_answer("Test answer")
        assert result == "\nTest answer"

    def test_format_answer_strips_trailing_whitespace(self):
        """Test that trailing whitespace is stripped."""
        formatter = PlainTextFormatter()
        result = formatter.format_answer("Test answer\n\n")
        assert result == "\nTest answer"

    def test_format_references(self):
        """Test formatting references."""
        formatter = PlainTextFormatter()
        refs = [
            WebResult(name="Test", url="https://test.com", snippet="test"),
            WebResult(name="Test2", url="https://test2.com", snippet="test2"),
        ]
        result = formatter.format_references(refs)
        assert "[1] https://test.com" in result
        assert "[2] https://test2.com" in result

    def test_format_references_empty(self):
        """Test formatting empty references."""
        formatter = PlainTextFormatter()
        result = formatter.format_references([])
        assert result == ""

    def test_format_complete(self):
        """Test formatting complete answer."""
        formatter = PlainTextFormatter()
        refs = [WebResult(name="Test", url="https://test.com", snippet="test")]
        answer = Answer(text="Answer text", references=refs)
        result = formatter.format_complete(answer)
        assert "Answer text" in result
        assert "References" in result
        assert "https://test.com" in result


class TestMarkdownFormatter:
    """Test MarkdownFormatter."""

    def test_format_answer(self):
        """Test formatting answer as Markdown."""
        formatter = MarkdownFormatter()
        result = formatter.format_answer("Test answer")
        assert "## Answer" in result
        assert "Test answer" in result

    def test_format_references(self):
        """Test formatting references as Markdown."""
        formatter = MarkdownFormatter()
        refs = [WebResult(name="Test", url="https://test.com", snippet="test")]
        result = formatter.format_references(refs)
        assert "## References" in result
        assert "[Test]" in result
        assert "https://" in result

    def test_format_references_with_snippet(self):
        """Test that snippets are included in Markdown."""
        formatter = MarkdownFormatter()
        refs = [WebResult(name="Test", url="https://test.com", snippet="test snippet")]
        result = formatter.format_references(refs)
        assert "test snippet" in result

    def test_format_complete(self):
        """Test complete Markdown document."""
        formatter = MarkdownFormatter()
        refs = [WebResult(name="Test", url="https://test.com", snippet="test")]
        answer = Answer(text="Answer text", references=refs)
        result = formatter.format_complete(answer)
        assert "# Answer from Perplexity" in result
        assert "## Answer" in result
        assert "## References" in result
        assert "Generated:" in result


class TestRichFormatter:
    """Test RichFormatter."""

    def test_format_answer(self):
        """Test formatting answer with Rich."""
        formatter = RichFormatter()
        result = formatter.format_answer("Test answer")
        assert "Test answer" in result

    def test_format_references(self):
        """Test formatting references as Rich table."""
        formatter = RichFormatter()
        refs = [WebResult(name="Test", url="https://test.com", snippet="test")]
        result = formatter.format_references(refs)
        assert "Test" in result
        assert "https://test.com" in result

    def test_format_complete(self):
        """Test complete Rich formatted output."""
        formatter = RichFormatter()
        refs = [WebResult(name="Test", url="https://test.com", snippet="test")]
        answer = Answer(text="Answer text", references=refs)
        result = formatter.format_complete(answer)
        assert "Answer text" in result
        assert "Test" in result or "https://test.com" in result

    def test_code_block_handling(self):
        """Test that code blocks are detected and handled."""
        formatter = RichFormatter()
        text_with_code = '```python\nprint("hello")\n```'
        result = formatter.format_answer(text_with_code)
        assert "print" in result


class TestFormatterRegistry:
    """Test formatter registry."""

    def test_list_formatters(self):
        """Test listing available formatters."""
        formatters = list_formatters()
        assert "plain" in formatters
        assert "markdown" in formatters
        assert "rich" in formatters

    def test_get_formatter(self):
        """Test getting formatters by name."""
        plain = get_formatter("plain")
        assert isinstance(plain, PlainTextFormatter)

        markdown = get_formatter("markdown")
        assert isinstance(markdown, MarkdownFormatter)

        rich = get_formatter("rich")
        assert isinstance(rich, RichFormatter)

    def test_get_invalid_formatter(self):
        """Test error on invalid formatter name."""
        with pytest.raises(ValueError):
            get_formatter("invalid")
