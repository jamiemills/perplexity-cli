"""Quality-ratchet gate tests.

Runs the fast ratchet gates and asserts they pass against their tracked
baselines, mirroring tests/test_semgrep_clean_code.py.  The slower
pyright-strict and semgrep-architecture ratchets are exercised directly by
``make check`` / CI (they are prerequisites of the ``check`` composite) and are
not re-run here to keep the default test suite fast.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_FAST_GATES = [
    "check_file_size.py",
    "check_suppressions.py",
    "check_ruff_architecture.py",
]


def _run_gate(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "python", f"scripts/{script}"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=120,
    )


@pytest.mark.parametrize("script", _FAST_GATES)
def test_ratchet_gate_passes(script: str) -> None:
    """Each fast ratchet gate passes against its baseline."""
    result = _run_gate(script)
    assert result.returncode == 0, (
        f"{script} reported a regression (new/grown findings):\n"
        f"{result.stdout}\n{result.stderr}\n"
        "Fix the finding, or refresh the baseline after intentional changes:\n"
        f"  uv run python scripts/{script} --update-baseline"
    )


def test_ratchet_baselines_exist() -> None:
    """Every ratchet has a tracked baseline file (proof the gate is initialised)."""
    baselines = PROJECT_ROOT / "quality" / "baselines"
    expected = {"file-size.json", "suppressions.json", "ruff-architecture.json"}
    present = {p.name for p in baselines.glob("*.json")}
    missing = expected - present
    assert not missing, (
        "Missing ratchet baseline(s); initialise with `<gate> --update-baseline`: "
        + ", ".join(sorted(missing))
    )
