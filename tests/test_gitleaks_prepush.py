"""Contract tests for the Gitleaks pre-push scanner."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "gitleaks_check.sh"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "gitleaks"
ZERO = "0" * 40
SENTINEL_URL = "https://user:url-secret@example.invalid/repo.git"


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def _git_run(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _setup_repo(tmp_path: Path, fixture: str = "clean-repo-setup.sh") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    subprocess.run(
        ["bash", str(FIXTURES / fixture), str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    return repo


def _add_commit(repo: Path, name: str, content: str = "clean\n") -> str:
    (repo / name).write_text(content)
    _git_run(repo, "add", name)
    _git_run(repo, "commit", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


def _add_bare_remote(repo: Path, tmp_path: Path, name: str = "upstream") -> Path:
    remote = tmp_path / f"{name}.git"
    subprocess.run(
        ["git", "clone", "--bare", str(repo), str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git_run(repo, "remote", "add", name, str(remote))
    return remote


def _install_fake_gitleaks(shim_dir: Path) -> None:
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim = shim_dir / "gitleaks"
    shim.write_text(
        """#!/usr/bin/env bash
if [[ "${1:-}" == "version" ]]; then
    printf '%b\\n' "${FAKE_GITLEAKS_VERSION:-8.30.1}"
    exit "${FAKE_VERSION_EXIT:-0}"
fi
for argument in "$@"; do
    if [[ "$argument" == --log-opts=* ]]; then
        printf '%s\\n' "${argument#--log-opts=}" > "${FAKE_GITLEAKS_RECORD:?}"
    fi
done
exit "${FAKE_GITLEAKS_EXIT:-0}"
"""
    )
    shim.chmod(0o755)


def _run(
    repo: Path,
    args: Sequence[str],
    *,
    stdin: str = "",
    shim_dir: Path | None = None,
    env_extra: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env_extra or {})}
    if shim_dir is not None:
        env["PATH"] = f"{shim_dir}:{env['PATH']}"
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=repo,
        input=stdin,
        text=True,
        capture_output=True,
        timeout=30,
        env=env,
    )


def _run_fake(
    repo: Path,
    tmp_path: Path,
    stdin: str,
    *,
    remote: str = "upstream",
    url: str = SENTINEL_URL,
    env_extra: Mapping[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], set[str]]:
    shim = tmp_path / "shim"
    record = tmp_path / "log-opts"
    _install_fake_gitleaks(shim)
    env = {"FAKE_GITLEAKS_RECORD": str(record), **(env_extra or {})}
    result = _run(repo, ["pre-push", remote, url], stdin=stdin, shim_dir=shim, env_extra=env)
    if not record.exists():
        return result, set()
    options = record.read_text().strip().split()
    assert options[:2] == ["--no-walk=unsorted", "--diff-merges=first-parent"]
    return result, set(options[2:])


def _fixture(name: str, values: Mapping[str, str]) -> str:
    return Template((FIXTURES / name).read_text()).substitute(values)


def _row(local_ref: str, local_oid: str, remote_ref: str, remote_oid: str) -> str:
    return f"{local_ref} {local_oid} {remote_ref} {remote_oid}\n"


def test_shell_syntax_valid() -> None:
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stderr == ""


@pytest.mark.parametrize("version", ["8.30.0", "8.30.4", "8.31.0", "7.30.1", "8.30.1-extra"])
def test_only_exact_gitleaks_version_is_accepted(tmp_path: Path, version: str) -> None:
    repo = _setup_repo(tmp_path)
    shim = tmp_path / "shim"
    _install_fake_gitleaks(shim)
    result = _run(
        repo,
        ["ci-full"],
        shim_dir=shim,
        env_extra={
            "FAKE_GITLEAKS_VERSION": version,
            "FAKE_GITLEAKS_RECORD": str(tmp_path / "record"),
        },
    )
    assert result.returncode == 3
    assert "requires exactly 8.30.1" in result.stderr


@pytest.mark.parametrize("version", ["8.30.1", "v8.30.1", "  8.30.1  ", "\tv8.30.1\t"])
def test_exact_version_allows_optional_v_and_whitespace(tmp_path: Path, version: str) -> None:
    repo = _setup_repo(tmp_path)
    shim = tmp_path / "shim"
    _install_fake_gitleaks(shim)
    result = _run(
        repo,
        ["ci-full"],
        shim_dir=shim,
        env_extra={
            "FAKE_GITLEAKS_VERSION": version,
            "FAKE_GITLEAKS_RECORD": str(tmp_path / "record"),
        },
    )
    assert result.returncode == 0


def test_version_command_failure_is_scanner_error(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    shim = tmp_path / "shim"
    _install_fake_gitleaks(shim)
    result = _run(
        repo,
        ["ci-full"],
        shim_dir=shim,
        env_extra={"FAKE_VERSION_EXIT": "7", "FAKE_GITLEAKS_RECORD": str(tmp_path / "record")},
    )
    assert result.returncode == 3
    assert "failed to run" in result.stderr


def test_existing_ref_uses_standard_order_and_exact_difference(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    _add_bare_remote(repo, tmp_path)
    remote_oid = _git(repo, "rev-parse", "HEAD~1")
    local_oid = _git(repo, "rev-parse", "HEAD")
    stdin = _fixture(
        "stdin-existing-ref.txt",
        {
            "LOCAL_REF": "refs/heads/main",
            "LOCAL_OID": local_oid,
            "REMOTE_REF": "refs/heads/main",
            "REMOTE_OID": remote_oid,
        },
    )
    result, commits = _run_fake(repo, tmp_path, stdin)
    assert result.returncode == 0
    assert commits == {local_oid}


def test_old_oid_first_order_is_rejected(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    _add_bare_remote(repo, tmp_path)
    local_oid = _git(repo, "rev-parse", "HEAD")
    remote_oid = _git(repo, "rev-parse", "HEAD~1")
    result, commits = _run_fake(
        repo,
        tmp_path,
        f"{local_oid} refs/heads/main {remote_oid} refs/heads/main\n",
    )
    assert result.returncode == 3
    assert "malformed local OID" in result.stderr
    assert commits == set()


def test_new_ref_subtracts_every_advertised_remote_commit(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    _git_run(repo, "branch", "remote-side")
    _add_bare_remote(repo, tmp_path)
    local_oid = _add_commit(repo, "feature.txt")
    stdin = _fixture(
        "stdin-new-ref.txt",
        {
            "LOCAL_REF": "refs/heads/feature",
            "LOCAL_OID": local_oid,
            "REMOTE_REF": "refs/heads/feature",
        },
    )
    result, commits = _run_fake(repo, tmp_path, stdin)
    assert result.returncode == 0
    assert commits == {local_oid}


def test_deleted_ref_scans_nothing(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    _add_bare_remote(repo, tmp_path)
    remote_oid = _git(repo, "rev-parse", "HEAD")
    stdin = _fixture(
        "stdin-deleted-ref.txt",
        {"LOCAL_REF": "(delete)", "REMOTE_REF": "refs/heads/old", "REMOTE_OID": remote_oid},
    )
    result, commits = _run_fake(repo, tmp_path, stdin)
    assert result.returncode == 0
    assert "skipping deleted ref" in result.stdout
    assert commits == set()


def test_multiple_rows_form_deduplicated_crossing_union(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    root = _git(repo, "rev-parse", "HEAD~1")
    middle = _git(repo, "rev-parse", "HEAD")
    tip = _add_commit(repo, "tip.txt")
    _add_bare_remote(repo, tmp_path)
    stdin = _fixture(
        "stdin-multiple-refs.txt",
        {
            "LOCAL_REF_1": "refs/heads/one",
            "LOCAL_OID_1": tip,
            "REMOTE_REF_1": "refs/heads/one",
            "REMOTE_OID_1": root,
            "LOCAL_REF_2": "refs/heads/two",
            "LOCAL_OID_2": tip,
            "REMOTE_REF_2": "refs/heads/two",
            "REMOTE_OID_2": middle,
        },
    )
    result, commits = _run_fake(repo, tmp_path, stdin)
    assert result.returncode == 0
    assert commits == {middle, tip}


def test_disconnected_rows_form_exact_union(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    first_base = _git(repo, "rev-parse", "HEAD")
    first_tip = _add_commit(repo, "first.txt")
    _git_run(repo, "checkout", "--orphan", "other")
    _git_run(repo, "rm", "-rf", ".")
    second_base = _add_commit(repo, "second-base.txt")
    second_tip = _add_commit(repo, "second-tip.txt")
    _add_bare_remote(repo, tmp_path)
    stdin = _row("refs/heads/first", first_tip, "refs/heads/first", first_base)
    stdin += _row("refs/heads/other", second_tip, "refs/heads/other", second_base)
    result, commits = _run_fake(repo, tmp_path, stdin)
    assert result.returncode == 0
    assert commits == {first_tip, second_tip}


def test_force_update_scans_local_side_not_merge_base_approximation(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    old_tip = _add_commit(repo, "old.txt")
    _git_run(repo, "reset", "--hard", base)
    local_tip = _add_commit(repo, "replacement.txt")
    _add_bare_remote(repo, tmp_path)
    result, commits = _run_fake(
        repo,
        tmp_path,
        _row("refs/heads/main", local_tip, "refs/heads/main", old_tip),
    )
    assert result.returncode == 0
    assert commits == {local_tip}


@pytest.mark.parametrize(
    ("local_oid", "remote_oid", "message"),
    [
        ("a" * 39, ZERO, "malformed local OID"),
        ("g" * 40, ZERO, "malformed local OID"),
        ("a" * 64, ZERO, "malformed local OID"),
        (ZERO, "b" * 39, "malformed remote OID"),
    ],
)
def test_malformed_oid_is_classified(
    tmp_path: Path, local_oid: str, remote_oid: str, message: str
) -> None:
    repo = _setup_repo(tmp_path)
    _add_bare_remote(repo, tmp_path)
    result, _ = _run_fake(
        repo,
        tmp_path,
        _row("refs/heads/main", local_oid, "refs/heads/main", remote_oid),
    )
    assert result.returncode == 3
    assert message in result.stderr


def test_malformed_field_count_is_rejected(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    _add_bare_remote(repo, tmp_path)
    result, _ = _run_fake(repo, tmp_path, (FIXTURES / "stdin-malformed.txt").read_text())
    assert result.returncode == 3
    assert "malformed pre-push row" in result.stderr


def test_sha256_repository_requires_64_character_oids(tmp_path: Path) -> None:
    repo = tmp_path / "sha256-repo"
    subprocess.run(
        ["git", "init", "--object-format=sha256", "--initial-branch=main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git_run(repo, "config", "user.email", "test@example.com")
    _git_run(repo, "config", "user.name", "Test User")
    first = _add_commit(repo, "first.txt")
    second = _add_commit(repo, "second.txt")
    assert len(first) == 64
    _add_bare_remote(repo, tmp_path)
    result, commits = _run_fake(
        repo,
        tmp_path,
        _row("refs/heads/main", second, "refs/heads/main", first),
    )
    assert result.returncode == 0
    assert commits == {second}


@pytest.mark.parametrize("missing_side", ["local", "remote"])
def test_missing_object_is_classified(tmp_path: Path, missing_side: str) -> None:
    repo = _setup_repo(tmp_path)
    _add_bare_remote(repo, tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    missing = "a" * 40
    local_oid, remote_oid = (missing, head) if missing_side == "local" else (head, missing)
    result, _ = _run_fake(
        repo,
        tmp_path,
        _row("refs/heads/main", local_oid, "refs/heads/main", remote_oid),
    )
    assert result.returncode == 3
    assert f"{missing_side} object" in result.stderr
    assert "unavailable locally" in result.stderr


def test_alternate_remote_is_queried_and_url_is_never_logged(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    _git_run(repo, "remote", "add", "origin", str(tmp_path / "missing-origin.git"))
    _add_bare_remote(repo, tmp_path, "secondary")
    local_oid = _add_commit(repo, "alternate.txt")
    result, commits = _run_fake(
        repo,
        tmp_path,
        _row("refs/heads/new", local_oid, "refs/heads/new", ZERO),
        remote="secondary",
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0
    assert commits == {local_oid}
    assert "url-secret" not in output
    assert "example.invalid" not in output


def test_unnamed_destination_existing_ref_needs_no_remote_lookup(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    local_oid = _git(repo, "rev-parse", "HEAD")
    remote_oid = _git(repo, "rev-parse", "HEAD~1")
    result, commits = _run_fake(
        repo,
        tmp_path,
        _row("refs/heads/main", local_oid, "refs/heads/main", remote_oid),
        remote=SENTINEL_URL,
    )
    assert result.returncode == 0
    assert commits == {local_oid}
    assert "url-secret" not in result.stdout + result.stderr


def test_unnamed_destination_delete_needs_no_remote_lookup(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    remote_oid = _git(repo, "rev-parse", "HEAD")
    result, commits = _run_fake(
        repo,
        tmp_path,
        _row("(delete)", ZERO, "refs/heads/old", remote_oid),
        remote=SENTINEL_URL,
    )
    assert result.returncode == 0
    assert commits == set()
    assert "url-secret" not in result.stdout + result.stderr


def test_unnamed_destination_new_ref_queries_location(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    remote_repo = _add_bare_remote(repo, tmp_path)
    local_oid = _add_commit(repo, "unnamed.txt")
    location = str(remote_repo)
    result, commits = _run_fake(
        repo,
        tmp_path,
        _row("refs/heads/new", local_oid, "refs/heads/new", ZERO),
        remote=location,
        url=location,
    )
    assert result.returncode == 0
    assert commits == {local_oid}


def test_dash_prefixed_configured_remote_is_rejected_safely(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    remote_repo = _add_bare_remote(repo, tmp_path)
    _git_run(repo, "config", "remote.-unsafe.url", str(remote_repo))
    _git_run(repo, "config", "remote.-unsafe.fetch", "+refs/heads/*:refs/remotes/-unsafe/*")
    local_oid = _add_commit(repo, "dash-remote.txt")
    result, commits = _run_fake(
        repo,
        tmp_path,
        _row("refs/heads/new", local_oid, "refs/heads/new", ZERO),
        remote="-unsafe",
        url=str(remote_repo),
    )
    assert result.returncode == 3
    assert "must not begin with '-'" in result.stderr
    assert commits == set()


def test_remote_query_failure_fails_closed_without_url(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    _git_run(repo, "remote", "add", "broken", str(tmp_path / "missing.git"))
    head = _git(repo, "rev-parse", "HEAD")
    result, commits = _run_fake(
        repo,
        tmp_path,
        _row("refs/heads/new", head, "refs/heads/new", ZERO),
        remote="broken",
    )
    output = result.stdout + result.stderr
    assert result.returncode == 3
    assert "failed to query advertised remote refs" in output
    assert commits == set()
    assert "url-secret" not in output


def test_empty_remote_fails_closed(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    remote = tmp_path / "empty.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    _git_run(repo, "remote", "add", "empty", str(remote))
    head = _git(repo, "rev-parse", "HEAD")
    result, _ = _run_fake(
        repo,
        tmp_path,
        _row("refs/heads/new", head, "refs/heads/new", ZERO),
        remote="empty",
    )
    assert result.returncode == 3
    assert "unexpectedly advertised no refs" in result.stderr


def test_advertised_object_unavailable_locally_fails_closed(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    subprocess.run(
        ["bash", str(FIXTURES / "clean-repo-setup.sh"), str(foreign)],
        check=True,
        capture_output=True,
    )
    _add_commit(foreign, "foreign-only.txt")
    remote = _add_bare_remote(foreign, tmp_path, "foreign-remote")
    _git_run(repo, "remote", "add", "foreign", str(remote))
    head = _git(repo, "rev-parse", "HEAD")
    result, _ = _run_fake(
        repo,
        tmp_path,
        _row("refs/heads/new", head, "refs/heads/new", ZERO),
        remote="foreign",
    )
    assert result.returncode == 3
    assert "advertised remote object" in result.stderr
    assert "unavailable locally" in result.stderr


def test_annotated_commit_tag_is_peeled(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    _git_run(repo, "tag", "-a", "release", "-m", "release", "HEAD")
    tag_oid = _git(repo, "rev-parse", "release")
    commit_oid = _git(repo, "rev-parse", "release^{}")
    _add_bare_remote(repo, tmp_path)
    result, commits = _run_fake(
        repo,
        tmp_path,
        _row("refs/tags/release", tag_oid, "refs/tags/release", ZERO),
    )
    assert result.returncode == 0
    assert commit_oid not in commits


def test_noncommit_tag_fails_closed(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    blob_oid = _git(repo, "hash-object", "README.md")
    _git_run(repo, "tag", "-a", "blob-tag", "-m", "blob", blob_oid)
    _add_bare_remote(repo, tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    result, _ = _run_fake(
        repo,
        tmp_path,
        _row("refs/heads/new", head, "refs/heads/new", ZERO),
    )
    assert result.returncode == 3
    assert "does not peel to a commit" in result.stderr


def test_root_commit_is_in_exact_union(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    remote = _add_bare_remote(repo, tmp_path)
    _git_run(repo, "checkout", "--orphan", "root-only")
    _git_run(repo, "rm", "-rf", ".")
    root = _add_commit(repo, "root.txt")
    assert remote.exists()
    result, commits = _run_fake(
        repo,
        tmp_path,
        _row("refs/heads/root-only", root, "refs/heads/root-only", ZERO),
    )
    assert result.returncode == 0
    assert commits == {root}


@pytest.mark.parametrize(("scanner_exit", "expected"), [("0", 0), ("10", 10), ("7", 7)])
def test_scanner_exit_classification(tmp_path: Path, scanner_exit: str, expected: int) -> None:
    repo = _setup_repo(tmp_path)
    _add_bare_remote(repo, tmp_path)
    local_oid = _git(repo, "rev-parse", "HEAD")
    remote_oid = _git(repo, "rev-parse", "HEAD~1")
    result, _ = _run_fake(
        repo,
        tmp_path,
        _row("refs/heads/main", local_oid, "refs/heads/main", remote_oid),
        env_extra={"FAKE_GITLEAKS_EXIT": scanner_exit},
    )
    assert result.returncode == expected


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks not installed")
def test_real_binary_clean_and_finding_fixtures(tmp_path: Path) -> None:
    clean = _setup_repo(tmp_path / "clean")
    finding = _setup_repo(tmp_path / "finding", "secret-repo-setup.sh")
    clean_result = _run(clean, ["ci-full"])
    finding_result = _run(finding, ["ci-full"])
    assert clean_result.returncode == 0
    assert finding_result.returncode == 10


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks not installed")
def test_real_binary_honours_exact_gitleaksignore_fingerprint(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path, "secret-repo-setup.sh")
    remote_oid = _git(repo, "rev-parse", "HEAD~1")
    local_oid = _git(repo, "rev-parse", "HEAD")
    _add_bare_remote(repo, tmp_path)
    row = _row("refs/heads/main", local_oid, "refs/heads/main", remote_oid)
    finding = _run(repo, ["pre-push", "upstream", SENTINEL_URL], stdin=row)
    assert finding.returncode == 10
    (repo / ".gitleaksignore").write_text(f"{local_oid}:config.py:generic-api-key:3\n")
    ignored = _run(repo, ["pre-push", "upstream", SENTINEL_URL], stdin=row)
    assert ignored.returncode == 0


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks not installed")
def test_real_binary_scans_merge_resolution_against_first_parent(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    _git_run(repo, "checkout", "-b", "side")
    (repo / "resolution.txt").write_text("side value\n")
    _git_run(repo, "add", "resolution.txt")
    _git_run(repo, "commit", "-m", "side change")
    _git_run(repo, "checkout", "main")
    (repo / "resolution.txt").write_text("main value\n")
    _git_run(repo, "add", "resolution.txt")
    _git_run(repo, "commit", "-m", "main change")
    first_parent = _git(repo, "rev-parse", "HEAD")

    merge = subprocess.run(
        ["git", "merge", "side", "-m", "merge side"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert merge.returncode != 0
    (repo / "resolution.txt").write_text('API_SECRET = "c4a82c662a22c001b83142d1265c7fb8360b3aa"\n')
    _git_run(repo, "add", "resolution.txt")
    _git_run(repo, "commit", "--no-edit")
    merge_oid = _git(repo, "rev-parse", "HEAD")

    row = _row("refs/heads/main", merge_oid, "refs/heads/main", first_parent)
    result = _run(repo, ["pre-push", SENTINEL_URL, SENTINEL_URL], stdin=row)
    assert result.returncode == 10
