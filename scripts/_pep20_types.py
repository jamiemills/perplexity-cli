"""Shared data model and aphorism catalogue for the PEP 20 adherence analyser.

This module owns every cross-module type used by the analyser.  The G1 build
invariant is that ``_pep20_metrics``, ``_pep20_detectors``, ``_pep20_scoping``
and ``_pep20_report`` import from here and never from each other.

The ``ModuleSignals`` contract is the single source of truth for what
``_pep20_metrics`` pre-computes and what ``_pep20_detectors`` consumes: every
signal a detector needs is a field on this dataclass so detectors never need
the AST themselves.

Verbatim aphorism text is from the Zen of Python (``import this``).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

__all__ = [
    "APHORISMS",
    "NON_MECHANICAL",
    "AggregateSignals",
    "AphorismId",
    "DiffEntry",
    "DuplicateBlock",
    "ExceptMetrics",
    "Finding",
    "FunctionMetrics",
    "Hunk",
    "ModuleSignals",
    "Severity",
    "Verdict",
]


class AphorismId(IntEnum):
    """Canonical numbering of the nineteen Zen of Python aphorisms."""

    BEAUTIFUL = 1
    EXPLICIT = 2
    SIMPLE = 3
    COMPLEX = 4
    FLAT = 5
    SPARSE = 6
    READABILITY = 7
    SPECIAL_CASES = 8
    PRACTICALITY = 9
    ERRORS_SILENT = 10
    EXPLICIT_SILENCED = 11
    AMBIGUITY = 12
    ONE_WAY = 13
    DUTCH = 14
    NOW = 15
    NEVER = 16
    HARD_EXPLAIN = 17
    EASY_EXPLAIN = 18
    NAMESPACES = 19


APHORISMS: dict[AphorismId, str] = {
    AphorismId.BEAUTIFUL: "Beautiful is better than ugly.",
    AphorismId.EXPLICIT: "Explicit is better than implicit.",
    AphorismId.SIMPLE: "Simple is better than complex.",
    AphorismId.COMPLEX: "Complex is better than complicated.",
    AphorismId.FLAT: "Flat is better than nested.",
    AphorismId.SPARSE: "Sparse is better than dense.",
    AphorismId.READABILITY: "Readability counts.",
    AphorismId.SPECIAL_CASES: "Special cases aren't special enough to break the rules.",
    AphorismId.PRACTICALITY: "Although practicality beats purity.",
    AphorismId.ERRORS_SILENT: "Errors should never pass silently.",
    AphorismId.EXPLICIT_SILENCED: "Unless explicitly silenced.",
    AphorismId.AMBIGUITY: "In the face of ambiguity, refuse the temptation to guess.",
    AphorismId.ONE_WAY: "There should be one-- and preferably only one --obvious way to do it.",
    AphorismId.DUTCH: "Although that way may not be obvious at first unless you're Dutch.",
    AphorismId.NOW: "Now is better than never.",
    AphorismId.NEVER: "Although never is often better than *right* now.",
    AphorismId.HARD_EXPLAIN: "If the implementation is hard to explain, it's a bad idea.",
    AphorismId.EASY_EXPLAIN: "If the implementation is easy to explain, it may be a good idea.",
    AphorismId.NAMESPACES: "Namespaces are one honking great idea -- let's do more of those!",
}

NON_MECHANICAL: frozenset[AphorismId] = frozenset(
    {AphorismId.PRACTICALITY, AphorismId.DUTCH, AphorismId.NEVER}
)


class Severity(StrEnum):
    """Severity of a finding, for report presentation only."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Verdict(StrEnum):
    """Per-aphorism verdict produced by the deterministic verdict rules."""

    STRONG = "Strong"
    MODERATE = "Moderate"
    WEAK = "Weak"
    NOT_ASSESSABLE = "Not-assessable"


@dataclass(frozen=True, slots=True)
class Finding:
    """A single evidence item: one aphorism, one location, one code."""

    aphorism: AphorismId
    severity: Severity
    code: str
    path: str
    line: int
    end_line: int
    message: str


@dataclass(frozen=True, slots=True)
class FunctionMetrics:
    """Per-function complexity and documentation metrics."""

    cc: int
    nesting_depth: int
    arg_count: int
    return_count: int
    statement_count: int
    has_docstring: bool
    start_line: int
    end_line: int


@dataclass(frozen=True, slots=True)
class ExceptMetrics:
    """Classification of a single ``except`` handler.

    ``kind`` is one of ``bare``, ``broad``, ``pass``, ``silent``, ``commented``,
    ``logged``, ``raise``, ``raise_from`` or ``return``.
    """

    kind: str
    line: int


@dataclass(frozen=True, slots=True)
class DuplicateBlock:
    """An identifier-normalised function body shared by two or more functions."""

    lines: tuple[int, ...]
    body_hash: str


@dataclass(frozen=True, slots=True)
class Hunk:
    """An added-line range parsed from a unified diff hunk header."""

    start_line: int
    length: int


@dataclass(frozen=True, slots=True)
class DiffEntry:
    """One changed file entry from the GitHub pulls files endpoint."""

    filename: str
    status: str
    previous_filename: str | None
    additions: int
    deletions: int
    patch: str | None
    head_sha: str


@dataclass(frozen=True, slots=True)
class ModuleSignals:
    """The full pre-computed signal contract for one source module.

    Every field is either an aggregate count, a line-indexed occurrence tuple,
    or a structural flag.  Detectors consume only these fields.
    """

    module_path: str
    functions: tuple[FunctionMetrics, ...] = ()
    excepts: tuple[ExceptMetrics, ...] = ()
    duplicate_blocks: tuple[DuplicateBlock, ...] = ()
    module_has_docstring: bool = False
    comment_line_count: int = 0
    code_line_count: int = 0
    long_line_count: int = 0
    long_lines: tuple[tuple[int, int], ...] = ()
    compound_line_count: int = 0
    compound_statement_lines: tuple[int, ...] = ()
    tab_mix_count: int = 0
    tab_mix_lines: tuple[int, ...] = ()
    noqa_count: int = 0
    type_ignore_count: int = 0
    todo_count: int = 0
    todo_lines: tuple[int, ...] = ()
    wildcard_import_count: int = 0
    wildcard_import_lines: tuple[int, ...] = ()
    global_statement_lines: tuple[int, ...] = ()
    getattr_count: int = 0
    getattr_lines: tuple[int, ...] = ()
    eval_exec_count: int = 0
    eval_exec_lines: tuple[int, ...] = ()
    magic_number_count: int = 0
    magic_numbers: tuple[tuple[int, object], ...] = ()
    function_import_lines: tuple[int, ...] = ()
    stub_function_lines: tuple[int, ...] = ()
    guess_continue_lines: tuple[int, ...] = ()
    fallback_chain_lines: tuple[int, ...] = ()
    bare_except_count: int = 0
    silent_swallow_count: int = 0
    has_all_in_init: bool = False
    parse_error: str | None = None


@dataclass(frozen=True, slots=True)
class AggregateSignals:
    """Repo-level aggregates folded from all module signals.

    Stores raw counts, never fractions, so verdicts compute ratios from a
    defined denominator at report time.
    """

    function_total: int = 0
    docstring_function_count: int = 0
    comment_line_count: int = 0
    code_line_count: int = 0
    easy_function_count: int = 0
