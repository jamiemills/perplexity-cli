"""Shared import graph adapter using Grimp (from import-linter).

Resolves absolute and relative imports, includes __init__.py module imports,
captures function-local imports (separately categorised), captures
TYPE_CHECKING imports as dependencies, returns deterministic module/edge
ordering, and fails on syntax/read errors with distinct exit codes.

Exit codes:
    0 — success
    1 — general failure / import resolution error
    2 — syntax error in a source file
    3 — file read error
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any, Protocol, cast

import grimp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
PACKAGE_NAME = "perplexity_cli"

_EXIT_SYNTAX_ERROR = 2
_EXIT_READ_ERROR = 3
_DEFAULT_EDGE_LIMIT = 50


class ImportGraphError(Exception):
    """Base exception for import graph errors."""


class SyntaxErrorInSource(ImportGraphError):
    """A source file has a syntax error."""


class FileReadError(ImportGraphError):
    """A source file could not be read."""


class _GrimpApi(Protocol):
    def build_graph(self, package_name: str, *, cache_dir: str | None) -> grimp.ImportGraph: ...


# ---------------------------------------------------------------------------
# Grimp graph builder
# ---------------------------------------------------------------------------


def _build_import_graph() -> grimp.ImportGraph:
    """Build and return the Grimp import graph for the project."""
    grimp_api = cast(_GrimpApi, grimp)
    return grimp_api.build_graph(str(PACKAGE_NAME), cache_dir=None)


# ---------------------------------------------------------------------------
# Source analysis helpers
# ---------------------------------------------------------------------------


def _resolve_source_path(module_name: str) -> Path | None:
    """Resolve a dotted module name to a source file or __init__.py path."""
    rel = module_name.replace(".", "/")
    filepath = SRC_ROOT / f"{rel}.py"
    init_filepath = SRC_ROOT / rel / "__init__.py"
    if filepath.exists():
        return filepath
    if init_filepath.exists():
        return init_filepath
    return None


def _parse_module_source(module_name: str) -> ast.AST:
    """Parse a module's source into an AST.

    Raises:
        SyntaxErrorInSource: If the source has a syntax error.
        FileReadError: If the file cannot be read.
    """
    resolved = _resolve_source_path(module_name)
    if resolved is None:
        raise FileReadError(f"Source file not found for {module_name}")
    try:
        source = resolved.read_text(encoding="utf-8")
        return ast.parse(source)
    except SyntaxError as exc:
        raise SyntaxErrorInSource(f"Syntax error in {module_name}: {exc}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise FileReadError(f"Could not read {module_name}: {exc}") from exc


# ---------------------------------------------------------------------------
# AST line-range helpers
# ---------------------------------------------------------------------------


def _find_type_checking_lines(tree: ast.AST) -> set[int]:
    """Return line numbers inside if TYPE_CHECKING blocks."""
    tc_lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if not _is_type_checking_test(node.test):
            continue
        if node.end_lineno is not None:
            tc_lines.update(range(node.lineno, node.end_lineno + 1))
    return tc_lines


def _find_function_body_lines(tree: ast.AST) -> set[int]:
    """Return line numbers inside function/method bodies."""
    func_lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.end_lineno is not None:
            func_lines.update(range(node.body[0].lineno, node.end_lineno + 1))
    return func_lines


def _is_type_checking_test(test: ast.expr) -> bool:
    """Return True if *test* evaluates to TYPE_CHECKING."""
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


# ---------------------------------------------------------------------------
# Import extraction from AST
# ---------------------------------------------------------------------------


def _strip_package(name: str) -> str:
    """Strip the root package prefix from a fully-qualified import name."""
    prefix = PACKAGE_NAME + "."
    if name.startswith(prefix):
        return name[len(prefix) :]
    return name


def _collect_import_targets(node: ast.AST, imports: set[str]) -> None:
    """Collect internal import targets from an AST node."""
    if isinstance(node, ast.Import):
        _collect_from_import_names(node.names, imports)
    elif isinstance(node, ast.ImportFrom):
        _collect_from_import_from_node(node, imports)


def _collect_from_import_names(aliases: list[ast.alias], imports: set[str]) -> None:
    """Collect imports from ast.Import aliases."""
    for alias in aliases:
        if alias.name.startswith(PACKAGE_NAME):
            imports.add(_strip_package(alias.name))


def _collect_from_import_from_node(node: ast.ImportFrom, imports: set[str]) -> None:
    """Collect imports from an ast.ImportFrom node."""
    if not node.module:
        return
    if not node.module.startswith(PACKAGE_NAME):
        return
    _collect_module_imports(node, imports)


def _collect_module_imports(node: ast.ImportFrom, imports: set[str]) -> None:
    """Collect imports from a dotted import-from node."""
    for alias in node.names:
        full = f"{node.module}.{alias.name}"
        imports.add(_strip_package(full))


def _node_location(node: ast.AST) -> tuple[int, int]:
    """Return the source line and column exposed by an AST node, if any."""
    # owner: quality-infrastructure; reason: heterogeneous ast.AST nodes expose optional location attributes
    line = getattr(node, "lineno", 0)  # nosemgrep: getattr-with-string-literal
    # owner: quality-infrastructure; reason: heterogeneous ast.AST nodes expose optional location attributes
    column = getattr(node, "col_offset", 0)  # nosemgrep: getattr-with-string-literal
    return line, column


def _extract_imports_in_lines(tree: ast.AST, allowed_lines: set[int]) -> set[str]:
    """Extract internal imports from nodes whose lineno falls in *allowed_lines*."""
    imports: set[str] = set()
    for node in ast.walk(tree):
        line, _column = _node_location(node)
        if line not in allowed_lines:
            continue
        _collect_import_targets(node, imports)
    return imports


def _all_module_lines(tree: ast.AST) -> set[int]:
    """Return the set of all lines in the module AST."""
    max_line = _max_ast_line(tree)
    return set(range(1, max_line + 1))


def _max_ast_line(tree: ast.AST) -> int:
    """Find the highest line number in an AST."""
    max_so_far = 0
    for node in ast.walk(tree):
        # owner: quality-infrastructure; reason: heterogeneous ast.AST nodes expose optional location attributes
        end = getattr(node, "end_lineno", 0) or 0  # nosemgrep: getattr-with-string-literal
        line, _column = _node_location(node)
        max_so_far = max(max_so_far, end, line)
    return max_so_far


# ---------------------------------------------------------------------------
# Public API — categorised imports
# ---------------------------------------------------------------------------


def _collect_categorised_imports(module_name: str, category: str) -> set[str]:
    """Collect internal imports of a specific *category*.

    Args:
        module_name: Dotted module name relative to root package.
        category: One of 'module_level', 'function_local', 'type_checking'.

    Returns:
        Set of internal module import targets (stripped of package prefix).

    Raises:
        SyntaxErrorInSource: If the source has a syntax error.
        FileReadError: If the file cannot be read.
    """
    tree = _parse_module_source(module_name)

    if category == "module_level":
        tc_lines = _find_type_checking_lines(tree)
        func_lines = _find_function_body_lines(tree)
        excluded = tc_lines | func_lines
        allowed = _all_module_lines(tree) - excluded
    elif category == "function_local":
        allowed = _find_function_body_lines(tree)
    elif category == "type_checking":
        allowed = _find_type_checking_lines(tree)
    else:
        return set()

    return _extract_imports_in_lines(tree, allowed)


def get_module_level_imports(module_name: str) -> list[str]:
    """Return module-level internal imports (excluding function-local and TYPE_CHECKING).

    Args:
        module_name: Fully-qualified module name.

    Returns:
        Sorted list of internal module targets.

    Raises:
        SyntaxErrorInSource: If a syntax error is found.
        FileReadError: If the file cannot be read.
    """
    return sorted(_collect_categorised_imports(module_name, "module_level"))


def get_function_local_imports(module_name: str) -> list[str]:
    """Return internal imports found inside function/method bodies.

    Args:
        module_name: Fully-qualified module name.

    Returns:
        Sorted list of internal module targets.

    Raises:
        SyntaxErrorInSource: If a syntax error is found.
        FileReadError: If the file cannot be read.
    """
    return sorted(_collect_categorised_imports(module_name, "function_local"))


def get_type_checking_imports(module_name: str) -> list[str]:
    """Return internal imports found inside TYPE_CHECKING blocks.

    Args:
        module_name: Fully-qualified module name.

    Returns:
        Sorted list of internal module targets.

    Raises:
        SyntaxErrorInSource: If a syntax error is found.
        FileReadError: If the file cannot be read.
    """
    return sorted(_collect_categorised_imports(module_name, "type_checking"))


# ---------------------------------------------------------------------------
# Public API — graph queries
# ---------------------------------------------------------------------------


def get_all_module_names() -> list[str]:
    """Return all module names in the package in deterministic order."""
    graph = _build_import_graph()
    return sorted(graph.modules)


def get_direct_imports(module_name: str) -> list[str]:
    """Return the direct imports of a module in deterministic order.

    Includes all imports that Grimp resolves (absolute, relative,
    __init__.py).  Also verifies the module can be parsed.

    Args:
        module_name: Fully-qualified module name.

    Returns:
        Sorted list of module name strings.

    Raises:
        ImportGraphError: On import graph failures.
    """
    graph = _build_import_graph()
    return sorted(graph.find_modules_directly_imported_by(module_name) - {module_name})


def get_all_edges() -> list[tuple[str, str]]:
    """Return all (source, target) import edges in deterministic order."""
    graph = _build_import_graph()
    edges: set[tuple[str, str]] = set()
    for module in graph.modules:
        for target in graph.find_modules_directly_imported_by(module):
            if module != target:
                edges.add((module, target))
    return sorted(edges)


def get_import_graph_summary() -> dict[str, Any]:
    """Return a summary of the import graph for all modules."""
    graph = _build_import_graph()
    result: dict[str, dict[str, list[str]]] = {}
    for module in sorted(graph.modules):
        direct = sorted(graph.find_modules_directly_imported_by(module) - {module})
        result[module] = {"direct_imports": direct}
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_single_module_info(module_name: str) -> None:
    """Print detailed import info for a single module."""
    direct = get_direct_imports(module_name)
    module_level = get_module_level_imports(module_name)
    func_local = get_function_local_imports(module_name)
    tc_imports = get_type_checking_imports(module_name)

    print(f"Module: {module_name}")
    print(f"  Direct imports ({len(direct)}):")
    for imp in direct:
        print(f"    {imp}")
    print(f"  Module-level ({len(module_level)}):")
    for imp in module_level:
        print(f"    {imp}")
    print(f"  Function-local ({len(func_local)}):")
    for imp in func_local:
        print(f"    {imp}")
    print(f"  TYPE_CHECKING ({len(tc_imports)}):")
    for imp in tc_imports:
        print(f"    {imp}")


def _print_full_graph_summary() -> None:
    """Print a summary of the full import graph."""
    graph = _build_import_graph()
    edges = get_all_edges()
    print(f"Total modules: {len(graph.modules)}")
    print(f"Total edges: {len(edges)}")
    for src, tgt in edges[:_DEFAULT_EDGE_LIMIT]:
        print(f"  {src} -> {tgt}")
    if len(edges) > _DEFAULT_EDGE_LIMIT:
        print(f"  ... and {len(edges) - _DEFAULT_EDGE_LIMIT} more edges")


def _handle_import_graph_errors(func: Any, *args: Any) -> int:
    """Call *func* and map any import graph errors to exit codes."""
    try:
        func(*args)
    except SyntaxErrorInSource as exc:
        print(f"SYNTAX ERROR: {exc}", file=sys.stderr)
        return _EXIT_SYNTAX_ERROR
    except FileReadError as exc:
        print(f"READ ERROR: {exc}", file=sys.stderr)
        return _EXIT_READ_ERROR
    except ImportGraphError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point — build and verify the import graph."""
    args = argv if argv is not None else sys.argv[1:]
    module_filter = args[0] if args else None

    def _run() -> None:
        if module_filter:
            _print_single_module_info(module_filter)
        else:
            _print_full_graph_summary()

    return _handle_import_graph_errors(_run)


if __name__ == "__main__":
    sys.exit(main())
