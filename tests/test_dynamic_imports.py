"""Prove that check_dynamic_imports.py:

- Detects importlib.import_module calls with constant-string arguments
- Detects __import__ calls
- Checks dynamic imports against the same direction policy
- Fails on non-constant dynamic imports unless allowlisted
- Fails on forbidden dynamic imports
- Allows explicitly declared dynamic imports
- Proves that moving a forbidden static import into a dynamic call still fails
"""
# noqa: D (tests are exempt from docstring requirements)

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import scripts.check_dynamic_imports as cdi  # noqa: E402
from scripts.check_dynamic_imports import (  # noqa: E402
    AnalysisResult,
    _build_dynamic_allowlist,
    _build_layer_map,
    _check_dynamic_call,
    _check_dynamic_direction,
    _detect_dynamic_imports,
    _DynamicCheckCtx,
    _DynamicImportCall,
    _load_toml,
    _resolve_dynamic_target,
    _run_checks,
    _RunConfig,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "dynamic_imports"


@contextmanager
def _with_src_root(new_root: Path):
    """Temporarily override cdi.SRC_ROOT for fixture-based tests."""
    old = cdi.SRC_ROOT
    cdi.SRC_ROOT = new_root
    try:
        yield
    finally:
        cdi.SRC_ROOT = old


def _make_dynamic_ctx(
    source_rel: str,
    lineno: int = 1,
    layer_map: dict | None = None,
    dynamic_allowlist: dict | None = None,
) -> _DynamicCheckCtx:
    """Build a minimal _DynamicCheckCtx for unit testing."""
    result = AnalysisResult()
    return _DynamicCheckCtx(
        source_module_rel=source_rel,
        lineno=lineno,
        filepath=f"test:source:{source_rel}",
        layer_map=layer_map or {},
        dynamic_allowlist=dynamic_allowlist or {},
        result=result,
    )


def _run_fixture_checks(fixture_name: str) -> AnalysisResult:
    """Run _run_checks against a named fixture package."""
    toml_path = FIXTURE_DIR / fixture_name / "architecture.toml"
    toml_data = _load_toml(toml_path)
    layer_map = _build_layer_map(toml_data)
    dynamic_allowlist = _build_dynamic_allowlist(toml_data)
    config = _RunConfig(layer_map=layer_map, dynamic_allowlist=dynamic_allowlist)
    pkg = FIXTURE_DIR / fixture_name / "pkg"
    files = sorted(p for p in pkg.rglob("*.py") if "__pycache__" not in str(p))
    with _with_src_root(pkg):
        return _run_checks(files, config)


# ------------------------------------------------------------------
# Dynamic import detection tests
# ------------------------------------------------------------------


def test_detects_importlib_import_module():
    """importlib.import_module("module") is detected."""
    import ast

    source = """
import importlib
mod = importlib.import_module("pkg.models")
"""
    tree = ast.parse(source)
    calls = _detect_dynamic_imports(tree)
    assert len(calls) == 1
    assert calls[0].func_name == "importlib.import_module"
    assert calls[0].argument == "pkg.models"
    assert calls[0].is_constant


def test_detects_builtin_import():
    """__import__("module") is detected."""
    import ast

    source = """
mod = __import__("pkg.models")
"""
    tree = ast.parse(source)
    calls = _detect_dynamic_imports(tree)
    assert len(calls) == 1
    assert calls[0].func_name == "__import__"
    assert calls[0].argument == "pkg.models"


def test_detects_non_constant_argument():
    """importlib.import_module(var) with non-constant arg is detected as non-constant."""
    import ast

    source = """
import importlib
mod = importlib.import_module(some_variable)
"""
    tree = ast.parse(source)
    calls = _detect_dynamic_imports(tree)
    assert len(calls) == 1
    assert calls[0].is_constant is False


# ------------------------------------------------------------------
# Clean dynamic imports (allowlisted)
# ------------------------------------------------------------------


def test_clean_dynamic_allowed():
    """Explicitly allowlisted dynamic import passes."""
    result = _run_fixture_checks("clean_dynamic")
    dynamic_errors = [v for v in result.errors if "dynamic" in v.rule]
    assert len(dynamic_errors) == 0, f"Unexpected dynamic errors: {dynamic_errors}"


# ------------------------------------------------------------------
# Forbidden dynamic imports
# ------------------------------------------------------------------


def test_forbidden_dynamic_import_fails():
    """Dynamic import of a forbidden layer without allowlist entry fails."""
    result = _run_fixture_checks("forbidden_dynamic")
    dynamic_errors = [v for v in result.errors if "dynamic" in v.rule]
    assert len(dynamic_errors) >= 1, f"Expected dynamic import errors, got {result.violations}"


def test_dynamic_bypass_still_fails():
    """Moving a forbidden static import into a dynamic call still fails."""
    layer_map = {
        "svc": ("application", frozenset({"domain", "application"})),
        "ui": ("presentation", frozenset({"domain", "application", "presentation"})),
    }
    ctx = _make_dynamic_ctx("svc", layer_map=layer_map)
    _check_dynamic_direction(ctx, "ui")
    assert len(ctx.result.violations) == 1
    v = ctx.result.violations[0]
    assert v.rule == "dynamic-import-direction"
    assert "application" in v.message


# ------------------------------------------------------------------
# Non-constant dynamic imports
# ------------------------------------------------------------------


def test_non_constant_dynamic_fails():
    """Non-constant string arguments in dynamic imports produce errors."""
    result = _run_fixture_checks("non_constant_dynamic")
    nonconst_errors = [v for v in result.errors if v.rule == "dynamic-import-non-constant"]
    assert len(nonconst_errors) >= 1, (
        f"Expected non-constant dynamic errors, got {result.violations}"
    )


def test_non_constant_argument_unit():
    """Unit test: non-constant dynamic imports are flagged."""
    call = _DynamicImportCall(
        func_name="importlib.import_module",
        argument=None,
        lineno=10,
        is_constant=False,
    )
    ctx = _make_dynamic_ctx("svc")
    _check_dynamic_call(ctx, call)
    assert len(ctx.result.violations) == 1
    assert ctx.result.violations[0].rule == "dynamic-import-non-constant"


# ------------------------------------------------------------------
# Resolution tests
# ------------------------------------------------------------------


def test_dynamic_target_resolution_absolute():
    """Absolute dynamic import target is resolved correctly."""
    pkg = FIXTURE_DIR / "clean_dynamic" / "pkg"
    with _with_src_root(pkg):
        result = cdi._resolve_dynamic_target("models", source_module_rel="svc")
        assert result == "models", f"Expected 'models', got {result!r}"


def test_dynamic_target_resolution_relative():
    """Relative dynamic import target is resolved correctly."""
    pkg = FIXTURE_DIR / "clean_dynamic" / "pkg"
    with _with_src_root(pkg):
        result = cdi._resolve_dynamic_target(".cli", source_module_rel="services")
        assert result == "cli", f"Expected 'cli', got {result!r}"


def test_dynamic_target_external_ignored():
    """External dynamic imports are ignored (return None)."""
    result = _resolve_dynamic_target("os.path", source_module_rel="svc")
    assert result is None


# ------------------------------------------------------------------
# TOML parsing tests
# ------------------------------------------------------------------


def test_dynamic_allowlist_parsed():
    """_build_dynamic_allowlist extracts the [dynamic_imports] section."""
    toml_data = {"dynamic_imports": {"services": ["models", "utils"], "cli": []}}
    allowlist = _build_dynamic_allowlist(toml_data)
    assert "services" in allowlist
    assert allowlist["services"] == {"models", "utils"}
    assert allowlist.get("cli") == set()


def test_missing_dynamic_imports_section():
    """When [dynamic_imports] is absent, allowlist is empty."""
    toml_data = {"layers": []}
    allowlist = _build_dynamic_allowlist(toml_data)
    assert allowlist == {}


# ------------------------------------------------------------------
# Fail-closed tests
# ------------------------------------------------------------------


def test_run_checks_always_returns_result():
    """_run_checks always produces a result with files_checked."""
    result = _run_fixture_checks("clean_dynamic")
    assert result is not None
    assert result.files_checked > 0
