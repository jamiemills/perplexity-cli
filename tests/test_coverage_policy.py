"""Tests for the surviving conventional per-module coverage policy.

``scripts/coverage_policy.py`` and ``quality/schemas/diff-coverage-v1.json``
were removed as dormant pseudo-diff infrastructure (decision A006).  These
tests exercise the policy surface that remains in
``scripts/check_module_coverage.py``: fail-closed report validation and
executable-module classification.  ``diff-cover`` remains the sole
changed-line coverage authority.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts._gates import load_gates
from scripts.check_module_coverage import (
    _check_branch_data_present,
    _classify_source,
    _load_report,
    _parse_args,
    validate_report,
)


class TestReportLoading:
    """Missing or malformed report files must fail closed."""

    def test_missing_report_aborts(self) -> None:
        with pytest.raises(SystemExit) as exc:
            _load_report("/nonexistent/coverage.json")
        assert exc.value.code == 2

    def test_malformed_json_aborts(self, tmp_path: Path) -> None:
        report = tmp_path / "coverage.json"
        report.write_text('{"files": [', encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            _load_report(str(report))
        assert exc.value.code == 2

    def test_non_object_json_aborts(self, tmp_path: Path) -> None:
        report = tmp_path / "coverage.json"
        report.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            _load_report(str(report))
        assert exc.value.code == 2


class TestReportStructure:
    """Structurally invalid reports must be rejected, never silently passed."""

    def test_missing_files_key_rejected(self, tmp_path: Path) -> None:
        errors = validate_report({"meta": {}}, min_coverage=80.0, src_root=tmp_path)
        assert any("no module entries" in e for e in errors)

    def test_empty_files_rejected(self, tmp_path: Path) -> None:
        errors = validate_report({"files": {}}, min_coverage=80.0, src_root=tmp_path)
        assert any("no module entries" in e for e in errors)

    def test_non_object_report_rejected(self, tmp_path: Path) -> None:
        errors = validate_report(["not", "an", "object"], min_coverage=80.0, src_root=tmp_path)
        assert any("JSON object" in e for e in errors)

    def test_non_object_totals_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8")
        report = {
            "meta": {"branch_coverage": False, "format": 3},
            "files": {
                "m.py": {
                    "summary": {
                        "percent_covered": 100.0,
                        "num_statements": 1,
                        "missing_lines": 0,
                    }
                }
            },
            "totals": "garbage",
        }
        errors = validate_report(report, min_coverage=80.0, src_root=tmp_path)
        assert any("totals" in e for e in errors)


class TestBranchCoverageRequired:
    """Branch coverage must be enabled or the report is rejected."""

    def test_branch_disabled_rejected(self) -> None:
        errors: list[str] = []
        _check_branch_data_present({"meta": {"branch_coverage": False}}, errors)
        assert any("branch" in e for e in errors)

    def test_missing_meta_rejected(self) -> None:
        errors: list[str] = []
        _check_branch_data_present({}, errors)
        assert any("branch" in e for e in errors)

    def test_branch_enabled_accepted(self) -> None:
        errors: list[str] = []
        _check_branch_data_present({"meta": {"branch_coverage": True}}, errors)
        assert errors == []


class TestExecutableClassification:
    """Which module shapes must appear in the coverage report."""

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("import json\n", "executable"),
            ('"""Interface documentation."""\n', "docstring"),
            ("class Repository(Protocol):\n    key: str\n    ...\n", "re-export"),
            ('from .repository import Repository\n__all__ = ["Repository"]\n', "executable"),
            ("x = 1\n", "executable"),
        ],
        ids=[
            "import-only-module",
            "docstring-only-module",
            "declarative-protocol",
            "init-reexport",
            "genuinely-executable",
        ],
    )
    def test_classification_fixture_matrix(self, source: str, expected: str) -> None:
        assert _classify_source(source) == expected

    def test_protocol_with_concrete_method_is_executable(self) -> None:
        source = "class Repository(Protocol):\n    def load(self) -> object:\n        return {}\n"
        assert _classify_source(source) == "executable"

    def test_decorated_protocol_is_executable(self) -> None:
        source = "@runtime_checkable\nclass Repository(Protocol):\n    key: str\n    ...\n"
        assert _classify_source(source) == "executable"


class TestReportEntryUniqueness:
    """Entries must be unique within the source root."""

    def test_colliding_keys_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "collide.py").write_text("x = 1\n", encoding="utf-8")
        entry = {
            "summary": {
                "percent_covered": 100.0,
                "num_statements": 1,
                "missing_lines": 0,
                "num_branches": 0,
                "num_partial_branches": 0,
            }
        }
        report = {
            "meta": {"branch_coverage": True, "format": 3},
            "files": {
                "src/perplexity_cli/collide.py": entry,
                "collide.py": entry,
            },
            "totals": {"percent_covered": 100.0},
        }
        errors = validate_report(report, min_coverage=80.0, src_root=tmp_path)
        assert any("Duplicate entry for source module" in e for e in errors)


class TestFailClosedOnUnparseableInput:
    """Inputs that cannot be parsed must never be treated as covered."""

    def test_unparseable_source_classified_executable(self) -> None:
        assert _classify_source("def broken(\n") == "executable"

    def test_non_dict_report_entry_fails_closed(self, tmp_path: Path) -> None:
        (tmp_path / "bad.py").write_text("x = 1\n", encoding="utf-8")
        report = {
            "meta": {"branch_coverage": False, "format": 3},
            "files": {"bad.py": "not-a-summary"},
            "totals": {"percent_covered": 100.0},
        }
        errors = validate_report(report, min_coverage=80.0, src_root=tmp_path)
        assert any("Non-numeric percent_covered" in e for e in errors)


class TestCliContract:
    """The CLI surface the Makefile depends on stays intact."""

    def test_min_coverage_sourced_from_gates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.argv", ["check_module_coverage.py"])
        args = _parse_args()
        expected = float(load_gates().get_int("MIN_COVERAGE", 85))
        assert args.min_coverage == expected

    def test_report_default_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.argv", ["check_module_coverage.py"])
        args = _parse_args()
        assert args.report == "coverage.json"
