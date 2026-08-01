"""Property-test marker, manifest, and reproduction-helper policy tests.

The repository manifest must exactly match supported top-level Hypothesis
properties. Marker checks cover explicit function markers and the designated
module marker; reproduction tests validate a command helper rather than
claiming that Hypothesis failures invoke it automatically.
"""

from __future__ import annotations

import ast
import re
import tomllib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MAKEFILE = _REPO_ROOT / "Makefile"
_PROPERTY_INVENTORY = _REPO_ROOT / "quality/property-inventory.toml"
_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_PROPERTY_FILES_PREFIX = "override PROPERTY_TEST_FILES :="
_SAFE_PROPERTY_PATH = re.compile(r"[A-Za-z0-9_./-]+\.py")


def _load_property_test_files(makefile: Path, repo_root: Path) -> tuple[Path, ...]:
    """Load the independently declared property source paths from Make."""
    assignments = [
        line.removeprefix(_PROPERTY_FILES_PREFIX).strip()
        for line in makefile.read_text(encoding="utf-8").splitlines()
        if line.startswith(_PROPERTY_FILES_PREFIX)
    ]
    if len(assignments) != 1:
        raise ValueError("Makefile must declare PROPERTY_TEST_FILES exactly once")
    tokens = tuple(assignments[0].split())
    if not tokens or any(_is_unsafe_property_path(token) for token in tokens):
        raise ValueError("PROPERTY_TEST_FILES must contain safe repository-relative paths")
    paths = tuple(repo_root / token for token in tokens)
    if any(not path.is_file() for path in paths):
        raise ValueError("PROPERTY_TEST_FILES must reference existing files")
    return paths


def _is_unsafe_property_path(value: str) -> bool:
    """Return whether a Make property source could escape or expand dynamically."""
    path = Path(value)
    return path.is_absolute() or ".." in path.parts or _SAFE_PROPERTY_PATH.fullmatch(value) is None


_PROPERTY_TEST_FILES = _load_property_test_files(_MAKEFILE, _REPO_ROOT)


@dataclass(frozen=True, slots=True)
class _GivenBindings:
    direct: frozenset[str]
    modules: frozenset[str]


@dataclass(frozen=True, slots=True)
class _PropertyFunction:
    node_id: str
    source_path: Path
    name: str
    lineno: int
    has_property_marker: bool


@dataclass(frozen=True, slots=True)
class _PropertyDiscovery:
    functions: tuple[_PropertyFunction, ...]
    duplicate_ids: tuple[str, ...]

    @property
    def node_ids(self) -> frozenset[str]:
        return frozenset(function.node_id for function in self.functions)


@dataclass(frozen=True, slots=True)
class _InventoryProperty:
    node_id: str
    oracle_type: str
    rationale: str


@dataclass(frozen=True, slots=True)
class _ManifestParity:
    source_only: tuple[str, ...]
    inventory_only: tuple[str, ...]
    source_duplicates: tuple[str, ...]
    inventory_duplicates: tuple[str, ...]

    @property
    def is_exact(self) -> bool:
        return not any(
            (
                self.source_only,
                self.inventory_only,
                self.source_duplicates,
                self.inventory_duplicates,
            )
        )


class _UnsupportedPropertyPlacement(ValueError):
    """Raised when a Hypothesis property is nested or defined on a class."""


def _given_bindings(tree: ast.Module) -> _GivenBindings:
    direct: set[str] = set()
    modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "hypothesis":
            direct.update(
                alias.asname or alias.name for alias in node.names if alias.name == "given"
            )
        if isinstance(node, ast.Import):
            modules.update(
                alias.asname or "hypothesis" for alias in node.names if alias.name == "hypothesis"
            )
    return _GivenBindings(frozenset(direct), frozenset(modules))


def _is_given_decorator(decorator: ast.expr, bindings: _GivenBindings) -> bool:
    if not isinstance(decorator, ast.Call):
        return False
    if isinstance(decorator.func, ast.Name):
        return decorator.func.id in bindings.direct
    return (
        isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr == "given"
        and isinstance(decorator.func.value, ast.Name)
        and decorator.func.value.id in bindings.modules
    )


def _has_given_decorator(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    bindings: _GivenBindings,
) -> bool:
    return any(_is_given_decorator(decorator, bindings) for decorator in node.decorator_list)


def _has_property_marker(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        marker = decorator.func if isinstance(decorator, ast.Call) else decorator
        if (
            isinstance(marker, ast.Attribute)
            and marker.attr == "property"
            and isinstance(marker.value, ast.Attribute)
            and marker.value.attr == "mark"
            and isinstance(marker.value.value, ast.Name)
            and marker.value.value.id == "pytest"
        ):
            return True
    return False


def _relative_source_path(source_path: Path, repo_root: Path) -> str:
    try:
        return source_path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as error:
        message = f"Property source must be inside repository root: {source_path}"
        raise ValueError(message) from error


def _discover_source(source_path: Path, repo_root: Path) -> tuple[_PropertyFunction, ...]:
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    bindings = _given_bindings(tree)
    top_level_functions = {
        id(node): node for node in tree.body if isinstance(node, _FUNCTION_NODES)
    }
    decorated = [
        node
        for node in ast.walk(tree)
        if isinstance(node, _FUNCTION_NODES) and _has_given_decorator(node, bindings)
    ]
    unsupported = [node for node in decorated if id(node) not in top_level_functions]
    if unsupported:
        locations = ", ".join(f"{node.name}:{node.lineno}" for node in unsupported)
        message = f"Unsupported nested or class @given placement in {source_path}: {locations}"
        raise _UnsupportedPropertyPlacement(message)

    relative_path = _relative_source_path(source_path, repo_root)
    return tuple(
        _PropertyFunction(
            node_id=f"{relative_path}::{node.name}",
            source_path=source_path,
            name=node.name,
            lineno=node.lineno,
            has_property_marker=_has_property_marker(node),
        )
        for node in decorated
        if node.name.startswith("test_")
    )


def _discover_property_tests(
    source_paths: Sequence[Path],
    repo_root: Path,
) -> _PropertyDiscovery:
    functions = tuple(
        function
        for source_path in source_paths
        for function in _discover_source(source_path, repo_root)
    )
    counts = Counter(function.node_id for function in functions)
    duplicates = tuple(sorted(node_id for node_id, count in counts.items() if count > 1))
    return _PropertyDiscovery(functions, duplicates)


def _top_level_test_functions(
    source_path: Path,
) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    return tuple(
        node
        for node in tree.body
        if isinstance(node, _FUNCTION_NODES) and node.name.startswith("test_")
    )


def _has_module_property_marker(source_path: Path) -> bool:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets
        ):
            return _marker_collection_has_property(node.value)
    return False


def _marker_collection_has_property(value: ast.expr) -> bool:
    """Return whether a marker assignment directly contains the property marker."""
    values = value.elts if isinstance(value, ast.List | ast.Tuple | ast.Set) else (value,)
    return any(_is_property_marker(value) for value in values)


def _is_property_marker(value: ast.expr) -> bool:
    """Return whether an expression is exactly ``pytest.mark.property``."""
    return (
        isinstance(value, ast.Attribute)
        and value.attr == "property"
        and isinstance(value.value, ast.Attribute)
        and value.value.attr == "mark"
        and isinstance(value.value.value, ast.Name)
        and value.value.value.id == "pytest"
    )


def _load_inventory(inventory_path: Path) -> tuple[_InventoryProperty, ...]:
    data = tomllib.loads(inventory_path.read_text(encoding="utf-8"))
    if set(data) != {"schema_version", "property"} or data["schema_version"] != 1:
        raise ValueError("Property inventory must use schema_version = 1 and [[property]] entries")
    raw_properties = data["property"]
    if not isinstance(raw_properties, list):
        raise TypeError("Property inventory 'property' value must be a list")
    return tuple(_parse_inventory_property(value) for value in raw_properties)


def _parse_inventory_property(value: object) -> _InventoryProperty:
    expected_keys = {"node_id", "oracle_type", "rationale"}
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise ValueError("Each property entry must contain node_id, oracle_type, and rationale")
    fields = tuple(value[key] for key in ("node_id", "oracle_type", "rationale"))
    if not all(isinstance(field, str) and field.strip() for field in fields):
        raise ValueError("Property inventory fields must be non-empty strings")
    return _InventoryProperty(*fields)


def _compare_manifest(
    discovery: _PropertyDiscovery,
    inventory: Sequence[_InventoryProperty],
) -> _ManifestParity:
    inventory_counts = Counter(item.node_id for item in inventory)
    inventory_ids = frozenset(inventory_counts)
    return _ManifestParity(
        source_only=tuple(sorted(discovery.node_ids - inventory_ids)),
        inventory_only=tuple(sorted(inventory_ids - discovery.node_ids)),
        source_duplicates=discovery.duplicate_ids,
        inventory_duplicates=tuple(
            sorted(node_id for node_id, count in inventory_counts.items() if count > 1)
        ),
    )


def _format_ids(title: str, node_ids: Sequence[str]) -> str:
    values = "\n".join(f"  {node_id}" for node_id in node_ids) or "  (none)"
    return f"{title}:\n{values}"


def _format_parity_failure(parity: _ManifestParity) -> str:
    return "\n".join(
        (
            "PROPERTY MANIFEST POLICY VIOLATION",
            "==================================",
            _format_ids("Source-only IDs (missing from inventory)", parity.source_only),
            _format_ids("Inventory-only IDs (stale)", parity.inventory_only),
            _format_ids("Duplicate source IDs", parity.source_duplicates),
            _format_ids("Duplicate inventory IDs", parity.inventory_duplicates),
            "Run: pytest -p no:cacheprovider tests/test_property_policy.py -v",
        )
    )


def test_all_given_tests_have_property_marker() -> None:
    discovery = _discover_property_tests(_PROPERTY_TEST_FILES, _REPO_ROOT)
    module_markers = {
        source_path: _has_module_property_marker(source_path)
        for source_path in _PROPERTY_TEST_FILES
    }
    missing = [
        function.node_id
        for function in discovery.functions
        if not function.has_property_marker and not module_markers[function.source_path]
    ]
    assert not missing, _format_ids("@given tests missing the property marker", missing)


def test_explicit_property_markers_use_hypothesis() -> None:
    discovery = _discover_property_tests(_PROPERTY_TEST_FILES, _REPO_ROOT)
    given_locations = {(function.source_path, function.name) for function in discovery.functions}
    invalid = [
        f"{_relative_source_path(source_path, _REPO_ROOT)}::{node.name}"
        for source_path in _PROPERTY_TEST_FILES
        for node in _top_level_test_functions(source_path)
        if _has_property_marker(node) and (source_path, node.name) not in given_locations
    ]
    assert not invalid, _format_ids("Explicit property markers without @given", invalid)


def test_property_inventory_exactly_matches_source() -> None:
    discovery = _discover_property_tests(_PROPERTY_TEST_FILES, _REPO_ROOT)
    parity = _compare_manifest(discovery, _load_inventory(_PROPERTY_INVENTORY))
    assert parity.is_exact, _format_parity_failure(parity)


def test_property_source_scope_comes_from_make() -> None:
    """The manifest cannot reduce the independently declared source scope."""
    assert _PROPERTY_TEST_FILES
    assert all(path.is_file() and path.is_relative_to(_REPO_ROOT) for path in _PROPERTY_TEST_FILES)


def test_property_source_scope_rejects_unsafe_or_duplicate_assignments(tmp_path: Path) -> None:
    """Malformed Make source declarations fail closed."""
    makefile = tmp_path / "Makefile"
    makefile.write_text(
        "override PROPERTY_TEST_FILES := ../outside.py\n"
        "override PROPERTY_TEST_FILES := tests/test_other.py\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="exactly once"):
        _load_property_test_files(makefile, tmp_path)


@pytest.mark.parametrize(
    "marker_value",
    ['"pytest.mark.property"', "pytest.mark.property if False else pytest.mark.slow"],
)
def test_module_property_marker_rejects_non_marker_expressions(
    tmp_path: Path, marker_value: str
) -> None:
    """Strings and conditional expressions do not satisfy marker policy."""
    source_path = _write_synthetic_source(
        tmp_path,
        f"import pytest\npytestmark = [{marker_value}]\n",
    )
    assert not _has_module_property_marker(source_path)


def _write_synthetic_source(tmp_path: Path, source: str) -> Path:
    source_path = tmp_path / "test_synthetic.py"
    source_path.write_text(source, encoding="utf-8")
    return source_path


def test_discovery_supports_direct_aliased_module_and_async_forms(tmp_path: Path) -> None:
    source_path = _write_synthetic_source(
        tmp_path,
        """
from hypothesis import given
from hypothesis import given as generated
import hypothesis
import hypothesis as hyp

@given(value=None)
def test_direct(value): pass

@generated(value=None)
def test_direct_alias(value): pass

@hypothesis.given(value=None)
def test_module(value): pass

@hyp.given(value=None)
async def test_module_alias(value): pass
""",
    )
    discovery = _discover_property_tests((source_path,), tmp_path)
    assert discovery.node_ids == {
        "test_synthetic.py::test_direct",
        "test_synthetic.py::test_direct_alias",
        "test_synthetic.py::test_module",
        "test_synthetic.py::test_module_alias",
    }


def test_discovery_ignores_unrelated_given_attribute(tmp_path: Path) -> None:
    source_path = _write_synthetic_source(
        tmp_path,
        """
import unrelated

@unrelated.given(value=None)
def test_not_hypothesis(value): pass
""",
    )
    assert not _discover_property_tests((source_path,), tmp_path).node_ids


@pytest.mark.parametrize(
    "source",
    [
        """
from hypothesis import given
def outer():
    @given(value=None)
    def test_nested(value): pass
""",
        """
from hypothesis import given
class TestProperties:
    @given(value=None)
    def test_method(self, value): pass
""",
    ],
)
def test_discovery_rejects_unsupported_property_placements(
    tmp_path: Path,
    source: str,
) -> None:
    source_path = _write_synthetic_source(tmp_path, source)
    with pytest.raises(_UnsupportedPropertyPlacement, match="Unsupported nested or class"):
        _discover_property_tests((source_path,), tmp_path)


def test_discovery_reports_duplicate_source_ids(tmp_path: Path) -> None:
    source_path = _write_synthetic_source(
        tmp_path,
        """
from hypothesis import given
@given(value=None)
def test_duplicate(value): pass
@given(value=None)
def test_duplicate(value): pass
""",
    )
    discovery = _discover_property_tests((source_path,), tmp_path)
    assert discovery.duplicate_ids == ("test_synthetic.py::test_duplicate",)


def test_manifest_comparison_separates_missing_stale_and_duplicate_ids() -> None:
    source_function = _PropertyFunction(
        "tests/test_source.py::test_missing",
        Path("tests/test_source.py"),
        "test_missing",
        1,
        False,
    )
    discovery = _PropertyDiscovery(
        functions=(source_function,),
        duplicate_ids=("tests/test_source.py::test_source_duplicate",),
    )
    stale = _InventoryProperty("tests/test_source.py::test_stale", "invariant", "Reviewed")
    parity = _compare_manifest(discovery, (stale, stale))

    assert parity.source_only == ("tests/test_source.py::test_missing",)
    assert parity.inventory_only == ("tests/test_source.py::test_stale",)
    assert parity.source_duplicates == ("tests/test_source.py::test_source_duplicate",)
    assert parity.inventory_duplicates == ("tests/test_source.py::test_stale",)
    message = _format_parity_failure(parity)
    assert "Source-only IDs (missing from inventory)" in message
    assert "Inventory-only IDs (stale)" in message


def _build_reproduction_blob(
    test_id: str,
    hypothesis_seed: int | None = None,
    **kwargs: Any,
) -> str:
    """Construct a command for manually replaying a property-test seed.

    Args:
        test_id: Fully qualified pytest node ID.
        hypothesis_seed: The seed to replay from Hypothesis output.
        **kwargs: Additional diagnostic key-value pairs.

    Returns:
        A shell command and diagnostic context for manual reproduction.
    """
    seed_arg = f" --hypothesis-seed={hypothesis_seed}" if hypothesis_seed is not None else ""
    lines = [
        "# --- Reproduction blob ---",
        f"# test_id:  {test_id}",
        f"# seed:     {hypothesis_seed}",
    ]
    lines.extend(f"# {key}: {value}" for key, value in sorted(kwargs.items()))
    lines.extend(
        (
            "# ---",
            f"pytest {test_id} -x -s --tb=long{seed_arg} --hypothesis-profile=ci",
            "# --- End reproduction blob ---",
        )
    )
    return "\n".join(lines)


_EXAMPLE_SEED = 12345


@given(value=st.integers(min_value=-100, max_value=100))
@example(value=0)
@settings()
def test_fake_property_that_always_passes(value: int) -> None:
    assert isinstance(value, int)


def test_reproduction_blob_is_well_formed() -> None:
    test_id = "tests/test_property_policy.py::test_fake_property_that_always_passes"
    blob = _build_reproduction_blob(
        test_id,
        hypothesis_seed=_EXAMPLE_SEED,
        note="This validates the helper, not automatic failure output",
    )

    assert test_id in blob
    assert str(_EXAMPLE_SEED) in blob
    command = next(line for line in blob.splitlines() if line.startswith("pytest "))
    assert "--hypothesis-seed=" in command
    assert "--hypothesis-profile=ci" in command
    assert "-x -s --tb=long" in command
    assert blob.endswith("# --- End reproduction blob ---")


def test_reproduction_blob_includes_all_diagnostics() -> None:
    blob = _build_reproduction_blob(
        "tests/test_foo.py::test_bar",
        hypothesis_seed=42,
        detected_violation="merge returned duplicates",
        input_urls="a,b,c",
    )
    assert "# detected_violation: merge returned duplicates" in blob
    assert "# input_urls: a,b,c" in blob
    assert "# seed:     42" in blob


def test_hypothesis_constructs_are_used_in_property_source() -> None:
    source = _PROPERTY_TEST_FILES[0].read_text(encoding="utf-8")
    tree = ast.parse(source)
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert {"given", "settings", "assume", "example"} <= called_names
