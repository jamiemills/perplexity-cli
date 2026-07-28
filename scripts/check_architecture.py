"""Architecture fitness checks using quality/architecture.toml as the sole
classification source. Uses scripts/import_graph.py for the shared Grimp
import graph.

Checks enforced
--------------
1. **Import direction**: every module-level, function-local, and TYPE_CHECKING
   import must respect TOML-directed allowed_deps rules.
2. **Framework isolation**: domain, ports, application, and shared_pure layers
   must not import framework libraries (click, rich, httpx, etc.).
3. **Adapter independence**: adapter groups declared in TOML must not import
   from unapproved sibling adapter groups.
4. **Complete classification**: any production module not listed in the TOML
   causes an error.

Usage
-----
    python scripts/check_architecture.py                     # full codebase (baseline applied)
    python scripts/check_architecture.py --files a.py b.py   # specific files
    python scripts/check_architecture.py --json              # machine-readable output
    python scripts/check_architecture.py --explain           # explain the layer model
    python scripts/check_architecture.py --no-baseline       # show all violations (ignore baseline)
    python scripts/check_architecture.py --update-baseline   # record current violations as accepted
    python scripts/check_architecture.py --toml custom.toml  # use a custom TOML file
"""

from __future__ import annotations

import ast as python_ast
import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src" / "perplexity_cli"
DEFAULT_TOML_PATH = PROJECT_ROOT / "quality" / "architecture.toml"
BASELINE_PATH = PROJECT_ROOT / ".architecture-baseline.json"
PACKAGE_NAME = "perplexity_cli"

FRAMEWORK_PACKAGES = frozenset(
    {
        "click",
        "rich",
        "httpx",
        "curl_cffi",
        "websockets",
        "mcp",
        "cryptography",
        "tenacity",
    }
)

RESTRICTED_FRAMEWORK_LAYERS = frozenset(
    {
        "shared_pure",
        "domain",
        "ports",
        "application",
    }
)


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
# TOML loading & layer-map construction
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


def _build_adapter_groups(model: dict[str, Any]) -> dict[str, tuple[str, frozenset[str]]]:
    """Build module_rel -> (group_name, frozenset(may_import_from_group_names))."""
    groups: dict[str, tuple[str, frozenset[str]]] = {}
    for group in model.get("adapter_independence", []):
        gname = group.get("name", "")
        may_from = frozenset(group.get("may_import_from", []))
        for mod in group.get("modules", []):
            if isinstance(mod, str):
                groups[mod] = (gname, may_from)
    return groups


def _collect_production_modules() -> set[str]:
    """Return all relative module paths from the source tree."""
    modules: set[str] = set()
    for pyfile in sorted(SRC_ROOT.rglob("*.py")):
        if "__pycache__" in str(pyfile):
            continue
        rel = pyfile.relative_to(SRC_ROOT)
        if rel.name == "__init__.py":
            modules.add("" if str(rel.parent) == "." else str(rel.parent).replace("/", "."))
        else:
            modules.add(str(rel.with_suffix("")).replace("/", "."))
    return modules


# ---------------------------------------------------------------------------
# Layer assignment helpers
# ---------------------------------------------------------------------------


def _layer_for_module(
    module_rel: str, layer_map: dict[str, tuple[str, frozenset[str]]]
) -> str | None:
    """Return the layer name for *module_rel*, exact match first then prefix-fallback."""
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
# AST import extraction
# ---------------------------------------------------------------------------


def _module_rel_from_path(filepath: Path) -> str:
    """Convert a source file path to a dotted relative module name."""
    rel = filepath.relative_to(SRC_ROOT)
    if rel.name == "__init__.py":
        pkg = str(rel.parent)
        return "" if pkg == "." else pkg.replace("/", ".")
    return str(rel.with_suffix("")).replace("/", ".")


def _find_type_checking_lines(tree: python_ast.AST) -> set[int]:
    """Return line numbers inside ``if TYPE_CHECKING:`` blocks."""
    tc_lines: set[int] = set()
    for node in python_ast.walk(tree):
        if not isinstance(node, python_ast.If):
            continue
        if not _is_type_checking_test(node.test):
            continue
        if node.end_lineno is not None:
            tc_lines.update(range(node.lineno, node.end_lineno + 1))
    return tc_lines


def _find_function_body_lines(tree: python_ast.AST) -> set[int]:
    """Return line numbers inside function / method bodies."""
    func_lines: set[int] = set()
    for node in python_ast.walk(tree):
        if not isinstance(node, (python_ast.FunctionDef, python_ast.AsyncFunctionDef)):
            continue
        if node.end_lineno is not None and node.body:
            func_lines.update(range(node.body[0].lineno, node.end_lineno + 1))
    return func_lines


def _is_type_checking_test(test: python_ast.expr) -> bool:
    """Return True if *test* resolves to ``TYPE_CHECKING``."""
    if isinstance(test, python_ast.Name) and test.id == "TYPE_CHECKING":
        return True
    return isinstance(test, python_ast.Attribute) and test.attr == "TYPE_CHECKING"


def _import_node_entries(
    node: python_ast.Import | python_ast.ImportFrom,
) -> list[tuple[str, str | None]]:
    """Return (module, name) for every import carried by *node*.

    Relative imports are returned with their leading dots preserved
    (e.g. ``.bar`` for ``from .bar import baz``).
    """
    if isinstance(node, python_ast.Import):
        return [(a.name, None) for a in node.names]
    if node.module is not None:
        dots = "." * (node.level or 0)
        full = dots + node.module
        return [(full, a.name) for a in node.names]
    return []


def _resolve_relative_import(
    module: str | None,
    source_module_rel: str,
) -> str:
    """Resolve a relative import-level to its absolute dotted form."""
    if module is None or not module.startswith("."):
        return module or ""
    level, rest = _split_relative_level(module)
    parts = source_module_rel.split(".") if source_module_rel else []
    if level > len(parts):
        return module
    base = _build_relative_base(parts, level)
    if base and rest:
        return f"{base}.{rest}"
    return rest if rest else base


def _build_relative_base(parts: list[str], level: int) -> str:
    """Build the absolute base path from source parts and relative level."""
    base_parts = parts[: len(parts) - level]
    return ".".join(base_parts)


def _split_relative_level(module: str) -> tuple[int, str]:
    """Return (dot_count, remainder) from a relative import string."""
    level = 0
    rest = module
    while rest.startswith("."):
        level += 1
        rest = rest[1:]
    return level, rest


def _parse_file_imports(
    filepath: Path,
) -> tuple[
    str,
    list[tuple[str, str | None, int]],
    list[tuple[str, str | None, int]],
    list[tuple[str, str | None, int]],
    str | None,
]:
    """Parse *filepath*; return (module_rel, ml, fl, tc, parse_error)."""
    module_rel = _module_rel_from_path(filepath)
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = python_ast.parse(source)
    except SyntaxError as exc:
        return module_rel, [], [], [], f"Syntax error: {exc}"
    except (OSError, UnicodeDecodeError) as exc:
        return module_rel, [], [], [], f"Read error: {exc}"
    tc_lines = _find_type_checking_lines(tree)
    func_lines = _find_function_body_lines(tree)
    ml, fl, tc_data = _collect_all_imports(tree, tc_lines, func_lines)
    return module_rel, ml, fl, tc_data, None


@dataclass
class _ImportCategoryLists:
    """Holder for the three import category lists."""

    ml: list[tuple[str, str | None, int]]
    fl: list[tuple[str, str | None, int]]
    tc: list[tuple[str, str | None, int]]


def _collect_all_imports(
    tree: python_ast.AST,
    tc_lines: set[int],
    func_lines: set[int],
) -> tuple[
    list[tuple[str, str | None, int]],
    list[tuple[str, str | None, int]],
    list[tuple[str, str | None, int]],
]:
    """Collect all imports from the AST, categorised by location."""
    cats = _ImportCategoryLists(ml=[], fl=[], tc=[])
    for node in python_ast.walk(tree):
        if not isinstance(node, (python_ast.Import, python_ast.ImportFrom)):
            continue
        lineno = node.lineno
        if lineno == 0:
            continue
        entries = _import_node_entries(node)
        for mod, name in entries:
            _add_entry_to_category((mod, name, lineno), tc_lines, func_lines, cats)
    return cats.ml, cats.fl, cats.tc


def _add_entry_to_category(
    entry: tuple[str, str | None, int],
    tc_lines: set[int],
    func_lines: set[int],
    cats: _ImportCategoryLists,
) -> None:
    """Append an import entry to the correct category list."""
    lineno = entry[2]
    if lineno in tc_lines:
        cats.tc.append(entry)
    elif lineno in func_lines:
        cats.fl.append(entry)
    else:
        cats.ml.append(entry)


# ---------------------------------------------------------------------------
# Internal import resolution
# ---------------------------------------------------------------------------


def _resolve_internal_target(
    module_str: str,
    name: str | None,
    source_module_rel: str,
) -> str | None:
    """Resolve an AST import entry to an internal module path (relative to package root).

    Returns the relative module path if internal, or None if external.
    """
    resolved = _resolve_relative_import(module_str, source_module_rel)
    if name == "*":
        return None
    if resolved.startswith(PACKAGE_NAME + "."):
        return resolved[len(PACKAGE_NAME) + 1 :]
    if resolved == PACKAGE_NAME:
        return ""
    if _top_level_is_internal(resolved):
        return resolved
    return None


def _top_level_is_internal(resolved: str) -> bool:
    """Check if a resolved top-level name exists in the source tree."""
    top = resolved.partition(".")[0]
    try:
        return (SRC_ROOT / f"{top}.py").exists() or (SRC_ROOT / top).is_dir()
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Rule checks
# ---------------------------------------------------------------------------


@dataclass
class _ImportCheckCtx:
    """Context bundle for import rule checks to keep parameter count <= 4."""

    source_module_rel: str
    lineno: int
    filepath: str
    location: str
    layer_map: dict[str, tuple[str, frozenset[str]]]
    adapter_groups: dict[str, tuple[str, frozenset[str]]]
    result: AnalysisResult


def _check_import_direction(ctx: _ImportCheckCtx, target_module_rel: str) -> None:
    """Verify that the source module is allowed to import the target module's layer."""
    source_layer = _layer_for_module(ctx.source_module_rel, ctx.layer_map)
    if source_layer is None:
        return
    target_layer = _layer_for_module(target_module_rel, ctx.layer_map)
    if target_layer is None or target_layer == source_layer:
        return
    allowed = _allowed_deps_for_module(ctx.source_module_rel, ctx.layer_map)
    if target_layer in allowed:
        return
    ctx.result.violations.append(
        Violation(
            severity=Severity.ERROR,
            rule="import-direction",
            message=(
                f"{ctx.source_module_rel or '.'} (layer: {source_layer}) imports "
                f"{target_module_rel or '.'} (layer: {target_layer}) "
                f"[{ctx.location}], but {source_layer} may only import from: "
                f"{', '.join(sorted(allowed))}"
            ),
            file=f"{ctx.filepath}:{ctx.lineno}",
        )
    )


def _check_framework_isolation(ctx: _ImportCheckCtx, imported_package: str) -> None:
    """Verify that the source module's layer permits *imported_package*."""
    source_layer = _layer_for_module(ctx.source_module_rel, ctx.layer_map)
    if source_layer is None or source_layer not in RESTRICTED_FRAMEWORK_LAYERS:
        return
    top_level = imported_package.partition(".")[0]
    if top_level in FRAMEWORK_PACKAGES:
        ctx.result.violations.append(
            Violation(
                severity=Severity.ERROR,
                rule="framework-isolation",
                message=(
                    f"{ctx.source_module_rel or '.'} (layer: {source_layer}) imports "
                    f"'{top_level}' [{ctx.location}], but {source_layer} must not "
                    f"depend on framework libraries"
                ),
                file=f"{ctx.filepath}:{ctx.lineno}",
            )
        )


def _check_adapter_independence(ctx: _ImportCheckCtx, target_module_rel: str) -> None:
    """Warn when one adapter group imports from another without permission."""
    if ctx.source_module_rel == target_module_rel:
        return
    src_info = ctx.adapter_groups.get(ctx.source_module_rel)
    tgt_info = ctx.adapter_groups.get(target_module_rel)
    if src_info is None or tgt_info is None:
        return
    src_group, src_may = src_info
    tgt_group, _ = tgt_info
    if src_group == tgt_group or tgt_group in src_may:
        return
    ctx.result.violations.append(
        Violation(
            severity=Severity.WARNING,
            rule="adapter-independence",
            message=(
                f"{ctx.source_module_rel or '.'} (adapter group: {src_group}) imports "
                f"{target_module_rel or '.'} (adapter group: {tgt_group}). "
                f"Adapter groups should remain independent; "
                f"'{src_group}' may import from: {', '.join(sorted(src_may)) or 'none'}"
            ),
            file=f"{ctx.filepath}:{ctx.lineno}",
        )
    )


# ---------------------------------------------------------------------------
# Module classification check
# ---------------------------------------------------------------------------


def _check_classification_completeness(
    layer_map: dict[str, tuple[str, frozenset[str]]],
    result: AnalysisResult,
) -> None:
    """Fail when any production module is not assigned to a layer."""
    all_modules = _collect_production_modules()
    for mod in sorted(all_modules):
        if _layer_for_module(mod, layer_map) is None:
            result.violations.append(
                Violation(
                    severity=Severity.ERROR,
                    rule="unclassified-module",
                    message=f"Production module '{mod or '.'}' has no layer assignment",
                    file="<classification>",
                )
            )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _resolve_targets_to_paths(targets: list[str]) -> list[Path]:
    """Convert user-provided file paths to absolute Paths, exiting on missing."""
    paths: list[Path] = []
    for target in targets:
        p = Path(target)
        if not p.exists():
            print(f"File not found: {target}", file=sys.stderr)
            sys.exit(2)
        paths.append(p.resolve())
    return paths


def _collect_all_source_files() -> list[Path]:
    """Return all .py files under SRC_ROOT excluding __pycache__."""
    return sorted(f for f in SRC_ROOT.rglob("*.py") if "__pycache__" not in str(f))


def _collect_files(targets: list[str] | None) -> list[Path]:
    """Return the list of .py files to analyse."""
    if targets:
        return _resolve_targets_to_paths(targets)
    return _collect_all_source_files()


@dataclass
class _RunConfig:
    """Configuration bundle for _run_checks to limit parameters."""

    layer_map: dict[str, tuple[str, frozenset[str]]]
    adapter_groups: dict[str, tuple[str, frozenset[str]]]


def _run_checks(files: list[Path], config: _RunConfig) -> AnalysisResult:
    """Run all architecture checks on *files* and return the result."""
    result = AnalysisResult(files_checked=len(files))
    _check_classification_completeness(config.layer_map, result)
    for filepath in files:
        _check_single_file(filepath, config, result)
    result.violations.sort(key=lambda v: (v.severity, v.file, v.message))
    return result


def _check_single_file(filepath: Path, config: _RunConfig, result: AnalysisResult) -> None:
    """Parse and check a single source file."""
    module_rel, ml, fl, tc, parse_err = _parse_file_imports(filepath)
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
    batch_ctx = _ImportEntryCtx(
        module_rel=module_rel,
        filepath=filepath,
        config=config,
        result=result,
    )
    _check_import_entries(batch_ctx, ml, "module-level")
    _check_import_entries(batch_ctx, fl, "function-local")
    _check_import_entries(batch_ctx, tc, "TYPE_CHECKING")


@dataclass
class _ImportEntryCtx:
    """Context for processing a batch of import entries."""

    module_rel: str
    filepath: Path
    config: _RunConfig
    result: AnalysisResult


def _check_import_entries(
    batch_ctx: _ImportEntryCtx,
    entries: list[tuple[str, str | None, int]],
    location: str,
) -> None:
    """Process a list of import entries, checking each against rules."""
    for module_str, name, lineno in entries:
        ctx = _ImportCheckCtx(
            source_module_rel=batch_ctx.module_rel,
            lineno=lineno,
            filepath=str(batch_ctx.filepath),
            location=location,
            layer_map=batch_ctx.config.layer_map,
            adapter_groups=batch_ctx.config.adapter_groups,
            result=batch_ctx.result,
        )
        _check_single_import_entry(ctx, module_str, name, batch_ctx.module_rel)


def _check_single_import_entry(
    ctx: _ImportCheckCtx,
    module_str: str,
    name: str | None,
    module_rel: str,
) -> None:
    """Check a single import entry against architecture rules."""
    internal_target = _resolve_internal_target(module_str, name, module_rel)
    if internal_target is not None:
        _check_import_direction(ctx, internal_target)
        _check_adapter_independence(ctx, internal_target)
    else:
        _check_framework_isolation(ctx, module_str or (name or ""))


# ---------------------------------------------------------------------------
# Baseline management
# ---------------------------------------------------------------------------


def _load_baseline() -> set[tuple[str, str, str]]:
    """Load accepted violations from .architecture-baseline.json."""
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
        f"Architecture check: {len(errors)} error(s), "
        f"{len(warnings)} warning(s) in {result.files_checked} files."
    )
    if accepted_count:
        summary += f"  ({accepted_count} accepted by baseline)"
    if not errors and not warnings:
        return summary.replace("Architecture check:", "Architecture check passed:") + "\n"
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


def _print_layer_model(layer_map: dict[str, tuple[str, frozenset[str]]]) -> None:
    """Print the layer model for human inspection."""
    print("Architecture Layer Model (from quality/architecture.toml)\n")
    grouped: dict[str, tuple[list[str], frozenset[str]]] = {}
    for mod, (lname, deps) in layer_map.items():
        if lname not in grouped:
            grouped[lname] = ([], deps)
        grouped[lname][0].append(mod)
    for lname in sorted(grouped.keys()):
        mods, deps = grouped[lname]
        print(f"  [{lname}]")
        print(f"    Modules:     {', '.join(sorted(mods))}")
        print(f"    May import:  {', '.join(sorted(deps))}")
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_flag_args(raw: list[str]) -> dict[str, str | bool | None]:
    """Process CLI flags returning a typed dict."""
    flags: dict[str, str | bool | None] = {
        "json": False,
        "explain": False,
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
    if arg in ("--json", "--explain", "--update-baseline", "--no-baseline"):
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
        "explain": bool(flags["explain"]),
        "update_baseline": bool(flags["update_baseline"]),
        "no_baseline": bool(flags["no_baseline"]),
        "toml": flags["toml"] if flags["toml"] else None,
    }


def main(argv: list[str] | None = None) -> None:
    """Run architecture checks and exit with the appropriate code."""
    cli_args = _parse_args(argv)
    toml_path = Path(cli_args["toml"]) if cli_args["toml"] else DEFAULT_TOML_PATH
    model = _load_toml(toml_path)
    layer_map = _build_layer_map(model)
    adapter_groups = _build_adapter_groups(model)
    if cli_args["explain"]:
        _print_layer_model(layer_map)
        sys.exit(0)
    files = _collect_files(cli_args["files"])
    config = _RunConfig(layer_map=layer_map, adapter_groups=adapter_groups)
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
