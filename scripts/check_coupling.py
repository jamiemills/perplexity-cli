"""Coupling and stability advisory report for architecture health.

Uses the shared import graph adapter (scripts/import_graph.py) to
calculate Robert C. Martin's package-level metrics.  Reports advisory
findings — it does not fail based on flagged counts, but DOES fail on
graph build errors, parse errors, or config errors.

Formulas
--------
    Afferent coupling  Ca = |{modules that import this one}|
    Efferent coupling  Ce = |{modules this one imports}|
    Instability        I  = Ce / (Ca + Ce)    (0 if Ca+Ce=0)
    Abstractness       A  = Na / (Na + Nc)    (0 if no classes)
    Distance           D  = |A + I - 1|

    - Na = abstract classes (ABC / Protocol subclasses or @abstractmethod)
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
    1 — graph build / import resolution error
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
from pathlib import Path
from typing import TYPE_CHECKING

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src" / "perplexity_cli"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gates import load_gates  # noqa: E402
from import_graph import (  # noqa: E402
    FileReadError,
    SyntaxErrorInSource,
    get_all_edges,
    get_all_module_names,
    get_function_local_imports,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

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


def _is_abstract_base(base: ast.expr) -> bool:
    """Return True if *base* is ABC or Protocol."""
    if isinstance(base, ast.Name):
        return base.id in ("ABC", "Protocol")
    if isinstance(base, ast.Attribute):
        return base.attr in ("ABC", "Protocol")
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


def _is_abstract_class(node: ast.ClassDef) -> bool:
    """Heuristic: abstract if ABC/Protocol subclass or has @abstractmethod."""
    for base in node.bases:
        if _is_abstract_base(base):
            return True
    return _has_abstract_method(node)


def _count_abstract_classes(tree: ast.AST) -> tuple[int, int]:
    """Count abstract and concrete classes in an AST.

    Args:
        tree: The parsed module AST.

    Returns:
        A tuple of (na, nc) counts.
    """
    na = 0
    nc = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if _is_abstract_class(node):
                na += 1
            else:
                nc += 1
    return na, nc


def _count_classes(filepath: Path) -> tuple[int, int]:
    """Return (abstract_classes, concrete_classes) for *filepath*.

    Args:
        filepath: Path to the source file.

    Returns:
        A tuple of (na, nc) counts.

    Raises:
        SyntaxErrorInSource: If the file has a syntax error.
        FileReadError: If the file cannot be read.
    """
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise SyntaxErrorInSource(f"Syntax error in {filepath}: {exc}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise FileReadError(f"Could not read {filepath}: {exc}") from exc

    return _count_abstract_classes(tree)


def _compute_abstractness(
    modules: set[str],
) -> dict[str, tuple[int, int]]:
    """Compute (na, nc) abstractness data for each module.

    Args:
        modules: Set of relative module names.

    Returns:
        A dict mapping module -> (na, nc).

    Raises:
        SyntaxErrorInSource: If a source file has a syntax error.
        FileReadError: If a source file cannot be read.
    """
    result: dict[str, tuple[int, int]] = {}
    for module in modules:
        filepath = _resolve_source_path(module)
        if filepath is None:
            result[module] = (0, 0)
            continue
        result[module] = _count_classes(filepath)
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


def _load_previous_report(previous_path: Path) -> dict:
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
        raise FileReadError(f"Cannot read trend-compare file {previous_path}: {exc}") from exc

    try:
        previous = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FileReadError(f"Invalid JSON in trend-compare file {previous_path}: {exc}") from exc

    if previous.get("report_version") != "1":
        ver = previous.get("report_version")
        raise FileReadError(f"Unsupported report version {ver} in {previous_path}")
    return previous


def _compare_trends(
    current_flagged: set[str],
    previous_path: Path,
) -> dict:
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

    prev_identities = set(previous.get("flagged_identities", []))
    if not prev_identities:
        prev_identities = {f["module"] for f in previous.get("findings", [])}

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


def _format_trend_section(trend: dict, flagged_count: int) -> list[str]:
    """Format the trend comparison section of the text report."""
    lines: list[str] = []
    lines.append("── Trend Comparison ──")
    lines.append(f"  Previous snapshot: {trend.get('previous_timestamp', 'N/A')}")
    lines.append(f"  Previous flagged:  {trend['previous_flagged_count']}")
    lines.append(f"  Current flagged:   {flagged_count}")
    lines.append(f"  Delta:             {trend['delta']:+d} ({trend['direction']})")
    if trend.get("added"):
        lines.append(f"  Newly flagged:     {', '.join(trend['added'])}")
    if trend.get("removed"):
        lines.append(f"  Resolved:          {', '.join(trend['removed'])}")
    if trend.get("persistent"):
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
    trend: dict | None = None,
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
    trend: dict | None = None,
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

    findings = []
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

    report: dict = {
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


def _handle_flag(
    args: list[str],
    idx: int,
    state: dict,
) -> int:
    """Process a single CLI flag, updating *state* in place.

    Returns the number of extra positional args consumed (0 or 1).
    """
    arg = args[idx]
    if arg == "--json":
        state["json_mode"] = True
        return 0
    if arg == "--threshold":
        val = _parse_arg_float(args, idx + 1, "--threshold")
        _ensure_threshold_range(val)
        state["threshold"] = val
        return 1
    if arg == "--max-flagged":
        if idx + 1 >= len(args):
            print("ERROR: --max-flagged requires an integer value", file=sys.stderr)
            sys.exit(_EXIT_CONFIG_ERROR)
        state["max_flagged"] = _parse_arg_int(args, idx + 1, "--max-flagged")
        return 1
    if arg == "--trend-compare":
        if idx + 1 >= len(args):
            print("ERROR: --trend-compare requires a file path", file=sys.stderr)
            sys.exit(_EXIT_CONFIG_ERROR)
        state["trend_compare"] = Path(args[idx + 1])
        return 1
    if arg in ("--module",):
        if idx + 1 >= len(args):
            print(f"ERROR: {arg} requires a module name", file=sys.stderr)
            sys.exit(_EXIT_CONFIG_ERROR)
        state["module"] = args[idx + 1]
        return 1
    return 0


def _parse_args(
    args: list[str],
) -> tuple[bool, float, int | None, Path | None]:
    """Parse CLI arguments.

    Returns:
        A tuple of (json_mode, threshold, max_flagged, trend_compare_path).
    """
    state: dict = {
        "json_mode": False,
        "threshold": DEFAULT_DISTANCE_THRESHOLD,
        "max_flagged": None,
        "trend_compare": None,
        "module": None,
    }

    i = 0
    while i < len(args):
        consumed = _handle_flag(args, i, state)
        i += 1 + consumed

    return (
        state["json_mode"],
        state["threshold"],
        state["max_flagged"],
        state["trend_compare"],
    )


# ---------------------------------------------------------------------------
# Single module detail
# ---------------------------------------------------------------------------


def _print_single_module(module_name: str) -> None:
    """Print detailed coupling info for a single module."""
    rel = _strip_package_prefix(module_name)
    efferent, afferent, all_modules = _build_coupling_graph()
    abstractness_map = _compute_abstractness(all_modules)
    na, nc = abstractness_map.get(rel, (0, 0))
    ce = len(efferent.get(rel, set()))
    ca = len(afferent.get(rel, set()))

    m = ModuleMetrics(
        module=rel,
        ca=ca,
        ce=ce,
        na=na,
        nc=nc,
        dependencies=tuple(sorted(efferent.get(rel, set()))),
        dependents=tuple(sorted(afferent.get(rel, set()))),
    )

    print(f"Module: {rel}")
    print(f"  Ca (afferent):    {m.ca}")
    print(f"  Ce (efferent):    {m.ce}")
    print(f"  Instability (I):  {m.instability:.3f}")
    print(f"  Abstractness (A): {m.abstractness:.3f}")
    print(f"  Distance (D):     {m.distance:.3f}")
    print(f"  Zone:             {_zone_label(m) or 'balanced'}")
    print("  Dependencies:")
    for d in m.dependencies:
        print(f"    {d}")
    print("  Dependents:")
    for d in m.dependents:
        print(f"    {d}")


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def _generate_report(
    json_mode: bool,
    threshold: float,
    max_flagged: int | None,
    trend_compare_path: Path | None,
) -> int:
    """Generate the coupling report.

    Returns:
        Exit code: 0 for success, non-zero for graph/parse/config errors.
    """
    try:
        efferent, afferent, all_modules = _build_coupling_graph()
    except SyntaxErrorInSource as exc:
        print(f"SYNTAX ERROR: {exc}", file=sys.stderr)
        if json_mode:
            print(_format_error_report(threshold, str(exc)))
        return _EXIT_SYNTAX_ERROR
    except FileReadError as exc:
        print(f"READ ERROR: {exc}", file=sys.stderr)
        if json_mode:
            print(_format_error_report(threshold, str(exc)))
        return _EXIT_READ_ERROR
    except Exception as exc:
        print(f"GRAPH ERROR: {exc}", file=sys.stderr)
        if json_mode:
            print(_format_error_report(threshold, str(exc)))
        return _EXIT_GRAPH_ERROR

    try:
        abstractness_map = _compute_abstractness(all_modules)
    except SyntaxErrorInSource as exc:
        print(f"SYNTAX ERROR: {exc}", file=sys.stderr)
        return _EXIT_SYNTAX_ERROR
    except FileReadError as exc:
        print(f"READ ERROR: {exc}", file=sys.stderr)
        return _EXIT_READ_ERROR

    metrics = _compute_metrics(all_modules, efferent, afferent, abstractness_map)
    flagged = _flagged_metrics(metrics, threshold)
    flagged_identities = {m.module for m in flagged}

    trend: dict | None = None
    if trend_compare_path:
        try:
            trend = _compare_trends(flagged_identities, trend_compare_path)
        except FileReadError as exc:
            print(f"READ ERROR: {exc}", file=sys.stderr)
            if json_mode:
                print(_format_error_report(threshold, str(exc)))
            return _EXIT_READ_ERROR

    if json_mode:
        print(_format_json_report(metrics, threshold, trend))
    else:
        print(_format_advisory_text(metrics, threshold, trend))

    if max_flagged is not None and len(flagged) > max_flagged:
        msg = (
            f"\nADVISORY: {len(flagged)} flagged modules exceeds "
            f"--max-flagged budget of {max_flagged}.  "
            f"This is informational only."
        )
        if not json_mode:
            print(msg)

    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the coupling advisory report.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code: 0 for success/advisory, non-zero for errors.
    """
    args = argv if argv is not None else sys.argv[1:]
    json_mode, threshold, max_flagged, trend_compare_path = _parse_args(args)
    return _generate_report(json_mode, threshold, max_flagged, trend_compare_path)


if __name__ == "__main__":
    sys.exit(main())
