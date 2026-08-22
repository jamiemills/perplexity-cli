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

Suppressions are extracted with Python's tokeniser so only real ``#``
comments are scanned — suppression-like text inside strings or docstrings is
ignored.

Usage::

    uv run python scripts/check_suppressions.py [--update-baseline]

Exit codes: 0 = pass, 1 = regression, 2 = tool/configuration error.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import tokenize
import tomllib
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))
from scripts._ratchet import (
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


class ToolError(Exception):
    """Raised when identities cannot be computed reliably (fail-closed)."""


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
    """Build one suppression identity (content-anchored via _ANCHOR_CONTEXT)."""
    anchor = _ANCHOR_CONTEXT.get("text", "")
    code = _anchored_code_line(anchor, line) if anchor else ""
    if code:
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()[:8]
        if detail:
            return f"{relative_path}:{stype}:{digest}:{detail}"
        return f"{relative_path}:{stype}:{digest}"
    if detail:
        return f"{relative_path}:{line}:{stype}:{detail}"
    return f"{relative_path}:{line}:{stype}"


_ANCHOR_CONTEXT: dict[str, str] = {}


def _anchored_code_line(text: str, line_no: int) -> str:
    """Return the nearest code statement at/after the annotated line.

    Comment-only lines are skipped so annotations sitting above a statement
    still bind to it.  Returns an empty string when no code follows, which
    degrades the identity to the historical line-number form.
    """
    lines = text.splitlines()
    index = min(line_no, len(lines)) - 1
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:200]
        index += 1
    return ""


def _extract_comment_identities(rel: str, line_no: int, source_text: str) -> list[str]:
    """Extract all suppression/pragma identities from one annotated line."""
    comment_lines = source_text.splitlines()
    raw_comment = comment_lines[line_no - 1] if line_no <= len(comment_lines) else ""
    # The regexes operate on the comment token; re-derive from the full line.
    identities: list[str] = []
    for m in _PRAGMA_RE.finditer(raw_comment):
        kind = m.group(1)
        detail = _normalise_detail(m.group(2))
        identities.append(_make_identity(rel, line_no, f"no-{kind}", detail))
    for stype, regex in _SUPPRESSION_TYPES:
        for m in regex.finditer(raw_comment):
            try:
                detail = _normalise_detail(m.group(1))
            except IndexError:
                detail = None
            identities.append(_make_identity(rel, line_no, stype, detail))
    return identities


def _iter_comment_tokens(text: str, path: Path) -> list[tuple[int, str]]:
    """Return ``(line_no, comment_text)`` pairs for real comment tokens.

    Raises:
        ToolError: When the source cannot be tokenised.
    """
    try:
        return [
            (tok.start[0], tok.string)
            for tok in tokenize.tokenize(io.BytesIO(text.encode("utf-8")).readline)
            if tok.type == tokenize.COMMENT
        ]
    except (tokenize.TokenError, SyntaxError) as exc:
        msg = f"Source file cannot be tokenised: {path}"
        raise ToolError(msg) from exc


def _collect_source_identities(src_dir: Path, root: Path) -> list[str]:
    identities: list[str] = []
    for path in sorted(src_dir.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            msg = f"Unreadable source file: {path}"
            raise ToolError(msg) from exc
        rel = str(path.relative_to(root))
        _ANCHOR_CONTEXT["text"] = text
        try:
            file_identities: list[str] = []
            for line_no, _comment in _iter_comment_tokens(text, path):
                file_identities.extend(_extract_comment_identities(rel, line_no, text))
        finally:
            _ANCHOR_CONTEXT.clear()
        identities.extend(_disambiguate_duplicates(file_identities))
    return identities


def _disambiguate_duplicates(file_identities: list[str]) -> list[str]:
    """Append occurrence ordinals so byte-identical anchors stay distinct."""
    seen: dict[str, int] = {}
    result: list[str] = []
    for identity in file_identities:
        count = seen.get(identity, 0) + 1
        seen[identity] = count
        result.append(identity if count == 1 else f"{identity}#{count}")
    return result


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


def _load_tool_config(pyproject: Path) -> dict[str, Any]:
    """Parse pyproject.toml, raising a ToolError when it is unreadable."""
    if not pyproject.is_file():
        return {}
    try:
        return tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        msg = f"Failed to read or parse {pyproject}"
        raise ToolError(msg) from exc


def _collect_coverage_config_identities(pyproject: Path) -> list[str]:
    config = _load_tool_config(pyproject)
    coverage = config.get("tool", {}).get("coverage", {})
    identities: list[str] = []

    for pattern in coverage.get("run", {}).get("omit", []):
        identities.append(_make_identity(pyproject.name, 0, "coverage-omit", str(pattern)))

    identities.extend(
        _extract_coverage_report_identities(coverage.get("report", {}), pyproject.name)
    )
    return identities


def _collect_mutmut_config_identities(pyproject: Path) -> list[str]:
    config = _load_tool_config(pyproject)
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
    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"Unreadable or unparseable baseline: {path}"
        raise ToolError(msg) from exc
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
    try:
        current = collect_identities()

        if args.update_baseline:
            path = save_fingerprints(BASELINE_NAME, current)
            print(f"Suppression baseline refreshed: {len(current)} identity/identities -> {path}")
            return

        baseline = _load_baseline_identities(BASELINE_NAME)
    except ToolError as exc:
        print(f"Suppression ratchet tool error: {exc}", file=sys.stderr)
        sys.exit(2)
    else:
        diff = diff_fingerprints(current, baseline)
        if diff.is_regression:
            sys.exit(_report_regression(diff))
        _report_pass(diff, len(current))


if __name__ == "__main__":
    main()
