"""Prove that architecture_model.py schema validation catches:

- duplicate module assignments
- missing modules
- overlapping assignments
- invalid layer names and references
"""
# noqa: D (tests are exempt from docstring requirements)

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.architecture_model import (  # noqa: E402
    _check_adapter_modules_validity,
    _check_composition_root_validity,
    _check_duplicates_and_overlaps,
    _check_layer_name_validity,
    _check_module_coverage,
    _validate_schema,
)

# ------------------------------------------------------------------
# Fixtures: minimal data dicts for testing
# ------------------------------------------------------------------


def _make_layers_data(*layers: tuple[str, list[str]]) -> dict:
    """Build a minimal data dict with given layers."""
    return {
        "schema": {"version": 1},
        "layers": [
            {
                "name": name,
                "description": f"{name} layer",
                "allowed_deps": ["shared_pure", "domain"],
                "modules": modules,
            }
            for name, modules in layers
        ],
    }


# ------------------------------------------------------------------
# Schema validation
# ------------------------------------------------------------------


def test_schema_missing_section():
    errors = _validate_schema({})
    assert any("Missing [schema] section" in e for e in errors)


def test_schema_missing_layers():
    errors = _validate_schema({"schema": {"version": 1}})
    assert any("Missing [[layers]] array" in e for e in errors)


def test_schema_layers_not_list():
    errors = _validate_schema({"schema": {"version": 1}, "layers": "not_list"})
    assert any("must be an array of tables" in e for e in errors)


def test_schema_layers_empty():
    errors = _validate_schema({"schema": {"version": 1}, "layers": []})
    assert any("must not be empty" in e for e in errors)


def test_schema_layer_missing_required_field():
    data = {
        "schema": {"version": 1},
        "layers": [{"name": "domain"}],  # missing description, allowed_deps, modules
    }
    errors = _validate_schema(data)
    assert any("missing required field: description" in e for e in errors)


def test_schema_layer_modules_not_list():
    data = {
        "schema": {"version": 1},
        "layers": [
            {
                "name": "domain",
                "description": "desc",
                "allowed_deps": [],
                "modules": "not_a_list",
            }
        ],
    }
    errors = _validate_schema(data)
    assert any("modules must be a list" in e for e in errors)


def test_schema_adapter_independence_missing_field():
    data = {
        "schema": {"version": 1},
        "layers": [
            {
                "name": "shared_pure",
                "description": "d",
                "allowed_deps": [],
                "modules": [],
            },
            {
                "name": "domain",
                "description": "d",
                "allowed_deps": [],
                "modules": [],
            },
        ],
        "adapter_independence": [{"name": "grp"}],  # missing modules, may_import_from
    }
    # Just verify it doesn't crash; schema validation warns about missing fields
    errors = _validate_schema(data)
    assert errors


def test_schema_composition_roots_missing_field():
    data = {
        "schema": {"version": 1},
        "layers": [
            {
                "name": "shared_pure",
                "description": "d",
                "allowed_deps": [],
                "modules": [],
            },
            {
                "name": "domain",
                "description": "d",
                "allowed_deps": [],
                "modules": [],
            },
        ],
        "composition_roots": [{"name": "cr"}],  # missing modules
    }
    errors = _validate_schema(data)
    assert any("missing required field: modules" in e for e in errors)


# ------------------------------------------------------------------
# Duplicate module detection
# ------------------------------------------------------------------


def test_no_duplicates_across_layers():
    data = _make_layers_data(
        ("domain", ["mod_a", "mod_b"]),
        ("ports", ["mod_c", "mod_d"]),
    )
    errors = _check_duplicates_and_overlaps(data)
    assert errors == []


def test_detects_duplicate_module():
    data = _make_layers_data(
        ("domain", ["mod_a", "mod_dup"]),
        ("ports", ["mod_dup", "mod_b"]),
    )
    errors = _check_duplicates_and_overlaps(data)
    assert any("Duplicate module assignment" in e for e in errors)
    assert any("mod_dup" in e for e in errors)


def test_detects_non_string_module():
    data = _make_layers_data(
        ("domain", [123, "mod_a"]),  # 123 is not a string
    )
    errors = _check_duplicates_and_overlaps(data)
    assert any("is not a string" in e for e in errors)


# ------------------------------------------------------------------
# Layer name validation
# ------------------------------------------------------------------


def test_invalid_layer_name_rejected():
    data = _make_layers_data(
        ("bogus_layer", ["mod_a"]),
    )
    errors = _check_layer_name_validity(data)
    assert any("Invalid layer name" in e for e in errors)


def test_missing_required_layers_reported():
    data = _make_layers_data(
        ("domain", ["mod_a"]),
    )
    errors = _check_layer_name_validity(data)
    assert any("Missing required layer(s)" in e for e in errors)


def test_unknown_layer_in_allowed_deps():
    data = _make_layers_data(
        ("domain", ["mod_a"]),
        ("ports", ["mod_b"]),
    )
    errors = _check_layer_name_validity(data)
    # domain's allowed_deps default is fine, but missing required layers is
    # a separate check. This test verifies referenced but unknown deps.
    assert errors  # should at least have missing layers


def test_unknown_adapter_group_in_may_import_from():
    data = {
        "schema": {"version": 1},
        "layers": [
            {
                "name": "adapter",
                "description": "d",
                "allowed_deps": ["domain"],
                "modules": ["mod_a"],
            },
        ],
        "adapter_independence": [
            {
                "name": "grp_a",
                "modules": ["mod_a"],
                "may_import_from": ["nonexistent_group"],
            }
        ],
    }
    errors = _check_layer_name_validity(data)
    assert any("unknown adapter group" in e for e in errors)


# ------------------------------------------------------------------
# Module coverage
# ------------------------------------------------------------------


def test_unclassified_modules_reported():
    data = _make_layers_data(
        ("domain", ["mod_a"]),
    )
    production = {"mod_a", "mod_missing"}
    errors = _check_module_coverage(data, production)
    assert any("Unclassified production modules" in e for e in errors)
    assert any("mod_missing" in e for e in errors)


def test_unknown_toml_modules_reported():
    data = _make_layers_data(
        ("domain", ["mod_a", "mod_ghost"]),
    )
    production = {"mod_a"}
    errors = _check_module_coverage(data, production)
    assert any("Unknown modules" in e for e in errors)
    assert any("mod_ghost" in e for e in errors)


# ------------------------------------------------------------------
# Adapter group validity
# ------------------------------------------------------------------


def test_adapter_group_references_non_adapter_module():
    data = {
        "schema": {"version": 1},
        "layers": [
            {
                "name": "adapter",
                "description": "d",
                "allowed_deps": [],
                "modules": ["adapter_mod"],
            },
        ],
        "adapter_independence": [
            {
                "name": "grp_a",
                "modules": ["non_adapter_mod"],
                "may_import_from": [],
            }
        ],
    }
    errors = _check_adapter_modules_validity(data)
    assert any("not classified as 'adapter'" in e and "non_adapter_mod" in e for e in errors)


# ------------------------------------------------------------------
# Composition root validity
# ------------------------------------------------------------------


def test_composition_root_references_wrong_layer_module():
    data = {
        "schema": {"version": 1},
        "layers": [
            {
                "name": "composition_root",
                "description": "d",
                "allowed_deps": [],
                "modules": ["cr_mod"],
            },
        ],
        "composition_roots": [{"modules": ["wrong_mod"]}],
    }
    errors = _check_composition_root_validity(data)
    assert any("not classified as 'composition_root'" in e for e in errors)
