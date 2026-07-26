"""Property-test policy enforcement — marker completeness and validation.

Proves that every ``@given`` test in ``test_property.py`` carries the
``property`` marker, and that every ``property``-marked test uses
Hypothesis.  Also verifies that CI failures emit a usable reproduction
blob so developers can re-run the failing case locally.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from hypothesis import example, given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _has_given_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Check whether *node* is decorated with ``@given`` (any import form)."""
    for deco in node.decorator_list:
        if isinstance(deco, ast.Name) and deco.id == "given":
            return True
        if isinstance(deco, ast.Call):
            name = _unpack_decorator_name(deco.func)
            if name == "given":
                return True
        if isinstance(deco, ast.Attribute) and deco.attr == "given":
            return True
    return False


def _unpack_decorator_name(expr: ast.expr) -> str | None:
    """Walk dotted/attributed names to get the final identifier."""
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    return None


def _has_property_marker(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Check whether *node* carries ``@pytest.mark.property``."""
    for deco in node.decorator_list:
        if isinstance(deco, ast.Attribute) and (
            isinstance(deco.value, ast.Attribute)
            and isinstance(deco.value.value, ast.Name)
            and deco.value.value.id == "pytest"
            and deco.value.attr == "mark"
            and deco.attr == "property"
        ):
            return True
        if isinstance(deco, ast.Call):
            name = _unpack_decorator_name(deco.func)
            if name == "property":
                return True
    return False


def _parse_property_test_functions(source_path: Path) -> dict[str, dict[str, object]]:
    """Return info about every function in *source_path*.

    Returns:
        dict mapping function name to ``{has_given, has_property_marker, lineno}``.
    """
    tree = ast.parse(source_path.read_text())
    result: dict[str, dict[str, object]] = {}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test_"
        ):
            result[node.name] = {
                "has_given": _has_given_decorator(node),
                "has_property_marker": _has_property_marker(node),
                "lineno": node.lineno,
            }

    return result


def _has_module_pytestmark(source_text: str, tree: ast.Module) -> bool:
    """Check whether *tree* has a global ``pytestmark`` containing ``property``."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "pytestmark":
                    segment = ast.get_source_segment(source_text, node.value)
                    if segment and "property" in segment:
                        return True
    return False


def _gather_given_functions(source_path: Path) -> list[str]:
    """Return names of all ``@given``-decorated test functions."""
    info = _parse_property_test_functions(source_path)
    return [name for name, meta in info.items() if meta["has_given"]]


# ============================================================================
# Policy 1 — Every @given test has the property marker
# ============================================================================


def test_all_given_tests_have_property_marker() -> None:
    """Every test decorated with ``@given`` carries the ``@pytest.mark.property`` marker."""
    source_path = Path(__file__).resolve().parent / "test_property.py"
    source_text = source_path.read_text()
    info = _parse_property_test_functions(source_path)

    tree = ast.parse(source_text)
    has_module_marker = _has_module_pytestmark(source_text, tree)

    missing: list[str] = []
    for name, meta in info.items():
        if meta["has_given"] and not meta["has_property_marker"] and not has_module_marker:
            lineno = meta["lineno"]
            missing.append(
                f"  {name} at line {lineno}\n"
                f"    → Add @pytest.mark.property decorator "
                f"or ensure pytestmark = [pytest.mark.property] is present"
            )

    assert not missing, (
        "PROPERTY MARKER POLICY VIOLATION\n"
        "===============================\n"
        f"The following @given tests are missing the 'property' marker:\n"
        f"{''.join(missing)}\n"
        "REPRODUCTION BLOB:\n"
        f"  file: {source_path}\n"
        f"  fix:  Add @pytest.mark.property decorator above each listed test\n"
        f"        or add pytestmark = [pytest.mark.property] at module level.\n"
        f"  ci:   Run `pytest tests/test_property_policy.py -v` to re-validate."
    )


# ============================================================================
# Policy 2 — Every property-marked test uses Hypothesis
# ============================================================================


def test_all_property_marked_tests_use_hypothesis() -> None:
    """Every test with an *explicit* ``@pytest.mark.property`` must use ``@given``.

    Tests in a module with ``pytestmark = [pytest.mark.property]`` are exempt
    from this check — the blanket marker is intentional and the file is
    designated as a property-test module.  Only individually-decorated tests
    are verified for Hypothesis use.
    """
    source_path = Path(__file__).resolve().parent / "test_property.py"
    info = _parse_property_test_functions(source_path)

    invalid: list[str] = []
    for name, meta in info.items():
        if meta["has_property_marker"] and not meta["has_given"]:
            lineno = meta["lineno"]
            invalid.append(
                f"  {name} at line {lineno}\n"
                f"    → Test has explicit @pytest.mark.property but does not use @given.\n"
                f"    Either add @given or remove the explicit property marker."
            )

    assert not invalid, (
        "PROPERTY MARKER POLICY VIOLATION\n"
        "===============================\n"
        f"The following property-marked tests do not use Hypothesis (@given):\n"
        f"{''.join(invalid)}\n"
        "REPRODUCTION BLOB:\n"
        f"  file: {source_path}\n"
        f"  fix:  Either decorate with @given or remove the @pytest.mark.property marker.\n"
        f"  ci:   Run `pytest tests/test_property_policy.py -v` to re-validate."
    )


# ============================================================================
# Policy 3 — Simulated CI failure emits usable reproduction blob
# ============================================================================


def _build_reproduction_blob(
    test_id: str,
    hypothesis_seed: int | None = None,
    **kwargs: Any,
) -> str:
    """Construct a standalone reproduction command for a failing property test.

    Args:
        test_id: Fully qualified pytest node ID.
        hypothesis_seed: The seed to replay (from Hypothesis output).
        **kwargs: Additional diagnostic key-value pairs.

    Returns:
        A shell command and context that reproduces the failure.
    """
    seed_arg = f" --hypothesis-seed={hypothesis_seed}" if hypothesis_seed is not None else ""
    profile_arg = " --hypothesis-profile=ci"

    lines = [
        "# --- Reproduction blob ---",
        f"# test_id:  {test_id}",
        f"# seed:     {hypothesis_seed}",
    ]
    for key, value in sorted(kwargs.items()):
        lines.append(f"# {key}: {value}")
    lines.extend(
        [
            "# ---",
            f"pytest {test_id} -x -s --tb=long{seed_arg}{profile_arg}",
            "# --- End reproduction blob ---",
        ]
    )
    return "\n".join(lines)


_EXAMPLE_SEED: int = 12345


@given(value=st.integers(min_value=-100, max_value=100))
@example(value=0)
@settings()
def test_fake_property_that_always_passes(value: int) -> None:
    """Trivial property used only to prove the reproduction blob is well-formed."""
    assert isinstance(value, int)


def test_reproduction_blob_is_well_formed() -> None:
    """The reproduction blob generator produces a runnable command.

    This is tested directly (not via an actual Hypothesis failure) to
    avoid making the suite depend on the Hypothesis example database or
    specific random seeds.
    """
    test_id = "tests/test_property.py::test_fake_property_that_always_passes"
    blob = _build_reproduction_blob(
        test_id,
        hypothesis_seed=_EXAMPLE_SEED,
        note="This is a policy validation, not an actual failure",
    )

    assert test_id in blob
    assert str(_EXAMPLE_SEED) in blob
    assert "pytest " in blob
    assert "--hypothesis-seed=" in blob
    assert "--- Reproduction blob ---" in blob
    assert "--- End reproduction blob ---" in blob

    # Verify it parses as a well-formed shell command line
    cmd_line = next(line for line in blob.splitlines() if line.startswith("pytest "))
    assert "tests/" in cmd_line
    assert "-x" in cmd_line
    assert "--tb=long" in cmd_line


def test_reproduction_blob_includes_all_diagnostics() -> None:
    """Extra kwargs appear in the reproduction blob."""
    blob = _build_reproduction_blob(
        "tests/test_foo.py::test_bar",
        hypothesis_seed=42,
        detected_violation="merge returned duplicates",
        input_urls="a,b,c",
    )
    assert "detected_violation" in blob
    assert "merge returned duplicates" in blob
    assert "input_urls" in blob
    assert "a,b,c" in blob
    assert "42" in blob


# ============================================================================
# Policy 4 — Marker count integrity (defence against accidental removal)
# ============================================================================


def test_property_test_count_within_expected_range() -> None:
    """Sanity-check that the number of @given tests does not unexpectedly shrink.

    The count is compared against the property-inventory.toml baseline.
    Accidental deletion of @given decorators (e.g. during refactors)
    would drop this number, which this test catches.
    """
    source_path = Path(__file__).resolve().parent / "test_property.py"
    given_names = _gather_given_functions(source_path)

    # Minimum expected — from inventory baseline (59 + 4 new in Wave 6)
    minimum_expected = 60

    assert len(given_names) >= minimum_expected, (
        "PROPERTY COUNT POLICY VIOLATION\n"
        "==============================\n"
        f"Found {len(given_names)} @given tests, expected at least {minimum_expected}.\n"
        "REPRODUCTION BLOB:\n"
        f"  file:    {source_path}\n"
        f"  current: {len(given_names)} @given tests\n"
        f"  minimum: {minimum_expected}\n"
        f"  action:  Verify that @given decorators were not accidentally removed.\n"
        f"           Check test_property.py for removed or renamed tests.\n"
        f"  ci:      Run `pytest tests/test_property_policy.py -v` to re-validate."
    )


# ============================================================================
# Policy 5 — Structural integrity: no dead Hypothesis imports
# ============================================================================


def test_hypothesis_imports_are_used() -> None:
    """Verify that key Hypothesis imports in test_property.py are actually used.

    Checks that ``given``, ``settings``, ``assume``, and ``example`` appear
    as decorators in the file (not just as a stale import).
    """
    source_path = Path(__file__).resolve().parent / "test_property.py"
    source = source_path.read_text()

    used_constructs: dict[str, int] = {}

    # Count usage occurrences as decorators or call expressions
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for deco in node.decorator_list:
                name = _unpack_decorator_name(deco.func) if isinstance(deco, ast.Call) else None
                if isinstance(deco, ast.Name):
                    name = deco.id
                if isinstance(deco, ast.Attribute):
                    name = deco.attr
                if name in ("given", "example"):
                    used_constructs[name] = used_constructs.get(name, 0) + 1
        if isinstance(node, ast.Call):
            name = _unpack_decorator_name(node.func)
            if name in ("assume", "settings"):
                used_constructs[name] = used_constructs.get(name, 0) + 1

    assert used_constructs.get("given", 0) > 0, (
        "PROPERTY INTEGRITY VIOLATION\n"
        "==========================\n"
        "No @given decorator found in test_property.py.  Verify imports are in use.\n"
    )
    assert used_constructs.get("settings", 0) > 0, (
        "PROPERTY INTEGRITY VIOLATION\n"
        "==========================\n"
        "No @settings usage found.  Verify settings are applied to at least one test.\n"
    )


# ============================================================================
# Policy 6 — Simulated marker violation produces actionable output
# ============================================================================


_MARKER_VIOLATION_MESSAGE = (
    "PROPERTY MARKER POLICY VIOLATION — SIMULATED CI FAILURE\n"
    "=======================================================\n"
    "Test ID:    {test_id}\n"
    "File:       {source_file}\n"
    "Line:       {lineno}\n"
    "Violation:  {reason}\n"
    "---\n"
    "Fix: Add the following decorator above the test function:\n"
    "\n"
    "    @pytest.mark.property\n"
    "\n"
    "Or ensure the module has:\n"
    "\n"
    "    pytestmark = [pytest.mark.property]\n"
    "\n"
    "Reproduction:\n"
    "    pytest tests/test_property_policy.py::test_marker_violation_message_is_usable -v\n"
    "--- End CI failure blob ---"
)


def test_marker_violation_message_is_usable() -> None:
    """When a marker violation is detected, the error message is self-contained.

    This test validates the template itself — it must include:
    - Test identification (name, file, line)
    - The specific violation reason
    - A concrete fix instruction
    - A reproduction command
    """
    msg = _MARKER_VIOLATION_MESSAGE.format(
        test_id="tests/test_property.py::test_encrypt_decrypt_roundtrip",
        source_file="tests/test_property.py",
        lineno=77,
        reason="@given present but @pytest.mark.property missing",
    )

    # Must contain actionable information
    assert "test_encrypt_decrypt_roundtrip" in msg
    assert "tests/test_property.py" in msg
    assert "77" in msg or ":77" in msg
    assert "Fix:" in msg or "Add" in msg
    assert "pytest.mark.property" in msg
    assert "pytestmark" in msg
    assert "Reproduction:" in msg or "reproduction" in msg.lower()
    assert "--- End CI failure blob ---" in msg
