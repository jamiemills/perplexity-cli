"""Behavioural tests for perplexity_cli.formatting.base."""

from __future__ import annotations

import inspect
import sys

import pytest

from perplexity_cli.api.models import Answer, WebResult
from perplexity_cli.formatting.base import Formatter


class _T010RecordingFormatter(Formatter):
    """Minimal concrete formatter exposing the base-class implementations."""

    def __init__(self) -> None:
        self.received_strip_references: bool | None = None

    def format_answer(self, text: str, strip_references: bool = False) -> str:
        self.received_strip_references = strip_references
        if strip_references:
            text = text.replace("[1]", "")
        return f"A:{text}"

    def format_references(self, references: list[WebResult]) -> str:
        return "R:" + ",".join(ref.url for ref in references)


class _T010TtyStdout:
    """Stdout stand-in reporting itself as a terminal."""

    def isatty(self) -> bool:
        return True


class _T010PipeStdout:
    """Stdout stand-in reporting itself as a non-terminal stream."""

    def isatty(self) -> bool:
        return False


def _web_result(url: str = "https://example.test/source") -> WebResult:
    return WebResult(name="Example Source", url=url, snippet="snippet")


# ---------------------------------------------------------------------------
# Paragraph unwrapping (public boundary for the private collectors)
# ---------------------------------------------------------------------------


def test_unwrap_blank_only_text_keeps_separator_line():
    """A lone blank line round-trips without crashing the line dispatcher."""
    assert Formatter.unwrap_paragraph_lines("\n") == "\n"


def test_unwrap_repeated_prose_line_is_not_duplicated():
    """Prose unwrapping starts at the given offset, not at a fixed index."""
    assert Formatter.unwrap_paragraph_lines("only prose") == "only prose"


def test_unwrap_preserves_verbatim_block_after_intro():
    """A fenced block following intro text survives byte-for-byte."""
    text = "Intro\n```py\nx = 1\n```"
    assert Formatter.unwrap_paragraph_lines(text) == text


def test_unwrap_closed_indented_fence_stops_collection():
    """An indented closing fence terminates the block; later prose is joined."""
    result = Formatter.unwrap_paragraph_lines("```t\nx\n  ```\nfirst\nsecond")
    lines = result.splitlines()
    assert lines[:3] == ["```t", "x", "  ```"]
    assert lines[-1] == "first second"


def test_unwrap_prose_stops_before_indented_list_item():
    """An indented list item is a boundary; prose is not swallowed into it."""
    result = Formatter.unwrap_paragraph_lines("para\n  - item")
    assert result.splitlines() == ["para", "  - item"]


def test_unwrap_list_item_does_not_absorb_unindented_lines():
    """Only indented lines continue a structural item; plain lines stay separate."""
    result = Formatter.unwrap_paragraph_lines("- item\nmore words")
    assert result.splitlines() == ["- item", "more words"]


def test_unwrap_indented_marker_line_is_structural_not_prose():
    """An indented list marker routes to item collection; following prose stays separate."""
    result = Formatter.unwrap_paragraph_lines("  - item\nplain follows")
    assert result.splitlines() == ["  - item", "plain follows"]


def test_unwrap_indented_fence_after_item_starts_block():
    """An indented fence ends item collection and opens a verbatim block."""
    result = Formatter.unwrap_paragraph_lines("- item\n  ```")
    assert result.splitlines()[0] == "- item"


def test_unwrap_header_line_is_structural_even_before_continuation():
    """Headers stay on their own line instead of joining the next line."""
    result = Formatter.unwrap_paragraph_lines("# Title\ncontinuation")
    assert result.splitlines() == ["# Title", "continuation"]


def test_unwrap_horizontal_rule_keeps_own_line():
    """Horizontal rules remain standalone structural lines."""
    result = Formatter.unwrap_paragraph_lines("above\n---\nbelow")
    assert "---" in result.splitlines()
    assert result.splitlines() == ["above", "---", "below"]


def test_unwrap_indented_opening_fence_is_verbatim_block():
    """An indented opening fence still routes to the code-block collector."""
    result = Formatter.unwrap_paragraph_lines("  ```py\n  x = 1\n  ```")
    assert result.splitlines() == ["  ```py", "  x = 1", "  ```"]


def test_unwrap_item_joins_indented_continuation():
    """Indented continuations join their structural item."""
    result = Formatter.unwrap_paragraph_lines("- item\n    continued here")
    assert result.splitlines() == ["- item continued here"]


def test_unwrap_unclosed_final_code_block_is_preserved():
    """An unterminated trailing code block is preserved without crashing."""
    result = Formatter.unwrap_paragraph_lines("```python\ncode = 1")
    assert result.splitlines() == ["```python", "code = 1"]


# ---------------------------------------------------------------------------
# Base Formatter.format_complete
# ---------------------------------------------------------------------------


def test_format_complete_default_includes_reference_section():
    """Without the strip flag the base implementation appends references."""
    formatter = _T010RecordingFormatter()
    answer = Answer(text="body", references=[_web_result()])
    assert formatter.format_complete(answer) == "A:body\nR:https://example.test/source"


def test_format_complete_strip_flag_excludes_and_propagates_true():
    """With strip_references=True references are dropped and the flag is forwarded."""
    formatter = _T010RecordingFormatter()
    answer = Answer(text="body [1]", references=[_web_result()])
    assert formatter.format_complete(answer, strip_references=True) == "A:body "
    assert formatter.received_strip_references is True


def test_format_complete_without_references_has_single_part():
    """No references means the output is exactly the formatted answer."""
    formatter = _T010RecordingFormatter()
    answer = Answer(text="body", references=[])
    assert formatter.format_complete(answer) == "A:body"


def test_format_complete_empty_reference_rendering_is_dropped():
    """An empty rendered reference section contributes nothing to the output."""
    formatter = _T010RecordingFormatter()
    answer = Answer(text="body", references=[WebResult(name="n", url="", snippet=None)])
    assert formatter.format_complete(answer) == "A:body\nR:"


def test_format_complete_calls_answer_formatter_before_references():
    """The complete boundary preserves answer-first ordering and exact output."""
    formatter = _T010RecordingFormatter()
    answer = Answer(text="body", references=[_web_result("https://example.test/ref")])

    assert formatter.format_complete(answer) == "A:body\nR:https://example.test/ref"


# ---------------------------------------------------------------------------
# Base Formatter.render_complete
# ---------------------------------------------------------------------------


def test_render_complete_default_is_unsupported():
    """The base render_complete refuses direct rendering with its contract message."""
    formatter = _T010RecordingFormatter()
    with pytest.raises(NotImplementedError) as exc_info:
        formatter.render_complete(Answer(text="body", references=[]))
    assert str(exc_info.value) == "This formatter does not support direct rendering"


def test_render_complete_signature_defaults_to_not_stripping():
    """render_complete keeps references unless the caller asks otherwise."""
    signature = inspect.signature(Formatter.render_complete)
    assert signature.parameters["strip_references"].default is False


# ---------------------------------------------------------------------------
# Formatter.should_use_colors
# ---------------------------------------------------------------------------


def test_should_use_colors_honours_no_color_env_over_tty(monkeypatch: pytest.MonkeyPatch):
    """NO_COLOR suppresses colours even when stdout is a terminal."""
    monkeypatch.setattr(sys, "stdout", _T010TtyStdout())
    monkeypatch.setenv("NO_COLOR", "1")
    assert _T010RecordingFormatter().should_use_colors() is False


def test_should_use_colors_ignores_lowercase_no_color_env(monkeypatch: pytest.MonkeyPatch):
    """Only the canonical uppercase NO_COLOR variable disables colours."""
    monkeypatch.setattr(sys, "stdout", _T010TtyStdout())
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("no_color", "1")
    assert _T010RecordingFormatter().should_use_colors() is True


def test_should_use_colors_on_tty_without_no_color(monkeypatch: pytest.MonkeyPatch):
    """A terminal without NO_COLOR gets colours."""
    monkeypatch.setattr(sys, "stdout", _T010TtyStdout())
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert _T010RecordingFormatter().should_use_colors() is True


def test_should_use_colors_is_false_for_non_tty_without_no_color(
    monkeypatch: pytest.MonkeyPatch,
):
    """Non-terminal output remains uncoloured when NO_COLOR is absent."""
    monkeypatch.setattr(sys, "stdout", _T010PipeStdout())
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert _T010RecordingFormatter().should_use_colors() is False
