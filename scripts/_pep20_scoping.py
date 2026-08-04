"""Diff-hunk parsing, PR line-scoping and the read-only ``gh`` client.

This module owns the *scoping* half of the PEP 20 adherence analyser:
turning a unified diff patch into added-line ranges, deciding whether a
statement span falls inside a pull request, and wrapping the ``gh`` CLI in a
typed, injectable read-only client.

The module imports only from ``scripts._pep20_types`` and never touches any
other ``_pep20_*`` module, preserving the G1 build invariant.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess  # nosec B404  # owner: quality-infrastructure; reason: deliberate gh API call, shell=False, argv not shell interpolation
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, TypeGuard

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts._pep20_types import DiffEntry, Hunk

__all__ = [
    "GhClient",
    "GhError",
    "added_line_ranges",
    "in_pr",
    "parse_diff_hunks",
]

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_REQUIRED_PR_KEYS = ("state", "baseSha", "headSha", "baseRef", "headRef")


def _split_hunks(patch_text: str) -> list[tuple[re.Match[str], list[str]]]:
    """Split a patch into (hunk header match, body lines) pairs.

    Lines before the first hunk header are discarded; every later non-header
    line is attributed to the most recent hunk.
    """
    sections: list[tuple[re.Match[str], list[str]]] = []
    for line in patch_text.splitlines():
        match = _HUNK_HEADER_RE.match(line)
        if match is not None:
            sections.append((match, []))
        elif sections:
            sections[-1][1].append(line)
    return sections


def parse_diff_hunks(patch_text: str) -> list[Hunk]:
    """Parse a unified diff patch into added-line ranges.

    Each hunk header ``@@ -a,b +c,d @@`` yields one Hunk whose start and
    length come from the header's new-side range; an omitted count means one.
    """
    hunks: list[Hunk] = []
    for match, body in _split_hunks(patch_text):
        start = int(match[3])
        length = int(match[4] or "1")
        del body
        hunks.append(Hunk(start_line=start, length=length))
    return hunks


def added_line_ranges(hunks: list[Hunk]) -> list[tuple[int, int]]:
    """Return inclusive added-line ranges ``(start, end)`` for each hunk."""
    return [(hunk.start_line, hunk.start_line + hunk.length - 1) for hunk in hunks]


def in_pr(span: tuple[int, int], ranges: list[tuple[int, int]]) -> bool:
    """Return True when the statement *span* overlaps any added-line range."""
    span_start, span_end = span
    return any(
        span_start <= range_end and range_start <= span_end for range_start, range_end in ranges
    )


def _is_object_dict(value: object) -> TypeGuard[dict[str, object]]:
    """Return whether a decoded JSON value is an object."""
    return isinstance(value, dict)


class GhError(RuntimeError):
    """Raised when the ``gh`` CLI exits non-zero or times out."""

    def __init__(self, message: str, stderr: str) -> None:
        """Initialise with a message and the captured stderr text."""
        super().__init__(message)
        self.message = message
        self.stderr = stderr


class GhClient:
    """Read-only GitHub client wrapping the ``gh`` CLI via subprocess."""

    def _run_gh(self, args: list[str], timeout: int = 60) -> str:
        """Run ``gh`` with *args*, returning stdout or raising GhError.

        Args:
            args: Full argument list after the ``gh`` executable.
            timeout: Maximum seconds to wait for the command to finish.

        Returns:
            The captured stdout on success.

        Raises:
            GhError: The command exited non-zero or exceeded *timeout*.
        """
        try:
            result = subprocess.run(  # nosec B603, B607  # owner: quality-infrastructure; reason: deliberate gh API call, shell=False, argv not shell interpolation
                ["gh", *args],
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            message = f"gh {args[0]} timed out after {timeout}s"
            stderr = str(exc.stderr or "")
            raise GhError(message, stderr) from exc
        if result.returncode != 0:
            message = f"gh {args[0]} exited {result.returncode}"
            raise GhError(message, result.stderr)
        return result.stdout

    def pr_meta(self, repo: str, number: int) -> dict[str, str]:
        """Return PR state, base/head SHA and ref metadata for *number*.

        Raises:
            GhError: The API call failed or the response is malformed.
        """
        url = f"repos/{repo}/pulls/{number}"
        query = (
            "{state, baseSha:.base.sha, headSha:.head.sha, baseRef:.base.ref, headRef:.head.ref}"
        )
        stdout = self._run_gh(["api", url, "--jq", query])
        return self._parse_pr_meta(stdout)

    def _parse_pr_meta(self, stdout: str) -> dict[str, str]:
        """Parse and validate the raw PR metadata JSON from *stdout*."""
        meta = self._decode_json(stdout)
        missing = [key for key in _REQUIRED_PR_KEYS if not isinstance(meta.get(key), str)]
        if missing:
            message = f"gh api PR metadata is missing: {', '.join(missing)}"
            raise GhError(message, stdout)
        return {key: str(meta[key]) for key in _REQUIRED_PR_KEYS}

    def _decode_json(self, stdout: str) -> dict[str, object]:
        """Decode *stdout* into a dictionary or raise GhError."""
        try:
            decoded: object = json.loads(stdout)
        except json.JSONDecodeError as exc:
            message = "gh api returned non-JSON PR metadata"
            raise GhError(message, stdout) from exc
        if not _is_object_dict(decoded):
            message = "gh api returned unexpected PR metadata shape"
            raise GhError(message, stdout)
        return decoded

    def pr_files(self, repo: str, number: int) -> list[DiffEntry]:
        """Return the changed-file entries for pull request *number*."""
        head_sha = self.pr_meta(repo, number)["headSha"]
        url = f"repos/{repo}/pulls/{number}/files?per_page=100"
        stdout = self._run_gh(["api", "--paginate", url, "--jq", ".[]"])
        return [
            self._to_diff_entry(json.loads(line), head_sha)
            for line in stdout.splitlines()
            if line.strip()
        ]

    def _to_diff_entry(self, entry: dict[str, Any], head_sha: str) -> DiffEntry:
        """Convert one GitHub file object into a DiffEntry record."""
        patch = entry.get("patch")
        previous_filename = entry.get("previous_filename")
        return DiffEntry(
            str(entry["filename"]),
            str(entry["status"]),
            previous_filename if isinstance(previous_filename, str) else None,
            int(entry["additions"]),
            int(entry["deletions"]),
            patch if isinstance(patch, str) else None,
            head_sha=head_sha,
        )

    def fetch_head_file(self, repo: str, number: int, path: str, head_sha: str) -> str:
        """Return the decoded text content of *path* at the PR head SHA.

        Raises:
            GhError: The API call failed or the content is not decodable.
        """
        url = f"repos/{repo}/contents/{path}?ref={head_sha}"
        stdout = self._run_gh(["api", url, "--jq", ".content"])
        try:
            return base64.b64decode(stdout, validate=False).decode("utf-8")
        except ValueError as exc:
            message = f"gh api returned non-decodable content for PR {number}"
            raise GhError(message, stdout) from exc

    def post_comment(self, repo: str, number: int, body: str) -> None:
        """POST a body as a review comment on pull request *number*.

        This endpoint is opt-in-only and is never exercised by the analyser.
        """
        url = f"repos/{repo}/pulls/{number}/comments"
        self._run_gh(["api", url, "-f", f"body={body}"])
