"""Semgrep clean-code rule enforcement tests.

These tests run Semgrep through the canonical Make target with the project's
custom rules and reviewed community-rule snapshots to
ensure no WARNING or ERROR-severity findings are present in the source
tree.  INFO-level findings are advisory and do not block.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEMGREP_CONFIG = PROJECT_ROOT / ".semgrep.yml"
SNAPSHOT_MANIFEST = PROJECT_ROOT / "quality" / "semgrep-snapshot.json"


def _run_semgrep(*extra_args: str) -> subprocess.CompletedProcess[str]:
    """Run semgrep against the project root and return the result."""
    target = " ".join(extra_args) if extra_args else "."
    cmd = ["make", "semgrep", f"SEMGREP_TARGETS={target}"]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=120,
    )


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


def test_no_semgrep_warnings_or_errors() -> None:
    """Semgrep finds zero WARNING/ERROR-severity findings in the source tree."""
    result = _run_semgrep()

    assert result.returncode == 0, (
        "Semgrep detected WARNING or ERROR-level findings:\n"
        f"{result.stdout}\n{result.stderr}\n"
        "Fix the findings, or add an inline '# nosemgrep: <rule-id>' "
        "comment with a justification if the finding is a false positive."
    )
