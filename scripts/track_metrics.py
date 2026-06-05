"""Track radon complexity and maintainability metrics over git history.

Replacement for wily that works with radon 6.x (no dependency conflict).
Iterates recent git revisions, runs radon on each, and reports trends.

Usage
-----
    python scripts/track_metrics.py                  # last 10 revisions
    python scripts/track_metrics.py --revisions 20   # last 20 revisions
    python scripts/track_metrics.py --since 2025-01-01  # all commits since date
    python scripts/track_metrics.py --json           # machine-readable output
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = "src/perplexity_cli"

DEFAULT_REVISIONS = 10


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class MetricSnapshot:
    """Radon metrics for a single git revision."""

    commit_hash: str
    commit_date: str
    commit_message: str

    # Cyclomatic complexity: count of blocks graded B or worse, worst rank
    cc_violations: int = 0
    cc_worst: str = "A"

    # Maintainability index: count of modules graded B or worse, worst rank
    mi_violations: int = 0
    mi_worst: str = "A"


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------


def _git_log(revisions: int) -> list[tuple[str, str, str]]:
    """Return list of (hash, date, message) for the last *revisions* commits."""
    result = subprocess.run(
        [
            "git",
            "log",
            f"-{revisions}",
            "--format=%H|%ad|%s",
            "--date=short",
            "--",
            SRC_DIR,
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    if result.returncode != 0:
        print("Failed to read git history", file=sys.stderr)
        sys.exit(1)

    entries: list[tuple[str, str, str]] = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) == 3:
            entries.append((parts[0], parts[1], parts[2]))

    return entries


def _git_since(since_date: str) -> list[tuple[str, str, str]]:
    """Return list of (hash, date, message) for commits since *since_date*."""
    result = subprocess.run(
        [
            "git",
            "log",
            f"--since={since_date}",
            "--format=%H|%ad|%s",
            "--date=short",
            "--",
            SRC_DIR,
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    if result.returncode != 0:
        print("Failed to read git history", file=sys.stderr)
        sys.exit(1)

    entries: list[tuple[str, str, str]] = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) == 3:
            entries.append((parts[0], parts[1], parts[2]))

    return entries


def _checkout_revision(rev: str, tmpdir: str) -> bool:
    """Extract src/ at *rev* into *tmpdir*.  Returns True on success."""
    result = subprocess.run(
        ["git", "archive", rev, f"{SRC_DIR}/", f"--output={tmpdir}/src.tar"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    if result.returncode != 0:
        return False

    extract = subprocess.run(
        ["tar", "-xf", f"{tmpdir}/src.tar", "-C", tmpdir],
        capture_output=True,
        text=True,
    )
    return extract.returncode == 0


# ---------------------------------------------------------------------------
# Radon analysis
# ---------------------------------------------------------------------------


def _run_radon_cc(tmpdir: str) -> tuple[int, str]:
    """Run radon cc on the checked-out source in *tmpdir*.  Returns (violations, worst_rank)."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "radon",
            "cc",
            f"{tmpdir}/{SRC_DIR}",
            "-s",
            "-n",
            "B",
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    output = result.stdout.strip()
    if not output:
        return 0, "A"

    lines = output.split("\n")
    violations = sum(1 for line in lines if line.strip() and not line.startswith(" "))
    worst = _worst_rank_from_lines(lines)
    return violations, worst


def _run_radon_mi(tmpdir: str) -> tuple[int, str]:
    """Run radon mi on the checked-out source in *tmpdir*.  Returns (violations, worst_rank)."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "radon",
            "mi",
            f"{tmpdir}/{SRC_DIR}",
            "-s",
            "-n",
            "B",
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    output = result.stdout.strip()
    if not output:
        return 0, "A"

    lines = output.split("\n")
    violations = sum(1 for line in lines if line.strip() and not line.startswith(" "))
    worst = _worst_rank_from_lines(lines)
    return violations, worst


def _worst_rank_from_lines(lines: list[str]) -> str:
    """Extract the worst rank letter from radon output lines."""
    rank_values = {"F": 6, "E": 5, "D": 4, "C": 3, "B": 2, "A": 1}
    worst_val = 1

    for line in lines:
        rank = _extract_rank(line)
        if rank and rank_values.get(rank, 0) > worst_val:
            worst_val = rank_values[rank]

    return _rank_for_value(rank_values, worst_val)


def _extract_rank(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith(" "):
        return None
    parts = stripped.split()
    return parts[-1].strip() if parts else None


def _rank_for_value(rank_values: dict[str, int], target: int) -> str:
    for rank, val in rank_values.items():
        if val == target:
            return rank
    return "A"


# ---------------------------------------------------------------------------
# Snapshot collection
# ---------------------------------------------------------------------------


def _collect_snapshots(
    revisions: list[tuple[str, str, str]],
) -> list[MetricSnapshot]:
    """Run radon on each revision and return a list of MetricSnapshots."""
    snapshots: list[MetricSnapshot] = []

    for commit_hash, commit_date, commit_message in revisions:
        with tempfile.TemporaryDirectory(prefix="track_metrics_") as tmpdir:
            if not _checkout_revision(commit_hash, tmpdir):
                continue

            cc_violations, cc_worst = _run_radon_cc(tmpdir)
            mi_violations, mi_worst = _run_radon_mi(tmpdir)

            snapshots.append(
                MetricSnapshot(
                    commit_hash=commit_hash[:8],
                    commit_date=commit_date,
                    commit_message=commit_message[:60],
                    cc_violations=cc_violations,
                    cc_worst=cc_worst,
                    mi_violations=mi_violations,
                    mi_worst=mi_worst,
                )
            )

    return snapshots


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _format_text(snapshots: list[MetricSnapshot]) -> str:
    lines: list[str] = []
    lines.append(f"Metric trends over {len(snapshots)} revisions (newest first)\n")
    lines.append(
        f"{'Date':<12} {'Commit':<10} {'CC#':>4} {'CC↓':>4} {'MI#':>4} {'MI↓':>4}  Message"
    )
    lines.append("-" * 78)

    for s in snapshots:
        lines.append(
            f"{s.commit_date:<12} {s.commit_hash:<10} "
            f"{s.cc_violations:>4} {s.cc_worst:>4} "
            f"{s.mi_violations:>4} {s.mi_worst:>4}  {s.commit_message}"
        )

    lines.append("")
    lines.append("CC# = count of blocks with cyclomatic complexity >= B (B or worse)")
    lines.append("CC↓ = worst complexity rank across all blocks")
    lines.append("MI# = count of modules with maintainability index < A (B or worse)")
    lines.append("MI↓ = worst maintainability rank across all modules")
    lines.append("Threshold: B.  Target: all A-grade (CC <= 5, MI >= 20).")

    return "\n".join(lines)


def _format_json(snapshots: list[MetricSnapshot]) -> str:
    return json.dumps(
        {
            "revisions": len(snapshots),
            "snapshots": [
                {
                    "commit": s.commit_hash,
                    "date": s.commit_date,
                    "message": s.commit_message,
                    "cc_violations": s.cc_violations,
                    "cc_worst": s.cc_worst,
                    "mi_violations": s.mi_violations,
                    "mi_worst": s.mi_worst,
                }
                for s in snapshots
            ],
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(args: list[str]) -> tuple[bool, int, str | None]:
    json_mode = False
    revisions = DEFAULT_REVISIONS
    since_date: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--json":
            json_mode = True
        elif arg == "--revisions":
            i += 1
            revisions = _parse_int_arg(args, i, "--revisions")
        elif arg == "--since":
            i += 1
            since_date = _parse_since_arg(args, i)
        i += 1

    return json_mode, revisions, since_date


def _parse_int_arg(args: list[str], i: int, flag: str) -> int:
    if i >= len(args):
        print(f"{flag} requires an integer", file=sys.stderr)
        sys.exit(2)
    return int(args[i])


def _parse_since_arg(args: list[str], i: int) -> str:
    if i >= len(args):
        print("--since requires a date (YYYY-MM-DD)", file=sys.stderr)
        sys.exit(2)
    return args[i]


def main() -> None:
    json_mode, revisions, since_date = _parse_args(sys.argv[1:])

    if since_date:
        entries = _git_since(since_date)
    else:
        entries = _git_log(revisions)

    if not entries:
        print("No revisions found.", file=sys.stderr)
        sys.exit(0)

    snapshots = _collect_snapshots(entries)

    if json_mode:
        print(_format_json(snapshots))
    else:
        print(_format_text(snapshots))


if __name__ == "__main__":
    main()
