"""Nineteen aphorism detectors, verdict rules and rubrics for the PEP 20 analyser.

Detectors are thin pure functions that consume the pre-computed
``ModuleSignals`` contract from ``scripts._pep20_types`` and emit one
``Finding`` per piece of evidence, keyed by aphorism, severity and code.
Verdict rules fold findings and repo-wide aggregates into a deterministic
``Verdict``; the three human-judgement aphorisms (9, 14, 16) carry prose
rubrics instead of mechanical verdicts.

The complexity measure carried by ``FunctionMetrics.cc`` includes ``try:``
blocks and therefore differs numerically from radon (the repository's
canonical ``make complexity`` gate).  Detectors never inspect the AST
directly: every signal they need is a pre-computed field on
``ModuleSignals``.  Aphorism 1 flags every undocumented function because
the current signal contract exposes no per-function name, so the public
(``not name.startswith("_")``) filter cannot be applied.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts._pep20_types import (
    AggregateSignals,
    AphorismId,
    DuplicateBlock,
    Finding,
    FunctionMetrics,
    ModuleSignals,
    Severity,
    Verdict,
)

SIMPLICITY_CC_LIMIT = 5
COMPLEXITY_CC_LIMIT = 8
NESTING_DEPTH_LIMIT = 3
EASY_ARG_COUNT_LIMIT = 4
EASY_RETURN_COUNT_LIMIT = 4
EASY_STATEMENT_COUNT_LIMIT = 30
SUPPRESSION_DENSITY_LIMIT = 5
STRONG_DOCSTRING_RATIO = 0.8
MODERATE_DOCSTRING_RATIO = 0.5
COMMENT_RATIO_FLOOR = 0.05
COMMENT_RATIO_CEILING = 0.4
STRONG_EASY_RATIO = 0.8
MODERATE_EASY_RATIO_FLOOR = 0.6
ADVISORY_STRONG_MAX = 2
ADVISORY_MODERATE_MAX = 9
INIT_MODULE_NAME = "__init__.py"


@dataclass(frozen=True, slots=True)
class _LineSpec:
    """Fixed per-finding attributes shared by every line in one signal."""

    aphorism: AphorismId
    severity: Severity
    code: str
    message: str


_MISSING_DOCSTRING = _LineSpec(
    AphorismId.BEAUTIFUL, Severity.INFO, "missing-docstring", "function lacks a docstring"
)
_MISSING_MODULE_DOCSTRING = _LineSpec(
    AphorismId.BEAUTIFUL,
    Severity.INFO,
    "missing-module-docstring",
    "module lacks a docstring",
)
_WILDCARD_IMPORT = _LineSpec(
    AphorismId.EXPLICIT, Severity.INFO, "wildcard-import", "wildcard import"
)
_GLOBAL_STATEMENT = _LineSpec(
    AphorismId.EXPLICIT, Severity.INFO, "global-statement", "global statement"
)
_DYNAMIC_GETATTR = _LineSpec(
    AphorismId.EXPLICIT, Severity.INFO, "dynamic-getattr", "dynamic getattr"
)
_MAGIC_NUMBER = _LineSpec(
    AphorismId.EXPLICIT, Severity.INFO, "magic-number", "magic number in expression"
)
_FUNCTION_LEVEL_IMPORT = _LineSpec(
    AphorismId.EXPLICIT,
    Severity.INFO,
    "function-level-import",
    "import inside a function",
)
_EVAL_EXEC = _LineSpec(AphorismId.EXPLICIT, Severity.INFO, "eval-exec", "eval or exec used")
_COMPLEXITY = _LineSpec(AphorismId.SIMPLE, Severity.ERROR, "complexity", "function too complex")
_COMPLICATED = _LineSpec(
    AphorismId.COMPLEX, Severity.WARNING, "complicated", "function is complicated"
)
_NESTING = _LineSpec(AphorismId.FLAT, Severity.WARNING, "nesting", "function is too deeply nested")
_LINE_LENGTH = _LineSpec(AphorismId.SPARSE, Severity.INFO, "line-length", "line is too long")
_COMPOUND_STATEMENT = _LineSpec(
    AphorismId.SPARSE, Severity.INFO, "compound-statement", "compound statement"
)
_TAB_MIX = _LineSpec(AphorismId.SPARSE, Severity.INFO, "tab-mix", "mixed tabs and spaces")
_BROAD_EXCEPT = _LineSpec(
    AphorismId.SPECIAL_CASES, Severity.WARNING, "broad-except", "broad exception handler"
)
_SUPPRESSION_DENSITY = _LineSpec(
    AphorismId.SPECIAL_CASES,
    Severity.WARNING,
    "suppression-density",
    "high density of suppressions",
)
_SILENT_SWALLOW = _LineSpec(
    AphorismId.ERRORS_SILENT, Severity.ERROR, "silent-swallow", "exception swallowed silently"
)
_BARE_EXCEPT = _LineSpec(
    AphorismId.ERRORS_SILENT, Severity.ERROR, "bare-except", "bare except clause"
)
_UNMARKED_SILENCE = _LineSpec(
    AphorismId.EXPLICIT_SILENCED,
    Severity.WARNING,
    "unmarked-silence",
    "exception silenced without an explicit marker",
)
_GUESS_CONTINUE = _LineSpec(
    AphorismId.AMBIGUITY, Severity.WARNING, "guess-continue", "guessing continues on ambiguity"
)
_FALLBACK_CHAIN = _LineSpec(
    AphorismId.AMBIGUITY, Severity.WARNING, "fallback-chain", "guessing fallback chain"
)
_DUPLICATE_LOGIC = _LineSpec(
    AphorismId.ONE_WAY, Severity.INFO, "duplicate-logic", "duplicated logic"
)
_TODO = _LineSpec(AphorismId.NOW, Severity.INFO, "todo", "deferred work marker")
_STUB_FUNCTION = _LineSpec(AphorismId.NOW, Severity.INFO, "stub-function", "stub function")
_HARD_TO_EXPLAIN = _LineSpec(
    AphorismId.HARD_EXPLAIN,
    Severity.WARNING,
    "hard-to-explain",
    "function is hard to explain",
)
_MISSING_ALL = _LineSpec(
    AphorismId.NAMESPACES,
    Severity.WARNING,
    "missing-all",
    "init module does not declare __all__",
)


def _finding_for_spec(
    module: ModuleSignals,
    spec: _LineSpec,
    line: int,
    message: str | None = None,
) -> Finding:
    """Build a line-scoped finding, overriding the spec message when given."""
    return Finding(
        aphorism=spec.aphorism,
        severity=spec.severity,
        code=spec.code,
        path=module.module_path,
        line=line,
        end_line=line,
        message=spec.message if message is None else message,
    )


def _lines_to_findings(
    module: ModuleSignals,
    spec: _LineSpec,
    lines: tuple[int, ...],
) -> list[Finding]:
    """Map each *lines* entry onto one finding using the fixed spec message."""
    return [_finding_for_spec(module, spec, line) for line in lines]


def _is_easy(metrics: FunctionMetrics) -> bool:
    """True when a function satisfies the aphorism-18 'easy' rubric."""
    return (
        metrics.cc <= SIMPLICITY_CC_LIMIT
        and metrics.arg_count <= EASY_ARG_COUNT_LIMIT
        and metrics.return_count <= EASY_RETURN_COUNT_LIMIT
        and metrics.statement_count <= EASY_STATEMENT_COUNT_LIMIT
        and metrics.nesting_depth <= NESTING_DEPTH_LIMIT
    )


def _has_long_line_in_span(module: ModuleSignals, start: int, end: int) -> bool:
    """True when any long line falls within the inclusive [start, end] span."""
    return any(start <= line <= end for line, _length in module.long_lines)


def _is_hard_to_explain(module: ModuleSignals, metrics: FunctionMetrics) -> bool:
    """True when a function is complex, undocumented and hard to explain."""
    if metrics.cc <= SIMPLICITY_CC_LIMIT or metrics.has_docstring:
        return False
    if metrics.nesting_depth > 1:
        return True
    return _has_long_line_in_span(module, metrics.start_line, metrics.end_line)


def _format_line_range(block: DuplicateBlock) -> str:
    """Render a duplicate block's member lines as a comma-separated list."""
    return ", ".join(str(line) for line in block.lines)


def _detect_beautiful(module: ModuleSignals) -> list[Finding]:
    """Aphorism 1: flag undocumented functions and an undocumented module."""
    findings = [
        _finding_for_spec(module, _MISSING_DOCSTRING, metrics.start_line)
        for metrics in module.functions
        if not metrics.has_docstring
    ]
    if not module.module_has_docstring and not module.module_path.endswith(INIT_MODULE_NAME):
        findings.append(_finding_for_spec(module, _MISSING_MODULE_DOCSTRING, 1))
    return findings


def _detect_explicit(module: ModuleSignals) -> list[Finding]:
    """Aphorism 2: flag implicit constructs one finding per occurrence."""
    findings: list[Finding] = []
    findings.extend(_lines_to_findings(module, _WILDCARD_IMPORT, module.wildcard_import_lines))
    findings.extend(_lines_to_findings(module, _GLOBAL_STATEMENT, module.global_statement_lines))
    findings.extend(_lines_to_findings(module, _DYNAMIC_GETATTR, module.getattr_lines))
    findings.extend(
        _finding_for_spec(module, _MAGIC_NUMBER, line, f"magic number {value!r} in expression")
        for line, value in module.magic_numbers
    )
    findings.extend(
        _lines_to_findings(module, _FUNCTION_LEVEL_IMPORT, module.function_import_lines)
    )
    findings.extend(_lines_to_findings(module, _EVAL_EXEC, module.eval_exec_lines))
    return findings


def _detect_simple(module: ModuleSignals) -> list[Finding]:
    """Aphorism 3: flag functions whose complexity exceeds the limit."""
    return [
        _finding_for_spec(
            module,
            _COMPLEXITY,
            metrics.start_line,
            f"function has complexity {metrics.cc}",
        )
        for metrics in module.functions
        if metrics.cc > SIMPLICITY_CC_LIMIT
    ]


def _detect_complex(module: ModuleSignals) -> list[Finding]:
    """Aphorism 4: flag undocumented-complex or simply too-complex functions."""
    return [
        _finding_for_spec(
            module,
            _COMPLICATED,
            metrics.start_line,
            f"function is complicated with complexity {metrics.cc}",
        )
        for metrics in module.functions
        if (metrics.cc > SIMPLICITY_CC_LIMIT and not metrics.has_docstring)
        or metrics.cc > COMPLEXITY_CC_LIMIT
    ]


def _detect_flat(module: ModuleSignals) -> list[Finding]:
    """Aphorism 5: flag functions whose nesting depth exceeds the limit."""
    return [
        _finding_for_spec(
            module,
            _NESTING,
            metrics.start_line,
            f"function nesting depth is {metrics.nesting_depth}",
        )
        for metrics in module.functions
        if metrics.nesting_depth > NESTING_DEPTH_LIMIT
    ]


def _detect_sparse(module: ModuleSignals) -> list[Finding]:
    """Aphorism 6: flag overlong lines, compound statements and tab mixing."""
    findings = [
        _finding_for_spec(
            module,
            _LINE_LENGTH,
            line,
            f"line is {length} characters long",
        )
        for line, length in module.long_lines
    ]
    findings.extend(
        _lines_to_findings(module, _COMPOUND_STATEMENT, module.compound_statement_lines)
    )
    findings.extend(_lines_to_findings(module, _TAB_MIX, module.tab_mix_lines))
    return findings


def _detect_readability(_module: ModuleSignals) -> list[Finding]:
    """Aphorism 7 emits no per-item findings; the verdict derives from aggregates."""
    return []


def _detect_special_cases(module: ModuleSignals) -> list[Finding]:
    """Aphorism 8: flag broad handlers and a high density of suppressions."""
    findings = [
        _finding_for_spec(module, _BROAD_EXCEPT, metrics.line)
        for metrics in module.excepts
        if metrics.kind == "broad"
    ]
    suppression_count = module.noqa_count + module.type_ignore_count
    if suppression_count >= SUPPRESSION_DENSITY_LIMIT:
        findings.append(
            _finding_for_spec(
                module,
                _SUPPRESSION_DENSITY,
                1,
                f"module suppresses {suppression_count} diagnostics",
            )
        )
    return findings


def _detect_practicality(_module: ModuleSignals) -> list[Finding]:
    """Aphorism 9 is rubric-only; the analyser only inventories suppressions."""
    return []


def _detect_errors_silent(module: ModuleSignals) -> list[Finding]:
    """Aphorism 10: flag silently swallowed and bare exceptions."""
    findings = [
        _finding_for_spec(module, _SILENT_SWALLOW, metrics.line)
        for metrics in module.excepts
        if metrics.kind in {"pass", "silent"}
    ]
    findings.extend(
        _finding_for_spec(module, _BARE_EXCEPT, metrics.line)
        for metrics in module.excepts
        if metrics.kind == "bare"
    )
    return findings


def _detect_explicit_silenced(module: ModuleSignals) -> list[Finding]:
    """Aphorism 11: flag silences that carry no explicit marker."""
    return [
        _finding_for_spec(module, _UNMARKED_SILENCE, metrics.line)
        for metrics in module.excepts
        if metrics.kind in {"pass", "silent"}
    ]


def _detect_ambiguity(module: ModuleSignals) -> list[Finding]:
    """Aphorism 12: flag guessed continues and guessing fallback chains."""
    findings = _lines_to_findings(module, _GUESS_CONTINUE, module.guess_continue_lines)
    findings.extend(_lines_to_findings(module, _FALLBACK_CHAIN, module.fallback_chain_lines))
    return findings


def _detect_one_way(module: ModuleSignals) -> list[Finding]:
    """Aphorism 13: flag duplicated function bodies one block at a time."""
    findings: list[Finding] = []
    for block in module.duplicate_blocks:
        if not block.lines:
            continue
        findings.append(
            _finding_for_spec(
                module,
                _DUPLICATE_LOGIC,
                block.lines[0],
                f"duplicated function body spans lines {_format_line_range(block)}",
            )
        )
    return findings


def _detect_dutch(_module: ModuleSignals) -> list[Finding]:
    """Aphorism 14 is rubric-only; obviousness is a human judgement."""
    return []


def _detect_now(module: ModuleSignals) -> list[Finding]:
    """Aphorism 15: flag deferred-work markers and stub functions."""
    findings = _lines_to_findings(module, _TODO, module.todo_lines)
    findings.extend(_lines_to_findings(module, _STUB_FUNCTION, module.stub_function_lines))
    return findings


def _detect_never(_module: ModuleSignals) -> list[Finding]:
    """Aphorism 16 is rubric-only; temporality cannot be judged statically."""
    return []


def _detect_hard_explain(module: ModuleSignals) -> list[Finding]:
    """Aphorism 17: flag complex, undocumented, hard-to-explain functions."""
    findings: list[Finding] = []
    for metrics in module.functions:
        if not _is_hard_to_explain(module, metrics):
            continue
        findings.append(
            _finding_for_spec(
                module,
                _HARD_TO_EXPLAIN,
                metrics.start_line,
                f"function has complexity {metrics.cc} without a docstring",
            )
        )
    return findings


def _detect_easy_explain(_module: ModuleSignals) -> list[Finding]:
    """Aphorism 18 emits no per-item findings; the verdict derives from aggregates."""
    return []


def _detect_namespaces(module: ModuleSignals) -> list[Finding]:
    """Aphorism 19: flag non-empty init modules that omit ``__all__``."""
    if (
        not module.module_path.endswith(INIT_MODULE_NAME)
        or module.has_all_in_init
        or (not module.functions and module.code_line_count == 0)
    ):
        return []
    return [_finding_for_spec(module, _MISSING_ALL, 1)]


DETECTORS: dict[AphorismId, Callable[[ModuleSignals], list[Finding]]] = {
    AphorismId.BEAUTIFUL: _detect_beautiful,
    AphorismId.EXPLICIT: _detect_explicit,
    AphorismId.SIMPLE: _detect_simple,
    AphorismId.COMPLEX: _detect_complex,
    AphorismId.FLAT: _detect_flat,
    AphorismId.SPARSE: _detect_sparse,
    AphorismId.READABILITY: _detect_readability,
    AphorismId.SPECIAL_CASES: _detect_special_cases,
    AphorismId.PRACTICALITY: _detect_practicality,
    AphorismId.ERRORS_SILENT: _detect_errors_silent,
    AphorismId.EXPLICIT_SILENCED: _detect_explicit_silenced,
    AphorismId.AMBIGUITY: _detect_ambiguity,
    AphorismId.ONE_WAY: _detect_one_way,
    AphorismId.DUTCH: _detect_dutch,
    AphorismId.NOW: _detect_now,
    AphorismId.NEVER: _detect_never,
    AphorismId.HARD_EXPLAIN: _detect_hard_explain,
    AphorismId.EASY_EXPLAIN: _detect_easy_explain,
    AphorismId.NAMESPACES: _detect_namespaces,
}


def _count_documented_and_easy(
    metrics_tuple: tuple[FunctionMetrics, ...],
) -> tuple[int, int]:
    """Count documented and easy functions within one module."""
    docstring_count = 0
    easy_count = 0
    for metrics in metrics_tuple:
        if metrics.has_docstring:
            docstring_count += 1
        if _is_easy(metrics):
            easy_count += 1
    return docstring_count, easy_count


def aggregate_signals(modules: Iterable[ModuleSignals]) -> AggregateSignals:
    """Fold per-module signals into repo-wide aggregates for the verdicts."""
    function_total = 0
    docstring_function_count = 0
    comment_line_count = 0
    code_line_count = 0
    easy_function_count = 0
    for module in modules:
        function_total += len(module.functions)
        docstring_count, easy_count = _count_documented_and_easy(module.functions)
        docstring_function_count += docstring_count
        easy_function_count += easy_count
        comment_line_count += module.comment_line_count
        code_line_count += module.code_line_count
    return AggregateSignals(
        function_total=function_total,
        docstring_function_count=docstring_function_count,
        comment_line_count=comment_line_count,
        code_line_count=code_line_count,
        easy_function_count=easy_function_count,
    )


def _threshold_verdict(n: int, threshold: int) -> Verdict:
    """Apply the strict count rule for the given threshold."""
    if n == 0:
        return Verdict.STRONG
    if n < threshold:
        return Verdict.MODERATE
    return Verdict.WEAK


def _make_threshold_verdict(
    threshold: int,
) -> Callable[[list[Finding], AggregateSignals], Verdict]:
    """Build the strict count rule for a single threshold."""

    def verdict(findings: list[Finding], _aggregates: AggregateSignals) -> Verdict:
        return _threshold_verdict(len(findings), threshold)

    return verdict


def _advisory_verdict(findings: list[Finding], _aggregates: AggregateSignals) -> Verdict:
    """Apply the advisory count rule used by aphorisms 12, 13 and 15."""
    n = len(findings)
    if n <= ADVISORY_STRONG_MAX:
        return Verdict.STRONG
    if n <= ADVISORY_MODERATE_MAX:
        return Verdict.MODERATE
    return Verdict.WEAK


def _docstring_ratio(aggregates: AggregateSignals) -> float:
    """Fraction of functions carrying a docstring, defaulting to full."""
    if aggregates.function_total > 0:
        return aggregates.docstring_function_count / aggregates.function_total
    return 1.0


def _comment_ratio(aggregates: AggregateSignals) -> float:
    """Fraction of source lines that are comments, defaulting to none."""
    comment_total = aggregates.comment_line_count + aggregates.code_line_count
    if comment_total > 0:
        return aggregates.comment_line_count / comment_total
    return 0.0


def _verdict_readability(_findings: list[Finding], aggregates: AggregateSignals) -> Verdict:
    """Judge readability from docstring and comment ratios."""
    docstring_ratio = _docstring_ratio(aggregates)
    comment_ratio = _comment_ratio(aggregates)
    if docstring_ratio >= STRONG_DOCSTRING_RATIO and (
        COMMENT_RATIO_FLOOR <= comment_ratio <= COMMENT_RATIO_CEILING
    ):
        return Verdict.STRONG
    if docstring_ratio >= MODERATE_DOCSTRING_RATIO:
        return Verdict.MODERATE
    return Verdict.WEAK


def _verdict_easy_explain(_findings: list[Finding], aggregates: AggregateSignals) -> Verdict:
    """Judge explainability from the fraction of easy functions."""
    easy_ratio = (
        aggregates.easy_function_count / aggregates.function_total
        if aggregates.function_total > 0
        else 1.0
    )
    if easy_ratio >= STRONG_EASY_RATIO:
        return Verdict.STRONG
    if MODERATE_EASY_RATIO_FLOOR <= easy_ratio < STRONG_EASY_RATIO:
        return Verdict.MODERATE
    return Verdict.WEAK


def _verdict_not_assessable(_findings: list[Finding], _aggregates: AggregateSignals) -> Verdict:
    """Report that a human-judgement aphorism carries no mechanical verdict."""
    return Verdict.NOT_ASSESSABLE


VERDICT_RULES: dict[AphorismId, Callable[[list[Finding], AggregateSignals], Verdict]] = {
    AphorismId.BEAUTIFUL: _make_threshold_verdict(10),
    AphorismId.EXPLICIT: _make_threshold_verdict(10),
    AphorismId.SIMPLE: _make_threshold_verdict(5),
    AphorismId.COMPLEX: _make_threshold_verdict(3),
    AphorismId.FLAT: _make_threshold_verdict(3),
    AphorismId.SPARSE: _make_threshold_verdict(10),
    AphorismId.READABILITY: _verdict_readability,
    AphorismId.SPECIAL_CASES: _make_threshold_verdict(5),
    AphorismId.PRACTICALITY: _verdict_not_assessable,
    AphorismId.ERRORS_SILENT: _make_threshold_verdict(3),
    AphorismId.EXPLICIT_SILENCED: _make_threshold_verdict(3),
    AphorismId.AMBIGUITY: _advisory_verdict,
    AphorismId.ONE_WAY: _advisory_verdict,
    AphorismId.DUTCH: _verdict_not_assessable,
    AphorismId.NOW: _advisory_verdict,
    AphorismId.NEVER: _verdict_not_assessable,
    AphorismId.HARD_EXPLAIN: _make_threshold_verdict(5),
    AphorismId.EASY_EXPLAIN: _verdict_easy_explain,
    AphorismId.NAMESPACES: _make_threshold_verdict(3),
}

RUBRICS: dict[AphorismId, str] = {
    AphorismId.PRACTICALITY: (
        "Pragmatic deviations are judged by their justification. Review each "
        "suppression (noqa/nosec/pragma) on whether its owner/reason makes the "
        "purity trade-off worthwhile; the analyser only inventories them."
    ),
    AphorismId.DUTCH: (
        "Obviousness is subjective. Review 'clever' idioms (walrus, dense "
        "ternaries, multi-clause comprehensions) with a human eye; the analyser "
        "does not judge cleverness."
    ),
    AphorismId.NEVER: (
        "Temporality is unknowable statically. Triage the TODO/FIXME markers "
        "surfaced by aphorism 15 and decide which should simply never happen."
    ),
}


def verdict_for(
    aphorism: AphorismId,
    findings: list[Finding],
    aggregates: AggregateSignals,
) -> Verdict:
    """Dispatch findings to the deterministic verdict rule for an aphorism."""
    try:
        rule = VERDICT_RULES[aphorism]
    except KeyError:
        return Verdict.NOT_ASSESSABLE
    return rule(findings, aggregates)
