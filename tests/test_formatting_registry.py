"""Behavioural tests for perplexity_cli.formatting.registry."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from perplexity_cli.formatting import registry as registry_module
from perplexity_cli.formatting.base import Formatter
from perplexity_cli.formatting.json import JSONFormatter
from perplexity_cli.formatting.markdown import MarkdownFormatter
from perplexity_cli.formatting.plain import PlainTextFormatter
from perplexity_cli.formatting.registry import (
    FormatterRegistry,
    get_formatter,
    list_formatters,
    register_formatter,
    resolve_format,
)
from perplexity_cli.formatting.rich import RichFormatter

if TYPE_CHECKING:
    from collections.abc import Iterator

    from perplexity_cli.contracts.query import WebResult


class _T010StubFormatter(Formatter):
    """Concrete formatter used to exercise registry wiring."""

    def format_answer(self, text: str, strip_references: bool = False) -> str:
        return text

    def format_references(self, references: list[WebResult]) -> str:
        return ""


@pytest.fixture
def t010_isolated_global_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[FormatterRegistry]:
    """Swap the module-level registry so global registrations never leak."""
    fresh = FormatterRegistry()
    monkeypatch.setattr(registry_module, "_registry", fresh)
    yield fresh


class TestFormatterRegistry:
    """Instance-level registry behaviour."""

    def test_register_and_get_returns_new_instance(self):
        registry = FormatterRegistry()
        registry.register("stub", _T010StubFormatter)
        assert isinstance(registry.get("stub"), _T010StubFormatter)

    def test_get_unknown_name_lists_available(self):
        registry = FormatterRegistry()
        registry.register("alpha", _T010StubFormatter)
        registry.register("beta", _T010StubFormatter)
        with pytest.raises(ValueError, match="Unknown formatter: missing") as exc_info:
            registry.get("missing")
        assert "alpha, beta" in str(exc_info.value)

    def test_names_are_sorted(self):
        registry = FormatterRegistry()
        registry.register("zeta", _T010StubFormatter)
        registry.register("alpha", _T010StubFormatter)
        assert registry.names() == ["alpha", "zeta"]

    def test_registration_replaces_previous_entry(self):
        registry = FormatterRegistry()

        class Replacement(_T010StubFormatter):
            pass

        registry.register("stub", _T010StubFormatter)
        registry.register("stub", Replacement)
        assert isinstance(registry.get("stub"), Replacement)


class TestGlobalRegistryFunctions:
    """Module-level registration and lookup helpers."""

    def test_register_formatter_makes_lookup_succeed(
        self, t010_isolated_global_registry: FormatterRegistry
    ):
        register_formatter("t010-stub", _T010StubFormatter)
        assert list_formatters() == ["t010-stub"]
        assert isinstance(get_formatter("t010-stub"), _T010StubFormatter)

    def test_get_formatter_unknown_name_reports_available(
        self, t010_isolated_global_registry: FormatterRegistry
    ):
        register_formatter("known", _T010StubFormatter)
        with pytest.raises(ValueError, match="Available: known"):
            get_formatter("other")


class TestBundledFormattersRegistered:
    """The shipped formatters are reachable through the global registry."""

    def test_list_formatters_contains_bundled_names(self):
        names = list_formatters()
        for expected in ("json", "markdown", "plain", "rich"):
            assert expected in names

    @pytest.mark.parametrize(
        ("name", "formatter_class"),
        [
            ("json", JSONFormatter),
            ("markdown", MarkdownFormatter),
            ("plain", PlainTextFormatter),
            ("rich", RichFormatter),
        ],
    )
    def test_get_formatter_returns_expected_type(self, name: str, formatter_class: type):
        assert isinstance(get_formatter(name), formatter_class)


class _T010TtyStdout:
    """Stdout stand-in reporting itself as a terminal."""

    def isatty(self) -> bool:
        return True


class TestResolveFormat:
    """Explicit format wins; environment decides the default."""

    def test_explicit_format_is_returned_unchanged(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(sys, "stdout", _T010TtyStdout())
        monkeypatch.delenv("NO_COLOR", raising=False)
        assert resolve_format("markdown") == "markdown"

    def test_tty_without_no_color_defaults_to_rich(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(sys, "stdout", _T010TtyStdout())
        monkeypatch.delenv("NO_COLOR", raising=False)
        assert resolve_format(None) == "rich"

    def test_no_colour_flag_forces_plain_on_tty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(sys, "stdout", _T010TtyStdout())
        monkeypatch.delenv("NO_COLOR", raising=False)
        assert resolve_format(None, no_color=True) == "plain"

    def test_no_color_env_forces_plain_on_tty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(sys, "stdout", _T010TtyStdout())
        monkeypatch.setenv("NO_COLOR", "1")
        assert resolve_format(None) == "plain"

    def test_non_tty_defaults_to_plain(self, monkeypatch: pytest.MonkeyPatch):
        import io

        monkeypatch.setattr(sys, "stdout", io.StringIO())
        monkeypatch.delenv("NO_COLOR", raising=False)
        assert resolve_format(None) == "plain"

    def test_empty_explicit_format_uses_environment_default(self, monkeypatch: pytest.MonkeyPatch):
        """An empty option is treated as unset rather than as a format name."""
        monkeypatch.setattr(sys, "stdout", _T010TtyStdout())
        monkeypatch.delenv("NO_COLOR", raising=False)
        assert resolve_format("") == "rich"
