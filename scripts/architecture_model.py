"""Validator for quality/architecture.toml — the canonical module-to-layer classification.

Validates schema structure, detects duplicate/overlapping/missing module
assignments, rejects invalid layer names and references.

Usage:
    python scripts/architecture_model.py                        # validate against current source tree
    python scripts/architecture_model.py --toml other.toml      # validate a specific TOML file
    python scripts/architecture_model.py --check-only           # only check TOML, not module coverage
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOML_PATH = PROJECT_ROOT / "quality" / "architecture.toml"
SRC_ROOT = PROJECT_ROOT / "src" / "perplexity_cli"

VALID_LAYER_NAMES = frozenset(
    {
        "shared_pure",
        "domain",
        "ports",
        "application",
        "adapter",
        "presentation",
        "composition_root",
    }
)

_REQUIRED_LAYER_FIELDS = ("name", "description", "allowed_deps", "modules")
_REQUIRED_INDEP_FIELDS = ("name", "modules", "may_import_from")


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file, returning the parsed data."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        print(f"TOML file not found: {path}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Failed to parse TOML file {path}: {exc}", file=sys.stderr)
        sys.exit(1)


def _collect_production_modules(src_root: Path) -> set[str]:
    """Return the set of dotted module paths for all .py files under src_root.

    __init__.py files are mapped to their parent package name.
    """
    modules: set[str] = set()
    for pyfile in sorted(src_root.rglob("*.py")):
        if "__pycache__" in str(pyfile):
            continue
        rel = pyfile.relative_to(src_root)
        if rel.name == "__init__.py":
            modules.add(str(rel.parent).replace("/", "."))
        else:
            modules.add(str(rel.with_suffix("")).replace("/", "."))
    return modules


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def _validate_schema_section(data: dict[str, Any]) -> list[str]:
    """Validate the [schema] top-level section."""
    errors: list[str] = []
    schema = data.get("schema")
    if schema is None:
        errors.append("Missing [schema] section")
        return errors
    if not isinstance(schema, dict):
        errors.append("[schema] must be a table")
        return errors
    if "version" not in schema:
        errors.append("[schema] missing required field: version")
    return errors


def _validate_layers_array(data: dict[str, Any]) -> list[str]:
    """Validate the [[layers]] array exists and has entries."""
    errors: list[str] = []
    layers = data.get("layers")
    if layers is None:
        errors.append("Missing [[layers]] array")
        return errors
    if not isinstance(layers, list):
        errors.append("[[layers]] must be an array of tables")
        return errors
    if len(layers) == 0:
        errors.append("[[layers]] array must not be empty")
    return errors


def _validate_individual_layer(layer: dict[str, Any], i: int) -> list[str]:
    """Validate a single layer entry at index *i*."""
    errors: list[str] = []
    if not isinstance(layer, dict):
        errors.append(f"layers[{i}] must be a table")
        return errors
    _check_layer_required_fields(layer, i, errors)
    _check_layer_list_fields(layer, i, errors)
    return errors


def _check_layer_required_fields(layer: dict[str, Any], i: int, errors: list[str]) -> None:
    """Check required fields exist in a layer entry."""
    for field in _REQUIRED_LAYER_FIELDS:
        if field not in layer:
            errors.append(f"layers[{i}] missing required field: {field}")


def _check_layer_list_fields(layer: dict[str, Any], i: int, errors: list[str]) -> None:
    """Check that list-typed fields in a layer entry are actually lists."""
    if not isinstance(layer.get("modules"), list):
        errors.append(f"layers[{i}].modules must be a list")
    if not isinstance(layer.get("allowed_deps"), list):
        errors.append(f"layers[{i}].allowed_deps must be a list")


def _validate_adapter_groups(data: dict[str, Any]) -> list[str]:
    """Validate [[adapter_independence]] entries."""
    errors: list[str] = []
    for i, indep in enumerate(data.get("adapter_independence", [])):
        if not isinstance(indep, dict):
            errors.append(f"adapter_independence[{i}] must be a table")
            continue
        for field in _REQUIRED_INDEP_FIELDS:
            if field not in indep:
                errors.append(f"adapter_independence[{i}] missing required field: {field}")
    return errors


def _validate_composition_roots_section(data: dict[str, Any]) -> list[str]:
    """Validate [[composition_roots]] entries."""
    errors: list[str] = []
    for i, crate_root in enumerate(data.get("composition_roots", [])):
        if not isinstance(crate_root, dict):
            errors.append(f"composition_roots[{i}] must be a table")
            continue
        if "modules" not in crate_root:
            errors.append(f"composition_roots[{i}] missing required field: modules")
    return errors


def _validate_schema(data: dict[str, Any]) -> list[str]:
    """Validate the full TOML structure. Returns list of error messages."""
    errors: list[str] = []
    errors.extend(_validate_schema_section(data))
    errors.extend(_validate_layers_array(data))
    if "layers" in data and isinstance(data["layers"], list):
        for i, layer_raw in enumerate(data["layers"]):
            if isinstance(layer_raw, dict):
                layer = cast(dict[str, Any], layer_raw)
                errors.extend(_validate_individual_layer(layer, i))
    errors.extend(_validate_adapter_groups(data))
    errors.extend(_validate_composition_roots_section(data))
    return errors


# ---------------------------------------------------------------------------
# Duplicate / overlap detection
# ---------------------------------------------------------------------------


def _collect_classified_modules(
    layers: list[dict[str, Any]],
) -> dict[str, str]:
    """Build a mapping of module -> layer_name, reporting duplicates."""
    seen: dict[str, str] = {}
    for layer in layers:
        name = layer.get("name", "<unnamed>")
        modules = layer.get("modules", [])
        if not isinstance(modules, list):
            continue
        for mod in modules:
            if isinstance(mod, str):
                seen[mod] = name
    return seen


def _check_layer_modules_for_duplicates(
    layer: dict[str, Any], seen: dict[str, str], errors: list[str]
) -> None:
    """Check modules in a single layer for duplicates against *seen*."""
    name = layer.get("name", "<unnamed>")
    for mod in layer.get("modules", []):
        if not isinstance(mod, str):
            errors.append(f"Module in layer '{name}' is not a string: {mod!r}")
            continue
        if mod in seen:
            errors.append(
                f"Duplicate module assignment: '{mod}' assigned to both '{seen[mod]}' and '{name}'"
            )
        seen[mod] = name


def _check_duplicates_and_overlaps(data: dict[str, Any]) -> list[str]:
    """Check for duplicate or overlapping module assignments across layers."""
    errors: list[str] = []
    seen: dict[str, str] = {}
    for layer in data.get("layers", []):
        if isinstance(layer.get("modules"), list):
            _check_layer_modules_for_duplicates(layer, seen, errors)
    return errors


# ---------------------------------------------------------------------------
# Layer name validation
# ---------------------------------------------------------------------------


def _validate_layer_deps(
    layer: dict[str, Any],
) -> list[str]:
    """Validate that a layer's allowed_deps reference valid layer names."""
    errors: list[str] = []
    name = layer.get("name", "<unnamed>")
    for dep in layer.get("allowed_deps", []):
        if not isinstance(dep, str):
            errors.append(f"Layer '{name}' has non-string allowed_deps entry: {dep!r}")
        elif dep not in VALID_LAYER_NAMES:
            errors.append(
                f"Layer '{name}' references unknown layer '{dep}' in "
                f"allowed_deps. Valid layers: "
                f"{', '.join(sorted(VALID_LAYER_NAMES))}"
            )
    return errors


def _validate_layer_names(layers: list[dict[str, Any]]) -> list[str]:
    """Validate that all layer names are valid and no required layers are missing."""
    errors: list[str] = []
    specified: set[str] = set()

    for layer in layers:
        name = layer.get("name")
        if not isinstance(name, str):
            errors.append(f"Layer name is not a string: {name!r}")
            continue
        if name not in VALID_LAYER_NAMES:
            errors.append(
                f"Invalid layer name '{name}' — must be one of: "
                f"{', '.join(sorted(VALID_LAYER_NAMES))}"
            )
        specified.add(name)

    missing = VALID_LAYER_NAMES - specified
    if missing:
        errors.append(f"Missing required layer(s): {', '.join(sorted(missing))}")

    return errors


def _check_single_adapter_refs(
    ai: dict[str, Any], adapter_names: set[str], errors: list[str]
) -> None:
    """Check may_import_from references for a single adapter group."""
    ai_name = ai.get("name", "<unnamed>")
    for dep_name in ai.get("may_import_from", []):
        if isinstance(dep_name, str) and dep_name not in adapter_names:
            errors.append(
                f"Adapter independence group '{ai_name}' references "
                f"unknown adapter group '{dep_name}' in may_import_from"
            )


def _validate_adapter_refs(data: dict[str, Any]) -> list[str]:
    """Validate that adapter_independence may_import_from references are valid."""
    errors: list[str] = []
    adapter_indep = data.get("adapter_independence", [])
    adapter_names = {ai.get("name") for ai in adapter_indep if isinstance(ai.get("name"), str)}
    for ai in adapter_indep:
        if isinstance(ai, dict):
            _check_single_adapter_refs(ai, adapter_names, errors)
    return errors


def _check_layer_name_validity(data: dict[str, Any]) -> list[str]:
    """Validate that all layer names and allowed_deps references are valid."""
    errors: list[str] = []
    layers = data.get("layers", [])
    if not isinstance(layers, list):
        return errors

    errors.extend(_validate_layer_names(layers))
    for layer in layers:
        if isinstance(layer, dict):
            errors.extend(_validate_layer_deps(layer))
    errors.extend(_validate_adapter_refs(data))
    return errors


# ---------------------------------------------------------------------------
# Module coverage
# ---------------------------------------------------------------------------


def _get_classified_modules(data: dict[str, Any]) -> set[str]:
    """Extract all classified module paths from all layers."""
    classified: set[str] = set()
    layers = data.get("layers", [])
    if not isinstance(layers, list):
        return classified
    for layer in layers:
        for mod in layer.get("modules", []):
            if isinstance(mod, str):
                classified.add(mod)
    return classified


def _check_module_coverage(data: dict[str, Any], production_modules: set[str]) -> list[str]:
    """Check that all production modules are classified and no unknown modules exist."""
    errors: list[str] = []
    classified = _get_classified_modules(data)

    unclassified = production_modules - classified
    if unclassified:
        errors.append(
            f"Unclassified production modules ({len(unclassified)}): "
            f"{', '.join(sorted(unclassified))}"
        )

    unknown = classified - production_modules
    if unknown:
        errors.append(
            f"Unknown modules in architecture.toml (not found in source tree): "
            f"{', '.join(sorted(unknown))}"
        )

    return errors


# ---------------------------------------------------------------------------
# Adapter group validity
# ---------------------------------------------------------------------------


def _add_module_strings(modules_container: list[Any], target: set[str]) -> None:
    """Add string entries from a modules list into *target* set."""
    for mod in modules_container:
        if isinstance(mod, str):
            target.add(mod)


def _collect_layer_modules(data: dict[str, Any], target_layer: str) -> set[str]:
    """Collect all module paths classified as *target_layer*."""
    modules: set[str] = set()
    layers = data.get("layers", [])
    if not isinstance(layers, list):
        return modules
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        if layer.get("name") == target_layer:
            _add_module_strings(layer.get("modules", []), modules)
    return modules


def _check_adapter_modules_validity(data: dict[str, Any]) -> list[str]:
    """Check that all modules in adapter groups are classified as adapter."""
    errors: list[str] = []
    adapter_modules = _collect_layer_modules(data, "adapter")

    for ai in data.get("adapter_independence", []):
        ai_name = ai.get("name", "<unnamed>")
        for mod in ai.get("modules", []):
            if isinstance(mod, str) and mod not in adapter_modules:
                errors.append(
                    f"Adapter independence group '{ai_name}' references "
                    f"module '{mod}' which is not classified as 'adapter'"
                )

    return errors


# ---------------------------------------------------------------------------
# Composition root validity
# ---------------------------------------------------------------------------


def _check_composition_root_validity(data: dict[str, Any]) -> list[str]:
    """Check composition_roots modules match composition_root layer."""
    errors: list[str] = []
    cr_modules = _collect_layer_modules(data, "composition_root")

    for cr in data.get("composition_roots", []):
        for mod in cr.get("modules", []):
            if isinstance(mod, str) and mod not in cr_modules:
                errors.append(
                    f"composition_roots references module '{mod}' "
                    f"which is not classified as 'composition_root'"
                )

    return errors


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def validate(toml_path: Path, src_root: Path, check_modules: bool = True) -> list[str]:
    """Validate the architecture TOML file. Returns a list of error messages.

    Args:
        toml_path: Path to the architecture.toml file.
        src_root: Path to the source root directory.
        check_modules: If True, also check module coverage against the source tree.

    Returns:
        List of error messages. Empty list means validation passed.
    """
    data = _load_toml(toml_path)
    errors: list[str] = []

    errors.extend(_validate_schema(data))
    errors.extend(_check_duplicates_and_overlaps(data))
    errors.extend(_check_layer_name_validity(data))
    errors.extend(_check_adapter_modules_validity(data))
    errors.extend(_check_composition_root_validity(data))

    if check_modules:
        production_modules = _collect_production_modules(src_root)
        errors.extend(_check_module_coverage(data, production_modules))

    return errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(
    args: list[str],
) -> tuple[Path, bool]:
    """Parse CLI arguments. Returns (toml_path, check_modules)."""
    toml_path = DEFAULT_TOML_PATH
    check_modules = True
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--toml":
            i += 1
            if i >= len(args):
                print("--toml requires a path", file=sys.stderr)
                sys.exit(2)
            toml_path = Path(args[i])
        elif arg == "--check-only":
            check_modules = False
        else:
            print(f"Unknown argument: {arg}", file=sys.stderr)
            sys.exit(2)
        i += 1
    return toml_path, check_modules


def main(argv: list[str] | None = None) -> int:
    """Run architecture TOML validation."""
    args = argv if argv is not None else sys.argv[1:]
    toml_path, check_modules = _parse_args(args)

    if not toml_path.exists():
        print(f"TOML file not found: {toml_path}", file=sys.stderr)
        return 1

    errors = validate(toml_path, SRC_ROOT, check_modules=check_modules)

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        print(f"{len(errors)} validation error(s) found.", file=sys.stderr)
        return 1

    print("Architecture TOML validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
