from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_GIT_BIN = shutil.which("git")

FORBIDDEN_PATHS = (
    "*.swp",
    ".sonar/.sonar_lock",
    ".home/.config/perplexity-cli/**",
    "coverage.xml",
    "coverage.json",
    "htmlcov/**",
    "build/**",
    "dist/**",
    "mutants/**",
    "*.egg-info/**",
    ".safety-project.ini",
)


def _tracked_forbidden_paths() -> list[str]:
    assert _GIT_BIN is not None, "git binary not found on PATH"
    result = subprocess.run(
        [
            _GIT_BIN,
            "ls-files",
            "--",
            *FORBIDDEN_PATHS,
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        check=False,
    )
    assert result.returncode == 0, (
        f"git ls-files failed while checking repository hygiene:\n{result.stdout}{result.stderr}"
    )
    return [line for line in result.stdout.splitlines() if line]


@pytest.mark.skipif(_GIT_BIN is None, reason="git not installed")
def test_no_forbidden_tracked_repository_hygiene_artifacts() -> None:
    tracked = _tracked_forbidden_paths()

    assert tracked == [], (
        "Git tracks forbidden repository hygiene artefacts:\n"
        + "\n".join(f"  - {path}" for path in tracked)
        + "\n\n"
        "Remove these paths from the index in the repository-health cleanup task. "
        "This guard intentionally fails until those artefacts are untracked."
    )
