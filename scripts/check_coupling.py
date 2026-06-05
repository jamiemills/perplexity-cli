"""Coupling and stability metrics for architecture health monitoring.

Calculates Robert C. Martin's package metrics for every module under
src/perplexity_cli/:

  Ca - Afferent coupling: how many modules depend on this one.
  Ce - Efferent coupling: how many modules this one depends on.
  I  - Instability = Ce / (Ca + Ce).  0 = maximally stable, 1 = maximally unstable.
  A  - Abstractness = abstract classes / total classes (0-1).
  D  - Distance from main sequence = |A + I - 1|.  0 = well-balanced.

Modules far from the main sequence (D >= 0.3) are flagged as
architecturally suspect and printed in the report.

Usage
-----
    python scripts/check_coupling.py              # full report, sorted by D
    python scripts/check_coupling.py --json       # machine-readable output
    python scripts/check_coupling.py --threshold 0.3  # custom D threshold
    python scripts/check_coupling.py --module api.client  # single module detail
"""

from __future__ import annotations

import ast
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src" / "perplexity_cli"

DEFAULT_D_THRESHOLD = 0.3


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ModuleMetrics:
    """Coupling and stability metrics for a single module."""

    module: str

    # Coupling
    ca: int = 0  # afferent: modules that import this one
    ce: int = 0  # efferent: modules this one imports

    # Abstractness
    abstract_classes: int = 0
    concrete_classes: int = 0

    @property
    def instability(self) -> float:
        total = self.ca + self.ce
        if total == 0:
            return 0.0
        return self.ce / total

    @property
    def abstractness(self) -> float:
        total = self.abstract_classes + self.concrete_classes
        if total == 0:
            return 0.0
        return self.abstract_classes / total

    @property
    def distance(self) -> float:
        return abs(self.abstractness + self.instability - 1.0)

    @property
    def is_zone_of_pain(self) -> bool:
        return self.instability < 0.3 and self.abstractness < 0.3

    @property
    def is_zone_of_uselessness(self) -> bool:
        return self.instability > 0.7 and self.abstractness > 0.7


# ---------------------------------------------------------------------------
# AST analysis
# ---------------------------------------------------------------------------


def _module_from_path(filepath: Path) -> str:
    return str(filepath.relative_to(SRC_ROOT).with_suffix("")).replace("/", ".")


def _extract_imports(filepath: Path) -> list[str]:
    """Return internal perplexity_cli modules imported by *filepath*."""
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"))
    except Exception:
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        _collect_internal_import(node, imports)
    return imports


def _collect_internal_import(node: ast.AST, imports: list[str]) -> None:
    if isinstance(node, ast.Import):
        _add_import_aliases(node.names, imports)
    elif (
        isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("perplexity_cli.")
    ):
        imports.append(node.module[len("perplexity_cli.") :])


def _add_import_aliases(aliases: list[ast.alias], imports: list[str]) -> None:
    for alias in aliases:
        if alias.name.startswith("perplexity_cli."):
            imports.append(alias.name[len("perplexity_cli.") :])


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
    """Heuristic: a class is abstract if it inherits ABC, Protocol, or has abstract methods."""
    for base in node.bases:
        if _is_abstract_base(base):
            return True
    return _has_abstract_method(node)


def _count_classes(filepath: Path) -> tuple[int, int]:
    """Return (abstract_classes, concrete_classes) for *filepath*."""
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"))
    except Exception:
        return 0, 0

    abstract = 0
    concrete = 0

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if _is_abstract_class(node):
                abstract += 1
            else:
                concrete += 1

    return abstract, concrete


# ---------------------------------------------------------------------------
# Graph building
# ---------------------------------------------------------------------------


def _build_import_graph(
    files: list[Path],
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, tuple[int, int]]]:
    """Build (efferent_map, afferent_map, abstractness_map) from *files*."""
    efferent: dict[str, set[str]] = defaultdict(set)
    afferent: dict[str, set[str]] = defaultdict(set)
    abstractness: dict[str, tuple[int, int]] = {}

    all_modules: set[str] = set()

    for filepath in files:
        module = _module_from_path(filepath)
        all_modules.add(module)

        abs_count, conc_count = _count_classes(filepath)
        abstractness[module] = (abs_count, conc_count)

        for imported in _extract_imports(filepath):
            # Resolve to top-level internal module
            target = imported.split(".")[0] if "." in imported else imported
            efferent[module].add(target)
            afferent[target].add(module)
            all_modules.add(target)

    return dict(efferent), dict(afferent), abstractness


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------


def _compute_metrics(
    modules: set[str],
    efferent: dict[str, set[str]],
    afferent: dict[str, set[str]],
    abstractness: dict[str, tuple[int, int]],
) -> list[ModuleMetrics]:
    """Compute ModuleMetrics for every module in *modules*."""
    results: list[ModuleMetrics] = []

    for module in sorted(modules):
        ce = len(efferent.get(module, set()))
        ca = len(afferent.get(module, set()))
        abs_c, conc_c = abstractness.get(module, (0, 0))

        results.append(
            ModuleMetrics(
                module=module,
                ca=ca,
                ce=ce,
                abstract_classes=abs_c,
                concrete_classes=conc_c,
            )
        )

    results.sort(key=lambda m: m.distance, reverse=True)
    return results


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def _collect_files() -> list[Path]:
    return sorted(
        f for f in SRC_ROOT.rglob("*.py") if "__pycache__" not in str(f) and f.name != "__init__.py"
    )


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _zone_label(m: ModuleMetrics) -> str:
    if m.is_zone_of_pain:
        return "PAIN"
    if m.is_zone_of_uselessness:
        return "USELESS"
    return ""


def _format_flagged_row(m: ModuleMetrics) -> str:
    return (
        f"{m.module:<35} {m.ca:>4} {m.ce:>4} "
        f"{m.instability:>6.2f} {m.abstractness:>6.2f} {m.distance:>6.2f} "
        f" {_zone_label(m)}"
    )


def _format_text(metrics: list[ModuleMetrics], threshold: float) -> str:
    flagged = [m for m in metrics if m.distance >= threshold]
    zones: list[str] = []

    zones.append(
        f"Coupling analysis: {len(metrics)} modules, {len(flagged)} flagged (D >= {threshold})\n"
    )

    if not flagged:
        zones.append("All modules are within acceptable distance from the main sequence.\n")
        return "\n".join(zones)

    zones.append(f"{'Module':<35} {'Ca':>4} {'Ce':>4} {'I':>6} {'A':>6} {'D':>6} {'Zone'}")
    zones.append("-" * 79)

    for m in flagged:
        zones.append(_format_flagged_row(m))

    zones.append("")
    zones.append("Zone of Pain (I < 0.3, A < 0.3): stable + concrete - rigid, hard to change.")
    zones.append(
        "Zone of Uselessness (I > 0.7, A > 0.7): unstable + abstract - no one depends on it."
    )
    zones.append(f"Threshold: D >= {threshold} is flagged. D = 0 means perfectly balanced.")
    return "\n".join(zones)


def _format_json(metrics: list[ModuleMetrics], threshold: float) -> str:
    flagged = [m for m in metrics if m.distance >= threshold]
    return json.dumps(
        {
            "total_modules": len(metrics),
            "flagged_count": len(flagged),
            "threshold": threshold,
            "flagged": [
                {
                    "module": m.module,
                    "ca": m.ca,
                    "ce": m.ce,
                    "instability": round(m.instability, 3),
                    "abstractness": round(m.abstractness, 3),
                    "distance": round(m.distance, 3),
                    "zone_of_pain": m.is_zone_of_pain,
                    "zone_of_uselessness": m.is_zone_of_uselessness,
                }
                for m in flagged
            ],
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(args: list[str]) -> tuple[bool, float, str | None]:
    json_mode = False
    threshold = DEFAULT_D_THRESHOLD
    single_module: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--json":
            json_mode = True
        elif arg == "--threshold":
            i += 1
            threshold = _parse_threshold_arg(args, i)
        elif arg == "--module":
            i += 1
            single_module = _parse_module_arg(args, i)
        i += 1

    return json_mode, threshold, single_module


def _parse_threshold_arg(args: list[str], i: int) -> float:
    if i >= len(args):
        print("--threshold requires a float value", file=sys.stderr)
        sys.exit(2)
    return float(args[i])


def _parse_module_arg(args: list[str], i: int) -> str:
    if i >= len(args):
        print("--module requires a module name", file=sys.stderr)
        sys.exit(2)
    return args[i]


def main() -> None:
    json_mode, threshold, single_module = _parse_args(sys.argv[1:])
    files = _collect_files()
    files = _filter_by_module(files, single_module)
    efferent, afferent, abstractness = _build_import_graph(files)
    metrics = _compute_metrics(
        set(efferent.keys()) | set(afferent.keys()), efferent, afferent, abstractness
    )

    if json_mode:
        print(_format_json(metrics, threshold))
    else:
        print(_format_text(metrics, threshold))


def _filter_by_module(files: list[Path], single_module: str | None) -> list[Path]:
    if single_module is None:
        return files
    filtered = [f for f in files if single_module in _module_from_path(f)]
    if not filtered:
        print(f"No files found for module: {single_module}", file=sys.stderr)
        sys.exit(1)
    return filtered


if __name__ == "__main__":
    main()
