"""PEP 20 adherence analyser CLI.

Assesses a Python repository (or a GitHub pull request via the read-only
``gh`` API) against the nineteen Zen of Python aphorisms and emits a
deterministic Markdown or JSON report.

Usage::

    uv run python scripts/check_pep20.py [--root PATH]
    uv run python scripts/check_pep20.py --pr N [--repo OWNER/REPO]
    uv run python scripts/check_pep20.py --pr N --repo OWNER/REPO --post-comment

Exit codes: 0 = success, 2 = usage or tool error.  The report is advisory:
findings never change the exit code.

PR mode is read-only by default; ``--post-comment`` is an explicit opt-in that
POSTs the Markdown report as a review comment on the pull request.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts._pep20_detectors import (
    DETECTORS,
    RUBRICS,
    aggregate_signals,
    verdict_for,
)
from scripts._pep20_metrics import collect_module_signals
from scripts._pep20_report import Report, build_report, render_json, render_markdown
from scripts._pep20_scoping import (
    GhClient,
    GhError,
    added_line_ranges,
    in_pr,
    parse_diff_hunks,
)
from scripts._pep20_types import (
    AggregateSignals,
    AphorismId,
    DiffEntry,
    Finding,
    ModuleSignals,
    Severity,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESCRIPTION = "Assess a Python repository or pull request for PEP 20 adherence."
_REPO_URL_RE = re.compile(r"(?:github\.com[:/])([^/]+)/([^/.]+?)(?:\.git)?$")


def _parse_args() -> argparse.Namespace:
    """Parse the command line into a Namespace."""
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument(
        "--root", default="src", help="Directory to walk in repo mode (default: src)."
    )
    parser.add_argument("--pr", type=int, default=None, help="Pull request number to assess.")
    parser.add_argument(
        "--repo", default=None, help="OWNER/REPO for --pr mode (default: from git config)."
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit a JSON report instead of Markdown."
    )
    parser.add_argument(
        "--output", default=None, help="Write the report to this path instead of stdout."
    )
    parser.add_argument(
        "--post-comment",
        action="store_true",
        help="POST the Markdown report as a review comment (opt-in, --pr only).",
    )
    return parser.parse_args()


def _merge_findings(
    findings_by_aphorism: dict[AphorismId, list[Finding]],
    findings: list[Finding],
) -> None:
    """Append each finding under its aphorism key."""
    for finding in findings:
        findings_by_aphorism.setdefault(finding.aphorism, []).append(finding)


def _detect_module(module: ModuleSignals) -> list[Finding]:
    """Run every detector over one module, reporting parse errors first."""
    if module.parse_error is not None:
        return [
            Finding(
                aphorism=AphorismId.READABILITY,
                severity=Severity.WARNING,
                code="parse-error",
                path=module.module_path,
                line=1,
                end_line=1,
                message=f"module failed to parse: {module.parse_error}",
            )
        ]
    findings: list[Finding] = []
    for aphorism_id in sorted(AphorismId):
        findings.extend(DETECTORS[aphorism_id](module))
    return findings


def _assess_modules(
    modules: list[ModuleSignals],
) -> tuple[dict[AphorismId, list[Finding]], AggregateSignals]:
    """Run all detectors and fold the aggregate signals for a repo."""
    findings_by_aphorism: dict[AphorismId, list[Finding]] = {}
    for module in modules:
        _merge_findings(findings_by_aphorism, _detect_module(module))
    aggregates = aggregate_signals(modules)
    return findings_by_aphorism, aggregates


def _collect_module_files(root: Path) -> list[ModuleSignals]:
    """Walk a directory tree and extract signals from every Python file."""
    modules: list[ModuleSignals] = []
    for path in sorted(root.rglob("*.py")):
        rel_path = str(path.relative_to(root))
        try:
            source = path.read_text()
        except OSError as exc:
            modules.append(ModuleSignals(module_path=rel_path, parse_error=f"unreadable: {exc}"))
            continue
        modules.append(collect_module_signals(source, rel_path))
    return modules


def _file_should_analyse(entry: DiffEntry) -> bool:
    """True when a PR file is Python and carries assessable content."""
    return (
        entry.filename.endswith(".py")
        and entry.status not in ("removed", "unchanged")
        and not (entry.status == "renamed" and entry.patch is None)
    )


def _eligible_files(files: list[DiffEntry]) -> list[DiffEntry]:
    """Filter PR files down to those the analyser should assess."""
    return [entry for entry in files if _file_should_analyse(entry)]


def _scope_findings(findings: list[Finding], ranges: list[tuple[int, int]]) -> list[Finding]:
    """Keep only findings whose statement span intersects an added range."""
    return [finding for finding in findings if in_pr((finding.line, finding.end_line), ranges)]


def _pr_file_result(
    gh: GhClient, repo: str, number: int, entry: DiffEntry
) -> tuple[ModuleSignals | None, list[Finding], bool]:
    """Analyse one PR file, scoping findings to its added lines.

    Returns:
        A tuple of (signals, findings, is_scoped).  Signals is None when the
        head file could not be fetched; is_scoped is False when the API
        supplied no patch so line attribution is unavailable.
    """
    try:
        source = gh.fetch_head_file(repo, number, entry.filename, entry.head_sha)
    except GhError:
        return None, [], False
    module = collect_module_signals(source, entry.filename)
    findings = _detect_module(module)
    if entry.patch is None:
        return module, findings, False
    ranges = added_line_ranges(parse_diff_hunks(entry.patch))
    return module, _scope_findings(findings, ranges), True


def _pr_files_to_signals(
    gh: GhClient, repo: str, number: int, files: list[DiffEntry]
) -> tuple[dict[AphorismId, list[Finding]], list[str], list[ModuleSignals]]:
    """Assess every eligible PR file and merge the scoped findings.

    Returns:
        A tuple of (findings by aphorism, unscoped file paths, module signals).
    """
    findings_by_aphorism: dict[AphorismId, list[Finding]] = {}
    unscoped: list[str] = []
    modules: list[ModuleSignals] = []
    for entry in _eligible_files(files):
        module, file_findings, is_scoped = _pr_file_result(gh, repo, number, entry)
        if module is None:
            unscoped.append(entry.filename)
            continue
        modules.append(module)
        _merge_findings(findings_by_aphorism, file_findings)
        if not is_scoped:
            unscoped.append(entry.filename)
    return findings_by_aphorism, unscoped, modules


def _assess_pr(
    gh: GhClient, repo: str, number: int
) -> tuple[str, dict[AphorismId, list[Finding]], AggregateSignals, list[str]]:
    """Fetch a PR's Python files and assess them line-scoped to the diff."""
    files = gh.pr_files(repo, number)
    findings_by_aphorism, unscoped, modules = _pr_files_to_signals(gh, repo, number, files)
    aggregates = aggregate_signals(modules)
    return f"{repo}#{number}", findings_by_aphorism, aggregates, unscoped


def _build_report(
    target: str,
    findings_by_aphorism: dict[AphorismId, list[Finding]],
    aggregates: AggregateSignals,
    unscoped: list[str],
) -> Report:
    """Compute verdicts and assemble the immutable Report."""
    verdicts = {
        aphorism_id: verdict_for(aphorism_id, findings_by_aphorism.get(aphorism_id, []), aggregates)
        for aphorism_id in AphorismId
    }
    return build_report(
        target=target,
        findings_by_aphorism=findings_by_aphorism,
        verdicts=verdicts,
        aggregates=aggregates,
        meta={"tool": "check_pep20"},
        unscoped_files=unscoped,
        rubrics=RUBRICS,
    )


def _render_and_emit(report: Report, args: argparse.Namespace) -> int:
    """Render the report and print it to stdout or write it to a path."""
    text = render_json(report) if args.json else render_markdown(report)
    if args.output:
        Path(args.output).write_text(text)
    else:
        print(text)
    return 0


def _is_origin_section(line: str) -> bool:
    """True when a git config line opens the origin remote section."""
    stripped = line.strip()
    return stripped.startswith("[") and "origin" in stripped


def _has_next(lines: list[str], index: int) -> bool:
    """True when a line index has a following line."""
    return index + 1 < len(lines)


def _origin_url(line: str) -> str | None:
    """Extract the url value from a git config line."""
    stripped = line.strip()
    if stripped.startswith("url"):
        return stripped.split("=", 1)[1].strip()
    return None


def _origin_url_after(lines: list[str], index: int, line: str) -> str | None:
    """Return the origin URL when *line* opens its section, else None."""
    if not _is_origin_section(line):
        return None
    if not _has_next(lines, index):
        return None
    return _origin_url(lines[index + 1])


def _remote_url(config_path: Path) -> str | None:
    """Return the origin remote URL from a git config file, or None."""
    if not config_path.exists():
        return None
    lines = config_path.read_text().splitlines()
    for index, line in enumerate(lines):
        url = _origin_url_after(lines, index, line)
        if url is not None:
            return url
    return None


def _repo_from_url(url: str) -> str | None:
    """Extract an OWNER/REPO pair from a GitHub remote URL."""
    match = _REPO_URL_RE.search(url.strip())
    if match is None:
        return None
    return f"{match.group(1)}/{match.group(2)}"


def _default_repo() -> str | None:
    """Derive OWNER/REPO from the local git origin remote."""
    url = _remote_url(PROJECT_ROOT / ".git" / "config")
    if url is None:
        return None
    return _repo_from_url(url)


def _resolve_repo(args: argparse.Namespace) -> str | None:
    """Return the --repo value, falling back to the git origin remote."""
    if args.repo is not None:
        return args.repo
    return _default_repo()


def _print_gh_error(exc: GhError) -> None:
    """Print a GhError message and any captured stderr."""
    print(f"error: {exc.message}", file=sys.stderr)
    if exc.stderr:
        print(exc.stderr, file=sys.stderr)


def _try_post_comment(gh: GhClient, repo: str, number: int, report: Report) -> None:
    """POST the report as a review comment, logging a warning on failure."""
    try:
        gh.post_comment(repo, number, render_markdown(report))
    except GhError as exc:
        print(f"warning: failed to post comment: {exc.message}", file=sys.stderr)


def _run_repo_mode(args: argparse.Namespace) -> int:
    """Assess a local repository tree and emit the report."""
    root = Path(args.root)
    if not root.is_dir():
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 2
    modules = _collect_module_files(root)
    findings_by_aphorism, aggregates = _assess_modules(modules)
    report = _build_report(str(root), findings_by_aphorism, aggregates, [])
    return _render_and_emit(report, args)


def _run_pr_mode(args: argparse.Namespace) -> int:
    """Assess a pull request via the read-only gh API and emit the report."""
    repo = _resolve_repo(args)
    if repo is None:
        print(
            "error: cannot determine repository owner/name; pass --repo OWNER/REPO",
            file=sys.stderr,
        )
        return 2
    gh = GhClient()
    try:
        target, findings_by_aphorism, aggregates, unscoped = _assess_pr(gh, repo, args.pr)
    except GhError as exc:
        _print_gh_error(exc)
        return 2
    report = _build_report(target, findings_by_aphorism, aggregates, unscoped)
    if args.post_comment:
        _try_post_comment(gh, repo, args.pr, report)
    return _render_and_emit(report, args)


def main() -> None:
    """Parse arguments and dispatch to repo or PR mode."""
    args = _parse_args()
    if args.pr is not None:
        exit_code = _run_pr_mode(args)
    else:
        exit_code = _run_repo_mode(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
