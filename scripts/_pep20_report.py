"""Deterministic Markdown and JSON rendering for the PEP 20 adherence analyser.

Owns the ``Report`` dataclass that bundles every analyser output (verdicts,
findings, rubric prose, unscoped files and repo-level aggregates) into a single
immutable object, plus the two pure renderers ``render_markdown`` and
``render_json``.

Both renderers are deterministic: they iterate ``AphorismId`` in ascending
order and sort findings by ``(path, line, code)`` so identical inputs always
produce identical output.  The three rubric-only aphorisms (9, 14 and 16) are
never mechanically assessed; their verdict is always ``Not-assessable`` and
their human-written prose is emitted verbatim from the ``rubrics`` mapping.

This module imports only from ``scripts._pep20_types``; it must never import
from the other ``_pep20_*`` modules, preserving the G1 build invariant.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))
from scripts._pep20_types import (
    APHORISMS,
    NON_MECHANICAL,
    AggregateSignals,
    AphorismId,
    Finding,
    Verdict,
)

_VERDICT_KEYS = {
    Verdict.STRONG: "strong",
    Verdict.MODERATE: "moderate",
    Verdict.WEAK: "weak",
    Verdict.NOT_ASSESSABLE: "not_assessable",
}


@dataclass(frozen=True, slots=True)
class Report:
    """Immutable bundle of every analyser output prepared for rendering."""

    target: str
    meta: dict[str, object]
    verdicts: dict[AphorismId, Verdict]
    findings: dict[AphorismId, list[Finding]]
    rubrics: dict[AphorismId, str]
    unscoped_files: list[str]
    aggregates: AggregateSignals | None


def build_report(  # noqa: PLR0913  # owner: quality-infrastructure; reason: keyword-only assembly context spanning the seven Report fields by design
    *,
    target: str,
    findings_by_aphorism: dict[AphorismId, list[Finding]],
    verdicts: dict[AphorismId, Verdict],
    aggregates: AggregateSignals | None,
    meta: dict[str, object],
    unscoped_files: list[str],
    rubrics: dict[AphorismId, str],
) -> Report:
    """Assemble a frozen Report from the analyser's raw outputs.

    All parameters are keyword-only so call sites stay explicit and the
    signature satisfies the repository four-argument rule.

    Args:
        target: Human-readable assessment target (repo or pull request name).
        findings_by_aphorism: Findings keyed by aphorism id.
        verdicts: Per-aphorism verdicts from the deterministic verdict rules.
        aggregates: Repo-level aggregate signals, or None when unavailable.
        meta: Free-form metadata about the assessment run.
        unscoped_files: Files whose added-line scope could not be computed.
        rubrics: Human-written prose for the three rubric-only aphorisms.

    Returns:
        An immutable Report ready for rendering.
    """
    return Report(
        target=target,
        meta=meta,
        verdicts=verdicts,
        findings=findings_by_aphorism,
        rubrics=rubrics,
        unscoped_files=unscoped_files,
        aggregates=aggregates,
    )


def _effective_verdict(report: Report, aphorism_id: AphorismId) -> Verdict:
    """Return an aphorism's verdict, forcing Not-assessable for rubric-only ones."""
    if aphorism_id in NON_MECHANICAL:
        return Verdict.NOT_ASSESSABLE
    return report.verdicts.get(aphorism_id, Verdict.NOT_ASSESSABLE)


def _summary_counts(report: Report) -> dict[str, int]:
    """Count verdicts across all nineteen aphorisms."""
    counts = {"strong": 0, "moderate": 0, "weak": 0, "not_assessable": 0}
    for aphorism_id in sorted(AphorismId):
        verdict = _effective_verdict(report, aphorism_id)
        counts[_VERDICT_KEYS[verdict]] += 1
    return counts


def _finding_sort_key(finding: Finding) -> tuple[str, int, str]:
    """Stable sort key for findings: path, then line, then code."""
    return (finding.path, finding.line, finding.code)


def _finding_location(finding: Finding) -> str:
    """Render a finding's location, spanning end_line when it differs."""
    if finding.end_line != finding.line:
        return f"{finding.path}:{finding.line}-{finding.end_line}"
    return f"{finding.path}:{finding.line}"


def _summary_row(report: Report, aphorism_id: AphorismId) -> str:
    """Render one summary table row for an aphorism."""
    verdict = _effective_verdict(report, aphorism_id)
    verdict_text = f"{verdict.value} (rubric)" if aphorism_id in NON_MECHANICAL else verdict.value
    finding_count = (
        0 if aphorism_id in NON_MECHANICAL else len(report.findings.get(aphorism_id, []))
    )
    return f"| {int(aphorism_id)} | {APHORISMS[aphorism_id]} | {verdict_text} | {finding_count} |"


def _summary_table(report: Report) -> list[str]:
    """Build the summary table header, separator and one row per aphorism."""
    rows = ["| # | Aphorism | Verdict | Findings |", "|---|----------|---------|----------|"]
    rows.extend(_summary_row(report, aphorism_id) for aphorism_id in sorted(AphorismId))
    return rows


def _overall_line(counts: dict[str, int]) -> str:
    """Render the overall verdict tally, e.g. 'Overall: 12 Strong, ...'."""
    parts = [f"{counts[_VERDICT_KEYS[verdict]]} {verdict.value}" for verdict in Verdict]
    return "Overall: " + ", ".join(parts)


def _finding_lines(report: Report, aphorism_id: AphorismId) -> list[str]:
    """Render the finding bullets for an aphorism, or a single '- no findings'."""
    findings = report.findings.get(aphorism_id, [])
    if not findings:
        return ["- no findings"]
    lines: list[str] = []
    for finding in sorted(findings, key=_finding_sort_key):
        lines.append(f"- {_finding_location(finding)} [{finding.code}] {finding.message}")
    return lines


def _aphorism_sections(report: Report) -> str:
    """Build per-aphorism finding sections for the mechanical aphorisms."""
    blocks: list[str] = []
    for aphorism_id in sorted(AphorismId):
        if aphorism_id in NON_MECHANICAL:
            continue
        heading = (
            f"### {int(aphorism_id)}. {APHORISMS[aphorism_id]} — "
            f"{_effective_verdict(report, aphorism_id).value}"
        )
        lines = [heading]
        lines.extend(_finding_lines(report, aphorism_id))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _rubric_section(report: Report) -> str:
    """Build the rubric-only aphorisms section with their human prose."""
    lines: list[str] = ["### Rubric-only aphorisms"]
    for aphorism_id in sorted(NON_MECHANICAL):
        prose = report.rubrics.get(aphorism_id, "")
        lines.append(f"- **{int(aphorism_id)}. {APHORISMS[aphorism_id]}** — {prose}")
    return "\n".join(lines)


def _unscoped_section(report: Report) -> str:
    """Build the unscoped-files warning section."""
    lines = ["### Unscoped files"]
    for path in report.unscoped_files:
        lines.append(
            f"- {path}: line-scope unavailable (large diff); findings not attributed to added lines"
        )
    return "\n".join(lines)


def _title(target: str) -> str:
    """Render the document title, tolerating an empty target string."""
    if not target:
        return "# PEP 20 Assessment"
    return f"# PEP 20 Assessment — {target}"


def render_markdown(report: Report) -> str:
    """Render the assessment as deterministic GitHub-flavoured Markdown.

    Args:
        report: The assembled assessment report.

    Returns:
        Markdown text with a summary table, overall tally, per-aphorism
        finding sections and any rubric or unscoped-file sections.
    """
    counts = _summary_counts(report)
    parts = [
        _title(report.target),
        "",
        "\n".join(_summary_table(report)),
        "",
        _overall_line(counts),
        "",
        _aphorism_sections(report),
    ]
    if report.rubrics:
        parts.extend(["", _rubric_section(report)])
    if report.unscoped_files:
        parts.extend(["", _unscoped_section(report)])
    return "\n".join(parts)


def _serialise_aggregates(aggregates: AggregateSignals | None) -> dict[str, object] | None:
    """Convert aggregate signals to a JSON-serialisable dict, or None."""
    if aggregates is None:
        return None
    return asdict(aggregates)


def _serialise_findings(report: Report, aphorism_id: AphorismId) -> list[dict[str, object]]:
    """Serialise a mechanical aphorism's findings for JSON output."""
    if aphorism_id in NON_MECHANICAL:
        return []
    findings = report.findings.get(aphorism_id, [])
    rows: list[dict[str, object]] = []
    for finding in sorted(findings, key=_finding_sort_key):
        rows.append(
            {
                "code": finding.code,
                "severity": finding.severity.value,
                "path": finding.path,
                "line": finding.line,
                "end_line": finding.end_line,
                "message": finding.message,
            }
        )
    return rows


def _aphorism_entry(report: Report, aphorism_id: AphorismId) -> dict[str, object]:
    """Build the JSON object describing a single aphorism."""
    is_mechanical = aphorism_id not in NON_MECHANICAL
    rubric = None if is_mechanical else report.rubrics.get(aphorism_id)
    return {
        "id": int(aphorism_id),
        "title": APHORISMS[aphorism_id],
        "verdict": _effective_verdict(report, aphorism_id).value,
        "assessable": is_mechanical,
        "findings": _serialise_findings(report, aphorism_id),
        "rubric": rubric,
    }


def render_json(report: Report) -> str:
    """Render the assessment as a deterministic, alphabetically sorted JSON document.

    Args:
        report: The assembled assessment report.

    Returns:
        Pretty-printed JSON text with keys sorted for reproducibility.
    """
    payload = {
        "meta": report.meta,
        "target": report.target,
        "summary": _summary_counts(report),
        "unscoped_files": report.unscoped_files,
        "aggregates": _serialise_aggregates(report.aggregates),
        "aphorisms": [_aphorism_entry(report, aphorism_id) for aphorism_id in sorted(AphorismId)],
    }
    return json.dumps(payload, sort_keys=True, indent=2)
