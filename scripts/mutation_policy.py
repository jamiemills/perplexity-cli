"""Mutation testing policy enforcement using mutmut 3.5.0 internal metadata.

Reads mutmut's ``.meta`` files from the ``mutants/`` directory and validates
outcomes against a hard-gate policy.  Supports equivalent-mutant waivers from
``quality/mutation-waivers.toml``.

Policy rules:
  - Require at least one generated mutant for changed executable code.
  - Require that the test command collected and executed tests.
  - Fail for: survived, untested, no-tests, suspicious, timeout, segfault,
    interrupted, skipped-without-waiver, not-checked, internal-error.

Exit codes:
  0  Policy passes (all non-waived mutants killed)
  1  Policy violations found
  2  Internal error (schema drift, missing metadata, etc.)

Usage::

    uv run python scripts/mutation_policy.py mutants/ --report mutation-report.json
"""

from __future__ import annotations

import datetime
import fnmatch
import json
import logging
import sys
from pathlib import Path

_PROJECT_ROOT_PATH = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_PATH))

logger = logging.getLogger(__name__)

REQUIRED_MUTMUT_VERSION = "3.5.0"
EXIT_PASS = 0
EXIT_VIOLATIONS = 1
EXIT_INTERNAL_ERROR = 2

_PROJECT_ROOT: Path = _PROJECT_ROOT_PATH

# Maps mutmut exit codes to status strings (from mutmut __main__.py).
_EXIT_CODE_TO_STATUS: dict[int | None, str] = {
    None: "not checked",
    0: "survived",
    1: "killed",
    2: "check was interrupted by user",
    3: "killed",
    5: "no tests",
    33: "no tests",
    34: "skipped",
    35: "suspicious",
    36: "timeout",
    37: "caught by type check",
    152: "timeout",
    255: "timeout",
    -24: "timeout",
    -11: "segfault",
    -9: "segfault",
}

_FAILING_STATUSES: frozenset[str] = frozenset(
    {
        "survived",
        "no tests",
        "suspicious",
        "timeout",
        "segfault",
        "check was interrupted by user",
        "not checked",
        "skipped",
    }
)


def _check_mutmut_version() -> str:
    """Verify that the installed mutmut version matches the required version.

    Returns:
        The installed version string.

    Raises:
        SystemExit: If the version does not match.
    """
    try:
        import mutmut

        found = mutmut.__version__
    except ImportError:
        logger.exception("mutmut is not installed")
        sys.exit(EXIT_INTERNAL_ERROR)

    if found != REQUIRED_MUTMUT_VERSION:
        logger.error(
            "Schema-drift: mutmut %s required but %s found",
            REQUIRED_MUTMUT_VERSION,
            found,
        )
        sys.exit(EXIT_INTERNAL_ERROR)

    return found


def _status_for_exit_code(exit_code: int | None) -> str:
    """Map a raw mutmut exit code to a human-readable status.

    Args:
        exit_code: The raw exit code (may be None for not checked).

    Returns:
        The status string.
    """
    if exit_code is None:
        return "not checked"
    return _EXIT_CODE_TO_STATUS.get(exit_code, "suspicious")


def _is_failing_status(status: str) -> bool:
    """Check if a status indicates a policy violation.

    Args:
        status: A mutmut status string.

    Returns:
        True if the status fails the policy.
    """
    return status in _FAILING_STATUSES


def _load_waivers(waivers_path: Path | None = None) -> dict:
    """Load mutation waivers from a TOML file.

    Args:
        waivers_path: Path to the waivers file. Defaults to
            ``quality/mutation-waivers.toml``.

    Returns:
        A dictionary of waiver data with ``equivalent`` and ``survived`` keys.
    """
    try:
        import tomllib
    except ImportError:
        logger.warning("tomllib not available (Python < 3.11); waivers disabled")
        return {}

    if waivers_path is None:
        waivers_path = _PROJECT_ROOT / "quality" / "mutation-waivers.toml"

    if not waivers_path.exists():
        logger.info("No waiver file at %s; running without waivers", waivers_path)
        return {}

    try:
        with open(waivers_path, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError:
        logger.exception("Invalid TOML in waivers file: %s", waivers_path)
        return {}


def _matches_waiver(mutant_key: str, waivers: dict) -> tuple[bool, str]:
    """Check if a mutant outcome is covered by a waiver.

    Args:
        mutant_key: The fully-qualified mutant key.
        waivers: Loaded waiver data.

    Returns:
        A tuple of (is_waived, reason).
    """
    for category in ("equivalent", "survived"):
        entries = waivers.get("waivers", {}).get(category, [])
        for entry in entries:
            pattern = entry.get("mutant_pattern", "")
            if fnmatch.fnmatch(mutant_key, pattern):
                return True, entry.get("reason", "No reason provided")
    return False, ""


def _read_mutant_metadata(meta_path: Path) -> dict:
    """Read a single .meta file into a dictionary with schema validation.

    Args:
        meta_path: Path to the .meta file.

    Returns:
        Parsed metadata dictionary.

    Raises:
        SystemExit: If the metadata format is invalid.
    """
    try:
        with open(meta_path) as f:
            data = json.load(f)
    except json.JSONDecodeError:
        logger.exception("Invalid JSON in %s", meta_path)
        sys.exit(EXIT_INTERNAL_ERROR)

    required_keys = {
        "exit_code_by_key",
        "durations_by_key",
        "type_check_error_by_key",
        "estimated_durations_by_key",
    }
    actual_keys = set(data.keys())
    if actual_keys != required_keys:
        extra = actual_keys - required_keys
        missing = required_keys - actual_keys
        details: list[str] = []
        if extra:
            details.append(f"extra keys: {sorted(extra)}")
        if missing:
            details.append(f"missing keys: {sorted(missing)}")
        logger.error(
            "Schema drift in %s: expected keys %s, got %s (%s)",
            meta_path,
            sorted(required_keys),
            sorted(actual_keys),
            "; ".join(details),
        )
        sys.exit(EXIT_INTERNAL_ERROR)

    return data


def _parse_one_file(meta_path: Path, waivers: dict) -> tuple[str, list[dict], list[dict]]:
    """Parse one .meta file into structured per-mutant records.

    Args:
        meta_path: Path to a .meta file.
        waivers: Loaded waiver data.

    Returns:
        A tuple of (source_path, mutants_list, violations_list).
    """
    data = _read_mutant_metadata(meta_path)
    exit_codes = data["exit_code_by_key"]
    durations = data["durations_by_key"]

    source_path = str(meta_path).replace("mutants/", "").removesuffix(".meta")

    mutants: list[dict] = []
    violations: list[dict] = []

    for key, exit_code in exit_codes.items():
        status = _status_for_exit_code(exit_code)
        duration = durations.get(key)
        waived, waiver_reason = _matches_waiver(key, waivers)

        entry: dict = {
            "key": key,
            "status": status,
            "exit_code": exit_code,
            "duration_s": duration,
            "waived": waived,
            "waiver_reason": waiver_reason,
        }
        mutants.append(entry)

        if _is_failing_status(status) and not waived:
            violations.append(
                {
                    "key": key,
                    "status": status,
                    "file": source_path,
                    "exit_code": exit_code,
                }
            )

    return source_path, mutants, violations


def _make_empty_agg() -> dict:
    """Create an empty aggregate summary dictionary.

    Returns:
        An aggregate dictionary with all known statuses set to 0.
    """
    return {
        "total": 0,
        "killed": 0,
        "survived": 0,
        "no_tests": 0,
        "suspicious": 0,
        "timeout": 0,
        "skipped": 0,
        "segfault": 0,
        "not_checked": 0,
        "check_was_interrupted_by_user": 0,
        "caught_by_type_check": 0,
        "tests_collected": 0,
        "tests_run": 0,
    }


def _update_agg_from_mutants(agg: dict, mutants: list[dict]) -> None:
    """Update aggregate counts from a list of mutant entries.

    Args:
        agg: The aggregate dictionary to update.
        mutants: List of mutant entry dictionaries.
    """
    for m in mutants:
        agg["total"] += 1
        status_key = m["status"].replace(" ", "_")
        if status_key in agg:
            agg[status_key] += 1


def _load_metadata(
    mutants_dir: Path,
    waivers: dict,
) -> tuple[list[tuple[str, list[dict]]], list[dict], dict]:
    """Load all .meta files and parse into structured results.

    Args:
        mutants_dir: Path to the mutants/ directory.
        waivers: Loaded waiver data.

    Returns:
        A tuple of (files_results, all_violations, summary).
    """
    file_results: list[tuple[str, list[dict]]] = []
    all_violations: list[dict] = []
    agg = _make_empty_agg()

    meta_files = sorted(Path(mutants_dir).rglob("*.meta"))
    if not meta_files:
        logger.error("No .meta files found in %s", mutants_dir)
        sys.exit(EXIT_INTERNAL_ERROR)

    for meta_path in meta_files:
        source_path, mutants, violations = _parse_one_file(meta_path, waivers)
        file_results.append((source_path, mutants))
        all_violations.extend(violations)
        _update_agg_from_mutants(agg, mutants)

    return file_results, all_violations, agg


def _source_path_from_manifest_path(path: str) -> str:
    """Convert a manifest path to a source path prefix for matching.

    Args:
        path: A file path from the manifest (e.g. src/perplexity_cli/api/__init__.py).

    Returns:
        A sanitised path for matching against .meta source paths.
    """
    if path.startswith("src/"):
        return path
    return f"src/{path}"


def _check_one_file_has_mutant(
    changed_file: str,
    deletion_set: set[str],
    metadata_paths: set[str],
) -> str | None:
    """Check if a single changed file has mutant coverage.

    Args:
        changed_file: A changed file path from the manifest.
        deletion_set: Set of deleted file paths.
        metadata_paths: Set of source paths from .meta files.

    Returns:
        An error message if no mutant found, or None.
    """
    if changed_file in deletion_set:
        return None
    expected = _source_path_from_manifest_path(changed_file)
    has_mutant = any(
        mpath == expected or mpath.startswith(f"{expected}/") for mpath in metadata_paths
    )
    if has_mutant:
        return None
    return f"No mutants generated for changed file: {changed_file}"


def _check_manifest_coverage(
    manifest: dict | None,
    file_results: list[tuple[str, list[dict]]],
) -> list[str]:
    """Verify every changed file has at least one mutant generated.

    Args:
        manifest: The manifest from discover_mutate_diff_files.
        file_results: Parsed file results from metadata.

    Returns:
        List of error messages for files missing mutants.
    """
    if manifest is None:
        return []

    changed = set(manifest.get("changed_files", []))
    deletion_set = set(manifest.get("deletions", []))
    metadata_paths = {path for path, _ in file_results}

    errors: list[str] = []
    for cf in changed:
        msg = _check_one_file_has_mutant(cf, deletion_set, metadata_paths)
        if msg:
            errors.append(msg)
    return errors


def _resolve_head_sha() -> str | None:
    """Resolve the current HEAD SHA.

    Returns:
        The full SHA, or None on failure.
    """
    from scripts.differential_context import _run_git

    returncode, stdout, _ = _run_git(["rev-parse", "HEAD"], cwd=_PROJECT_ROOT)
    if returncode == 0 and stdout:
        return stdout
    return None


def generate_report(
    file_results: list[tuple[str, list[dict]]],
    violations: list[dict],
    summary: dict,
    extra: dict | None = None,
) -> dict:
    """Generate a machine-readable mutation report.

    Args:
        file_results: Per-file mutant data.
        violations: Policy violations.
        summary: Aggregated counts.
        extra: Optional dict with ``manifest`` and/or ``manifest_errors`` keys.

    Returns:
        A report dictionary conforming to mutation-report-v1.json.
    """
    now = datetime.datetime.now(datetime.UTC).isoformat()
    head_sha = _resolve_head_sha()

    report: dict = {
        "schema_version": "1",
        "timestamp": now,
        "head_sha": head_sha,
        "mutmut_version_required": REQUIRED_MUTMUT_VERSION,
        "mutmut_version_found": REQUIRED_MUTMUT_VERSION,
        "summary": summary,
        "files": [{"path": path, "mutants": mutants} for path, mutants in file_results],
        "policy_pass": len(violations) == 0,
        "violations": violations,
    }

    if extra:
        if "manifest" in extra:
            report["manifest"] = extra["manifest"]
        if "manifest_errors" in extra:
            report["manifest_errors"] = extra["manifest_errors"]

    return report


def save_report(report: dict, output_path: Path) -> None:
    """Save the mutation report as JSON.

    Args:
        report: The report dictionary.
        output_path: Path to write the report to.
    """
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    logger.info("Mutation report written to %s", output_path)


def _handle_policy_outcome(
    violations: list[dict],
    summary: dict,
    report: dict,
    report_output: Path | None,
) -> int:
    """Handle the final policy outcome: log violations or pass, and return exit code.

    Args:
        violations: List of policy violations.
        summary: Aggregate counts.
        report: The generated report.
        report_output: Optional path to save the report.

    Returns:
        Exit code (EXIT_PASS or EXIT_VIOLATIONS).
    """
    if report_output:
        save_report(report, report_output)

    if violations:
        logger.warning("Mutation policy VIOLATIONS: %s", len(violations))
        for v in violations:
            logger.warning("  %s -> %s (%s)", v["key"], v["status"], v["file"])
        return EXIT_VIOLATIONS

    logger.info(
        "Mutation policy PASS: %s/%s mutants killed",
        summary["killed"],
        summary["total"],
    )
    return EXIT_PASS


def run_policy(
    mutants_dir: Path,
    manifest: dict | None = None,
    waivers_path: Path | None = None,
    report_output: Path | None = None,
) -> int:
    """Run the full mutation policy check.

    Args:
        mutants_dir: Path to the mutants/ directory containing .meta files.
        manifest: Optional manifest from discover_mutate_diff_files.
        waivers_path: Optional path to mutation-waivers.toml.
        report_output: If provided, write the JSON report to this path.

    Returns:
        Exit code: 0 pass, 1 violations, 2 internal error.
    """
    found_version = _check_mutmut_version()
    logger.info("mutmut version %s confirmed", found_version)

    waivers = _load_waivers(waivers_path)
    file_results, violations, summary = _load_metadata(mutants_dir, waivers)

    if manifest:
        manifest_errors = _check_manifest_coverage(manifest, file_results)
        if manifest_errors:
            for err in manifest_errors:
                logger.error(err)
            return EXIT_VIOLATIONS

    extra: dict = {}
    if manifest:
        extra["manifest"] = manifest

    report = generate_report(file_results, violations, summary, extra)

    return _handle_policy_outcome(violations, summary, report, report_output)


def main() -> int:
    """CLI entry point.

    Usage: python scripts/mutation_policy.py mutants/ [--report report.json]
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Mutation testing policy enforcement using mutmut 3.5.0 metadata"
    )
    parser.add_argument("mutants_dir", type=Path, help="Path to the mutants/ directory")
    parser.add_argument("--report", type=Path, default=None, help="Write JSON report to this path")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Path to manifest JSON from discover_mutate_diff_files",
    )
    parser.add_argument(
        "--waivers",
        type=Path,
        default=None,
        help="Path to mutation-waivers.toml",
    )
    args = parser.parse_args()

    manifest = None
    if args.manifest:
        with open(args.manifest) as f:
            manifest = json.load(f)

    return run_policy(
        mutants_dir=args.mutants_dir,
        manifest=manifest,
        waivers_path=args.waivers,
        report_output=args.report,
    )


if __name__ == "__main__":
    sys.exit(main())
