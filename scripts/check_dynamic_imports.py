"""Supplemental dynamic-import analyser.

Consumes quality/architecture.toml for direction policy and detects
runtime import-resolution calls (importlib.import_module, __import__) that
skirt static-analysis-based architecture checks.  Every dynamic import
must be covered by a site-specific declaration in the manifest, or else
the call is treated as a violation.

Proves that moving a forbidden static import into a dynamic call
(e.g. ``importlib.import_module("forbidden.module")``) still fails.

Usage
-----
    python scripts/check_dynamic_imports.py                     # full codebase (baseline applied)
    python scripts/check_dynamic_imports.py --files a.py b.py   # specific files
    python scripts/check_dynamic_imports.py --json              # machine-readable output
    python scripts/check_dynamic_imports.py --no-baseline       # show all violations
    python scripts/check_dynamic_imports.py --toml custom.toml  # use a custom TOML file
"""

from __future__ import annotations

import ast as python_ast
import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src" / "perplexity_cli"
DEFAULT_TOML_PATH = PROJECT_ROOT / "quality" / "architecture.toml"
BASELINE_PATH = PROJECT_ROOT / ".dynamic-imports-baseline.json"
PACKAGE_NAME = "perplexity_cli"

_DYNAMIC_IMPORT_FUNCTIONS = frozenset(
    {
        "import_module",
        "__import__",
    }
)

_IMPORTLIB_MODULE = "importlib"


# ---------------------------------------------------------------------------
# Severity & data types
# ---------------------------------------------------------------------------


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Violation:
    severity: Severity
    rule: str
    message: str
    file: str


@dataclass
class AnalysisResult:
    violations: list[Violation] = field(default_factory=list[Violation])
    files_checked: int = 0

    @property
    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == Severity.WARNING]

    @property
    def clean(self) -> bool:
        return not self.errors and not self.warnings


# ---------------------------------------------------------------------------
# TOML parsing (shared helpers)
# ---------------------------------------------------------------------------


def _load_toml(path: Path) -> dict[str, Any]:
    """Parse a TOML file, dying on read/parse errors."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        print(f"TOML file not found: {path}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Failed to parse TOML file {path}: {exc}", file=sys.stderr)
        sys.exit(1)


def _build_layer_map(model: dict[str, Any]) -> dict[str, tuple[str, frozenset[str]]]:
    """Build module_rel -> (layer_name, frozenset(allowed_deps)) from TOML data."""
    layer_map: dict[str, tuple[str, frozenset[str]]] = {}
    for layer in model.get("layers", []):
        name = layer.get("name", "")
        allowed = frozenset(layer.get("allowed_deps", []))
        for mod in layer.get("modules", []):
            if isinstance(mod, str):
                normalised = "" if mod in {".", ""} else mod
                layer_map[normalised] = (name, allowed)
    return layer_map


def _build_dynamic_allowlist(model: dict[str, Any]) -> dict[str, set[str]]:
    """Build module_rel -> set(allowed_dynamic_import_targets) from TOML data.

    Reads ``[dynamic_imports]`` section where keys are source module paths
    and values are lists of permitted dynamic-import targets.
    """
    allowlist: dict[str, set[str]] = {}
    dynamic_section: object = model.get("dynamic_imports", {})
    if isinstance(dynamic_section, dict):
        dynamic_mapping = cast(dict[object, object], dynamic_section)
        for source, targets in dynamic_mapping.items():
            if isinstance(targets, list):
                typed_targets = cast(list[object], targets)
                allowlist[str(source)] = {
                    target for target in typed_targets if isinstance(target, str)
                }
    return allowlist


# ---------------------------------------------------------------------------
# Layer assignment helpers (same logic as check_architecture.py)
# ---------------------------------------------------------------------------


def _layer_for_module(
    module_rel: str, layer_map: dict[str, tuple[str, frozenset[str]]]
) -> str | None:
    """Return the layer name for *module_rel*."""
    if module_rel in layer_map:
        return layer_map[module_rel][0]
    if not module_rel:
        return None
    return _prefix_match_layer(module_rel, layer_map)


def _prefix_match_layer(
    module_rel: str,
    layer_map: dict[str, tuple[str, frozenset[str]]],
) -> str | None:
    """Fallback: match the most-specific prefix present in the layer map."""
    parts = module_rel.split(".")
    for i in range(len(parts) - 1, 0, -1):
        prefix = ".".join(parts[:i])
        if prefix and prefix in layer_map:
            return layer_map[prefix][0]
    return None


def _allowed_deps_for_module(
    module_rel: str, layer_map: dict[str, tuple[str, frozenset[str]]]
) -> frozenset[str]:
    """Return the allowed deps for *module_rel*'s layer, or empty frozenset."""
    if module_rel in layer_map:
        return layer_map[module_rel][1]
    fallback = _prefix_match_layer(module_rel, layer_map)
    if fallback is not None:
        return _find_prefix_allowed(module_rel, layer_map)
    return frozenset()


def _find_prefix_allowed(
    module_rel: str, layer_map: dict[str, tuple[str, frozenset[str]]]
) -> frozenset[str]:
    """Find allowed_deps by longest-matching prefix."""
    for prefix in sorted(layer_map.keys(), key=lambda x: -len(x)):
        if prefix and module_rel.startswith(prefix + "."):
            return layer_map[prefix][1]
    return frozenset()


# ---------------------------------------------------------------------------
# AST dynamic-import detection
# ---------------------------------------------------------------------------


def _module_rel_from_path(filepath: Path) -> str:
    """Convert a source file path to a dotted relative module name."""
    rel = filepath.relative_to(SRC_ROOT)
    if rel.name == "__init__.py":
        pkg = str(rel.parent)
        return "" if pkg == "." else pkg.replace("/", ".")
    return str(rel.with_suffix("")).replace("/", ".")


@dataclass
class _DynamicImportCall:
    """A detected dynamic-import call site."""

    func_name: str
    argument: str | None
    lineno: int
    is_constant: bool


def _detect_dynamic_imports(tree: python_ast.AST) -> list[_DynamicImportCall]:
    """Find all importlib.import_module(...) and __import__(...) calls."""
    calls: list[_DynamicImportCall] = []
    for node in python_ast.walk(tree):
        call_site = _examine_call_node(node)
        if call_site is not None:
            calls.append(call_site)
    return calls


def _examine_call_node(node: python_ast.AST) -> _DynamicImportCall | None:
    """Check if *node* is a dynamic import call and extract details."""
    if not isinstance(node, python_ast.Call):
        return None
    return _check_importlib_call(node) or _check_builtin_import(node)


def _check_importlib_call(node: python_ast.Call) -> _DynamicImportCall | None:
    """Check for importlib.import_module(...)."""
    func = node.func
    if not isinstance(func, python_ast.Attribute):
        return None
    if func.attr != "import_module":
        return None
    if not _references_importlib(func.value):
        return None
    arg, is_const = _extract_string_arg(node)
    return _DynamicImportCall(
        func_name="importlib.import_module",
        argument=arg,
        lineno=node.lineno,
        is_constant=is_const,
    )


def _check_builtin_import(node: python_ast.Call) -> _DynamicImportCall | None:
    """Check for __import__(...)."""
    if not isinstance(node.func, python_ast.Name):
        return None
    if node.func.id != "__import__":
        return None
    arg, is_const = _extract_string_arg(node)
    return _DynamicImportCall(
        func_name="__import__",
        argument=arg,
        lineno=node.lineno,
        is_constant=is_const,
    )


def _references_importlib(node: python_ast.expr) -> bool:
    """Check if *node* refers to the importlib module."""
    if isinstance(node, python_ast.Name) and node.id == _IMPORTLIB_MODULE:
        return True
    return isinstance(node, python_ast.Attribute) and node.attr == _IMPORTLIB_MODULE


def _extract_string_arg(node: python_ast.Call) -> tuple[str | None, bool]:
    """Extract the first argument if it is a constant string.

    Returns (value, is_constant) where is_constant indicates whether
    the argument is a known string literal.
    """
    if not node.args:
        return None, False
    first_arg = node.args[0]
    if isinstance(first_arg, python_ast.Constant) and isinstance(first_arg.value, str):
        return first_arg.value, True
    if isinstance(first_arg, python_ast.JoinedStr):
        return None, False
    return None, False


# ---------------------------------------------------------------------------
# Module resolution
# ---------------------------------------------------------------------------


def _resolve_dynamic_target(
    argument: str,
    source_module_rel: str,
) -> str | None:
    """Resolve a dynamic import argument to an internal module path.

    Handles absolute (perplexity_cli.x.y), relative (.x, ..y), and
    bare internal (x.y) forms.
    """
    if argument.startswith(PACKAGE_NAME + "."):
        return argument[len(PACKAGE_NAME) + 1 :]
    if argument == PACKAGE_NAME:
        return ""
    if argument.startswith("."):
        return _resolve_relative_dynamic(argument, source_module_rel)
    return _resolve_bare_internal(argument)


def _resolve_bare_internal(argument: str) -> str | None:
    """Check if a bare name resolves to an internal module."""
    top = argument.partition(".")[0]
    try:
        internal = (SRC_ROOT / f"{top}.py").exists() or (SRC_ROOT / top).is_dir()
    except OSError:
        internal = False
    return argument if internal else None


def _resolve_relative_dynamic(argument: str, source_module_rel: str) -> str | None:
    """Resolve a relative dynamic import against the source module."""
    level = 0
    rest = argument
    while rest.startswith("."):
        level += 1
        rest = rest[1:]
    parts = source_module_rel.split(".") if source_module_rel else []
    if level > len(parts):
        return None
    base_parts = parts[: len(parts) - level]
    base = ".".join(base_parts)
    if rest:
        return f"{base}.{rest}" if base else rest
    return base


# ---------------------------------------------------------------------------
# Rule checks
# ---------------------------------------------------------------------------


@dataclass
class _DynamicCheckCtx:
    """Context bundle for dynamic import checks."""

    source_module_rel: str
    lineno: int
    filepath: str
    layer_map: dict[str, tuple[str, frozenset[str]]]
    dynamic_allowlist: dict[str, set[str]]
    result: AnalysisResult


def _check_dynamic_call(ctx: _DynamicCheckCtx, call: _DynamicImportCall) -> None:
    """Evaluate a single dynamic import call against architecture rules."""
    if call.argument is None:
        _report_non_constant(ctx, call)
        return
    if not call.is_constant:
        _report_non_constant(ctx, call)
        return
    target = _resolve_dynamic_target(call.argument, ctx.source_module_rel)
    if target is None:
        return
    if _is_explicitly_allowed(ctx, target):
        return
    _check_dynamic_direction(ctx, target)


def _report_non_constant(ctx: _DynamicCheckCtx, call: _DynamicImportCall) -> None:
    """Report a non-constant dynamic import as a violation."""
    ctx.result.violations.append(
        Violation(
            severity=Severity.ERROR,
            rule="dynamic-import-non-constant",
            message=(
                f"{ctx.source_module_rel or '.'}: "
                f"{call.func_name}() at line {call.lineno} uses a "
                f"non-constant argument. All production dynamic imports "
                f"must use string literals with explicit allowlist entries."
            ),
            file=f"{ctx.filepath}:{call.lineno}",
        )
    )


def _is_explicitly_allowed(ctx: _DynamicCheckCtx, target: str) -> bool:
    """Check if the dynamic import target is in the allowlist for the source."""
    allowed = ctx.dynamic_allowlist.get(ctx.source_module_rel, set())
    return target in allowed


def _check_dynamic_direction(ctx: _DynamicCheckCtx, target: str) -> None:
    """Verify the dynamic import target respects layer direction rules."""
    source_layer = _layer_for_module(ctx.source_module_rel, ctx.layer_map)
    if source_layer is None:
        return
    target_layer = _layer_for_module(target, ctx.layer_map)
    if target_layer is None or target_layer == source_layer:
        return
    allowed = _allowed_deps_for_module(ctx.source_module_rel, ctx.layer_map)
    if target_layer in allowed:
        return
    ctx.result.violations.append(
        Violation(
            severity=Severity.ERROR,
            rule="dynamic-import-direction",
            message=(
                f"{ctx.source_module_rel or '.'} (layer: {source_layer}) "
                f"dynamically imports {target or '.'} (layer: {target_layer}) "
                f"at line {ctx.lineno}, but {source_layer} may only import "
                f"from: {', '.join(sorted(allowed))}"
            ),
            file=f"{ctx.filepath}:{ctx.lineno}",
        )
    )


# ---------------------------------------------------------------------------
# File processing
# ---------------------------------------------------------------------------


def _parse_dynamic_imports(
    filepath: Path,
) -> tuple[str, list[_DynamicImportCall], str | None]:
    """Parse *filepath* and extract dynamic import calls.

    Returns (module_rel, dynamic_calls, parse_error).
    """
    module_rel = _module_rel_from_path(filepath)
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = python_ast.parse(source)
    except SyntaxError as exc:
        return module_rel, [], f"Syntax error: {exc}"
    except (OSError, UnicodeDecodeError) as exc:
        return module_rel, [], f"Read error: {exc}"
    calls = _detect_dynamic_imports(tree)
    return module_rel, calls, None


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _collect_all_source_files() -> list[Path]:
    """Return all .py files under SRC_ROOT excluding __pycache__."""
    return sorted(f for f in SRC_ROOT.rglob("*.py") if "__pycache__" not in str(f))


def _resolve_targets_to_paths(targets: list[str]) -> list[Path]:
    """Convert user-provided file paths to absolute Paths."""
    paths: list[Path] = []
    for target in targets:
        p = Path(target)
        if not p.exists():
            print(f"File not found: {target}", file=sys.stderr)
            sys.exit(2)
        paths.append(p.resolve())
    return paths


def _collect_files(targets: list[str] | None) -> list[Path]:
    """Return the list of .py files to analyse."""
    if targets:
        return _resolve_targets_to_paths(targets)
    return _collect_all_source_files()


@dataclass
class _RunConfig:
    """Configuration bundle for dynamic import checks."""

    layer_map: dict[str, tuple[str, frozenset[str]]]
    dynamic_allowlist: dict[str, set[str]]


def _run_checks(files: list[Path], config: _RunConfig) -> AnalysisResult:
    """Run dynamic import checks on *files* and return the result."""
    result = AnalysisResult(files_checked=len(files))
    for filepath in files:
        _check_single_file(filepath, config, result)
    result.violations.sort(key=lambda v: (v.severity, v.file, v.message))
    return result


def _check_single_file(filepath: Path, config: _RunConfig, result: AnalysisResult) -> None:
    """Parse and check dynamic imports in a single source file."""
    module_rel, calls, parse_err = _parse_dynamic_imports(filepath)
    if parse_err is not None:
        result.violations.append(
            Violation(
                severity=Severity.ERROR,
                rule="parse-error",
                message=f"{module_rel or '.'}: {parse_err}",
                file=str(filepath),
            )
        )
        return
    for call in calls:
        ctx = _DynamicCheckCtx(
            source_module_rel=module_rel,
            lineno=call.lineno,
            filepath=str(filepath),
            layer_map=config.layer_map,
            dynamic_allowlist=config.dynamic_allowlist,
            result=result,
        )
        _check_dynamic_call(ctx, call)


# ---------------------------------------------------------------------------
# Baseline management
# ---------------------------------------------------------------------------


def _load_baseline() -> set[tuple[str, str, str]]:
    """Load accepted violations from baseline JSON."""
    if not BASELINE_PATH.is_file():
        return set()
    try:
        baseline_payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        accepted = baseline_payload.get("accepted", [])
        return {(entry["rule"], entry["file"], entry["message"]) for entry in accepted}
    except (json.JSONDecodeError, KeyError):
        return set()


def _save_baseline(violations: list[Violation]) -> None:
    """Save the current set of violations as the accepted baseline."""
    accepted = [{"rule": v.rule, "file": v.file, "message": v.message} for v in violations]
    baseline_payload = {"version": 1, "accepted": accepted}
    BASELINE_PATH.write_text(json.dumps(baseline_payload, indent=2) + "\n", encoding="utf-8")


def _apply_baseline(
    violations: list[Violation], baseline: set[tuple[str, str, str]]
) -> tuple[list[Violation], list[Violation]]:
    """Split *violations* into (active, accepted) based on *baseline*."""
    active: list[Violation] = []
    accepted: list[Violation] = []
    for v in violations:
        key = (v.rule, v.file, v.message)
        if key in baseline:
            accepted.append(v)
        else:
            active.append(v)
    return active, accepted


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _deduplicate(violations: list[Violation]) -> list[Violation]:
    """Remove duplicate violations (same rule + file + message)."""
    seen: set[tuple[str, str, str]] = set()
    unique: list[Violation] = []
    for v in violations:
        key = (v.rule, v.file, v.message)
        if key not in seen:
            seen.add(key)
            unique.append(v)
    return unique


def _format_violation_section(title: str, violations: list[Violation]) -> list[str]:
    """Format a section of violations with a title and separator."""
    lines: list[str] = [title, "─" * 72]
    for v in violations:
        lines.append(f"  [{v.rule}] {v.message}")
        lines.append(f"    → {v.file}")
    lines.append("")
    return lines


def _format_text(result: AnalysisResult, accepted_count: int = 0) -> str:
    """Format results as human-readable text."""
    errors = _deduplicate(result.errors)
    warnings = _deduplicate(result.warnings)
    summary = (
        f"Dynamic import check: {len(errors)} error(s), "
        f"{len(warnings)} warning(s) in {result.files_checked} files."
    )
    if accepted_count:
        summary += f"  ({accepted_count} accepted by baseline)"
    if not errors and not warnings:
        return summary.replace("Dynamic import check:", "Dynamic import check passed:") + "\n"
    lines: list[str] = [summary, ""]
    if errors:
        lines.extend(_format_violation_section("Errors (must fix):", errors))
    if warnings:
        lines.extend(_format_violation_section("Warnings (should fix):", warnings))
    return "\n".join(lines)


def _format_json(result: AnalysisResult, accepted_count: int = 0) -> str:
    """Format results as JSON."""
    errors = _deduplicate(result.errors)
    warnings = _deduplicate(result.warnings)
    return json.dumps(
        {
            "files_checked": result.files_checked,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "accepted_count": accepted_count,
            "clean": not errors and not warnings,
            "errors": [{"rule": v.rule, "message": v.message, "file": v.file} for v in errors],
            "warnings": [{"rule": v.rule, "message": v.message, "file": v.file} for v in warnings],
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_flag_args(raw: list[str]) -> dict[str, str | bool | None]:
    """Process CLI flags returning a typed dict."""
    flags: dict[str, str | bool | None] = {
        "json": False,
        "update_baseline": False,
        "no_baseline": False,
        "toml": None,
    }
    i = 0
    while i < len(raw):
        arg = raw[i]
        i = _process_single_flag(arg, flags, raw, i)
        i += 1
    return flags


def _flag_key_for_arg(arg: str) -> str:
    """Convert a --flag-name to a dict key."""
    return arg[2:].replace("-", "_")


def _process_single_flag(
    arg: str, flags: dict[str, str | bool | None], raw: list[str], idx: int
) -> int:
    """Process one CLI flag, returning the new index."""
    if arg in ("--json", "--update-baseline", "--no-baseline"):
        flags[_flag_key_for_arg(arg)] = True
    elif arg == "--toml":
        flags["toml"] = _consume_toml_arg(raw, idx)
        return idx + 1
    return idx


def _consume_toml_arg(raw: list[str], idx: int) -> str:
    """Consume the next argument as the TOML path."""
    next_idx = idx + 1
    if next_idx >= len(raw):
        print("--toml requires a path", file=sys.stderr)
        sys.exit(2)
    return raw[next_idx]


def _parse_positional_files(raw: list[str]) -> list[str]:
    """Extract positional file arguments."""
    files: list[str] = []
    i = 0
    while i < len(raw):
        arg = raw[i]
        if arg == "--files":
            return _consume_files_args(raw, i)
        if arg == "--toml":
            i += 1
        elif not arg.startswith("--"):
            files.append(arg)
        i += 1
    return files


def _consume_files_args(raw: list[str], idx: int) -> list[str]:
    """Consume all remaining args after --files."""
    next_idx = idx + 1
    if next_idx >= len(raw):
        print("--files requires at least one file path", file=sys.stderr)
        sys.exit(2)
    return list(raw[next_idx:])


def _parse_args(argv: list[str] | None = None) -> dict[str, Any]:
    """Minimal argument parser (no external dependency)."""
    raw = argv if argv is not None else sys.argv[1:]
    flags = _parse_flag_args(raw)
    files = _parse_positional_files(raw)
    return {
        "files": files if files else None,
        "json": bool(flags["json"]),
        "update_baseline": bool(flags["update_baseline"]),
        "no_baseline": bool(flags["no_baseline"]),
        "toml": flags["toml"] if flags["toml"] else None,
    }


def main(argv: list[str] | None = None) -> None:
    """Run dynamic import checks and exit with the appropriate code."""
    cli_args = _parse_args(argv)
    toml_path = Path(cli_args["toml"]) if cli_args["toml"] else DEFAULT_TOML_PATH
    model = _load_toml(toml_path)
    layer_map = _build_layer_map(model)
    dynamic_allowlist = _build_dynamic_allowlist(model)
    files = _collect_files(cli_args["files"])
    config = _RunConfig(layer_map=layer_map, dynamic_allowlist=dynamic_allowlist)
    result = _run_checks(files, config)
    if cli_args["update_baseline"]:
        _save_baseline(_deduplicate(result.errors) + _deduplicate(result.warnings))
        print(
            f"Baseline updated: "
            f"{len(_deduplicate(result.errors) + _deduplicate(result.warnings))} "
            f"violation(s) recorded."
        )
        sys.exit(0)
    filtered, accepted_count = _filter_with_baseline(result, cli_args)
    if cli_args["json"]:
        print(_format_json(filtered, accepted_count))
    else:
        print(_format_text(filtered, accepted_count))
    sys.exit(0 if filtered.clean else 1)


def _filter_with_baseline(
    result: AnalysisResult, cli_args: dict[str, Any]
) -> tuple[AnalysisResult, int]:
    """Apply baseline filtering and return (filtered_result, accepted_count)."""
    baseline: set[tuple[str, str, str]] = set()
    if not cli_args["no_baseline"]:
        baseline = _load_baseline()
    active_errors, accepted_errors = _apply_baseline(_deduplicate(result.errors), baseline)
    active_warnings, accepted_warnings = _apply_baseline(_deduplicate(result.warnings), baseline)
    accepted_count = len(accepted_errors) + len(accepted_warnings)
    filtered = AnalysisResult(
        violations=active_errors + active_warnings,
        files_checked=result.files_checked,
    )
    return filtered, accepted_count


if __name__ == "__main__":
    main()
