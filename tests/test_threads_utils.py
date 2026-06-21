"""Tests for threads/utils.py utility functions."""

from __future__ import annotations

import pytest

from perplexity_cli.threads.utils import convert_cache_dicts_to_thread_records
from perplexity_cli.utils.exceptions import UpstreamSchemaError


class TestConvertCacheDictsToThreadRecords:
    def test_converts_valid_dicts_to_records(self) -> None:
        records = convert_cache_dicts_to_thread_records(
            [
                {"title": "t", "url": "https://a.com", "created_at": "2024-01-01"},
            ]
        )
        assert len(records) == 1
        assert records[0].title == "t"

    def test_returns_empty_for_empty_list(self) -> None:
        records = convert_cache_dicts_to_thread_records([])
        assert records == []

    def test_raises_for_non_dict_input(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="Malformed cached thread record"):
            convert_cache_dicts_to_thread_records(["not_a_dict"])

    def test_raises_for_missing_key(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="missing title"):
            convert_cache_dicts_to_thread_records([{"url": "a", "created_at": "b"}])
