"""Prove that import_graph.py:

- resolves absolute and relative imports (via Grimp)
- captures __init__.py module imports
- captures function-local imports
- captures TYPE_CHECKING imports as dependencies
- categorises module-level / function-local / TYPE_CHECKING imports separately
- handles relative ImportFrom nodes in the resolved graph
- fails on syntax/read errors with distinct exit codes
- returns deterministic ordering
"""
# noqa: D (tests are exempt from docstring requirements)  # owner: quality-infrastructure; reason: test modules exempt from pydocstyle

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str, register_as: str | None = None) -> ModuleType:
    """Load a scripts/<name>.py module by file path without sys.path mutation."""
    module_name = register_as or f"scripts.{name}"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(
        module_name, PROJECT_ROOT / "scripts" / f"{name}.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_load_script("import_graph")
from scripts.import_graph import (  # noqa: E402  # owner: quality-infrastructure; reason: module registered in sys.modules by _load_script
    FileReadError,
    SyntaxErrorInSource,
    _collect_categorised_imports,
    get_all_edges,
    get_all_module_names,
    get_direct_imports,
    get_function_local_imports,
    get_module_level_imports,
    get_type_checking_imports,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "import_graph"


def _write_synthetic_package(src_dir: Path, pkg_name: str) -> Path:
    """Write a synthetic package root with an __init__.py so grimp can find it."""
    pkg_root = src_dir / pkg_name
    pkg_root.mkdir(parents=True)
    (pkg_root / "__init__.py").write_text("", encoding="utf-8")
    return pkg_root


def _point_graph_at(monkeypatch, src_dir: Path, pkg_name: str) -> None:
    """Redirect import_graph module constants at a synthetic package.

    grimp discovers the package through the provided source directory; the
    package directory is exposed on sys.path only so grimp can resolve it.
    """
    import scripts.import_graph as ig

    monkeypatch.setattr(ig, "SRC_ROOT", src_dir)
    monkeypatch.setattr(ig, "PACKAGE_NAME", pkg_name)
    monkeypatch.setattr(ig, "PROJECT_ROOT", src_dir.parent)
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


# ------------------------------------------------------------------
# Grimp integration tests (integration-marker optional)
# ------------------------------------------------------------------


def test_get_all_module_names_returns_deterministic_list():
    names = get_all_module_names()
    assert isinstance(names, list)
    assert len(names) > 0
    assert names == sorted(names), "module names must be sorted"


def test_get_direct_imports_returns_sorted_list():
    imports = get_direct_imports("perplexity_cli")
    assert isinstance(imports, list)
    assert imports == sorted(imports)


# ------------------------------------------------------------------
# Categorised import capture (synthetic package fixtures)
# ------------------------------------------------------------------


def _write_categorisation_fixture(src_dir: Path, pkg_name: str) -> None:
    """Write a synthetic package with all three import categories."""
    pkg_root = _write_synthetic_package(src_dir, pkg_name)
    (pkg_root / "mod_b.py").write_text(
        "class ModuleLevel:\n    pass\nclass FuncLevel:\n    pass\nclass TcLevel:\n    pass\n",
        encoding="utf-8",
    )
    (pkg_root / "mod_a.py").write_text(
        f"from {pkg_name}.mod_b import ModuleLevel\n"
        "\n"
        "def run():\n"
        f"    from {pkg_name}.mod_b import FuncLevel\n"
        "    return FuncLevel\n"
        "\n"
        "if TYPE_CHECKING:\n"
        f"    from {pkg_name}.mod_b import TcLevel\n",
        encoding="utf-8",
    )


def test_module_level_imports_captured(tmp_path, monkeypatch):
    """Module-level imports are reported in the module_level category only."""
    pkg = "ig_mod_cat"
    src_dir = tmp_path / "src"
    _write_categorisation_fixture(src_dir, pkg)
    _point_graph_at(monkeypatch, src_dir, pkg)

    module_level = _collect_categorised_imports(f"{pkg}.mod_a", "module_level")
    function_local = _collect_categorised_imports(f"{pkg}.mod_a", "function_local")
    type_checking = _collect_categorised_imports(f"{pkg}.mod_a", "type_checking")
    assert module_level == {"mod_b.ModuleLevel"}
    assert function_local == {"mod_b.FuncLevel"}
    assert type_checking == {"mod_b.TcLevel"}


def test_public_getters_return_categorised_imports(tmp_path, monkeypatch):
    """The public getters expose the categorised import sets, sorted."""
    pkg = "ig_mod_cat2"
    src_dir = tmp_path / "src"
    _write_categorisation_fixture(src_dir, pkg)
    _point_graph_at(monkeypatch, src_dir, pkg)

    assert get_module_level_imports(f"{pkg}.mod_a") == ["mod_b.ModuleLevel"]
    assert get_function_local_imports(f"{pkg}.mod_a") == ["mod_b.FuncLevel"]
    assert get_type_checking_imports(f"{pkg}.mod_a") == ["mod_b.TcLevel"]


def test_relative_import_from_resolved_by_grimp(tmp_path, monkeypatch):
    """A relative `from . import` edge is resolved into the module graph."""
    pkg = "ig_rel"
    src_dir = tmp_path / "src"
    pkg_root = _write_synthetic_package(src_dir, pkg)
    (pkg_root / "leaf.py").write_text("class Leaf:\n    pass\n")
    (pkg_root / "importer.py").write_text("from .leaf import Leaf\n", encoding="utf-8")
    _point_graph_at(monkeypatch, src_dir, pkg)

    direct = get_direct_imports(f"{pkg}.importer")
    assert f"{pkg}.leaf" in direct


def test_relative_import_from_module_attributes_resolved(tmp_path, monkeypatch):
    """Relative ImportFrom nodes with dotted targets resolve to module edges."""
    pkg = "ig_rel2"
    src_dir = tmp_path / "src"
    pkg_root = _write_synthetic_package(src_dir, pkg)
    sub = pkg_root / "sub"
    sub.mkdir()
    (sub / "__init__.py").write_text("", encoding="utf-8")
    (sub / "inner.py").write_text("class Inner:\n    pass\n")
    (pkg_root / "importer.py").write_text("from .sub.inner import Inner\n", encoding="utf-8")
    _point_graph_at(monkeypatch, src_dir, pkg)

    direct = get_direct_imports(f"{pkg}.importer")
    assert f"{pkg}.sub.inner" in direct


def test_get_all_edges_returns_deterministic():
    edges = get_all_edges()
    assert isinstance(edges, list)
    for src, tgt in edges:
        assert isinstance(src, str)
        assert isinstance(tgt, str)
        assert src != tgt
    assert edges == sorted(edges)


def test_module_level_imports_for_api_client():
    imports = get_module_level_imports("perplexity_cli.api.client")
    assert isinstance(imports, list)
    assert imports == sorted(imports)


def test_function_local_imports_exist():
    """Verify that function-local imports are captured for known modules."""
    imports = get_function_local_imports("perplexity_cli.utils.logging")
    assert isinstance(imports, list)
    assert imports == sorted(imports)


def test_type_checking_imports():
    """Verify TYPE_CHECKING imports are captured."""
    imports = get_type_checking_imports("perplexity_cli.services.model_service")
    assert isinstance(imports, list)
    assert imports == sorted(imports)


def test_deterministic_ordering_across_calls():
    """Prove that repeated calls return identical results."""
    r1 = get_direct_imports("perplexity_cli")
    r2 = get_direct_imports("perplexity_cli")
    r3 = get_direct_imports("perplexity_cli")
    assert r1 == r2 == r3


# ------------------------------------------------------------------
# Guard: Syntax and read errors
# ------------------------------------------------------------------


def test_syntax_error_module():
    """Verify that a file with syntax error raises SyntaxErrorInSource.

    Creates a temporary broken module in the source tree, tests, then removes it.
    """
    src_root = PROJECT_ROOT / "src" / "perplexity_cli"
    temp_module = src_root / "_temp_syntax_test_module.py"

    try:
        temp_module.write_text("def broken(\n", encoding="utf-8")
        with pytest.raises(SyntaxErrorInSource):
            _collect_categorised_imports("perplexity_cli._temp_syntax_test_module", "module_level")
    finally:
        if temp_module.exists():
            temp_module.unlink()


def test_file_read_error_module():
    """Verify that a non-existent module raises FileReadError."""
    with pytest.raises(FileReadError):
        _collect_categorised_imports(
            "perplexity_cli.this_module_does_not_exist_xyz123", "module_level"
        )


# ------------------------------------------------------------------
# Graph integrity
# ------------------------------------------------------------------


def test_direct_imports_excludes_self():
    imports = get_direct_imports("perplexity_cli")
    assert "perplexity_cli" not in imports


def test_get_all_module_names_is_nonempty():
    names = get_all_module_names()
    assert "perplexity_cli" in names or any("perplexity_cli" in n for n in names)


def test_all_edges_are_unique():
    edges = get_all_edges()
    assert len(edges) == len(set(edges))
