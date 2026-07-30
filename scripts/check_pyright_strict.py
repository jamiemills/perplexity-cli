"""Pyright strict ratchet gate.

Runs Pyright in ``strict`` mode against ``src/`` (using a dedicated config so
the standard ``make typecheck-pyright`` is unaffected) and ratchets the
diagnostics against ``quality/baselines/pyright-strict.json``.

Existing ``Any`` / untyped-boundary diagnostics (documented in
``.claude/thermo-nuclear-review.md`` section 3) are captured as accepted debt;
the gate fails only on *new* strict diagnostics, blocking future boundary
erosion without forcing the full typed-model refactor now.

Usage::

    uv run python scripts/check_pyright_strict.py [--update-baseline]

Exit codes: 0 = pass, 1 = regression.
"""

from __future__ import annotations

import argparse
import json

# owner: quality-infrastructure; reason: invoke Pyright with a static argv and no shell
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, TypeGuard

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ratchet import (
    FingerprintDiff,
    add_update_flag,
    diff_fingerprints,
    load_fingerprints,
    save_fingerprints,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMP_CONFIG = PROJECT_ROOT / ".pyright.strict.tmp.json"
BASELINE_NAME = "pyright-strict.json"
DESCRIPTION = "Pyright strict ratchet: block new Any/unknown diagnostics."
_SCRIPT = Path(__file__).name

_STRICT_CONFIG: dict[str, object] = {
    "include": ["src/"],
    "typeCheckingMode": "strict",
    "pythonVersion": "3.12",
    "reportMissingTypeStubs": "none",
}

# Pyright exit codes: 0 = no findings, 1 = findings present, >=2 = tool crash.
_TOOL_ERROR_EXIT_THRESHOLD = 2


class DiagnosticPosition(TypedDict):
    """Source position in a Pyright diagnostic."""

    line: int
    character: int


class DiagnosticRange(TypedDict):
    """Source range fields used by the ratchet fingerprint."""

    start: DiagnosticPosition


class PyrightDiagnostic(TypedDict):
    """Validated Pyright diagnostic fields used by this gate."""

    file: str
    range: DiagnosticRange
    rule: str
    severity: str
    message: str


@dataclass(frozen=True, slots=True)
class PyrightOptions:
    """Immutable Pyright ratchet command-line options."""

    update_baseline: bool


def _is_object_dict(value: object) -> TypeGuard[dict[str, object]]:
    """Return whether a decoded JSON value is an object."""
    return isinstance(value, dict)


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    """Return whether a decoded JSON value is an array."""
    return isinstance(value, list)


def _parse_args() -> PyrightOptions:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    add_update_flag(parser)
    parsed = parser.parse_args()
    update_baseline: object = parsed.update_baseline
    return PyrightOptions(update_baseline=update_baseline is True)


def _required_object(mapping: dict[str, object], key: str) -> dict[str, object]:
    """Return a required JSON object field or raise a schema error."""
    value = mapping.get(key)
    if not _is_object_dict(value):
        msg = f"Pyright diagnostic field '{key}' must be an object."
        raise RuntimeError(msg)
    return value


def _required_string(mapping: dict[str, object], key: str) -> str:
    """Return a required JSON string field or raise a schema error."""
    value = mapping.get(key)
    if not isinstance(value, str):
        msg = f"Pyright diagnostic field '{key}' must be a string."
        raise RuntimeError(msg)
    return value


def _required_int(mapping: dict[str, object], key: str) -> int:
    """Return a required JSON integer field or raise a schema error."""
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f"Pyright diagnostic field '{key}' must be an integer."
        raise RuntimeError(msg)
    return value


def _position(value: dict[str, object]) -> DiagnosticPosition:
    """Validate a decoded Pyright source position."""
    return {
        "line": _required_int(value, "line"),
        "character": _required_int(value, "character"),
    }


def _diagnostic(value: object) -> PyrightDiagnostic:
    """Validate one decoded Pyright diagnostic."""
    if not _is_object_dict(value):
        msg = "Every Pyright generalDiagnostics entry must be an object."
        raise RuntimeError(msg)
    range_value = _required_object(value, "range")
    start_value = _required_object(range_value, "start")
    return {
        "file": _required_string(value, "file"),
        "range": {"start": _position(start_value)},
        "rule": _required_string(value, "rule"),
        "severity": _required_string(value, "severity"),
        "message": _required_string(value, "message"),
    }


def _parse_diagnostics(stdout: str) -> list[PyrightDiagnostic]:
    """Decode and validate the diagnostics array from Pyright JSON."""
    decoded: object = json.loads(stdout or "{}")
    if not _is_object_dict(decoded):
        msg = "Pyright JSON root must be an object."
        raise RuntimeError(msg)
    raw_diagnostics = decoded.get("generalDiagnostics", [])
    if not _is_object_list(raw_diagnostics):
        msg = "Pyright generalDiagnostics must be an array."
        raise RuntimeError(msg)
    diagnostics: list[PyrightDiagnostic] = []
    for value in raw_diagnostics:
        diagnostics.append(_diagnostic(value))
    return diagnostics


def _fingerprint(diag: PyrightDiagnostic) -> str:
    """Create a stable identifier from a Pyright diagnostic."""
    start = diag["range"]["start"]
    file_path = diag["file"]
    root_prefix = str(PROJECT_ROOT) + "/"
    if file_path.startswith(root_prefix):
        file_path = file_path[len(root_prefix) :]
    return "{}:{}:{}:{}".format(
        file_path,
        start["line"],
        start["character"],
        diag["rule"] or diag["message"][:40],
    )


def collect_findings() -> list[str]:
    """Run Pyright in strict mode and return sorted diagnostic fingerprints."""
    TEMP_CONFIG.write_text(json.dumps(_STRICT_CONFIG), encoding="utf-8")
    cmd = ["uv", "run", "pyright", "-p", str(TEMP_CONFIG), "--outputjson"]
    try:
        # owner: quality-infrastructure; reason: static argv uses a project-owned config without a shell
        result = subprocess.run(  # nosec B603
            cmd,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=300,
            check=False,
        )
    finally:
        TEMP_CONFIG.unlink(missing_ok=True)
    try:
        diagnostics = _parse_diagnostics(result.stdout)
    except json.JSONDecodeError as exc:
        detail = result.stderr.strip() or "Pyright produced unparseable output."
        raise RuntimeError(detail) from exc
    # Pyright can exit non-zero for findings — that is expected.
    # Only exit >=2 signals a tool crash.
    is_tool_error = result.returncode >= _TOOL_ERROR_EXIT_THRESHOLD
    if is_tool_error:
        raise RuntimeError(
            result.stderr.strip() or f"Pyright exited with status {result.returncode}."
        )
    return sorted({_fingerprint(diagnostic) for diagnostic in diagnostics})


def _report_pass(diff: FingerprintDiff, count: int) -> None:
    """Print a passing summary with optional shrinkage note."""
    print(f"Pyright strict ratchet passed: {count} baselined diagnostic(s); no new findings.")
    if diff.removed:
        print(
            f"Improvement: {len(diff.removed)} diagnostic(s) cleared "
            "(run with --update-baseline to capture)."
        )


def _report_regression(diff: FingerprintDiff) -> int:
    """Print a regression report and return exit code 1."""
    print("Pyright strict ratchet FAILED: new strict diagnostics.\n", file=sys.stderr)
    for fingerprint in diff.new:
        print(f"  NEW  {fingerprint}", file=sys.stderr)
    print(
        "\nFix the typing, or refresh the baseline after intentional changes:\n"
        f"  uv run python scripts/{_SCRIPT} --update-baseline",
        file=sys.stderr,
    )
    return 1


def main() -> None:
    """Entry point: collect diagnostics, ratchet, and report."""
    args = _parse_args()
    try:
        current = collect_findings()
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"Pyright strict gate could not run: {exc}", file=sys.stderr)
        sys.exit(2)

    if args.update_baseline:
        path = save_fingerprints(BASELINE_NAME, current)
        print(f"Pyright strict baseline refreshed: {len(current)} diagnostic(s) -> {path}")
        return

    diff = diff_fingerprints(current, load_fingerprints(BASELINE_NAME))
    if diff.is_regression:
        sys.exit(_report_regression(diff))
    _report_pass(diff, len(current))


if __name__ == "__main__":
    main()
