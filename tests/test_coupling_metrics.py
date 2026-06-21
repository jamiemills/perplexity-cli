"""Tests for coupling metric import resolution."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import scripts.check_coupling as coupling

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_module(src_root: Path, module: str, source: str) -> Path:
    path = src_root / f"{module.replace('.', '/')}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return path


def test_resolve_imported_module_prefers_concrete_module() -> None:
    known = {"api.models", "query_runner", "utils.file_handler"}

    assert coupling._resolve_imported_module("api.models", known) == "api.models"
    assert coupling._resolve_imported_module("api.models.QueryInput", known) == "api.models"
    assert coupling._resolve_imported_module("api", known) is None


def test_build_import_graph_does_not_create_synthetic_package_roots(
    tmp_path: Path, monkeypatch
) -> None:
    src_root = tmp_path / "src" / "perplexity_cli"
    query_runner = _write_module(
        src_root,
        "query_runner",
        "from perplexity_cli.api.models import QueryInput\n",
    )
    api_models = _write_module(src_root, "api.models", "class QueryInput:\n    pass\n")
    monkeypatch.setattr(coupling, "SRC_ROOT", src_root)

    efferent, afferent, abstractness = coupling._build_import_graph([query_runner, api_models])

    assert efferent["query_runner"] == {"api.models"}
    assert afferent["api.models"] == {"query_runner"}
    assert "api" not in afferent
    assert set(abstractness) == {"query_runner", "api.models"}


def test_flagged_metrics_excludes_dependency_free_leaf_modules() -> None:
    leaf = coupling.ModuleMetrics(module="domain.value", ca=5, ce=0)
    dependent = coupling.ModuleMetrics(module="service.flow", ca=5, ce=1)

    flagged = coupling._flagged_metrics([leaf, dependent], threshold=0.3)

    assert flagged == [dependent]


def test_format_json_uses_calibrated_flagged_count() -> None:
    leaf = coupling.ModuleMetrics(module="domain.value", ca=5, ce=0)
    dependent = coupling.ModuleMetrics(module="service.flow", ca=5, ce=1)

    output = coupling._format_json([leaf, dependent], threshold=0.3)

    assert '"flagged_count": 1' in output
    assert '"module": "service.flow"' in output
    assert '"module": "domain.value"' not in output


def test_check_coupling_max_flagged_budget_exits_by_budget() -> None:
    result_ok = subprocess.run(
        [sys.executable, "scripts/check_coupling.py", "--max-flagged", "24"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    result_fail = subprocess.run(
        [sys.executable, "scripts/check_coupling.py", "--max-flagged", "10"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result_ok.returncode == 0
    assert result_fail.returncode != 0
