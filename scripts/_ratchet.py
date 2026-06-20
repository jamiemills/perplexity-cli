"""Shared baseline-ratchet helpers for the quality gates.

A ratchet gate captures the *current* findings as a JSON baseline and then
fails on growth: new findings or increased counts are regressions, while
shrinking is always allowed (and becomes the new baseline via
``--update-baseline``).  This lets the repo record existing debt from
``.claude/thermo-nuclear-review.md`` as accepted, while blocking future work
from reintroducing or worsening the same classes of issue.

Two flavours are supported:

* **counts** — ``{relative_path: int}`` (file-size, suppressions).
* **fingerprints** — ``[str, ...]`` stable finding IDs (ruff/pyright/semgrep).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_DIR = PROJECT_ROOT / "quality" / "baselines"


@dataclass
class CountDiff:
    """Result of comparing current per-file counts against a baseline."""

    new: dict[str, int] = field(default_factory=dict)
    grown: dict[str, tuple[int, int]] = field(default_factory=dict)
    shrunk: dict[str, tuple[int, int]] = field(default_factory=dict)
    baseline_total: int = 0
    current_total: int = 0

    @property
    def is_regression(self) -> bool:
        """True if any new file or grown count was introduced."""
        return bool(self.new) or bool(self.grown)


@dataclass
class FingerprintDiff:
    """Result of comparing current finding fingerprints against a baseline."""

    new: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def is_regression(self) -> bool:
        """True if any fingerprint absent from the baseline appeared."""
        return bool(self.new)


def add_update_flag(parser: argparse.ArgumentParser) -> None:
    """Register the common ``--update-baseline`` flag on a parser."""
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Refresh the baseline file with the current findings (use after fixes).",
    )


def _baseline_path(name: str) -> Path:
    return BASELINE_DIR / name


def load_counts(name: str) -> dict[str, int]:
    """Load a counts baseline, returning an empty map when absent."""
    path = _baseline_path(name)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text())
    return {str(k): int(v) for k, v in data.items()}


def save_counts(name: str, counts: dict[str, int]) -> Path:
    """Persist a counts baseline, creating the directory if necessary."""
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    path = _baseline_path(name)
    payload = dict(sorted(counts.items()))
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def load_fingerprints(name: str) -> list[str]:
    """Load a fingerprint baseline, returning an empty list when absent."""
    path = _baseline_path(name)
    if not path.is_file():
        return []
    data = json.loads(path.read_text())
    items = data.get("fingerprints", data) if isinstance(data, dict) else data
    return sorted(str(item) for item in items)


def save_fingerprints(name: str, fingerprints: list[str]) -> Path:
    """Persist a fingerprint baseline, creating the directory if necessary."""
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    path = _baseline_path(name)
    payload = {"fingerprints": sorted(set(fingerprints))}
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def _changed(
    current: dict[str, int], baseline: dict[str, int], *, grown: bool
) -> dict[str, tuple[int, int]]:
    """Return ``{file: (previous, current)}`` for files that grew or shrunk."""
    result: dict[str, tuple[int, int]] = {}
    for file, count in current.items():
        previous = baseline.get(file)
        if previous is None:
            continue
        if (count > previous) if grown else (count < previous):
            result[file] = (previous, count)
    return dict(sorted(result.items()))


def diff_counts(current: dict[str, int], baseline: dict[str, int]) -> CountDiff:
    """Compare current per-file counts with the baseline."""
    new = {f: n for f, n in current.items() if f not in baseline and n > 0}
    return CountDiff(
        new=dict(sorted(new.items())),
        grown=_changed(current, baseline, grown=True),
        shrunk=_changed(current, baseline, grown=False),
        baseline_total=sum(baseline.values()),
        current_total=sum(current.values()),
    )


def diff_fingerprints(current: list[str], baseline: list[str]) -> FingerprintDiff:
    """Compare current finding fingerprints with the baseline."""
    current_set = set(current)
    baseline_set = set(baseline)
    return FingerprintDiff(
        new=sorted(current_set - baseline_set),
        removed=sorted(baseline_set - current_set),
    )
