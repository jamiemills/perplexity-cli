"""Tests for the typed dependency container module."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from perplexity_cli.query_deps import (
    make_query_deps,
    override_query_deps,
    require_query_deps,
)


class TestQueryDeps:
    """Container defaults and override behaviour (no global mutation)."""

    def test_make_query_deps_rejects_placeholder_calls(self) -> None:
        container = make_query_deps()
        with pytest.raises(AssertionError, match="placeholder"):
            container.handle_error()

    def test_override_returns_previous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        original = require_query_deps()
        replacement = override_query_deps(monkeypatch, PerplexityAPI=Mock())
        assert replacement is original
        # monkeypatch teardown restores the original container.

    def test_override_fields_are_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_api = Mock()
        original = require_query_deps()
        override_query_deps(monkeypatch, PerplexityAPI=fake_api)
        current = require_query_deps()
        assert current.PerplexityAPI is fake_api
        assert current is not original
