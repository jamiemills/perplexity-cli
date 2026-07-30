"""Tests for the YAML 1.2-aware workflow policy validator.

Covers the public surface of :mod:`scripts.validate_workflow_policy`:

* Fixture-driven unit tests run the validator against canned workflows under
  ``tests/fixtures/workflow_policy/``.
* CLI tests invoke ``main()`` directly with ``--dir`` pointed at a temp
  directory containing a single fixture copy, so each scenario is isolated.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "workflow_policy"

SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import validate_workflow_policy as wfp  # noqa: E402


def _copy_fixture_to(tmp_path: Path, fixture_name: str) -> Path:
    """Copy a single fixture into ``tmp_path`` and return the directory."""
    shutil.copy2(FIXTURES / fixture_name, tmp_path / fixture_name)
    return tmp_path


def _run_main(tmp_path: Path, *extra: str) -> tuple[int, str, str]:
    """Invoke ``main()`` capturing stdout/stderr via capsys-like monkeypatching."""
    return wfp.main(["--dir", str(tmp_path), *extra])


# ---------------------------------------------------------------------------
# Parser configuration
# ---------------------------------------------------------------------------


class TestParserConfig:
    """ruamel.yaml must be configured to reject duplicate keys (YAML 1.2)."""

    def test_parser_rejects_duplicate_keys(self) -> None:
        """Duplicate top-level keys raise a YAMLError during parse."""
        parser = wfp._make_parser()
        data, error = wfp._parse_workflow("a: 1\na: 2\n", parser)
        assert data is None
        assert error


# ---------------------------------------------------------------------------
# Per-fixture CLI behaviour
# ---------------------------------------------------------------------------


class TestCli:
    """CLI exit codes for each fixture workflow."""

    def test_valid_workflow_passes(self, tmp_path: Path) -> None:
        """A clean workflow exits 0 with no findings."""
        directory = _copy_fixture_to(tmp_path, "valid.yml")
        exit_code = _run_main(directory)
        assert exit_code == wfp.EXIT_PASS

    def test_missing_permissions_fails(self, tmp_path: Path) -> None:
        """Missing permissions block exits 1."""
        directory = _copy_fixture_to(tmp_path, "missing-permissions.yml")
        exit_code = _run_main(directory)
        assert exit_code == wfp.EXIT_FAIL

    def test_unpinned_action_fails(self, tmp_path: Path) -> None:
        """A non-SHA action reference exits 1."""
        directory = _copy_fixture_to(tmp_path, "unpinned-action.yml")
        exit_code = _run_main(directory)
        assert exit_code == wfp.EXIT_FAIL

    def test_pull_request_target_fails(self, tmp_path: Path) -> None:
        """The forbidden trigger exits 1."""
        directory = _copy_fixture_to(tmp_path, "pull-request-target.yml")
        exit_code = _run_main(directory)
        assert exit_code == wfp.EXIT_FAIL

    def test_duplicate_keys_fails(self, tmp_path: Path) -> None:
        """Duplicate YAML keys produce a parse failure and exit 1."""
        directory = _copy_fixture_to(tmp_path, "duplicate-keys.yml")
        exit_code = _run_main(directory)
        assert exit_code == wfp.EXIT_FAIL

    def test_missing_timeout_warns_non_strict(self, tmp_path: Path) -> None:
        """Missing timeout-minutes is a warning; passes without --strict."""
        directory = _copy_fixture_to(tmp_path, "missing-timeout.yml")
        exit_code = _run_main(directory)
        assert exit_code == wfp.EXIT_PASS

    def test_missing_timeout_fails_under_strict(self, tmp_path: Path) -> None:
        """Missing timeout-minutes under --strict exits 1."""
        directory = _copy_fixture_to(tmp_path, "missing-timeout.yml")
        exit_code = _run_main(directory, "--strict")
        assert exit_code == wfp.EXIT_FAIL

    def test_invalid_syntax_fails_cleanly(self, tmp_path: Path) -> None:
        """Malformed YAML must not crash; it produces a controlled failure."""
        directory = _copy_fixture_to(tmp_path, "invalid-syntax.yml")
        exit_code = _run_main(directory)
        assert exit_code == wfp.EXIT_FAIL

    def test_missing_directory_returns_usage_error(self, tmp_path: Path) -> None:
        """A non-existent directory exits with usage error code 2."""
        missing = tmp_path / "does-not-exist"
        exit_code = wfp.main(["--dir", str(missing)])
        assert exit_code == wfp.EXIT_USAGE


# ---------------------------------------------------------------------------
# JSON output schema
# ---------------------------------------------------------------------------


class TestJsonOutput:
    """The ``--json`` flag emits a structured report with the expected schema."""

    def test_json_has_expected_top_level_keys(self, tmp_path: Path) -> None:
        """The JSON report contains the documented top-level keys."""
        directory = _copy_fixture_to(tmp_path, "missing-permissions.yml")
        captured = _capture_json_output(directory)
        for key in (
            "pass",
            "strict",
            "file_count",
            "error_count",
            "warning_count",
            "unparsed_count",
            "files",
        ):
            assert key in captured, f"missing key: {key}"

    def test_json_finding_shape(self, tmp_path: Path) -> None:
        """Findings expose severity, code, message, and file."""
        directory = _copy_fixture_to(tmp_path, "unpinned-action.yml")
        captured = _capture_json_output(directory)
        file_payload = captured["files"][0]
        assert file_payload["parsed"] is True
        codes = {finding["code"] for finding in file_payload["findings"]}
        assert "WF_ACTION_UNPINNED" in codes

    def test_json_unparsed_file_includes_parse_error(self, tmp_path: Path) -> None:
        """Malformed YAML reports parsed=False with a parse_error message."""
        directory = _copy_fixture_to(tmp_path, "invalid-syntax.yml")
        captured = _capture_json_output(directory)
        file_payload = captured["files"][0]
        assert file_payload["parsed"] is False
        assert file_payload["parse_error"]


def _capture_json_output(directory: Path) -> dict:
    """Run the CLI in JSON mode and return the parsed top-level dict."""
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exit_code = wfp.main(["--dir", str(directory), "--json"])
    assert exit_code in {wfp.EXIT_PASS, wfp.EXIT_FAIL}
    return json.loads(buffer.getvalue())


# ---------------------------------------------------------------------------
# Unit-level validator checks
# ---------------------------------------------------------------------------


class TestValidators:
    """Direct unit checks for individual rule helpers."""

    def test_external_action_extraction_skips_local(self) -> None:
        """Local actions starting with './' are exempt from pinning checks."""
        assert wfp._extract_uses_ref("./.github/actions/local") is None
        assert wfp._extract_uses_ref("docker://image:tag") is None

    def test_external_action_extraction_returns_ref(self) -> None:
        """External references return just the ref portion (post-@)."""
        assert wfp._extract_uses_ref("actions/checkout@abc123") == "abc123"

    def test_sha_pattern_matches_full_lowercase_sha(self) -> None:
        """The SHA pattern accepts a 40-character lowercase hex string."""
        sha = "a" * 40
        assert wfp.SHA_PATTERN.fullmatch(sha) is not None

    def test_sha_pattern_rejects_short_ref(self) -> None:
        """The SHA pattern rejects tags and short SHAs."""
        assert wfp.SHA_PATTERN.fullmatch("v4") is None
        assert wfp.SHA_PATTERN.fullmatch("abc123") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
