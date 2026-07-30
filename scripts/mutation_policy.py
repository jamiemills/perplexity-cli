"""Canonical mutation testing policy wrapper for mutmut 3.x.

Reads ``mutmut results`` text output (run as a subprocess), classifies each
mutant into policy categories, emits a JSON report conforming to
``quality/schemas/mutation-report.json``, and returns a classified exit code.
This wrapper does NOT run mutation testing itself (``mutmut run``) — that is
the Make target's responsibility. It only consumes the results.

mutmut 3.x has no machine-readable JSON output. The text format produced by
``mutmut results`` is one line per mutant, indented by four spaces::

        <mutant-key>: <status>

Known mutmut 3.x statuses are mapped to six policy categories:
``killed``, ``survived``, ``timeout``, ``suspicious``, ``skipped``,
``not_checked``. ``survived``, ``timeout`` and ``suspicious`` are actionable
and trigger a ``findings`` outcome; the others are informational.

Usage::

    uv run python scripts/mutation_policy.py [--report-path <path>]

Exit codes:
    0  clean       — no actionable mutants
    1  findings    — at least one survived/timeout/suspicious mutant
    2  tool-error  — mutmut unavailable or output unparseable (schema drift)
"""

from __future__ import annotations

import argparse
import json
import logging
import re

# owner: quality-infrastructure; reason: only the fixed pinned mutmut command is executed without a shell
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PROJECT_ROOT_PATH = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_PATH))

logger = logging.getLogger(__name__)

PROJECT_ROOT: Path = _PROJECT_ROOT_PATH

EXIT_CLEAN: int = 0
EXIT_FINDINGS: int = 1
EXIT_TOOL_ERROR: int = 2

TOOL_NAME: str = "mutmut"
UNKNOWN_VERSION: str = "unknown"
STATUS_CLEAN: str = "clean"
STATUS_FINDINGS: str = "findings"
STATUS_TOOL_ERROR: str = "tool-error"

# Actionable categories (cause findings).
ACTIONABLE_CATEGORIES: frozenset[str] = frozenset({"survived", "timeout", "suspicious"})

# Canonical category order used in the report.
CATEGORY_ORDER: tuple[str, ...] = (
    "killed",
    "survived",
    "timeout",
    "suspicious",
    "skipped",
    "not_checked",
)

# mutmut 3.x raw statuses mapped to normalised policy categories.
STATUS_TO_CATEGORY: dict[str, str] = {
    "killed": "killed",
    "survived": "survived",
    "timeout": "timeout",
    "suspicious": "suspicious",
    "skipped": "skipped",
    "not checked": "not_checked",
    "no tests": "skipped",
}

# Subprocess invocation prefix used to reach the project's pinned mutmut.
_MUTMUT_PREFIX: tuple[str, ...] = ("uv", "run", "mutmut")
# Subprocess timeout in seconds for any single mutmut invocation.
_MUTMUT_TIMEOUT_S: int = 120


class ResultsParseError(ValueError):
    """Raised when a mutmut results line cannot be parsed (line-format drift)."""


class UnknownStatusError(ValueError):
    """Raised when mutmut emits a status outside the known mapping."""

    def __init__(self, status: str) -> None:
        super().__init__(f"Unknown mutmut status: {status!r}")
        self.status = status


class MutmutUnavailableError(RuntimeError):
    """Raised when mutmut cannot be invoked or returns a non-zero exit code."""


@dataclass(frozen=True, slots=True)
class MutantEntry:
    """A single mutant with its raw status and normalised category."""

    key: str
    status: str
    category: str


@dataclass(frozen=True, slots=True)
class CategoryCounts:
    """Per-category aggregate counts."""

    killed: int = 0
    survived: int = 0
    timeout: int = 0
    suspicious: int = 0
    skipped: int = 0
    not_checked: int = 0


@dataclass(frozen=True, slots=True)
class MutationReport:
    """The full mutation policy report."""

    tool: str
    version: str
    total_mutants: int
    categories: CategoryCounts
    status: str
    survivors: tuple[MutantEntry, ...]
    error: str = ""


# Matches lines of the form "    <key>: <status>" (four-space indent).
_LINE_PATTERN: re.Pattern[str] = re.compile(r"^    (?P<key>.+): (?P<status>.+)$")
# Matches the output of `mutmut --version`, e.g. "mutmut, version 3.5.0".
_VERSION_PATTERN: re.Pattern[str] = re.compile(r"^mutmut, version (?P<version>\S+)\s*$")


def _parse_line(line: str) -> tuple[str, str] | None:
    """Parse a single ``mutmut results`` line.

    Args:
        line: One line of text from ``mutmut results``.

    Returns:
        Tuple of (key, status), or None if the line does not match the
        expected four-space-indented ``key: status`` format.
    """
    match = _LINE_PATTERN.match(line)
    if match is None:
        return None
    return match.group("key"), match.group("status")


def _classify_status(status: str) -> str:
    """Map a raw mutmut status to a normalised policy category.

    Args:
        status: A raw mutmut status string (e.g. ``"not checked"``).

    Returns:
        The normalised category (e.g. ``"not_checked"``).

    Raises:
        UnknownStatusError: If the status is outside the known mapping.
    """
    category = STATUS_TO_CATEGORY.get(status)
    if category is None:
        raise UnknownStatusError(status)
    return category


def parse_results_text(text: str) -> list[MutantEntry]:
    """Parse the raw text output of ``mutmut results --all``.

    Args:
        text: Raw stdout from ``mutmut results --all True``.

    Returns:
        List of :class:`MutantEntry` records, one per non-blank line.

    Raises:
        ResultsParseError: If a non-blank line does not match the expected
            format (line-format schema drift).
        UnknownStatusError: If a parsed status is outside the known mapping
            (status schema drift).
    """
    entries: list[MutantEntry] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        entries.append(_parse_entry_line(line))
    return entries


def _parse_entry_line(line: str) -> MutantEntry:
    """Parse a single non-blank results line into a :class:`MutantEntry`.

    Args:
        line: A non-blank line of ``mutmut results`` output.

    Returns:
        The parsed mutant entry.

    Raises:
        ResultsParseError: If the line does not match the expected format.
        UnknownStatusError: If the status is not recognised.
    """
    parsed = _parse_line(line)
    if parsed is None:
        raise ResultsParseError(line)
    key, status = parsed
    return MutantEntry(key=key, status=status, category=_classify_status(status))


def _count_categories(entries: list[MutantEntry]) -> CategoryCounts:
    """Aggregate mutant entries into category counts.

    Args:
        entries: Mutant entries to tally.

    Returns:
        A :class:`CategoryCounts` instance.
    """
    tallies: dict[str, int] = dict.fromkeys(CATEGORY_ORDER, 0)
    for entry in entries:
        tallies[entry.category] += 1
    return CategoryCounts(**tallies)


def _pick_survivors(entries: list[MutantEntry]) -> tuple[MutantEntry, ...]:
    """Return the actionable subset of ``entries``.

    Args:
        entries: All mutant entries.

    Returns:
        Tuple of entries whose category is survived, timeout or suspicious.
    """
    return tuple(entry for entry in entries if entry.category in ACTIONABLE_CATEGORIES)


def build_report(version: str, entries: list[MutantEntry]) -> MutationReport:
    """Build a :class:`MutationReport` from a version and parsed entries.

    Args:
        version: Detected mutmut version string.
        entries: Parsed mutant entries.

    Returns:
        A :class:`MutationReport` with status ``clean`` or ``findings``.
    """
    survivors = _pick_survivors(entries)
    status = STATUS_FINDINGS if survivors else STATUS_CLEAN
    return MutationReport(
        tool=TOOL_NAME,
        version=version,
        total_mutants=len(entries),
        categories=_count_categories(entries),
        status=status,
        survivors=survivors,
    )


def build_tool_error_report(message: str) -> MutationReport:
    """Build a ``tool-error`` report.

    Args:
        message: Diagnostic describing why mutmut could not be used.

    Returns:
        A :class:`MutationReport` with status ``tool-error``.
    """
    return MutationReport(
        tool=TOOL_NAME,
        version=UNKNOWN_VERSION,
        total_mutants=0,
        categories=CategoryCounts(),
        status=STATUS_TOOL_ERROR,
        survivors=(),
        error=message,
    )


def _counts_to_dict(counts: CategoryCounts) -> dict[str, int]:
    """Serialise :class:`CategoryCounts` to a JSON-compatible dict."""
    return {
        "killed": counts.killed,
        "survived": counts.survived,
        "timeout": counts.timeout,
        "suspicious": counts.suspicious,
        "skipped": counts.skipped,
        "not_checked": counts.not_checked,
    }


def _entry_to_dict(entry: MutantEntry) -> dict[str, str]:
    """Serialise a :class:`MutantEntry` to a JSON-compatible dict."""
    return {
        "key": entry.key,
        "status": entry.status,
        "category": entry.category,
    }


def report_to_dict(report: MutationReport) -> dict[str, Any]:
    """Serialise a :class:`MutationReport` to a JSON-compatible dict.

    Args:
        report: The report to serialise.

    Returns:
        A dict suitable for :func:`json.dumps`. The ``error`` key is only
        included when populated.
    """
    payload: dict[str, Any] = {
        "tool": report.tool,
        "version": report.version,
        "total_mutants": report.total_mutants,
        "categories": _counts_to_dict(report.categories),
        "status": report.status,
        "survivors": [_entry_to_dict(entry) for entry in report.survivors],
    }
    if report.error:
        payload["error"] = report.error
    return payload


def write_report(report: MutationReport, report_path: Path) -> None:
    """Write the JSON report to ``report_path``.

    Parent directories are created if missing. The report is written before
    any non-zero exit code is returned by the wrapper.

    Args:
        report: The report to write.
        report_path: Destination file path.
    """
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report_to_dict(report), indent=2) + "\n"
    report_path.write_text(payload)
    logger.info("Mutation report written to %s", report_path)


def _run_mutmut(args: tuple[str, ...]) -> str:
    """Run a mutmut subprocess and return its stdout.

    Args:
        args: Argument argv to forward to mutmut (after the invocation prefix).

    Returns:
        The stripped stdout.

    Raises:
        MutmutUnavailableError: If the binary cannot be found, the process
            times out, or mutmut exits non-zero.
    """
    cmd = [*_MUTMUT_PREFIX, *args]
    logger.info("Running: %s", " ".join(cmd))
    try:
        # owner: quality-infrastructure; reason: args are restricted to the mutmut helper contracts and shell is disabled
        result = subprocess.run(  # nosec B603
            cmd,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            check=False,
            timeout=_MUTMUT_TIMEOUT_S,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        raise MutmutUnavailableError(str(exc)) from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        msg = f"mutmut exited {result.returncode}: {detail}"
        raise MutmutUnavailableError(msg)
    return result.stdout


def parse_version_text(text: str) -> str:
    """Parse the version string from ``mutmut --version`` output.

    Args:
        text: Output of the form ``"mutmut, version 3.5.0\\n"``.

    Returns:
        The version string (e.g. ``"3.5.0"``).

    Raises:
        MutmutUnavailableError: If the output does not match the expected
            format (schema drift on the version line).
    """
    match = _VERSION_PATTERN.match(text)
    if match is None:
        msg = f"Unparseable mutmut version output: {text!r}"
        raise MutmutUnavailableError(msg)
    return match.group("version")


def detect_version() -> str:
    """Run ``mutmut --version`` and return the parsed version string."""
    return parse_version_text(_run_mutmut(("--version",)))


def fetch_results_text() -> str:
    """Run ``mutmut results --all True`` and return the raw stdout text."""
    return _run_mutmut(("results", "--all", "True"))


def _exit_code_for_status(status: str) -> int:
    """Map a report status to its exit code.

    Args:
        status: One of ``clean``, ``findings`` or ``tool-error``.

    Returns:
        The matching exit code (0, 1 or 2).
    """
    if status == STATUS_CLEAN:
        return EXIT_CLEAN
    if status == STATUS_FINDINGS:
        return EXIT_FINDINGS
    return EXIT_TOOL_ERROR


def _finalise_tool_error(message: str, report_path: Path | None) -> int:
    """Write a tool-error report (if requested) and return the exit code."""
    if report_path is not None:
        write_report(build_tool_error_report(message), report_path)
    return EXIT_TOOL_ERROR


def run_policy(
    version: str,
    results_text: str,
    report_path: Path | None,
) -> int:
    """Run the policy against pre-fetched mutmut results text.

    Args:
        version: Detected mutmut version string.
        results_text: Raw stdout of ``mutmut results --all True``.
        report_path: Optional path to which the JSON report is written
            before the exit code is returned.

    Returns:
        Exit code: 0 clean, 1 findings, 2 tool-error.
    """
    try:
        entries = parse_results_text(results_text)
    except (ResultsParseError, UnknownStatusError):
        logger.exception("Schema drift detected in mutmut output")
        return _finalise_tool_error("schema drift in mutmut output", report_path)

    report = build_report(version, entries)
    if report_path is not None:
        write_report(report, report_path)
    return _exit_code_for_status(report.status)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list, or None for ``sys.argv[1:]``.

    Returns:
        The parsed namespace with a ``report_path`` attribute.
    """
    parser = argparse.ArgumentParser(
        description="Canonical mutation testing policy wrapper for mutmut 3.x."
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=None,
        help="Path to write the JSON report (omitted: no report file).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code: 0 clean, 1 findings, 2 tool-error.
    """
    args = _parse_args(argv)
    report_path: Path | None = args.report_path

    try:
        version = detect_version()
        results_text = fetch_results_text()
    except MutmutUnavailableError:
        logger.exception("mutmut unavailable")
        return _finalise_tool_error("mutmut unavailable", report_path)

    return run_policy(version, results_text, report_path)


if __name__ == "__main__":
    sys.exit(main())
