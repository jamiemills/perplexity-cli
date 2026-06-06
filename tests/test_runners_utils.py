"""Unit tests for runner utility functions not covered elsewhere."""

from __future__ import annotations

from perplexity_cli.runners._utils import resolve_json_flag


class TestResolveJsonFlag:
    """Tests for resolve_json_flag()."""

    def test_explicit_true_takes_precedence(self) -> None:
        assert resolve_json_flag(True, None) is True

    def test_explicit_false_takes_precedence(self) -> None:
        assert resolve_json_flag(False, {"json": True}) is False

    def test_from_ctx_obj_when_explicit_is_none(self) -> None:
        assert resolve_json_flag(None, {"json": True}) is True

    def test_from_ctx_obj_missing_key(self) -> None:
        assert resolve_json_flag(None, {"other": "value"}) is False

    def test_returns_false_when_ctx_obj_is_none(self) -> None:
        assert resolve_json_flag(None, None) is False

    def test_returns_false_when_ctx_obj_is_empty(self) -> None:
        assert resolve_json_flag(None, {}) is False
