"""Coupling and stability metrics for architecture health.

Uses the shared import graph adapter (scripts/import_graph.py) to
calculate Robert C. Martin's package-level metrics. Findings are advisory
by default; ``--blocking`` fails when the configured flagged-module budget
is exceeded. Graph, parse, read, and configuration errors always fail.

Formulas
--------
    Afferent coupling  Ca = |{modules that import this one}|
    Efferent coupling  Ce = |{modules this one imports}|
    Instability        I  = Ce / (Ca + Ce)    (0 if Ca+Ce=0)
    Abstractness       A  = Na / (Na + Nc)    (0 if no classes)
    Distance           D  = |A + I - 1|

    - Na = abstract classes (classes with @abstractmethod, or ABC/Protocol
      subclasses that are imported or instantiated outside their own module)
    - Nc = concrete classes (all other class definitions)

Usage
-----
    python scripts/check_coupling.py                     # advisory report
    python scripts/check_coupling.py --json              # JSON (schema v1)
    python scripts/check_coupling.py --trend-compare baseline.json
    python scripts/check_coupling.py --max-flagged 20

Exit codes
----------
    0 — success (or advisory findings exist)
    1 — graph error or blocking budget exceeded
    2 — syntax error in a source file
    3 — file read error
    4 — invalid config / argument error
"""

from __future__ import annotations

import ast
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src" / "perplexity_cli"

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))
from scripts._gates import (  # noqa: E402  # owner: quality-infrastructure; reason: package-relative import after repo-root setup
    load_gates,
)
from scripts.import_graph import (  # noqa: E402  # owner: quality-infrastructure; reason: package-relative import after repo-root setup
    FileReadError,
    SyntaxErrorInSource,
    get_all_edges,
    get_all_module_names,
    get_function_local_imports,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_gates = load_gates()
DEFAULT_DISTANCE_THRESHOLD = _gates.get_float("DISTANCE_THRESHOLD", 0.3)

_EXIT_GRAPH_ERROR = 1
_EXIT_SYNTAX_ERROR = 2
_EXIT_READ_ERROR = 3
_EXIT_CONFIG_ERROR = 4

_ZONE_PAIN_THRESHOLD = 0.3
_ZONE_USELESS_THRESHOLD = 0.7
_TREND_PERSISTENT_LIMIT = 5


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ModuleMetrics:
    """Coupling and stability metrics for a single module."""

    module: str
    ca: int = 0
    ce: int = 0
    na: int = 0
    nc: int = 0
    dependencies: tuple[str, ...] = ()
    dependents: tuple[str, ...] = ()

    @property
    def instability(self) -> float:
        """I = Ce / (Ca + Ce).  0 = stable, 1 = unstable."""
        total = self.ca + self.ce
        if total == 0:
            return 0.0
        return self.ce / total

    @property
    def abstractness(self) -> float:
        """A = Na / (Na + Nc).  0 = concrete, 1 = abstract."""
        total = self.na + self.nc
        if total == 0:
            return 0.0
        return self.na / total

    @property
    def distance(self) -> float:
        """D = |A + I - 1|.  0 = perfectly balanced on the main sequence."""
        return abs(self.abstractness + self.instability - 1.0)

    @property
    def is_zone_of_pain(self) -> bool:
        """I < 0.3 and A < 0.3: stable + concrete with outgoing deps — rigid."""
        return self.instability < _ZONE_PAIN_THRESHOLD and self.abstractness < _ZONE_PAIN_THRESHOLD

    @property
    def is_zone_of_uselessness(self) -> bool:
        """I > 0.7 and A > 0.7: unstable + abstract — no dependents."""
        return (
            self.instability > _ZONE_USELESS_THRESHOLD
            and self.abstractness > _ZONE_USELESS_THRESHOLD
        )

    @property
    def finding_id(self) -> str:
        """Stable identifier for trend tracking and deduplication."""
        return self.module


class OutputMode(Enum):
    """Available coupling report output formats."""

    TEXT = "text"
    JSON = "json"


@dataclass(frozen=True, slots=True)
class ReportOptions:
    """Immutable options for coupling report generation."""

    output_mode: OutputMode
    threshold: float
    max_flagged: int | None
    trend_compare_path: Path | None
    blocking: bool = False


class TrendReport(TypedDict):
    """Trend comparison fields emitted in coupling report schema v1."""

    previous_flagged_count: int
    delta: int
    direction: str
    previous_timestamp: object
    added: list[str]
    removed: list[str]
    persistent: list[str]


@dataclass(slots=True)
class _ArgumentState:
    """Mutable state used while consuming command-line flags."""

    json_mode: bool = False
    threshold: float = DEFAULT_DISTANCE_THRESHOLD
    max_flagged: int | None = None
    trend_compare: Path | None = None
    module: str | None = None
    blocking: bool = False


def _make_finding_id(module: str) -> str:
    """Generate a stable finding identifier."""
    return module


# ---------------------------------------------------------------------------
# Coupling graph construction (delegates to import_graph.py)
# ---------------------------------------------------------------------------


def _strip_package_prefix(name: str) -> str:
    """Strip the root package prefix from a fully-qualified module name.

    Args:
        name: A fully-qualified module name like 'perplexity_cli.api.client'.

    Returns:
        The module name relative to the root package, e.g. 'api.client'.
        Bare root package returns ''.
    """
    prefix = "perplexity_cli."
    if name == "perplexity_cli":
        return ""
    if name.startswith(prefix):
        return name[len(prefix) :]
    return name


def _gather_grimp_edges(
    efferent: dict[str, set[str]],
    afferent: dict[str, set[str]],
) -> None:
    """Read edges from the Grimp import graph into efferent/afferent maps."""
    for src, tgt in get_all_edges():
        src_rel = _strip_package_prefix(src)
        tgt_rel = _strip_package_prefix(tgt)
        efferent[src_rel].add(tgt_rel)
        afferent[tgt_rel].add(src_rel)


def _gather_function_local_edges(
    efferent: dict[str, set[str]],
    afferent: dict[str, set[str]],
) -> None:
    """Add function-local imports as coupling edges."""
    for module_fq in get_all_module_names():
        rel = _strip_package_prefix(module_fq)
        func_imports = get_function_local_imports(module_fq)
        for imported in func_imports:
            imported_rel = _strip_package_prefix(imported)
            if not imported_rel:
                continue
            efferent[rel].add(imported_rel)
            afferent[imported_rel].add(rel)


def _build_coupling_graph() -> tuple[dict[str, set[str]], dict[str, set[str]], set[str]]:
    """Build efferent and afferent coupling maps from the shared import graph.

    Includes all import categories (module-level, function-local, relative)
    as coupling.  No filtering of leaf-only or sibling dependencies is
    performed without documented rationale.

    Returns:
        A tuple of (efferent, afferent, all_modules).
        - efferent: module_name -> set of modules it imports.
        - afferent: module_name -> set of modules that import it.
        - all_modules: set of all module names (relative form).

    Raises:
        SyntaxErrorInSource: If a source file contains a syntax error.
        FileReadError: If a source file cannot be read.
    """
    efferent: dict[str, set[str]] = defaultdict(set)
    afferent: dict[str, set[str]] = defaultdict(set)

    _gather_grimp_edges(efferent, afferent)

    all_modules_rel: set[str] = {_strip_package_prefix(m) for m in get_all_module_names()}

    _gather_function_local_edges(efferent, afferent)

    return dict(efferent), dict(afferent), all_modules_rel


# ---------------------------------------------------------------------------
# Abstractness calculation (AST-based)
# ---------------------------------------------------------------------------


def _resolve_source_path(module_rel: str) -> Path | None:
    """Resolve a relative module name to a source file path."""
    parts = module_rel.split(".")
    file_path = SRC_ROOT / f"{'/'.join(parts)}.py"
    init_path = SRC_ROOT / "/".join(parts) / "__init__.py"
    if file_path.exists():
        return file_path
    if init_path.exists():
        return init_path
    return None


def _parse_source(filepath: Path) -> ast.Module:
    """Parse *filepath* into an AST, raising coupling-specific errors.

    Args:
        filepath: Path to the source file.

    Returns:
        The parsed module AST.

    Raises:
        SyntaxErrorInSource: If the file has a syntax error.
        FileReadError: If the file cannot be read.
    """
    try:
        source = filepath.read_text(encoding="utf-8")
        return ast.parse(source)
    except SyntaxError as exc:
        msg = f"Syntax error in {filepath}: {exc}"
        raise SyntaxErrorInSource(msg) from exc
    except (OSError, UnicodeDecodeError) as exc:
        msg = f"Could not read {filepath}: {exc}"
        raise FileReadError(msg) from exc


def _is_abstract_base(base: ast.expr) -> bool:
    """Return True if *base* is ABC or Protocol."""
    if isinstance(base, ast.Name):
        return base.id in {"ABC", "Protocol"}
    if isinstance(base, ast.Attribute):
        return base.attr in {"ABC", "Protocol"}
    return False


def _has_abstract_method(node: ast.ClassDef) -> bool:
    """Return True if *node* has any method decorated with @abstractmethod."""
    for item in node.body:
        if isinstance(item, ast.FunctionDef) and _is_abstract_decorated(item):
            return True
    return False


def _is_abstract_decorated(func: ast.FunctionDef) -> bool:
    """Return True if *func* has @abstractmethod in its decorators."""
    for decorator in func.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "abstractmethod":
            return True
    return False


def _has_abstract_base(node: ast.ClassDef) -> bool:
    """Return True if *node* subclasses ABC or Protocol."""
    return any(_is_abstract_base(base) for base in node.bases)


def _is_abstract_class(
    node: ast.ClassDef,
    referenced_classes: set[str] | None = None,
) -> bool:
    """Heuristic: abstract if it has abstract methods or is referenced.

    A class is abstract when it declares ``@abstractmethod``, or subclasses
    ABC/Protocol and is referenced (imported or instantiated) outside its own
    module.  Unreferenced Protocol-only declarative stubs are counted as
    concrete so they do not inflate abstractness.

    Args:
        node: The class definition node.
        referenced_classes: Set of class names in this module that are
            referenced from other modules.  ``None`` restores the legacy
            behaviour where every ABC/Protocol subclass is abstract.

    Returns:
        True when the class counts toward abstract classes (Na).
    """
    if _has_abstract_method(node):
        return True
    return _has_abstract_base(node) and (
        referenced_classes is None or node.name in referenced_classes
    )


def _count_abstract_classes(
    tree: ast.AST,
    referenced_classes: set[str] | None = None,
) -> tuple[int, int]:
    """Count abstract and concrete classes in an AST.

    Args:
        tree: The parsed module AST.
        referenced_classes: Class names in this module referenced from
            other modules.

    Returns:
        A tuple of (na, nc) counts.
    """
    na = 0
    nc = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if _is_abstract_class(node, referenced_classes):
                na += 1
            else:
                nc += 1
    return na, nc


def _class_names_in_tree(tree: ast.AST) -> set[str]:
    """Return the names of every class defined in *tree*."""
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}


def _imported_names_in_tree(tree: ast.AST) -> set[str]:
    """Return names imported into *tree* via ``from ... import``."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names if alias.name != "*")
    return names


def _identifier_names_in_tree(tree: ast.AST) -> set[str]:
    """Return every plain identifier used in *tree*."""
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def _attribute_names_in_tree(tree: ast.AST) -> set[str]:
    """Return every attribute access target in *tree*."""
    return {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}


def _referenced_names_in_tree(tree: ast.AST) -> set[str]:
    """Return names in *tree* that could reference a class elsewhere.

    Includes every imported name, plain identifier, and attribute access,
    because any of these may instantiate, subclass, or type-annotate with a
    class defined in another module.
    """
    names = _imported_names_in_tree(tree)
    names.update(_identifier_names_in_tree(tree))
    names.update(_attribute_names_in_tree(tree))
    return names


def _collect_module_class_info(
    modules: set[str],
) -> list[tuple[str, set[str], set[str]]]:
    """Parse *modules* into (module, class names, referenced names) triples.

    Args:
        modules: Set of relative module names.

    Returns:
        A list of per-module triples for every resolvable module.

    Raises:
        SyntaxErrorInSource: If a source file contains a syntax error.
        FileReadError: If a source file cannot be read.
    """
    parsed: list[tuple[str, set[str], set[str]]] = []
    for module in sorted(modules):
        filepath = _resolve_source_path(module)
        if filepath is None:
            continue
        tree = _parse_source(filepath)
        parsed.append((module, _class_names_in_tree(tree), _referenced_names_in_tree(tree)))
    return parsed


def _mark_definitions(
    parsed: list[tuple[str, set[str], set[str]]],
) -> dict[str, set[str]]:
    """Map every class name to the set of modules that define it."""
    definitions: dict[str, set[str]] = defaultdict(set)
    for module, class_names, _ in parsed:
        for name in class_names:
            definitions[name].add(module)
    return definitions


def _build_reference_map(
    parsed: list[tuple[str, set[str], set[str]]],
    definitions: dict[str, set[str]],
) -> dict[str, set[str]]:
    """Map module -> set of its class names referenced from other modules."""
    referenced: dict[str, set[str]] = defaultdict(set)
    for module, _, used_names in parsed:
        for used in used_names:
            for defining_module in definitions.get(used, ()):
                if defining_module != module:
                    referenced[defining_module].add(used)
    return dict(referenced)


def _referenced_class_names(modules: set[str]) -> dict[str, set[str]]:
    """Map each module to its class names referenced from other modules.

    A class is treated as referenced when its name is imported or used
    (instantiated, subclassed, or annotated) by any other module.  Uses
    within the defining module itself never count.

    Args:
        modules: Set of relative module names.

    Returns:
        A dict mapping module -> set of its class names referenced elsewhere.

    Raises:
        SyntaxErrorInSource: If a source file contains a syntax error.
        FileReadError: If a source file cannot be read.
    """
    parsed = _collect_module_class_info(modules)
    definitions = _mark_definitions(parsed)
    return _build_reference_map(parsed, definitions)


def _count_classes(
    filepath: Path,
    referenced_classes: set[str] | None = None,
) -> tuple[int, int]:
    """Return (abstract_classes, concrete_classes) for *filepath*.

    Args:
        filepath: Path to the source file.
        referenced_classes: Class names in this module referenced from
            other modules.

    Returns:
        A tuple of (na, nc) counts.

    Raises:
        SyntaxErrorInSource: If the file has a syntax error.
        FileReadError: If the file cannot be read.
    """
    tree = _parse_source(filepath)
    return _count_abstract_classes(tree, referenced_classes)


def _compute_abstractness(
    modules: set[str],
) -> dict[str, tuple[int, int]]:
    """Compute (na, nc) abstractness data for each module.

    A class counts as abstract only when it has ``@abstractmethod`` or is an
    ABC/Protocol subclass referenced outside its own module; unreferenced
    Protocol-only declarative stubs count as concrete.

    Args:
        modules: Set of relative module names.

    Returns:
        A dict mapping module -> (na, nc).

    Raises:
        SyntaxErrorInSource: If a source file has a syntax error.
        FileReadError: If a source file cannot be read.
    """
    referenced = _referenced_class_names(modules)
    result: dict[str, tuple[int, int]] = {}
    for module in modules:
        filepath = _resolve_source_path(module)
        if filepath is None:
            result[module] = (0, 0)
            continue
        result[module] = _count_classes(filepath, referenced.get(module, set()))
    return result


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------


def _compute_metrics(
    modules: set[str],
    efferent: dict[str, set[str]],
    afferent: dict[str, set[str]],
    abstractness_map: dict[str, tuple[int, int]],
) -> list[ModuleMetrics]:
    """Compute ModuleMetrics for every module.

    Args:
        modules: Set of all relative module names.
        efferent: Efferent coupling map.
        afferent: Afferent coupling map.
        abstractness_map: Map of module -> (na, nc).

    Returns:
        List of ModuleMetrics sorted by distance descending.
    """
    results: list[ModuleMetrics] = []
    for module in sorted(modules):
        ce = len(efferent.get(module, set()))
        ca = len(afferent.get(module, set()))
        na, nc = abstractness_map.get(module, (0, 0))
        deps = sorted(efferent.get(module, set()))
        depents = sorted(afferent.get(module, set()))

        results.append(
            ModuleMetrics(
                module=module,
                ca=ca,
                ce=ce,
                na=na,
                nc=nc,
                dependencies=tuple(deps),
                dependents=tuple(depents),
            )
        )
    results.sort(key=lambda m: m.distance, reverse=True)
    return results


# ---------------------------------------------------------------------------
# Flagged findings
# ---------------------------------------------------------------------------


def _flagged_metrics(metrics: Sequence[ModuleMetrics], threshold: float) -> list[ModuleMetrics]:
    """Filter metrics to findings that are architecturally notable.

    A module is flagged when its distance from the main sequence meets
    or exceeds the threshold (D >= threshold) and it has outgoing
    dependencies (Ce > 0, not a pure leaf).

    Args:
        metrics: All module metrics.
        threshold: Distance threshold for flagging.

    Returns:
        Flagged modules in distance-descending order.
    """
    return [m for m in metrics if m.distance >= threshold and m.ce > 0]


# ---------------------------------------------------------------------------
# Trend comparison
# ---------------------------------------------------------------------------


def _as_json_object(value: object, path: Path) -> dict[str, object]:
    """Validate and narrow a parsed JSON report object."""
    if not isinstance(value, dict):
        msg = f"Trend-compare file {path} must contain a JSON object"
        raise FileReadError(msg)
    entries = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in entries):
        msg = f"Trend-compare file {path} contains a non-string key"
        raise FileReadError(msg)
    return cast(dict[str, object], entries)


def _load_previous_report(previous_path: Path) -> dict[str, object]:
    """Load and validate a previous coupling report.

    Args:
        previous_path: Path to a previous coupling-report JSON file.

    Returns:
        The parsed report dict.

    Raises:
        FileReadError: If the file cannot be read or has invalid JSON/version.
    """
    try:
        raw = previous_path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"Cannot read trend-compare file {previous_path}: {exc}"
        raise FileReadError(msg) from exc

    try:
        loaded: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"Invalid JSON in trend-compare file {previous_path}: {exc}"
        raise FileReadError(msg) from exc

    previous = _as_json_object(loaded, previous_path)
    if previous.get("report_version") != "1":
        ver = previous.get("report_version")
        msg = f"Unsupported report version {ver} in {previous_path}"
        raise FileReadError(msg)
    return previous


def _string_list(value: object) -> list[str] | None:
    """Return a JSON array only when every item is a string."""
    if not isinstance(value, list):
        return None
    items = cast(list[object], value)
    if not all(isinstance(item, str) for item in items):
        return None
    return cast(list[str], items)


def _finding_identities(value: object) -> set[str]:
    """Extract module identities from a validated findings array."""
    if not isinstance(value, list):
        return set()
    identities: set[str] = set()
    for finding_raw in cast(list[object], value):
        finding = _as_finding(finding_raw)
        if finding is not None:
            identities.add(finding)
    return identities


def _as_finding(value: object) -> str | None:
    """Extract a module name from one previous finding object."""
    if not isinstance(value, dict):
        return None
    finding = cast(dict[object, object], value)
    module = finding.get("module")
    return module if isinstance(module, str) else None


def _previous_identities(previous: dict[str, object]) -> set[str]:
    """Read identities from the preferred field or legacy findings fallback."""
    flagged = _string_list(previous.get("flagged_identities"))
    if flagged:
        return set(flagged)
    return _finding_identities(previous.get("findings"))


def _compare_trends(
    current_flagged: set[str],
    previous_path: Path,
) -> TrendReport:
    """Compare current flagged modules against a previous snapshot.

    Args:
        current_flagged: Set of currently flagged module identities.
        previous_path: Path to a previous coupling-report JSON file.

    Returns:
        A trend dict conforming to the schema.

    Raises:
        FileReadError: If the previous report cannot be read or parsed.
    """
    previous = _load_previous_report(previous_path)

    prev_identities = _previous_identities(previous)

    prev_count = len(prev_identities)
    curr_count = len(current_flagged)
    delta = curr_count - prev_count

    if delta < 0:
        direction = "improved"
    elif delta > 0:
        direction = "regressed"
    else:
        direction = "unchanged"

    return {
        "previous_flagged_count": prev_count,
        "delta": delta,
        "direction": direction,
        "previous_timestamp": previous.get("timestamp"),
        "added": sorted(current_flagged - prev_identities),
        "removed": sorted(prev_identities - current_flagged),
        "persistent": sorted(current_flagged & prev_identities),
    }


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _zone_label(m: ModuleMetrics) -> str:
    if m.is_zone_of_pain:
        return "PAIN"
    if m.is_zone_of_uselessness:
        return "USELESS"
    return ""


def _format_finding_row(m: ModuleMetrics) -> str:
    return (
        f"{m.module:<40}"
        f" {m.ca:>4}"
        f" {m.ce:>4}"
        f" {m.instability:>6.2f}"
        f" {m.abstractness:>6.2f}"
        f" {m.distance:>6.2f}"
        f" {_zone_label(m)}"
    )


def _format_trend_section(trend: TrendReport, flagged_count: int) -> list[str]:
    """Format the trend comparison section of the text report."""
    lines: list[str] = []
    lines.append("── Trend Comparison ──")
    lines.append(f"  Previous snapshot: {trend.get('previous_timestamp', 'N/A')}")
    lines.append(f"  Previous flagged:  {trend['previous_flagged_count']}")
    lines.append(f"  Current flagged:   {flagged_count}")
    lines.append(f"  Delta:             {trend['delta']:+d} ({trend['direction']})")
    if trend["added"]:
        lines.append(f"  Newly flagged:     {', '.join(trend['added'])}")
    if trend["removed"]:
        lines.append(f"  Resolved:          {', '.join(trend['removed'])}")
    if trend["persistent"]:
        persistent = trend["persistent"]
        label = ", ".join(persistent[:_TREND_PERSISTENT_LIMIT])
        suffix = " ..." if len(persistent) > _TREND_PERSISTENT_LIMIT else ""
        lines.append(f"  Persistent:        {label}{suffix}")
    return lines


def _format_header(metrics_count: int, flagged_count: int, threshold: float) -> list[str]:
    """Format the report header."""
    lines: list[str] = []
    lines.append("╔══════════════════════════════════════════════════════════════════════╗")
    lines.append("║  Coupling Report (ADVISORY)                                        ║")
    lines.append("║  Findings are informational and do not fail the build.             ║")
    lines.append("╚══════════════════════════════════════════════════════════════════════╝")
    lines.append("")
    lines.append(
        f"Modules analysed: {metrics_count}"
        f"  |  Flagged: {flagged_count}"
        f"  |  Threshold: D >= {threshold}"
    )
    lines.append("")
    return lines


def _format_flag_table(flagged: Sequence[ModuleMetrics]) -> list[str]:
    """Format the flagged modules table."""
    lines: list[str] = []
    if not flagged:
        lines.append("All modules are within acceptable distance from the main sequence.")
        return lines

    lines.append(f"{'Module':<40} {'Ca':>4} {'Ce':>4} {'I':>6} {'A':>6} {'D':>6} {'Zone'}")
    lines.append("-" * 85)
    for m in flagged:
        lines.append(_format_finding_row(m))
    return lines


def _format_legend() -> list[str]:
    """Format the formula legend."""
    return [
        "",
        "Formulas:",
        "  Ca = afferent coupling  (how many modules import this one)",
        "  Ce = efferent coupling  (how many modules this one imports)",
        "  I  = Ce / (Ca + Ce)     (0 = stable, 1 = unstable)",
        "  A  = abstract classes / total classes",
        "  D  = |A + I - 1|        (0 = perfectly balanced)",
        "",
        "This report is ADVISORY.  Findings do not fail the build.",
    ]


def _format_advisory_text(
    metrics: list[ModuleMetrics],
    threshold: float,
    trend: TrendReport | None = None,
) -> str:
    """Format the advisory text report.

    Args:
        metrics: All module metrics sorted by distance.
        threshold: Distance threshold.
        trend: Optional trend comparison dict.

    Returns:
        The formatted report string.
    """
    flagged = _flagged_metrics(metrics, threshold)
    lines: list[str] = []

    lines.extend(_format_header(len(metrics), len(flagged), threshold))

    if trend:
        lines.extend(_format_trend_section(trend, len(flagged)))
        lines.append("")

    lines.extend(_format_flag_table(flagged))
    lines.extend(_format_legend())

    return "\n".join(lines)


def _format_json_report(
    metrics: list[ModuleMetrics],
    threshold: float,
    trend: TrendReport | None = None,
) -> str:
    """Format the advisory coupling report as JSON (schema v1).

    Args:
        metrics: All module metrics sorted by distance.
        threshold: Distance threshold.
        trend: Optional trend comparison dict.

    Returns:
        JSON string conforming to coupling-report-v1 schema.
    """
    flagged = _flagged_metrics(metrics, threshold)

    findings: list[dict[str, object]] = []
    for m in metrics:
        findings.append(
            {
                "module": m.module,
                "ca": m.ca,
                "ce": m.ce,
                "instability": round(m.instability, 3),
                "abstractness": round(m.abstractness, 3),
                "distance": round(m.distance, 3),
                "zone_of_pain": m.is_zone_of_pain,
                "zone_of_uselessness": m.is_zone_of_uselessness,
                "advisory": True,
                "finding_id": _make_finding_id(m.module),
                "dependencies": list(m.dependencies),
                "dependents": list(m.dependents),
            }
        )

    report: dict[str, object] = {
        "report_version": "1",
        "total_modules": len(metrics),
        "flagged_count": len(flagged),
        "flagged_identities": sorted([m.module for m in flagged]),
        "threshold": threshold,
        "graph_error": False,
        "trend": trend,
        "findings": findings,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    return json.dumps(report, indent=2)


def _format_error_report(threshold: float, error_msg: str) -> str:
    """Format an error-bearing JSON report."""
    return json.dumps(
        {
            "report_version": "1",
            "total_modules": 0,
            "flagged_count": 0,
            "flagged_identities": [],
            "threshold": threshold,
            "graph_error": True,
            "trend": None,
            "findings": [],
            "timestamp": datetime.now(UTC).isoformat(),
            "error": error_msg,
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


def _ensure_threshold_range(value: float) -> None:
    """Validate that *value* is a valid coupling threshold, exiting on failure."""
    if value < 0 or value > 1:
        print(
            f"ERROR: threshold must be between 0 and 1, got {value}",
            file=sys.stderr,
        )
        sys.exit(_EXIT_CONFIG_ERROR)


def _parse_arg_float(args: list[str], idx: int, opt: str) -> float:
    """Parse a float CLI argument value.

    Raises SystemExit on missing or invalid value.
    """
    if idx >= len(args):
        print(f"ERROR: {opt} requires a float value", file=sys.stderr)
        sys.exit(_EXIT_CONFIG_ERROR)
    try:
        return float(args[idx])
    except ValueError:
        print(f"ERROR: invalid value for {opt}: {args[idx]}", file=sys.stderr)
        sys.exit(_EXIT_CONFIG_ERROR)


def _parse_arg_int(args: list[str], idx: int, opt: str) -> int:
    """Parse an integer CLI argument value.

    Raises SystemExit on missing or invalid value.
    """
    if idx >= len(args):
        print(f"ERROR: {opt} requires an integer value", file=sys.stderr)
        sys.exit(_EXIT_CONFIG_ERROR)
    try:
        return int(args[idx])
    except ValueError:
        print(f"ERROR: invalid value for {opt}: {args[idx]}", file=sys.stderr)
        sys.exit(_EXIT_CONFIG_ERROR)


def _ensure_value_present(args: list[str], idx: int, message: str) -> None:
    """Exit with a config error if no positional value exists at *idx*."""
    if idx >= len(args):
        print(f"ERROR: {message}", file=sys.stderr)
        sys.exit(_EXIT_CONFIG_ERROR)


def _handle_json_flag(_args: list[str], _idx: int, state: _ArgumentState) -> int:
    """Enable JSON output mode in *state*."""
    state.json_mode = True
    return 0


def _handle_threshold_flag(args: list[str], idx: int, state: _ArgumentState) -> int:
    """Parse and store the --threshold value in *state*."""
    val = _parse_arg_float(args, idx + 1, "--threshold")
    _ensure_threshold_range(val)
    state.threshold = val
    return 1


def _handle_max_flagged_flag(args: list[str], idx: int, state: _ArgumentState) -> int:
    """Parse and store the --max-flagged value in *state*."""
    _ensure_value_present(args, idx + 1, "--max-flagged requires an integer value")
    state.max_flagged = _parse_arg_int(args, idx + 1, "--max-flagged")
    return 1


def _handle_trend_compare_flag(args: list[str], idx: int, state: _ArgumentState) -> int:
    """Store the --trend-compare file path in *state*."""
    _ensure_value_present(args, idx + 1, "--trend-compare requires a file path")
    state.trend_compare = Path(args[idx + 1])
    return 1


def _handle_blocking_flag(_args: list[str], _idx: int, state: _ArgumentState) -> int:
    """Enable blocking (non-zero exit) mode in *state*."""
    state.blocking = True
    return 0


def _handle_module_flag(args: list[str], idx: int, state: _ArgumentState) -> int:
    """Store the --module name in *state*."""
    arg = args[idx]
    _ensure_value_present(args, idx + 1, f"{arg} requires a module name")
    state.module = args[idx + 1]
    return 1


_FLAG_HANDLERS: dict[str, Callable[[list[str], int, _ArgumentState], int]] = {
    "--json": _handle_json_flag,
    "--threshold": _handle_threshold_flag,
    "--max-flagged": _handle_max_flagged_flag,
    "--trend-compare": _handle_trend_compare_flag,
    "--blocking": _handle_blocking_flag,
    "--module": _handle_module_flag,
}


def _handle_flag(
    args: list[str],
    idx: int,
    state: _ArgumentState,
) -> int:
    """Process a single CLI flag, updating *state* in place.

    Returns the number of extra positional args consumed (0 or 1).
    """
    flag_handler = _FLAG_HANDLERS.get(args[idx])
    if flag_handler is None:
        return 0
    return flag_handler(args, idx, state)


def _parse_args(
    args: list[str],
) -> tuple[bool, float, int | None, Path | None, bool]:
    """Parse CLI arguments.

    Returns:
        A tuple of (json_mode, threshold, max_flagged, trend_compare_path, blocking).
    """
    state = _ArgumentState()

    i = 0
    while i < len(args):
        consumed = _handle_flag(args, i, state)
        i += 1 + consumed

    return (
        state.json_mode,
        state.threshold,
        state.max_flagged,
        state.trend_compare,
        state.blocking,
    )


# ---------------------------------------------------------------------------
# Single module detail
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def _emit_error(
    prefix: str,
    exc: BaseException,
    options: ReportOptions,
) -> None:
    """Print *prefix* and *exc* to stderr, and a JSON report in JSON mode."""
    print(f"{prefix}: {exc}", file=sys.stderr)
    if options.output_mode is OutputMode.JSON:
        print(_format_error_report(options.threshold, str(exc)))


def _build_graph_or_exit(
    options: ReportOptions,
) -> tuple[dict[str, set[str]], dict[str, set[str]], set[str]] | int:
    """Build the coupling graph or return an exit code on failure."""
    try:
        return _build_coupling_graph()
    except SyntaxErrorInSource as exc:
        _emit_error("SYNTAX ERROR", exc, options)
        return _EXIT_SYNTAX_ERROR
    except FileReadError as exc:
        _emit_error("READ ERROR", exc, options)
        return _EXIT_READ_ERROR
    except Exception as exc:
        _emit_error("GRAPH ERROR", exc, options)
        return _EXIT_GRAPH_ERROR


def _compute_abstractness_or_exit(
    all_modules: set[str],
) -> dict[str, tuple[int, int]] | int:
    """Compute abstractness or return an exit code on failure."""
    try:
        return _compute_abstractness(all_modules)
    except SyntaxErrorInSource as exc:
        print(f"SYNTAX ERROR: {exc}", file=sys.stderr)
        return _EXIT_SYNTAX_ERROR
    except FileReadError as exc:
        print(f"READ ERROR: {exc}", file=sys.stderr)
        return _EXIT_READ_ERROR


def _compare_trends_or_exit(
    flagged_identities: set[str],
    trend_compare_path: Path,
    options: ReportOptions,
) -> TrendReport | int:
    """Compare trends or return an exit code on failure."""
    try:
        return _compare_trends(flagged_identities, trend_compare_path)
    except FileReadError as exc:
        _emit_error("READ ERROR", exc, options)
        return _EXIT_READ_ERROR


def _emit_report(
    metrics: list[ModuleMetrics],
    trend: TrendReport | None,
    options: ReportOptions,
) -> None:
    """Print the report in JSON or advisory-text form."""
    if options.output_mode is OutputMode.JSON:
        print(_format_json_report(metrics, options.threshold, trend))
        return
    print(_format_advisory_text(metrics, options.threshold, trend))


def _emit_budget_advisory(
    flagged: list[ModuleMetrics],
    options: ReportOptions,
) -> None:
    """Print the budget advisory when flagged count exceeds the budget."""
    if options.max_flagged is None or len(flagged) <= options.max_flagged:
        return
    msg = _format_budget_message(len(flagged), options.max_flagged, options.blocking)
    if options.output_mode is OutputMode.TEXT:
        print(msg)


def _format_budget_message(  # nosemgrep: boolean-flag-argument  # owner: quality-infrastructure; reason: private helper, boolean from typed enum context.
    flagged_count: int, max_flagged: int, blocking: bool
) -> str:
    """Build the budget-exceeded message."""
    label = "BLOCKING" if blocking else "ADVISORY"
    suffix = "" if blocking else "  This is informational only."
    return (
        f"\n{label}: {flagged_count} flagged modules exceeds "
        f"--max-flagged budget of {max_flagged}.{suffix}"
    )


def _should_block(
    flagged: list[ModuleMetrics],
    options: ReportOptions,
) -> bool:
    """Return True when --blocking is set and flagged exceeds the budget."""
    if not options.blocking:
        return False
    if options.max_flagged is None:
        return False
    return len(flagged) > options.max_flagged


def _generate_report(options: ReportOptions) -> int:
    """Generate the coupling report.

    Returns:
        Exit code: 0 for success/advisory, non-zero for graph/parse/config errors
        or when --blocking is set and flagged exceeds max_flagged budget.
    """
    graph_result = _build_graph_or_exit(options)
    if isinstance(graph_result, int):
        return graph_result
    efferent, afferent, all_modules = graph_result

    exit_code = _collect_and_report(efferent, afferent, all_modules, options)
    if exit_code is not None:
        return exit_code
    return 0


def _collect_and_report(
    efferent: dict[str, set[str]],
    afferent: dict[str, set[str]],
    all_modules: set[str],
    options: ReportOptions,
) -> int | None:
    """Collect metrics, emit report, return exit code or None for success."""
    abstractness_result = _compute_abstractness_or_exit(all_modules)
    if isinstance(abstractness_result, int):
        return abstractness_result
    abstractness_map = abstractness_result

    metrics = _compute_metrics(all_modules, efferent, afferent, abstractness_map)
    flagged = _flagged_metrics(metrics, options.threshold)
    flagged_identities = {m.module for m in flagged}

    trend = _resolve_trend(flagged_identities, options)
    if isinstance(trend, int):
        return trend

    _emit_report(metrics, trend, options)
    _emit_budget_advisory(flagged, options)

    if _should_block(flagged, options):
        return 1
    return None


def _resolve_trend(
    flagged_identities: set[str], options: ReportOptions
) -> TrendReport | int | None:
    """Compute trend comparison, returning None if no trend path is configured."""
    if not options.trend_compare_path:
        return None
    trend_result = _compare_trends_or_exit(flagged_identities, options.trend_compare_path, options)
    if isinstance(trend_result, int):
        return trend_result
    return trend_result


def main(argv: list[str] | None = None) -> int:
    """Run the coupling advisory report.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code: 0 for success/advisory, non-zero for errors.
    """
    args = argv if argv is not None else sys.argv[1:]
    json_mode, threshold, max_flagged, trend_compare_path, blocking = _parse_args(args)
    output_mode = OutputMode.JSON if json_mode else OutputMode.TEXT
    options = ReportOptions(output_mode, threshold, max_flagged, trend_compare_path, blocking)
    return _generate_report(options)


if __name__ == "__main__":
    sys.exit(main())
