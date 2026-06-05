"""Architecture fitness checks: layer boundaries, import direction, framework leaks.

Designed to be run before a large change begins (once a plan is agreed) or
as part of CI to catch architecture drift.  Operates on the current codebase
by default, but can focus on specific files via ``--files`` for pre-change
analysis of proposed new modules.

Rules enforced
--------------
1. **Import direction**: each layer may only import from its declared allowed
   layers.  Violations are ERROR severity.
2. **Framework isolation**: domain and application layers must not import
   framework libraries (click, rich, httpx, etc.).  Violations are ERROR.
3. **Inter-adapter coupling**: infrastructure modules should be independent --
   one adapter importing from another is a WARNING unless explicitly allowed.
4. **Utility isolation**: utils/ modules must not import from api/, auth/,
   threads/, formatting/, runners/, services/.  Violations are WARNING.

Usage
-----
    python scripts/check_architecture.py                     # full codebase (baseline applied)
    python scripts/check_architecture.py --files a.py b.py   # specific files
    python scripts/check_architecture.py --json              # machine-readable output
    python scripts/check_architecture.py --explain           # explain the layer model
    python scripts/check_architecture.py --no-baseline       # show all violations (ignore baseline)
    python scripts/check_architecture.py --update-baseline   # record current violations as accepted

Layer model
-----------
The project follows a ports-and-adapters (hexagonal) architecture:

  domain/       Core business objects and rules.  No framework imports.
                Modules: envelope, exit_codes, config/models, models/

  application/  Use cases and orchestration.  Depends on domain + utils.
                Modules: services/, runners/, query_runner

  infrastructure/  Adapters for external systems (HTTP, auth, file I/O).
                Modules: api/, auth/, attachments/, threads/, utils/

  presentation/  User interface and CLI machinery.
                Modules: cli, commands, command_runner, formatting/,
                error_handler, help_json, mcp_server, ndjson, session_log
"""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src" / "perplexity_cli"
BASELINE_PATH = PROJECT_ROOT / ".architecture-baseline.json"

# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


# ---------------------------------------------------------------------------
# Layer definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LayerRule:
    """A named architectural layer with its constituent modules and constraints."""

    name: str
    description: str

    # Module prefixes that belong to this layer (e.g. "api", "auth.utils").
    # A file matches if its import path starts with any prefix.
    modules: tuple[str, ...]

    # Layers this layer is allowed to import from (by layer name).
    allowed_imports_from: tuple[str, ...]

    # Framework packages forbidden in this layer (top-level package names).
    forbidden_frameworks: tuple[str, ...] = ()


# The ordered layers.  Rules are evaluated top-to-bottom; the first match wins.
LAYERS: tuple[LayerRule, ...] = (
    LayerRule(
        name="domain",
        description="Core business objects and rules — no framework imports",
        modules=(
            "envelope",
            "exit_codes",
            "config.models",
            "config.defaults",
            "models",
            "ndjson",
        ),
        allowed_imports_from=("domain",),
        forbidden_frameworks=(
            "click",
            "rich",
            "httpx",
            "curl_cffi",
            "websockets",
            "mcp",
            "cryptography",
            "tenacity",
        ),
    ),
    LayerRule(
        name="application",
        description="Use cases and orchestration — depends on domain + utils",
        modules=(
            "services",
            "runners",
            "query_runner",
        ),
        allowed_imports_from=("domain", "application", "infrastructure"),
        forbidden_frameworks=(
            "click",
            "rich",
            "httpx",
            "curl_cffi",
            "websockets",
            "mcp",
            "cryptography",
            "tenacity",
        ),
    ),
    LayerRule(
        name="infrastructure",
        description="Adapters for external systems (HTTP, auth, file I/O, threads)",
        modules=(
            "api",
            "auth",
            "attachments",
            "threads",
            "utils",
            "config",  # config/ module is infrastructure plumbing
        ),
        allowed_imports_from=("domain", "infrastructure"),
        # Infrastructure is allowed to import frameworks — that's its job.
    ),
    LayerRule(
        name="presentation",
        description="User interface and CLI machinery — depends on everything",
        modules=(
            "cli",
            "commands",
            "command_runner",
            "formatting",
            "error_handler",
            "help_json",
            "session_log",
            "mcp_server",
        ),
        allowed_imports_from=(
            "domain",
            "application",
            "infrastructure",
            "presentation",
        ),
    ),
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Violation:
    """A single architecture rule violation."""

    severity: Severity
    rule: str
    message: str
    file: str


@dataclass
class AnalysisResult:
    """Aggregated results of an architecture check run."""

    violations: list[Violation] = field(default_factory=list)
    files_checked: int = 0

    @property
    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == Severity.WARNING]

    @property
    def clean(self) -> bool:
        return len(self.errors) == 0 and (len(self.warnings) == 0)


# ---------------------------------------------------------------------------
# Layer assignment
# ---------------------------------------------------------------------------


def _assign_layer(module: str) -> LayerRule | None:
    """Return the LayerRule that *module* belongs to, or None if no match."""
    for layer in LAYERS:
        for prefix in layer.modules:
            if module == prefix or module.startswith(prefix + "."):
                return layer
    return None


def _target_layer(imported_module: str) -> str:
    """Return the layer name of the imported module, or 'external'."""
    layer = _assign_layer(imported_module)
    return layer.name if layer else "external"


# ---------------------------------------------------------------------------
# AST extraction
# ---------------------------------------------------------------------------


def _module_name_from_path(filepath: Path) -> str:
    """Derive the dotted module name from a file path relative to SRC_ROOT."""
    return str(filepath.relative_to(SRC_ROOT).with_suffix("")).replace("/", ".")


def _parse_source(filepath: Path) -> ast.AST | None:
    """Parse *filepath* into an AST, returning None on failure."""
    try:
        source = filepath.read_text(encoding="utf-8")
        return ast.parse(source)
    except Exception:
        return None


def _collect_import_nodes(tree: ast.AST) -> list[tuple[str, str | None, str]]:
    """Walk *tree* and return [(imported_module, name, lineno)] for every import."""
    imports: list[tuple[str, str | None, str]] = []

    for node in ast.walk(tree):
        _add_import_if_applicable(node, imports)

    return imports


def _import_entries(node: ast.Import) -> list[tuple[str, None, str]]:
    return [(a.name, None, str(node.lineno)) for a in node.names]


def _import_from_entries(node: ast.ImportFrom) -> list[tuple[str, str, str]]:
    module = node.module
    if module is None:
        return []
    return [(module, a.name, str(node.lineno)) for a in node.names]


def _add_import_if_applicable(node: ast.AST, imports: list[tuple[str, str | None, str]]) -> None:
    if isinstance(node, ast.Import):
        imports.extend(_import_entries(node))
    elif isinstance(node, ast.ImportFrom) and node.module is not None:
        imports.extend(_import_from_entries(node))


def _extract_imports(filepath: Path) -> tuple[str, list[tuple[str, str | None, str]]]:
    """Parse *filepath* and return (module_name, [(imported_module, name, lineno)])."""
    module_name = _module_name_from_path(filepath)
    tree = _parse_source(filepath)
    if tree is None:
        return module_name, []

    imports = _collect_import_nodes(tree)
    return module_name, imports


# ---------------------------------------------------------------------------
# Rule checks
# ---------------------------------------------------------------------------


def _check_import_direction(
    module: str,
    imported_module: str,
    lineno: str,
    filepath: str,
    result: AnalysisResult,
) -> None:
    """Verify that *module* is allowed to import from *imported_module*'s layer."""
    source_layer = _assign_layer(module)
    if source_layer is None:
        return  # Unknown/top-level module — skip

    target_name = _target_layer(imported_module)
    if target_name == "external":
        return  # External package — checked separately by framework rules

    if target_name not in source_layer.allowed_imports_from:
        result.violations.append(
            Violation(
                severity=Severity.ERROR,
                rule="import-direction",
                message=(
                    f"{module} (layer: {source_layer.name}) imports "
                    f"{imported_module} (layer: {target_name}), "
                    f"but {source_layer.name} may only import from: "
                    f"{', '.join(source_layer.allowed_imports_from)}"
                ),
                file=f"{filepath}:{lineno}",
            )
        )


def _check_framework_isolation(
    module: str,
    imported_package: str,
    lineno: str,
    filepath: str,
    result: AnalysisResult,
) -> None:
    """Verify that *module*'s layer permits *imported_package*."""
    source_layer = _assign_layer(module)
    if source_layer is None:
        return

    top_level = imported_package.split(".")[0]
    if top_level in source_layer.forbidden_frameworks:
        result.violations.append(
            Violation(
                severity=Severity.ERROR,
                rule="framework-isolation",
                message=(
                    f"{module} (layer: {source_layer.name}) imports "
                    f"'{top_level}', but {source_layer.name} must not depend on "
                    "framework libraries"
                ),
                file=f"{filepath}:{lineno}",
            )
        )


_ADAPTER_LAYERS = frozenset({"infrastructure"})

# Pairs of infrastructure sub-modules where cross-imports are expected
# (because they form a cohesive unit or share internal utilities).
_ALLOWED_INFRA_COUPLING: set[tuple[str, str]] = {
    ("api", "auth"),  # api/client.py needs AuthContext
    ("api", "utils"),  # api uses utils for headers, cookies, retry
    ("auth", "utils"),  # auth uses utils for encryption, config
    ("threads", "utils"),  # threads uses utils for rate limiting, config
    ("attachments", "utils"),  # attachments uses utils for config, file handling
    ("attachments", "api"),  # attachments delegates upload to api
    ("config", "utils"),  # config module uses utils for config management
}


def _is_infra_layer(module_name: str) -> bool:
    """Return True if *module_name* belongs to the infrastructure layer."""
    layer = _assign_layer(module_name)
    return layer is not None and layer.name in _ADAPTER_LAYERS


def _top_level_group(module_name: str) -> str:
    """Return the first component of a dotted module name."""
    return module_name.split(".")[0]


def _is_allowed_infra_coupling(src_group: str, tgt_group: str) -> bool:
    """Return True if cross-import between these infra groups is expected."""
    return src_group == tgt_group or (src_group, tgt_group) in _ALLOWED_INFRA_COUPLING


def _check_adapter_independence(
    module: str,
    imported_module: str,
    lineno: str,
    filepath: str,
    result: AnalysisResult,
) -> None:
    """Warn when one adapter imports from another adapter's internals."""
    if not _is_infra_layer(module) or not _is_infra_layer(imported_module):
        return

    src_group = _top_level_group(module)
    tgt_group = _top_level_group(imported_module)

    if _is_allowed_infra_coupling(src_group, tgt_group):
        return

    result.violations.append(
        Violation(
            severity=Severity.WARNING,
            rule="adapter-independence",
            message=(
                f"{module} (infra: {src_group}) imports {imported_module} "
                f"(infra: {tgt_group}).  Infrastructure adapters should be "
                f"independent; consider extracting shared code to a port "
                f"or a dedicated shared-kernel module."
            ),
            file=f"{filepath}:{lineno}",
        )
    )


# ---------------------------------------------------------------------------
# Baseline management (known-accepted violations)
# ---------------------------------------------------------------------------


def _load_baseline() -> set[tuple[str, str, str]]:
    """Load accepted violations from .architecture-baseline.json."""
    if not BASELINE_PATH.is_file():
        return set()
    try:
        data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        accepted = data.get("accepted", [])
        return {(entry["rule"], entry["file"], entry["message"]) for entry in accepted}
    except (json.JSONDecodeError, KeyError):
        return set()


def _save_baseline(violations: list[Violation]) -> None:
    """Save the current set of violations as the accepted baseline."""
    accepted = [{"rule": v.rule, "file": v.file, "message": v.message} for v in violations]
    data = {"version": 1, "accepted": accepted}
    BASELINE_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


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
# Orchestration
# ---------------------------------------------------------------------------


def _resolve_targets_to_paths(targets: list[str]) -> list[Path]:
    """Convert user-provided file paths to absolute Paths, exiting on missing."""
    paths: list[Path] = []
    for t in targets:
        p = Path(t)
        if not p.exists():
            print(f"File not found: {t}", file=sys.stderr)
            sys.exit(2)
        paths.append(p.resolve())
    return paths


def _collect_all_source_files() -> list[Path]:
    """Return all .py files under SRC_ROOT, excluding __pycache__ and __init__.py."""
    return sorted(
        f for f in SRC_ROOT.rglob("*.py") if "__pycache__" not in str(f) and f.name != "__init__.py"
    )


def _collect_files(targets: list[str] | None) -> list[Path]:
    """Return the list of .py files to analyse."""
    if targets:
        return _resolve_targets_to_paths(targets)
    return _collect_all_source_files()


def _run_checks(files: list[Path]) -> AnalysisResult:
    """Run all architecture checks on *files* and return the result."""
    result = AnalysisResult(files_checked=len(files))

    for filepath in files:
        module, imports = _extract_imports(filepath)
        if not imports:
            continue

        for imported_module, _name, lineno in imports:
            # Is this an internal import?
            if imported_module.startswith("perplexity_cli."):
                internal_target = imported_module[len("perplexity_cli.") :]
                _check_import_direction(module, internal_target, lineno, str(filepath), result)
                _check_adapter_independence(module, internal_target, lineno, str(filepath), result)
            else:
                # External import — check framework isolation
                _check_framework_isolation(module, imported_module, lineno, str(filepath), result)

    # Sort violations for deterministic output
    result.violations.sort(key=lambda v: (v.severity, v.file, v.message))
    return result


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
            "clean": len(errors) == 0 and len(warnings) == 0,
            "errors": [{"rule": v.rule, "message": v.message, "file": v.file} for v in errors],
            "warnings": [{"rule": v.rule, "message": v.message, "file": v.file} for v in warnings],
        },
        indent=2,
    )


def _print_layer_model() -> None:
    """Print the layer model for human inspection."""
    print("Architecture Layer Model\n")
    print("Layers are evaluated top-to-bottom; first matching module prefix wins.\n")
    for layer in LAYERS:
        print(f"  [{layer.name}]  {layer.description}")
        print(f"    Modules:     {', '.join(layer.modules)}")
        print(f"    May import:  {', '.join(layer.allowed_imports_from)}")
        if layer.forbidden_frameworks:
            print(f"    Forbidden:   {', '.join(layer.forbidden_frameworks)}")
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_flag_args(raw: list[str]) -> dict[str, bool | None]:
    """Process --json, --explain, --files, --update-baseline, --no-baseline flags."""
    flags: dict[str, bool | None] = {
        "json": False,
        "explain": False,
        "files": None,
        "update_baseline": False,
        "no_baseline": False,
    }
    i = 0
    while i < len(raw):
        arg = raw[i]
        if arg == "--json":
            flags["json"] = True
        elif arg == "--explain":
            flags["explain"] = True
        elif arg == "--files":
            flags["files"] = True
        elif arg == "--update-baseline":
            flags["update_baseline"] = True
        elif arg == "--no-baseline":
            flags["no_baseline"] = True
        i += 1
    return flags


def _parse_positional_files(raw: list[str]) -> list[str]:
    """Extract positional file arguments (anything after --files or bare paths)."""
    files: list[str] = []
    i = 0
    while i < len(raw):
        arg = raw[i]
        if arg == "--files":
            i += 1
            if i >= len(raw):
                print("--files requires at least one file path", file=sys.stderr)
                sys.exit(2)
            files.extend(raw[i:])
            break
        elif not arg.startswith("--"):
            files.append(arg)
        i += 1
    return files


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
    }


def main(argv: list[str] | None = None) -> None:
    """Run architecture checks and exit with the appropriate code."""
    cli_args = _parse_args(argv)

    if cli_args["explain"]:
        _print_layer_model()
        sys.exit(0)

    files = _collect_files(cli_args["files"])
    result = _run_checks(files)

    all_violations = _deduplicate(result.errors) + _deduplicate(result.warnings)
    baseline: set[tuple[str, str, str]] = set()

    if cli_args["update_baseline"]:
        _save_baseline(all_violations)
        print(f"Baseline updated: {len(all_violations)} violation(s) recorded.")
        sys.exit(0)

    if not cli_args["no_baseline"]:
        baseline = _load_baseline()

    active_errors, accepted_errors = _apply_baseline(_deduplicate(result.errors), baseline)
    active_warnings, accepted_warnings = _apply_baseline(_deduplicate(result.warnings), baseline)
    accepted_count = len(accepted_errors) + len(accepted_warnings)

    filtered = AnalysisResult(
        violations=active_errors + active_warnings,
        files_checked=result.files_checked,
    )

    if cli_args["json"]:
        print(_format_json(filtered, accepted_count))
    else:
        print(_format_text(filtered, accepted_count))

    sys.exit(0 if filtered.clean else 1)


if __name__ == "__main__":
    main()
