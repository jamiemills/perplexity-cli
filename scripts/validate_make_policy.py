"""Make target ownership and dependency validator.

Parses the ``make -p`` (print database) output of a Makefile and enforces a
small policy on top of it:

* A configurable list of targets must exist.
* A configurable mapping of targets must declare their expected prerequisites.
* No two unrelated targets should both run the same canonical command (a sign
  of accidentially duplicated responsibility).

The default expectation set is intentionally tiny — callers are expected to
extend it via the CLI flags.

Usage::

    uv run python scripts/validate_make_policy.py [--makefile PATH]
                                                  [--json]

Exit codes:
    0  pass       — every declared policy holds
    1  fail       — at least one policy violation
    2  usage      — Makefile not found or ``make`` unavailable
"""

from __future__ import annotations

import argparse
import json
import logging
import re

# owner: quality-infrastructure; reason: fixed make database query runs without a shell
import subprocess  # nosec B404
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAKEFILE = PROJECT_ROOT / "Makefile"

EXIT_PASS: int = 0
EXIT_FAIL: int = 1
EXIT_USAGE: int = 2

SEVERITY_ERROR: str = "error"
SEVERITY_WARNING: str = "warning"

# Canonical "interesting" targets expected to exist in this project. These can
# be overridden by callers via the CLI.
DEFAULT_REQUIRED_TARGETS: tuple[str, ...] = (
    "test",
    "lint",
    "format-check",
    "ci-static",
    "ci-test-coverage",
    "ci-test-compat",
    "ci-property",
    "ci-package",
)

# Targets whose prerequisites should follow a known shape. Each value is the
# list of prerequisites that must all be present (in any order).
DEFAULT_DEPENDENCY_RULES: dict[str, tuple[str, ...]] = {
    "ci": (
        "ci-static",
        "ci-test-coverage",
        "ci-fuzz-status",
        "pip-audit",
        "sonar-reports",
        "ci-property",
        "ci-package",
        "smoke-test",
    ),
    "ci-trusted": ("ci", "safety-gate"),
}

# Canonical command tokens that, if shared across two unrelated targets,
# usually indicate duplicated responsibility. Each token maps to the single
# target that should "own" it.
DEFAULT_COMMAND_OWNERSHIP: dict[str, str] = {}


class ReportFormat(Enum):
    """Select machine-readable or human-readable report output."""

    JSON = "json"
    TEXT = "text"


class MakefileSchemaError(ValueError):
    """A non-canonical Makefile uses syntax the safe parser cannot model."""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MakeTarget:
    """A single Make target with its prerequisites and recipe.

    Attributes:
        name: Target name as it appears in the Makefile.
        prerequisites: Tuple of prerequisite target names.
        recipe: Tuple of recipe command lines (untrimmed).
    """

    name: str
    prerequisites: tuple[str, ...] = ()
    recipe: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Finding:
    """A single policy finding.

    Attributes:
        severity: ``error`` or ``warning``.
        code: Stable machine-readable rule identifier.
        message: Human-readable description.
        target: Offending target name when applicable.
    """

    severity: str
    code: str
    message: str
    target: str | None = None


@dataclass(frozen=True, slots=True)
class MakeReport:
    """Aggregated policy report.

    Attributes:
        makefile: Path of the Makefile that was analysed.
        targets: Parsed target definitions keyed by name.
        findings: Policy violations discovered.
    """

    makefile: str
    targets: dict[str, MakeTarget] = field(default_factory=dict[str, MakeTarget])
    findings: list[Finding] = field(default_factory=list[Finding])


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


# A target rule line in `make -p` output looks like "name1 name2: prereqs".
# Variable assignment lines look like "VAR := value" or "VAR ?= value".
_TARGET_RULE_PATTERN: re.Pattern[str] = re.compile(
    r"^(?P<targets>[^\s=:][^\s=]*(:?\s[^\s=:][^\s=]*)*):\s*(?P<rest>.*)$"
)
_VARIABLE_ASSIGNMENT_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?P<operator>:=|=)\s*(?P<value>.*)$"
)
_TARGET_SPECIFIC_ASSIGNMENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*(?:::=|:=|\?=|\+=|=)")
_VARIABLE_REFERENCE_PATTERN = re.compile(r"\$\((?P<paren>[^()]*)\)|\$\{(?P<brace>[^{}]*)\}")
_VARIABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_UNSUPPORTED_DIRECTIVE_PATTERN = re.compile(
    r"^(?:-?include|sinclude|ifeq|ifneq|ifdef|ifndef|else|endif|define|endef|override|export|unexport)\b"
)


def _new_string_lists() -> dict[str, list[str]]:
    """Create a string-keyed list accumulator."""
    return defaultdict(list)


@dataclass(slots=True)
class _SourceParseState:
    """Mutable state for safe Makefile source parsing."""

    variables: dict[str, str] = field(default_factory=dict[str, str])
    prereqs: dict[str, list[str]] = field(default_factory=_new_string_lists)
    recipes: dict[str, list[str]] = field(default_factory=_new_string_lists)
    current_targets: tuple[str, ...] = ()


def parse_make_database(text: str) -> dict[str, MakeTarget]:
    """Parse ``make -p`` output into a dict of :class:`MakeTarget`.

    Args:
        text: Raw stdout of ``make -p``.

    Returns:
        Mapping of target name → :class:`MakeTarget`. Pattern rules
        (containing ``%``), variable assignments, and special targets
        beginning with ``.`` are skipped.
    """
    prereqs: dict[str, list[str]] = defaultdict(list)
    recipes: dict[str, list[str]] = defaultdict(list)
    _accumulate_lines(text.splitlines(), prereqs, recipes)
    return _build_targets(prereqs, recipes)


def parse_makefile_source(text: str) -> dict[str, MakeTarget]:
    """Safely parse the supported static subset of Makefile source syntax."""
    state = _SourceParseState()
    for line in _logical_source_lines(text):
        _consume_source_line(line, state)
    return _build_targets(state.prereqs, state.recipes)


def _logical_source_lines(text: str) -> list[str]:
    """Join backslash continuations outside recipes."""
    physical_lines = text.splitlines()
    logical_lines: list[str] = []
    index = 0
    while index < len(physical_lines):
        line = physical_lines[index]
        index += 1
        if line.startswith("\t"):
            logical_lines.append(line)
            continue
        while line.rstrip().endswith("\\"):
            if index >= len(physical_lines):
                msg = "unterminated backslash continuation"
                raise MakefileSchemaError(msg)
            line = line.rstrip()[:-1] + " " + physical_lines[index].strip()
            index += 1
        logical_lines.append(line)
    return logical_lines


def _consume_source_line(line: str, state: _SourceParseState) -> None:
    """Consume one logical source line into parser state."""
    if line.startswith("\t"):
        _associate_source_recipe(line[1:], state)
        return
    statement = line.split("#", 1)[0].strip()
    if not statement:
        return
    if _UNSUPPORTED_DIRECTIVE_PATTERN.match(statement):
        msg = f"unsupported Make directive: {statement}"
        raise MakefileSchemaError(msg)
    assignment = _VARIABLE_ASSIGNMENT_PATTERN.match(statement)
    if assignment is not None:
        _record_source_variable(assignment, state)
        return
    state.current_targets = _record_source_rule(statement, state)


def _associate_source_recipe(recipe: str, state: _SourceParseState) -> None:
    """Associate one recipe line with every target in the preceding rule."""
    if not state.current_targets:
        msg = "recipe has no preceding supported target rule"
        raise MakefileSchemaError(msg)
    for target in state.current_targets:
        state.recipes[target].append(recipe)


def _record_source_variable(match: re.Match[str], state: _SourceParseState) -> None:
    """Record a simple recursive or immediate variable assignment."""
    name = match.group("name")
    value = match.group("value").strip()
    if match.group("operator") == ":=":
        value = _expand_source_variables(value, state.variables)
    state.variables[name] = value
    state.current_targets = ()


def _record_source_rule(statement: str, state: _SourceParseState) -> tuple[str, ...]:
    """Expand and record one static target rule."""
    expanded = _expand_source_variables(statement, state.variables)
    _reject_basic_rule_syntax(expanded, statement)
    match = _TARGET_RULE_PATTERN.match(expanded)
    if match is None:
        msg = f"unrecognised Makefile statement: {statement}"
        raise MakefileSchemaError(msg)
    _reject_target_specific_assignment(match, statement)
    _reject_double_colon_rule(expanded, statement)
    names, prereqs = _extract_target_pieces(match)
    if names == [".PHONY"]:
        return ()
    if not names or any(name.startswith(".") for name in names):
        msg = f"unsupported special target rule: {statement}"
        raise MakefileSchemaError(msg)
    _accumulate_rule(_pair_targets_with_prereqs(names, prereqs), state.prereqs)
    return tuple(names)


def _reject_basic_rule_syntax(expanded: str, statement: str) -> None:
    """Reject unsupported static rule operators except target assignments."""
    if any(token in expanded for token in (";", "|", "%")):
        msg = f"unsupported target rule syntax: {statement}"
        raise MakefileSchemaError(msg)


def _reject_double_colon_rule(expanded: str, statement: str) -> None:
    """Reject double-colon rules after target assignment detection."""
    if "::" in expanded:
        msg = f"unsupported target rule syntax: {statement}"
        raise MakefileSchemaError(msg)


def _reject_target_specific_assignment(match: re.Match[str], statement: str) -> None:
    """Reject target-specific variable assignment operators."""
    if _TARGET_SPECIFIC_ASSIGNMENT_PATTERN.match(match.group("rest").strip()):
        msg = f"unsupported target-specific variable assignment: {statement}"
        raise MakefileSchemaError(msg)


def _expand_source_variables(
    value: str,
    variables: dict[str, str],
    stack: tuple[str, ...] = (),
) -> str:
    """Expand simple Make variable references and reject dynamic functions."""

    def replace(match: re.Match[str]) -> str:
        name = match.group("paren") or match.group("brace")
        if not _VARIABLE_NAME_PATTERN.fullmatch(name):
            msg = f"unsupported dynamic Make expression: {match.group(0)}"
            raise MakefileSchemaError(msg)
        if name in stack:
            msg = f"cyclic Make variable reference: {name}"
            raise MakefileSchemaError(msg)
        return _expand_source_variables(variables.get(name, ""), variables, (*stack, name))

    expanded = _VARIABLE_REFERENCE_PATTERN.sub(replace, value)
    if "$" in expanded:
        msg = f"unsupported Make expansion: {expanded}"
        raise MakefileSchemaError(msg)
    return expanded


def _accumulate_lines(
    lines: list[str],
    prereqs: dict[str, list[str]],
    recipes: dict[str, list[str]],
) -> None:
    """Iterate database lines, populating ``prereqs`` and ``recipes`` dicts."""
    current: str | None = None
    for line in lines:
        rule = _parse_target_rule_line(line)
        if rule is not None:
            _accumulate_rule(rule, prereqs)
            current = rule[0][0]
            continue
        recipe_line = _parse_recipe_line(line)
        if recipe_line is not None and current is not None:
            recipes[current].append(recipe_line)


def _accumulate_rule(
    rule: list[tuple[str, list[str]]],
    prereqs: dict[str, list[str]],
) -> None:
    """Append one rule's prereqs to the accumulating dict."""
    for name, prereq_list in rule:
        prereqs[name].extend(prereq_list)


def _build_targets(
    prereqs: dict[str, list[str]],
    recipes: dict[str, list[str]],
) -> dict[str, MakeTarget]:
    """Assemble the final target dict, de-duplicating entries."""
    result: dict[str, MakeTarget] = {}
    for name, prereq_list in prereqs.items():
        clean_prereqs = tuple(_dedupe(prereq_list))
        clean_recipe = tuple(_dedupe(recipes.get(name, [])))
        result[name] = MakeTarget(
            name=name,
            prerequisites=clean_prereqs,
            recipe=clean_recipe,
        )
    return result


def _dedupe(items: list[str]) -> list[str]:
    """Return items in insertion order without duplicates."""
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _parse_target_rule_line(line: str) -> list[tuple[str, list[str]]] | None:
    """Parse a single database line into ``(target, prerequisites)`` pairs.

    Returns None for comments, recipe lines, variable assignments, and
    pattern rules.
    """
    if _is_skippable_line(line):
        return None
    match = _TARGET_RULE_PATTERN.match(line)
    if match is None:
        return None
    names, prereq_list = _extract_target_pieces(match)
    if not names or _has_pattern_or_special(names):
        return None
    return _pair_targets_with_prereqs(names, prereq_list)


def _is_skippable_line(line: str) -> bool:
    """Return True for blank, comment, or recipe lines."""
    return not line or line[0] in "#\t "


def _pair_targets_with_prereqs(names: list[str], prereqs: list[str]) -> list[tuple[str, list[str]]]:
    """Build (target, prereqs) pairs for each name."""
    return [(name, list(prereqs)) for name in names]


def _extract_target_pieces(match: re.Match[str]) -> tuple[list[str], list[str]]:
    """Return ``(target_names, prerequisites)`` from a rule match.

    Returns an empty name list if the match is actually a variable assignment.
    """
    target_part = match.group("targets")
    rest = match.group("rest")
    if _looks_like_assignment(rest):
        return [], []
    names = target_part.split()
    prereq_part = rest.split(";", 1)[0]
    return names, prereq_part.split()


def _has_pattern_or_special(names: list[str]) -> bool:
    """Return True if any target name is a pattern rule or Make special target."""
    return any("%" in name or name.startswith(".") for name in names)


def _looks_like_assignment(rest: str) -> bool:
    """Return True if the text after ``:`` is actually an assignment operator."""
    stripped = rest.lstrip()
    return stripped.startswith(("=", ":=", "::=", "?=", "+="))


def _parse_recipe_line(line: str) -> str | None:
    """Return the recipe text for a TAB-indented line, else None."""
    if not line.startswith("\t"):
        return None
    return line[1:]


# ---------------------------------------------------------------------------
# Subprocess wrapper
# ---------------------------------------------------------------------------


# A non-existent target requested purely to suppress execution of the
# Makefile's default goal. Without this, ``make -p`` would attempt to build
# the first declared target, which could run side-effecting recipes.
_DATABASE_QUERY_TARGET = "__px_policy_db_query__"

# Subprocess timeout in seconds for any single ``make -p`` invocation.
_MAKE_TIMEOUT_S = 30


def _run_make_database(makefile: Path) -> str:
    """Return parseable target text without executing caller-controlled Makefiles.

    The canonical repository Makefile is trusted and expanded with ``make -p``.
    Every other file is read directly and parsed without invoking Make.

    Args:
        makefile: Path to the Makefile to inspect.

    Returns:
        The raw stdout of ``make``.

    Raises:
        FileNotFoundError: If ``make`` is not installed or the Makefile
            is missing.
        subprocess.CalledProcessError: If ``make`` produces no stdout
            (e.g. invalid Makefile syntax that fails before printing).
        subprocess.TimeoutExpired: If the invocation exceeds the timeout.
    """
    resolved_makefile = makefile.resolve(strict=True)
    canonical_makefile = DEFAULT_MAKEFILE.resolve(strict=True)
    if resolved_makefile != canonical_makefile:
        return makefile.read_text(encoding="utf-8")
    cmd: list[str] = [
        "make",
        "-p",
        "-f",
        str(canonical_makefile),
        _DATABASE_QUERY_TARGET,
    ]
    logger.info("Running: %s", " ".join(cmd))
    try:
        # owner: quality-infrastructure; reason: only the resolved trusted repository Makefile is queried
        result = subprocess.run(  # nosec B603
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=_MAKE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise subprocess.TimeoutExpired(cmd, _MAKE_TIMEOUT_S) from exc
    if not result.stdout.strip():
        detail = result.stderr.strip() or result.stdout.strip()
        raise subprocess.CalledProcessError(
            result.returncode,
            cmd,
            output=result.stdout,
            stderr=detail,
        )
    return result.stdout


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def validate_required_targets(
    targets: dict[str, MakeTarget],
    required: list[str],
) -> list[Finding]:
    """Check that every required target name is defined.

    Args:
        targets: Parsed target definitions.
        required: Required target names.

    Returns:
        A finding per missing target.
    """
    findings: list[Finding] = []
    for name in required:
        if name not in targets:
            findings.append(
                Finding(
                    severity=SEVERITY_ERROR,
                    code="MAKE_TARGET_MISSING",
                    message=f"required Make target '{name}' is not defined",
                    target=name,
                )
            )
    return findings


def validate_dependencies(
    targets: dict[str, MakeTarget],
    expected_deps: dict[str, list[str]],
) -> list[Finding]:
    """Check expected prerequisite presence for specific targets.

    Args:
        targets: Parsed target definitions.
        expected_deps: Mapping of target → list of prerequisites that must
            be present (in any order).

    Returns:
        A finding per missing prerequisite or undefined target.
    """
    findings: list[Finding] = []
    for target_name, expected in expected_deps.items():
        findings.extend(_check_one_target_deps(targets, target_name, expected))
    return findings


def _check_one_target_deps(
    targets: dict[str, MakeTarget],
    target_name: str,
    expected: list[str],
) -> list[Finding]:
    """Check prerequisites for a single target."""
    if target_name not in targets:
        return [
            Finding(
                severity=SEVERITY_ERROR,
                code="MAKE_DEP_TARGET_MISSING",
                message=(f"cannot verify dependencies of '{target_name}': target is not defined"),
                target=target_name,
            )
        ]
    actual = set(targets[target_name].prerequisites)
    missing = [prereq for prereq in expected if prereq not in actual]
    if missing:
        return [
            Finding(
                severity=SEVERITY_ERROR,
                code="MAKE_DEP_MISSING",
                message=(
                    f"target '{target_name}' is missing prerequisite(s): " + ", ".join(missing)
                ),
                target=target_name,
            )
        ]
    return []


def validate_command_ownership(
    targets: dict[str, MakeTarget],
    ownership: dict[str, str],
) -> list[Finding]:
    """Check canonical commands are owned by exactly one target.

    Args:
        targets: Parsed target definitions.
        ownership: Mapping of command token → canonical owning target.

    Returns:
        A finding for each command found in a non-canonical target.
    """
    findings: list[Finding] = []
    for command, owner in ownership.items():
        findings.extend(_check_one_command_owners(targets, command, owner))
    return findings


def _check_one_command_owners(
    targets: dict[str, MakeTarget],
    command: str,
    owner: str,
) -> list[Finding]:
    """Check ownership for a single canonical command."""
    holders = _targets_running_command(targets, command)
    offenders = sorted(name for name in holders if name != owner)
    if not offenders:
        return []
    return [
        Finding(
            severity=SEVERITY_WARNING,
            code="MAKE_COMMAND_DUPLICATED",
            message=(
                f"canonical command '{command}' also appears in target(s): " + ", ".join(offenders)
            ),
            target=offenders[0],
        )
    ]


def _targets_running_command(
    targets: dict[str, MakeTarget],
    command: str,
) -> list[str]:
    """Return the names of targets whose recipe contains ``command``."""
    pattern = re.compile(rf"\b{re.escape(command)}\b")
    return [
        name
        for name, target in targets.items()
        if any(pattern.search(recipe_line) for recipe_line in target.recipe)
    ]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PolicySpec:
    """Declarative policy spec consumed by :func:`run_policy`.

    Attributes:
        required_targets: Targets that must exist.
        dependency_rules: Mapping of target → expected prerequisites.
        command_ownership: Mapping of canonical command → owning target.
    """

    required_targets: list[str]
    dependency_rules: dict[str, list[str]]
    command_ownership: dict[str, str]


def run_policy(targets: dict[str, MakeTarget], spec: PolicySpec) -> list[Finding]:
    """Run every policy check against the parsed targets.

    Args:
        targets: Parsed target definitions.
        spec: Declarative policy specification.

    Returns:
        List of findings, errors first then warnings.
    """
    findings: list[Finding] = []
    findings.extend(validate_required_targets(targets, spec.required_targets))
    findings.extend(validate_dependencies(targets, spec.dependency_rules))
    findings.extend(validate_command_ownership(targets, spec.command_ownership))
    return findings


def analyse_makefile(makefile: Path, spec: PolicySpec) -> MakeReport:
    """Parse ``makefile`` and run the policy against it.

    Args:
        makefile: Path to the Makefile to analyse.
        spec: Policy specification to apply.

    Returns:
        A :class:`MakeReport` with parsed targets and findings.
    """
    resolved_makefile = makefile.resolve(strict=True)
    if resolved_makefile == DEFAULT_MAKEFILE.resolve(strict=True):
        targets = parse_make_database(_run_make_database(makefile))
    else:
        targets = parse_makefile_source(makefile.read_text(encoding="utf-8"))
    findings = run_policy(targets, spec)
    return MakeReport(makefile=str(makefile), targets=targets, findings=findings)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _finding_to_dict(finding: Finding) -> dict[str, Any]:
    """Serialise a :class:`Finding` to a JSON-compatible dict."""
    payload: dict[str, Any] = {
        "severity": finding.severity,
        "code": finding.code,
        "message": finding.message,
    }
    if finding.target is not None:
        payload["target"] = finding.target
    return payload


def _target_to_dict(target: MakeTarget) -> dict[str, Any]:
    """Serialise a :class:`MakeTarget` to a JSON-compatible dict."""
    return {
        "name": target.name,
        "prerequisites": list(target.prerequisites),
        "recipe": list(target.recipe),
    }


def report_to_dict(report: MakeReport) -> dict[str, Any]:
    """Serialise a :class:`MakeReport` to a JSON-compatible dict.

    Args:
        report: The report to serialise.

    Returns:
        Dict with ``pass``, ``makefile``, ``target_count``, ``error_count``,
        ``warning_count``, ``targets``, and ``findings`` keys.
    """
    errors, warnings = _count_findings_by_severity(report.findings)
    return {
        "pass": errors == 0,
        "makefile": report.makefile,
        "target_count": len(report.targets),
        "error_count": errors,
        "warning_count": warnings,
        "targets": {name: _target_to_dict(target) for name, target in report.targets.items()},
        "findings": [_finding_to_dict(f) for f in report.findings],
    }


def _count_findings_by_severity(findings: list[Finding]) -> tuple[int, int]:
    """Return ``(error_count, warning_count)`` for the given findings."""
    errors = sum(1 for f in findings if f.severity == SEVERITY_ERROR)
    warnings = sum(1 for f in findings if f.severity == SEVERITY_WARNING)
    return errors, warnings


# ---------------------------------------------------------------------------
# Human-readable output
# ---------------------------------------------------------------------------


def _format_text(report: MakeReport) -> str:
    """Format a :class:`MakeReport` as human-readable text."""
    lines: list[str] = [f"Makefile: {report.makefile}"]
    lines.append(f"Parsed {len(report.targets)} target(s).")
    if not report.findings:
        lines.append("OK — no policy violations.")
        return "\n".join(lines)
    for finding in report.findings:
        location = finding.target or "-"
        lines.append(f"  [{finding.severity.upper():7}] {finding.code} ({location})")
        lines.append(f"      {finding.message}")
    payload = report_to_dict(report)
    lines.append(
        f"\nMake policy: {payload['error_count']} error(s), {payload['warning_count']} warning(s)."
    )
    lines.append("FAIL" if payload["error_count"] else "PASS (with warnings)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _default_spec() -> PolicySpec:
    """Build the default :class:`PolicySpec` from the module constants."""
    return PolicySpec(
        required_targets=list(DEFAULT_REQUIRED_TARGETS),
        dependency_rules={
            name: list(prereqs) for name, prereqs in DEFAULT_DEPENDENCY_RULES.items()
        },
        command_ownership=dict(DEFAULT_COMMAND_OWNERSHIP),
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list, or None for ``sys.argv[1:]``.

    Returns:
        Namespace with ``makefile`` and ``json`` attributes.
    """
    parser = argparse.ArgumentParser(
        description="Make target ownership and dependency validator.",
    )
    parser.add_argument(
        "--makefile",
        type=Path,
        default=DEFAULT_MAKEFILE,
        help=f"Makefile to analyse (default: {DEFAULT_MAKEFILE}).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON report instead of human-readable text.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code: 0 pass, 1 fail, 2 usage error.
    """
    args = _parse_args(argv)
    if not args.makefile.is_file():
        sys.stderr.write(f"Makefile not found: {args.makefile}\n")
        return EXIT_USAGE
    report = _build_report_safely(args.makefile)
    if report is None:
        return EXIT_USAGE
    _emit_report(report, args.json)
    payload = report_to_dict(report)
    return EXIT_PASS if payload["pass"] else EXIT_FAIL


def _build_report_safely(makefile: Path) -> MakeReport | None:
    """Run analysis, returning None if a usage-level failure occurred."""
    spec = _default_spec()
    try:
        return analyse_makefile(makefile, spec)
    except FileNotFoundError as exc:
        sys.stderr.write(f"'make' executable not found: {exc}\n")
        return None
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"make failed: {exc}\n")
        return None
    except MakefileSchemaError as exc:
        sys.stderr.write(f"unsupported Makefile schema: {exc}\n")
        return None


# owner: quality-infrastructure; reason: stable tested helper contract
def _emit_report(  # nosemgrep: boolean-flag-argument
    report: MakeReport, json_mode: bool
) -> None:
    """Convert the stable boolean contract and emit the report."""
    output_format = ReportFormat.JSON if json_mode else ReportFormat.TEXT
    _emit_report_with_format(report, output_format)


def _emit_report_with_format(report: MakeReport, output_format: ReportFormat) -> None:
    """Print the report in the requested format."""
    if output_format is ReportFormat.JSON:
        print(json.dumps(report_to_dict(report), indent=2))
    else:
        print(_format_text(report))


if __name__ == "__main__":
    sys.exit(main())
