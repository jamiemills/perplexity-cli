"""Pre-push contract tests for ``scripts/gitleaks_check.sh``.

These tests pin the contract that the Wave 4 ``D2-HOOKS`` task will rely on
when wiring the Lefthook pre-push hook:

* stdin refspec parsing (existing, new, deleted, multiple, malformed, empty)
* object-format-aware zero-OID detection (SHA-1 and SHA-256)
* exit-code classification (0 clean, 10 findings, 3 error)
* no remote URL is ever written to stdout/stderr

The tests do NOT perform a real ``git push`` and do NOT require network
access.  Each test materialises an isolated temporary git repository via
the setup scripts under ``tests/fixtures/gitleaks/`` and feeds curated
stdin payloads to the script.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "gitleaks_check.sh"
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures" / "gitleaks"

ZERO_OID_SHA1 = "0" * 40
ZERO_OID_SHA256 = "0" * 64
# ``file://`` URL with no backing repository fails instantly with no DNS
# or network traffic — ideal for offline tests of the new-ref branch.
UNREACHABLE_REMOTE = "file:///nonexistent/gitleaks-prepush/repo.git"

pytestmark = pytest.mark.skipif(
    shutil.which("gitleaks") is None,
    reason="gitleaks not installed",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_script(
    cwd: Path,
    *args: str,
    stdin_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke ``gitleaks_check.sh`` inside ``cwd`` and capture the result.

    Sets ``GIT_TERMINAL_PROMPT=0`` so any incidental credential prompt
    fails fast instead of hanging the test runner.
    """
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=30,
        input=stdin_text,
        env=env,
    )


def _load_fixture(name: str) -> str:
    """Read a fixture file from ``tests/fixtures/gitleaks/`` as text."""
    return (FIXTURES_DIR / name).read_text()


def _render_fixture(name: str, mapping: Mapping[str, str]) -> str:
    """Substitute ``${placeholder}`` tokens in a fixture stdin template."""
    return Template(_load_fixture(name)).substitute(mapping)


def _setup_repo(tmp_path: Path, script_name: str) -> Path:
    """Provision a temp git repository by running a fixture setup script."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["bash", str(FIXTURES_DIR / script_name), str(repo)],
        capture_output=True,
        text=True,
        check=True,
    )
    return repo


def _rev_parse(repo: Path, ref: str) -> str:
    """Resolve ``ref`` to a commit SHA inside ``repo``."""
    return subprocess.check_output(
        ["git", "rev-parse", ref],
        text=True,
        cwd=str(repo),
    ).strip()


def _install_fake_gitleaks(shim_dir: Path, body: str) -> None:
    """Write a fake ``gitleaks`` binary into ``shim_dir``."""
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim = shim_dir / "gitleaks"
    shim.write_text(f"#!/usr/bin/env bash\n{body}")
    shim.chmod(0o755)


def _run_with_shim(
    shim_dir: Path,
    mode: str,
    *,
    stdin_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the script with ``shim_dir`` prepended to ``PATH``."""
    env = {
        **os.environ,
        "PATH": f"{shim_dir}:{os.environ['PATH']}",
        "GIT_TERMINAL_PROMPT": "0",
    }
    return subprocess.run(
        ["bash", str(SCRIPT), mode],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=15,
        input=stdin_text,
        env=env,
    )


# ---------------------------------------------------------------------------
# Shell syntax validation
# ---------------------------------------------------------------------------


def test_shell_syntax_valid() -> None:
    """``bash -n`` accepts the script with no syntax errors."""
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stderr == ""


# ---------------------------------------------------------------------------
# Version check — rejects unsupported versions
# ---------------------------------------------------------------------------


class TestVersionCheck:
    """The version gate accepts 8.30.x and rejects anything else."""

    def test_supported_version_accepted(self, tmp_path: Path) -> None:
        _install_fake_gitleaks(
            tmp_path / "shim",
            'if [ "$1" = "version" ]; then echo "8.30.1"; exit 0; fi\nexit 0',
        )
        result = _run_with_shim(tmp_path / "shim", "ci-full")
        # Fake binary exits 0 for the scan itself; no findings reported.
        assert result.returncode == 0

    def test_supported_version_with_leading_v(self, tmp_path: Path) -> None:
        _install_fake_gitleaks(
            tmp_path / "shim",
            'if [ "$1" = "version" ]; then echo "v8.30.4"; exit 0; fi\nexit 0',
        )
        result = _run_with_shim(tmp_path / "shim", "ci-full")
        assert result.returncode == 0

    def test_unsupported_older_rejected(self, tmp_path: Path) -> None:
        _install_fake_gitleaks(
            tmp_path / "shim",
            'if [ "$1" = "version" ]; then echo "8.29.0"; exit 0; fi\nexit 0',
        )
        result = _run_with_shim(tmp_path / "shim", "ci-full")
        assert result.returncode == 3
        combined = result.stdout + result.stderr
        assert "unsupported" in combined

    def test_unsupported_newer_major_rejected(self, tmp_path: Path) -> None:
        _install_fake_gitleaks(
            tmp_path / "shim",
            'if [ "$1" = "version" ]; then echo "9.0.0"; exit 0; fi\nexit 0',
        )
        result = _run_with_shim(tmp_path / "shim", "ci-full")
        assert result.returncode == 3
        combined = result.stdout + result.stderr
        assert "unsupported" in combined

    def test_version_command_failure_rejected(self, tmp_path: Path) -> None:
        _install_fake_gitleaks(tmp_path / "shim", "exit 1")
        result = _run_with_shim(tmp_path / "shim", "ci-full")
        assert result.returncode == 3
        combined = result.stdout + result.stderr
        assert "failed" in combined.lower()


# ---------------------------------------------------------------------------
# Pre-push stdin parsing — ref-type dispatch
# ---------------------------------------------------------------------------


class TestPrePushStdinParsing:
    """Each ref type routes through the correct code path."""

    def test_existing_ref_scans_range(self, tmp_path: Path) -> None:
        """Both OIDs non-zero → scans ``remote..local`` range."""
        repo = _setup_repo(tmp_path, "clean-repo-setup.sh")
        head = _rev_parse(repo, "HEAD")
        root = _rev_parse(repo, "HEAD~1")
        stdin = _render_fixture(
            "stdin-existing-ref.txt",
            {
                "LOCAL_OID": head,
                "LOCAL_REF": "refs/heads/main",
                "REMOTE_OID": root,
                "REMOTE_REF": "refs/heads/main",
            },
        )
        result = _run_script(
            repo,
            "pre-push",
            "origin",
            UNREACHABLE_REMOTE,
            stdin_text=stdin,
        )
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "existing ref" in combined
        assert "scanning" in combined

    def test_new_ref_scans_local_history(self, tmp_path: Path) -> None:
        """Remote OID is zero → new-ref path scans local history."""
        repo = _setup_repo(tmp_path, "clean-repo-setup.sh")
        head = _rev_parse(repo, "HEAD")
        stdin = _render_fixture(
            "stdin-new-ref.txt",
            {
                "LOCAL_OID": head,
                "LOCAL_REF": "refs/heads/feature",
                "REMOTE_REF": "refs/heads/feature",
            },
        )
        result = _run_script(
            repo,
            "pre-push",
            "origin",
            UNREACHABLE_REMOTE,
            stdin_text=stdin,
        )
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "new ref" in combined

    def test_deleted_ref_skips_scan(self, tmp_path: Path) -> None:
        """Local OID is zero → deletion, skipped without scanning."""
        repo = _setup_repo(tmp_path, "clean-repo-setup.sh")
        head = _rev_parse(repo, "HEAD")
        stdin = _render_fixture(
            "stdin-deleted-ref.txt",
            {
                "LOCAL_REF": "refs/heads/feature",
                "REMOTE_OID": head,
                "REMOTE_REF": "refs/heads/feature",
            },
        )
        result = _run_script(
            repo,
            "pre-push",
            "origin",
            UNREACHABLE_REMOTE,
            stdin_text=stdin,
        )
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "skipping deleted ref" in combined

    def test_multiple_refs_scan_union(self, tmp_path: Path) -> None:
        """Multiple non-deletion rows → union scan."""
        repo = _setup_repo(tmp_path, "clean-repo-setup.sh")
        head = _rev_parse(repo, "HEAD")
        root = _rev_parse(repo, "HEAD~1")
        stdin = _render_fixture(
            "stdin-multiple-refs.txt",
            {
                "LOCAL_OID_1": head,
                "LOCAL_REF_1": "refs/heads/main",
                "REMOTE_OID_1": root,
                "REMOTE_REF_1": "refs/heads/main",
                "LOCAL_OID_2": head,
                "LOCAL_REF_2": "refs/heads/feature",
                "REMOTE_OID_2": root,
                "REMOTE_REF_2": "refs/heads/feature",
            },
        )
        result = _run_script(
            repo,
            "pre-push",
            "origin",
            UNREACHABLE_REMOTE,
            stdin_text=stdin,
        )
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "scanning union" in combined

    def test_malformed_row_exits_error(self, tmp_path: Path) -> None:
        """Fewer than four fields → exit 3 (not 10, not 0)."""
        repo = _setup_repo(tmp_path, "clean-repo-setup.sh")
        stdin = _load_fixture("stdin-malformed.txt")
        result = _run_script(
            repo,
            "pre-push",
            "origin",
            UNREACHABLE_REMOTE,
            stdin_text=stdin,
        )
        assert result.returncode == 3
        combined = result.stdout + result.stderr
        assert "malformed" in combined

    def test_empty_stdin_returns_clean(self, tmp_path: Path) -> None:
        """No ref rows on stdin → exit 0 without invoking gitleaks."""
        repo = _setup_repo(tmp_path, "clean-repo-setup.sh")
        result = _run_script(
            repo,
            "pre-push",
            "origin",
            UNREACHABLE_REMOTE,
            stdin_text="",
        )
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "no refs received" in combined


# ---------------------------------------------------------------------------
# Object-format awareness — SHA-1 and SHA-256 zero OIDs
# ---------------------------------------------------------------------------


class TestObjectFormatAwareZeroOid:
    """Zero-OID detection accepts both 40-zero (SHA-1) and 64-zero forms."""

    def test_sha1_zero_remote_oid_treated_as_new_ref(self, tmp_path: Path) -> None:
        repo = _setup_repo(tmp_path, "clean-repo-setup.sh")
        head = _rev_parse(repo, "HEAD")
        stdin = f"{head} refs/heads/main {ZERO_OID_SHA1} refs/heads/main\n"
        result = _run_script(
            repo,
            "pre-push",
            "origin",
            UNREACHABLE_REMOTE,
            stdin_text=stdin,
        )
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "new ref" in combined

    def test_sha256_zero_remote_oid_treated_as_new_ref(self, tmp_path: Path) -> None:
        repo = _setup_repo(tmp_path, "clean-repo-setup.sh")
        head = _rev_parse(repo, "HEAD")
        stdin = f"{head} refs/heads/main {ZERO_OID_SHA256} refs/heads/main\n"
        result = _run_script(
            repo,
            "pre-push",
            "origin",
            UNREACHABLE_REMOTE,
            stdin_text=stdin,
        )
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "new ref" in combined

    def test_sha1_zero_local_oid_treated_as_deleted(self, tmp_path: Path) -> None:
        repo = _setup_repo(tmp_path, "clean-repo-setup.sh")
        head = _rev_parse(repo, "HEAD")
        stdin = f"{ZERO_OID_SHA1} refs/heads/main {head} refs/heads/main\n"
        result = _run_script(
            repo,
            "pre-push",
            "origin",
            UNREACHABLE_REMOTE,
            stdin_text=stdin,
        )
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "skipping deleted ref" in combined

    def test_sha256_zero_local_oid_treated_as_deleted(self, tmp_path: Path) -> None:
        repo = _setup_repo(tmp_path, "clean-repo-setup.sh")
        head = _rev_parse(repo, "HEAD")
        stdin = f"{ZERO_OID_SHA256} refs/heads/main {head} refs/heads/main\n"
        result = _run_script(
            repo,
            "pre-push",
            "origin",
            UNREACHABLE_REMOTE,
            stdin_text=stdin,
        )
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "skipping deleted ref" in combined


# ---------------------------------------------------------------------------
# Exit-code classification
# ---------------------------------------------------------------------------


class TestExitCodeClassification:
    """0 = clean, 10 = findings, 3 = scanner / input error."""

    def test_clean_scan_exits_zero(self, tmp_path: Path) -> None:
        repo = _setup_repo(tmp_path, "clean-repo-setup.sh")
        result = _run_script(repo, "ci-full")
        assert result.returncode == 0

    def test_secrets_found_exits_ten(self, tmp_path: Path) -> None:
        repo = _setup_repo(tmp_path, "secret-repo-setup.sh")
        result = _run_script(repo, "ci-full")
        assert result.returncode == 10

    def test_scanner_error_exits_nonzero_non_ten(self, tmp_path: Path) -> None:
        """Invalid ref in range mode → exit 3 (error, not 10)."""
        repo = _setup_repo(tmp_path, "clean-repo-setup.sh")
        result = _run_script(repo, "range", "nonexistent-sha", "HEAD")
        assert result.returncode != 0
        assert result.returncode != 10


# ---------------------------------------------------------------------------
# Security contract — never log the remote URL
# ---------------------------------------------------------------------------


class TestNoRemoteUrlLeak:
    """The remote URL passed to ``pre-push`` must never appear in output."""

    def test_remote_url_absent_from_output(self, tmp_path: Path) -> None:
        repo = _setup_repo(tmp_path, "clean-repo-setup.sh")
        head = _rev_parse(repo, "HEAD")
        stdin = _render_fixture(
            "stdin-existing-ref.txt",
            {
                "LOCAL_OID": head,
                "LOCAL_REF": "refs/heads/main",
                "REMOTE_OID": head,
                "REMOTE_REF": "refs/heads/main",
            },
        )
        # Embed a sentinel substring in the URL that must never be echoed.
        sentinel = "zZsentinel-cred-in-urlZz"
        url = f"https://user:{sentinel}@example.invalid/repo.git"
        result = _run_script(
            repo,
            "pre-push",
            "origin",
            url,
            stdin_text=stdin,
        )
        combined = result.stdout + result.stderr
        assert sentinel not in combined
        assert "example.invalid" not in combined


# ---------------------------------------------------------------------------
# CI-full mode — argument handling and end-to-end scan
# ---------------------------------------------------------------------------


class TestCiFullMode:
    """``ci-full`` scans the entire repository history."""

    def test_ci_full_rejects_extra_args(self, tmp_path: Path) -> None:
        repo = _setup_repo(tmp_path, "clean-repo-setup.sh")
        result = _run_script(repo, "ci-full", "unexpected-arg")
        assert result.returncode == 3
        combined = result.stdout + result.stderr
        assert "usage:" in combined

    def test_ci_full_clean_repo_exits_zero(self, tmp_path: Path) -> None:
        repo = _setup_repo(tmp_path, "clean-repo-setup.sh")
        result = _run_script(repo, "ci-full")
        assert result.returncode == 0

    def test_ci_full_secret_repo_exits_ten(self, tmp_path: Path) -> None:
        repo = _setup_repo(tmp_path, "secret-repo-setup.sh")
        result = _run_script(repo, "ci-full")
        assert result.returncode == 10


# ---------------------------------------------------------------------------
# Regression — single-commit repo (root commit in the union)
# ---------------------------------------------------------------------------


class TestRootCommitUnionRegression:
    """A new ref whose history is a single (root) commit must still be scanned.

    Regression test for a bug where ``${oldest}^..${newest}`` was emitted
    even when ``oldest`` was the root commit (no parent).  Git rejects the
    ``<root>^..<root>`` range and gitleaks silently scanned zero commits.
    """

    def test_single_commit_repo_scans_root(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(
            ["git", "init", "--initial-branch=main"],
            capture_output=True,
            cwd=str(repo),
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            capture_output=True,
            cwd=str(repo),
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            capture_output=True,
            cwd=str(repo),
            check=True,
        )
        secret = "AKIA0123456789ABCDEF"
        (repo / "leaked.txt").write_text(
            f"# Synthetic test fixture — NOT a real credential.\nAWS_KEY={secret}\n"
        )
        subprocess.run(["git", "add", "leaked.txt"], capture_output=True, cwd=str(repo), check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            capture_output=True,
            cwd=str(repo),
            check=True,
        )
        head = _rev_parse(repo, "HEAD")
        stdin = f"{head} refs/heads/main {ZERO_OID_SHA1} refs/heads/main\n"
        result = _run_script(
            repo,
            "pre-push",
            "origin",
            UNREACHABLE_REMOTE,
            stdin_text=stdin,
        )
        # Without the fix this returned 0 (zero commits scanned).  The fix
        # must surface the leaked key as a finding.
        assert result.returncode == 10
