"""Mutation-killing tests for formatting/ modules."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from perplexity_cli.api.models import Answer, WebResult
from perplexity_cli.formatting.base import (
    Formatter,
    _collect_code_block,
    _collect_prose_paragraph,
    _collect_structural_block,
    _dispatch_line,
    _is_continuation_line,
    _is_prose_boundary,
    _is_structural_line,
    should_use_plain_default,
)
from perplexity_cli.formatting.context import OutputOptions, RenderContext
from perplexity_cli.formatting.json import JSONFormatter
from perplexity_cli.formatting.markdown import MarkdownFormatter
from perplexity_cli.formatting.plain import (
    PlainTextFormatter,
    _process_blank_line,
    _process_header,
    _process_plain_line,
    _strip_markdown_emphasis,
)
from perplexity_cli.formatting.registry import FormatterRegistry, resolve_format
from perplexity_cli.formatting.rich import RichFormatter


class TestIsStructuralLine:
    def test_h1(self) -> None:
        assert _is_structural_line("# Header") is True

    def test_h2(self) -> None:
        assert _is_structural_line("## Header") is True

    def test_h3(self) -> None:
        assert _is_structural_line("### Header") is True

    def test_h6(self) -> None:
        assert _is_structural_line("###### Header") is True

    def test_h7_not_structural(self) -> None:
        assert _is_structural_line("####### Not a header") is False

    def test_hash_no_space(self) -> None:
        assert _is_structural_line("#NoSpace") is False

    def test_dash_list(self) -> None:
        assert _is_structural_line("- item") is True

    def test_asterisk_list(self) -> None:
        assert _is_structural_line("* item") is True

    def test_plus_list(self) -> None:
        assert _is_structural_line("+ item") is True

    def test_numbered_list(self) -> None:
        assert _is_structural_line("1. item") is True

    def test_multi_digit_numbered(self) -> None:
        assert _is_structural_line("10. item") is True

    def test_blockquote(self) -> None:
        assert _is_structural_line("> quote") is True

    def test_table_pipe(self) -> None:
        assert _is_structural_line("| col |") is True

    def test_horizontal_rule_dashes(self) -> None:
        assert _is_structural_line("---") is True

    def test_horizontal_rule_asterisks(self) -> None:
        assert _is_structural_line("***") is True

    def test_horizontal_rule_two_dashes_not(self) -> None:
        assert _is_structural_line("--") is False

    def test_plain_text(self) -> None:
        assert _is_structural_line("just text") is False

    def test_empty_string(self) -> None:
        assert _is_structural_line("") is False


class TestIsContinuationLine:
    def test_indented_non_structural(self) -> None:
        assert _is_continuation_line("  continued text", "continued text") is True

    def test_not_indented(self) -> None:
        assert _is_continuation_line("same line", "same line") is False

    def test_empty_stripped(self) -> None:
        assert _is_continuation_line("  ", "") is False

    def test_indented_code_fence(self) -> None:
        assert _is_continuation_line("  ```python", "```python") is False

    def test_indented_structural(self) -> None:
        assert _is_continuation_line("  - item", "- item") is False

    def test_indented_header(self) -> None:
        assert _is_continuation_line("  # header", "# header") is False


class TestIsProseBoundary:
    def test_blank_line(self) -> None:
        assert _is_prose_boundary("", "") is True

    def test_whitespace_only(self) -> None:
        assert _is_prose_boundary("   ", "") is True

    def test_code_fence(self) -> None:
        assert _is_prose_boundary("```python", "```python") is True

    def test_structural_line(self) -> None:
        assert _is_prose_boundary("# Header", "# Header") is True

    def test_regular_text(self) -> None:
        assert _is_prose_boundary("regular text", "regular text") is False


class TestCollectCodeBlock:
    def test_closed_block(self) -> None:
        lines = ["```python", "code here", "```", "after"]
        result: list[str] = []
        next_idx = _collect_code_block(lines, 0, result)
        assert next_idx == 3
        assert result == ["```python", "code here", "```"]

    def test_unclosed_block(self) -> None:
        lines = ["```python", "code here", "more code"]
        result: list[str] = []
        next_idx = _collect_code_block(lines, 0, result)
        assert next_idx == 3
        assert result == ["```python", "code here", "more code"]

    def test_single_fence_line(self) -> None:
        lines = ["```"]
        result: list[str] = []
        next_idx = _collect_code_block(lines, 0, result)
        assert next_idx == 1
        assert result == ["```"]


class TestCollectStructuralBlock:
    def test_no_continuation(self) -> None:
        lines = ["- item one", "- item two"]
        result: list[str] = []
        next_idx = _collect_structural_block(lines, 0, result)
        assert next_idx == 1
        assert result == ["- item one"]

    def test_with_continuation(self) -> None:
        lines = ["- item one", "  continued here", "- item two"]
        result: list[str] = []
        next_idx = _collect_structural_block(lines, 0, result)
        assert next_idx == 2
        assert result == ["- item one continued here"]


class TestCollectProseParagraph:
    def test_single_line(self) -> None:
        lines = ["just text", "", "next para"]
        result: list[str] = []
        next_idx = _collect_prose_paragraph(lines, 0, result)
        assert next_idx == 1
        assert result == ["just text"]

    def test_multi_line_join(self) -> None:
        lines = ["line one", "line two", "", "next"]
        result: list[str] = []
        next_idx = _collect_prose_paragraph(lines, 0, result)
        assert next_idx == 2
        assert result == ["line one line two"]

    def test_stops_at_structural(self) -> None:
        lines = ["prose text", "# Header"]
        result: list[str] = []
        next_idx = _collect_prose_paragraph(lines, 0, result)
        assert next_idx == 1
        assert result == ["prose text"]


class TestDispatchLine:
    def test_code_block(self) -> None:
        lines = ["```", "code", "```"]
        result: list[str] = []
        next_idx = _dispatch_line(lines, 0, result)
        assert next_idx == 3

    def test_blank_line(self) -> None:
        lines = ["", "text"]
        result: list[str] = []
        next_idx = _dispatch_line(lines, 0, result)
        assert next_idx == 1
        assert result == [""]

    def test_structural_line(self) -> None:
        lines = ["# Header", "text"]
        result: list[str] = []
        next_idx = _dispatch_line(lines, 0, result)
        assert next_idx == 1
        assert result == ["# Header"]

    def test_prose_line(self) -> None:
        lines = ["prose text", "more prose", ""]
        result: list[str] = []
        next_idx = _dispatch_line(lines, 0, result)
        assert next_idx == 2
        assert result == ["prose text more prose"]


class TestStripCitations:
    def test_removes_single(self) -> None:
        assert Formatter.strip_citations("text[1]more") == "textmore"

    def test_removes_multiple(self) -> None:
        assert Formatter.strip_citations("a[1]b[2]c[3]") == "abc"

    def test_removes_multi_digit(self) -> None:
        assert Formatter.strip_citations("text[12]more") == "textmore"

    def test_no_citations(self) -> None:
        assert Formatter.strip_citations("no citations here") == "no citations here"

    def test_empty_string(self) -> None:
        assert Formatter.strip_citations("") == ""

    def test_removes_zero_index_brackets(self) -> None:
        assert Formatter.strip_citations("array[0]") == "array"


class TestUnwrapParagraphLines:
    def test_empty_returns_empty(self) -> None:
        assert PlainTextFormatter().unwrap_paragraph_lines("") == ""

    def test_single_line_unchanged(self) -> None:
        text = "single line"
        assert PlainTextFormatter().unwrap_paragraph_lines(text) == "single line"

    def test_joins_prose(self) -> None:
        text = "line one\nline two"
        result = PlainTextFormatter().unwrap_paragraph_lines(text)
        assert result == "line one line two"


class TestRenderComplete:
    def test_base_raises_not_implemented(self) -> None:
        formatter = PlainTextFormatter()
        answer = Answer(text="test", references=[])
        with pytest.raises(NotImplementedError, match="does not support direct rendering"):
            Formatter.render_complete(formatter, answer)


class TestShouldUseColors:
    def test_no_color_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        formatter = PlainTextFormatter()
        assert formatter.should_use_colors() is False

    def test_no_color_empty_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NO_COLOR", "")
        formatter = PlainTextFormatter()
        assert formatter.should_use_colors() is False

    def test_no_no_color_not_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = False
            formatter = PlainTextFormatter()
            assert formatter.should_use_colors() is False


class TestShouldUsePlainDefault:
    def test_not_tty(self) -> None:
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = False
            assert should_use_plain_default() is True

    def test_tty_no_color(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert should_use_plain_default() is True

    def test_tty_with_color(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert should_use_plain_default() is False


class TestPlainTextHelpers:
    def test_strip_bold(self) -> None:
        assert _strip_markdown_emphasis("**bold**") == "bold"

    def test_strip_italic(self) -> None:
        assert _strip_markdown_emphasis("*italic*") == "italic"

    def test_strip_mixed(self) -> None:
        assert _strip_markdown_emphasis("**bold** and *italic*") == "bold and italic"

    def test_no_emphasis(self) -> None:
        assert _strip_markdown_emphasis("plain text") == "plain text"

    def test_process_header_non_header(self) -> None:
        result: list[str] = []
        was_header, blank_count = _process_header("not a header", result)
        assert was_header is False
        assert blank_count == 0
        assert result == []

    def test_process_header_h1(self) -> None:
        result: list[str] = []
        was_header, blank_count = _process_header("# Title", result)
        assert was_header is True
        assert blank_count == 0
        assert result == ["Title", "====="]

    def test_process_header_h2(self) -> None:
        result: list[str] = []
        was_header, _ = _process_header("## Section", result)
        assert was_header is True
        assert result == ["Section", "======="]

    def test_process_header_with_existing_content(self) -> None:
        result: list[str] = ["existing"]
        was_header, _ = _process_header("# Title", result)
        assert was_header is True
        assert result == ["existing", "", "Title", "====="]

    def test_process_header_strips_emphasis(self) -> None:
        result: list[str] = []
        was_header, _ = _process_header("# **Bold Title**", result)
        assert was_header is True
        assert result == ["Bold Title", "=========="]

    def test_process_blank_line_skip(self) -> None:
        result: list[str] = []
        skip, count = _process_blank_line(result, True, 0)
        assert skip is False
        assert result == []

    def test_process_blank_line_first(self) -> None:
        result: list[str] = []
        skip, count = _process_blank_line(result, False, 0)
        assert skip is False
        assert count == 1
        assert result == [""]

    def test_process_blank_line_second(self) -> None:
        result: list[str] = []
        skip, count = _process_blank_line(result, False, 1)
        assert count == 2
        assert result == [""]

    def test_process_blank_line_third_suppressed(self) -> None:
        result: list[str] = []
        skip, count = _process_blank_line(result, False, 2)
        assert count == 3
        assert result == []

    def test_process_plain_line_horizontal_rule(self) -> None:
        result: list[str] = []
        skip, count = _process_plain_line("---", result, False, 0)
        assert result == []

    def test_process_plain_line_asterisk_rule(self) -> None:
        result: list[str] = []
        skip, count = _process_plain_line("***", result, False, 0)
        assert result == []

    def test_process_plain_line_normal_text(self) -> None:
        result: list[str] = []
        skip, count = _process_plain_line("hello **world**", result, False, 0)
        assert result == ["hello world"]
        assert skip is False
        assert count == 0

    def test_process_plain_line_header_sets_skip(self) -> None:
        result: list[str] = []
        skip, count = _process_plain_line("# Title", result, False, 0)
        assert skip is True
        assert count == 0


class TestPlainTextFormatter:
    def test_format_answer_empty(self) -> None:
        formatter = PlainTextFormatter()
        assert formatter.format_answer("") == ""

    def test_format_answer_strips_citations(self) -> None:
        formatter = PlainTextFormatter()
        result = formatter.format_answer("text[1] more[2]", strip_references=True)
        assert "[1]" not in result
        assert "[2]" not in result
        assert "text more" in result

    def test_format_complete_no_references(self) -> None:
        formatter = PlainTextFormatter()
        answer = Answer(text="Answer text", references=[])
        result = formatter.format_complete(answer)
        assert result == "Answer text"

    def test_format_complete_with_references(self) -> None:
        formatter = PlainTextFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet="s")]
        answer = Answer(text="Answer", references=refs)
        result = formatter.format_complete(answer)
        assert "Answer" in result
        assert "References" in result
        assert "https://src.com" in result

    def test_format_complete_strip_references(self) -> None:
        formatter = PlainTextFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet="s")]
        answer = Answer(text="Answer[1]", references=refs)
        result = formatter.format_complete(answer, strip_references=True)
        assert "References" not in result
        assert "[1]" not in result

    def test_format_references_ruler(self) -> None:
        formatter = PlainTextFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet="s")]
        result = formatter.format_references(refs)
        assert "─" * 50 in result

    def test_format_references_underline(self) -> None:
        formatter = PlainTextFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet="s")]
        result = formatter.format_references(refs)
        assert "References" in result
        assert "=" * len("References") in result

    def test_format_references_numbered(self) -> None:
        formatter = PlainTextFormatter()
        refs = [
            WebResult(name="A", url="https://a.com", snippet="a"),
            WebResult(name="B", url="https://b.com", snippet="b"),
        ]
        result = formatter.format_references(refs)
        assert "[1] https://a.com" in result
        assert "[2] https://b.com" in result


class TestMarkdownFormatter:
    def test_format_answer_empty(self) -> None:
        formatter = MarkdownFormatter()
        assert formatter.format_answer("") == ""

    def test_format_answer_strips_trailing(self) -> None:
        formatter = MarkdownFormatter()
        assert formatter.format_answer("text\n\n") == "text"

    def test_format_references_empty(self) -> None:
        formatter = MarkdownFormatter()
        assert formatter.format_references([]) == ""

    def test_format_references_header(self) -> None:
        formatter = MarkdownFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet="s")]
        result = formatter.format_references(refs)
        assert result.startswith("## References")

    def test_format_references_with_snippet(self) -> None:
        formatter = MarkdownFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet="a snippet")]
        result = formatter.format_references(refs)
        assert '"a snippet"' in result

    def test_format_references_without_snippet(self) -> None:
        formatter = MarkdownFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet=None)]
        result = formatter.format_references(refs)
        assert '"' not in result

    def test_format_complete_no_references(self) -> None:
        formatter = MarkdownFormatter()
        answer = Answer(text="Answer", references=[])
        result = formatter.format_complete(answer)
        assert result == "Answer"

    def test_format_complete_with_references(self) -> None:
        formatter = MarkdownFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet="s")]
        answer = Answer(text="Answer", references=refs)
        result = formatter.format_complete(answer)
        assert "## References" in result

    def test_escape_markdown_special_chars(self) -> None:
        result = MarkdownFormatter._escape_markdown("a*b_c[d")
        assert "\\*" in result
        assert "\\_" in result
        assert "\\[" in result

    def test_escape_markdown_backslash(self) -> None:
        result = MarkdownFormatter._escape_markdown("a\\b")
        assert "\\\\" in result

    def test_escape_markdown_hash(self) -> None:
        result = MarkdownFormatter._escape_markdown("# heading")
        assert "\\#" in result

    def test_escape_markdown_parens(self) -> None:
        result = MarkdownFormatter._escape_markdown("(text)")
        assert "\\(" in result
        assert "\\)" in result


class TestRichFormatter:
    def test_format_answer_empty(self) -> None:
        formatter = RichFormatter()
        assert formatter.format_answer("") == ""

    def test_format_answer_strips_trailing(self) -> None:
        formatter = RichFormatter()
        result = formatter.format_answer("text\n\n")
        assert not result.endswith("\n")

    def test_format_references_empty(self) -> None:
        formatter = RichFormatter()
        assert formatter.format_references([]) == ""

    def test_format_references_table(self) -> None:
        formatter = RichFormatter()
        refs = [WebResult(name="Source", url="https://src.com", snippet="s")]
        result = formatter.format_references(refs)
        assert "Source" in result
        assert "https://src.com" in result

    def test_format_complete_no_references(self) -> None:
        formatter = RichFormatter()
        answer = Answer(text="Answer text", references=[])
        result = formatter.format_complete(answer)
        assert "Answer text" in result

    def test_format_complete_with_references(self) -> None:
        formatter = RichFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet="s")]
        answer = Answer(text="Answer", references=refs)
        result = formatter.format_complete(answer)
        assert "Answer" in result
        assert "Src" in result

    def test_format_complete_strip_references(self) -> None:
        formatter = RichFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet="s")]
        answer = Answer(text="Answer[1]", references=refs)
        result = formatter.format_complete(answer, strip_references=True)
        assert "[1]" not in result
        assert "Src" not in result

    def test_process_answer_text_no_code(self) -> None:
        formatter = RichFormatter()
        result = formatter._process_answer_text("plain text")
        assert result == "plain text"

    def test_process_answer_text_with_code(self) -> None:
        formatter = RichFormatter()
        text = "before\n```python\nprint('hi')\n```\nafter"
        result = formatter._process_answer_text(text)
        assert "print" in result

    def test_render_code_block_fallback(self) -> None:
        formatter = RichFormatter()
        result = formatter._render_code_block("nonexistent_lang_xyz", "code here")
        assert "code here" in result

    def test_render_code_block_valid_language(self) -> None:
        formatter = RichFormatter()
        result = formatter._render_code_block("python", "x = 1")
        assert "x" in result

    def test_render_complete_with_references(self) -> None:
        formatter = RichFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet="s")]
        answer = Answer(text="Answer", references=refs)
        formatter.render_complete(answer)

    def test_render_complete_strip_references(self) -> None:
        formatter = RichFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet="s")]
        answer = Answer(text="Answer[1]", references=refs)
        formatter.render_complete(answer, strip_references=True)

    def test_print_formatted_text_h1(self) -> None:
        formatter = RichFormatter()
        formatter._print_formatted_text("# Title")

    def test_print_formatted_text_h2(self) -> None:
        formatter = RichFormatter()
        formatter._print_formatted_text("## Section")

    def test_print_formatted_text_h3(self) -> None:
        formatter = RichFormatter()
        formatter._print_formatted_text("### Subsection")

    def test_print_formatted_text_plain(self) -> None:
        formatter = RichFormatter()
        formatter._print_formatted_text("plain text line")


class TestJSONFormatter:
    def test_format_answer_passthrough(self) -> None:
        formatter = JSONFormatter()
        assert formatter.format_answer("text") == "text"

    def test_format_answer_strips_trailing(self) -> None:
        formatter = JSONFormatter()
        assert formatter.format_answer("text\n\n") == "text"

    def test_format_answer_strips_citations(self) -> None:
        formatter = JSONFormatter()
        result = formatter.format_answer("text[1] more[2]", strip_references=True)
        assert result == "text more"

    def test_format_references_always_empty(self) -> None:
        formatter = JSONFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet="s")]
        assert formatter.format_references(refs) == ""

    def test_format_complete_structure(self) -> None:
        formatter = JSONFormatter()
        answer = Answer(text="Test", references=[])
        parsed = json.loads(formatter.format_complete(answer))
        assert parsed["ok"] is True
        assert parsed["command"] == "pxcli query"
        assert parsed["meta"] is None
        assert parsed["next_actions"] == []

    def test_format_complete_answer_text(self) -> None:
        formatter = JSONFormatter()
        answer = Answer(text="The answer", references=[])
        parsed = json.loads(formatter.format_complete(answer))
        assert parsed["result"]["answer"] == "The answer"

    def test_format_complete_references_included(self) -> None:
        formatter = JSONFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet="snip")]
        answer = Answer(text="Ans", references=refs)
        parsed = json.loads(formatter.format_complete(answer))
        assert len(parsed["result"]["references"]) == 1
        assert parsed["result"]["references"][0]["index"] == 1
        assert parsed["result"]["references"][0]["title"] == "Src"
        assert parsed["result"]["references"][0]["url"] == "https://src.com"
        assert parsed["result"]["references"][0]["snippet"] == "snip"

    def test_format_complete_null_snippet(self) -> None:
        formatter = JSONFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet=None)]
        answer = Answer(text="Ans", references=refs)
        parsed = json.loads(formatter.format_complete(answer))
        assert parsed["result"]["references"][0]["snippet"] is None

    def test_format_complete_strip_references(self) -> None:
        formatter = JSONFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet="s")]
        answer = Answer(text="Ans[1]", references=refs)
        parsed = json.loads(formatter.format_complete(answer, strip_references=True))
        assert parsed["result"]["references"] == []
        assert "[1]" not in parsed["result"]["answer"]

    def test_format_complete_ensure_ascii_false(self) -> None:
        formatter = JSONFormatter()
        answer = Answer(text="café résumé", references=[])
        result = formatter.format_complete(answer)
        assert "café" in result
        assert "\\u" not in result


class TestFormatterRegistry:
    def test_register_and_get(self) -> None:
        registry = FormatterRegistry()
        registry.register("test", PlainTextFormatter)
        formatter = registry.get("test")
        assert isinstance(formatter, PlainTextFormatter)

    def test_get_unknown_raises(self) -> None:
        registry = FormatterRegistry()
        with pytest.raises(ValueError, match="Unknown formatter: nope"):
            registry.get("nope")

    def test_get_unknown_lists_available(self) -> None:
        registry = FormatterRegistry()
        registry.register("alpha", PlainTextFormatter)
        registry.register("beta", MarkdownFormatter)
        with pytest.raises(ValueError, match="alpha, beta"):
            registry.get("gamma")

    def test_names_sorted(self) -> None:
        registry = FormatterRegistry()
        registry.register("zeta", PlainTextFormatter)
        registry.register("alpha", MarkdownFormatter)
        assert registry.names() == ["alpha", "zeta"]

    def test_names_empty(self) -> None:
        registry = FormatterRegistry()
        assert registry.names() == []

    def test_register_overwrites(self) -> None:
        registry = FormatterRegistry()
        registry.register("fmt", PlainTextFormatter)
        registry.register("fmt", MarkdownFormatter)
        formatter = registry.get("fmt")
        assert isinstance(formatter, MarkdownFormatter)


class TestResolveFormat:
    def test_explicit_format_wins(self) -> None:
        assert resolve_format("json") == "json"

    def test_explicit_format_overrides_no_color(self) -> None:
        assert resolve_format("rich", no_color=True) == "rich"

    def test_not_tty_returns_plain(self) -> None:
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = False
            assert resolve_format(None) == "plain"

    def test_no_color_env_returns_plain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert resolve_format(None) == "plain"

    def test_no_color_flag_returns_plain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert resolve_format(None, no_color=True) == "plain"

    def test_tty_no_flags_returns_rich(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert resolve_format(None) == "rich"


class TestOutputOptions:
    def test_defaults(self) -> None:
        opts = OutputOptions()
        assert opts.output_format == "text"
        assert opts.strip_references is False
        assert opts.json_mode is False
        assert opts.include_schema is False

    def test_custom_values(self) -> None:
        opts = OutputOptions(
            output_format="json", strip_references=True, json_mode=True, include_schema=True
        )
        assert opts.output_format == "json"
        assert opts.strip_references is True
        assert opts.json_mode is True
        assert opts.include_schema is True

    def test_frozen(self) -> None:
        opts = OutputOptions()
        with pytest.raises(AttributeError):
            opts.output_format = "changed"  # type: ignore[misc]


class TestRenderContext:
    def test_creation(self) -> None:
        formatter = PlainTextFormatter()
        opts = OutputOptions()
        ctx = RenderContext(formatter=formatter, options=opts)
        assert ctx.formatter is formatter
        assert ctx.options is opts

    def test_frozen(self) -> None:
        ctx = RenderContext(formatter=PlainTextFormatter(), options=OutputOptions())
        with pytest.raises(AttributeError):
            ctx.formatter = MarkdownFormatter()  # type: ignore[misc]


class TestFormatCompleteBase:
    def test_base_format_complete_no_refs(self) -> None:
        formatter = MarkdownFormatter()
        answer = Answer(text="Answer", references=[])
        result = formatter.format_complete(answer)
        assert "Answer" in result

    def test_base_format_complete_empty_formatted_refs(self) -> None:
        formatter = JSONFormatter()
        answer = Answer(text="Answer", references=[])
        result = formatter.format_complete(answer)
        parsed = json.loads(result)
        assert parsed["result"]["references"] == []
