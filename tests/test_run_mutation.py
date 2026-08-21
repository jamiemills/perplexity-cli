"""Contract tests for the canonical fresh-run mutation orchestrator."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

import pytest

from scripts import run_mutation as rm
from scripts.mutation_evidence import MutationSelection, matches_selection


def _args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "scope": "full",
        "pattern": [],
        "manifest_path": None,
        "report_path": Path("report.json"),
        "timeout_seconds": 60,
        "outer_deadline_epoch": None,
        "candidate_sha": None,
        "allow_empty_diff": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestBuildRequestValidation:
    def test_full_rejects_patterns_and_manifest(self) -> None:
        with pytest.raises(rm.RunnerUsageError, match="full scope"):
            rm.build_request(_args(scope="full", pattern=["pkg.x*"]), ())
        with pytest.raises(rm.RunnerUsageError, match="full scope"):
            rm.build_request(_args(scope="full", manifest_path=Path("m.json")), ())

    def test_selected_requires_pattern_or_empty_diff_flag(self) -> None:
        with pytest.raises(rm.RunnerUsageError, match="at least one pattern"):
            rm.build_request(_args(scope="selected"), ())
        request = rm.build_request(_args(scope="selected", allow_empty_diff=True), ())
        assert request.selection.scope == "selected"

    def test_pattern_and_manifest_are_mutually_exclusive(self) -> None:
        with pytest.raises(rm.RunnerUsageError, match="mutually exclusive"):
            rm.build_request(_args(scope="selected", pattern=["a.x*"], manifest_path=Path("m")), ())

    def test_manifest_patterns_fill_selected_scope(self) -> None:
        request = rm.build_request(_args(scope="selected"), ("perplexity_cli.api.client.x*",))
        assert request.selection.patterns == ("perplexity_cli.api.client.x*",)

    def test_timeout_and_candidate_sha_are_validated(self) -> None:
        with pytest.raises(rm.RunnerUsageError, match="positive"):
            rm.build_request(_args(timeout_seconds=0), ())
        with pytest.raises(rm.RunnerUsageError, match="40-hex"):
            rm.build_request(_args(candidate_sha="nothex"), ())
        request = rm.build_request(
            _args(candidate_sha="a" * 40),
            (),
        )
        assert request.candidate_sha == "a" * 40


class TestBudgetResolution:
    def test_scope_caps_are_enforced(self) -> None:
        request = rm.build_request(_args(timeout_seconds=19_801), ())
        with pytest.raises(rm.RunnerUsageError, match="19800s cap"):
            rm.resolve_budget(request, 0.0)
        selected = rm.build_request(
            _args(scope="selected", timeout_seconds=2_101, allow_empty_diff=True), ()
        )
        with pytest.raises(rm.RunnerUsageError, match="2100s cap"):
            rm.resolve_budget(selected, 0.0)

    def test_deadline_reserves_shrink_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(rm.time, "time", lambda: 1_000_000)
        deadline = 1_000_000 + 600 + 120 + 500 + 100
        full = rm.build_request(_args(timeout_seconds=10_000, outer_deadline_epoch=deadline), ())
        assert rm.resolve_budget(full, 0.0) == 600
        selected = rm.build_request(
            _args(
                scope="selected",
                timeout_seconds=2_000,
                outer_deadline_epoch=deadline,
                allow_empty_diff=True,
            ),
            (),
        )
        assert rm.resolve_budget(selected, 0.0) == 900

    def test_exhausted_deadline_refuses_before_launch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(rm.time, "time", lambda: 2_000_000)
        request = rm.build_request(_args(timeout_seconds=100, outer_deadline_epoch=2_000_000), ())
        with pytest.raises(rm.RunnerUsageError, match="deadline exhausted"):
            rm.resolve_budget(request, 0.0)


@pytest.fixture
def sandbox_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(rm, "PROJECT_ROOT", tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    "make_sentinel",
    [
        lambda root: (root / "mutants").write_text("stale"),
        lambda root: (root / "mutants").mkdir(),
        lambda root: (
            (root / "target.txt").write_text("keep")
            or (root / "mutants").symlink_to(root / "missing-target")
        ),
    ],
)
def test_execute_refuses_existing_workspace_sentinels(sandbox_root: Path, make_sentinel) -> None:
    make_sentinel(sandbox_root)
    before = (
        (sandbox_root / "mutants").read_bytes()
        if (sandbox_root / "mutants").is_file()
        else b"<dir>"
    )
    request = rm.build_request(_args(), ())
    assert rm.execute(request, 0.0) == rm.policy.EXIT_TOOL_ERROR
    after = (
        (sandbox_root / "mutants").read_bytes()
        if (sandbox_root / "mutants").is_file()
        else b"<dir>"
    )
    assert before == after


def test_execute_refuses_symlink_without_touching_target(
    sandbox_root: Path,
) -> None:
    target = sandbox_root / "precious.txt"
    target.write_text("keep")
    (sandbox_root / "mutants").symlink_to(target)
    request = rm.build_request(_args(), ())
    assert rm.execute(request, 0.0) == rm.policy.EXIT_TOOL_ERROR
    assert target.read_text() == "keep"
    assert (sandbox_root / "mutants").is_symlink()


def test_execute_writes_schema_valid_failure_report(
    sandbox_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode() -> rm.policy.EnvironmentIdentity:
        raise rm.EnvironmentMismatchError("verification failed")

    monkeypatch.setattr(rm, "verify_environment", explode)
    report_path = sandbox_root / "reports" / "failure.json"
    request = rm.build_request(_args(report_path=report_path), ())
    assert rm.execute(request, 0.0) == rm.policy.EXIT_TOOL_ERROR
    payload = json.loads(report_path.read_text())
    assert payload["status"] == rm.policy.STATUS_TOOL_ERROR
    assert payload["error"]


class TestLaunchMutmut:
    def test_zero_exit_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            rm.policy,
            "MUTMUT_PREFIX",
            (rm.sys.executable, "-c", "import sys; sys.exit(0)"),
        )
        assert rm.launch_mutmut((), 30) is None

    def test_findings_exit_code_is_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            rm.policy,
            "MUTMUT_PREFIX",
            (rm.sys.executable, "-c", "import sys; sys.exit(1)"),
        )
        assert rm.launch_mutmut((), 30) is None

    def test_infrastructure_exit_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            rm.policy,
            "MUTMUT_PREFIX",
            (rm.sys.executable, "-c", "import sys; sys.exit(7)"),
        )
        with pytest.raises(rm.EnvironmentMismatchError, match="status 7"):
            rm.launch_mutmut((), 30)

    def test_timeout_terminates_group_and_raises(
        self, monkeypatch: pytest.MonkeyPatch, sandbox_root: Path
    ) -> None:
        monkeypatch.setattr(
            rm.policy,
            "MUTMUT_PREFIX",
            (rm.sys.executable, "-c", "import time; time.sleep(30)"),
        )
        with pytest.raises(rm.EnvironmentMismatchError, match="timed out"):
            rm.launch_mutmut((), 1)


class TestRecordVerification:
    """Installed-file verification against a fake dist-info tree."""

    @staticmethod
    def _install_fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutate: str) -> None:

        dist_info = tmp_path / f"mutmut-{rm.policy.LOCKED_MUTMUT_VERSION}.dist-info"
        dist_info.mkdir(parents=True)
        package = tmp_path / "mutmut"
        package.mkdir()
        entries: list[tuple[Path, bytes]] = [
            (package / "core.py", b"original"),
            (dist_info / "METADATA", b"meta"),
        ]
        lines = []
        for path, original in entries:
            digest = base64.urlsafe_b64encode(hashlib.sha256(original).digest())
            lines.append(
                f"{path.relative_to(tmp_path).as_posix()},"
                f"sha256={digest.rstrip(b'=').decode()},{len(original)}"
            )
            if mutate == "tamper" and path.name == "core.py":
                path.write_bytes(b"tampered")
                continue
            if not (mutate == "missing" and path.name == "core.py"):
                path.write_bytes(original)
        record = dist_info / "RECORD"
        record.write_text("\n".join(lines) + f"\n{record.relative_to(tmp_path).as_posix()},,\n")
        if mutate == "extra":
            (package / "implant.py").write_bytes(b"evil")
        monkeypatch.setattr(rm.sys, "path", [str(tmp_path), *rm.sys.path])
        monkeypatch.setattr(
            rm.importlib.metadata,
            "version",
            lambda _name: rm.policy.LOCKED_MUTMUT_VERSION,
        )

    def test_clean_tree_verifies(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self._install_fake(monkeypatch, tmp_path, "clean")
        distribution_digest, record_digest = rm._distribution_identity()
        assert len(distribution_digest) == len(record_digest) == 64
        assert all(ch in "0123456789abcdef" for ch in distribution_digest + record_digest)

    def test_tampered_file_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._install_fake(monkeypatch, tmp_path, "tamper")
        with pytest.raises(rm.EnvironmentMismatchError, match="tampered"):
            rm._distribution_identity()

    def test_missing_file_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._install_fake(monkeypatch, tmp_path, "missing")
        with pytest.raises(rm.EnvironmentMismatchError, match="missing"):
            rm._distribution_identity()

    def test_unlisted_file_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._install_fake(monkeypatch, tmp_path, "extra")
        with pytest.raises(rm.EnvironmentMismatchError, match="not recorded"):
            rm._distribution_identity()


class TestMakeInjectionGuards:
    """Hostile Make variables are rejected before any runner invocation."""

    @staticmethod
    def _run_make(target: str, assignment: str) -> int:
        import subprocess

        result = subprocess.run(
            ["make", f"{target}={assignment}", target],
            capture_output=True,
            text=True,
            cwd=rm.PROJECT_ROOT,
            check=False,
        )
        return result.returncode

    def test_hostile_module_assignment_exits_two(self) -> None:
        assert self._run_make("MODULE", "x'; touch pwned") == 2

    def test_hostile_patterns_assignment_exits_two(self) -> None:
        assert self._run_make("PATTERNS", "ok.x*`id`") == 2


class TestManifestPatterns:
    def _write_manifest(self, path: Path, changed: list[str]) -> Path:
        payload = {"schema_version": "1", "changed_files": changed}
        path.write_text(json.dumps(payload))
        return path

    def test_module_package_and_init_mapping_is_boundary_safe(self, tmp_path: Path) -> None:
        manifest = self._write_manifest(
            tmp_path / "m.json",
            [
                "src/perplexity_cli/api/client.py",
                "src/perplexity_cli/api/__init__.py",
                "src/perplexity_cli/__init__.py",
            ],
        )
        assert rm.patterns_from_manifest(manifest) == (
            "perplexity_cli.api.client.x*",
            "perplexity_cli.api.x*",
            "perplexity_cli.x*",
        )

    def test_prefix_spill_is_impossible(self) -> None:
        assert rm._module_pattern("src/perplexity_cli/foo.py") == "perplexity_cli.foo.x*"
        assert (
            matches_selection(
                "perplexity_cli.foo_bar.x_f__mutmut_1",
                MutationSelection("selected", ("perplexity_cli.foo.x*",)),
            )
            is False
        )

    @pytest.mark.parametrize(
        ("payload", "message"),
        [
            ("not json", "unreadable discovery manifest"),
            ('{"changed_files": "x"}', "lacks a non-empty"),
            ('{"changed_files": []}', "lacks a non-empty"),
            ('{"changed_files": [1]}', "must be strings"),
            ('{"other": 1}', "lacks a non-empty"),
        ],
    )
    def test_malformed_manifests_fail_closed(
        self, tmp_path: Path, payload: str, message: str
    ) -> None:
        manifest = tmp_path / "bad.json"
        manifest.write_text(payload)
        with pytest.raises(rm.RunnerUsageError, match=message):
            rm.patterns_from_manifest(manifest)

    def test_outside_source_paths_are_rejected(self, tmp_path: Path) -> None:
        manifest = self._write_manifest(tmp_path / "m.json", ["tests/x.py"])
        with pytest.raises(rm.RunnerUsageError, match="not production source"):
            rm.patterns_from_manifest(manifest)
