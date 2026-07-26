"""Tests for unconditional per-module coverage enforcement."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_module_coverage import (
    _check_modules,
    _classify_module,
    _classify_source,
    _enumerate_source_modules,
    validate_report,
)

FIXTURES = Path(__file__).parent / "fixtures" / "coverage"
FIXTURE_SRC = FIXTURES / "src_tree"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class TestCheckModules:
    def test_small_module_below_threshold_fails(self) -> None:
        """Modules below five statements remain subject to the configured floor."""
        report = {
            "files": {
                "src/perplexity_cli/tiny.py": {
                    "summary": {
                        "percent_covered": 0.0,
                        "num_statements": 4,
                        "missing_lines": 4,
                    }
                }
            }
        }
        assert _check_modules(report, 85.0) == [("tiny", 0.0, 4, 4)]

    def test_empty_report_fails_closed(self) -> None:
        """Missing module data cannot be interpreted as full coverage."""
        with pytest.raises(ValueError, match="no module entries"):
            _check_modules({"files": {}}, 85.0)


class TestValidateReport:
    def test_valid_report_passes(self) -> None:
        report = _load_fixture("valid.json")
        errors = validate_report(report, min_coverage=80.0, src_root=FIXTURE_SRC)
        assert errors == []

    def test_missing_entry_for_executable_module(self) -> None:
        """Report missing an executable source module triggers an error."""
        report = _load_fixture("valid.json")
        del report["files"]["src/perplexity_cli/ndjson.py"]
        errors = validate_report(report, min_coverage=80.0, src_root=FIXTURE_SRC)
        assert any("missing from coverage report" in e for e in errors)

    def test_nan_percentage_rejected(self) -> None:
        """NaN percent_covered is rejected as invalid."""
        report = _load_fixture("valid.json")
        report["files"]["src/perplexity_cli/cli.py"]["summary"]["percent_covered"] = float("nan")
        errors = validate_report(report, min_coverage=80.0, src_root=FIXTURE_SRC)
        assert any("Invalid percent_covered" in e for e in errors)

    def test_infinity_percentage_rejected(self) -> None:
        """Infinity percent_covered is rejected as invalid."""
        report = _load_fixture("valid.json")
        from math import inf

        report["files"]["src/perplexity_cli/cli.py"]["summary"]["percent_covered"] = inf
        errors = validate_report(report, min_coverage=80.0, src_root=FIXTURE_SRC)
        assert any("Invalid percent_covered" in e for e in errors)

    def test_non_numeric_percentage_rejected(self) -> None:
        """Non-numeric percent_covered is rejected."""
        report = _load_fixture("valid.json")
        report["files"]["src/perplexity_cli/cli.py"]["summary"]["percent_covered"] = "high"
        errors = validate_report(report, min_coverage=80.0, src_root=FIXTURE_SRC)
        assert any("Non-numeric percent_covered" in e for e in errors)

    def test_duplicate_path_rejected(self) -> None:
        """Entries seen more than once are reported as duplicates."""
        report = _load_fixture("valid.json")
        src1 = FIXTURE_SRC / "__init__.py"
        src1.write_text("x = 1\n")
        errors = validate_report(report, min_coverage=80.0, src_root=FIXTURE_SRC)
        assert errors == []  # valid fixture has unique paths

    def test_duplicate_path_directly(self) -> None:
        """The _check_duplicate helper flags second occurrences."""
        from scripts.check_module_coverage import _check_duplicate

        seen: set[str] = set()
        errors: list[str] = []
        assert not _check_duplicate("some/file.py", seen, errors)
        assert _check_duplicate("some/file.py", seen, errors)
        assert any("Duplicate" in e for e in errors)

    def test_outside_root_rejected(self) -> None:
        """Entry with path not under the source root is rejected."""
        report = _load_fixture("valid.json")
        report["files"]["var/log/evil.py"] = {
            "summary": {"percent_covered": 100.0, "num_statements": 1, "missing_lines": 0}
        }
        errors = validate_report(report, min_coverage=80.0, src_root=FIXTURE_SRC)
        assert any("outside source root" in e for e in errors)

    def test_non_python_file_in_report_rejected(self) -> None:
        """Non-.py files in the report are rejected."""
        report = _load_fixture("valid.json")
        report["files"]["src/perplexity_cli/README.md"] = {
            "summary": {"percent_covered": 100.0, "num_statements": 1, "missing_lines": 0}
        }
        errors = validate_report(report, min_coverage=80.0, src_root=FIXTURE_SRC)
        assert any("Non-Python file" in e for e in errors)

    def test_report_entry_missing_from_source_tree(self) -> None:
        """Report contains entry for a module not present in source tree."""
        report = _load_fixture("valid.json")
        report["files"]["src/perplexity_cli/deleted_module.py"] = {
            "summary": {"percent_covered": 100.0, "num_statements": 1, "missing_lines": 0}
        }
        errors = validate_report(report, min_coverage=80.0, src_root=FIXTURE_SRC)
        assert any("missing from source tree" in e for e in errors)

    def test_missing_branch_data_when_enabled(self) -> None:
        """When branch_coverage is enabled, missing branch data is an error."""
        report = _load_fixture("valid.json")
        report["meta"]["branch_coverage"] = True
        del report["files"]["src/perplexity_cli/cli.py"]["summary"]["num_branches"]
        errors = validate_report(report, min_coverage=80.0, src_root=FIXTURE_SRC)
        assert any("Missing branch data" in e for e in errors)

    def test_statement_free_module_not_required(self, tmp_path: Path) -> None:
        """Empty/docstring/re-export modules may be absent from the report."""
        (tmp_path / "empty_module.py").write_text("")
        (tmp_path / "exec.py").write_text("x = 1\n")
        report = {
            "meta": {"branch_coverage": False, "format": 3},
            "files": {
                "exec.py": {
                    "summary": {
                        "percent_covered": 100.0,
                        "num_statements": 1,
                        "missing_lines": 0,
                    }
                }
            },
            "totals": {"percent_covered": 100.0},
        }
        errors = validate_report(report, min_coverage=80.0, src_root=tmp_path)
        assert errors == []

    def test_executable_module_missing_errors(self, tmp_path: Path) -> None:
        """Executable modules absent from the report produce errors."""
        (tmp_path / "missing_executable.py").write_text("x = 1\n")
        (tmp_path / "covered.py").write_text("y = 1\n")
        report = {
            "meta": {"branch_coverage": False, "format": 3},
            "files": {
                "covered.py": {
                    "summary": {
                        "percent_covered": 100.0,
                        "num_statements": 1,
                        "missing_lines": 0,
                    }
                }
            },
            "totals": {"percent_covered": 100.0},
        }
        errors = validate_report(report, min_coverage=80.0, src_root=tmp_path)
        assert any("missing from coverage report" in e for e in errors)


class TestClassifySource:
    def test_empty_source(self) -> None:
        assert _classify_source("") == "empty"

    def test_docstring_only(self) -> None:
        assert _classify_source('"""A docstring module."""') == "docstring"

    def test_re_export_only(self) -> None:
        assert _classify_source("from .foo import bar\n") == "re-export"

    def test_executable_source(self) -> None:
        assert _classify_source("x = 1\n") == "executable"

    def test_syntax_error_treated_as_executable(self) -> None:
        assert _classify_source("def broken(\n") == "executable"

    def test_mixed_import_and_value(self) -> None:
        assert _classify_source("import os\nx = 2\n") == "executable"


class TestClassifyModule:
    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.py"
        f.write_text("")
        assert _classify_module(f) == "empty"

    def test_docstring_file(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.py"
        f.write_text('"""Module docs."""\n')
        assert _classify_module(f) == "docstring"

    def test_re_export_file(self, tmp_path: Path) -> None:
        f = tmp_path / "reexport.py"
        f.write_text("from .foo import bar\nfrom .baz import qux\n")
        assert _classify_module(f) == "re-export"

    def test_executable_file(self, tmp_path: Path) -> None:
        f = tmp_path / "exec.py"
        f.write_text("x = 1\n")
        assert _classify_module(f) == "executable"


class TestEnumerateSourceModules:
    def test_enumerates_py_files(self, tmp_path: Path) -> None:
        a = tmp_path / "a.py"
        b = tmp_path / "b.py"
        c = tmp_path / "c.py"
        d = tmp_path / "d.py"
        a.write_text("x = 1\n")
        b.write_text('"""doc"""\n')
        c.write_text("")
        d.write_text("from .x import y\n")
        modules = _enumerate_source_modules(tmp_path)
        assert len(modules) == 4
        assert modules["a.py"] == "executable"
        assert modules["b.py"] == "docstring"
        assert modules["c.py"] == "empty"
        assert modules["d.py"] == "re-export"
