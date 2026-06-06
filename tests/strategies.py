"""Reusable bounded Hypothesis strategies for property-based tests."""

from __future__ import annotations

from datetime import UTC, datetime

from hypothesis import strategies as st

from perplexity_cli.threads.exporter import ThreadRecord

__all__ = [
    "citation_text",
    "json_scalars_and_containers",
    "markdown_text",
    "ordered_utc_datetime_pair",
    "safe_text",
    "thread_record_lists",
    "utc_datetimes",
]


def safe_text(max_size: int = 200) -> st.SearchStrategy[str]:
    return st.text(max_size=max_size)


def _normalise_line(value: str, fallback: str) -> str:
    line = " ".join(value.split()).strip()
    return line or fallback


def _citation_marker() -> st.SearchStrategy[str]:
    numeric_marker = st.integers(min_value=1, max_value=99).map(lambda value: f"[{value}]")
    bracketed_text = st.text(min_size=1, max_size=8).map(lambda value: f"[{value}]")
    return st.one_of(numeric_marker, numeric_marker, bracketed_text)


def citation_text() -> st.SearchStrategy[str]:
    token = st.one_of(safe_text(24), _citation_marker(), st.text(min_size=1, max_size=24))
    return st.lists(token, min_size=1, max_size=14).map(
        lambda parts: " ".join(part for part in parts if part)
    )


def _markdown_heading() -> st.SearchStrategy[str]:
    return st.tuples(st.integers(min_value=1, max_value=3), safe_text(40)).map(
        lambda pair: f"{'#' * pair[0]} {_normalise_line(pair[1], 'Heading')}"
    )


def _markdown_paragraph() -> st.SearchStrategy[str]:
    return safe_text(120).map(lambda value: _normalise_line(value, "Paragraph"))


def _markdown_list_item() -> st.SearchStrategy[str]:
    bullet = st.sampled_from(["-", "*", "1."])
    return st.tuples(bullet, safe_text(80)).map(
        lambda pair: f"{pair[0]} {_normalise_line(pair[1], 'List item')}"
    )


def _markdown_blockquote() -> st.SearchStrategy[str]:
    return safe_text(100).map(lambda value: f"> {_normalise_line(value, 'Quoted text')}")


def _markdown_table_row() -> st.SearchStrategy[str]:
    return st.lists(safe_text(16), min_size=2, max_size=4).map(
        lambda cells: " | ".join(_normalise_line(cell, "cell") for cell in cells)
    )


def _markdown_horizontal_rule() -> st.SearchStrategy[str]:
    return st.sampled_from(["---", "***", "___"])


def _markdown_code_block() -> st.SearchStrategy[str]:
    languages = st.sampled_from(["", "python", "json", "bash"])
    lines = st.lists(safe_text(32), min_size=1, max_size=4)
    return st.tuples(languages, lines).map(
        lambda pair: (
            f"```{pair[0]}\n"
            + "\n".join(_normalise_line(line, "code") for line in pair[1])
            + "\n```"
        )
    )


def markdown_text() -> st.SearchStrategy[str]:
    block = st.one_of(
        _markdown_heading(),
        _markdown_paragraph(),
        _markdown_list_item(),
        _markdown_blockquote(),
        _markdown_table_row(),
        _markdown_horizontal_rule(),
        _markdown_code_block(),
    )
    return st.lists(block, min_size=1, max_size=8).map(lambda blocks: "\n\n".join(blocks))


def utc_datetimes() -> st.SearchStrategy[datetime]:
    return st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2030, 12, 31, 23, 59, 59, 999999),
        timezones=st.just(UTC),
    )


def ordered_utc_datetime_pair() -> st.SearchStrategy[tuple[datetime, datetime]]:
    return st.tuples(utc_datetimes(), utc_datetimes()).map(
        lambda pair: (pair[0], pair[1]) if pair[0] <= pair[1] else (pair[1], pair[0])
    )


def _thread_record_strategy() -> st.SearchStrategy[ThreadRecord]:
    urls = st.sampled_from(
        [
            "https://www.perplexity.ai/search/a",
            "https://www.perplexity.ai/search/b",
            "https://www.perplexity.ai/search/c",
            "https://www.perplexity.ai/search/d",
            "https://www.perplexity.ai/search/e",
            "https://www.perplexity.ai/search/f",
            "https://www.perplexity.ai/search/g",
            "https://www.perplexity.ai/search/h",
        ]
    )
    created_at = utc_datetimes().map(lambda value: value.isoformat().replace("+00:00", "Z"))
    return st.builds(
        ThreadRecord,
        title=safe_text(80).map(lambda value: _normalise_line(value, "Thread title")),
        url=urls,
        created_at=created_at,
    )


def thread_record_lists() -> st.SearchStrategy[tuple[list[ThreadRecord], list[ThreadRecord]]]:
    records = _thread_record_strategy()
    return st.tuples(
        st.lists(records, max_size=15),
        st.lists(records, max_size=15),
    )


def json_scalars_and_containers() -> st.SearchStrategy[object]:
    scalars = st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-1_000_000, max_value=1_000_000),
        st.floats(
            min_value=-1_000_000.0,
            max_value=1_000_000.0,
            allow_nan=False,
            allow_infinity=False,
            width=32,
        ),
        st.text(max_size=40),
    )
    return st.recursive(
        scalars,
        lambda children: st.one_of(
            st.lists(children, max_size=5),
            st.dictionaries(st.text(max_size=12), children, max_size=5),
        ),
        max_leaves=20,
    )
