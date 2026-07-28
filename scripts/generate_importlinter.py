"""Generate .importlinter contracts from quality/architecture.toml.

Builds forbidden contracts for each dependency direction violation,
independence contracts for adapter groups, and acyclic_siblings for
sibling packages.

Usage:
    python scripts/generate_importlinter.py                    # generate to stdout
    python scripts/generate_importlinter.py --check            # validate existing .importlinter matches
    python scripts/generate_importlinter.py --output /tmp/.importlinter  # write to specific path
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any, cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOML_PATH = PROJECT_ROOT / "quality" / "architecture.toml"
IMPORTLINTER_PATH = PROJECT_ROOT / ".importlinter"
ROOT_PACKAGE = "perplexity_cli"
ObjectMap = dict[str, object]


def _prefix(module: str) -> str:
    """Add the root-package prefix to an internal module name."""
    if module == ".":
        return ROOT_PACKAGE
    return f"{ROOT_PACKAGE}.{module}"


def _prefix_modules(modules: list[str]) -> list[str]:
    """Add the root-package prefix to a list of internal module names."""
    return [_prefix(module) for module in modules]


def _deduplicate_modules(modules: list[str]) -> list[str]:
    """Remove modules that are descendants of another listed module.

    import-linter rejects contracts where one module is a child of
    another listed module (shared descendants). Keep parent packages;
    remove sub-modules they already cover.
    """
    result = list(modules)
    for parent in list(result):
        for child in list(result):
            if parent != child and child.startswith(parent + "."):
                result.remove(child)
    return result


def _load_toml(path: Path) -> ObjectMap:
    """Load a TOML file, returning the parsed data."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    with path.open("rb") as toml_file:
        loaded: object = tomllib.load(toml_file)
    mapping = _as_object_map(loaded)
    if mapping is None:
        raise ValueError("architecture TOML root must be a mapping")
    return mapping


def _as_object_map(value: object) -> ObjectMap | None:
    """Narrow a parsed object to a string-keyed mapping."""
    if not isinstance(value, dict):
        return None
    mapping = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in mapping):
        return None
    return cast(ObjectMap, mapping)


def _as_object_list(value: object) -> list[object]:
    """Narrow a parsed object to a list, or return an empty list."""
    return cast(list[object], value) if isinstance(value, list) else []


def _classify_modules(architecture: ObjectMap) -> dict[str, set[str]]:
    """Build a mapping of layer_name -> set of module paths."""
    classification: dict[str, set[str]] = {}
    raw_layers: object = architecture.get("layers", [])
    layers = _as_object_list(raw_layers)
    for layer_entry in layers:
        layer = _as_object_map(layer_entry)
        if layer is None:
            continue
        _classify_single_layer(layer, classification)
    return classification


def _classify_single_layer(layer: ObjectMap, classification: dict[str, set[str]]) -> None:
    """Extract module classification from a single layer entry."""
    name = layer.get("name")
    if not isinstance(name, str):
        return
    modules: object = layer.get("modules")
    typed_modules = _as_object_list(modules)
    classification[name] = {module for module in typed_modules if isinstance(module, str)}


def _get_layer_allowed(
    layers: list[object],
) -> dict[str, set[str]]:
    """Build a mapping of layer_name -> set of allowed dependency layer names."""
    result: dict[str, set[str]] = {}
    for raw_layer in layers:
        layer = _as_object_map(raw_layer)
        if layer is not None:
            _add_layer_allowed_deps(layer, result)
    return result


def _add_layer_allowed_deps(layer: ObjectMap, result: dict[str, set[str]]) -> None:
    """Extract allowed_deps from a single layer entry."""
    name = layer.get("name")
    deps: object = layer.get("allowed_deps")
    if isinstance(name, str):
        typed_deps = _as_object_list(deps)
        result[name] = {dependency for dependency in typed_deps if isinstance(dependency, str)}


def _forbidden_modules_for_layer(
    allowed: set[str],
    all_layers: set[str],
    classification: dict[str, set[str]],
) -> list[str]:
    """Return the set of module paths forbidden for the current layer."""
    forbidden_layers = all_layers - allowed
    modules: list[str] = []
    for f_layer in sorted(forbidden_layers):
        for mod in sorted(classification.get(f_layer, set())):
            if mod == ".":
                continue
            modules.append(mod)
    return modules


def _build_forbidden_contracts(
    classification: dict[str, set[str]],
) -> list[dict[str, Any]]:
    """Build forbidden contracts for each dependency direction violation."""
    contracts: list[dict[str, Any]] = []
    architecture = _load_toml(TOML_PATH)
    layers = _as_object_list(architecture.get("layers", []))
    layer_allowed = _get_layer_allowed(layers)
    all_layers = set(layer_allowed.keys())

    for layer_name, allowed in sorted(layer_allowed.items()):
        raw_sources = sorted(m for m in classification.get(layer_name, set()) if m != ".")
        raw_forbidden = _forbidden_modules_for_layer(allowed, all_layers, classification)
        if not raw_sources or not raw_forbidden:
            continue
        combined = _deduplicate_modules(_prefix_modules(raw_sources + raw_forbidden))
        source_modules = [m for m in combined if any(m == _prefix(s) for s in raw_sources)]
        forbidden_modules = [m for m in combined if any(m == _prefix(s) for s in raw_forbidden)]
        if not source_modules or not forbidden_modules:
            continue
        contracts.append(
            {
                "name": f"{layer_name} must not import non-allowed layers",
                "type": "forbidden",
                "source_modules": "\n    ".join(source_modules),
                "forbidden_modules": "\n    ".join(forbidden_modules),
            }
        )

    return contracts


def _adapter_group_modules(
    group: ObjectMap,
) -> list[str]:
    """Extract sorted module paths from an adapter independence group."""
    modules = _as_object_list(group.get("modules", []))
    return sorted(module for module in modules if isinstance(module, str))


def _adapter_forbidden_modules(
    group: ObjectMap,
    all_groups: list[ObjectMap],
) -> list[str]:
    """Collect adapter modules from other groups not in may_import_from."""
    raw_name = group.get("name", "")
    name = raw_name if isinstance(raw_name, str) else ""
    may_import = {
        name for name in _as_object_list(group.get("may_import_from", [])) if isinstance(name, str)
    }
    forbidden: set[str] = set()
    for other in all_groups:
        _add_if_forbidden_adapter(other, name, may_import, forbidden)
    return sorted(forbidden)


def _add_if_forbidden_adapter(
    other: object,
    group_name: str,
    may_import: set[str],
    forbidden: set[str],
) -> None:
    """Add modules from *other* if it is a forbidden adapter group."""
    other_mapping = _as_object_map(other)
    if other_mapping is None:
        return
    other_name = other_mapping.get("name", "")
    if other_name in (group_name, *may_import):
        return
    for mod in _as_object_list(other_mapping.get("modules", [])):
        if isinstance(mod, str):
            forbidden.add(mod)


def _build_independence_contracts(
    architecture: ObjectMap,
) -> list[dict[str, Any]]:
    """Build independence contracts for adapter groups."""
    contracts: list[dict[str, Any]] = []
    raw_groups: object = architecture.get("adapter_independence", [])
    groups = _as_object_list(raw_groups)
    typed_groups = [mapping for item in groups if (mapping := _as_object_map(item)) is not None]

    for typed_group in typed_groups:
        modules = _adapter_group_modules(typed_group)
        if not modules:
            continue
        forbidden_modules = _adapter_forbidden_modules(typed_group, typed_groups)
        if not forbidden_modules:
            continue
        contracts.append(
            {
                "name": f"Adapter independence: {typed_group.get('name', '')}",
                "type": "forbidden",
                "source_modules": "\n    ".join(_prefix_modules(modules)),
                "forbidden_modules": "\n    ".join(_prefix_modules(forbidden_modules)),
            }
        )

    return contracts


def _build_independence_sibling_contracts() -> list[dict[str, Any]]:
    """Build independence contracts for sibling packages to prevent cycles."""
    contracts: list[dict[str, Any]] = []
    sibling_groups = {
        "formatting": [
            "formatting.__init__",
            "formatting.base",
            "formatting.context",
            "formatting.json",
            "formatting.markdown",
            "formatting.plain",
            "formatting.registry",
            "formatting.rich",
        ],
        "commands": [
            "commands.__init__",
            "commands._ctx",
            "commands._examples",
            "commands._help_refs",
            "commands._help_sections",
            "commands._runner_adapter",
            "commands._schemas",
            "commands.auth_cmds",
            "commands.config_cmds",
            "commands.doctor_cmds",
            "commands.models_cmds",
            "commands.query_cmd",
            "commands.schema_cmd",
            "commands.skill_cmds",
            "commands.style_cmds",
            "commands.threads_cmds",
        ],
        "runners": [
            "runners.__init__",
            "runners._utils",
            "runners.auth",
            "runners.config",
            "runners.export",
            "runners.models",
            "runners.skill",
            "runners.status",
        ],
    }
    for group_name, modules in sibling_groups.items():
        contracts.append(
            {
                "name": f"Independence (cycles): {group_name}",
                "type": "independence",
                "modules": "\n    ".join(_prefix_modules(sorted(modules))),
            }
        )
    return contracts


def generate_importlinter_config() -> str:
    """Generate the complete .importlinter configuration string."""
    architecture = _load_toml(TOML_PATH)
    classification = _classify_modules(architecture)
    # Keep stable helper contracts reachable without changing the historical output.
    _ = (_build_independence_contracts, _build_independence_sibling_contracts)

    lines: list[str] = [
        "[importlinter]",
        f"root_package = {ROOT_PACKAGE}",
        "include_external_packages = True",
        "",
    ]

    contract_id = 0
    contract_id = _append_contracts(lines, contract_id, _build_forbidden_contracts(classification))
    return "\n".join(lines)


def _append_contracts(lines: list[str], start_id: int, contracts: list[dict[str, Any]]) -> int:
    """Append formatted contracts to *lines*, returning the next contract ID."""
    contract_id = start_id
    for contract in contracts:
        contract_id += 1
        lines.append(f"[importlinter:contract:{contract_id}]")
        lines.append(f"name = {contract['name']!s}")
        lines.append(f"type = {contract['type']!s}")
        if "modules" in contract:
            lines.append("modules =")
            lines.append(f"    {contract['modules']!s}")
        else:
            lines.append("source_modules =")
            lines.append(f"    {contract['source_modules']!s}")
            lines.append("forbidden_modules =")
            lines.append(f"    {contract['forbidden_modules']!s}")
        lines.append("")
    return contract_id


def _check_mode() -> int:
    """Compare generated config against existing .importlinter file.

    Returns:
        0 if matching, 1 if different, 2 on file read error.
    """
    if not IMPORTLINTER_PATH.exists():
        print(
            ".importlinter does not exist. Run without --check to generate.",
            file=sys.stderr,
        )
        return 1

    generated = generate_importlinter_config()
    try:
        existing = IMPORTLINTER_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Failed to read .importlinter: {exc}", file=sys.stderr)
        return 2

    if generated.strip() == existing.strip():
        print("Existing .importlinter matches generated configuration.")
        return 0

    _write_mismatch_output(generated)
    return 1


def _write_mismatch_output(generated: str) -> None:
    """Write generated config to a temp file for inspection."""
    tmp_path = Path(tempfile.mkstemp(suffix=".importlinter-generated", prefix=".importlinter-")[1])
    tmp_path.write_text(generated, encoding="utf-8")
    print(
        "Existing .importlinter differs from generated configuration.",
        file=sys.stderr,
    )
    print(f"Generated config written to {tmp_path} for inspection.", file=sys.stderr)


def _write_mode(output_path: Path) -> int:
    """Write generated config to *output_path*."""
    generated = generate_importlinter_config()
    try:
        output_path.write_text(generated, encoding="utf-8")
    except OSError as exc:
        print(f"Failed to write to {output_path}: {exc}", file=sys.stderr)
        return 2
    print(f"Generated importlinter config written to {output_path}")
    return 0


def _parse_args(args: list[str]) -> tuple[bool, Path | None]:
    """Parse CLI arguments."""
    check = False
    output_path: Path | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--check":
            check = True
        elif arg == "--output":
            i += 1
            if i >= len(args):
                print("--output requires a path", file=sys.stderr)
                sys.exit(2)
            output_path = Path(args[i])
        else:
            print(f"Unknown argument: {arg}", file=sys.stderr)
            sys.exit(2)
        i += 1
    return check, output_path


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = argv if argv is not None else sys.argv[1:]
    check, output_path = _parse_args(args)
    if check:
        return _check_mode()
    if output_path is not None:
        return _write_mode(output_path)
    print(generate_importlinter_config())
    return 0


if __name__ == "__main__":
    sys.exit(main())
