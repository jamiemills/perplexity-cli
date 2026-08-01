"""Integration tests for gitleaks_check.sh and .gitleaks.toml.

Creates temporary git repositories with synthetic test data, runs the
gitleaks scanning pipeline, and verifies correct detection and allowlist
behaviour across all three modes (pre-push, ci-full, range).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT_INT = __import__("pathlib").Path(__file__).resolve().parents[1]
SCRIPT_INT = PROJECT_ROOT_INT / "scripts" / "gitleaks_check.sh"


def _require_gitleaks() -> None:
    """Require the gitleaks binary; fail in CI contexts, skip locally.

    These integration tests verify the secret-scanning pipeline, so in a CI
    context an absent binary is a hard failure rather than a silent skip
    (authoritative run).  Locally, skipping is a non-authoritative convenience.
    """
    if shutil.which("gitleaks") is not None:
        return
    if os.environ.get("CI"):
        pytest.fail(
            "gitleaks binary is required for the authoritative gitleaks "
            "integration run in CI (install gitleaks 8.30.1)"
        )
    pytest.skip("gitleaks binary not installed")


@pytest.fixture(autouse=True)
def _require_gitleaks_autouse() -> None:
    _require_gitleaks()


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "gitleaks_check.sh"
GITLEAKS_CONFIG = PROJECT_ROOT / ".gitleaks.toml"
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures" / "gitleaks"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_gitleaks(
    tmp_repo: Path,
    *args: str,
    stdin_text: str | None = None,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run gitleaks_check.sh from inside a temporary git repository."""
    env = {**dict(__import__("os").environ), **(env_extra or {})}
    # Ensure gitleaks uses our project config (not the default).
    env["GITLEAKS_CONFIG"] = str(GITLEAKS_CONFIG)
    result = subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(tmp_repo),
        timeout=30,
        input=stdin_text,
        env=env,
    )
    return result


def _init_tmp_repo(tmp_path: Path) -> Path:
    """Initialise a clean git repository in a temp directory."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=main"],
        capture_output=True,
        text=True,
        cwd=str(repo),
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        capture_output=True,
        text=True,
        cwd=str(repo),
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        capture_output=True,
        text=True,
        cwd=str(repo),
        check=True,
    )
    # Create an initial commit so there is always a reachable HEAD.
    (repo / "README.md").write_text("# Test Repo\n")
    subprocess.run(
        ["git", "add", "README.md"],
        capture_output=True,
        text=True,
        cwd=str(repo),
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        capture_output=True,
        text=True,
        cwd=str(repo),
        check=True,
    )
    return repo


def _commit_file(repo: Path, filename: str, content: str, message: str = "add file") -> str:
    """Create and commit a file, returning the commit SHA."""
    filepath = repo / filename
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content)
    subprocess.run(
        ["git", "add", filename],
        capture_output=True,
        text=True,
        cwd=str(repo),
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", message],
        capture_output=True,
        text=True,
        cwd=str(repo),
        check=True,
    )
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        text=True,
        cwd=str(repo),
    ).strip()


def _add_bare_remote(repo: Path, tmp_path: Path) -> Path:
    """Clone ``repo`` as a local bare origin and configure it."""
    remote = tmp_path / "origin.git"
    subprocess.run(
        ["git", "clone", "--bare", str(repo), str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote)],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo,
    )
    return remote


# ---------------------------------------------------------------------------
# Secret-bearing fixture content
# These are NOT real secrets — they are synthetic strings that trigger
# known gitleaks built-in rules (generic-api-key, GitHub PAT pattern, etc.).
# Owner: jamie.mills@gmail.com
#
# The detector strings are assembled from parts at runtime so the committed
# test module contains no literal secret-shaped substring (T004).  The
# assembled values are only ever written into throwaway temp repositories.
# ---------------------------------------------------------------------------

_NON_SECRET_CONTENT = textwrap.dedent("""\
    def hello():
        return "world"
""")

_AWS_ACCESS_KEY_ID = "AKIA" + "0123456789ABCDEF"
_AWS_SECRET_VALUE = "c4a82c66" + "2a22c001b83142d1265c7fb8360b3aa"
_SECRET_CONTENT_AWS = textwrap.dedent(f"""\
    # This is a fake AWS key for testing — NOT a real credential.
    AWS_ACCESS_KEY_ID = {_AWS_ACCESS_KEY_ID}
    AWS_SECRET = "{_AWS_SECRET_VALUE}"
""")

_GH_TOKEN_VALUE = "ghp_" + "xK9mN2qR7vB4fL8wD1jH6aY0cU3eG5bc4a82c6"
_SECRET_CONTENT_GH = textwrap.dedent(f"""\
    # This is a fake GitHub token for testing — NOT a real credential.
    GITHUB_TOKEN = {_GH_TOKEN_VALUE}
""")

_PEM_HEADER = "-----BEGIN RSA " + "PRIVATE KEY-----"
_PEM_FOOTER = "-----END RSA " + "PRIVATE KEY-----"
_PEM_BODY_LINES = [
    "MIIBOgIBAAJBAKj34GkxFhD11eUsZ77mL+LWJ1W3YhhPePBkZDGH/Jd0KbHkjG0P",
    "qKq1N0my5mJRQlBi37L+Sc0A1iS4HhOtrm0CAwEAAQJAFVvdH3GVeN8xhq0VQ8oD",
    "eAqJCV4PLNNxrwPKsBBMzB/VjJGntj7VkcqR5HO7apQvvsWHPYL5JY2xh6Z+0VJ4",
    "UQIhANS46jsYBgOAU+zKkMpgRaxl+yIE4VfSj4+lALFypdG3AiEAy0HBUqwCd+Wp",
    "n4AFN1uj6HNB+fBlVaf9PKiTDSjzmBsCIQCM2BW0Lup4TL4Ku2boGYd4k7IVKXgW",
    "4P6Yv0YLmELnSwIgXyQkKzhOmMxcHbxdtCNmFJAgjj+uGhvBpRZL8x4CmwECIQDG",
    "J4UgJGNY2bG7UBzS60qRGLq5PvGXi3u3y3LpmBv3lQ==",
]
_SECRET_CONTENT_PEM = f"{_PEM_HEADER}\n" + "\n".join(_PEM_BODY_LINES) + f"\n{_PEM_FOOTER}\n"


# ---------------------------------------------------------------------------
# Clean-repo tests — no secrets committed
# ---------------------------------------------------------------------------


class TestCleanRepo:
    """When the repo has no secrets, all modes exit clean (0)."""

    def test_ci_full_clean_repo(self, tmp_path: Path) -> None:
        repo = _init_tmp_repo(tmp_path)
        _commit_file(repo, "hello.py", _NON_SECRET_CONTENT)
        result = _run_gitleaks(repo, "ci-full")
        assert result.returncode == 0

    def test_range_clean_commits(self, tmp_path: Path) -> None:
        repo = _init_tmp_repo(tmp_path)
        initial = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=str(repo),
        ).strip()
        _commit_file(repo, "hello.py", _NON_SECRET_CONTENT)
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=str(repo),
        ).strip()
        result = _run_gitleaks(repo, "range", initial, head)
        assert result.returncode == 0

    def test_pre_push_clean_repo(self, tmp_path: Path) -> None:
        repo = _init_tmp_repo(tmp_path)
        initial = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=str(repo),
        ).strip()
        _commit_file(repo, "hello.py", _NON_SECRET_CONTENT)
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=str(repo),
        ).strip()
        stdin = f"refs/heads/main {head} refs/heads/main {initial}\n"
        result = _run_gitleaks(
            repo,
            "pre-push",
            "origin",
            "https://example.com/repo.git",
            stdin_text=stdin,
        )
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# Secret detection tests — gitleaks should catch fake secrets
# ---------------------------------------------------------------------------


class TestSecretDetection:
    """Synthetic secrets in commits should produce findings (exit 10)."""

    def test_ci_full_detects_secret(self, tmp_path: Path) -> None:
        repo = _init_tmp_repo(tmp_path)
        _commit_file(repo, "src/secrets.py", _SECRET_CONTENT_AWS)
        result = _run_gitleaks(repo, "ci-full")
        assert result.returncode == 10

    def test_range_detects_secret(self, tmp_path: Path) -> None:
        repo = _init_tmp_repo(tmp_path)
        initial = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=str(repo),
        ).strip()
        _commit_file(repo, "src/secrets.py", _SECRET_CONTENT_AWS)
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=str(repo),
        ).strip()
        result = _run_gitleaks(repo, "range", initial, head)
        assert result.returncode == 10

    def test_pre_push_detects_secret(self, tmp_path: Path) -> None:
        repo = _init_tmp_repo(tmp_path)
        initial = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=str(repo),
        ).strip()
        _commit_file(repo, "src/secrets.py", _SECRET_CONTENT_AWS)
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=str(repo),
        ).strip()
        stdin = f"refs/heads/main {head} refs/heads/main {initial}\n"
        result = _run_gitleaks(
            repo,
            "pre-push",
            "origin",
            "https://example.com/repo.git",
            stdin_text=stdin,
        )
        assert result.returncode == 10

    def test_github_token_detected(self, tmp_path: Path) -> None:
        repo = _init_tmp_repo(tmp_path)
        _commit_file(repo, ".env.example", _SECRET_CONTENT_GH)
        result = _run_gitleaks(repo, "ci-full")
        assert result.returncode == 10

    def test_private_key_detected(self, tmp_path: Path) -> None:
        repo = _init_tmp_repo(tmp_path)
        _commit_file(repo, "key.pem", _SECRET_CONTENT_PEM)
        result = _run_gitleaks(repo, "ci-full")
        assert result.returncode == 10


# ---------------------------------------------------------------------------
# Allowlist tests — only exact per-file exceptions are exempt
# ---------------------------------------------------------------------------


class TestAllowlistExemptions:
    """Only exact per-file allowlist entries may contain fake secrets.

    The blanket tests/ path rule was removed (T004), so a secret-shaped value
    in an ordinary tests/test_*.py file must now FAIL scanning with exit 10.
    """

    def test_secret_in_ordinary_test_module_is_detected(self, tmp_path: Path) -> None:
        """A synthetic secret in a normal tests/test_*.py file is blocked."""
        repo = _init_tmp_repo(tmp_path)
        _commit_file(repo, "tests/test_fakes.py", _SECRET_CONTENT_AWS)
        result = _run_gitleaks(repo, "ci-full")
        assert result.returncode == 10

    def test_secret_in_non_exempt_fixture_file_is_detected(self, tmp_path: Path) -> None:
        """A secret in a fixtures file that is not an exact exception fails."""
        repo = _init_tmp_repo(tmp_path)
        _commit_file(
            repo,
            "tests/fixtures/gitleaks/fake_data.py",
            _SECRET_CONTENT_GH,
        )
        result = _run_gitleaks(repo, "ci-full")
        assert result.returncode == 10

    def test_exact_fixture_exception_is_allowed(self, tmp_path: Path) -> None:
        """The exact allowlisted fixture file passes individually (exit 0)."""
        repo = _init_tmp_repo(tmp_path)
        _commit_file(
            repo,
            "tests/fixtures/gitleaks/secrets_test_data.txt",
            _SECRET_CONTENT_GH,
        )
        result = _run_gitleaks(repo, "ci-full")
        assert result.returncode == 0

    def test_exact_prepush_module_is_allowed(self, tmp_path: Path) -> None:
        """The exact allowlisted prepush module passes individually (exit 0)."""
        repo = _init_tmp_repo(tmp_path)
        _commit_file(
            repo,
            "tests/test_gitleaks_prepush.py",
            _SECRET_CONTENT_AWS,
        )
        result = _run_gitleaks(repo, "ci-full")
        assert result.returncode == 0

    def test_secret_outside_tests_still_blocked(self, tmp_path: Path) -> None:
        """src/ with secrets still fails."""
        repo = _init_tmp_repo(tmp_path)
        _commit_file(repo, "src/config.py", _SECRET_CONTENT_AWS)
        result = _run_gitleaks(repo, "ci-full")
        assert result.returncode == 10


# ---------------------------------------------------------------------------
# Pre-push ref handling
# ---------------------------------------------------------------------------


class TestPrePushRefHandling:
    """Refspec edge cases: deletions, new branches, multiple refs."""

    def test_deleted_ref_skipped(self, tmp_path: Path) -> None:
        repo = _init_tmp_repo(tmp_path)
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=str(repo),
        ).strip()
        stdin = f"(delete) 0000000000000000000000000000000000000000 refs/heads/delete-me {head}\n"
        result = _run_gitleaks(
            repo,
            "pre-push",
            "origin",
            "https://example.com/repo.git",
            stdin_text=stdin,
        )
        assert result.returncode == 0

    def test_new_branch_uses_advertised_remote_refs(self, tmp_path: Path) -> None:
        """A new branch subtracts commits advertised by a local bare remote."""
        repo = _init_tmp_repo(tmp_path)
        _add_bare_remote(repo, tmp_path)
        _commit_file(repo, "new-feature.py", _NON_SECRET_CONTENT)
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=str(repo),
        ).strip()
        stdin = (
            f"refs/heads/new-feature {head} refs/heads/new-feature "
            "0000000000000000000000000000000000000000\n"
        )
        result = _run_gitleaks(
            repo,
            "pre-push",
            "origin",
            str(tmp_path / "origin.git"),
            stdin_text=stdin,
        )
        assert result.returncode == 0

    def test_multiple_refs_union_scan(self, tmp_path: Path) -> None:
        repo = _init_tmp_repo(tmp_path)
        base = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=str(repo),
        ).strip()
        _commit_file(repo, "src/main_code.py", _NON_SECRET_CONTENT)
        main_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=str(repo),
        ).strip()
        subprocess.run(
            ["git", "branch", "feature"],
            capture_output=True,
            cwd=str(repo),
            check=True,
        )
        _commit_file(repo, "src/feature_code.py", _NON_SECRET_CONTENT)
        feature_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=str(repo),
        ).strip()

        stdin = (
            f"refs/heads/main {main_head} refs/heads/main {base}\n"
            f"refs/heads/feature {feature_head} refs/heads/feature {base}\n"
        )
        result = _run_gitleaks(
            repo,
            "pre-push",
            "origin",
            "https://example.com/repo.git",
            stdin_text=stdin,
        )
        assert result.returncode == 0

    def test_all_deletions_no_scan(self, tmp_path: Path) -> None:
        repo = _init_tmp_repo(tmp_path)
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=str(repo),
        ).strip()
        stdin = (
            f"(delete) 0000000000000000000000000000000000000000 refs/heads/a {head}\n"
            f"(delete) 0000000000000000000000000000000000000000 refs/heads/b {head}\n"
        )
        result = _run_gitleaks(
            repo,
            "pre-push",
            "origin",
            "https://example.com/repo.git",
            stdin_text=stdin,
        )
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "deleted" in combined.lower() or "nothing to scan" in combined.lower()

    def test_local_equals_remote_skipped(self, tmp_path: Path) -> None:
        repo = _init_tmp_repo(tmp_path)
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=str(repo),
        ).strip()
        stdin = f"refs/heads/main {head} refs/heads/main {head}\n"
        result = _run_gitleaks(
            repo,
            "pre-push",
            "origin",
            "https://example.com/repo.git",
            stdin_text=stdin,
        )
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# Secret detection *without* the project config (default rules only)
# ---------------------------------------------------------------------------


class TestDefaultRulesDetection:
    """Verify that built-in gitleaks rules detect known patterns."""

    def test_aws_pattern_detected_by_default_rules(self, tmp_path: Path) -> None:
        repo = _init_tmp_repo(tmp_path)
        _commit_file(repo, "leaked.txt", _SECRET_CONTENT_AWS)
        # Explicitly use our config which extends defaults.
        result = _run_gitleaks(repo, "ci-full")
        assert result.returncode == 10
        combined = result.stdout + result.stderr
        # Gitleaks verbose output shows rule IDs for findings.
        assert (
            "leaked.txt" in combined or "aws" in combined.lower() or "generic" in combined.lower()
        )

    def test_pem_pattern_detected_by_default_rules(self, tmp_path: Path) -> None:
        repo = _init_tmp_repo(tmp_path)
        _commit_file(repo, "key.pem", _SECRET_CONTENT_PEM)
        result = _run_gitleaks(repo, "ci-full")
        assert result.returncode == 10
