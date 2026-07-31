"""Structural policy tests for __init__.py files and formatter registry dispatch.

Verifies that production __init__.py modules remain declarative (imports,
__all__, constants, __version__) and contain no executable logic.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    pass

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "perplexity_cli"

KNOWN_VIOLATIONS: frozenset[str] = frozenset(
    {
        "formatting/__init__.py",
        "auth/__init__.py",
        "commands/__init__.py",
    }
)

_LITERAL_NODES = (
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Dict,
)


def _is_simple_literal_assign(node: ast.stmt) -> bool:
    """Return True if *node* is an assignment of a literal value."""
    if not isinstance(node, ast.Assign):
        return False
    if not isinstance(node.value, _LITERAL_NODES):
        return False
    return all(isinstance(t, ast.Name) for t in node.targets)


def _is_version_assign(node: ast.stmt) -> bool:
    """Return True if *node* assigns to ``__version__``."""
    if not isinstance(node, ast.Assign):
        return False
    return any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)


def _is_all_assign(node: ast.stmt) -> bool:
    """Return True if *node* assigns to ``__all__``."""
    if not isinstance(node, ast.Assign):
        return False
    return any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)


def _is_protocol_classdef(node: ast.stmt) -> bool:
    """Return True for ``class X(Protocol):`` definitions (declarative interfaces)."""
    if not isinstance(node, ast.ClassDef):
        return False
    return any(
        (isinstance(b, ast.Name) and b.id == "Protocol")
        or (isinstance(b, ast.Attribute) and b.attr == "Protocol")
        for b in node.bases
    )


def _classify_statement(node: ast.stmt) -> str:
    """Classify a single AST statement as allowed or executable."""
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
        return "docstring"
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return "import"
    if _is_all_assign(node):
        return "__all__"
    if _is_version_assign(node):
        return "__version__"
    if _is_simple_literal_assign(node):
        return "constant"
    if _is_protocol_classdef(node):
        return "protocol"
    return "executable"


def find_violations(source: str) -> list[str]:
    """Return descriptions of executable statements in *source*."""
    tree = ast.parse(source)
    violations: list[str] = []
    for node in tree.body:
        kind = _classify_statement(node)
        if kind == "executable":
            violations.append(f"line {node.lineno}: {type(node).__name__}")
    return violations


def _all_init_files() -> list[Path]:
    """Collect all production __init__.py files."""
    return sorted(SOURCE_ROOT.rglob("__init__.py"))


class TestInitPolicySynthetic:
    """Synthetic pass/fail cases for the init policy checker."""

    def test_clean_init_passes(self) -> None:
        source = textwrap.dedent("""\
            \"\"\"Module docstring.\"\"\"

            from foo import bar
            import baz

            __all__ = ["bar"]
            __version__ = "1.0.0"
            CONSTANT = 42
        """)
        assert find_violations(source) == []

    def test_function_def_fails(self) -> None:
        source = textwrap.dedent("""\
            \"\"\"Doc.\"\"\"

            def helper():
                pass
        """)
        violations = find_violations(source)
        assert len(violations) == 1
        assert "FunctionDef" in violations[0]

    def test_class_def_fails(self) -> None:
        source = textwrap.dedent("""\
            class Foo:
                pass
        """)
        violations = find_violations(source)
        assert len(violations) == 1
        assert "ClassDef" in violations[0]

    def test_if_statement_fails(self) -> None:
        source = textwrap.dedent("""\
            import sys
            if sys.platform == "win32":
                pass
        """)
        violations = find_violations(source)
        assert len(violations) == 1
        assert "If" in violations[0]

    def test_for_loop_fails(self) -> None:
        source = "for x in range(3):\n    pass\n"
        violations = find_violations(source)
        assert len(violations) == 1
        assert "For" in violations[0]

    def test_while_loop_fails(self) -> None:
        source = "while True:\n    break\n"
        violations = find_violations(source)
        assert len(violations) == 1
        assert "While" in violations[0]

    def test_try_except_fails(self) -> None:
        source = textwrap.dedent("""\
            try:
                pass
            except OSError:
                pass
        """)
        violations = find_violations(source)
        assert len(violations) == 1
        assert "Try" in violations[0]

    def test_function_call_fails(self) -> None:
        source = textwrap.dedent("""\
            from foo import register
            register("thing")
        """)
        violations = find_violations(source)
        assert len(violations) == 1
        assert "Expr" in violations[0]

    def test_method_call_fails(self) -> None:
        source = textwrap.dedent("""\
            import warnings
            warnings.filterwarnings("ignore")
        """)
        violations = find_violations(source)
        assert len(violations) == 1

    def test_version_call_allowed(self) -> None:
        source = textwrap.dedent("""\
            from pkg import get_version
            __version__ = get_version()
        """)
        assert find_violations(source) == []


class TestInitPolicyCodebase:
    """Verify production __init__.py files comply with the declarative policy."""

    def test_all_init_files_are_declarative(self) -> None:
        failures: list[str] = []
        for path in _all_init_files():
            rel = str(path.relative_to(SOURCE_ROOT))
            if rel in KNOWN_VIOLATIONS:
                continue
            source = path.read_text(encoding="utf-8")
            violations = find_violations(source)
            if violations:
                failures.append(f"{rel}: {violations}")
        assert failures == [], "Policy violations:\n" + "\n".join(failures)

    def test_known_violations_are_tracked(self) -> None:
        for rel in sorted(KNOWN_VIOLATIONS):
            path = SOURCE_ROOT / rel
            assert path.is_file(), f"Known violation {rel} no longer exists"


class TestFormatterRegistryDispatch:
    """Direct tests for formatting/registry.py dispatch behaviour."""

    def test_register_and_get(self) -> None:
        from perplexity_cli.formatting.registry import FormatterRegistry

        registry = FormatterRegistry()

        class _Stub:
            pass

        registry.register("stub", _Stub)  # type: ignore[arg-type]
        result = registry.get("stub")
        assert isinstance(result, _Stub)

    def test_get_unknown_raises(self) -> None:
        from perplexity_cli.formatting.registry import FormatterRegistry

        registry = FormatterRegistry()
        with pytest.raises(ValueError, match="Unknown formatter"):
            registry.get("nonexistent")

    def test_names_sorted(self) -> None:
        from perplexity_cli.formatting.registry import FormatterRegistry

        registry = FormatterRegistry()

        class _A:
            pass

        class _B:
            pass

        registry.register("beta", _B)  # type: ignore[arg-type]
        registry.register("alpha", _A)  # type: ignore[arg-type]
        assert registry.names() == ["alpha", "beta"]

    def test_global_registry_resolves_builtin_formats(self) -> None:
        import perplexity_cli.formatting  # noqa: F401  # owner: cli-team; reason: side-effect import registers built-in formatters
        from perplexity_cli.formatting.registry import get_formatter, list_formatters

        names = list_formatters()
        assert "plain" in names
        assert "rich" in names
        assert "json" in names
        assert "markdown" in names

        formatter = get_formatter("plain")
        assert formatter is not None

    def test_resolve_format_explicit(self) -> None:
        from perplexity_cli.formatting.registry import resolve_format

        assert resolve_format("json") == "json"

    def test_resolve_format_no_color_flag(self) -> None:
        from perplexity_cli.formatting.registry import resolve_format

        assert resolve_format(None, no_color=True) == "plain"

    def test_resolve_format_no_color_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from perplexity_cli.formatting.registry import resolve_format

        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        assert resolve_format(None) == "plain"

    def test_resolve_format_non_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from perplexity_cli.formatting.registry import resolve_format

        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        assert resolve_format(None) == "plain"

    def test_resolve_format_tty_default_rich(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from perplexity_cli.formatting.registry import resolve_format

        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        assert resolve_format(None) == "rich"
