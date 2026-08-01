"""Prove that check_architecture.py:

- Detects import direction violations (module-level, function-local, TYPE_CHECKING)
- Detects relative imports that violate direction rules
- Detects framework isolation violations
- Detects unclassified production modules
- Detects syntax errors and parse failures
- Checks fail closed (errors produce violations, not silent empty)
- Consumes quality/architecture.toml for classification
- Requires exact module classification (no prefix fallback)
- Uses repository-relative violation identities
- Fails closed on malformed/absent baseline JSON
- Validates the architecture manifest before the operational check
- The --no-baseline and --explain flags work
"""
# noqa: D (tests are exempt from docstring requirements)  # owner: quality-infrastructure; reason: test modules exempt from pydocstyle

from __future__ import annotations

import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str, register_as: str | None = None) -> ModuleType:
    """Load a scripts/<name>.py module by file path without sys.path mutation."""
    module_name = register_as or f"scripts.{name}"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(
        module_name, PROJECT_ROOT / "scripts" / f"{name}.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_load_script("architecture_model", register_as="architecture_model")
ca = _load_script("check_architecture")
from scripts.check_architecture import (  # noqa: E402  # owner: quality-infrastructure; reason: module registered in sys.modules by _load_script
    AnalysisResult,
    BaselineError,
    Severity,
    _build_adapter_groups,
    _build_layer_map,
    _check_adapter_independence,
    _check_framework_isolation,
    _check_import_direction,
    _collect_production_modules,
    _ImportCheckCtx,
    _load_baseline,
    _load_toml,
    _parse_file_imports,
    _resolve_internal_target,
    _run_checks,
    _RunConfig,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "architecture_contracts"


@contextmanager
def _with_src_root(new_root: Path):
    """Temporarily override ca.SRC_ROOT for fixture-based tests."""
    old = ca.SRC_ROOT
    ca.SRC_ROOT = new_root
    try:
        yield
    finally:
        ca.SRC_ROOT = old


def _make_context(
    source_rel: str,
    lineno: int = 1,
    layer_map: dict | None = None,
    adapter_groups: dict | None = None,
    location: str = "module-level",
) -> _ImportCheckCtx:
    """Build a minimal _ImportCheckCtx for unit testing."""
    result = AnalysisResult()
    return _ImportCheckCtx(
        source_module_rel=source_rel,
        lineno=lineno,
        filepath=f"test:source:{source_rel}",
        location=location,
        layer_map=layer_map or {},
        adapter_groups=adapter_groups or {},
        result=result,
    )


# ------------------------------------------------------------------
# TOML parsing & layer map tests
# ------------------------------------------------------------------


def test_load_toml_builds_layer_map():
    """Verify the clean fixture's TOML produces a correct layer map."""
    toml_path = FIXTURE_DIR / "clean_pkg" / "architecture.toml"
    data = _load_toml(toml_path)
    layer_map = _build_layer_map(data)
    assert layer_map["utils"] == ("shared_pure", frozenset({"shared_pure"}))
    assert layer_map["models"] == ("domain", frozenset({"shared_pure", "domain"}))
    assert layer_map["contracts"] == ("ports", frozenset({"shared_pure", "domain", "ports"}))
    assert "domain" in layer_map["services"][1]


def test_load_toml_missing_file_exits():
    """Verify loading a non-existent TOML exits with error."""
    with pytest.raises(SystemExit):
        _load_toml(Path("/nonexistent/architecture.toml"))


# ------------------------------------------------------------------
# Import direction tests
# ------------------------------------------------------------------


def _run_fixture_checks(fixture_name: str) -> AnalysisResult:
    """Run _run_checks against a named fixture package."""
    toml_path = FIXTURE_DIR / fixture_name / "architecture.toml"
    toml_data = _load_toml(toml_path)
    layer_map = _build_layer_map(toml_data)
    adapter_groups = _build_adapter_groups(toml_data)
    config = _RunConfig(layer_map=layer_map, adapter_groups=adapter_groups)
    pkg = FIXTURE_DIR / fixture_name / "pkg"
    files = sorted(p for p in pkg.rglob("*.py") if "__pycache__" not in str(p))
    with _with_src_root(pkg):
        return _run_checks(files, config)


def test_clean_package_no_violations():
    """A correctly layered package produces no violations."""
    result = _run_fixture_checks("clean_pkg")
    dir_errors = [v for v in result.errors if v.rule == "import-direction"]
    assert len(dir_errors) == 0, f"Unexpected direction errors: {dir_errors}"


def test_direction_violation_detected():
    """services (application) importing from cli (presentation) is caught."""
    result = _run_fixture_checks("violation_pkg")
    dir_errors = [v for v in result.errors if v.rule == "import-direction"]
    assert len(dir_errors) == 1, f"Expected exactly one direction error, got {result.violations}"
    assert dir_errors[0].severity == Severity.ERROR
    assert dir_errors[0].message.startswith(
        "services (layer: application) imports cli (layer: presentation)"
    )
    assert "may only import from:" in dir_errors[0].message


def test_direction_violation_unit():
    """Unit test: import direction check catches forbidden cross-layer import."""
    layer_map = {
        "svc": ("application", frozenset({"domain", "application"})),
        "ui": ("presentation", frozenset({"domain", "presentation"})),
    }
    ctx = _make_context("svc", layer_map=layer_map)
    _check_import_direction(ctx, "ui")
    assert len(ctx.result.violations) == 1
    v = ctx.result.violations[0]
    assert v.severity == Severity.ERROR
    assert v.rule == "import-direction"


def test_same_layer_no_violation():
    """Import within the same layer is allowed."""
    layer_map = {
        "svc_a": ("application", frozenset({"domain", "application"})),
        "svc_b": ("application", frozenset({"domain", "application"})),
    }
    ctx = _make_context("svc_a", layer_map=layer_map)
    _check_import_direction(ctx, "svc_b")
    assert len(ctx.result.violations) == 0


def test_allowed_layer_no_violation():
    """Import from an explicitly allowed layer is fine."""
    layer_map = {
        "svc": ("application", frozenset({"domain", "application"})),
        "mdl": ("domain", frozenset({"domain"})),
    }
    ctx = _make_context("svc", layer_map=layer_map)
    _check_import_direction(ctx, "mdl")
    assert len(ctx.result.violations) == 0


# ------------------------------------------------------------------
# Relative import tests
# ------------------------------------------------------------------


def test_relative_import_violation_detected():
    """Relative imports that resolve to a forbidden layer should be caught."""
    result = _run_fixture_checks("relative_violation_pkg")
    dir_errors = [v for v in result.errors if v.rule == "import-direction"]
    assert len(dir_errors) == 1, (
        f"Expected one direction error from relative imports, got {result.violations}"
    )
    assert "services (layer: application) imports cli (layer: presentation)" in (
        dir_errors[0].message
    )
    assert dir_errors[0].file.endswith("services.py:3")


def test_relative_import_resolution():
    """Verify relative imports are resolved to their absolute dotted form."""
    pkg = FIXTURE_DIR / "relative_violation_pkg" / "pkg"
    with _with_src_root(pkg):
        target = _resolve_internal_target(".cli", None, "services")
        assert target == "cli", f"Expected 'cli', got {target!r}"


def test_relative_parent_import_resolution():
    """A relative import that goes beyond the package root returns unresolvable."""
    pkg = FIXTURE_DIR / "relative_violation_pkg" / "pkg"
    with _with_src_root(pkg):
        # Level 2 from "services" goes above "pkg" boundary
        target = _resolve_internal_target("..pkg.cli", None, "services")
        assert target == "..pkg.cli", f"Expected unresolvable dot-string, got {target!r}"


# ------------------------------------------------------------------
# Function-local and TYPE_CHECKING import tests
# ------------------------------------------------------------------


def test_function_local_import_detection():
    """Imports inside function bodies are parsed and categorized as function-local."""
    pkg_dir = FIXTURE_DIR / "relative_violation_pkg" / "pkg"
    test_file = pkg_dir / "_test_func_local.py"
    # Create a temporary file inside the fixture pkg
    test_file.write_text("""\
def foo():
    from .cli import render
    return render
""")
    try:
        with _with_src_root(pkg_dir):
            module_rel, ml, fl, tc, err = _parse_file_imports(test_file)
            assert err is None
            assert len(fl) == 1
            assert fl[0] == (".cli", "render", 2)
            assert not tc
            assert not ml
    finally:
        test_file.unlink()


def test_type_checking_import_detection():
    """Imports inside if TYPE_CHECKING blocks are detected."""
    pkg_dir = FIXTURE_DIR / "relative_violation_pkg" / "pkg"
    test_file = pkg_dir / "_test_tc.py"
    test_file.write_text("""\
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .cli import render
""")
    try:
        with _with_src_root(pkg_dir):
            module_rel, ml, fl, tc, err = _parse_file_imports(test_file)
            assert err is None
            assert len(tc) == 1, f"Expected TYPE_CHECKING imports, got ml={ml}, fl={fl}, tc={tc}"
            assert tc[0] == (".cli", "render", 3)
            assert not fl
    finally:
        test_file.unlink()


def test_aliased_import_edge():
    """An `import x as y` / `from x import y as z` edge is captured."""
    pkg_dir = FIXTURE_DIR / "relative_violation_pkg" / "pkg"
    test_file = pkg_dir / "_test_alias.py"
    test_file.write_text("""\
import logging as log
from .cli import render as r
""")
    try:
        with _with_src_root(pkg_dir):
            module_rel, ml, fl, tc, err = _parse_file_imports(test_file)
            assert err is None
            assert ("logging", None, 1) in ml
            assert (".cli", "render", 2) in ml
    finally:
        test_file.unlink()


# ------------------------------------------------------------------
# Framework isolation tests
# ------------------------------------------------------------------


def test_framework_isolation_violation():
    """Domain layer importing httpx should be flagged."""
    layer_map = {
        "mdl": ("domain", frozenset({"domain"})),
    }
    ctx = _make_context("mdl", layer_map=layer_map)
    _check_framework_isolation(ctx, "httpx")
    assert len(ctx.result.violations) == 1
    v = ctx.result.violations[0]
    assert v.severity == Severity.ERROR
    assert v.rule == "framework-isolation"
    assert "httpx" in v.message


def test_framework_isolation_allowed_in_adapter():
    """Adapter layer importing httpx is not flagged."""
    layer_map = {
        "api": ("adapter", frozenset({"domain", "adapter"})),
    }
    ctx = _make_context("api", layer_map=layer_map)
    _check_framework_isolation(ctx, "httpx")
    assert len(ctx.result.violations) == 0


# ------------------------------------------------------------------
# Adapter independence tests
# ------------------------------------------------------------------


def test_adapter_independence_warns_on_cross_import():
    """Two different adapter groups importing from each other warns."""
    adapter_groups = {
        "api_mod": ("api_adapter", frozenset()),
        "auth_mod": ("auth_adapter", frozenset()),
    }
    result = AnalysisResult()
    ctx = _ImportCheckCtx(
        source_module_rel="api_mod",
        lineno=1,
        filepath="test.py",
        location="module-level",
        layer_map={},
        adapter_groups=adapter_groups,
        result=result,
    )
    _check_adapter_independence(ctx, "auth_mod")
    assert len(result.violations) == 1
    v = result.violations[0]
    assert v.severity == Severity.WARNING
    assert v.rule == "adapter-independence"


def test_adapter_independence_allows_declared_import():
    """An allowed cross-group import should not warn."""
    adapter_groups = {
        "api_mod": ("api_adapter", frozenset({"auth_adapter"})),
        "auth_mod": ("auth_adapter", frozenset()),
    }
    result = AnalysisResult()
    ctx = _ImportCheckCtx(
        source_module_rel="api_mod",
        lineno=1,
        filepath="test.py",
        location="module-level",
        layer_map={},
        adapter_groups=adapter_groups,
        result=result,
    )
    _check_adapter_independence(ctx, "auth_mod")
    assert len(result.violations) == 0


# ------------------------------------------------------------------
# Classification completeness tests
# ------------------------------------------------------------------


def test_unclassified_module_detected():
    """Modules not assigned to any layer produce errors."""
    result = _run_fixture_checks("unclassified_pkg")
    class_errors = [v for v in result.errors if v.rule == "unclassified-module"]
    assert any("unlisted" in v.message for v in class_errors), (
        f"Expected unclassified-module error naming 'unlisted', got {result.violations}"
    )
    assert all(v.severity == Severity.ERROR for v in class_errors)


def test_exact_classification_required_no_prefix_inheritance(tmp_path):
    """A leaf module must be classified exactly; a classified package prefix
    does not silently classify its children."""
    pkg_dir = tmp_path / "pkg"
    (pkg_dir / "util").mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "util" / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "util" / "deep.py").write_text("", encoding="utf-8")
    toml = tmp_path / "architecture.toml"
    toml.write_text(
        "[schema]\n"
        "version = 1\n\n"
        "[[layers]]\n"
        'name = "shared_pure"\n'
        'description = "pure"\n'
        'allowed_deps = ["shared_pure"]\n'
        'modules = ["util"]\n',
        encoding="utf-8",
    )
    toml_data = _load_toml(toml)
    layer_map = _build_layer_map(toml_data)
    config = _RunConfig(layer_map=layer_map, adapter_groups=_build_adapter_groups(toml_data))
    files = sorted(p for p in pkg_dir.rglob("*.py") if "__pycache__" not in str(p))
    with _with_src_root(pkg_dir):
        result = _run_checks(files, config)
    class_errors = [v for v in result.errors if v.rule == "unclassified-module"]
    messages = {v.message for v in class_errors}
    assert any("'util.deep'" in m for m in messages), (
        f"'util.deep' must be flagged unclassified, got {sorted(messages)}"
    )
    assert "Production module 'util' has no layer assignment" not in messages


def test_collect_production_modules_includes_all():
    """_collect_production_modules finds known fixture modules."""
    pkg = FIXTURE_DIR / "clean_pkg" / "pkg"
    with _with_src_root(pkg):
        modules = _collect_production_modules()
        assert "utils" in modules
        assert "models" in modules
        assert "services" in modules
        assert "contracts" in modules


# ------------------------------------------------------------------
# Syntax error and parse failure tests
# ------------------------------------------------------------------


def test_syntax_error_produces_parse_error():
    """Files with syntax errors should produce 'parse-error' violation."""
    result = _run_fixture_checks("syntax_error_pkg")
    parse_errors = [v for v in result.errors if v.rule == "parse-error"]
    assert len(parse_errors) == 1, f"Expected one parse error, got {result.violations}"
    assert "Syntax error" in parse_errors[0].message
    assert parse_errors[0].severity == Severity.ERROR
    assert parse_errors[0].file.endswith("syntax_error.py")


def test_syntax_error_parse_file_imports():
    """_parse_file_imports returns error string on syntax error."""
    error_file = FIXTURE_DIR / "syntax_error_pkg" / "pkg" / "syntax_error.py"
    pkg = FIXTURE_DIR / "syntax_error_pkg" / "pkg"
    with _with_src_root(pkg):
        module_rel, ml, fl, tc, err = _parse_file_imports(error_file)
        assert err is not None, "Expected parse error string"
        assert "Syntax error" in err


# ------------------------------------------------------------------
# Fail-closed tests
# ------------------------------------------------------------------


def test_parse_error_not_silent():
    """Parse errors produce violations, not silently empty results."""
    result = _run_fixture_checks("syntax_error_pkg")
    assert len(result.violations) > 0, "Expected at least one violation from syntax error"


def test_run_checks_fail_closed():
    """Verify _run_checks always produces a non-None result with files_checked set."""
    result = _run_fixture_checks("clean_pkg")
    assert result is not None
    assert result.files_checked > 0


def test_no_old_hardcoded_layers():
    """Verify the old LAYERS tuple no longer exists."""
    assert not hasattr(ca, "LAYERS"), "Old LAYERS tuple should be removed"


# ------------------------------------------------------------------
# CLI flag tests
# ------------------------------------------------------------------


def test_no_baseline_flag_works():
    """--no-baseline flag skips baseline loading."""
    args = ca._parse_args(["--no-baseline", "--json"])
    assert args["no_baseline"] is True
    assert args["json"] is True


def test_explain_flag():
    """--explain flag is parsed and exits."""
    with pytest.raises(SystemExit) as excinfo:
        toml_path = FIXTURE_DIR / "clean_pkg" / "architecture.toml"
        ca.main(["--explain", "--toml", str(toml_path)])
    assert excinfo.value.code == 0


# ------------------------------------------------------------------
# Absolute import violation tests
# ------------------------------------------------------------------


def test_absolute_import_across_layers():
    """Absolute import from application to presentation should be caught."""
    layer_map = {
        "svc": ("application", frozenset({"domain", "application"})),
        "ui.cli": ("presentation", frozenset({"domain", "application", "presentation"})),
    }
    ctx = _make_context("svc", layer_map=layer_map)
    _check_import_direction(ctx, "ui.cli")
    v = ctx.result.violations[0]
    assert v.rule == "import-direction"
    assert "presentation" in v.message


# ------------------------------------------------------------------
# Repository-relative identity tests
# ------------------------------------------------------------------


def test_violation_identities_are_repository_relative():
    """Violation file identities must be repo-relative, never absolute paths."""
    result = _run_fixture_checks("violation_pkg")
    for v in result.violations:
        if v.file == "<classification>":
            continue
        assert not v.file.startswith("/"), f"Absolute identity leaked: {v.file}"
        assert str(PROJECT_ROOT) not in v.file, f"Project root leaked: {v.file}"
        assert v.file.startswith("tests/fixtures/"), f"Not repo-relative: {v.file}"


def test_repo_relative_path_keeps_foreign_paths_unchanged():
    """Synthetic (non-repo) identities survive normalisation unchanged."""
    assert ca._repo_relative_path("src/perplexity_cli/api/models.py") == (
        "src/perplexity_cli/api/models.py"
    )
    assert ca._repo_relative_path("test:source:svc") == "test:source:svc"


# ------------------------------------------------------------------
# Baseline fail-closed tests
# ------------------------------------------------------------------


def _baseline_with(tmp_path: Path, payload: str) -> Path:
    """Write a baseline payload to a temp path and point the module at it."""
    baseline_path = tmp_path / ".architecture-baseline.json"
    baseline_path.write_text(payload, encoding="utf-8")
    return baseline_path


def test_missing_baseline_fails_closed(tmp_path, monkeypatch):
    """An absent baseline file raises BaselineError rather than degrading to empty."""
    monkeypatch.setattr(ca, "BASELINE_PATH", tmp_path / "does-not-exist.json")
    with pytest.raises(BaselineError):
        _load_baseline()


def test_malformed_baseline_fails_closed(tmp_path, monkeypatch):
    """Malformed baseline JSON raises BaselineError."""
    baseline_path = _baseline_with(tmp_path, "not valid json {{{")
    monkeypatch.setattr(ca, "BASELINE_PATH", baseline_path)
    with pytest.raises(BaselineError):
        _load_baseline()


def test_baseline_wrong_schema_version_fails_closed(tmp_path, monkeypatch):
    """An unsupported baseline schema version raises BaselineError."""
    baseline_path = _baseline_with(
        tmp_path, '{"version": 2, "accepted": [{"rule": "r", "file": "f", "message": "m"}]}'
    )
    monkeypatch.setattr(ca, "BASELINE_PATH", baseline_path)
    with pytest.raises(BaselineError):
        _load_baseline()


def test_baseline_entry_missing_fields_fails_closed(tmp_path, monkeypatch):
    """A baseline entry missing rule/file/message raises BaselineError."""
    baseline_path = _baseline_with(tmp_path, '{"version": 1, "accepted": [{"rule": "r"}]}')
    monkeypatch.setattr(ca, "BASELINE_PATH", baseline_path)
    with pytest.raises(BaselineError):
        _load_baseline()


def test_valid_baseline_loads_with_repo_relative_keys(tmp_path, monkeypatch):
    """A valid baseline loads and its absolute paths map to repo-relative keys."""
    import json

    payload = json.dumps(
        {
            "version": 1,
            "accepted": [
                {
                    "rule": "import-direction",
                    "file": f"{PROJECT_ROOT}/src/perplexity_cli/api/models.py:20",
                    "message": "m",
                }
            ],
        }
    )
    baseline_path = _baseline_with(tmp_path, payload)
    monkeypatch.setattr(ca, "BASELINE_PATH", baseline_path)
    baseline = _load_baseline()
    assert ("import-direction", "src/perplexity_cli/api/models.py:20", "m") in baseline


def test_main_fails_closed_on_malformed_baseline(tmp_path, monkeypatch):
    """Baseline filtering raises BaselineError when the baseline file is malformed."""
    baseline_path = _baseline_with(tmp_path, "{broken")
    monkeypatch.setattr(ca, "BASELINE_PATH", baseline_path)
    result = AnalysisResult(files_checked=1)
    with pytest.raises(BaselineError):
        ca._filter_with_baseline(result, {"no_baseline": False})


# ------------------------------------------------------------------
# Manifest validation tests
# ------------------------------------------------------------------


def test_manifest_validation_reports_schema_errors(tmp_path):
    """Architecture manifest schema/coverage errors are surfaced, not masked."""
    bad_toml = tmp_path / "bad.toml"
    bad_toml.write_text(
        "[schema]\n"
        "version = 1\n\n"
        "[[layers]]\n"
        'name = "adapter"\n'
        'description = "d"\n'
        'allowed_deps = ["bogus_layer"]\n'
        'modules = ["mod"]\n',
        encoding="utf-8",
    )
    errors = ca._validate_architecture_manifest(bad_toml, src_root=ca.SRC_ROOT)
    assert any("references unknown layer" in e for e in errors)


def test_main_exits_nonzero_on_invalid_manifest(tmp_path):
    """main() fails closed when the manifest does not validate."""
    bad_toml = tmp_path / "bad.toml"
    bad_toml.write_text(
        "[schema]\n"
        "version = 1\n\n"
        "[[layers]]\n"
        'name = "adapter"\n'
        'description = "d"\n'
        'allowed_deps = ["bogus_layer"]\n'
        'modules = ["mod"]\n',
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as excinfo:
        ca.main(["--toml", str(bad_toml)])
    assert excinfo.value.code != 0
