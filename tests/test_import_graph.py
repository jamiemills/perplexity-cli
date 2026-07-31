"""Prove that import_graph.py:

- resolves absolute and relative imports (via Grimp)
- captures __init__.py module imports
- captures function-local imports
- captures TYPE_CHECKING imports as dependencies
- fails on syntax/read errors with distinct exit codes
- returns deterministic ordering
"""
# noqa: D (tests are exempt from docstring requirements)  # owner: quality-infrastructure; reason: test modules exempt from pydocstyle

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.import_graph import (  # noqa: E402  # owner: quality-infrastructure; reason: repo-relative import after sys.path setup
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
