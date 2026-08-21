"""Tests for the Make target ownership and dependency validator.

Covers :mod:`scripts.validate_make_policy`:

* Pure parser tests with hand-rolled ``make -p`` snippets.
* End-to-end CLI tests against synthetic Makefiles written to ``tmp_path``.
* Failure-path coverage for missing targets, missing dependencies, and
  invalid Makefile paths.
"""

from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

import pytest

from scripts import validate_make_policy as mkp

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MAKE_PRESENT: bool = shutil.which("make") is not None


# ---------------------------------------------------------------------------
# Synthetic make-database fixtures
# ---------------------------------------------------------------------------


SAMPLE_DATABASE = textwrap.dedent(
    """\
    # GNU Make 4.3
    # Variables
    SHELL := /bin/bash
    # Files

    test: lint
    #  recipe to execute (from 'Makefile', line 1):
    \tpytest

    lint:
    #  recipe to execute (from 'Makefile', line 2):
    \truff check .

    format-check: lint
    #  recipe to execute (from 'Makefile', line 3):
    \truff format --check .

    ci: test
    #  recipe to execute (from 'Makefile', line 4):
    \tmake test-coverage

    other-test:
    #  recipe to execute (from 'Makefile', line 5):
    \tpytest --some-flag

    # Not a target:
    .PHONY: test lint format-check ci
    #  Phony target (prerequisite of .PHONY).

    # Finished Make data base
    """
)


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestParseMakeDatabase:
    """Direct parser tests with synthetic make-database output."""

    def test_parses_named_targets(self) -> None:
        """Canonical targets are extracted by name."""
        targets = mkp.parse_make_database(SAMPLE_DATABASE)
        for name in ("test", "lint", "format-check", "ci", "other-test"):
            assert name in targets

    def test_excludes_special_and_pattern_targets(self) -> None:
        """Special targets like .PHONY are skipped."""
        targets = mkp.parse_make_database(SAMPLE_DATABASE)
        assert ".PHONY" not in targets

    def test_captures_prerequisites(self) -> None:
        """Prerequisites of ``test`` are parsed in order."""
        targets = mkp.parse_make_database(SAMPLE_DATABASE)
        assert "lint" in targets["test"].prerequisites

    def test_captures_recipe_lines(self) -> None:
        """Recipe lines (TAB-indented after a target) are captured."""
        targets = mkp.parse_make_database(SAMPLE_DATABASE)
        assert any("pytest" in line for line in targets["test"].recipe)

    def test_skips_variable_assignments(self) -> None:
        """``VAR := value`` lines are not treated as targets."""
        targets = mkp.parse_make_database("VAR := value\n")
        assert targets == {}


# ---------------------------------------------------------------------------
# Validator unit tests
# ---------------------------------------------------------------------------


class TestValidateRequiredTargets:
    """Required-target checks return one finding per missing name."""

    def _make_targets(self, *names: str) -> dict[str, mkp.MakeTarget]:
        return {name: mkp.MakeTarget(name=name) for name in names}

    def test_returns_no_findings_when_all_present(self) -> None:
        """No findings when every required target exists."""
        targets = self._make_targets("test", "lint")
        assert mkp.validate_required_targets(targets, ["test", "lint"]) == []

    def test_returns_finding_per_missing_target(self) -> None:
        """Each missing target produces one error finding."""
        targets = self._make_targets("test")
        findings = mkp.validate_required_targets(targets, ["test", "lint", "build"])
        codes = [(f.code, f.target) for f in findings]
        assert ("MAKE_TARGET_MISSING", "lint") in codes
        assert ("MAKE_TARGET_MISSING", "build") in codes
        assert all(f.severity == mkp.SEVERITY_ERROR for f in findings)


class TestValidateDependencies:
    """Dependency-chain validation."""

    def test_passes_when_prereqs_present(self) -> None:
        """No finding when expected prereqs are present."""
        targets = {
            "ci": mkp.MakeTarget(name="ci", prerequisites=("test", "lint")),
        }
        findings = mkp.validate_dependencies(targets, {"ci": ["test"]})
        assert findings == []

    def test_reports_missing_prerequisite(self) -> None:
        """Missing prereqs produce a MAKE_DEP_MISSING finding."""
        targets = {
            "ci": mkp.MakeTarget(name="ci", prerequisites=("lint",)),
        }
        findings = mkp.validate_dependencies(targets, {"ci": ["test"]})
        assert len(findings) == 1
        assert findings[0].code == "MAKE_DEP_MISSING"

    def test_reports_missing_target(self) -> None:
        """A dependency rule on an undefined target errors out."""
        findings = mkp.validate_dependencies({}, {"nope": ["x"]})
        assert len(findings) == 1
        assert findings[0].code == "MAKE_DEP_TARGET_MISSING"


class TestValidateCommandOwnership:
    """Canonical command ownership checks."""

    def _targets(self) -> dict[str, mkp.MakeTarget]:
        return {
            "test": mkp.MakeTarget(name="test", recipe=("pytest",)),
            "other": mkp.MakeTarget(name="other", recipe=("pytest --extra",)),
        }

    def test_warns_when_command_in_extra_target(self) -> None:
        """A canonical command in a non-owning target produces a warning."""
        findings = mkp.validate_command_ownership(self._targets(), {"pytest": "test"})
        assert len(findings) == 1
        assert findings[0].severity == mkp.SEVERITY_WARNING
        assert findings[0].code == "MAKE_COMMAND_DUPLICATED"

    def test_no_finding_when_only_canonical_owner(self) -> None:
        """No finding when only the canonical owner runs the command."""
        targets = {"test": mkp.MakeTarget(name="test", recipe=("pytest",))}
        assert mkp.validate_command_ownership(targets, {"pytest": "test"}) == []


# ---------------------------------------------------------------------------
# CLI end-to-end tests (require ``make`` to be installed)
# ---------------------------------------------------------------------------


SIMPLE_MAKEFILE = textwrap.dedent(
    """\
    .PHONY: test lint format-check ci-static ci-test-coverage ci-test-compat ci-fuzz-status pip-audit sonar-reports ci-property ci-package smoke-test safety-gate ci ci-trusted

    test: lint
    \tpytest

    lint:
    \truff check .

    format-check: lint
    \truff format --check .

    ci-static: format-check
    ci-test-coverage:
    ci-test-compat:
    ci-fuzz-status:
    pip-audit:
    sonar-reports:
    ci-property:
    ci-package:
    smoke-test:
    safety-gate:

    ci: ci-static ci-test-coverage ci-fuzz-status pip-audit sonar-reports ci-property ci-package smoke-test
    \techo building

    ci-trusted: ci safety-gate
    """
)


@pytest.mark.skipif(not MAKE_PRESENT, reason="make binary not available")
class TestCliEndToEnd:
    """End-to-end tests running the validator against a real Makefile."""

    def _write_makefile(self, tmp_path: Path, content: str = SIMPLE_MAKEFILE) -> Path:
        path = tmp_path / "Makefile"
        path.write_text(content)
        return path

    def test_required_targets_pass(self, tmp_path: Path) -> None:
        """A Makefile with all required targets exits 0."""
        makefile = self._write_makefile(tmp_path)
        exit_code = mkp.main(["--makefile", str(makefile)])
        assert exit_code == mkp.EXIT_PASS

    def test_missing_target_fails(self, tmp_path: Path) -> None:
        """A Makefile without ``lint`` fails the required-target check."""
        makefile = self._write_makefile(
            tmp_path,
            textwrap.dedent(
                """\
                .PHONY: test format-check

                test:
                \tpytest

                format-check:
                \truff format --check .
                """
            ),
        )
        exit_code = mkp.main(["--makefile", str(makefile)])
        assert exit_code == mkp.EXIT_FAIL

    def test_dependency_chain_validated(self, tmp_path: Path) -> None:
        """The default split-CI dependency rule is enforced."""
        makefile = self._write_makefile(
            tmp_path,
            SIMPLE_MAKEFILE.replace(
                "ci: ci-static ci-test-coverage ci-fuzz-status pip-audit "
                "sonar-reports ci-property ci-package smoke-test",
                "ci: ci-static",
            ),
        )
        exit_code = mkp.main(["--makefile", str(makefile)])
        assert exit_code == mkp.EXIT_FAIL

    def test_invalid_makefile_path_returns_usage_error(self, tmp_path: Path) -> None:
        """A non-existent Makefile exits with usage code 2."""
        missing = tmp_path / "nope.mk"
        exit_code = mkp.main(["--makefile", str(missing)])
        assert exit_code == mkp.EXIT_USAGE

    def test_json_output_has_expected_schema(self, tmp_path: Path) -> None:
        """The ``--json`` flag emits the documented top-level keys."""
        import contextlib
        import io

        makefile = self._write_makefile(tmp_path)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            exit_code = mkp.main(["--makefile", str(makefile), "--json"])
        assert exit_code in {mkp.EXIT_PASS, mkp.EXIT_FAIL}
        payload = json.loads(buffer.getvalue())
        for key in ("pass", "makefile", "target_count", "targets", "findings"):
            assert key in payload
        assert "test" in payload["targets"]


# ---------------------------------------------------------------------------
# Makefile round-trip: parse real ``make -p`` output
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not MAKE_PRESENT, reason="make binary not available")
class TestRealMakeOutput:
    """Run real ``make -p`` and check the parser handles it cleanly."""

    def test_real_make_p_parses_named_targets(self, tmp_path: Path) -> None:
        """``make -p`` output of a real Makefile parses to expected targets."""
        path = tmp_path / "Makefile"
        path.write_text(SIMPLE_MAKEFILE)
        text = mkp._run_make_database(path)
        targets = mkp.parse_make_database(text)
        for name in ("test", "lint", "format-check", "ci"):
            assert name in targets


# ---------------------------------------------------------------------------
# Canonical mutation adapter contracts (repository Makefile)
# ---------------------------------------------------------------------------


class TestMutationAdapterContracts:
    """Every mutation lane routes through the canonical runner."""

    _makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")

    def test_all_execution_targets_use_the_canonical_runner(self) -> None:
        for target in (
            "mutate-full-policy:",
            "mutate-selected:",
            "mutate-module:",
            "mutate-diff:",
        ):
            start = self._makefile.index(f"\n{target}")
            end = self._makefile.find("\n\n", start)
            recipe = self._makefile[start:end]
            assert "scripts/run_mutation.py" in recipe, target

    def test_no_raw_mutmut_run_recipe_remains(self) -> None:
        assert "\tuv run mutmut run" not in self._makefile

    def test_mutate_alias_enforces_full_policy(self) -> None:
        line = next(line for line in self._makefile.splitlines() if line.startswith("mutate:"))
        assert line.startswith("mutate: mutate-full-policy")

    def test_module_pattern_is_boundary_safe(self) -> None:
        assert "--pattern 'perplexity_cli.$(MODULE).x*'" in self._makefile

    def test_diff_adapter_propagates_discovery_failure(
        self,
    ) -> None:
        start = self._makefile.index("\nmutate-diff:")
        end = self._makefile.find("\n\n", start)
        recipe = self._makefile[start:end]
        assert "exit $$status" in recipe
        assert "--allow-empty-diff" in recipe

    def test_base_sha_default_matches_remote_head_branch(self) -> None:
        assert "BASE_SHA ?= origin/master" in self._makefile


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
