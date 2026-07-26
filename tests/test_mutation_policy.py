from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mutation"


def _run_policy(
    mutants_dir: Path,
    manifest: Path | None = None,
    waivers: Path | None = None,
) -> tuple[int, str, str]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.mutation_policy",
            str(mutants_dir),
            *(["--manifest", str(manifest)] if manifest else []),
            *(["--waivers", str(waivers)] if waivers else []),
        ],
        capture_output=True,
        text=True,
        cwd=FIXTURES.parents[2],
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


class TestMutationPolicyResults:
    def test_all_killed_passes(self, tmp_path: Path) -> None:
        """Policy passes when all mutants are killed."""
        src_dir = tmp_path / "mutants"
        src_dir.mkdir(parents=True)
        (src_dir / "all_killed.meta").write_text((FIXTURES / "all_killed.meta").read_text())

        exit_code, _stdout, stderr = _run_policy(src_dir)
        assert exit_code == 0, f"Expected pass, got exit code {exit_code}\nstderr: {stderr}"

    def test_survivor_detected(self, tmp_path: Path) -> None:
        """Policy fails when a mutant survives."""
        src_dir = tmp_path / "mutants"
        src_dir.mkdir(parents=True)
        (src_dir / "kill_survivor.meta").write_text((FIXTURES / "kill_survivor.meta").read_text())

        exit_code, _stdout, _stderr = _run_policy(src_dir)
        assert exit_code == 1, f"Expected violation, got exit code {exit_code}"

    def test_waivers_respected(self, tmp_path: Path) -> None:
        """Waived survivors do not cause policy failure."""
        src_dir = tmp_path / "mutants"
        src_dir.mkdir(parents=True)
        (src_dir / "survived_waived.meta").write_text(
            (FIXTURES / "survived_waived.meta").read_text()
        )

        exit_code, _stdout, _ = _run_policy(src_dir, waivers=FIXTURES / "waivers.toml")
        assert exit_code == 0, f"Expected pass with waivers, got {exit_code}"

    def test_no_tests_detected(self, tmp_path: Path) -> None:
        """Policy fails when mutants have no tests."""
        src_dir = tmp_path / "mutants"
        src_dir.mkdir(parents=True)
        (src_dir / "no_tests.meta").write_text((FIXTURES / "no_tests.meta").read_text())

        exit_code, _stdout, _stderr = _run_policy(src_dir)
        assert exit_code == 1, f"Expected violation for no tests, got {exit_code}"

    def test_timeout_detected(self, tmp_path: Path) -> None:
        """Policy fails when mutants time out."""
        src_dir = tmp_path / "mutants"
        src_dir.mkdir(parents=True)
        (src_dir / "timeout.meta").write_text((FIXTURES / "timeout.meta").read_text())

        exit_code, _stdout, _stderr = _run_policy(src_dir)
        assert exit_code == 1, f"Expected violation for timeout, got {exit_code}"

    def test_not_checked_detected(self, tmp_path: Path) -> None:
        """Policy fails when mutants were never checked."""
        src_dir = tmp_path / "mutants"
        src_dir.mkdir(parents=True)
        (src_dir / "not_checked.meta").write_text((FIXTURES / "not_checked.meta").read_text())

        exit_code, _stdout, _stderr = _run_policy(src_dir)
        assert exit_code == 1, f"Expected violation for not checked, got {exit_code}"

    def test_segfault_detected(self, tmp_path: Path) -> None:
        """Policy fails on segfault."""
        src_dir = tmp_path / "mutants"
        src_dir.mkdir(parents=True)
        (src_dir / "segfault.meta").write_text((FIXTURES / "segfault.meta").read_text())

        exit_code, _stdout, _stderr = _run_policy(src_dir)
        assert exit_code == 1, f"Expected violation for segfault, got {exit_code}"

    def test_mixed_pass(self, tmp_path: Path) -> None:
        """Mixed results should fail when any non-waived violation exists."""
        src_dir = tmp_path / "mutants"
        src_dir.mkdir(parents=True)
        (src_dir / "mixed.meta").write_text((FIXTURES / "mixed.meta").read_text())

        exit_code, _stdout, _stderr = _run_policy(src_dir)
        assert exit_code == 1, f"Expected violation for mixed, got {exit_code}"

    def test_report_generated(self, tmp_path: Path) -> None:
        """Report is generated in valid JSON format."""
        import json

        src_dir = tmp_path / "mutants"
        src_dir.mkdir(parents=True)
        (src_dir / "all_killed.meta").write_text((FIXTURES / "all_killed.meta").read_text())

        report_path = tmp_path / "report.json"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.mutation_policy",
                str(src_dir),
                "--report",
                str(report_path),
            ],
            capture_output=True,
            text=True,
            cwd=FIXTURES.parents[2],
            check=False,
        )
        assert result.returncode == 0
        assert report_path.exists()

        report = json.loads(report_path.read_text())
        assert report["schema_version"] == "1"
        assert report["policy_pass"] is True
        assert report["mutmut_version_required"] == "3.5.0"
        assert "summary" in report
        assert "files" in report


class TestMutationPolicySchemaDrift:
    def test_missing_metadata_dir(self, tmp_path: Path) -> None:
        """Missing mutants dir produces internal error."""
        missing = tmp_path / "nonexistent"
        exit_code, _stdout, _stderr = _run_policy(missing)
        assert exit_code == 2, f"Expected internal error, got {exit_code}"

    def test_schema_drift_extra_keys(self, tmp_path: Path) -> None:
        """Schema drift in .meta files produces internal error."""
        src_dir = tmp_path / "mutants"
        src_dir.mkdir(parents=True)
        (src_dir / "schema_drift.meta").write_text((FIXTURES / "schema_drift.meta").read_text())

        exit_code, _stdout, _stderr = _run_policy(src_dir)
        assert exit_code == 2, f"Expected internal error for schema drift, got {exit_code}"


class TestMutationPolicySuccess:
    def test_all_killed_is_pass(self, tmp_path: Path) -> None:
        """All-killed mutants produce a passing report."""
        src_dir = tmp_path / "mutants"
        src_dir.mkdir(parents=True)
        (src_dir / "all_killed.meta").write_text((FIXTURES / "all_killed.meta").read_text())

        exit_code, _stdout, _stderr = _run_policy(src_dir)
        assert exit_code == 0

    def test_survivor_without_waiver_fails(self, tmp_path: Path) -> None:
        """Survivor without waiver fails policy."""
        src_dir = tmp_path / "mutants"
        src_dir.mkdir(parents=True)
        (src_dir / "all_survived.meta").write_text((FIXTURES / "all_survived.meta").read_text())

        exit_code, _stdout, _stderr = _run_policy(src_dir)
        assert exit_code == 1

    def test_class_mutant_waiver(self, tmp_path: Path) -> None:
        """Class-based mutants can be waived via fnmatch pattern."""
        src_dir = tmp_path / "mutants"
        src_dir.mkdir(parents=True)
        (src_dir / "survived_class.meta").write_text((FIXTURES / "survived_class.meta").read_text())

        exit_code, _, _ = _run_policy(src_dir, waivers=FIXTURES / "waivers.toml")
        assert exit_code == 0, f"Class mutant waiver should pass, got {exit_code}"
