"""Atheris-based fuzz tests for input-parsing and validation functions.

Each harness runs in a **separate subprocess** because atheris.Setup() can
only be called once per process.  The harnesses are defined in the
companion script ``_fuzz_harnesses.py`` and invoked via ``subprocess.run``.

The ``fuzz`` pytest marker allows selective execution:
    pytest -m fuzz          # run only fuzz tests
    pytest -m "not fuzz"    # skip fuzz tests (default via addopts)

Note on dateutil:
    Date-parsing functions (parse_absolute_date_string, _validate_date_params,
    is_in_date_range) are excluded because dateutil.parser.parse() has
    well-documented pathological cases where certain inputs cause unbounded
    execution time.  These are third-party bugs we cannot fix.
"""

import ast
import importlib.util
import pathlib
import subprocess
import sys

import pytest

# atheris is an optional dependency -- skip fuzz harness tests when absent
# (e.g. in CI where it is not installed).
_HAS_ATHERIS = importlib.util.find_spec("atheris") is not None

# Number of fuzz iterations per harness.
_FUZZ_ITERATIONS = 5_000

# Path to the harness runner script (same directory as this test file).
_HARNESS_SCRIPT = str(__import__("pathlib").Path(__file__).parent / "_fuzz_harnesses.py")


def _run_harness(harness_name: str, iterations: int = _FUZZ_ITERATIONS) -> None:
    """Run a named fuzz harness in a subprocess.

    Raises AssertionError with stderr output if the subprocess exits
    with a non-zero code.
    """
    result = subprocess.run(
        [sys.executable, _HARNESS_SCRIPT, harness_name, str(iterations)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Fuzz harness '{harness_name}' failed (exit {result.returncode}):\n{result.stderr[-2000:]}"
    )


# ===================================================================
# 1. SSE protocol parsing
# ===================================================================


@pytest.mark.fuzz
@pytest.mark.skipif(not _HAS_ATHERIS, reason="atheris not installed")
class TestFuzzSSEParser:
    """Fuzz tests for the SSE wire-format parser."""

    def test_fuzz_decode_line(self):
        """_decode_line must not crash on arbitrary bytes."""
        _run_harness("sse_decode_line")

    def test_fuzz_parse_line(self):
        """_parse_line must never crash."""
        _run_harness("sse_parse_line")

    def test_fuzz_yield_event(self):
        """_yield_event must raise UpstreamSchemaError on non-JSON data."""
        _run_harness("sse_yield_event")

    def test_fuzz_accumulate_line(self):
        """_accumulate_line must never crash."""
        _run_harness("sse_accumulate_line")


# ===================================================================
# 2. Text formatting
# ===================================================================


@pytest.mark.fuzz
@pytest.mark.skipif(not _HAS_ATHERIS, reason="atheris not installed")
class TestFuzzFormatting:
    """Fuzz tests for text transformation functions."""

    def test_fuzz_strip_citations(self):
        """strip_citations must never crash on any string."""
        _run_harness("strip_citations")

    def test_fuzz_unwrap_paragraph_lines(self):
        """unwrap_paragraph_lines must never crash on any string."""
        _run_harness("unwrap_paragraph_lines")

    def test_fuzz_is_structural_line(self):
        """_is_structural_line must never crash."""
        _run_harness("is_structural_line")


# ===================================================================
# 3. Encryption
# ===================================================================


@pytest.mark.fuzz
@pytest.mark.skipif(not _HAS_ATHERIS, reason="atheris not installed")
class TestFuzzEncryption:
    """Fuzz tests for decryption of corrupt ciphertext."""

    def test_fuzz_decrypt_token(self):
        """decrypt_token must raise AuthenticationError on corrupt data."""
        _run_harness("decrypt_token")


# ===================================================================
# 4. Thread scraper field extraction
# ===================================================================


@pytest.mark.fuzz
@pytest.mark.skipif(not _HAS_ATHERIS, reason="atheris not installed")
class TestFuzzScraperFields:
    """Fuzz tests for thread-parsing module-level functions."""

    def test_fuzz_get_str_field(self):
        """_get_str_field must raise UpstreamSchemaError or return str."""
        _run_harness("get_str_field")

    def test_fuzz_extract_total_threads(self):
        """_extract_total_threads must raise UpstreamSchemaError or return int."""
        _run_harness("extract_total_threads")


# ===================================================================
# 5. API contracts
# ===================================================================


@pytest.mark.fuzz
@pytest.mark.skipif(not _HAS_ATHERIS, reason="atheris not installed")
class TestFuzzContracts:
    """Fuzz tests for upstream payload validation helpers."""

    def test_fuzz_require_mapping(self):
        """require_mapping must raise UpstreamSchemaError for non-dicts."""
        _run_harness("require_mapping")

    def test_fuzz_require_list(self):
        """require_list must raise UpstreamSchemaError for non-lists."""
        _run_harness("require_list")

    def test_fuzz_parse_thread_list_payload(self):
        """parse_thread_list_payload must raise UpstreamSchemaError on bad shape."""
        _run_harness("parse_thread_list_payload")

    def test_fuzz_parse_upload_url_response(self):
        """parse_upload_url_response must raise UpstreamSchemaError on bad shape."""
        _run_harness("parse_upload_url_response")


# ===================================================================
# 6. Pydantic model validation
# ===================================================================


@pytest.mark.fuzz
@pytest.mark.skipif(not _HAS_ATHERIS, reason="atheris not installed")
class TestFuzzPydanticModels:
    """Fuzz tests for Pydantic model validation with untrusted input."""

    def test_fuzz_block_model_validate(self):
        """Block.model_validate must raise ValidationError on bad shape."""
        _run_harness("block_model_validate")

    def test_fuzz_block_extract_text(self):
        """Block.extract_text must never crash regardless of content."""
        _run_harness("block_extract_text")

    def test_fuzz_sse_message_model_validate(self):
        """SSEMessage.model_validate must raise on bad shape."""
        _run_harness("sse_message_model_validate")


# ===================================================================
# 7. Structural enforcement (not fuzz-marked; runs with standard suite)
# ===================================================================


class TestFuzzHarnessEnforcement:
    """Verify the harness script and test file stay in sync.

    These are NOT fuzz tests -- they are structural checks that run with
    the standard test suite to catch drift between the harness registry
    in ``_fuzz_harnesses.py`` and the pytest wrappers in this file.
    """

    @staticmethod
    def _extract_test_harness_names() -> set[str]:
        """Extract harness names from ``_run_harness()`` calls in this file."""
        source = pathlib.Path(__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        names: set[str] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_run_harness"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                names.add(node.args[0].value)
        return names

    @staticmethod
    def _extract_registry_keys() -> set[str]:
        """Extract harness names from ``_HARNESSES`` dict in the runner script."""
        source = pathlib.Path(_HARNESS_SCRIPT).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "_HARNESSES"
                and isinstance(node.value, ast.Dict)
            ):
                return {
                    k.value
                    for k in node.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                }
        msg = "_HARNESSES dict not found in harness script"
        raise AssertionError(msg)

    def test_harness_script_exists(self):
        """The harness runner script must exist."""
        assert pathlib.Path(_HARNESS_SCRIPT).is_file()

    def test_all_test_harnesses_registered(self):
        """Every harness name used in tests must exist in the registry."""
        test_names = self._extract_test_harness_names()
        registry_names = self._extract_registry_keys()
        missing = test_names - registry_names
        assert not missing, f"Harness names used in tests but not in _HARNESSES: {missing}"

    def test_all_registered_harnesses_tested(self):
        """Every harness in _HARNESSES must have a corresponding test."""
        test_names = self._extract_test_harness_names()
        registry_names = self._extract_registry_keys()
        untested = registry_names - test_names
        assert not untested, f"Harness names in _HARNESSES but with no test: {untested}"

    def test_harness_count(self):
        """Test and registry harness counts must match (currently 17)."""
        test_names = self._extract_test_harness_names()
        registry_names = self._extract_registry_keys()
        assert len(test_names) == len(registry_names) == 17
