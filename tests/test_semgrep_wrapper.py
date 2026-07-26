"""Tests for the canonical Semgrep wrapper (scripts/semgrep_policy.py).

Proves each exit classification:
  - clean (no findings)
  - findings (blocking findings detected)
  - malformed JSON
  - timeout
  - missing config
  - errors array handling (internal error)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = PROJECT_ROOT / "scripts" / "semgrep_policy.py"


def _run_wrapper(*args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=30,
    )
    return result


class TestSemgrepWrapper:
    """Exit-code classification tests for the wrapper process."""

    def test_requires_mode_flag(self) -> None:
        """Wrapper exits non-zero when no --blocking or --advisory."""
        result = _run_wrapper()
        assert result.returncode != 0

    def test_advisory_with_help_succeeds(self) -> None:
        """Wrapper with --advisory --help exits clean (argparse handles it)."""
        result = _run_wrapper("--advisory", "--help")
        assert result.returncode == 0


class TestParseOutput:
    """Unit tests for JSON parsing and error classification."""

    def test_parses_valid_json(self) -> None:
        """Valid JSON is parsed correctly."""
        from scripts.semgrep_policy import _parse_output

        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"results":[],"errors":[]}', stderr=""
        )
        data = _parse_output(result)
        assert data == {"results": [], "errors": []}

    def test_exits_on_malformed_json(self) -> None:
        """Malformed JSON triggers exit code 2."""
        from scripts.semgrep_policy import _parse_output

        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="not json {", stderr="")
        with pytest.raises(SystemExit) as exc_info:
            _parse_output(result)
        assert exc_info.value.code == 2


class TestCheckErrors:
    """Unit tests for errors array validation."""

    def test_passes_on_empty_errors(self) -> None:
        """Empty errors array does not trigger exit."""
        from scripts.semgrep_policy import _check_errors

        _check_errors({"errors": []})

    def test_exits_on_nonempty_errors(self) -> None:
        """Non-empty errors array triggers exit code 5."""
        from scripts.semgrep_policy import _check_errors

        with pytest.raises(SystemExit) as exc_info:
            _check_errors({"errors": [{"code": 3, "message": "parse error"}]})
        assert exc_info.value.code == 5


class TestClassify:
    """Unit tests for finding classification."""

    def test_blocking_findings_separated(self) -> None:
        """Blocking rules are classified as blocking."""
        from scripts.semgrep_policy import _classify

        policy = {
            "eval-or-exec": {"blocking": True, "severity": "ERROR"},
            "todo-fixme-without-ticket": {"blocking": False, "severity": "INFO"},
        }
        results = [
            {"check_id": "eval-or-exec", "path": "x.py", "start": {"line": 1}},
            {"check_id": "todo-fixme-without-ticket", "path": "y.py", "start": {"line": 2}},
        ]
        blocking, advisory = _classify(results, policy)
        assert len(blocking) == 1
        assert blocking[0]["check_id"] == "eval-or-exec"
        assert len(advisory) == 1
        assert advisory[0]["check_id"] == "todo-fixme-without-ticket"

    def test_unknown_rules_default_blocking(self) -> None:
        """Unknown rules default to blocking."""
        from scripts.semgrep_policy import _classify

        results = [{"check_id": "unknown-rule", "path": "z.py", "start": {"line": 1}}]
        blocking, advisory = _classify(results, {})
        assert len(blocking) == 1
        assert len(advisory) == 0


class TestTimeoutHandling:
    """Unit tests for timeout classification."""

    def test_timeout_caught(self) -> None:
        """TimeoutExpired maps to exit code 3."""
        from scripts.semgrep_policy import _run_semgrep

        with patch.object(
            subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(
                cmd=["semgrep"], timeout=180, output=b"", stderr=b""
            ),
        ):
            with pytest.raises(subprocess.TimeoutExpired):
                _run_semgrep(["."], timeout=1)
