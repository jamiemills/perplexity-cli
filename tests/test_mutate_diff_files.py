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
    """Changed files are deduplicated across git sources."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    for name in (
        "src/perplexity_cli/committed.py",
        "src/perplexity_cli/staged.py",
        "src/perplexity_cli/unstaged.py",
        "src/perplexity_cli/untracked.py",
        "src/perplexity_cli/staged_only.py",
        "src/perplexity_cli/package/__init__.py",
    ):
        p = repo_root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("value = 1\n")

    (repo_root / "src/perplexity_cli/package/__pycache__/ignored.py").parent.mkdir(
        parents=True, exist_ok=True
    )
    (repo_root / "src/perplexity_cli/package/__pycache__/ignored.py").write_text("ignored=1\n")

    def fake_collect() -> tuple[str, ...]:
        return (
            "src/perplexity_cli/committed.py",
            "src/perplexity_cli/staged.py",
            "src/perplexity_cli/staged_only.py",
            "src/perplexity_cli/unstaged.py",
            "src/perplexity_cli/untracked.py",
            "src/perplexity_cli/package/__init__.py",
            "src/perplexity_cli/package/__pycache__/ignored.py",
        )

    monkeypatch.setattr(mutate_diff_files, "PROJECT_ROOT", repo_root)
    monkeypatch.setattr(mutate_diff_files, "_collect_local_source_files", fake_collect)

    # Bypass git entirely by mocking the diff context computation.
    from scripts.differential_context import DiffContext as DC

    def fake_ctx():
        return DC(mode="local", local_head="abc", local_dirty=True, is_empty_diff=False)

    monkeypatch.setattr(
        "scripts.discover_mutate_diff_files._compute_local_manifest",
        lambda: mutate_diff_files._process_diff_context(fake_ctx()),
    )

    manifest, exit_code = mutate_diff_files.discover_mutate_diff_files(local=True)
    assert exit_code == mutate_diff_files.EXIT_SOURCE_CHANGES
    assert sorted(manifest["changed_files"]) == sorted(
        [
            "src/perplexity_cli/committed.py",
            "src/perplexity_cli/staged.py",
            "src/perplexity_cli/staged_only.py",
            "src/perplexity_cli/unstaged.py",
            "src/perplexity_cli/untracked.py",
            "src/perplexity_cli/package/__init__.py",
        ]
    )


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

    manifest, exit_code = mutate_diff_files.discover_mutate_diff_files(local=True)
    assert exit_code == mutate_diff_files.EXIT_SOURCE_CHANGES
    changed = manifest["changed_files"]
    assert "src/perplexity_cli/base.py" in changed
    assert "src/perplexity_cli/staged_only.py" in changed
    assert "src/perplexity_cli/unstaged_only.py" in changed
    assert "src/perplexity_cli/untracked_only.py" in changed


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

    manifest, exit_code = mutate_diff_files.discover_mutate_diff_files(local=True)
    assert exit_code == mutate_diff_files.EXIT_NO_PRODUCTION_CHANGES
    assert manifest["changed_files"] == []


class TestDiscoverNewFeatures:
    """Tests for the new --base-sha/--tested-sha/--local interface."""

    def test_local_mode_accepts_flag(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """--local mode returns structured results."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        _initialise_repo(repo_root)

        _write(repo_root, "src/perplexity_cli/base.py", "base = 1\n")
        subprocess.run(
            ["git", "add", "."], cwd=repo_root, capture_output=True, text=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        _write(repo_root, "src/perplexity_cli/base.py", "base = 2\n")

        monkeypatch.setattr(mutate_diff_files, "PROJECT_ROOT", repo_root)

        manifest, exit_code = mutate_diff_files.discover_mutate_diff_files(local=True)
        assert exit_code == mutate_diff_files.EXIT_SOURCE_CHANGES
        assert "schema_version" in manifest
        assert "changed_files" in manifest

    def test_manifest_includes_init_py(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """__init__.py files are included in discovery."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        _initialise_repo(repo_root)

        _write(repo_root, "src/perplexity_cli/__init__.py", "__version__ = '1.0'\n")
        subprocess.run(
            ["git", "add", "."], cwd=repo_root, capture_output=True, text=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        _write(repo_root, "src/perplexity_cli/__init__.py", "__version__ = '1.1'\n")

        monkeypatch.setattr(mutate_diff_files, "PROJECT_ROOT", repo_root)

        manifest, _exit_code = mutate_diff_files.discover_mutate_diff_files(local=True)
        changed = manifest["changed_files"]
        assert any("__init__.py" in f for f in changed), (
            f"__init__.py should be discovered: {changed}"
        )

    def test_exit_code_no_changes(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Returns exit code 1 when no source changes."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        _initialise_repo(repo_root)

        _write(repo_root, "src/perplexity_cli/base.py", "base = 1\n")
        subprocess.run(
            ["git", "add", "."], cwd=repo_root, capture_output=True, text=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )

        monkeypatch.setattr(mutate_diff_files, "PROJECT_ROOT", repo_root)

        manifest, exit_code = mutate_diff_files.discover_mutate_diff_files(local=True)
        assert exit_code == mutate_diff_files.EXIT_NO_PRODUCTION_CHANGES
        assert manifest["changed_files"] == []

    def test_git_error_produces_exit_2(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Git error returns exit code 2."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        monkeypatch.setattr(mutate_diff_files, "PROJECT_ROOT", repo_root)

        _manifest, exit_code = mutate_diff_files.discover_mutate_diff_files(
            base_sha="deadbeef00000000000000000000000000000000",
            tested_sha="cafebabe00000000000000000000000000000000",
        )
        assert exit_code == mutate_diff_files.EXIT_GIT_ERROR

    def test_ci_mode_accepts_shas(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """--base-sha and --tested-sha produce structured results."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        _initialise_repo(repo_root)

        _write(repo_root, "src/perplexity_cli/base.py", "base = 1\n")
        subprocess.run(
            ["git", "add", "."], cwd=repo_root, capture_output=True, text=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "commit1"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )

        sha1_result = _run_git(repo_root, "rev-parse", "HEAD")
        sha1 = sha1_result.stdout.strip()

        _write(repo_root, "src/perplexity_cli/new_file.py", "new = 1\n")
        subprocess.run(
            ["git", "add", "."], cwd=repo_root, capture_output=True, text=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "commit2"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )

        sha2_result = _run_git(repo_root, "rev-parse", "HEAD")
        sha2 = sha2_result.stdout.strip()

        monkeypatch.setattr(mutate_diff_files, "PROJECT_ROOT", repo_root)

        _manifest, exit_code = mutate_diff_files.discover_mutate_diff_files(
            base_sha=sha1, tested_sha=sha2
        )
        assert exit_code in (
            mutate_diff_files.EXIT_SOURCE_CHANGES,
            mutate_diff_files.EXIT_NO_PRODUCTION_CHANGES,
        )

    def test_rename_detection(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Renames between commits are detected."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        _initialise_repo(repo_root)

        _write(repo_root, "src/perplexity_cli/old_name.py", "old = 1\n")
        subprocess.run(
            ["git", "add", "."], cwd=repo_root, capture_output=True, text=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "commit1"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        sha1 = _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()

        subprocess.run(
            ["git", "mv", "src/perplexity_cli/old_name.py", "src/perplexity_cli/new_name.py"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "rename"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        sha2 = _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()

        monkeypatch.setattr(mutate_diff_files, "PROJECT_ROOT", repo_root)

        manifest, exit_code = mutate_diff_files.discover_mutate_diff_files(
            base_sha=sha1, tested_sha=sha2
        )
        assert exit_code == mutate_diff_files.EXIT_SOURCE_CHANGES
        renames = manifest.get("renames", [])
        assert len(renames) >= 1, f"Expected at least 1 rename, got {renames}"
