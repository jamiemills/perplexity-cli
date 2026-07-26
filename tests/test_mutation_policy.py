"""Fixture-based tests for the canonical mutation policy wrapper.

The tests cover the canonical policy outcomes described in
``scripts/mutation_policy.py``:

* clean   — no actionable mutants
* findings — survived, timeout or suspicious mutants detected
* tool-error — mutmut unavailable, output unparseable, or schema drift

No real mutation testing is performed; every scenario is driven by
fixtures under ``tests/fixtures/mutation_policy``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "mutation_policy"
SCHEMA = PROJECT_ROOT / "quality" / "schemas" / "mutation-report.json"

VERSION_FIXTURE = "mutmut, version 3.5.0\n"


def _fixture_text(name: str) -> str:
    """Read the ``results.txt`` fixture for ``name``."""
    return (FIXTURES / name / "results.txt").read_text()


def _import_module():
    """Import the wrapper module (after sys.path is configured)."""
    from scripts import mutation_policy

    return mutation_policy


# ---------------------------------------------------------------------------
# parse_results_text unit tests
# ---------------------------------------------------------------------------


class TestParseResultsText:
    """Direct tests of the pure parser using fixture content."""

    def test_all_killed_parses(self) -> None:
        """All-killed fixture yields four killed entries."""
        mod = _import_module()
        entries = mod.parse_results_text(_fixture_text("all-killed"))
        assert len(entries) == 4
        assert all(entry.category == "killed" for entry in entries)

    def test_survived_parses(self) -> None:
        """Survived fixture yields two survived entries."""
        mod = _import_module()
        entries = mod.parse_results_text(_fixture_text("survived"))
        survived = [entry for entry in entries if entry.category == "survived"]
        assert len(survived) == 2

    def test_timeout_parses(self) -> None:
        """Timeout fixture yields one timeout entry."""
        mod = _import_module()
        entries = mod.parse_results_text(_fixture_text("timeout"))
        timeouts = [entry for entry in entries if entry.category == "timeout"]
        assert len(timeouts) == 1

    def test_suspicious_parses(self) -> None:
        """Suspicious fixture yields one suspicious entry."""
        mod = _import_module()
        entries = mod.parse_results_text(_fixture_text("suspicious"))
        suspicious = [entry for entry in entries if entry.category == "suspicious"]
        assert len(suspicious) == 1

    def test_not_checked_normalised(self) -> None:
        """Raw 'not checked' (two words) normalises to the not_checked category."""
        mod = _import_module()
        text = "    pkg.module.fn__mutmut_1: not checked\n"
        entries = mod.parse_results_text(text)
        assert entries[0].category == "not_checked"
        assert entries[0].status == "not checked"

    def test_empty_yields_no_entries(self) -> None:
        """Empty fixture produces an empty list."""
        mod = _import_module()
        assert mod.parse_results_text(_fixture_text("empty")) == []

    def test_malformed_raises_results_parse_error(self) -> None:
        """Malformed fixture raises ResultsParseError (line-format drift)."""
        mod = _import_module()
        with pytest.raises(mod.ResultsParseError):
            mod.parse_results_text(_fixture_text("malformed"))

    def test_unknown_status_raises(self) -> None:
        """Unknown status fixture raises UnknownStatusError (status drift)."""
        mod = _import_module()
        with pytest.raises(mod.UnknownStatusError):
            mod.parse_results_text(_fixture_text("unknown-status"))

    def test_blank_lines_ignored(self) -> None:
        """Blank lines and trailing whitespace do not break parsing."""
        mod = _import_module()
        text = "\n    pkg.fn__mutmut_1: killed\n\n    pkg.fn__mutmut_2: killed\n\n"
        entries = mod.parse_results_text(text)
        assert len(entries) == 2


# ---------------------------------------------------------------------------
# parse_version_text unit tests
# ---------------------------------------------------------------------------


class TestParseVersionText:
    """Direct tests for the version-output parser."""

    def test_parses_known_version(self) -> None:
        """Standard mutmut version output is parsed."""
        mod = _import_module()
        assert mod.parse_version_text(VERSION_FIXTURE) == "3.5.0"

    def test_rejects_unparseable_version(self) -> None:
        """Unexpected version output raises MutmutUnavailableError."""
        mod = _import_module()
        with pytest.raises(mod.MutmutUnavailableError):
            mod.parse_version_text("mutmut 3.5.0\n")


# ---------------------------------------------------------------------------
# build_report unit tests
# ---------------------------------------------------------------------------


class TestBuildReport:
    """Direct tests for the report builder."""

    def test_clean_report(self) -> None:
        """All-killed entries produce a clean report."""
        mod = _import_module()
        entries = mod.parse_results_text(_fixture_text("all-killed"))
        report = mod.build_report("3.5.0", entries)
        assert report.status == "clean"
        assert report.total_mutants == 4
        assert report.categories.killed == 4
        assert report.survivors == ()
        assert report.error == ""

    def test_findings_report(self) -> None:
        """Survived entries produce a findings report with survivors."""
        mod = _import_module()
        entries = mod.parse_results_text(_fixture_text("survived"))
        report = mod.build_report("3.5.0", entries)
        assert report.status == "findings"
        assert len(report.survivors) == 2
        assert all(s.category == "survived" for s in report.survivors)

    def test_tool_error_report(self) -> None:
        """Tool-error report has empty counts and the diagnostic message."""
        mod = _import_module()
        report = mod.build_tool_error_report("boom")
        assert report.status == "tool-error"
        assert report.total_mutants == 0
        assert report.survivors == ()
        assert report.error == "boom"
        assert report.version == "unknown"


# ---------------------------------------------------------------------------
# run_policy integration tests (no subprocess)
# ---------------------------------------------------------------------------


class TestRunPolicy:
    """End-to-end policy tests using fixture content directly."""

    def test_all_killed_exits_clean(self, tmp_path: Path) -> None:
        """All-killed fixture exits 0."""
        mod = _import_module()
        exit_code = mod.run_policy("3.5.0", _fixture_text("all-killed"), None)
        assert exit_code == mod.EXIT_CLEAN

    def test_survived_exits_findings(self, tmp_path: Path) -> None:
        """Survived fixture exits 1."""
        mod = _import_module()
        exit_code = mod.run_policy("3.5.0", _fixture_text("survived"), None)
        assert exit_code == mod.EXIT_FINDINGS

    def test_timeout_exits_findings(self, tmp_path: Path) -> None:
        """Timeout fixture exits 1."""
        mod = _import_module()
        exit_code = mod.run_policy("3.5.0", _fixture_text("timeout"), None)
        assert exit_code == mod.EXIT_FINDINGS

    def test_suspicious_exits_findings(self, tmp_path: Path) -> None:
        """Suspicious fixture exits 1."""
        mod = _import_module()
        exit_code = mod.run_policy("3.5.0", _fixture_text("suspicious"), None)
        assert exit_code == mod.EXIT_FINDINGS

    def test_empty_exits_clean(self, tmp_path: Path) -> None:
        """Empty fixture exits 0."""
        mod = _import_module()
        exit_code = mod.run_policy("3.5.0", _fixture_text("empty"), None)
        assert exit_code == mod.EXIT_CLEAN

    def test_malformed_exits_tool_error(self, tmp_path: Path) -> None:
        """Malformed fixture exits 2 (schema drift)."""
        mod = _import_module()
        exit_code = mod.run_policy("3.5.0", _fixture_text("malformed"), None)
        assert exit_code == mod.EXIT_TOOL_ERROR

    def test_unknown_status_exits_tool_error(self, tmp_path: Path) -> None:
        """Unknown status fixture exits 2 (schema drift)."""
        mod = _import_module()
        exit_code = mod.run_policy("3.5.0", _fixture_text("unknown-status"), None)
        assert exit_code == mod.EXIT_TOOL_ERROR

    def test_clean_report_written(self, tmp_path: Path) -> None:
        """Report file is written for the clean case."""
        mod = _import_module()
        report_path = tmp_path / "report.json"
        exit_code = mod.run_policy(
            "3.5.0", _fixture_text("all-killed"), report_path
        )
        assert exit_code == mod.EXIT_CLEAN
        assert report_path.exists()
        payload = json.loads(report_path.read_text())
        assert payload["status"] == "clean"

    def test_findings_report_written_before_exit(self, tmp_path: Path) -> None:
        """Report file is written before the non-zero findings exit code."""
        mod = _import_module()
        report_path = tmp_path / "report.json"
        exit_code = mod.run_policy(
            "3.5.0", _fixture_text("survived"), report_path
        )
        assert exit_code == mod.EXIT_FINDINGS
        assert report_path.exists()
        payload = json.loads(report_path.read_text())
        assert payload["status"] == "findings"
        assert len(payload["survivors"]) == 2

    def test_tool_error_report_written_before_exit(self, tmp_path: Path) -> None:
        """Report file (status tool-error) is written before exit code 2."""
        mod = _import_module()
        report_path = tmp_path / "report.json"
        exit_code = mod.run_policy(
            "3.5.0", _fixture_text("malformed"), report_path
        )
        assert exit_code == mod.EXIT_TOOL_ERROR
        assert report_path.exists()
        payload = json.loads(report_path.read_text())
        assert payload["status"] == "tool-error"
        assert payload["error"]


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestReportSchema:
    """Validates generated reports against the JSON schema."""

    @pytest.fixture(scope="class")
    def schema(self) -> dict:
        """Load the mutation-report.json schema once."""
        return json.loads(SCHEMA.read_text())

    @pytest.mark.parametrize(
        "fixture",
        ["all-killed", "survived", "timeout", "suspicious", "empty"],
    )
    def test_clean_or_findings_report_matches_schema(
        self, tmp_path: Path, schema: dict, fixture: str
    ) -> None:
        """Each successful fixture produces a schema-valid report."""
        jsonschema = pytest.importorskip("jsonschema")
        mod = _import_module()
        report_path = tmp_path / f"{fixture}.json"
        mod.run_policy("3.5.0", _fixture_text(fixture), report_path)
        payload = json.loads(report_path.read_text())
        jsonschema.validate(payload, schema)

    def test_tool_error_report_matches_schema(
        self, tmp_path: Path, schema: dict
    ) -> None:
        """Tool-error reports are also schema-valid."""
        jsonschema = pytest.importorskip("jsonschema")
        mod = _import_module()
        report_path = tmp_path / "tool-error.json"
        mod.run_policy("3.5.0", _fixture_text("malformed"), report_path)
        payload = json.loads(report_path.read_text())
        jsonschema.validate(payload, schema)


# ---------------------------------------------------------------------------
# CLI entry point (main)
# ---------------------------------------------------------------------------


class TestMain:
    """Tests for the CLI ``main`` entry point and subprocess invocation."""

    def test_help_exits_zero(self) -> None:
        """``--help`` exits 0 and advertises --report-path."""
        result = subprocess.run(
            [sys.executable, "-m", "scripts.mutation_policy", "--help"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0
        assert "--report-path" in result.stdout

    def test_tool_error_when_mutmut_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() returns 2 when mutmut cannot be invoked."""
        mod = _import_module()

        def _raise(_args: tuple[str, ...]) -> str:
            raise mod.MutmutUnavailableError("mutmut binary not found")

        monkeypatch.setattr(mod, "_run_mutmut", _raise)
        report_path = tmp_path / "tool-error.json"
        exit_code = mod.main(["--report-path", str(report_path)])
        assert exit_code == mod.EXIT_TOOL_ERROR
        assert report_path.exists()
        payload = json.loads(report_path.read_text())
        assert payload["status"] == "tool-error"

    def test_main_clean_with_injected_text(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() returns 0 when injected results text is all-killed."""
        mod = _import_module()

        class _Stub:
            def __init__(self) -> None:
                self.calls = 0

            def __call__(self, args: tuple[str, ...]) -> str:
                self.calls += 1
                if "--version" in args:
                    return VERSION_FIXTURE
                return _fixture_text("all-killed")

        monkeypatch.setattr(mod, "_run_mutmut", _Stub())
        report_path = tmp_path / "report.json"
        exit_code = mod.main(["--report-path", str(report_path)])
        assert exit_code == mod.EXIT_CLEAN
        assert report_path.exists()

    def test_main_findings_with_injected_text(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() returns 1 when injected results text has survivors."""
        mod = _import_module()

        def _stub(args: tuple[str, ...]) -> str:
            if "--version" in args:
                return VERSION_FIXTURE
            return _fixture_text("survived")

        monkeypatch.setattr(mod, "_run_mutmut", _stub)
        exit_code = mod.main([])
        assert exit_code == mod.EXIT_FINDINGS

    def test_main_schema_drift_with_injected_text(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() returns 2 when injected results text is malformed."""
        mod = _import_module()

        def _stub(args: tuple[str, ...]) -> str:
            if "--version" in args:
                return VERSION_FIXTURE
            return _fixture_text("malformed")

        monkeypatch.setattr(mod, "_run_mutmut", _stub)
        exit_code = mod.main([])
        assert exit_code == mod.EXIT_TOOL_ERROR
