"""Differential comparison module for computing structured diff contexts.

Supports multiple modes (local, PR, push, dispatch, CI) and handles all
git command failures explicitly.  Never returns raw strings
every
result is a typed dataclass that distinguishes git failures from empty
diffs.

Usage::

    from scripts.differential_context import (
        compute_pr_context,
        compute_push_context,
        compute_local_context,
        compute_dispatch_context,
    )

    ctx = compute_pr_context(base_tip="main", event_head="abc123")
    if ctx.git_error:
        logger.error("Git error: %s", ctx.git_error_details)
    elif ctx.is_empty_diff:
        logger.info("No changes detected")
    else:
        for f in ctx.changed_files:
            logger.info("Changed: %s", f)

See also: quality/schemas/differential-context-v1.json
"""

from __future__ import annotations

import logging
import subprocess  # nosec B404  # owner: quality-infrastructure; reason: git argv is structurally delimited and always runs without a shell
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

EMPTY_TREE_HASH = "4b825dc642cb6eb9a060e54bf892b69e8b9e75fe"
ZERO_BEFORE_SHA = "0000000000000000000000000000000000000000"
_MIN_SHA_LENGTH = 40

DiffMode = Literal["local", "pr", "push", "dispatch", "ci"]

_ALLOWED_GIT_COMMANDS = frozenset(
    {"--version", "diff", "diff-index", "log", "merge-base", "rev-parse"}
)
_FORBIDDEN_GIT_OPTIONS = frozenset({"-c", "--exec-path", "--ext-diff", "--textconv"})


@dataclass(frozen=True, slots=True)
class GitErrorDetails:
    """Information about a failed git command."""

    command: str
    returncode: int
    stderr: str


@dataclass(frozen=True, slots=True)
class MergeBase:
    """Validated result of git merge-base computation.

    found is True when a common ancestor exists.  When found is
    False, either the histories have no common ancestor or a git error
    occurred (check error_details).
    """

    sha: str | None
    found: bool
    error_details: GitErrorDetails | None = None


@dataclass(frozen=True, slots=True)
class DiffResult:
    """Result of running git diff between two commits.

    is_empty is True when there are no differences.  git_error
    is True only when the git command itself failed (non-zero exit code).
    These two states are always distinct.
    """

    changed_files: tuple[str, ...] = ()
    diff_raw: str | None = None
    is_empty: bool = True
    git_error: bool = False
    error_details: GitErrorDetails | None = None


@dataclass(frozen=True, slots=True)
class DiffContext:
    """Complete differential comparison result.

    This is the primary output type.  Consumers should always check
    git_error first, then is_empty_diff, before accessing
    changed_files or diff_raw.
    """

    schema_version: Literal["1"] = "1"
    mode: DiffMode = "local"

    base_tip: str | None = None
    event_head: str | None = None
    merge_base: str | None = None
    tested_sha: str | None = None

    zero_before: bool = False
    empty_tree_hash: str | None = None

    git_error: bool = False
    git_error_details: GitErrorDetails | None = None

    is_empty_diff: bool = True
    changed_files: tuple[str, ...] = ()
    diff_raw: str | None = None

    local_head: str | None = None
    local_dirty: bool = False


def _is_zero_before(sha: str) -> bool:
    if not sha or len(sha) < _MIN_SHA_LENGTH:
        return False
    return sha == ZERO_BEFORE_SHA


def _run_git(
    args: list[str],
    cwd: Path | None = None,
    timeout_s: float = 30.0,
) -> tuple[int, str, str]:
    if not _git_args_are_safe(args):
        return (-1, "", "git arguments rejected by policy")
    cmd = ["git", *args]
    logger.debug("Running: %s", " ".join(cmd))
    try:
        proc = subprocess.run(  # nosec B603  # owner: quality-infrastructure; reason: git argv is structurally delimited and shell execution is disabled
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return (-1, "", "git executable not found")
    except subprocess.TimeoutExpired:
        return (-2, "", f"git command timed out after {timeout_s}s")
    except OSError as exc:
        return (-3, "", f"git command failed: {exc}")


def _git_args_are_safe(args: list[str]) -> bool:
    """Allow only required git commands and reject execution-capable options."""
    if not args:
        return True
    if args[0] not in _ALLOWED_GIT_COMMANDS:
        return False
    return not any(
        argument in _FORBIDDEN_GIT_OPTIONS
        or any(character in argument for character in ("\x00", "\n", "\r"))
        for argument in args
    )


def compute_merge_base(
    base_tip: str,
    head: str,
    cwd: Path | None = None,
) -> MergeBase:
    returncode, stdout, stderr = _run_git(["merge-base", "--", base_tip, head], cwd=cwd)
    if returncode != 0:
        details = GitErrorDetails(
            command=f"merge-base {base_tip} {head}",
            returncode=returncode,
            stderr=stderr,
        )
        logger.warning(
            "merge-base failed for %s..%s: returncode=%s stderr=%s",
            base_tip,
            head,
            returncode,
            stderr,
        )
        return MergeBase(sha=None, found=False, error_details=details)
    sha = stdout
    if not sha:
        return MergeBase(sha=None, found=False)
    return MergeBase(sha=sha, found=True)


def _files_from_empty_tree(to_sha: str, cwd: Path | None = None) -> DiffResult:
    if not _is_safe_revision(to_sha):
        return DiffResult(
            git_error=True,
            error_details=GitErrorDetails("log --name-only " + to_sha, -1, "invalid revision"),
        )
    returncode, stdout, stderr = _run_git(["log", "--name-only", "--format=", to_sha], cwd=cwd)
    if returncode != 0:
        return DiffResult(
            is_empty=True,
            git_error=True,
            error_details=GitErrorDetails("log --name-only " + to_sha, returncode, stderr),
        )
    if not stdout:
        return DiffResult(is_empty=True)
    changed = tuple(line.strip() for line in stdout.splitlines() if line.strip())
    return DiffResult(changed_files=changed, is_empty=not changed)


def _is_safe_revision(revision: str) -> bool:
    """Reject option-like or control-character-bearing git revisions."""
    return (
        bool(revision)
        and not revision.startswith("-")
        and not any(character in revision for character in ("\x00", "\n", "\r"))
    )


def compute_diff(
    from_sha: str,
    to_sha: str,
    cwd: Path | None = None,
) -> DiffResult:
    if from_sha == EMPTY_TREE_HASH:
        return _files_from_empty_tree(to_sha, cwd=cwd)
    returncode, stdout, stderr = _run_git(
        ["diff", "--name-only", f"{from_sha}...{to_sha}", "--"], cwd=cwd
    )
    if returncode != 0:
        return DiffResult(
            is_empty=True,
            git_error=True,
            error_details=GitErrorDetails(
                command=f"diff --name-only {from_sha}...{to_sha}",
                returncode=returncode,
                stderr=stderr,
            ),
        )
    if not stdout:
        return DiffResult(is_empty=True)
    changed = tuple(line.strip() for line in stdout.split("\n") if line.strip())
    return DiffResult(changed_files=changed, is_empty=not changed)


def compute_full_diff(
    from_sha: str,
    to_sha: str,
    cwd: Path | None = None,
) -> DiffResult:
    if from_sha == EMPTY_TREE_HASH:
        return _files_from_empty_tree(to_sha, cwd=cwd)
    returncode, stdout, stderr = _run_git(["diff", f"{from_sha}...{to_sha}", "--"], cwd=cwd)
    if returncode != 0:
        return DiffResult(
            is_empty=True,
            git_error=True,
            error_details=GitErrorDetails(
                command=f"diff {from_sha}...{to_sha}",
                returncode=returncode,
                stderr=stderr,
            ),
        )
    if not stdout:
        return DiffResult(is_empty=True, diff_raw="")
    return DiffResult(changed_files=(), diff_raw=stdout, is_empty=False)


def compute_pr_context(
    base_tip: str,
    event_head: str,
    cwd: Path | None = None,
) -> DiffContext:
    merge_base = compute_merge_base(base_tip, event_head, cwd=cwd)
    if not merge_base.found:
        return DiffContext(
            mode="pr",
            base_tip=base_tip,
            event_head=event_head,
            git_error=merge_base.error_details is not None,
            git_error_details=merge_base.error_details,
            is_empty_diff=True,
        )
    mb_sha = merge_base.sha
    if mb_sha is None:
        return DiffContext(
            mode="pr",
            base_tip=base_tip,
            event_head=event_head,
            merge_base=merge_base.sha,
            is_empty_diff=True,
        )
    diff_result = compute_diff(mb_sha, event_head, cwd=cwd)
    if diff_result.git_error:
        return DiffContext(
            mode="pr",
            base_tip=base_tip,
            event_head=event_head,
            merge_base=merge_base.sha,
            git_error=True,
            git_error_details=diff_result.error_details,
            is_empty_diff=True,
        )
    return DiffContext(
        mode="pr",
        base_tip=base_tip,
        event_head=event_head,
        merge_base=merge_base.sha,
        is_empty_diff=diff_result.is_empty,
        changed_files=diff_result.changed_files,
    )


def _push_zero_before_context(
    base_tip: str,
    before_sha: str,
    after_sha: str,
    cwd: Path | None,
) -> DiffContext | None:
    """Build the DiffContext for a push when *before_sha* is the zero SHA.

    Returns None when *before_sha* is not the zero SHA, signalling the
    caller should fall back to the merge-base logic.
    """
    if not _is_zero_before(before_sha):
        return None
    diff_result = compute_diff(EMPTY_TREE_HASH, after_sha, cwd=cwd)
    if diff_result.git_error:
        return DiffContext(
            mode="push",
            base_tip=base_tip,
            event_head=after_sha,
            merge_base=EMPTY_TREE_HASH,
            zero_before=True,
            empty_tree_hash=EMPTY_TREE_HASH,
            git_error=True,
            git_error_details=diff_result.error_details,
            is_empty_diff=True,
        )
    return DiffContext(
        mode="push",
        base_tip=base_tip,
        event_head=after_sha,
        merge_base=EMPTY_TREE_HASH,
        zero_before=True,
        empty_tree_hash=EMPTY_TREE_HASH,
        is_empty_diff=diff_result.is_empty,
        changed_files=diff_result.changed_files,
    )


def compute_push_context(
    base_tip: str,
    before_sha: str,
    after_sha: str,
    cwd: Path | None = None,
) -> DiffContext:
    zero_ctx = _push_zero_before_context(base_tip, before_sha, after_sha, cwd)
    if zero_ctx is not None:
        return zero_ctx
    merge_base = compute_merge_base(before_sha, after_sha, cwd=cwd)
    if not merge_base.found:
        return DiffContext(
            mode="push",
            base_tip=base_tip,
            event_head=after_sha,
            git_error=merge_base.error_details is not None,
            git_error_details=merge_base.error_details,
            is_empty_diff=True,
        )
    mb_sha = merge_base.sha
    if mb_sha is None:
        return DiffContext(
            mode="push",
            base_tip=base_tip,
            event_head=after_sha,
            merge_base=merge_base.sha,
            is_empty_diff=True,
        )
    diff_result = compute_diff(mb_sha, after_sha, cwd=cwd)
    if diff_result.git_error:
        return DiffContext(
            mode="push",
            base_tip=base_tip,
            event_head=after_sha,
            merge_base=merge_base.sha,
            git_error=True,
            git_error_details=diff_result.error_details,
            is_empty_diff=True,
        )
    return DiffContext(
        mode="push",
        base_tip=base_tip,
        event_head=after_sha,
        merge_base=merge_base.sha,
        is_empty_diff=diff_result.is_empty,
        changed_files=diff_result.changed_files,
    )


def compute_local_context(
    cwd: Path | None = None,
) -> DiffContext:
    head_sha = _resolve_head_sha(cwd=cwd)
    dirty = _is_worktree_dirty(cwd=cwd)
    if head_sha is None:
        return DiffContext(
            mode="local",
            git_error=True,
            git_error_details=GitErrorDetails(
                command="rev-parse HEAD",
                returncode=-1,
                stderr="Could not resolve HEAD",
            ),
            local_dirty=dirty,
        )
    if dirty:
        return DiffContext(
            mode="local",
            local_head=head_sha,
            local_dirty=True,
            is_empty_diff=False,
        )
    return DiffContext(
        mode="local",
        local_head=head_sha,
        local_dirty=False,
        is_empty_diff=True,
    )


def compute_dispatch_context(
    base_tip: str,
    event_head: str,
    cwd: Path | None = None,
) -> DiffContext:
    ctx = compute_pr_context(base_tip, event_head, cwd=cwd)
    return DiffContext(
        schema_version=ctx.schema_version,
        mode="dispatch",
        base_tip=ctx.base_tip,
        event_head=ctx.event_head,
        merge_base=ctx.merge_base,
        git_error=ctx.git_error,
        git_error_details=ctx.git_error_details,
        is_empty_diff=ctx.is_empty_diff,
        changed_files=ctx.changed_files,
    )


def _ci_zero_before_context(
    base_sha: str,
    tested_sha: str,
    cwd: Path | None,
) -> DiffContext | None:
    """Build the DiffContext for CI when *base_sha* is the zero SHA.

    Returns None when *base_sha* is not the zero SHA, signalling the
    caller should fall back to the merge-base logic.
    """
    if not _is_zero_before(base_sha):
        return None
    diff_result = compute_diff(EMPTY_TREE_HASH, tested_sha, cwd=cwd)
    if diff_result.git_error:
        return DiffContext(
            mode="ci",
            base_tip=base_sha,
            event_head=tested_sha,
            tested_sha=tested_sha,
            merge_base=EMPTY_TREE_HASH,
            zero_before=True,
            empty_tree_hash=EMPTY_TREE_HASH,
            git_error=True,
            git_error_details=diff_result.error_details,
            is_empty_diff=True,
        )
    return DiffContext(
        mode="ci",
        base_tip=base_sha,
        event_head=tested_sha,
        tested_sha=tested_sha,
        merge_base=EMPTY_TREE_HASH,
        zero_before=True,
        empty_tree_hash=EMPTY_TREE_HASH,
        is_empty_diff=diff_result.is_empty,
        changed_files=diff_result.changed_files,
    )


def compute_ci_context(
    base_sha: str,
    tested_sha: str,
    cwd: Path | None = None,
) -> DiffContext:
    zero_ctx = _ci_zero_before_context(base_sha, tested_sha, cwd)
    if zero_ctx is not None:
        return zero_ctx
    merge_base = compute_merge_base(base_sha, tested_sha, cwd=cwd)
    if not merge_base.found:
        return DiffContext(
            mode="ci",
            base_tip=base_sha,
            event_head=tested_sha,
            tested_sha=tested_sha,
            git_error=merge_base.error_details is not None,
            git_error_details=merge_base.error_details,
            is_empty_diff=True,
        )
    mb_sha = merge_base.sha
    if mb_sha is None:
        return DiffContext(
            mode="ci",
            base_tip=base_sha,
            event_head=tested_sha,
            tested_sha=tested_sha,
            is_empty_diff=True,
        )
    diff_result = compute_diff(mb_sha, tested_sha, cwd=cwd)
    if diff_result.git_error:
        return DiffContext(
            mode="ci",
            base_tip=base_sha,
            event_head=tested_sha,
            tested_sha=tested_sha,
            merge_base=merge_base.sha,
            git_error=True,
            git_error_details=diff_result.error_details,
            is_empty_diff=True,
        )
    return DiffContext(
        mode="ci",
        base_tip=base_sha,
        event_head=tested_sha,
        tested_sha=tested_sha,
        merge_base=merge_base.sha,
        is_empty_diff=diff_result.is_empty,
        changed_files=diff_result.changed_files,
    )


def _resolve_head_sha(cwd: Path | None = None) -> str | None:
    returncode, stdout, stderr = _run_git(["rev-parse", "HEAD"], cwd=cwd)
    if returncode != 0:
        logger.warning(
            "rev-parse HEAD failed: returncode=%s stderr=%s",
            returncode,
            stderr,
        )
        return None
    return stdout if stdout else None


def _is_worktree_dirty(cwd: Path | None = None) -> bool:
    returncode, _stdout, stderr = _run_git(["diff-index", "--quiet", "HEAD"], cwd=cwd)
    if returncode == 0:
        return False
    if returncode == 1:
        return True
    logger.warning(
        "diff-index --quiet HEAD failed: returncode=%s stderr=%s",
        returncode,
        stderr,
    )
    return True
