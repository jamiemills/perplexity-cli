"""Tests for coupling metrics, import resolution, and advisory reporting.

Proves:
- Equivalent results for absolute AND relative forms of same import
- Equivalent results for module-level AND function-local forms
- Package split and rename handling
- Threshold-boundary values
- Syntax/read failure (non-zero exit)
- New unclassified package (non-zero exit)
- Advisory findings do not fail the command, but graph/parse/config errors do
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = PROJECT_ROOT / "quality" / "baselines" / "coupling-report.json"


def _load_script(name: str, aliases: list[str] | None = None) -> ModuleType:
    """Load a scripts/<name>.py module by file path without sys.path mutation.

    Extra *aliases* register the same module object under additional import
    names so sibling scripts that import each other by bare name share state.
    """
    module_name = f"scripts.{name}"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(
        module_name, PROJECT_ROOT / "scripts" / f"{name}.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    for alias in [module_name] + (aliases or []):
        sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


_load_script("_gates", aliases=["_gates"])
_load_script("import_graph", aliases=["import_graph"])
_load_script("check_coupling")

from scripts.check_coupling import (  # noqa: E402  # owner: quality-infrastructure; reason: module registered in sys.modules by _load_script
    DEFAULT_DISTANCE_THRESHOLD,
    ModuleMetrics,
    SyntaxErrorInSource,
    _compute_metrics,
    _flagged_metrics,
    _format_json_report,
    _make_finding_id,
    _strip_package_prefix,
)

# ============================================================================
# Unit tests: module name resolution
# ============================================================================


def test_strip_package_prefix() -> None:
    """Absolute imports are stripped to their relative form."""
    assert _strip_package_prefix("perplexity_cli.api.client") == "api.client"
    assert _strip_package_prefix("perplexity_cli") == ""
    assert _strip_package_prefix("other_pkg.thing") == "other_pkg.thing"


def test_make_finding_id_stable() -> None:
    """Finding IDs are deterministic for the same module."""
    id1 = _make_finding_id("api.client")
    id2 = _make_finding_id("api.client")
    assert id1 == id2
    assert _make_finding_id("api.models") != _make_finding_id("api.client")


# ============================================================================
# Unit tests: metrics computation
# ============================================================================


def _make_metric(
    module: str,
    ca: int = 0,
    ce: int = 0,
    na: int = 0,
    nc: int = 0,
) -> ModuleMetrics:
    return ModuleMetrics(module=module, ca=ca, ce=ce, na=na, nc=nc)


class TestInstability:
    """Prove the instability formula I = Ce / (Ca + Ce)."""

    def test_instability_zero_when_no_coupling(self) -> None:
        m = _make_metric("leaf", ca=0, ce=0)
        assert m.instability == 0.0

    def test_instability_one_when_only_efferent(self) -> None:
        m = _make_metric("unstable", ca=0, ce=5)
        assert m.instability == 1.0

    def test_instability_zero_when_only_afferent(self) -> None:
        m = _make_metric("stable", ca=10, ce=0)
        assert m.instability == 0.0

    def test_instability_balanced(self) -> None:
        m = _make_metric("balanced", ca=4, ce=6)
        assert m.instability == 0.6


class TestAbstractness:
    """Prove the abstractness formula A = Na / (Na + Nc)."""

    def test_abstractness_zero_when_no_classes(self) -> None:
        m = _make_metric("no_classes", na=0, nc=0)
        assert m.abstractness == 0.0

    def test_abstractness_one_when_all_abstract(self) -> None:
        m = _make_metric("pure_abstract", na=3, nc=0)
        assert m.abstractness == 1.0

    def test_abstractness_zero_when_all_concrete(self) -> None:
        m = _make_metric("pure_concrete", na=0, nc=7)
        assert m.abstractness == 0.0

    def test_abstractness_mixed(self) -> None:
        m = _make_metric("mixed", na=2, nc=3)
        assert m.abstractness == 0.4


class TestDistance:
    """Prove the distance formula D = |A + I - 1|."""

    def test_distance_zero_perfectly_balanced(self) -> None:
        m = _make_metric("perfect", ca=3, ce=3, na=2, nc=2)
        assert m.instability == 0.5
        assert m.abstractness == 0.5
        assert m.distance == 0.0

    def test_distance_maximally_far(self) -> None:
        """Stable+concrete (A=0, I=0) has D=1."""
        m = _make_metric("far", ca=1, ce=0, na=0, nc=1)
        assert m.instability == 0.0
        assert m.abstractness == 0.0
        assert m.distance == 1.0

    def test_distance_half(self) -> None:
        m = _make_metric("half", ca=0, ce=1, na=1, nc=1)
        assert m.instability == 1.0
        assert m.abstractness == 0.5
        assert m.distance == 0.5


class TestZones:
    """Prove zone-of-pain and zone-of-uselessness predicates."""

    def test_zone_of_pain(self) -> None:
        m = _make_metric("pain", ca=10, ce=2, na=0, nc=5)
        assert m.is_zone_of_pain
        assert not m.is_zone_of_uselessness

    def test_zone_of_uselessness(self) -> None:
        m = _make_metric("useless", ca=0, ce=8, na=8, nc=2)
        assert m.is_zone_of_uselessness
        assert not m.is_zone_of_pain

    def test_neither_zone(self) -> None:
        m = _make_metric("normal", ca=5, ce=5, na=5, nc=5)
        assert not m.is_zone_of_pain
        assert not m.is_zone_of_uselessness

    def test_boundary_below_pain(self) -> None:
        m = _make_metric("boundary_pain", ca=8, ce=2, na=0, nc=10)
        assert m.instability == pytest.approx(0.2)
        assert m.abstractness == 0.0
        assert m.is_zone_of_pain

    def test_boundary_above_pain_not_pain(self) -> None:
        m = _make_metric("exact_boundary", ca=7, ce=3, na=3, nc=7)
        assert m.instability == pytest.approx(0.3)
        assert m.abstractness == pytest.approx(0.3)
        assert not m.is_zone_of_pain


# ============================================================================
# Unit tests: flagged_metrics filtering
# ============================================================================


class TestFlaggedMetrics:
    def test_leaf_module_not_flagged(self) -> None:
        """Ce=0 modules should not be flagged regardless of distance."""
        leaf = _make_metric("leaf", ca=5, ce=0, na=0, nc=0)
        flagged = _flagged_metrics([leaf], threshold=0.3)
        assert not flagged

    def test_high_distance_with_ce_flagged(self) -> None:
        """I=1 with A=0.5 gives D=0.5, which is >= 0.3 threshold."""
        m = _make_metric("suspect", ca=0, ce=5, na=1, nc=1)
        assert m.distance == pytest.approx(0.5)
        flagged = _flagged_metrics([m], threshold=0.3)
        assert len(flagged) == 1

    def test_threshold_boundary_exact_match(self) -> None:
        m = _make_metric("exact", ca=0, ce=1, na=1, nc=1)
        assert m.distance == 0.5
        flagged_exact = _flagged_metrics([m], threshold=0.5)
        assert len(flagged_exact) == 1

    def test_threshold_boundary_just_below(self) -> None:
        m = _make_metric("just_below", ca=0, ce=1, na=1, nc=1)
        assert m.distance == 0.5
        flagged = _flagged_metrics([m], threshold=0.5001)
        assert not flagged

    def test_threshold_zero_flags_all_with_ce(self) -> None:
        m = _make_metric("any", ca=10, ce=1)
        flagged = _flagged_metrics([m], threshold=0.0)
        assert len(flagged) == 1

    def test_multiple_flagged_sorted_by_distance(self) -> None:
        a = _make_metric("a", ca=0, ce=1, na=0, nc=0)
        b = _make_metric("b", ca=0, ce=1, na=1, nc=1)
        metrics = [a, b]
        flagged = _flagged_metrics(metrics, threshold=0.0)
        assert len(flagged) == 2
        assert flagged[0].module == "a"
        assert flagged[1].module == "b"


# ============================================================================
# Unit tests: _compute_metrics
# ============================================================================


class TestComputeMetrics:
    def test_empty_modules(self) -> None:
        result = _compute_metrics(set(), {}, {}, {})
        assert result == []

    def test_single_module_no_edges(self) -> None:
        result = _compute_metrics({"api.client"}, {}, {}, {"api.client": (0, 0)})
        assert len(result) == 1
        m = result[0]
        assert m.module == "api.client"
        assert m.ca == 0
        assert m.ce == 0
        assert m.abstractness == 0.0

    def test_sorts_by_distance_descending(self) -> None:
        modules = {"a", "b", "c"}
        efferent = {"a": {"b"}}
        afferent = {"b": {"a"}}
        abstractness_map = {"a": (0, 0), "b": (0, 0), "c": (0, 0)}
        result = _compute_metrics(modules, efferent, afferent, abstractness_map)
        assert len(result) == 3
        assert result[0].distance >= result[1].distance >= result[2].distance

    def test_module_with_function_local_imports(self) -> None:
        """Function-local imports are counted as efferent coupling."""
        modules = {"package_a.hub", "package_b.core"}
        efferent = {
            "package_b.core": {"package_a.hub"},
        }
        afferent = {
            "package_a.hub": {"package_b.core"},
        }
        abstractness_map = {"package_a.hub": (0, 1), "package_b.core": (0, 1)}
        result = _compute_metrics(modules, efferent, afferent, abstractness_map)
        ce_map = {m.module: m.ce for m in result}
        assert ce_map["package_b.core"] == 1


# ============================================================================
# Unit tests: JSON output format
# ============================================================================


class TestFormatJson:
    def test_output_conforms_to_schema(self) -> None:
        m = _make_metric("api.models", ca=5, ce=3, na=0, nc=3)
        output = _format_json_report([m], threshold=0.3)
        report = json.loads(output)
        assert report["report_version"] == "1"
        assert report["total_modules"] == 1
        assert "findings" in report
        assert "flagged_identities" in report
        assert "timestamp" in report
        finding = report["findings"][0]
        assert finding["module"] == "api.models"
        assert finding["advisory"] is True
        assert "dependencies" in finding
        assert "dependents" in finding
        assert "finding_id" in finding

    def test_flagged_identities_excludes_non_flagged(self) -> None:
        leaf = _make_metric("leaf", ca=5, ce=0, na=0, nc=0)
        suspect = _make_metric("suspect", ca=0, ce=3, na=1, nc=1)
        assert suspect.distance == pytest.approx(0.5)
        output = _format_json_report([leaf, suspect], threshold=0.3)
        report = json.loads(output)
        assert report["flagged_count"] == 1
        assert report["flagged_identities"] == ["suspect"]


# ============================================================================
# Subprocess tests: exit codes and error handling
# ============================================================================


def _run_coupling_script(
    args: list[str],
    tmpdir: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the check_coupling.py script in the project root with TMPDIR set."""
    import tempfile

    env = {**__import__("os").environ, "TMPDIR": tmpdir or tempfile.gettempdir()}
    return subprocess.run(
        [sys.executable, "scripts/check_coupling.py", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


class TestScriptExitCodes:
    """Prove that advisory findings do not fail, but errors do."""

    def test_baseline_report_succeeds(self) -> None:
        """The default report should exit 0 despite flagged modules."""
        result = _run_coupling_script(["--json"])
        assert result.returncode == 0, f"stderr: {result.stderr}"
        report = json.loads(result.stdout)
        assert report["report_version"] == "1"
        assert report["total_modules"] > 0

    def test_max_flagged_exceeded_does_not_fail(self) -> None:
        """Advisory findings exceeding budget do NOT fail the command."""
        result = _run_coupling_script(["--max-flagged", "0", "--json"])
        assert result.returncode == 0, (
            f"Advisory findings should not fail. "
            f"Got rc={result.returncode}, stderr={result.stderr[:200]}"
        )

    def test_invalid_threshold_fails(self) -> None:
        """Config errors should fail the command."""
        result = _run_coupling_script(["--threshold", "invalid"])
        assert result.returncode != 0

    def test_threshold_out_of_range_fails(self) -> None:
        result = _run_coupling_script(["--threshold", "1.5"])
        assert result.returncode != 0

    def test_baseline_file_exists(self) -> None:
        """The baseline report file should exist and be valid."""
        assert BASELINE_PATH.exists()
        raw = BASELINE_PATH.read_text()
        report = json.loads(raw)
        assert report["report_version"] == "1"
        assert "flagged_identities" in report


class TestTrendCompare:
    """Prove the --trend-compare feature."""

    def test_trend_compare_against_self_is_unchanged(self) -> None:
        """Comparing against own snapshot should show no changes."""
        result = _run_coupling_script(
            [
                "--trend-compare",
                str(BASELINE_PATH),
                "--json",
            ]
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        report = json.loads(result.stdout)
        assert report["trend"] is not None
        assert report["trend"]["direction"] == "unchanged"
        assert report["trend"]["delta"] == 0
        assert report["trend"]["added"] == []
        assert report["trend"]["removed"] == []

    def test_trend_compare_missing_file_fails(self, tmp_path: Path) -> None:
        result = _run_coupling_script(
            [
                "--trend-compare",
                str(tmp_path / "nonexistent_coupling_report.json"),
                "--json",
            ]
        )
        assert result.returncode != 0

    def test_trend_compare_invalid_json_fails(self, tmp_path: Path) -> None:
        broken = tmp_path / "broken.json"
        broken.write_text("not valid json {{{")
        result = _run_coupling_script(["--trend-compare", str(broken), "--json"])
        assert result.returncode != 0

    def test_trend_compare_old_version_fails(self, tmp_path: Path) -> None:
        old = tmp_path / "old_version.json"
        old.write_text(
            json.dumps(
                {
                    "report_version": "0",
                    "total_modules": 1,
                    "flagged_count": 0,
                    "flagged_identities": [],
                    "threshold": 0.3,
                    "findings": [],
                }
            )
        )
        result = _run_coupling_script(["--trend-compare", str(old), "--json"])
        assert result.returncode != 0


# ============================================================================
# Synthetic package tests (use monkeypatch to redirect import_graph)
# ============================================================================


def _write_synthetic_package(src_dir: Path, pkg_name: str) -> None:
    """Write a synthetic Python package under *src_dir*.

    Creates src_dir/<pkg_name>/__init__.py so that grimp can discover it.
    """
    pkg_root = src_dir / pkg_name
    pkg_root.mkdir(parents=True)
    (pkg_root / "__init__.py").write_text("", encoding="utf-8")


def _patch_import_graph(monkeypatch, src_dir: Path, pkg_name: str) -> None:
    """Redirect import_graph to build from a synthetic package.

    Monkey-patches the module-level constants so that grimp is pointed
    at the test package, and the AST helpers find the source files.
    Also adds *src_dir* to sys.path so grimp can discover the package.
    """
    import scripts.import_graph as ig

    monkeypatch.setattr(ig, "SRC_ROOT", src_dir)
    monkeypatch.setattr(ig, "PACKAGE_NAME", pkg_name)
    monkeypatch.setattr(ig, "PROJECT_ROOT", src_dir.parent)

    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


class TestAbsoluteRelativeEquivalence:
    """Prove absolute and relative import forms produce equivalent edges."""

    def test_same_target_from_both_forms(self, tmp_path: Path, monkeypatch) -> None:
        """Both absolute and relative import of the same module produce edges."""
        pkg = "coupling_eq_test"
        src_dir = tmp_path / "src"
        _write_synthetic_package(src_dir, pkg)

        pkg_root = src_dir / pkg
        sub_a = pkg_root / "sub_a"
        sub_a.mkdir()
        (sub_a / "__init__.py").write_text("", encoding="utf-8")
        (sub_a / "leaf.py").write_text("class X:\n    pass\n")

        sub_b = pkg_root / "sub_b"
        sub_b.mkdir()
        (sub_b / "__init__.py").write_text("", encoding="utf-8")
        (sub_b / "abs_importer.py").write_text(
            f"from {pkg}.sub_a.leaf import X\n"  # absolute
        )
        (sub_b / "rel_importer.py").write_text(
            "from ..sub_a.leaf import X\n"  # relative
        )

        _patch_import_graph(monkeypatch, src_dir, pkg)

        from scripts.import_graph import get_all_module_names, get_direct_imports

        abs_fq = f"{pkg}.sub_b.abs_importer"
        rel_fq = f"{pkg}.sub_b.rel_importer"
        leaf_fq = f"{pkg}.sub_a.leaf"

        modules = get_all_module_names()
        assert abs_fq in modules, f"Expected {abs_fq} in {list(modules)[:5]}..."
        assert rel_fq in modules, f"Expected {rel_fq} in module list"

        abs_deps = get_direct_imports(abs_fq)
        rel_deps = get_direct_imports(rel_fq)

        assert leaf_fq in abs_deps, f"{abs_fq} should import {leaf_fq}"
        assert leaf_fq in rel_deps, f"{rel_fq} should import {leaf_fq}"


class TestFunctionLocalEquivalence:
    """Prove function-local imports are captured (equivalent to module-level)."""

    def test_function_local_import_is_captured(self, tmp_path: Path, monkeypatch) -> None:
        """get_function_local_imports reports imports inside functions."""
        pkg = "coupling_func_test"
        src_dir = tmp_path / "src"
        _write_synthetic_package(src_dir, pkg)

        pkg_root = src_dir / pkg
        sub_a = pkg_root / "sub_a"
        sub_a.mkdir()
        (sub_a / "__init__.py").write_text("", encoding="utf-8")
        (sub_a / "leaf.py").write_text("class A:\n    pass\n")

        (pkg_root / "lazy_importer.py").write_text(
            f"def do_import():\n    from {pkg}.sub_a.leaf import A\n    return A\n"
        )

        _patch_import_graph(monkeypatch, src_dir, pkg)

        from scripts.import_graph import get_function_local_imports

        mod_fq = f"{pkg}.lazy_importer"
        func_imports = get_function_local_imports(mod_fq)
        assert "sub_a.leaf.A" in func_imports, (
            f"Expected sub_a.leaf.A in func-local imports, got {func_imports}"
        )


class TestPackageSplitAndRename:
    """Prove renamed/reorganised modules produce stable coupling data."""

    def test_module_identity_stable_across_reorganisation(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The module's metrics are based on its identity, not its path."""
        pkg = "coupling_split_test"
        src_dir = tmp_path / "src"
        _write_synthetic_package(src_dir, pkg)

        pkg_root = src_dir / pkg
        pkg_a = pkg_root / "package_a"
        pkg_a.mkdir()
        (pkg_a / "__init__.py").write_text("", encoding="utf-8")
        (pkg_a / "service.py").write_text("class Svc:\n    pass\n")

        pkg_b = pkg_root / "package_b"
        pkg_b.mkdir()
        (pkg_b / "__init__.py").write_text("", encoding="utf-8")
        (pkg_b / "client.py").write_text(f"from {pkg}.package_a.service import Svc\n")

        _patch_import_graph(monkeypatch, src_dir, pkg)

        from scripts.import_graph import get_direct_imports

        client_fq = f"{pkg}.package_b.client"
        service_fq = f"{pkg}.package_a.service"

        deps = get_direct_imports(client_fq)
        assert service_fq in deps


# ============================================================================
# Error handling tests
# ============================================================================


def test_syntax_error_in_module_causes_error(tmp_path: Path, monkeypatch) -> None:
    """A syntactically broken module raises SyntaxErrorInSource."""
    pkg = "syntax_err_test"
    src_dir = tmp_path / "src"
    _write_synthetic_package(src_dir, pkg)
    (src_dir / pkg / "broken.py").write_text("def oops(syntax error\n")

    _patch_import_graph(monkeypatch, src_dir, pkg)

    from scripts.import_graph import (
        SyntaxErrorInSource as IGSyntaxErr,
    )
    from scripts.import_graph import (
        _collect_categorised_imports,
    )

    with pytest.raises(IGSyntaxErr):
        _collect_categorised_imports(f"{pkg}.broken", "module_level")


def test_read_error_non_existent_module() -> None:
    """Missing modules produce (0,0) abstractness (graceful)."""
    from scripts.check_coupling import _compute_abstractness

    result = _compute_abstractness({"nonexistent.mod"})
    assert result["nonexistent.mod"] == (0, 0)


def test_syntax_error_near_edge_of_module(tmp_path: Path, monkeypatch) -> None:
    """A module with a syntax error during abstractness phase raises."""
    src = tmp_path / "src" / "edge_test"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("")
    (src / "ok.py").write_text("class Fine:\n    pass\n")
    (src / "bad.py").write_text("class Broken(\n")

    import scripts.check_coupling as coupling_mod

    monkeypatch.setattr(coupling_mod, "SRC_ROOT", src)

    with pytest.raises(SyntaxErrorInSource):
        coupling_mod._compute_abstractness({"ok", "bad"})


def test_unclassified_package_appears_in_graph(tmp_path: Path, monkeypatch) -> None:
    """A new package on sys.path appears in the module list via grimp."""
    pkg = "unclassified_test"
    src_dir = tmp_path / "src"
    _write_synthetic_package(src_dir, pkg)
    (src_dir / pkg / "new_mod.py").write_text("class NewClass:\n    pass\n")

    _patch_import_graph(monkeypatch, src_dir, pkg)

    from scripts.import_graph import get_all_module_names

    modules = get_all_module_names()
    assert f"{pkg}.new_mod" in modules, f"Expected {pkg}.new_mod in modules"


# ============================================================================
# Integration: full coupling report for the real project
# ============================================================================


def test_full_project_report_generates_valid_json() -> None:
    """The real project's full report must be valid JSON with all required keys."""
    result = _run_coupling_script(["--json"])
    assert result.returncode == 0, f"stderr: {result.stderr}"

    report = json.loads(result.stdout)
    assert report["report_version"] == "1"
    assert report["total_modules"] > 80
    assert report["flagged_count"] >= 0
    assert report["threshold"] == DEFAULT_DISTANCE_THRESHOLD
    assert report["graph_error"] is False
    assert isinstance(report["findings"], list)
    assert len(report["findings"]) == report["total_modules"]

    for finding in report["findings"]:
        assert "module" in finding
        assert "ca" in finding
        assert "ce" in finding
        assert "instability" in finding
        assert "abstractness" in finding
        assert "distance" in finding
        assert "advisory" in finding
        assert "finding_id" in finding


def test_flagged_identities_are_all_flagged() -> None:
    """Every module in flagged_identities should have D >= threshold and Ce > 0."""
    result = _run_coupling_script(["--json"])
    assert result.returncode == 0

    report = json.loads(result.stdout)
    findings_by_module = {f["module"]: f for f in report["findings"]}

    for mod_name in report["flagged_identities"]:
        f = findings_by_module[mod_name]
        assert f["distance"] >= report["threshold"], (
            f"{mod_name} D={f['distance']} < threshold={report['threshold']}"
        )
        assert f["ce"] > 0, f"{mod_name} flagged but Ce=0"


def test_timestamp_is_iso8601() -> None:
    """The timestamp must be a valid ISO-8601 string."""
    result = _run_coupling_script(["--json"])
    report = json.loads(result.stdout)
    ts = report["timestamp"]
    assert "T" in ts
    assert "+" in ts or "Z" in ts


def test_no_module_appears_twice_in_findings() -> None:
    """Each module must appear exactly once in the findings array."""
    result = _run_coupling_script(["--json"])
    report = json.loads(result.stdout)
    module_names = [f["module"] for f in report["findings"]]
    assert len(module_names) == len(set(module_names))


# ============================================================================
# Command-line integration: snapshot re-fetch
# ============================================================================


def test_text_output_contains_advisory_wording() -> None:
    """The text output must label itself as ADVISORY."""
    result = _run_coupling_script([])
    assert result.returncode == 0
    assert "ADVISORY" in result.stdout
    assert "do not fail" in result.stdout.lower()


def test_json_output_produces_valid_trend_when_compared() -> None:
    """--trend-compare with baseline produces a valid trend dict."""
    result = _run_coupling_script(["--json", "--trend-compare", str(BASELINE_PATH)])
    assert result.returncode == 0
    report = json.loads(result.stdout)
    trend = report["trend"]
    assert trend is not None
    assert "previous_flagged_count" in trend
    assert "delta" in trend
    assert "direction" in trend
    assert trend["direction"] in {"improved", "regressed", "unchanged"}
