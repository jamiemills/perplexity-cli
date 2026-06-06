"""Generate static analysis reports for SonarQube integration.

Runs bandit with JSON report output for import via
``sonar.python.bandit.reportPaths``.

Ruff and semgrep are enforced via lefthook pre-commit hooks and are
not imported into SonarQube (SARIF external issues create duplicate
enforcement and can break the Quality Gate for intentionally-accepted
findings).

Reports are written to ``build/reports/`` which is gitignored.

Usage::

    uv run python scripts/generate_sonar_reports.py
"""

from __future__ import annotations

import logging
import subprocess  # nosec B404 — hardcoded tool commands only, no user input
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "src"
REPORT_DIR = PROJECT_ROOT / "build" / "reports"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Specification for a single analyser tool and its report output."""

    name: str
    command: list[str]
    output: Path


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="bandit",
        command=[
            "uvx",
            "--from",
            "bandit",
            "bandit",
            "-c",
            "pyproject.toml",
            "-r",
            str(SOURCE_DIR),
            "-f",
            "json",
            "-o",
            str(REPORT_DIR / "bandit-report.json"),
        ],
        output=REPORT_DIR / "bandit-report.json",
    ),
]


def _ensure_report_dir() -> None:
    """Create the report output directory if it does not exist."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)


def _report_exists(path: Path) -> bool:
    """Return True if *path* is a non-empty file."""
    return path.is_file() and path.stat().st_size > 0


def _log_failure(spec: ToolSpec, result: subprocess.CompletedProcess[str]) -> None:
    """Log diagnostic details when a tool fails to produce its report."""
    logger.error("%s: failed to generate report -> %s", spec.name, spec.output)
    if result.returncode != 0:
        logger.error("%s: exit code %d", spec.name, result.returncode)
    if result.stderr:
        logger.error("%s: stderr: %s", spec.name, result.stderr.strip())


def _run_tool(spec: ToolSpec) -> bool:
    """Run a single analyser tool and return True if the report was generated.

    Tools may exit non-zero when findings exist (e.g. bandit exits 1 for
    findings). This is expected — we care about the report file, not
    the exit code.
    """
    logger.info("Running %s...", spec.name)
    try:
        result = subprocess.run(  # nosec B603 — hardcoded commands, no user input
            spec.command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        logger.error("%s: command not found — is it installed?", spec.name)
        return False

    if _report_exists(spec.output):
        logger.info(
            "%s: report generated (%d bytes) -> %s",
            spec.name,
            spec.output.stat().st_size,
            spec.output,
        )
        return True

    _log_failure(spec, result)
    return False


def main() -> None:
    """Generate all static analysis reports for SonarQube."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    _ensure_report_dir()

    failures = [spec.name for spec in TOOLS if not _run_tool(spec)]

    if failures:
        logger.error("Failed to generate reports for: %s", ", ".join(failures))
        sys.exit(1)

    logger.info("All reports generated in %s/", REPORT_DIR)


if __name__ == "__main__":
    main()
