from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import discover_mutate_diff_files as mutate_diff_files


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _initialise_repo(repo_root: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_root, capture_output=True, text=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )


def _write(repo_root: Path, relative_path: str, content: str) -> Path:
    target = repo_root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def test_discover_mutate_diff_files_unions_git_sources_and_dedupes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    for relative_path in (
        "src/perplexity_cli/committed.py",
        "src/perplexity_cli/staged.py",
        "src/perplexity_cli/unstaged.py",
        "src/perplexity_cli/untracked.py",
        "src/perplexity_cli/staged_only.py",
    ):
        _write(repo_root, relative_path, "value = 1\n")

    _write(repo_root, "src/perplexity_cli/package/__init__.py", "\n")
    _write(repo_root, "src/perplexity_cli/package/__pycache__/ignored.py", "ignored = 1\n")

    responses = {
        ("rev-parse", "--abbrev-ref", "origin/HEAD"): ["origin/main"],
        (
            "diff",
            "--name-only",
            "origin/main...HEAD",
            "--",
            "src/perplexity_cli/",
        ): [
            "src/perplexity_cli/committed.py",
            "src/perplexity_cli/staged_only.py",
            "src/perplexity_cli/package/__init__.py",
            "src/perplexity_cli/package/__pycache__/ignored.py",
        ],
        (
            "diff",
            "--name-only",
            "--cached",
            "--",
            "src/perplexity_cli/",
        ): ["src/perplexity_cli/staged.py", "src/perplexity_cli/staged_only.py"],
        ("diff", "--name-only", "--", "src/perplexity_cli/"): [
            "src/perplexity_cli/unstaged.py",
            "src/perplexity_cli/committed.py",
        ],
        (
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            "src/perplexity_cli/",
        ): ["src/perplexity_cli/untracked.py"],
    }

    def fake_git_lines(*args: str) -> list[str]:
        return responses.get(args, [])

    monkeypatch.setattr(mutate_diff_files, "PROJECT_ROOT", repo_root)
    monkeypatch.setattr(mutate_diff_files, "_git_lines", fake_git_lines)

    assert mutate_diff_files.discover_mutate_diff_files() == [
        "src/perplexity_cli/committed.py",
        "src/perplexity_cli/staged.py",
        "src/perplexity_cli/staged_only.py",
        "src/perplexity_cli/unstaged.py",
        "src/perplexity_cli/untracked.py",
    ]


def test_discover_mutate_diff_files_includes_staged_only_source_edits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _initialise_repo(repo_root)

    _write(repo_root, "src/perplexity_cli/base.py", "base = 1\n")
    _write(repo_root, "src/perplexity_cli/package/__init__.py", "\n")
    _write(repo_root, "src/perplexity_cli/package/__pycache__/ignored.py", "ignored = 1\n")
    subprocess.run(["git", "add", "src"], cwd=repo_root, capture_output=True, text=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "base"], cwd=repo_root, capture_output=True, text=True, check=True
    )

    _write(repo_root, "src/perplexity_cli/base.py", "base = 2\n")
    _write(repo_root, "src/perplexity_cli/staged_only.py", "staged = 1\n")
    _write(repo_root, "src/perplexity_cli/unstaged_only.py", "unstaged = 1\n")
    _write(repo_root, "src/perplexity_cli/untracked_only.py", "untracked = 1\n")
    subprocess.run(
        ["git", "add", "src/perplexity_cli/staged_only.py"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )

    monkeypatch.setattr(mutate_diff_files, "PROJECT_ROOT", repo_root)

    assert mutate_diff_files.discover_mutate_diff_files() == [
        "src/perplexity_cli/base.py",
        "src/perplexity_cli/staged_only.py",
        "src/perplexity_cli/unstaged_only.py",
        "src/perplexity_cli/untracked_only.py",
    ]


def test_discover_mutate_diff_files_skips_when_no_source_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _initialise_repo(repo_root)

    _write(repo_root, "src/perplexity_cli/base.py", "base = 1\n")
    subprocess.run(["git", "add", "src"], cwd=repo_root, capture_output=True, text=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "base"], cwd=repo_root, capture_output=True, text=True, check=True
    )

    _write(repo_root, "README.md", "docs only\n")

    monkeypatch.setattr(mutate_diff_files, "PROJECT_ROOT", repo_root)

    assert mutate_diff_files.discover_mutate_diff_files() == []
