"""Discover source files changed relative to a git baseline for mutation testing.

Uses ``scripts.differential_context`` to compute a structured diff context,
then extracts a manifest of Python source files to mutate.  Supports
``--base-sha``/``--tested-sha`` (CI mode) and ``--local`` (worktree mode).

Exit codes::

    0  source files found for mutation
    1  no production source changes detected
    2  Git or context error

Usage::

    # CI mode
    uv run python scripts/discover_mutate_diff_files.py \
        --base-sha main --tested-sha abc123

    # Local worktree mode
    uv run python scripts/discover_mutate_diff_files.py --local
"""

from __future__ import annotations

import json
import logging

# owner: quality-infrastructure; reason: invoke Git with internally assembled argv and no shell
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from scripts.differential_context import DiffContext

_PROJECT_ROOT_PATH = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_PATH))

logger = logging.getLogger(__name__)

PROJECT_ROOT: Path = _PROJECT_ROOT_PATH
SOURCE_ROOT: str = "src/perplexity_cli/"


EXIT_SOURCE_CHANGES = 0
EXIT_NO_PRODUCTION_CHANGES = 1
EXIT_GIT_ERROR = 2


class RenameEntry(TypedDict):
    """A renamed path pair in the mutation manifest."""

    old: str
    new: str


class MutationManifest(TypedDict):
    """Stable JSON schema emitted by mutation discovery."""

    schema_version: str
    changed_files: list[str]
    deletions: list[str]
    renames: list[RenameEntry]


@dataclass(frozen=True, slots=True)
class DiscoveryOptions:
    """Immutable command-line options for mutation discovery."""

    base_sha: str | None
    tested_sha: str | None
    local: bool
    manifest: bool


def _run_git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    """Run an internally assembled Git command without a shell."""
    command = ["git", *args]
    try:
        # owner: quality-infrastructure; reason: internal Git argv keeps refs discrete and disables shell
        result = subprocess.run(  # nosec B603
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30.0,
            check=False,
        )
    except FileNotFoundError:
        return -1, "", "git executable not found"
    except subprocess.TimeoutExpired:
        return -2, "", "git command timed out after 30.0s"
    except OSError as exc:
        return -3, "", f"git command failed: {exc}"
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _resolve_ref(ref: str) -> str:
    """Expand a symbolic ref to a full SHA.

    Args:
        ref: A branch name, tag, or abbreviated SHA.

    Returns:
        The full 40-character SHA, or the input unchanged on failure.
    """
    returncode, stdout, stderr = _run_git(
        ["rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
        cwd=PROJECT_ROOT,
    )
    if returncode != 0:
        logger.warning("Could not resolve ref %s: %s", ref, stderr)
        return ref
    return stdout if stdout else ref


def _is_production_python_source(path: str) -> bool:
    """Return True if *path* is a Python file under the production source tree.

    Args:
        path: A file path relative to the repository root.

    Returns:
        True if the path is a candidate mutation target.
    """
    candidate = PROJECT_ROOT / path
    if not path.startswith(SOURCE_ROOT) or not path.endswith(".py"):
        return False
    if "__pycache__" in candidate.parts:
        return False
    return candidate.is_file()


def _build_manifest(
    changed_files: tuple[str, ...],
    deletions: tuple[str, ...],
    renames: tuple[tuple[str, str], ...],
) -> MutationManifest:
    """Build a structured manifest dictionary.

    Args:
        changed_files: All changed source files (including __init__.py).
        deletions: Files that were deleted.
        renames: Pairs of (old_path, new_path) for renamed files.

    Returns:
        A dictionary suitable for JSON serialization.
    """
    return {
        "schema_version": "1",
        "changed_files": list(changed_files),
        "deletions": list(deletions),
        "renames": [{"old": old, "new": new} for old, new in renames],
    }


def _collect_local_source_files() -> tuple[str, ...]:
    """Collect locally changed source files from worktree.

    Returns:
        A tuple of relative file paths.
    """
    seen: dict[str, None] = {}
    for cmd_args in (
        ("diff", "--name-only", "--cached", "--", SOURCE_ROOT),
        ("diff", "--name-only", "--", SOURCE_ROOT),
        ("ls-files", "--others", "--exclude-standard", "--", SOURCE_ROOT),
    ):
        returncode, stdout, stderr = _run_git(list(cmd_args), cwd=PROJECT_ROOT)
        if returncode != 0:
            logger.warning(
                "git %s failed (returncode=%s): %s",
                " ".join(cmd_args),
                returncode,
                stderr,
            )
            continue
        for line in stdout.split("\n"):
            stripped = line.strip()
            if stripped:
                seen[stripped] = None
    return tuple(seen.keys())


_MIN_PARTS_DELETE = 2
_MIN_PARTS_RENAME = 3


def _is_delete_status(status: str, num_parts: int) -> bool:
    """Check if git diff status line indicates a deleted file.

    Args:
        status: The status character(s) from git diff --name-status.
        num_parts: Number of tab-separated parts in the line.

    Returns:
        True if this is a deletion with sufficient data.
    """
    return status == "D" and num_parts >= _MIN_PARTS_DELETE


def _is_rename_status(status: str, num_parts: int) -> bool:
    """Check if git diff status line indicates a renamed file.

    Args:
        status: The status character(s) from git diff --name-status.
        num_parts: Number of tab-separated parts in the line.

    Returns:
        True if this is a rename with sufficient data.
    """
    return status.startswith("R") and num_parts >= _MIN_PARTS_RENAME


def _handle_rename_line(parts: list[str], renames: list[tuple[str, str]]) -> None:
    """Process a git diff rename line and append to renames list if relevant."""
    old_path = parts[1]
    new_path = parts[2]
    if _is_production_python_source(old_path) or _is_production_python_source(new_path):
        renames.append((old_path, new_path))


def _handle_delete_line(parts: list[str], deletions: list[str]) -> None:
    """Process a git diff delete line and append to deletions list if relevant."""
    path = parts[1]
    if _is_production_python_source(path):
        deletions.append(path)


def _parse_diff_status_output(stdout: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Parse git ``diff --name-status`` output for deletions and renames.

    Args:
        stdout: Raw stdout from ``git diff --name-status``.

    Returns:
        A tuple of (deletions_list, renames_list).
    """
    deletions: list[str] = []
    renames: list[tuple[str, str]] = []
    for line in stdout.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split("\t")
        num_parts = len(parts)
        status = parts[0]
        if _is_rename_status(status, num_parts):
            _handle_rename_line(parts, renames)
        elif _is_delete_status(status, num_parts):
            _handle_delete_line(parts, deletions)
    return deletions, renames


def _process_git_diff_status(
    from_sha: str, to_sha: str
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    """Detect deleted and renamed files between two SHAs.

    Args:
        from_sha: The base commit SHA.
        to_sha: The target commit SHA.

    Returns:
        A tuple of (deletions, renames) where renames are (old, new) pairs.
    """
    returncode, stdout, stderr = _run_git(
        ["diff", "--name-status", "--diff-filter=DR", f"{from_sha}...{to_sha}"],
        cwd=PROJECT_ROOT,
    )
    if returncode != 0:
        logger.warning("git diff --name-status failed (returncode=%s): %s", returncode, stderr)
        return (), ()
    deletions, renames = _parse_diff_status_output(stdout)
    return tuple(deletions), tuple(renames)


def _classify_result(
    changed_files: tuple[str, ...],
    deletions: tuple[str, ...],
    renames: tuple[tuple[str, str], ...],
) -> tuple[MutationManifest, int]:
    """Determine exit code from collected results.

    Args:
        changed_files: Production source files that were changed.
        deletions: Production source files that were deleted.
        renames: Rename pairs involving production source files.

    Returns:
        A tuple of (manifest_dict, exit_code).
    """
    manifest = _build_manifest(changed_files, deletions, renames)
    has_any_changes = bool(changed_files or deletions or renames)
    if not has_any_changes:
        logger.info("No production Python source files changed")
        return manifest, EXIT_NO_PRODUCTION_CHANGES
    logger.info("Found %s changed production source file(s)", len(changed_files))
    return manifest, EXIT_SOURCE_CHANGES


def _compute_ci_manifest(base_sha: str, tested_sha: str) -> tuple[MutationManifest, int]:
    """Compute manifest for a CI differential comparison.

    Args:
        base_sha: The base reference for comparison.
        tested_sha: The SHA under test.

    Returns:
        A tuple of (manifest_dict, exit_code).
    """
    from scripts.differential_context import compute_ci_context

    resolved_base = _resolve_ref(base_sha)
    resolved_tested = _resolve_ref(tested_sha)
    ctx = compute_ci_context(resolved_base, resolved_tested, cwd=PROJECT_ROOT)
    return _process_diff_context(ctx)


def _compute_local_manifest() -> tuple[MutationManifest, int]:
    """Compute manifest for local worktree changes.

    Returns:
        A tuple of (manifest_dict, exit_code).
    """
    from scripts.differential_context import compute_local_context

    ctx = compute_local_context(cwd=PROJECT_ROOT)
    return _process_diff_context(ctx)


def _make_empty_manifest() -> MutationManifest:
    """Return an empty manifest dictionary."""
    return _build_manifest((), (), ())


def _handle_git_error(ctx: DiffContext) -> tuple[MutationManifest, int]:
    """Handle a git error from a DiffContext.

    Args:
        ctx: A DiffContext that has a git error.

    Returns:
        A tuple of (empty_manifest, EXIT_GIT_ERROR).
    """
    error_msg = ctx.git_error_details.stderr if ctx.git_error_details else "Unknown git error"
    logger.error("Git error computing diff context: %s", error_msg)
    return _make_empty_manifest(), EXIT_GIT_ERROR


def _filter_production_files(files: tuple[str, ...]) -> tuple[str, ...]:
    """Filter a tuple of file paths to only production Python source files.

    Args:
        files: Tuple of file paths.

    Returns:
        Tuple containing only production source file paths.
    """
    return tuple(p for p in files if _is_production_python_source(p))


def _resolve_diff_refs(ctx: DiffContext) -> tuple[str, str]:
    """Extract base and head refs from a DiffContext.

    Args:
        ctx: A DiffContext from differential_context.py.

    Returns:
        A tuple of (base_ref, head_ref). Either may be empty.
    """
    base_ref = ctx.merge_base or ctx.base_tip or ""
    head_ref = ctx.event_head or ""
    return base_ref, head_ref


def _collect_rename_details(
    ctx: DiffContext,
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    """Collect deletions and renames from a diff context.

    Args:
        ctx: A DiffContext from differential_context.py.

    Returns:
        A tuple of (deletions, renames).
    """
    if ctx.is_empty_diff:
        return (), ()
    base_ref, head_ref = _resolve_diff_refs(ctx)
    if not base_ref or not head_ref:
        return (), ()
    return _process_git_diff_status(base_ref, head_ref)


def _is_local_dirty(ctx: DiffContext) -> bool:
    """Check if the DiffContext indicates dirty worktree."""
    return ctx.local_dirty


def _resolve_changed_files(ctx: DiffContext) -> tuple[str, ...]:
    """Extract changed file paths from a DiffContext.

    Args:
        ctx: A DiffContext from differential_context.py.

    Returns:
        A tuple of changed file paths.
    """
    if _is_local_dirty(ctx):
        return _collect_local_source_files()
    return ctx.changed_files


def _process_diff_context(ctx: DiffContext) -> tuple[MutationManifest, int]:
    """Process a DiffContext to extract mutation target files.

    Args:
        ctx: A DiffContext from differential_context.py.

    Returns:
        A tuple of (manifest_dict, exit_code).
    """
    if ctx.git_error:
        return _handle_git_error(ctx)

    if not _is_local_dirty(ctx) and ctx.is_empty_diff:
        return _make_empty_manifest(), EXIT_NO_PRODUCTION_CHANGES

    all_files = _resolve_changed_files(ctx)
    production_files = _filter_production_files(all_files)
    deletions, renames = _collect_rename_details(ctx)

    return _classify_result(production_files, deletions, renames)


# owner: quality-infrastructure; reason: backwards-compatible public discovery API
def discover_mutate_diff_files(  # nosemgrep: boolean-flag-argument
    base_sha: str | None = None,
    tested_sha: str | None = None,
    local: bool = False,
) -> tuple[MutationManifest, int]:
    """Discover source files to mutate between two git references.

    Args:
        base_sha: The base commit/branch for comparison.
        tested_sha: The tested commit/branch for comparison.
        local: If True, compute local worktree diff instead.

    Returns:
        A tuple of (manifest_dict, exit_code).
    """
    if local:
        return _compute_local_manifest()
    if base_sha and tested_sha:
        return _compute_ci_manifest(base_sha, tested_sha)
    logger.error("Must specify --local or both --base-sha and --tested-sha")
    return _make_empty_manifest(), EXIT_GIT_ERROR


def _parse_args(
    args: list[str] | None = None,
) -> tuple[str | None, str | None, bool, bool]:
    """Parse command-line arguments.

    Args:
        args: Argument list or None for sys.argv.

    Returns:
        A tuple of (base_sha, tested_sha, local, manifest_output).
    """
    import argparse

    parser = argparse.ArgumentParser(description="Discover source files for mutation testing")
    parser.add_argument("--base-sha", default=None, help="Base commit/branch")
    parser.add_argument("--tested-sha", default=None, help="Tested commit/branch")
    parser.add_argument("--local", action="store_true", help="Local worktree diff")
    parser.add_argument(
        "--manifest", action="store_true", help="Write structured JSON manifest to stdout"
    )
    parsed = parser.parse_args(args)
    return parsed.base_sha, parsed.tested_sha, parsed.local, parsed.manifest


def _parse_options(args: list[str] | None = None) -> DiscoveryOptions:
    """Construct immutable CLI options from the compatibility parser."""
    base_sha, tested_sha, local, manifest = _parse_args(args)
    return DiscoveryOptions(
        base_sha=base_sha,
        tested_sha=tested_sha,
        local=local,
        manifest=manifest,
    )


def main() -> int:
    """CLI entry point."""
    options = _parse_options()
    manifest, exit_code = discover_mutate_diff_files(
        base_sha=options.base_sha,
        tested_sha=options.tested_sha,
        local=options.local,
    )
    if options.manifest:
        print(json.dumps(manifest, indent=2))
        return exit_code
    for path in manifest.get("changed_files", []):
        print(path)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
