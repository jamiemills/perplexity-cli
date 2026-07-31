"""Semgrep clean-code rule enforcement tests.

These tests verify the project's custom rules against the canonical
Semgrep wrapper (scripts/semgrep_policy.py).

Two dimensions are tested:
  - Blocking mode: zero WARNING/ERROR-severity findings must be present
    in the source tree.
  - Advisory mode: INFO-level findings are reported but do not fail.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEMGREP_CONFIG = PROJECT_ROOT / ".semgrep.yml"
SNAPSHOT_MANIFEST = PROJECT_ROOT / "quality" / "semgrep-snapshot.json"
WRAPPER = PROJECT_ROOT / "scripts" / "semgrep_policy.py"


def test_semgrep_config_exists() -> None:
    """The project and reviewed Semgrep configurations exist and match hashes."""
    assert SEMGREP_CONFIG.is_file(), (
        f"Semgrep config not found at {SEMGREP_CONFIG}. "
        "This file defines the project's custom clean-code rules."
    )
    manifest = json.loads(SNAPSHOT_MANIFEST.read_text(encoding="utf-8"))
    for pack in manifest["packs"].values():
        config = PROJECT_ROOT / pack["file"]
        assert config.is_file(), f"Semgrep snapshot not found: {config}"
        digest = hashlib.sha256(config.read_bytes()).hexdigest()
        assert digest == pack["sha256"], f"Semgrep snapshot changed without manifest: {config}"


def test_no_semgrep_warnings_or_errors_via_wrapper() -> None:
    """Semgrep blocking mode reports a clean ERROR/WARNING source tree."""
    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(WRAPPER),
            "--blocking",
            "--config",
            str(SEMGREP_CONFIG),
            "--config",
            str(PROJECT_ROOT / ".semgrep-community-python.yml"),
            "--config",
            str(PROJECT_ROOT / ".semgrep-community-comment.yml"),
            "--config",
            str(PROJECT_ROOT / ".semgrep-community-best-practices.yml"),
            "--severity",
            "ERROR",
            "--severity",
            "WARNING",
            "--exclude",
            "tests/",
            "--exclude",
            ".semgrep-community-*.yml",
            "--exclude",
            ".github/",
            ".",
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=300,
    )
    assert result.returncode == 0, (
        f"Semgrep blocking mode failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "Semgrep: no findings." in result.stdout


def test_semgrep_advisory_runs_without_failure() -> None:
    """Semgrep advisory mode runs and produces output without crashing."""
    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(WRAPPER),
            "--advisory",
            "--config",
            str(SEMGREP_CONFIG),
            "--severity",
            "ERROR",
            "--severity",
            "WARNING",
            "--severity",
            "INFO",
            "--exclude",
            "tests/",
            "--exclude",
            ".semgrep-community-*.yml",
            "--exclude",
            ".github/",
            ".",
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=300,
    )
    assert result.returncode == 0, (
        f"Semgrep advisory mode failed unexpectedly:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "Semgrep:" in result.stdout, "Wrapper failed to produce output in advisory mode"
