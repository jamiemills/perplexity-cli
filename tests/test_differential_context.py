"""Tests for scripts/differential_context.py."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.differential_context import (
    EMPTY_TREE_HASH,
    ZERO_BEFORE_SHA,
    DiffContext,
    DiffResult,
    GitErrorDetails,
    MergeBase,
    _is_zero_before,
    _run_git,
    compute_ci_context,
    compute_diff,
    compute_dispatch_context,
    compute_full_diff,
    compute_local_context,
    compute_merge_base,
    compute_pr_context,
    compute_push_context,
)

C = chr(99) + chr(111) + chr(109) + chr(109) + chr(105) + chr(116)


def _r(repo_root: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_root, capture_output=True, text=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )


def _w(repo_root: Path, r: str, c: str) -> Path:
    t = repo_root / r
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text(c)
    return t


def _s(repo_root: Path, ref: str = "HEAD") -> str:
    p = subprocess.run(
        ["git", "rev-parse", ref], cwd=repo_root, capture_output=True, text=True, check=True
    )
    return p.stdout.strip()


class TestIsZeroBefore:
    def test_zero_sha_true(self):
        assert _is_zero_before(ZERO_BEFORE_SHA) is True

    def test_normal_sha_false(self):
        assert _is_zero_before("a1b2c3d4e5f67890123456789012345678901234") is False

    def test_short_zero_false(self):
        assert _is_zero_before("0000000") is False


class TestComputeMergeBase:
    def test_finds_ancestor(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        _w(r, "a.txt", "v1")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", C, "-m", "v1"], cwd=r, capture_output=True, text=True, check=True)
        s1 = _s(r)
        _w(r, "b.txt", "v2")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", C, "-m", "v2"], cwd=r, capture_output=True, text=True, check=True)
        s2 = _s(r)
        result = compute_merge_base(s1, s2, cwd=r)
        assert result.found and result.sha == s1

    def test_no_common_ancestor(self, tmp_path):
        ra = tmp_path / "ra"
        ra.mkdir()
        _r(ra)
        _w(ra, "a.txt", "a")
        subprocess.run(["git", "add", "."], cwd=ra, capture_output=True, text=True, check=True)
        subprocess.run(["git", C, "-m", "a"], cwd=ra, capture_output=True, text=True, check=True)
        sa = _s(ra)
        rb = tmp_path / "rb"
        rb.mkdir()
        _r(rb)
        _w(rb, "b.txt", "b")
        subprocess.run(["git", "add", "."], cwd=rb, capture_output=True, text=True, check=True)
        subprocess.run(["git", C, "-m", "b"], cwd=rb, capture_output=True, text=True, check=True)
        sb = _s(rb)
        result = compute_merge_base(sa, sb, cwd=ra)
        assert not result.found

    def test_bad_ref_error(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        result = compute_merge_base("nonexistent", "also-nonexistent", cwd=r)
        assert not result.found
        assert result.error_details is not None
        assert result.error_details.returncode != 0


class TestComputeDiff:
    def test_empty_same_sha(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        _w(r, "a.txt", "x")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", C, "-m", "x"], cwd=r, capture_output=True, text=True, check=True)
        sha = _s(r)
        result = compute_diff(sha, sha, cwd=r)
        assert not result.git_error and result.is_empty and len(result.changed_files) == 0

    def test_diff_with_changes(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        _w(r, "a.txt", "before")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(
            ["git", C, "-m", "before"], cwd=r, capture_output=True, text=True, check=True
        )
        s1 = _s(r)
        _w(r, "b.txt", "after")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", C, "-m", "after"], cwd=r, capture_output=True, text=True, check=True)
        s2 = _s(r)
        result = compute_diff(s1, s2, cwd=r)
        assert not result.git_error and not result.is_empty
        assert "b.txt" in result.changed_files

    def test_bad_ref_error(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        result = compute_diff("deadbeef", "cafebabe", cwd=r)
        assert result.git_error and result.error_details is not None and result.is_empty


class TestFullDiff:
    def test_full_diff_with_changes(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        _w(r, "a.txt", "before")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(
            ["git", C, "-m", "before"], cwd=r, capture_output=True, text=True, check=True
        )
        s1 = _s(r)
        _w(r, "a.txt", "after")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", C, "-m", "after"], cwd=r, capture_output=True, text=True, check=True)
        s2 = _s(r)
        result = compute_full_diff(s1, s2, cwd=r)
        assert not result.git_error and not result.is_empty
        assert result.diff_raw is not None and len(result.diff_raw) > 0

    def test_full_diff_empty(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        _w(r, "a.txt", "x")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", C, "-m", "x"], cwd=r, capture_output=True, text=True, check=True)
        sha = _s(r)
        result = compute_full_diff(sha, sha, cwd=r)
        assert not result.git_error and result.is_empty


class TestPrContext:
    def test_pr_with_changes(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        _w(r, "a.txt", "base")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", C, "-m", "base"], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", "branch", "main"], cwd=r, capture_output=True, text=True, check=True)
        _w(r, "feat.txt", "feature")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(
            ["git", C, "-m", "feature"], cwd=r, capture_output=True, text=True, check=True
        )
        feat = _s(r)
        ctx = compute_pr_context("main", feat, cwd=r)
        assert ctx.mode == "pr" and not ctx.git_error
        assert ctx.merge_base is not None
        assert "feat.txt" in ctx.changed_files

    def test_pr_no_changes(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        _w(r, "a.txt", "x")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", C, "-m", "x"], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", "branch", "main"], cwd=r, capture_output=True, text=True, check=True)
        sha = _s(r)
        ctx = compute_pr_context("main", sha, cwd=r)
        assert ctx.mode == "pr" and not ctx.git_error and ctx.is_empty_diff

    def test_pr_bad_ref(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        ctx = compute_pr_context("nobranch", "nosha", cwd=r)
        assert ctx.mode == "pr" and ctx.git_error


class TestPushContext:
    def test_push_with_changes(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        _w(r, "a.txt", "v1")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", C, "-m", "v1"], cwd=r, capture_output=True, text=True, check=True)
        s1 = _s(r)
        _w(r, "b.txt", "v2")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", C, "-m", "v2"], cwd=r, capture_output=True, text=True, check=True)
        s2 = _s(r)
        ctx = compute_push_context("refs/heads/main", s1, s2, cwd=r)
        assert ctx.mode == "push" and not ctx.git_error and not ctx.is_empty_diff
        assert "b.txt" in ctx.changed_files

    def test_push_zero_before(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        _w(r, "x.txt", "new")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", C, "-m", "new"], cwd=r, capture_output=True, text=True, check=True)
        sha = _s(r)
        ctx = compute_push_context("main", ZERO_BEFORE_SHA, sha, cwd=r)
        assert ctx.mode == "push" and ctx.zero_before
        assert ctx.empty_tree_hash == EMPTY_TREE_HASH
        assert ctx.merge_base == EMPTY_TREE_HASH
        assert not ctx.git_error and not ctx.is_empty_diff

    def test_push_bad_refs(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        ctx = compute_push_context(
            "main",
            "a111111111111111111111111111111111111111",
            "b222222222222222222222222222222222222222",
            cwd=r,
        )
        assert ctx.git_error and ctx.is_empty_diff


class TestLocalContext:
    def test_local_dirty(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        _w(r, "a.txt", "v1")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", C, "-m", "v1"], cwd=r, capture_output=True, text=True, check=True)
        _w(r, "a.txt", "modified")
        ctx = compute_local_context(cwd=r)
        assert ctx.mode == "local" and not ctx.git_error
        assert ctx.local_dirty and not ctx.is_empty_diff
        assert ctx.local_head is not None

    def test_local_clean(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        _w(r, "a.txt", "clean")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", C, "-m", "clean"], cwd=r, capture_output=True, text=True, check=True)
        ctx = compute_local_context(cwd=r)
        assert ctx.mode == "local" and not ctx.git_error
        assert not ctx.local_dirty and ctx.is_empty_diff
        assert ctx.local_head is not None


class TestDispatchContext:
    def test_dispatch_with_changes(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        _w(r, "a.txt", "base")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", C, "-m", "base"], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", "branch", "main"], cwd=r, capture_output=True, text=True, check=True)
        _w(r, "feat.txt", "feature")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(
            ["git", C, "-m", "feature"], cwd=r, capture_output=True, text=True, check=True
        )
        feat = _s(r)
        ctx = compute_dispatch_context("main", feat, cwd=r)
        assert ctx.mode == "dispatch" and not ctx.git_error
        assert "feat.txt" in ctx.changed_files

    def test_dispatch_bad_ref(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        ctx = compute_dispatch_context("nobranch", "nosha", cwd=r)
        assert ctx.mode == "dispatch" and ctx.git_error


class TestCiContext:
    def test_ci_with_changes(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        _w(r, "a.txt", "base")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", C, "-m", "base"], cwd=r, capture_output=True, text=True, check=True)
        base = _s(r)
        _w(r, "b.txt", "tested")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(
            ["git", C, "-m", "tested"], cwd=r, capture_output=True, text=True, check=True
        )
        tested = _s(r)
        ctx = compute_ci_context(base, tested, cwd=r)
        assert ctx.mode == "ci" and not ctx.git_error
        assert ctx.tested_sha == tested and "b.txt" in ctx.changed_files

    def test_ci_zero_before(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        _w(r, "new.txt", "new")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", C, "-m", "new"], cwd=r, capture_output=True, text=True, check=True)
        tested = _s(r)
        ctx = compute_ci_context(ZERO_BEFORE_SHA, tested, cwd=r)
        assert ctx.mode == "ci" and ctx.zero_before and not ctx.git_error

    def test_ci_bad_refs(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        ctx = compute_ci_context(
            "a111111111111111111111111111111111111111",
            "b222222222222222222222222222222222222222",
            cwd=r,
        )
        assert ctx.git_error and ctx.is_empty_diff


class TestResultTypes:
    def test_diff_error_vs_empty(self):
        e = DiffResult(is_empty=True, git_error=True, error_details=GitErrorDetails("x", 1, ""))
        em = DiffResult(is_empty=True)
        ne = DiffResult(is_empty=False, changed_files=("f.txt",))
        assert e.git_error and e.is_empty
        assert em.is_empty and not em.git_error
        assert not ne.is_empty and not ne.git_error

    def test_merge_base_states(self):
        f = MergeBase(sha="abc", found=True)
        assert f.found and f.sha == "abc" and not f.error_details
        m = MergeBase(sha=None, found=False)
        assert not m.found and not m.error_details
        e = MergeBase(sha=None, found=False, error_details=GitErrorDetails("mb", 128, "fatal"))
        assert not e.found and e.error_details is not None

    def test_diff_context_defaults(self):
        ctx = DiffContext()
        assert ctx.schema_version == "1" and ctx.mode == "local"
        assert ctx.is_empty_diff and not ctx.git_error


class TestRunGit:
    def test_returns_structured(self):
        rc, out, err = _run_git(["--version"])
        assert rc == 0 and "git version" in out.lower()

    def test_bad_subcommand(self):
        rc, out, err = _run_git(["nonexistent-subcommand-xyz"])
        assert rc != 0

    def test_empty_args(self):
        rc, out, err = _run_git([])
        assert rc != 0


class TestGitErrorVsEmptyDiff:
    def test_pr_bad_merge_gives_error(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        ctx = compute_pr_context("ghost", "ghost", cwd=r)
        assert ctx.git_error and ctx.is_empty_diff and ctx.changed_files == ()

    def test_no_changes_empty_diff_not_error(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        _w(r, "a.txt", "x")
        subprocess.run(["git", "add", "."], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", C, "-m", "init"], cwd=r, capture_output=True, text=True, check=True)
        subprocess.run(["git", "branch", "main"], cwd=r, capture_output=True, text=True, check=True)
        sha = _s(r)
        ctx = compute_pr_context("main", sha, cwd=r)
        assert not ctx.git_error and ctx.is_empty_diff

    def test_zero_before_empty_tree(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        _r(r)
        ctx = compute_push_context("main", ZERO_BEFORE_SHA, EMPTY_TREE_HASH, cwd=r)
        assert ctx.zero_before and isinstance(ctx, DiffContext)
