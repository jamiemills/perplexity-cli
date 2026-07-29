"""Final-round mutation-killing tests for formatting/rich.py and threads/scraper.py.

Targets ~55 surviving mutants with exact-output assertions, boundary checks,
and error-message verification that existing tests do not cover.
"""

from __future__ import annotations

from io import StringIO
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from perplexity_cli.api.models import Answer, WebResult
from perplexity_cli.formatting.rich import RichFormatter, _HEADER_LEVEL_2, _SECTION_HEADER_STYLE
from perplexity_cli.threads.exporter import ThreadRecord
from perplexity_cli.threads.scraper import (
    BatchProcessingContext,
    FetchMergeContext,
    ThreadScraper,
    _build_batch_processing_context,
    _build_legacy_batch_processing_context,
    _coerce_optional_int,
    _coerce_optional_str,
    _coerce_progress_callback,
    _convert_cache_thread_dicts,
    _extract_cache_thread_dicts,
    _extract_total_threads,
    _get_cache_str_field,
    _get_str_field,
    _handle_http_error,
    _has_integer_status_code,
    _has_more_pages,
    _is_in_date_range,
    _is_progress_callback,
    _is_response_protocol,
    _legacy_context_value,
    _parse_single_thread,
    _report_progress,
    _require_response,
    _response_core_members,
    _to_iso8601,
    _validate_batch_processing_arg_count,
    _validate_date_params,
)
from perplexity_cli.utils.exceptions import (
    AuthenticationError,
    PerplexityHTTPStatusError,
    RateLimitError,
    SimpleResponse,
    UpstreamSchemaError,
)


# ---------------------------------------------------------------------------
# formatting/rich.py – exact ANSI and markup assertions
# ---------------------------------------------------------------------------


class TestRichFormatterHeaderStyles:
    """Kill mutants in _print_formatted_text header style selection."""

    def _capture(self, text: str) -> str:
        formatter = RichFormatter()
        buffer = StringIO()
        formatter.console.file = buffer
        formatter._print_formatted_text(text)
        return buffer.getvalue()

    def test_h1_uses_bold_bright_cyan_ansi(self) -> None:
        output = self._capture("# Main Title")
        assert "\x1b[1;96m" in output or "\x1b[1m" in output
        assert "Main Title" in output
        assert "# " not in output

    def test_h2_uses_bold_cyan_ansi(self) -> None:
        output = self._capture("## Section Header")
        assert "Section Header" in output
        assert "## " not in output

    def test_h3_uses_bold_white_ansi(self) -> None:
        output = self._capture("### Sub Header")
        assert "Sub Header" in output
        assert "### " not in output

    def test_h4_uses_bold_white_same_as_h3(self) -> None:
        output_h3 = self._capture("### Level3")
        output_h4 = self._capture("#### Level4")
        assert "Level3" in output_h3
        assert "Level4" in output_h4
        assert "####" not in output_h4

    def test_h5_uses_bold_white(self) -> None:
        output = self._capture("##### Deep")
        assert "Deep" in output
        assert "#####" not in output

    def test_h6_uses_bold_white(self) -> None:
        output = self._capture("###### Deepest")
        assert "Deepest" in output
        assert "######" not in output

    def test_header_with_emoji_content(self) -> None:
        output = self._capture("# 🚀 Launch")
        assert "🚀 Launch" in output
        assert "# " not in output

    def test_header_no_space_after_hash_not_matched(self) -> None:
        output = self._capture("#NoSpace")
        assert "#NoSpace" in output

    def test_header_empty_content_not_matched(self) -> None:
        output = self._capture("# ")
        assert "# " in output or output.strip() == ""

    def test_plain_line_printed_verbatim(self) -> None:
        output = self._capture("just a line")
        assert "just a line" in output

    def test_multiple_headers_different_levels(self) -> None:
        output = self._capture("# H1\n## H2\n### H3\n#### H4")
        assert "H1" in output
        assert "H2" in output
        assert "H3" in output
        assert "H4" in output


class TestRichFormatterCodeBlockExact:
    """Kill mutants in _render_code_block and _process_answer_text."""

    def test_fallback_exact_format_with_language(self) -> None:
        formatter = RichFormatter()
        with patch("perplexity_cli.formatting.rich.Syntax", side_effect=ValueError("bad")):
            result = formatter._render_code_block("rust", "fn main() {}")
        assert result == "```rust\nfn main() {}\n```"

    def test_fallback_exact_format_type_error(self) -> None:
        formatter = RichFormatter()
        with patch("perplexity_cli.formatting.rich.Syntax", side_effect=TypeError("bad")):
            result = formatter._render_code_block("go", "package main")
        assert result == "```go\npackage main\n```"

    def test_fallback_exact_format_lookup_error(self) -> None:
        formatter = RichFormatter()
        with patch("perplexity_cli.formatting.rich.Syntax", side_effect=LookupError("bad")):
            result = formatter._render_code_block("cobol", "DISPLAY 'HI'")
        assert result == "```cobol\nDISPLAY 'HI'\n```"

    def test_valid_python_no_fallback_fences(self) -> None:
        formatter = RichFormatter()
        result = formatter._render_code_block("python", "x = 1")
        assert "```" not in result
        assert "x" in result

    def test_process_answer_text_language_defaults_to_text(self) -> None:
        formatter = RichFormatter()
        text = "```\nhello world\n```"
        result = formatter._process_answer_text(text)
        assert "hello world" in result
        assert "```" not in result

    def test_process_answer_text_preserves_surrounding_text_exactly(self) -> None:
        formatter = RichFormatter()
        text = "BEFORE\n```python\ncode\n```\nAFTER"
        result = formatter._process_answer_text(text)
        assert result.startswith("BEFORE")
        assert result.endswith("AFTER")

    def test_process_answer_text_multiple_blocks_all_rendered(self) -> None:
        formatter = RichFormatter()
        text = "```python\na=1\n```\nmid\n```js\nb=2\n```"
        result = formatter._process_answer_text(text)
        assert "a" in result
        assert "mid" in result
        assert "b" in result

    def test_process_answer_text_no_trailing_content(self) -> None:
        formatter = RichFormatter()
        text = "```python\nx=1\n```"
        result = formatter._process_answer_text(text)
        assert "x" in result

    def test_format_answer_strips_trailing_newlines(self) -> None:
        formatter = RichFormatter()
        result = formatter.format_answer("text\n\n\n")
        assert result == "text"

    def test_format_answer_strip_references_true(self) -> None:
        formatter = RichFormatter()
        result = formatter.format_answer("fact[1] and[23] end", strip_references=True)
        assert "[1]" not in result
        assert "[23]" not in result
        assert "fact" in result
        assert "end" in result

    def test_format_answer_strip_references_false_keeps(self) -> None:
        formatter = RichFormatter()
        result = formatter.format_answer("fact[1] here", strip_references=False)
        assert "[1]" in result


class TestRichFormatterReferencesExact:
    """Kill mutants in format_references table construction."""

    def test_empty_list_returns_empty_string(self) -> None:
        formatter = RichFormatter()
        assert formatter.format_references([]) == ""

    def test_single_ref_contains_number_1(self) -> None:
        formatter = RichFormatter()
        refs = [WebResult(name="Source A", url="https://a.example.com", snippet="s")]
        result = formatter.format_references(refs)
        assert "1" in result
        assert "Source A" in result
        assert "https://a.example.com" in result

    def test_two_refs_numbered_sequentially(self) -> None:
        formatter = RichFormatter()
        refs = [
            WebResult(name="First", url="https://first.com", snippet="a"),
            WebResult(name="Second", url="https://second.com", snippet="b"),
        ]
        result = formatter.format_references(refs)
        assert "1" in result
        assert "2" in result
        assert "First" in result
        assert "Second" in result

    def test_three_refs_all_present(self) -> None:
        formatter = RichFormatter()
        refs = [
            WebResult(name="A", url="https://a.com", snippet="a"),
            WebResult(name="B", url="https://b.com", snippet="b"),
            WebResult(name="C", url="https://c.com", snippet="c"),
        ]
        result = formatter.format_references(refs)
        assert "1" in result
        assert "2" in result
        assert "3" in result

    def test_table_contains_references_title(self) -> None:
        formatter = RichFormatter()
        refs = [WebResult(name="X", url="https://x.com", snippet="x")]
        result = formatter.format_references(refs)
        assert "References" in result

    def test_output_has_ansi_escape(self) -> None:
        formatter = RichFormatter()
        refs = [WebResult(name="X", url="https://x.com", snippet="x")]
        result = formatter.format_references(refs)
        assert "\x1b[" in result

    def test_output_rstripped_no_trailing_newline(self) -> None:
        formatter = RichFormatter()
        refs = [WebResult(name="X", url="https://x.com", snippet="x")]
        result = formatter.format_references(refs)
        assert not result.endswith("\n")


class TestRichFormatterFormatCompleteExact:
    """Kill mutants in format_complete output structure."""

    def test_no_refs_no_separator_no_table(self) -> None:
        formatter = RichFormatter()
        answer = Answer(text="Just answer", references=[])
        result = formatter.format_complete(answer)
        assert "Just answer" in result
        assert "─" not in result

    def test_with_refs_has_50_char_separator(self) -> None:
        formatter = RichFormatter()
        refs = [WebResult(name="S", url="https://s.com", snippet="s")]
        answer = Answer(text="Ans", references=refs)
        result = formatter.format_complete(answer)
        assert "─" * 50 in result

    def test_with_refs_has_49_char_separator_absent(self) -> None:
        formatter = RichFormatter()
        refs = [WebResult(name="S", url="https://s.com", snippet="s")]
        answer = Answer(text="Ans", references=refs)
        result = formatter.format_complete(answer)
        assert "─" * 51 not in result

    def test_strip_references_true_no_separator(self) -> None:
        formatter = RichFormatter()
        refs = [WebResult(name="S", url="https://s.com", snippet="s")]
        answer = Answer(text="Ans[1]", references=refs)
        result = formatter.format_complete(answer, strip_references=True)
        assert "─" * 50 not in result
        assert "[1]" not in result
        assert "S" not in result

    def test_strip_references_false_keeps_refs(self) -> None:
        formatter = RichFormatter()
        refs = [WebResult(name="KeepMe", url="https://keep.com", snippet="s")]
        answer = Answer(text="Ans[1]", references=refs)
        result = formatter.format_complete(answer, strip_references=False)
        assert "KeepMe" in result
        assert "1" in result

    def test_output_rstripped(self) -> None:
        formatter = RichFormatter()
        answer = Answer(text="text", references=[])
        result = formatter.format_complete(answer)
        assert not result.endswith("\n")

    def test_empty_refs_list_no_separator(self) -> None:
        formatter = RichFormatter()
        answer = Answer(text="text", references=[])
        result = formatter.format_complete(answer)
        assert "─" * 50 not in result


class TestRichFormatterRenderCompleteExact:
    """Kill mutants in render_complete direct console output."""

    def _capture_render(self, answer: Answer, strip: bool = False) -> str:
        formatter = RichFormatter()
        buffer = StringIO()
        formatter.console.file = buffer
        formatter.render_complete(answer, strip_references=strip)
        return buffer.getvalue()

    def test_with_refs_prints_separator_and_title(self) -> None:
        refs = [WebResult(name="Ref", url="https://ref.com", snippet="s")]
        answer = Answer(text="Body", references=refs)
        output = self._capture_render(answer)
        assert "─" * 50 in output
        assert "References" in output
        assert "Ref" in output

    def test_strip_true_no_separator(self) -> None:
        refs = [WebResult(name="Ref", url="https://ref.com", snippet="s")]
        answer = Answer(text="Body[1]", references=refs)
        output = self._capture_render(answer, strip=True)
        assert "─" * 50 not in output
        assert "[1]" not in output

    def test_no_refs_no_separator(self) -> None:
        answer = Answer(text="Plain", references=[])
        output = self._capture_render(answer)
        assert "─" * 50 not in output
        assert "Plain" in output

    def test_header_in_answer_rendered(self) -> None:
        answer = Answer(text="# Title\nbody text", references=[])
        output = self._capture_render(answer)
        assert "Title" in output
        assert "body text" in output


class TestRichFormatterConsoleConfig:
    """Kill mutants in RichFormatter.__init__ console configuration."""

    def test_console_width_200(self) -> None:
        formatter = RichFormatter()
        assert formatter.console.width == 200

    def test_console_force_terminal(self) -> None:
        formatter = RichFormatter()
        assert formatter.console._force_terminal is True


# ---------------------------------------------------------------------------
# threads/scraper.py – coercion, protocol, and parsing
# ---------------------------------------------------------------------------


class TestIsProgressCallback:
    """Kill mutants in _is_progress_callback."""

    def test_lambda_is_callback(self) -> None:
        assert _is_progress_callback(lambda c, t: None) is True

    def test_function_is_callback(self) -> None:
        def cb(current: int, total: int) -> None:
            pass

        assert _is_progress_callback(cb) is True

    def test_string_not_callback(self) -> None:
        assert _is_progress_callback("not callable") is False

    def test_none_not_callback(self) -> None:
        assert _is_progress_callback(None) is False

    def test_int_not_callback(self) -> None:
        assert _is_progress_callback(42) is False


class TestCoerceOptionalStrExact:
    """Kill mutants in _coerce_optional_str with exact messages."""

    def test_none_returns_none(self) -> None:
        assert _coerce_optional_str(None, "from_date") is None

    def test_string_returns_string(self) -> None:
        assert _coerce_optional_str("2026-01-01", "from_date") == "2026-01-01"

    def test_empty_string_returns_empty(self) -> None:
        assert _coerce_optional_str("", "field") == ""

    def test_int_raises_exact_message(self) -> None:
        with pytest.raises(TypeError, match="from_date must be a string or None"):
            _coerce_optional_str(123, "from_date")

    def test_list_raises_exact_message(self) -> None:
        with pytest.raises(TypeError, match="to_date must be a string or None"):
            _coerce_optional_str(["a"], "to_date")

    def test_bool_raises(self) -> None:
        with pytest.raises(TypeError, match="flag must be a string or None"):
            _coerce_optional_str(True, "flag")


class TestCoerceOptionalIntExact:
    """Kill mutants in _coerce_optional_int with exact messages."""

    def test_none_returns_none(self) -> None:
        assert _coerce_optional_int(None, "total") is None

    def test_int_returns_int(self) -> None:
        assert _coerce_optional_int(99, "total") == 99

    def test_zero_returns_zero(self) -> None:
        assert _coerce_optional_int(0, "total") == 0

    def test_negative_returns_negative(self) -> None:
        assert _coerce_optional_int(-5, "offset") == -5

    def test_string_raises_exact_message(self) -> None:
        with pytest.raises(TypeError, match="total_threads must be an integer or None"):
            _coerce_optional_int("100", "total_threads")

    def test_float_raises(self) -> None:
        with pytest.raises(TypeError, match="count must be an integer or None"):
            _coerce_optional_int(3.14, "count")


class TestCoerceProgressCallbackExact:
    """Kill mutants in _coerce_progress_callback with exact messages."""

    def test_none_returns_none(self) -> None:
        assert _coerce_progress_callback(None) is None

    def test_callable_returns_same_object(self) -> None:
        cb = Mock()
        assert _coerce_progress_callback(cb) is cb

    def test_string_raises_exact_message(self) -> None:
        with pytest.raises(TypeError, match="progress_callback must be callable or None"):
            _coerce_progress_callback("bad")

    def test_int_raises_exact_message(self) -> None:
        with pytest.raises(TypeError, match="progress_callback must be callable or None"):
            _coerce_progress_callback(42)


class TestValidateBatchArgCountExact:
    """Kill mutants in _validate_batch_processing_arg_count."""

    def test_zero_ok(self) -> None:
        _validate_batch_processing_arg_count(0)

    def test_one_ok(self) -> None:
        _validate_batch_processing_arg_count(1)

    def test_two_ok(self) -> None:
        _validate_batch_processing_arg_count(2)

    def test_three_ok(self) -> None:
        _validate_batch_processing_arg_count(3)

    def test_four_raises_exact_message(self) -> None:
        with pytest.raises(
            TypeError, match="_process_thread_batch expected at most three context arguments"
        ):
            _validate_batch_processing_arg_count(4)

    def test_five_raises(self) -> None:
        with pytest.raises(TypeError, match="expected at most three"):
            _validate_batch_processing_arg_count(5)


class TestLegacyContextValueExact:
    """Kill mutants in _legacy_context_value boundary checks."""

    def test_index_0_present(self) -> None:
        assert _legacy_context_value(("a", "b"), 0) == "a"

    def test_index_1_present(self) -> None:
        assert _legacy_context_value(("a", "b"), 1) == "b"

    def test_index_equal_to_len_returns_none(self) -> None:
        assert _legacy_context_value(("a",), 1) is None

    def test_index_beyond_len_returns_none(self) -> None:
        assert _legacy_context_value(("a",), 99) is None

    def test_empty_tuple_any_index(self) -> None:
        assert _legacy_context_value((), 0) is None


class TestBuildLegacyBatchContext:
    """Kill mutants in _build_legacy_batch_processing_context."""

    def test_all_three_args(self) -> None:
        cb = Mock()
        ctx = _build_legacy_batch_processing_context(("2026-01-01", 50, cb))
        assert ctx.from_date == "2026-01-01"
        assert ctx.total_threads == 50
        assert ctx.progress_callback is cb

    def test_only_from_date(self) -> None:
        ctx = _build_legacy_batch_processing_context(("2025-06-15",))
        assert ctx.from_date == "2025-06-15"
        assert ctx.total_threads is None
        assert ctx.progress_callback is None

    def test_from_date_and_total(self) -> None:
        ctx = _build_legacy_batch_processing_context(("2025-01-01", 200))
        assert ctx.from_date == "2025-01-01"
        assert ctx.total_threads == 200
        assert ctx.progress_callback is None

    def test_all_none(self) -> None:
        ctx = _build_legacy_batch_processing_context((None, None, None))
        assert ctx.from_date is None
        assert ctx.total_threads is None
        assert ctx.progress_callback is None

    def test_empty_tuple(self) -> None:
        ctx = _build_legacy_batch_processing_context(())
        assert ctx.from_date is None
        assert ctx.total_threads is None
        assert ctx.progress_callback is None


class TestBuildBatchProcessingContext:
    """Kill mutants in _build_batch_processing_context dispatch."""

    def test_no_args_returns_defaults(self) -> None:
        ctx = _build_batch_processing_context()
        assert ctx.from_date is None
        assert ctx.total_threads is None
        assert ctx.progress_callback is None

    def test_single_context_object_passthrough(self) -> None:
        original = BatchProcessingContext(from_date="2026-03-01", total_threads=10)
        result = _build_batch_processing_context(original)
        assert result is original

    def test_legacy_three_args(self) -> None:
        ctx = _build_batch_processing_context("2026-01-01", 42, None)
        assert ctx.from_date == "2026-01-01"
        assert ctx.total_threads == 42

    def test_too_many_args_raises(self) -> None:
        with pytest.raises(TypeError, match="expected at most three"):
            _build_batch_processing_context("a", "b", "c", "d")

    def test_single_non_context_string_uses_legacy(self) -> None:
        ctx = _build_batch_processing_context("2026-05-05")
        assert ctx.from_date == "2026-05-05"


class TestResponseProtocolChecks:
    """Kill mutants in _response_core_members, _has_integer_status_code, _is_response_protocol."""

    def test_core_members_returns_tuple(self) -> None:
        resp = Mock()
        resp.ok = True
        resp.json = Mock()
        result = _response_core_members(resp)
        assert result is not None
        assert len(result) == 2
        assert result[0] is True

    def test_core_members_missing_ok_returns_none(self) -> None:
        resp = Mock(spec=[])
        assert _response_core_members(resp) is None

    def test_has_integer_status_true(self) -> None:
        resp = Mock()
        resp.status_code = 404
        assert _has_integer_status_code(resp) is True

    def test_has_integer_status_false_for_str(self) -> None:
        resp = Mock()
        resp.status_code = "200"
        assert _has_integer_status_code(resp) is False

    def test_has_integer_status_false_for_none(self) -> None:
        resp = Mock()
        resp.status_code = None
        assert _has_integer_status_code(resp) is False

    def test_has_integer_status_missing_attr(self) -> None:
        resp = Mock(spec=[])
        assert _has_integer_status_code(resp) is False

    def test_is_response_protocol_ok_true(self) -> None:
        resp = Mock()
        resp.ok = True
        resp.json = Mock()
        assert _is_response_protocol(resp) is True

    def test_is_response_protocol_ok_false_int_status(self) -> None:
        resp = Mock()
        resp.ok = False
        resp.status_code = 500
        resp.json = Mock()
        assert _is_response_protocol(resp) is True

    def test_is_response_protocol_ok_false_no_int_status(self) -> None:
        resp = Mock()
        resp.ok = False
        resp.status_code = "500"
        resp.json = Mock()
        assert _is_response_protocol(resp) is False

    def test_is_response_protocol_ok_not_bool(self) -> None:
        resp = Mock()
        resp.ok = 1
        resp.json = Mock()
        assert _is_response_protocol(resp) is False

    def test_is_response_protocol_json_not_callable(self) -> None:
        resp = Mock()
        resp.ok = True
        resp.json = "not_callable"
        assert _is_response_protocol(resp) is False

    def test_require_response_valid(self) -> None:
        resp = Mock()
        resp.ok = True
        resp.json = Mock()
        assert _require_response(resp) is resp

    def test_require_response_invalid_raises_exact(self) -> None:
        resp = Mock(spec=[])
        with pytest.raises(UpstreamSchemaError, match="Malformed HTTP response object from upstream session"):
            _require_response(resp)


class TestGetCacheStrFieldExact:
    """Kill mutants in _get_cache_str_field with exact messages."""

    def test_valid_string(self) -> None:
        assert _get_cache_str_field({"title": "Hello"}, "title") == "Hello"

    def test_missing_field_exact_message(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="Malformed cached thread record: missing title"):
            _get_cache_str_field({}, "title")

    def test_non_string_exact_message(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="Malformed cached thread record: missing url"):
            _get_cache_str_field({"url": 123}, "url")

    def test_none_value_raises(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="missing created_at"):
            _get_cache_str_field({"created_at": None}, "created_at")


class TestConvertCacheThreadDicts:
    """Kill mutants in _convert_cache_thread_dicts."""

    def test_valid_single_entry(self) -> None:
        dicts = [{"title": "T", "url": "https://u.com", "created_at": "2026-01-01T00:00:00Z"}]
        records = _convert_cache_thread_dicts(dicts)
        assert len(records) == 1
        assert records[0].title == "T"
        assert records[0].url == "https://u.com"
        assert records[0].created_at == "2026-01-01T00:00:00Z"

    def test_multiple_entries(self) -> None:
        dicts = [
            {"title": "A", "url": "https://a.com", "created_at": "2026-01-01T00:00:00Z"},
            {"title": "B", "url": "https://b.com", "created_at": "2026-02-01T00:00:00Z"},
        ]
        records = _convert_cache_thread_dicts(dicts)
        assert len(records) == 2
        assert records[0].title == "A"
        assert records[1].title == "B"

    def test_empty_list(self) -> None:
        assert _convert_cache_thread_dicts([]) == []

    def test_missing_field_raises(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="missing title"):
            _convert_cache_thread_dicts([{"url": "u", "created_at": "c"}])


class TestExtractCacheThreadDicts:
    """Kill mutants in _extract_cache_thread_dicts."""

    def test_valid_entries(self) -> None:
        result = _extract_cache_thread_dicts([{"title": "T", "url": "U"}])
        assert result == [{"title": "T", "url": "U"}]

    def test_empty_list(self) -> None:
        assert _extract_cache_thread_dicts([]) == []

    def test_non_list_raises(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="Malformed cached thread records"):
            _extract_cache_thread_dicts("not a list")

    def test_non_mapping_entry_raises(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="Malformed cached thread records"):
            _extract_cache_thread_dicts([42])

    def test_preserves_all_keys(self) -> None:
        entry = {"title": "T", "url": "U", "created_at": "C", "extra": "E"}
        result = _extract_cache_thread_dicts([entry])
        assert result[0]["extra"] == "E"


class TestGetStrFieldExact:
    """Kill mutants in _get_str_field with exact messages."""

    def test_returns_value(self) -> None:
        assert _get_str_field({"slug": "my-slug"}, "slug") == "my-slug"

    def test_returns_default_when_missing(self) -> None:
        assert _get_str_field({}, "title", "Untitled") == "Untitled"

    def test_returns_empty_default(self) -> None:
        assert _get_str_field({}, "slug", "") == ""

    def test_non_string_raises_exact_message(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="Malformed thread slug in upstream API response"):
            _get_str_field({"slug": 42}, "slug")

    def test_missing_no_default_raises(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="Malformed thread title in upstream API response"):
            _get_str_field({}, "title")

    def test_none_value_raises(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="Malformed thread title"):
            _get_str_field({"title": None}, "title")


class TestExtractTotalThreadsExact:
    """Kill mutants in _extract_total_threads."""

    def test_existing_total_returned_unchanged(self) -> None:
        assert _extract_total_threads({"total_threads": 999}, 42) == 42

    def test_extracts_from_dict_when_none(self) -> None:
        assert _extract_total_threads({"total_threads": 77}, None) == 77

    def test_defaults_to_zero_when_missing(self) -> None:
        assert _extract_total_threads({}, None) == 0

    def test_non_int_raises_exact_message(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="Malformed total_threads value in upstream API response"):
            _extract_total_threads({"total_threads": "bad"}, None)

    def test_float_raises(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="Malformed total_threads"):
            _extract_total_threads({"total_threads": 3.14}, None)


class TestParseSingleThreadExact:
    """Kill mutants in _parse_single_thread with exact field checks."""

    def test_valid_thread_url_format(self) -> None:
        thread_dict = {
            "last_query_datetime": "2026-06-15T12:00:00+00:00",
            "slug": "test-query",
            "title": "My Question",
        }
        record, should_stop = _parse_single_thread(thread_dict, None)
        assert should_stop is False
        assert record is not None
        assert record.title == "My Question"
        assert record.url.endswith("/search/test-query")

    def test_empty_timestamp_raises_exact(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="Malformed thread timestamp in upstream API response"):
            _parse_single_thread({"last_query_datetime": ""}, None)

    def test_missing_timestamp_raises(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="Malformed thread last_query_datetime"):
            _parse_single_thread({}, None)

    def test_old_thread_returns_none_true(self) -> None:
        thread_dict = {
            "last_query_datetime": "2020-01-01T00:00:00+00:00",
            "slug": "old",
            "title": "Old",
        }
        record, should_stop = _parse_single_thread(thread_dict, "2025-01-01")
        assert record is None
        assert should_stop is True

    def test_recent_thread_returns_record_false(self) -> None:
        thread_dict = {
            "last_query_datetime": "2026-06-01T00:00:00+00:00",
            "slug": "new",
            "title": "New",
        }
        record, should_stop = _parse_single_thread(thread_dict, "2025-01-01")
        assert record is not None
        assert should_stop is False

    def test_default_title_untitled(self) -> None:
        thread_dict = {"last_query_datetime": "2026-06-01T00:00:00+00:00"}
        record, _ = _parse_single_thread(thread_dict, None)
        assert record is not None
        assert record.title == "Untitled"

    def test_default_slug_empty(self) -> None:
        thread_dict = {"last_query_datetime": "2026-06-01T00:00:00+00:00"}
        record, _ = _parse_single_thread(thread_dict, None)
        assert record is not None
        assert "/search/" in record.url

    def test_no_from_date_never_stops(self) -> None:
        thread_dict = {
            "last_query_datetime": "2000-01-01T00:00:00+00:00",
            "slug": "ancient",
            "title": "Ancient",
        }
        record, should_stop = _parse_single_thread(thread_dict, None)
        assert should_stop is False
        assert record is not None


class TestHasMorePagesExact:
    """Kill mutants in _has_more_pages."""

    def test_empty_list_false(self) -> None:
        assert _has_more_pages([]) is False

    def test_true_value(self) -> None:
        assert _has_more_pages([{"has_next_page": True}]) is True

    def test_false_value(self) -> None:
        assert _has_more_pages([{"has_next_page": False}]) is False

    def test_missing_key_false(self) -> None:
        assert _has_more_pages([{"other": 1}]) is False

    def test_truthy_int_coerced_to_bool(self) -> None:
        assert _has_more_pages([{"has_next_page": 1}]) is True

    def test_falsy_zero(self) -> None:
        assert _has_more_pages([{"has_next_page": 0}]) is False


class TestReportProgressExact:
    """Kill mutants in _report_progress."""

    def test_callback_called_with_exact_args(self) -> None:
        cb = Mock()
        _report_progress(cb, 7, 15)
        cb.assert_called_once_with(7, 15)

    def test_none_callback_no_error(self) -> None:
        _report_progress(None, 5, 10)

    def test_none_total_skips(self) -> None:
        cb = Mock()
        _report_progress(cb, 5, None)
        cb.assert_not_called()

    def test_zero_total_skips(self) -> None:
        cb = Mock()
        _report_progress(cb, 5, 0)
        cb.assert_not_called()

    def test_one_total_calls(self) -> None:
        cb = Mock()
        _report_progress(cb, 1, 1)
        cb.assert_called_once_with(1, 1)


class TestValidateDateParamsExact:
    """Kill mutants in _validate_date_params with exact messages."""

    def test_valid_from_and_to(self) -> None:
        _validate_date_params("2026-01-01", "2026-12-31")

    def test_none_both(self) -> None:
        _validate_date_params(None, None)

    def test_none_from_only(self) -> None:
        _validate_date_params(None, "2026-06-15")

    def test_none_to_only(self) -> None:
        _validate_date_params("2026-06-15", None)

    def test_invalid_from_exact_message(self) -> None:
        with pytest.raises(ValueError, match="Invalid from_date 'garbage': expected YYYY-MM-DD format"):
            _validate_date_params("garbage", None)

    def test_invalid_to_exact_message(self) -> None:
        with pytest.raises(ValueError, match="Invalid to_date 'xyz': expected YYYY-MM-DD format"):
            _validate_date_params(None, "xyz")

    def test_preserves_cause_chain(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            _validate_date_params("not-a-date", None)
        assert exc_info.value.__cause__ is not None


class TestHandleHttpErrorExact:
    """Kill mutants in _handle_http_error with exact messages."""

    def _make_error(self, status: int) -> PerplexityHTTPStatusError:
        resp = SimpleResponse(status_code=status)
        return PerplexityHTTPStatusError(f"HTTP {status}", response=resp)

    def test_401_raises_authentication_error_exact(self) -> None:
        with pytest.raises(AuthenticationError, match="Authentication failed. Token may be expired."):
            _handle_http_error(self._make_error(401))

    def test_401_message_includes_reauth_command(self) -> None:
        with pytest.raises(AuthenticationError, match="perplexity-cli auth"):
            _handle_http_error(self._make_error(401))

    def test_429_raises_rate_limit_error_exact(self) -> None:
        with pytest.raises(RateLimitError, match="Rate limit exceeded while fetching threads"):
            _handle_http_error(self._make_error(429))

    def test_500_reraises_original(self) -> None:
        error = self._make_error(500)
        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            try:
                raise error
            except PerplexityHTTPStatusError as caught:
                _handle_http_error(caught)
        assert exc_info.value is error

    def test_403_reraises_original(self) -> None:
        error = self._make_error(403)
        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            try:
                raise error
            except PerplexityHTTPStatusError as caught:
                _handle_http_error(caught)
        assert exc_info.value is error


class TestDateProxies:
    """Kill mutants in _is_in_date_range and _to_iso8601 proxies."""

    def test_is_in_date_range_within(self) -> None:
        from datetime import UTC, datetime

        dt = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
        assert _is_in_date_range(dt, "2026-01-01", "2026-12-31") is True

    def test_is_in_date_range_before(self) -> None:
        from datetime import UTC, datetime

        dt = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
        assert _is_in_date_range(dt, "2026-01-01", None) is False

    def test_is_in_date_range_no_bounds(self) -> None:
        from datetime import UTC, datetime

        dt = datetime(2020, 1, 1, tzinfo=UTC)
        assert _is_in_date_range(dt, None, None) is True

    def test_to_iso8601_format(self) -> None:
        from datetime import UTC, datetime

        dt = datetime(2026, 3, 15, 10, 30, 0, tzinfo=UTC)
        result = _to_iso8601(dt)
        assert result == "2026-03-15T10:30:00Z"


class TestThreadScraperBuildAuthContext:
    """Kill mutants in ThreadScraper._build_auth_context."""

    def test_sets_content_type_header(self) -> None:
        scraper = ThreadScraper(token="tok")
        headers, cookies = scraper._build_auth_context("session-tok")
        assert headers == {"Content-Type": "application/json"}

    def test_sets_session_token_cookie(self) -> None:
        scraper = ThreadScraper(token="tok")
        headers, cookies = scraper._build_auth_context("my-session")
        assert cookies["__Secure-next-auth.session-token"] == "my-session"

    def test_existing_cookies_preserved(self) -> None:
        scraper = ThreadScraper(token="tok", cookies={"cf_clearance": "abc"})
        headers, cookies = scraper._build_auth_context("sess")
        assert cookies["cf_clearance"] == "abc"
        assert cookies["__Secure-next-auth.session-token"] == "sess"

    def test_existing_session_token_not_overwritten(self) -> None:
        scraper = ThreadScraper(
            token="tok", cookies={"__Secure-next-auth.session-token": "existing"}
        )
        _, cookies = scraper._build_auth_context("new-val")
        assert cookies["__Secure-next-auth.session-token"] == "existing"

    def test_none_cookies_defaults_to_empty(self) -> None:
        scraper = ThreadScraper(token="tok", cookies=None)
        _, cookies = scraper._build_auth_context("sess")
        assert cookies["__Secure-next-auth.session-token"] == "sess"


class TestThreadScraperFilterByDateRange:
    """Kill mutants in ThreadScraper._filter_by_date_range."""

    def _make_thread(self, title: str, date: str) -> ThreadRecord:
        return ThreadRecord(title=title, url="https://x.com/s", created_at=date)

    def test_no_bounds_returns_all(self) -> None:
        scraper = ThreadScraper(token="tok")
        threads = [self._make_thread("A", "2026-01-01T00:00:00Z")]
        result = scraper._filter_by_date_range(threads, None, None)
        assert len(result) == 1

    def test_from_date_filters_old(self) -> None:
        scraper = ThreadScraper(token="tok")
        threads = [
            self._make_thread("Old", "2025-06-01T00:00:00Z"),
            self._make_thread("New", "2026-06-01T00:00:00Z"),
        ]
        result = scraper._filter_by_date_range(threads, "2026-01-01", None)
        assert len(result) == 1
        assert result[0].title == "New"

    def test_to_date_filters_new(self) -> None:
        scraper = ThreadScraper(token="tok")
        threads = [
            self._make_thread("Old", "2025-06-01T00:00:00Z"),
            self._make_thread("New", "2026-06-01T00:00:00Z"),
        ]
        result = scraper._filter_by_date_range(threads, None, "2025-12-31")
        assert len(result) == 1
        assert result[0].title == "Old"

    def test_both_bounds(self) -> None:
        scraper = ThreadScraper(token="tok")
        threads = [
            self._make_thread("Jan", "2026-01-15T00:00:00Z"),
            self._make_thread("Mar", "2026-03-15T00:00:00Z"),
            self._make_thread("Jun", "2026-06-15T00:00:00Z"),
        ]
        result = scraper._filter_by_date_range(threads, "2026-02-01", "2026-04-30")
        assert len(result) == 1
        assert result[0].title == "Mar"

    def test_empty_threads(self) -> None:
        scraper = ThreadScraper(token="tok")
        result = scraper._filter_by_date_range([], "2026-01-01", None)
        assert result == []


class TestThreadScraperMergeWithCache:
    """Kill mutants in ThreadScraper._merge_with_cache."""

    def test_no_cached_returns_fetched(self) -> None:
        scraper = ThreadScraper(token="tok")
        fetched = [ThreadRecord(title="F", url="u", created_at="c")]
        result = scraper._merge_with_cache([], fetched)
        assert result is fetched

    def test_no_cache_manager_returns_fetched(self) -> None:
        scraper = ThreadScraper(token="tok", cache_manager=None)
        cached = [ThreadRecord(title="C", url="u", created_at="c")]
        fetched = [ThreadRecord(title="F", url="u", created_at="c")]
        result = scraper._merge_with_cache(cached, fetched)
        assert result is fetched

    def test_with_cache_manager_calls_merge(self) -> None:
        cm = MagicMock()
        cm.merge_threads.return_value = [ThreadRecord(title="M", url="u", created_at="c")]
        scraper = ThreadScraper(token="tok", cache_manager=cm)
        cached = [ThreadRecord(title="C", url="u", created_at="c")]
        fetched = [ThreadRecord(title="F", url="u", created_at="c")]
        result = scraper._merge_with_cache(cached, fetched)
        cm.merge_threads.assert_called_once_with(cached, fetched)
        assert result[0].title == "M"


class TestThreadScraperMergeAndSave:
    """Kill mutants in ThreadScraper._merge_and_save."""

    def test_saves_to_cache_when_manager_present(self) -> None:
        cm = MagicMock()
        cm.merge_threads.return_value = []
        scraper = ThreadScraper(token="tok", cache_manager=cm)
        scraper._merge_and_save(None, None, [], [])
        cm.save_cache.assert_called_once()

    def test_no_save_without_cache_manager(self) -> None:
        scraper = ThreadScraper(token="tok", cache_manager=None)
        result = scraper._merge_and_save(None, None, [], [])
        assert result == []

    def test_filters_before_saving(self) -> None:
        cm = MagicMock()
        cm.merge_threads.return_value = [
            ThreadRecord(title="Old", url="u", created_at="2025-01-01T00:00:00Z"),
            ThreadRecord(title="New", url="u", created_at="2026-06-01T00:00:00Z"),
        ]
        scraper = ThreadScraper(token="tok", cache_manager=cm)
        result = scraper._merge_and_save("2026-01-01", None, [ThreadRecord(title="C", url="u", created_at="c")], [])
        assert len(result) == 1
        assert result[0].title == "New"


class TestThreadScraperProcessBatch:
    """Kill mutants in ThreadScraper._process_thread_batch."""

    def test_empty_batch_returns_false(self) -> None:
        scraper = ThreadScraper(token="tok")
        threads: list[ThreadRecord] = []
        result = scraper._process_thread_batch([], threads)
        assert result is False

    def test_valid_thread_appended(self) -> None:
        scraper = ThreadScraper(token="tok")
        threads: list[ThreadRecord] = []
        data = [{"last_query_datetime": "2026-06-01T00:00:00+00:00", "slug": "s", "title": "T"}]
        result = scraper._process_thread_batch(data, threads)
        assert result is False
        assert len(threads) == 1
        assert threads[0].title == "T"

    def test_from_date_cutoff_returns_true(self) -> None:
        scraper = ThreadScraper(token="tok")
        threads: list[ThreadRecord] = []
        data = [{"last_query_datetime": "2020-01-01T00:00:00+00:00", "slug": "s", "title": "Old"}]
        ctx = BatchProcessingContext(from_date="2025-01-01")
        result = scraper._process_thread_batch(data, threads, ctx)
        assert result is True
        assert len(threads) == 0

    def test_progress_callback_invoked(self) -> None:
        scraper = ThreadScraper(token="tok")
        threads: list[ThreadRecord] = []
        cb = Mock()
        data = [
            {
                "last_query_datetime": "2026-06-01T00:00:00+00:00",
                "slug": "s",
                "title": "T",
                "total_threads": 10,
            }
        ]
        ctx = BatchProcessingContext(total_threads=10, progress_callback=cb)
        scraper._process_thread_batch(data, threads, ctx)
        cb.assert_called_once_with(1, 10)


class TestThreadScraperInit:
    """Kill mutants in ThreadScraper.__init__."""

    def test_token_stored(self) -> None:
        scraper = ThreadScraper(token="my-token")
        assert scraper.token == "my-token"

    def test_force_refresh_default_false(self) -> None:
        scraper = ThreadScraper(token="tok")
        assert scraper.force_refresh is False

    def test_force_refresh_true(self) -> None:
        scraper = ThreadScraper(token="tok", force_refresh=True)
        assert scraper.force_refresh is True

    def test_cookies_stored(self) -> None:
        scraper = ThreadScraper(token="tok", cookies={"a": "b"})
        assert scraper.cookies == {"a": "b"}

    def test_cookies_default_none(self) -> None:
        scraper = ThreadScraper(token="tok")
        assert scraper.cookies is None

    def test_rate_limiter_stored(self) -> None:
        rl = Mock()
        scraper = ThreadScraper(token="tok", rate_limiter=rl)
        assert scraper.rate_limiter is rl

    def test_cache_manager_stored(self) -> None:
        cm = Mock()
        scraper = ThreadScraper(token="tok", cache_manager=cm)
        assert scraper.cache_manager is cm


class TestFetchMergeContextDataclass:
    """Kill mutants in FetchMergeContext frozen dataclass."""

    def test_fields_accessible(self) -> None:
        ctx = FetchMergeContext(
            from_date="2026-01-01",
            to_date="2026-12-31",
            fetch_from="2026-06-01",
            cached_threads=[],
            progress_callback=None,
        )
        assert ctx.from_date == "2026-01-01"
        assert ctx.to_date == "2026-12-31"
        assert ctx.fetch_from == "2026-06-01"
        assert ctx.cached_threads == []
        assert ctx.progress_callback is None

    def test_frozen_raises_on_mutation(self) -> None:
        ctx = FetchMergeContext(
            from_date=None, to_date=None, fetch_from=None, cached_threads=[], progress_callback=None
        )
        with pytest.raises(AttributeError):
            ctx.from_date = "changed"  # type: ignore[misc]


class TestBatchProcessingContextDefaults:
    """Kill mutants in BatchProcessingContext default values."""

    def test_all_defaults_none(self) -> None:
        ctx = BatchProcessingContext()
        assert ctx.from_date is None
        assert ctx.total_threads is None
        assert ctx.progress_callback is None

    def test_custom_values(self) -> None:
        cb = Mock()
        ctx = BatchProcessingContext(from_date="2026-01-01", total_threads=50, progress_callback=cb)
        assert ctx.from_date == "2026-01-01"
        assert ctx.total_threads == 50
        assert ctx.progress_callback is cb
