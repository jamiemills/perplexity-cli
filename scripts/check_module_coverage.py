"""Check that every module meets the per-module coverage threshold.

Reads the JSON report produced by ``pytest --cov --cov-report=json``
(default output: ``coverage.json``) and exits non-zero if any module
falls below the required minimum.

This checker is the sole conventional coverage authority; ``diff-cover``
remains the only changed-line coverage engine.

The checker performs full coverage-integrity validation:

* Independently enumerates ``src/perplexity_cli/**/*.py`` via ``Path.glob()``.
* Requires every executable module to have a coverage.json report entry.
* AST-classifies modules: a module may be absent from coverage only if
  it is demonstrably inert (empty, docstring-only, or solely declarative
  Protocol interfaces).  Imports, constant assignments, and concrete
  method bodies all execute at import time and can raise, so modules
  containing them must be present.
* Rejects duplicate entries, outside-root paths, omitted executable
  modules, and unexpected entries.
* Fails closed when branch coverage is not enabled or branch data is
  missing from the report.
* Rejects non-numeric, NaN, and infinity coverage values.

Usage::

    uv run python scripts/check_module_coverage.py [--min-coverage 85] [--report coverage.json]
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)
if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))
from scripts._gates import (  # noqa: E402  # owner: quality-infrastructure; reason: package-relative import after repo-root setup
    load_gates,
)

_gates = load_gates()
DEFAULT_MIN_COVERAGE = _gates.get_int("MIN_COVERAGE", 85)
DEFAULT_REPORT = "coverage.json"
SRC_ROOT = Path("src/perplexity_cli").resolve()


@dataclass(frozen=True, slots=True)
class _ValidationConfig:
    min_coverage: float
    branch_enabled: bool


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify per-module test coverage meets the minimum threshold.",
    )
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=DEFAULT_MIN_COVERAGE,
        help=f"Minimum coverage percentage per module (default: {DEFAULT_MIN_COVERAGE})",
    )
    parser.add_argument(
        "--report",
        type=str,
        default=DEFAULT_REPORT,
        help=f"Path to coverage JSON report (default: {DEFAULT_REPORT})",
    )
    return parser.parse_args()


def _enumerate_source_modules(src_root: Path) -> dict[str, str]:
    """Enumerate all Python modules under *src_root*, returning {relpath: classification}.

    Paths are relative to *src_root*. They do **not** include a ``src/``
    prefix; callers that compare against coverage JSON keys (which use
    ``src/perplexity_cli/...``) must strip the project-relative prefix.
    """
    modules: dict[str, str] = {}
    for py_file in sorted(src_root.glob("**/*.py")):
        rel = str(py_file.relative_to(src_root))
        modules[rel] = _classify_module(py_file)
    return modules


def _strip_src_prefix(filepath: str) -> str:
    """Strip the ``src/perplexity_cli/`` prefix from a report filepath."""
    for prefix in ("src/perplexity_cli/", "src/"):
        if filepath.startswith(prefix):
            return filepath[len(prefix) :]
    return filepath


def _classify_module(path: Path) -> str:
    """Classify a Python file as empty, docstring, re-export, or executable."""
    if path.stat().st_size == 0:
        return "empty"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "executable"
    return _classify_source(text, str(path))


def _try_parse(source: str, filename: str) -> ast.Module | None:
    try:
        return ast.parse(source, filename=filename)
    except SyntaxError:
        return None


def _classify_source(source: str, filename: str = "<string>") -> str:
    tree = _try_parse(source, filename)
    if tree is None:
        return "executable"
    return _classify_from_tree(tree)


def _classify_from_tree(tree: ast.Module) -> str:
    if not tree.body:
        return "empty"
    if len(tree.body) == 1 and _is_docstring_node(tree.body[0]):
        return "docstring"
    if _is_inert_module(tree.body):
        return "re-export"
    return "executable"


def _is_inert_module(body: list[ast.stmt]) -> bool:
    """Return True if *body* contains only demonstrably inert statements."""
    return all(_is_docstring_node(n) or _is_declarative_protocol_classdef(n) for n in body)


def _is_declarative_protocol_classdef(node: ast.AST) -> bool:
    """Return True for a ``class X(Protocol):`` with no executable statements.

    A Protocol subclass is inert only while its body stays purely declarative
    (docstrings, annotations, ``pass``, and ``...`` stubs).  Concrete method
    bodies, decorators, and imports execute at import time, so classes or
    modules containing them must appear in the coverage report.
    """
    if not isinstance(node, ast.ClassDef):
        return False
    if not any(_is_protocol_base(base) for base in node.bases):
        return False
    if node.decorator_list:
        return False
    return _is_declarative_body(node.body)


def _is_declarative_body(body: list[ast.stmt]) -> bool:
    """Return True if *body* contains no executable statements."""
    return all(_is_declarative_statement(n) for n in body)


def _is_declarative_statement(node: ast.AST) -> bool:
    """Return True for a docstring, annotation, stub, or declarative def/class."""
    if _is_inert_leaf(node):
        return True
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return _is_declarative_definition(node)
    return False


def _is_inert_leaf(node: ast.AST) -> bool:
    """Return True for a docstring, bare annotation, pass, or ellipsis statement."""
    return (
        _is_docstring_node(node)
        or _is_ellipsis_node(node)
        or _is_pass_node(node)
        or _is_annotation_stmt(node)
    )


def _is_declarative_definition(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> bool:
    """Return True for an unadorned def/class whose body is declarative."""
    if node.decorator_list:
        return False
    return _is_declarative_body(node.body)


def _is_docstring_node(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_ellipsis_node(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and node.value.value is Ellipsis
    )


def _is_pass_node(node: ast.AST) -> bool:
    return isinstance(node, ast.Pass)


def _is_annotation_stmt(node: ast.AST) -> bool:
    """Return True for a bare ``NAME: type`` annotation, which is never evaluated."""
    return isinstance(node, ast.AnnAssign) and node.value is None


def _is_protocol_base(base: ast.expr) -> bool:
    """Return True if a base expression references ``Protocol``."""
    if isinstance(base, ast.Name):
        return base.id == "Protocol"
    if isinstance(base, ast.Attribute):
        return base.attr == "Protocol"
    return False


def _load_report(path: str) -> dict[str, Any]:
    report_path = Path(path)
    if not report_path.is_file():
        print(f"Coverage report not found: {path}", file=sys.stderr)
        print("Run pytest with --cov --cov-report=json first.", file=sys.stderr)
        sys.exit(2)
    try:
        with report_path.open(encoding="utf-8") as f:
            report_payload: Any = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Coverage report is not valid JSON: {path} ({exc})", file=sys.stderr)
        sys.exit(2)
    if not isinstance(report_payload, dict):
        print(f"Coverage report must be a JSON object: {path}", file=sys.stderr)
        sys.exit(2)
    return cast("dict[str, Any]", report_payload)


def _format_module_name(filepath: Any) -> str:
    """Format a file path as a module name for display."""
    return str(filepath).replace("src/perplexity_cli/", "").replace(".py", "")


def _check_module_entry(
    filepath: Any, entry: Any, min_coverage: float
) -> tuple[str, float, int, int] | None:
    """Check a single module entry against the coverage threshold."""
    entry_dict = _entry_as_dict(entry)
    summary = _summary_from_entry(entry_dict)
    pct = summary.get("percent_covered", 0.0)
    if not isinstance(pct, (int, float)) or pct >= min_coverage:
        return None
    module = _format_module_name(filepath)
    stmts = summary.get("num_statements", 0)
    miss = summary.get("missing_lines", 0)
    return (module, float(pct), int(stmts), int(miss))


def _check_modules(
    coverage_data: dict[str, Any], min_coverage: float
) -> list[tuple[str, float, int, int]]:
    """Return a list of (module, percentage, statements, missing) for failing modules."""
    files: object = coverage_data.get("files")
    if not isinstance(files, dict) or not files:
        msg = "Coverage report contains no module entries."
        raise ValueError(msg)
    typed_files = cast(dict[str, Any], files)
    failures: list[tuple[str, float, int, int]] = []
    for filepath, entry in sorted(typed_files.items()):
        result = _check_module_entry(filepath, entry, min_coverage)
        if result is not None:
            failures.append(result)
    return failures


# ---------------------------------------------------------------------------
# Full validation
# ---------------------------------------------------------------------------


def _entry_as_dict(entry: Any) -> dict[str, Any]:
    return cast(dict[str, Any], entry) if isinstance(entry, dict) else {}


def _summary_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
    summary = entry.get("summary")
    return cast(dict[str, Any], summary) if isinstance(summary, dict) else {}


def _is_python_source(fp: str) -> bool:
    return fp.endswith(".py") and not fp.endswith(".pyc")


def _validate_entry_path(fp: str, source_modules: dict[str, str], errors: list[str]) -> bool:
    if not _is_python_source(fp):
        errors.append(f"Non-Python file in report: {fp}")
        return False
    normalised = _strip_src_prefix(fp)
    if normalised == fp and "/" in fp:
        errors.append(f"Entry outside source root: {fp}")
        return False
    return _module_known(fp, normalised, source_modules) or _add_missing_error(fp, errors)


def _add_missing_error(fp: str, errors: list[str]) -> bool:
    errors.append(f"Report entry missing from source tree: {fp}")
    return False


def _module_known(fp: str, normalised: str, source_modules: dict[str, str]) -> bool:
    return fp in source_modules or normalised in source_modules


def _validate_entry_summary(
    fp: str,
    summary: dict[str, Any],
    min_coverage: float,
    errors: list[str],
) -> None:
    pct = summary.get("percent_covered")
    if not isinstance(pct, (int, float)):
        errors.append(f"Non-numeric percent_covered for: {fp} (got {type(pct).__name__})")
        return
    if math.isnan(float(pct)) or math.isinf(float(pct)):
        errors.append(f"Invalid percent_covered for: {fp} (got {pct})")
        return
    if pct < min_coverage:
        stmts = summary.get("num_statements", 0)
        miss = summary.get("missing_lines", 0)
        errors.append(
            f"Coverage below {min_coverage}%: {fp} ({pct:.1f}%, "
            f"{int(miss)} of {int(stmts)} statements missing)"
        )


def _validate_entry_branches(
    fp: str,
    summary: dict[str, Any],
    errors: list[str],
) -> None:
    num_branches = summary.get("num_branches")
    num_partial = summary.get("num_partial_branches")
    if num_branches is None or num_partial is None:
        errors.append(f"Missing branch data for: {fp}")
        return
    if not isinstance(num_branches, (int, float)):
        errors.append(f"Non-numeric num_branches for: {fp}")
    if not isinstance(num_partial, (int, float)):
        errors.append(f"Non-numeric num_partial_branches for: {fp}")


def _check_duplicate(fp: str, seen: set[str], errors: list[str]) -> bool:
    """Record a report entry, returning True if its source module was already seen.

    Entries are keyed by their source-root-relative path so two report keys
    mapping to the same module (for example ``src/perplexity_cli/a.py`` and
    ``a.py``) are rejected as duplicates.
    """
    normalised = _strip_src_prefix(fp)
    if normalised in seen:
        errors.append(f"Duplicate entry for source module: {normalised}")
        return True
    seen.add(normalised)
    return False


def _process_report_entries(
    files: dict[str, Any],
    source_modules: dict[str, str],
    config: _ValidationConfig,
    errors: list[str],
) -> set[str]:
    report_paths: set[str] = set()
    seen: set[str] = set()
    for filepath, entry in sorted(files.items()):
        fp = str(filepath)
        if _check_duplicate(fp, seen, errors):
            continue
        if not _validate_entry_path(fp, source_modules, errors):
            continue
        report_paths.add(_strip_src_prefix(fp))
        _validate_report_entry(fp, entry, config, errors)
    return report_paths


def _validate_report_entry(
    fp: str,
    entry: Any,
    config: _ValidationConfig,
    errors: list[str],
) -> None:
    entry_dict = _entry_as_dict(entry)
    summary = _summary_from_entry(entry_dict)
    _validate_entry_summary(fp, summary, config.min_coverage, errors)
    if config.branch_enabled:
        _validate_entry_branches(fp, summary, errors)


def _check_missing_executable(
    source_modules: dict[str, str],
    report_paths: set[str],
    errors: list[str],
) -> None:
    executable_source = {k for k, v in source_modules.items() if v == "executable"}
    for mod_path in sorted(executable_source - report_paths):
        errors.append(f"Source module missing from coverage report: {mod_path}")


def _log_missing_statement_free(
    source_modules: dict[str, str],
    report_paths: set[str],
) -> None:
    statement_free_source = {k for k, v in source_modules.items() if v != "executable"}
    for mod_path in sorted(statement_free_source - report_paths):
        logger.info("Statement-free module not in report (allowed): %s", mod_path)


def _report_files(coverage_data: Any, errors: list[str]) -> dict[str, Any] | None:
    """Extract the files map, recording fail-closed errors on malformed input."""
    if not isinstance(coverage_data, dict):
        errors.append("Coverage report must be a JSON object.")
        return None
    coverage_map = cast("dict[str, Any]", coverage_data)
    files: object = coverage_map.get("files")
    if not isinstance(files, dict) or not files:
        errors.append("Coverage report contains no module entries.")
        return None
    return cast("dict[Any, Any]", files)


def _report_config(coverage_data: dict[str, Any], min_coverage: float) -> _ValidationConfig:
    meta: object = coverage_data.get("meta")
    meta_dict = cast(dict[str, Any], meta) if isinstance(meta, dict) else {}
    return _ValidationConfig(
        min_coverage=min_coverage,
        branch_enabled=bool(meta_dict.get("branch_coverage", False)),
    )


def _validate_totals(coverage_data: dict[str, Any], errors: list[str]) -> None:
    totals: object = coverage_data.get("totals")
    if totals is None:
        return
    if not isinstance(totals, dict):
        errors.append("Coverage report 'totals' must be an object.")
        return
    typed_totals = cast(dict[str, Any], totals)
    pct = typed_totals.get("percent_covered")
    if pct is not None and not isinstance(pct, (int, float)):
        errors.append("Non-numeric overall percent_covered in report totals.")


def validate_report(
    coverage_data: Any,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
    src_root: Path | None = None,
) -> list[str]:
    """Full validation of a coverage.json report against the source tree."""
    errors: list[str] = []
    files = _report_files(coverage_data, errors)
    if files is None:
        return errors
    config = _report_config(coverage_data, min_coverage)
    _validate_totals(coverage_data, errors)
    source_modules = _enumerate_source_modules(src_root or SRC_ROOT)
    report_paths = _process_report_entries(files, source_modules, config, errors)
    _check_missing_executable(source_modules, report_paths, errors)
    _log_missing_statement_free(source_modules, report_paths)
    return errors


def _check_branch_data_present(coverage_data: dict[str, Any], errors: list[str]) -> None:
    """Fail if the report was generated without branch coverage."""
    meta: object = coverage_data.get("meta")
    meta_dict = cast(dict[str, Any], meta) if isinstance(meta, dict) else {}
    if not meta_dict.get("branch_coverage", False):
        errors.append(
            "Coverage report missing branch data. "
            "Run pytest with --cov-branch or set branch=true in [tool.coverage.run]."
        )


def _print_validation_errors(errors: list[str]) -> None:
    print(f"Coverage validation FAILED: {len(errors)} error(s):\n", file=sys.stderr)
    for error in errors:
        print(f"  {error}", file=sys.stderr)


def _print_success(coverage_data: dict[str, Any], min_coverage: float) -> None:
    totals: object = coverage_data.get("totals", {})
    if isinstance(totals, dict):
        typed_totals = cast(dict[str, Any], totals)
        raw_pct = typed_totals.get("percent_covered", 0.0)
        total_pct = float(raw_pct) if isinstance(raw_pct, (int, float)) else 0.0
    else:
        total_pct = 0.0
    file_count = len(coverage_data.get("files", {}))
    print(
        f"Per-module coverage check passed: all {file_count} modules "
        f">= {min_coverage}% (overall: {total_pct:.1f}%)"
    )


def main() -> None:
    args = _parse_args()
    coverage_report = _load_report(args.report)
    errors = validate_report(coverage_report, min_coverage=args.min_coverage)
    _check_branch_data_present(coverage_report, errors)
    if errors:
        _print_validation_errors(errors)
        sys.exit(1)
    _print_success(coverage_report, args.min_coverage)
    sys.exit(0)


if __name__ == "__main__":
    main()

# Exported for test use (tests import these directly).
__all__ = [
    "_check_branch_data_present",
    "_check_duplicate",
    "_check_modules",
    "_classify_module",
    "_classify_source",
    "_enumerate_source_modules",
    "_format_module_name",
    "_load_report",
    "main",
    "validate_report",
]
