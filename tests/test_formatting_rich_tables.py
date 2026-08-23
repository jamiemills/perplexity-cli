"""Behavioural tests for RichFormatter rendering structure and styling."""

from __future__ import annotations

import re
from io import StringIO

import pytest
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from perplexity_cli.api.models import Answer, WebResult
from perplexity_cli.formatting.base import Formatter
from perplexity_cli.formatting.rich import RichFormatter


def _t010_ref(name: str = "Example", url: str = "https://example.test/a") -> WebResult:
    return WebResult(name=name, url=url, snippet="snippet")


def _t010_plain(ansi_output: str) -> str:
    return Text.from_ansi(ansi_output).plain


def _t010_lines(ansi_output: str) -> list[str]:
    return [line for line in _t010_plain(ansi_output).splitlines() if line.strip()]


def _t010_canonical_console(buffer: StringIO) -> Console:
    """Console configured exactly as the production rendering consoles."""
    return Console(file=buffer, force_terminal=True, legacy_windows=False)


def _t010_canonical_references(references: list[WebResult]) -> str:
    """Byte-exact reference table per the documented presentation contract."""
    buffer = StringIO()
    console = _t010_canonical_console(buffer)
    table = Table(
        title="References",
        show_header=True,
        header_style="bold cyan",
        padding=(0, 1),
    )
    table.add_column("#", style="cyan", width=3, no_wrap=True)
    table.add_column("Source", style="white", no_wrap=False, max_width=40)
    table.add_column("URL", style="bright_blue", no_wrap=False, max_width=120)
    for index, ref in enumerate(references, 1):
        table.add_row(str(index), ref.name, ref.url)
    console.print(table)
    return buffer.getvalue().rstrip()


def _t010_canonical_code_block(code: str, language: str) -> str:
    """Byte-exact highlighted code block per the documented contract."""
    buffer = StringIO()
    console = Console(file=buffer, legacy_windows=False)
    console.print(Syntax(code, language, theme="monokai", line_numbers=False))
    return buffer.getvalue().rstrip()


_T010_HEADER_RE = re.compile(r"^(#{1,6})\s+(\S.*)$")


def _t010_header_style(level: int) -> str:
    """Documented heading styles by markdown level."""
    if level == 1:
        return "bold bright_cyan"
    if level == 2:
        return "bold cyan"
    return "bold white"


def _t010_print_markdown_lines(console: Console, text: str) -> None:
    """Replay the documented left-aligned markdown line rendering."""
    for line in text.split("\n"):
        header_match = _T010_HEADER_RE.match(line)
        if header_match:
            level = len(header_match.group(1))
            console.print(Text(header_match.group(2), style=_t010_header_style(level)))
        else:
            console.print(line)


def _t010_references_rows(console: Console, references: list[WebResult]) -> None:
    """Print the shared references table shape used by complete rendering."""
    table = Table(show_header=True, header_style="bold cyan", padding=(0, 1))
    table.add_column("#", style="cyan", width=3, no_wrap=True)
    table.add_column("Source", style="white", no_wrap=False, max_width=40)
    table.add_column("URL", style="bright_blue", no_wrap=False, max_width=120)
    for index, ref in enumerate(references, 1):
        table.add_row(str(index), ref.name, ref.url)
    console.print(table)


def _t010_canonical_render(answer_text: str, references: list[WebResult] | None) -> str:
    """Byte-exact direct-render transcript per the documented contract."""
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=True, legacy_windows=False, width=200)
    _t010_print_markdown_lines(console, Formatter.unwrap_paragraph_lines(answer_text))
    if references:
        console.print()
        console.print("─" * 50, style="dim")
        console.print()
        console.print(Text("References", style="bold cyan"))
        console.print()
        _t010_references_rows(console, references)
    return buffer.getvalue()


class TestRichFormatAnswer:
    """Answer-body presentation through the Rich pipeline."""

    def test_trailing_blank_lines_are_removed(self):
        """Trailing whitespace is trimmed from the rendered answer."""
        assert RichFormatter().format_answer("Body\n\n") == "Body"

    def test_citations_kept_by_default(self):
        """Citation markers survive unless stripping is requested."""
        assert "[1]" in RichFormatter().format_answer("Facts[1] here")

    def test_strip_flag_removes_citations(self):
        """strip_references removes citation markers."""
        result = RichFormatter().format_answer("Facts[1] here", strip_references=True)
        assert "[1]" not in result

    def test_multiline_fenced_block_is_highlighted_without_fences(self):
        """Multi-line code blocks are syntax-highlighted, replacing the fences."""
        result = RichFormatter().format_answer("```python\nalpha = 1\nbeta = 2\n```")
        assert "```" not in result
        assert "alpha = 1" in _t010_plain(result)

    def test_bare_fence_block_renders_as_plain_text_without_fences(self):
        """A fence without a language identifier still loses its fences."""
        result = RichFormatter().format_answer("Intro\n\n```\nplain stuff\n```\n")
        assert "```" not in result
        assert "plain stuff" in result

    def test_leading_indent_of_code_survives_rendering(self):
        """Code indentation is preserved verbatim inside the block."""
        result = RichFormatter().format_answer("```\n    indented = True\n```")
        assert "    indented = True" in _t010_plain(result)

    def test_line_numbers_are_not_added_to_code(self):
        """Rendered code carries no gutter numbering."""
        result = RichFormatter().format_answer("```python\nalpha = 1\nbeta = 2\n```")
        gutter_pattern = re.compile(r"(?m)^\s*\d+ \S")
        assert not gutter_pattern.search(_t010_plain(result))

    def test_python_block_matches_canonical_syntax_render(self):
        """The embedded highlight matches the documented Syntax configuration."""
        result = RichFormatter().format_answer("A\n\n```python\nx = 1\n```\n\nB")
        canonical = _t010_canonical_code_block("x = 1", "python")
        assert canonical in result
        positions = [result.index(part) for part in ("A", canonical, "B")]
        assert positions == sorted(positions)

    def test_bare_fence_matches_canonical_text_lexer_render(self):
        """A fence with no language highlights through the documented default lexer."""
        result = RichFormatter().format_answer("```\nplain stuff\n```")
        assert result == _t010_canonical_code_block("plain stuff", "text")

    def test_wide_index_labels_match_canonical_table_render(self):
        """Four-digit row labels keep the documented number-column geometry."""
        refs = [_t010_ref(f"S{n}", f"https://example.test/{n}") for n in range(1, 1002)]
        assert RichFormatter().format_references(refs) == _t010_canonical_references(refs)

    def test_wide_index_labels_match_canonical_direct_render(
        self, capsys: pytest.CaptureFixture[str]
    ):
        """Four-digit labels keep their geometry during direct rendering too."""
        refs = [_t010_ref(f"S{n}", f"https://example.test/{n}") for n in range(1, 1002)]
        RichFormatter().render_complete(Answer(text="Body", references=refs))
        assert capsys.readouterr().out == _t010_canonical_render("Body", refs)

    def test_prose_around_code_blocks_has_no_separator_artifacts(self):
        """Segments are joined directly with no synthetic separators."""
        result = RichFormatter().format_answer("before\n```py\nx = 1\n```\nafter")
        assert "XXXX" not in result
        positions = [_t010_plain(result).index(part) for part in ("before", "after")]
        assert positions == sorted(positions)


class TestRichReferencesTable:
    """References table structure, ordering, and semantic styling."""

    def test_empty_references_render_nothing(self):
        """No references produce an empty string."""
        assert RichFormatter().format_references([]) == ""

    def test_table_structure_and_semantic_styling(self):
        """Title, headers, numbered rows, and per-column colours are all present."""
        refs = [_t010_ref()]
        raw = RichFormatter().format_references(refs)
        plain_lines = _t010_lines(raw)

        assert any(line.strip() == "References" for line in plain_lines[:2])
        joined = "\n".join(plain_lines)
        for header in ("#", "Source", "URL"):
            assert header in joined
        assert any(line.startswith("│ 1") for line in plain_lines)
        assert any("Example" in line for line in plain_lines)
        assert any("https://example.test/a" in line for line in plain_lines)

        assert "\x1b[1;36m" in raw
        assert "\x1b[36m" in raw
        assert "\x1b[37m" in raw
        assert "\x1b[94m" in raw
        assert "None" not in joined

    def test_single_reference_matches_canonical_table_render(self):
        """The rendered table equals the documented canonical byte stream."""
        refs = [_t010_ref()]
        assert RichFormatter().format_references(refs) == _t010_canonical_references(refs)

    def test_rows_are_numbered_in_reference_order(self):
        """Each row carries its one-based position label."""
        refs = [
            _t010_ref("First", "https://first.test"),
            _t010_ref("Second", "https://second.test"),
        ]
        assert RichFormatter().format_references(refs) == _t010_canonical_references(refs)

    def test_two_digit_row_labels_match_canonical_render(self):
        """Double-digit numbering keeps the documented number-column geometry."""
        refs = [_t010_ref(f"Source {n}", f"https://example.test/{n}") for n in range(1, 13)]
        assert RichFormatter().format_references(refs) == _t010_canonical_references(refs)

    def test_wrapped_source_name_keeps_tail_words(self):
        """Folded source names retain their trailing words instead of cropping."""
        long_name = "alpha beta gamma delta epsilon zeta eta theta"
        refs = [_t010_ref(long_name, "https://a.b")]
        raw = RichFormatter().format_references(refs)
        assert "theta" in _t010_plain(raw)

    def test_long_source_word_matches_canonical_render(self):
        """An over-wide source word folds exactly as the canonical column allows."""
        refs = [WebResult(name="x" * 80, url="https://a.b", snippet=None)]
        assert RichFormatter().format_references(refs) == _t010_canonical_references(refs)

    def test_over_long_url_row_matches_canonical_render(self, monkeypatch: pytest.MonkeyPatch):
        """An over-wide URL folds exactly as the canonical column allows."""
        # A wide console budget makes the documented max_width=120 URL cap bind,
        # so any relaxation of the cap changes the rendered bytes.
        monkeypatch.setenv("COLUMNS", "300")
        refs = [WebResult(name="Src", url="u" * 130, snippet=None)]
        assert RichFormatter().format_references(refs) == _t010_canonical_references(refs)

    def test_output_carries_terminal_styling(self):
        """Rendered tables include ANSI escape sequences for terminals."""
        raw = RichFormatter().format_references([_t010_ref()])
        assert "\x1b[" in raw


class TestRichFormatComplete:
    """Complete rendering combines answer section and references table."""

    def _canonical_complete(self, answer: Answer, strip_references: bool) -> str:
        buffer = StringIO()
        console = _t010_canonical_console(buffer)
        answer_text = answer.text
        if strip_references:
            answer_text = Formatter.strip_citations(answer_text)
        console.print(answer_text)
        if answer.references and not strip_references:
            console.print()
            console.print("─" * 50, style="dim")
            console.print()
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("#", style="cyan", width=3)
            table.add_column("Source", style="white")
            table.add_column("URL", style="bright_blue")
            for index, ref in enumerate(answer.references, 1):
                table.add_row(str(index), ref.name, ref.url)
            console.print(table)
        return buffer.getvalue().rstrip()

    def test_default_includes_reference_section(self):
        """Without stripping, the separator, rule, and table are emitted."""
        answer = Answer(text="Body", references=[_t010_ref()])
        assert RichFormatter().format_complete(answer) == self._canonical_complete(answer, False)

    def test_strip_flag_removes_section_and_citations(self):
        """Stripping yields only the answer body without markers."""
        answer = Answer(text="Body[1]", references=[_t010_ref()])
        assert RichFormatter().format_complete(
            answer, strip_references=True
        ) == self._canonical_complete(answer, True)

    def test_no_references_yields_answer_only(self):
        """An empty reference list contributes nothing but the answer."""
        answer = Answer(text="Body", references=[])
        assert RichFormatter().format_complete(answer) == self._canonical_complete(answer, False)

    def test_wide_source_word_matches_canonical_render(self):
        """Column folding inside complete output follows the documented widths."""
        answer = Answer(text="Body", references=[WebResult(name="x" * 80, url="https://a.b")])
        assert RichFormatter().format_complete(answer) == self._canonical_complete(answer, False)

    def test_two_digit_row_labels_match_canonical_render(self):
        """Double-digit numbering keeps the documented number-column geometry."""
        refs = [_t010_ref(f"Source {n}", f"https://example.test/{n}") for n in range(1, 13)]
        answer = Answer(text="Body", references=refs)
        assert RichFormatter().format_complete(answer) == self._canonical_complete(answer, False)

    def test_leading_indent_body_matches_canonical_render(self):
        """The answer section keeps its leading indentation through completion."""
        answer = Answer(text="  Body", references=[_t010_ref()])
        assert RichFormatter().format_complete(answer) == self._canonical_complete(answer, False)

    def test_separator_line_is_dimmed_rule(self):
        """The reference separator is a dimmed fifty-column rule."""
        answer = Answer(text="Body", references=[_t010_ref()])
        raw = RichFormatter().format_complete(answer)

        assert ("\x1b[2m" + "─" * 50) in raw
        assert raw.count("─" * 50) >= 1
        assert "─" * 51 not in raw
        assert "None" not in _t010_plain(raw).splitlines()[0]


class TestRichRenderComplete:
    """Direct console rendering semantics."""

    def test_renders_answer_then_separator_heading_and_table(
        self, capsys: pytest.CaptureFixture[str]
    ):
        """Direct rendering emits answer, dimmed rule, styled heading, and table."""
        formatter = RichFormatter()
        answer = Answer(text="Body", references=[_t010_ref()])
        formatter.render_complete(answer)
        captured = capsys.readouterr().out

        assert captured == _t010_canonical_render("Body", answer.references)

    def test_strip_flag_skips_reference_section(self, capsys: pytest.CaptureFixture[str]):
        """Stripping suppresses the whole reference block when rendering."""
        formatter = RichFormatter()
        answer = Answer(text="Body[1]", references=[_t010_ref()])
        formatter.render_complete(answer, strip_references=True)
        captured = capsys.readouterr().out

        assert captured == _t010_canonical_render(Formatter.strip_citations(answer.text), None)

    def test_heading_levels_keep_distinct_styles(self, capsys: pytest.CaptureFixture[str]):
        """Level-one and level-two headings use their documented styles."""
        formatter = RichFormatter()
        formatter.render_complete(Answer(text="# Top\n## Sub", references=[]))

        assert capsys.readouterr().out == _t010_canonical_render("# Top\n## Sub", None)

    def test_long_prose_wraps_within_documented_width_budget(
        self, capsys: pytest.CaptureFixture[str]
    ):
        """Rendered prose wraps at the 200-column console budget."""
        formatter = RichFormatter()
        formatter.render_complete(Answer(text="y" * 250, references=[]))

        assert capsys.readouterr().out == _t010_canonical_render("y" * 250, None)

    def test_wide_source_word_matches_canonical_render(self, capsys: pytest.CaptureFixture[str]):
        """Source folding during direct rendering follows the documented width."""
        refs = [WebResult(name="x" * 80, url="https://a.b", snippet=None)]
        RichFormatter().render_complete(Answer(text="Body", references=refs))

        assert capsys.readouterr().out == _t010_canonical_render("Body", refs)

    def test_over_long_url_matches_canonical_render(self, capsys: pytest.CaptureFixture[str]):
        """URL folding during direct rendering follows the documented width."""
        refs = [WebResult(name="Src", url="u" * 121, snippet=None)]
        RichFormatter().render_complete(Answer(text="Body", references=refs))

        assert capsys.readouterr().out == _t010_canonical_render("Body", refs)

    def test_two_digit_row_labels_match_canonical_render(self, capsys: pytest.CaptureFixture[str]):
        """Double-digit numbering keeps the documented number-column geometry."""
        refs = [_t010_ref(f"Source {n}", f"https://example.test/{n}") for n in range(1, 13)]
        RichFormatter().render_complete(Answer(text="Body", references=refs))

        assert capsys.readouterr().out == _t010_canonical_render("Body", refs)

    def test_console_reports_non_legacy_mode_and_fixed_width(self):
        """The instance console pins the documented width and modern mode."""
        console = RichFormatter().console
        assert console.width == 200
        assert console.options.legacy_windows is False

    def test_console_forces_terminal_ansi_output(self):
        """The formatter's direct console always emits terminal styling."""
        assert RichFormatter().console.is_terminal is True


class TestRichFallbackPaths:
    """Failure handling of the syntax renderer preserves content."""

    def test_renderer_failure_restores_fences(self, monkeypatch: pytest.MonkeyPatch):
        """If highlighting fails, the fenced block is returned intact."""
        import perplexity_cli.formatting.rich as rich_module

        def broken_syntax(*args: object, **kwargs: object) -> object:
            raise ValueError("unusable lexer or theme")

        monkeypatch.setattr(rich_module, "Syntax", broken_syntax)
        result = RichFormatter().format_answer("```python\nx = 1\n```")
        assert "```python" in result
        assert "x = 1" in result
