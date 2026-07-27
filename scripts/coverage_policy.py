"""Coverage policy engine: combine fragments and produce a diff-coverage report.

Accepts unit and integration coverage fragments (``.coverage`` files),
combines them with ``coverage combine``, runs unified validation, optionally
computes diff context between base and tested SHAs, and emits a structured
JSON report conforming to ``quality/schemas/diff-coverage-v1.json``.

Usage::

    uv run python scripts/coverage_policy.py \\
        --unit-coverage .coverage-unit \\
        --integration-coverage .coverage-integration \\
        --report output.json

    # With diff context:
    uv run python scripts/coverage_policy.py \\
        --unit-coverage .coverage-unit \\
        --base-sha abc123 --tested-sha def456 \\
        --report output.json
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gates import load_gates  # noqa: E402
from check_module_coverage import validate_report  # noqa: E402

_gates = load_gates()
DEFAULT_MIN_COVERAGE = _gates.get_int("MIN_COVERAGE", 85)
DEFAULT_REPORT = "diff-coverage-report.json"


@dataclass(frozen=True, slots=True)
class _ReportInputs:
    success: bool
    errors: list[str]
    overall_pct: float
    threshold: float
    total_modules: int
    fragments: list[str]
    base_sha: str | None = None
    tested_sha: str | None = None
    diff_info: dict[str, Any] | None = None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Combine coverage fragments and produce a diff-coverage report.",
    )
    parser.add_argument(
        "--unit-coverage",
        type=str,
        required=True,
        help="Path to the unit coverage fragment (.coverage file).",
    )
    parser.add_argument(
        "--integration-coverage",
        type=str,
        default=None,
        help="Path to the integration coverage fragment (optional).",
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
        help=f"Path for the output JSON report (default: {DEFAULT_REPORT})",
    )
    parser.add_argument(
        "--base-sha",
        type=str,
        default=None,
        help="Base commit SHA for diff context.",
    )
    parser.add_argument(
        "--tested-sha",
        type=str,
        default=None,
        help="Tested commit SHA for diff context.",
    )
    return parser.parse_args()


def _validate_fragment_path(path: str, label: str) -> Path:
    p = Path(path)
    if not p.is_file():
        print(f"{label} coverage fragment not found: {path}", file=sys.stderr)
        sys.exit(2)
    return p


def _copy_to_temp(src: Path, workdir: Path) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".coverage", dir=str(workdir)) as tmp:
        tmp.write(src.read_bytes())
        tmp.flush()
    return tmp.name


def _combine_fragments(
    fragments: list[Path],
    workdir: Path,
) -> Path:
    """Combine .coverage fragments into a single data file."""
    combined_data = workdir / ".coverage"
    data_files: list[str] = [_copy_to_temp(frag, workdir) for frag in fragments]

    env = {"COVERAGE_FILE": str(combined_data)}
    cmd = ["coverage", "combine", "--keep", *data_files]
    result = subprocess.run(
        cmd, capture_output=True, text=True, env=env, cwd=str(workdir), check=False
    )
    if result.returncode != 0:
        print(f"coverage combine failed: {result.stderr}", file=sys.stderr)
        sys.exit(2)

    if not combined_data.is_file():
        print("coverage combine succeeded but no .coverage file was produced.", file=sys.stderr)
        sys.exit(2)

    return combined_data


def _generate_json_report(combined_data: Path, workdir: Path) -> dict[str, Any]:
    """Run 'coverage json' on the combined data file to produce a report dict."""
    env = {"COVERAGE_FILE": str(combined_data)}
    json_path = workdir / "coverage.json"
    cmd = ["coverage", "json", "-o", str(json_path)]
    result = subprocess.run(
        cmd, capture_output=True, text=True, env=env, cwd=str(workdir), check=False
    )
    if result.returncode != 0:
        print(f"coverage json failed: {result.stderr}", file=sys.stderr)
        sys.exit(2)

    with open(json_path) as f:
        return json.load(f)


def _compute_diff_context(
    base_sha: str,
    tested_sha: str,
    workdir: Path,
) -> dict[str, Any]:
    """Compute changed files between base and tested SHAs."""
    from differential_context import compute_ci_context

    ctx = compute_ci_context(base_sha, tested_sha, cwd=workdir)
    return {
        "changed_files": list(ctx.changed_files),
        "empty_diff": ctx.is_empty_diff,
        "git_error": ctx.git_error,
    }


def _build_report(inputs: _ReportInputs) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": "1",
        "success": inputs.success,
        "overall_pct": inputs.overall_pct,
        "threshold": inputs.threshold,
        "total_modules": inputs.total_modules,
        "errors": inputs.errors,
        "fragments": inputs.fragments,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if inputs.base_sha:
        report["base_sha"] = inputs.base_sha
    if inputs.tested_sha:
        report["tested_sha"] = inputs.tested_sha
    if inputs.diff_info:
        report.update(inputs.diff_info)
    return report


def _process_fragments(
    fragments: list[Path],
    workdir: Path,
) -> dict[str, Any]:
    if len(fragments) == 1:
        combined_data = fragments[0]
    else:
        combined_data = _combine_fragments(fragments, workdir)
    return _generate_json_report(combined_data, workdir)


def main() -> None:
    args = _parse_args()

    unit_path = _validate_fragment_path(args.unit_coverage, "Unit")
    fragments: list[Path] = [unit_path]
    fragment_paths: list[str] = [str(unit_path)]

    if args.integration_coverage:
        int_path = _validate_fragment_path(args.integration_coverage, "Integration")
        fragments.append(int_path)
        fragment_paths.append(str(int_path))

    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        coverage_data = _process_fragments(fragments, workdir)

        validation_errors = validate_report(coverage_data, min_coverage=args.min_coverage)
        overall_pct = coverage_data.get("totals", {}).get("percent_covered", 0.0)
        total_modules = len(coverage_data.get("files", {}))

        diff_info: dict[str, Any] | None = None
        if args.base_sha and args.tested_sha:
            diff_info = _compute_diff_context(args.base_sha, args.tested_sha, workdir)

        report = _build_report(
            _ReportInputs(
                success=not validation_errors,
                errors=validation_errors,
                overall_pct=overall_pct,
                threshold=args.min_coverage,
                total_modules=total_modules,
                fragments=fragment_paths,
                base_sha=args.base_sha,
                tested_sha=args.tested_sha,
                diff_info=diff_info,
            )
        )

    _write_report(report, args.report)


def _write_report(report: dict[str, Any], path: str) -> None:
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
        f.write("\n")

    if report["success"]:
        print(f"Diff-coverage check passed: {report['overall_pct']:.1f}%")
        sys.exit(0)
    else:
        errors: list[str] = report["errors"]
        print(
            f"Diff-coverage check FAILED: {len(errors)} error(s)\n",
            file=sys.stderr,
        )
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
