"""Suppression ratchet gate — identity-fingerprint edition.

Tracks exact identities (not just per-file counts) for:
- Inline analyser-suppression comments
- Coverage pragmas
- Mutmut mutation-blocking pragmas
- Coverage configuration from pyproject.toml (omit, exclude_lines,
  exclude_also, partial_branches)
- Mutmut configuration from pyproject.toml (do_not_mutate)

Each identity is a ``file:line:type[:detail]`` fingerprint.
Moving, replacing, or broadening a suppression creates a new identity and
triggers a regression.

Usage::

    uv run python scripts/check_suppressions.py [--update-baseline]

Exit codes: 0 = pass, 1 = regression.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ratchet import (
    BASELINE_DIR,
    FingerprintDiff,
    add_update_flag,
    diff_fingerprints,
    save_fingerprints,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (PROJECT_ROOT / "src", PROJECT_ROOT / "scripts")
PYPROJECT = PROJECT_ROOT / "pyproject.toml"
BASELINE_NAME = "suppressions.json"
DESCRIPTION = "Suppression ratchet: block new, moved, or broadened suppressions."
_SCRIPT = Path(__file__).name

_NOQA_RE = re.compile(r"#\s*noqa\b(?:\s*:\s*(.+?))?(?=\s*$|\s*#)")
_NOSEMGREP_RE = re.compile(r"#\s*nosemgrep\b(?:\s*:\s*(.+?))?(?=\s*$|\s*#)")
_NOSEC_RE = re.compile(r"#\s*nosec\b")
_TYPE_IGNORE_RE = re.compile(r"#\s*type:\s*ignore(?:\s*\[\s*([^\]]*?)\s*\])?")
_PYRIGHT_IGNORE_RE = re.compile(r"#\s*pyright:\s*ignore(?:\s*\[\s*([^\]]*?)\s*\])?")

_PRAGMA_RE = re.compile(r"#\s*pragma:\s*no\s*(cover|branch|mutate)(?::\s*(.+?))?\s*(?:\s*#.*)?$")

_SUPPRESSION_TYPES: list[tuple[str, re.Pattern[str]]] = [
    ("noqa", _NOQA_RE),
    ("nosemgrep", _NOSEMGREP_RE),
    ("nosec", _NOSEC_RE),
    ("type-ignore", _TYPE_IGNORE_RE),
    ("pyright-ignore", _PYRIGHT_IGNORE_RE),
]


def _normalise_detail(detail: str | None) -> str | None:
    if detail is None:
        return None
    normalised = detail.strip().replace(" ", "")
    return normalised if normalised else None


def _make_identity(relative_path: str, line: int, stype: str, detail: str | None = None) -> str:
    if detail:
        return f"{relative_path}:{line}:{stype}:{detail}"
    return f"{relative_path}:{line}:{stype}"


def _extract_line_identities(rel: str, line_no: int, line: str) -> list[str]:
    """Extract all suppression/pragma identities from a single source line."""
    identities: list[str] = []
    for m in _PRAGMA_RE.finditer(line):
        kind = m.group(1)
        detail = _normalise_detail(m.group(2))
        identities.append(_make_identity(rel, line_no, f"no-{kind}", detail))
    for stype, regex in _SUPPRESSION_TYPES:
        for m in regex.finditer(line):
            try:
                detail = _normalise_detail(m.group(1))
            except IndexError:
                detail = None
            identities.append(_make_identity(rel, line_no, stype, detail))
    return identities


def _collect_source_identities(src_dir: Path, root: Path) -> list[str]:
    identities: list[str] = []
    for path in sorted(src_dir.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(root))
        for line_no, line in enumerate(text.splitlines(), start=1):
            identities.extend(_extract_line_identities(rel, line_no, line))
    return identities


def _extract_coverage_report_identities(report: dict[str, Any], pyproject_name: str) -> list[str]:
    """Yield identities from [tool.coverage.report] settings."""
    identities: list[str] = []
    for key, stype in [
        ("exclude_lines", "coverage-exclude-lines"),
        ("exclude_also", "coverage-exclude-also"),
        ("partial_branches", "coverage-partial-branch"),
    ]:
        for pattern in report.get(key, []):
            identities.append(_make_identity(pyproject_name, 0, stype, str(pattern)))
    return identities


def _collect_coverage_config_identities(pyproject: Path) -> list[str]:
    if not pyproject.is_file():
        return []
    try:
        config = tomllib.loads(pyproject.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return []

    coverage = config.get("tool", {}).get("coverage", {})
    identities: list[str] = []

    for pattern in coverage.get("run", {}).get("omit", []):
        identities.append(_make_identity(pyproject.name, 0, "coverage-omit", str(pattern)))

    identities.extend(
        _extract_coverage_report_identities(coverage.get("report", {}), pyproject.name)
    )
    return identities


def _collect_mutmut_config_identities(pyproject: Path) -> list[str]:
    if not pyproject.is_file():
        return []
    try:
        config = tomllib.loads(pyproject.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return []

    mutmut = config.get("tool", {}).get("mutmut", {})
    identities: list[str] = []

    for pattern in mutmut.get("do_not_mutate", []):
        identities.append(_make_identity(pyproject.name, 0, "mutmut-do-not-mutate", str(pattern)))
    return identities


def collect_identities() -> list[str]:
    identities: list[str] = []
    for source_root in SOURCE_ROOTS:
        identities.extend(_collect_source_identities(source_root, PROJECT_ROOT))
    identities.extend(_collect_coverage_config_identities(PYPROJECT))
    identities.extend(_collect_mutmut_config_identities(PYPROJECT))
    return sorted(identities)


def _migrate_legacy_baseline(name: str) -> list[str]:
    """Auto-migrate from count-based to fingerprint baseline."""
    identities = collect_identities()
    save_fingerprints(name, identities)
    print(
        "Suppression baseline migrated from count-based to identity-fingerprint format.",
        file=sys.stderr,
    )
    print(
        f"    Captured {len(identities)} identity/identities as the new baseline.",
        file=sys.stderr,
    )
    return identities


def _cast_fingerprints(raw: Any) -> list[str]:
    """Cast *raw* to a sorted list of fingerprint strings."""
    return sorted(str(fp) for fp in raw)


def _load_identities_from_data(baseline: Any) -> list[str] | None:
    """Extract fingerprints from loaded baseline data, or None on legacy format."""
    if isinstance(baseline, list):
        return _cast_fingerprints(baseline)
    try:
        return _cast_fingerprints(baseline["fingerprints"])
    except (KeyError, TypeError):
        return None


def _load_baseline_identities(name: str) -> list[str]:
    path = BASELINE_DIR / name
    if not path.is_file():
        return []
    baseline = json.loads(path.read_text())
    identities = _load_identities_from_data(baseline)
    if identities is not None:
        return identities
    return _migrate_legacy_baseline(name)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    add_update_flag(parser)
    return parser.parse_args()


def _report_pass(diff: FingerprintDiff, total: int) -> None:
    print(f"Suppression ratchet passed: {total} identity/identities tracked; no new suppressions.")
    if diff.removed:
        print("Removed suppressions (run with --update-baseline to capture):")
        for identity in sorted(diff.removed):
            print(f"  {identity}")


def _report_regression(diff: FingerprintDiff) -> int:
    print(
        "Suppression ratchet FAILED: new or changed suppressions.\n",
        file=sys.stderr,
    )
    if diff.new:
        for identity in sorted(diff.new):
            print(f"  NEW  {identity}", file=sys.stderr)
    if diff.removed:
        print(
            "\nRemoved identities (may indicate moved, replaced, or broadened suppressions):",
            file=sys.stderr,
        )
        for identity in sorted(diff.removed):
            print(f"  GONE {identity}", file=sys.stderr)
    print(
        "\nFix the underlying finding, or justify and refresh the baseline:\n"
        f"  uv run python scripts/{_SCRIPT} --update-baseline",
        file=sys.stderr,
    )
    return 1


def main() -> None:
    args = _parse_args()
    current = collect_identities()

    if args.update_baseline:
        path = save_fingerprints(BASELINE_NAME, current)
        print(f"Suppression baseline refreshed: {len(current)} identity/identities -> {path}")
        return

    baseline = _load_baseline_identities(BASELINE_NAME)
    diff = diff_fingerprints(current, baseline)
    if diff.is_regression:
        sys.exit(_report_regression(diff))
    _report_pass(diff, len(current))


if __name__ == "__main__":
    main()
