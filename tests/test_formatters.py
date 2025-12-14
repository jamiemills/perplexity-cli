"""Tests for output formatters."""

import json

import pytest

from perplexity_cli.api.models import Answer, WebResult
from perplexity_cli.formatting import get_formatter, list_formatters
from perplexity_cli.formatting.json import JSONFormatter
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
        assert "Answer text" in result
        assert "## References" in result


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


class TestStripReferences:
    """Test strip_references functionality across all formatters."""

    def test_plain_formatter_strips_citations(self):
        """Test that plain formatter removes citation numbers."""
        formatter = PlainTextFormatter()
        text = "This is answer text[1] with citations[2] and more[3]."
        result = formatter.format_answer(text, strip_references=True)
        assert "[1]" not in result
        assert "[2]" not in result
        assert "[3]" not in result
        assert "This is answer text with citations and more." in result

    def test_plain_formatter_keeps_citations_by_default(self):
        """Test that plain formatter keeps citations by default."""
        formatter = PlainTextFormatter()
        text = "This is answer text[1] with citations[2]."
        result = formatter.format_answer(text)
        assert "[1]" in result
        assert "[2]" in result

    def test_plain_formatter_complete_strips_references(self):
        """Test that format_complete strips references section when requested."""
        formatter = PlainTextFormatter()
        refs = [WebResult(name="Test", url="https://test.com", snippet="test")]
        answer = Answer(text="Answer text[1]", references=refs)
        result = formatter.format_complete(answer, strip_references=True)
        assert "Answer text" in result
        assert "References" not in result
        assert "https://test.com" not in result
        assert "[1]" not in result

    def test_markdown_formatter_strips_citations(self):
        """Test that markdown formatter removes citation numbers."""
        formatter = MarkdownFormatter()
        text = "Answer text[1] with citations[2]."
        result = formatter.format_answer(text, strip_references=True)
        assert "[1]" not in result
        assert "[2]" not in result

    def test_markdown_formatter_complete_strips_references(self):
        """Test that format_complete strips references section when requested."""
        formatter = MarkdownFormatter()
        refs = [WebResult(name="Test", url="https://test.com", snippet="test")]
        answer = Answer(text="Answer text[1]", references=refs)
        result = formatter.format_complete(answer, strip_references=True)
        assert "Answer text" in result
        assert "## References" not in result
        assert "https://test.com" not in result

    def test_rich_formatter_strips_citations(self):
        """Test that rich formatter removes citation numbers."""
        formatter = RichFormatter()
        text = "Answer text[1] with citations[2]."
        result = formatter.format_answer(text, strip_references=True)
        assert "[1]" not in result
        assert "[2]" not in result

    def test_rich_formatter_complete_strips_references(self):
        """Test that format_complete strips references section when requested."""
        formatter = RichFormatter()
        refs = [WebResult(name="Test", url="https://test.com", snippet="test")]
        answer = Answer(text="Answer text[1]", references=refs)
        result = formatter.format_complete(answer, strip_references=True)
        assert "Answer text" in result
        assert "References" not in result
        assert "https://test.com" not in result


class TestJSONFormatter:
    """Test JSONFormatter."""

    def test_format_answer(self):
        """Test formatting answer text."""
        formatter = JSONFormatter()
        result = formatter.format_answer("Test answer")
        assert result == "Test answer"

    def test_format_answer_strips_citations(self):
        """Test that citations are stripped when requested."""
        formatter = JSONFormatter()
        text = "Answer text[1] with citations[2]."
        result = formatter.format_answer(text, strip_references=True)
        assert "[1]" not in result
        assert "[2]" not in result
        assert "Answer text with citations." in result

    def test_format_references(self):
        """Test that format_references returns empty string (not used in JSON)."""
        formatter = JSONFormatter()
        refs = [WebResult(name="Test", url="https://test.com", snippet="test")]
        result = formatter.format_references(refs)
        assert result == ""

    def test_format_complete_basic(self):
        """Test formatting complete answer as JSON."""
        formatter = JSONFormatter()
        answer = Answer(text="Test answer", references=[])
        result = formatter.format_complete(answer)

        # Parse JSON to verify structure
        parsed = json.loads(result)
        assert parsed["format_version"] == "1.0"
        assert parsed["answer"] == "Test answer"
        assert parsed["references"] == []

    def test_format_complete_with_references(self):
        """Test JSON output includes references."""
        formatter = JSONFormatter()
        refs = [
            WebResult(
                name="Test Source",
                url="https://test.com",
                snippet="This is a test snippet"
            ),
            WebResult(
                name="Second Source",
                url="https://test2.com",
                snippet="Another snippet"
            ),
        ]
        answer = Answer(text="Answer text", references=refs)
        result = formatter.format_complete(answer)

        parsed = json.loads(result)
        assert parsed["format_version"] == "1.0"
        assert parsed["answer"] == "Answer text"
        assert len(parsed["references"]) == 2

        # Verify reference structure
        ref1 = parsed["references"][0]
        assert ref1["index"] == 1
        assert ref1["title"] == "Test Source"
        assert ref1["url"] == "https://test.com"
        assert ref1["snippet"] == "This is a test snippet"

        ref2 = parsed["references"][1]
        assert ref2["index"] == 2
        assert ref2["title"] == "Second Source"

    def test_format_complete_strips_references(self):
        """Test that references are excluded when strip_references is True."""
        formatter = JSONFormatter()
        refs = [WebResult(name="Test", url="https://test.com", snippet="test")]
        answer = Answer(text="Answer text[1]", references=refs)
        result = formatter.format_complete(answer, strip_references=True)

        parsed = json.loads(result)
        assert parsed["answer"] == "Answer text"  # Citation stripped
        assert parsed["references"] == []

    def test_format_complete_null_snippets(self):
        """Test that null snippets are handled correctly."""
        formatter = JSONFormatter()
        refs = [WebResult(name="Test", url="https://test.com", snippet=None)]
        answer = Answer(text="Answer", references=refs)
        result = formatter.format_complete(answer)

        parsed = json.loads(result)
        assert parsed["references"][0]["snippet"] is None

    def test_json_output_is_valid(self):
        """Test that output is always valid JSON."""
        formatter = JSONFormatter()
        refs = [
            WebResult(name="Test", url="https://test.com", snippet="test"),
            WebResult(name="Test2", url="https://test2.com", snippet=None),
        ]
        answer = Answer(text="Complex answer\nwith\nmultiple\nlines", references=refs)
        result = formatter.format_complete(answer)

        # Should not raise an exception
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert "format_version" in parsed
        assert "answer" in parsed
        assert "references" in parsed

    def test_json_formatter_in_registry(self):
        """Test that JSON formatter is registered."""
        formatters = list_formatters()
        assert "json" in formatters

        formatter = get_formatter("json")
        assert isinstance(formatter, JSONFormatter)
