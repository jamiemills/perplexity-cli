"""Check that every module meets the per-module coverage threshold.

Reads the JSON report produced by ``pytest --cov --cov-report=json``
(default output: ``coverage.json``) and exits non-zero if any module
falls below the required minimum.

The checker performs full coverage-integrity validation:

* Independently enumerates ``src/perplexity_cli/**/*.py`` via ``Path.glob()``.
* Requires every executable module to have a coverage.json report entry.
* AST-classifies ``__init__.py`` files: a module may be absent from
  coverage only if it contains no executable statements (docstring,
  imports, ``__all__``, and constants are permitted).
* Rejects duplicate entries, outside-root paths, omitted executable
  modules, and unexpected entries.
* Validates that branch data is present in the report.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gates import (  # noqa: E402  # owner: quality-infrastructure; reason: repo-relative import after sys.path setup
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
    return _classify_source(text, str(path), is_init=path.name == "__init__.py")


def _try_parse(source: str, filename: str) -> ast.Module | None:
    try:
        return ast.parse(source, filename=filename)
    except SyntaxError:
        return None


def _classify_source(  # nosemgrep: boolean-flag-argument  # owner: quality-infrastructure; reason: is_init classifies __init__.py vs regular module, not a feature toggle.
    source: str, filename: str = "<string>", is_init: bool = False
) -> str:
    tree = _try_parse(source, filename)
    if tree is None:
        return "executable"
    return _classify_from_tree(tree, is_init=is_init)


def _classify_from_tree(  # nosemgrep: boolean-flag-argument  # owner: quality-infrastructure; reason: is_init classifies __init__.py vs regular module, not a feature toggle.
    tree: ast.Module, is_init: bool = False
) -> str:
    if not tree.body:
        return "empty"
    if len(tree.body) == 1 and _is_docstring_node(tree.body[0]):
        return "docstring"
    if _is_statement_free(tree.body, is_init):
        return "re-export"
    return "executable"


def _is_statement_free(  # nosemgrep: boolean-flag-argument  # owner: quality-infrastructure; reason: is_init classifies __init__.py vs regular module, not a feature toggle.
    body: list[ast.stmt], is_init: bool
) -> bool:
    """Return True if *body* contains no executable statements."""
    if _all_import_or_docstring(body):
        return True
    return is_init and _all_init_stub(body)


def _all_import_or_docstring(body: list[ast.stmt]) -> bool:
    return all(
        _is_docstring_node(n) or _is_import_node(n) or _is_protocol_classdef(n) for n in body
    )


def _all_init_stub(body: list[ast.stmt]) -> bool:
    """Return True if every node is a docstring, import, or constant assignment."""
    return all(_is_docstring_node(n) or _is_import_node(n) or _is_constant_assign(n) for n in body)


def _is_constant_assign(node: ast.AST) -> bool:
    """Return True for simple ``NAME = value`` or ``NAME: type = value`` assignments."""
    if isinstance(node, ast.Assign):
        return all(isinstance(t, ast.Name) for t in node.targets)
    if isinstance(node, ast.AnnAssign):
        return isinstance(node.target, ast.Name)
    return False


def _is_docstring_node(node: ast.AST) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)


def _is_import_node(node: ast.AST) -> bool:
    return isinstance(node, (ast.Import, ast.ImportFrom))


def _is_protocol_classdef(node: ast.AST) -> bool:
    """Return True for ``class X(Protocol):`` definitions (declarative interfaces)."""
    if not isinstance(node, ast.ClassDef):
        return False
    return any(_is_protocol_base(base) for base in node.bases)


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
    with report_path.open(encoding="utf-8") as f:
        return json.load(f)


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
# Full validation (used by coverage_policy.py)
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
    if fp in seen:
        errors.append(f"Duplicate entry in report: {fp}")
        return True
    seen.add(fp)
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
        normalised = _strip_src_prefix(fp)
        report_paths.add(normalised)
        entry_dict = _entry_as_dict(entry)
        summary = _summary_from_entry(entry_dict)
        _validate_entry_summary(fp, summary, config.min_coverage, errors)
        if config.branch_enabled:
            _validate_entry_branches(fp, summary, errors)
    return report_paths


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


def validate_report(
    coverage_data: dict[str, Any],
    min_coverage: float = DEFAULT_MIN_COVERAGE,
    src_root: Path | None = None,
) -> list[str]:
    """Full validation of a coverage.json report against the source tree."""
    root = src_root or SRC_ROOT
    errors: list[str] = []

    files: object = coverage_data.get("files")
    if not isinstance(files, dict) or not files:
        errors.append("Coverage report contains no module entries.")
        return errors

    typed_files = cast(dict[str, Any], files)
    meta: object = coverage_data.get("meta")
    meta_dict = cast(dict[str, Any], meta) if isinstance(meta, dict) else {}
    config = _ValidationConfig(
        min_coverage=min_coverage,
        branch_enabled=bool(meta_dict.get("branch_coverage", False)),
    )

    source_modules = _enumerate_source_modules(root)
    report_paths = _process_report_entries(typed_files, source_modules, config, errors)
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
        total_pct = float(typed_totals.get("percent_covered", 0.0))
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

# Exported for test use (tests/test_module_coverage.py imports these directly).
__all__ = ["_check_modules", "_format_module_name", "main"]
