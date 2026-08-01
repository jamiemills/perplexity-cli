"""Atheris-based fuzz tests for input-parsing and validation functions.

Each harness runs in a **separate subprocess** because atheris.Setup() can
only be called once per process.  The harnesses are defined in the
companion script ``_fuzz_harnesses.py`` and invoked via ``subprocess.run``.

The ``fuzz`` pytest marker allows selective execution:
    pytest -m fuzz          # run only fuzz tests
    pytest -m "not fuzz"    # skip fuzz tests (default via addopts)

Coverage-guided, seed-driven, oracle-based (task T025):

* Harnesses import target modules under ``atheris.instrument_imports`` so
  fuzzing is coverage-guided, and each run verifies the target functions
  were actually instrumented (reported in the machine-readable state file).
* The synthetic corpus in ``tests/fuzz_corpus/`` is deterministically
  replayed before mutation and passed to ``atheris.Setup`` as the seed
  corpus.  ``_run_harness`` asserts non-zero executed iterations and that
  every seed was replayed.
* Harnesses assert target-specific invariants (SSE parser equivalence,
  encryption round-trips, model round-trips, no caller-input mutation) and
  exact allowed-exception sets instead of broad "does not crash" checks.

Note on dateutil:
    Date-parsing functions (parse_absolute_date_string, _validate_date_params,
    is_in_date_range) are excluded because dateutil.parser.parse() has
    well-documented pathological cases where certain inputs cause unbounded
    execution time.  These are third-party bugs we cannot fix.
"""

import ast
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile

import pytest

# Number of fuzz iterations per harness (bounded: atheris runs are CPU-heavy).
_FUZZ_ITERATIONS = 5_000

# Path to the harness runner script (same directory as this test file).
_HARNESS_SCRIPT = str(__import__("pathlib").Path(__file__).parent / "_fuzz_harnesses.py")

# Synthetic seed corpus replayed before mutation and fed to atheris.Setup.
_CORPUS_DIR = str(pathlib.Path(__file__).parent / "fuzz_corpus")


def _run_harness(harness_name: str, iterations: int = _FUZZ_ITERATIONS) -> dict[str, object]:
    """Run a named fuzz harness in a subprocess and assert its evidence.

    Fails loudly when atheris is unavailable -- the fuzz lane is
    authoritative and must not silently skip.

    Asserts that the harness reported a machine-readable state file proving
    instrumentation, non-zero executed iterations, and corpus seed replay.

    Raises AssertionError with stderr output if the subprocess exits with a
    non-zero code, or if the state file is missing/empty.

    The 120s timeout is bounded: instrumentation startup is ~2s and the
    slowest measured harness (decrypt_token, with PBKDF2 round-trips during
    seed replay) completes in ~6s, so 120s leaves ample margin for
    coverage-guided exploration of the v2 decryption path on slower CI.
    """
    if importlib.util.find_spec("atheris") is None:
        pytest.fail(
            "atheris is not installed -- run 'uv sync --all-extras --group dev' "
            "(fuzz lane is authoritative and must not skip)"
        )
    with tempfile.TemporaryDirectory() as tmp_dir:
        state_path = pathlib.Path(tmp_dir) / f"fuzz-state-{harness_name}.json"
        result = subprocess.run(
            [
                sys.executable,
                _HARNESS_SCRIPT,
                harness_name,
                str(iterations),
                _CORPUS_DIR,
                str(state_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"Fuzz harness '{harness_name}' failed (exit {result.returncode}):\n{result.stderr[-2000:]}"
        )
        assert state_path.is_file(), (
            f"Fuzz harness '{harness_name}' did not write its state file:\n{result.stdout[-2000:]}"
        )
        state: dict[str, object] = json.loads(state_path.read_text(encoding="utf-8"))
        assert isinstance(state.get("iterations"), int) and state["iterations"] > 0, (
            f"Fuzz harness '{harness_name}' reported no executed iterations"
        )
        assert isinstance(state.get("seed_replays"), list) and state["seed_replays"], (
            f"Fuzz harness '{harness_name}' reported no corpus seed replay"
        )
        assert (
            isinstance(state.get("instrumented_functions"), list)
            and state["instrumented_functions"]
        ), f"Fuzz harness '{harness_name}' reported no instrumented target functions"
        return state


# ===================================================================
# 1. SSE protocol parsing
# ===================================================================


@pytest.mark.fuzz
class TestFuzzSSEParser:
    """Fuzz tests for the SSE wire-format parser."""

    def test_fuzz_decode_line(self):
        """_decode_line must round-trip bytes through UTF-8 or raise UnicodeDecodeError."""
        _run_harness("sse_decode_line")

    def test_fuzz_parse_line(self):
        """_parse_line must match the reference line grammar."""
        _run_harness("sse_parse_line")

    def test_fuzz_yield_event(self):
        """_yield_event must parse a JSON object or raise UpstreamSchemaError."""
        _run_harness("sse_yield_event")

    def test_fuzz_accumulate_line(self):
        """_accumulate_line must match the reference accumulation semantics."""
        _run_harness("sse_accumulate_line")


# ===================================================================
# 2. Text formatting
# ===================================================================


@pytest.mark.fuzz
class TestFuzzFormatting:
    """Fuzz tests for text transformation functions."""

    def test_fuzz_strip_citations(self):
        """strip_citations must equal re.sub of citation markers."""
        _run_harness("strip_citations")

    def test_fuzz_unwrap_paragraph_lines(self):
        """unwrap_paragraph_lines must never invent line breaks."""
        _run_harness("unwrap_paragraph_lines")

    def test_fuzz_is_structural_line(self):
        """_is_structural_line must match the structural regex contract."""
        _run_harness("is_structural_line")


# ===================================================================
# 3. Encryption
# ===================================================================


@pytest.mark.fuzz
class TestFuzzEncryption:
    """Fuzz tests for token encryption/decryption."""

    def test_fuzz_decrypt_token(self):
        """decrypt_token must round-trip encrypt_token and only raise AuthenticationError."""
        _run_harness("decrypt_token")


# ===================================================================
# 4. Thread scraper field extraction
# ===================================================================


@pytest.mark.fuzz
class TestFuzzScraperFields:
    """Fuzz tests for thread-parsing module-level functions."""

    def test_fuzz_get_str_field(self):
        """_get_str_field must return the field or raise UpstreamSchemaError without mutation."""
        _run_harness("get_str_field")

    def test_fuzz_extract_total_threads(self):
        """_extract_total_threads must return int or raise UpstreamSchemaError without mutation."""
        _run_harness("extract_total_threads")


# ===================================================================
# 5. API contracts
# ===================================================================


@pytest.mark.fuzz
class TestFuzzContracts:
    """Fuzz tests for upstream payload validation helpers."""

    def test_fuzz_require_mapping(self):
        """require_mapping must return the same mapping or raise UpstreamSchemaError."""
        _run_harness("require_mapping")

    def test_fuzz_require_list(self):
        """require_list must return the same list or raise UpstreamSchemaError."""
        _run_harness("require_list")

    def test_fuzz_parse_thread_list_payload(self):
        """parse_thread_list_payload must validate list-of-mappings without mutation."""
        _run_harness("parse_thread_list_payload")

    def test_fuzz_parse_upload_url_response(self):
        """parse_upload_url_response must validate the upload shape without mutation."""
        _run_harness("parse_upload_url_response")


# ===================================================================
# 6. Pydantic model validation
# ===================================================================


@pytest.mark.fuzz
class TestFuzzPydanticModels:
    """Fuzz tests for Pydantic model validation with untrusted input."""

    def test_fuzz_block_model_validate(self):
        """Block.model_validate must round-trip valid objects without mutating input."""
        _run_harness("block_model_validate")

    def test_fuzz_block_extract_text(self):
        """Block.extract_text must return str or None without crashing."""
        _run_harness("block_extract_text")

    def test_fuzz_sse_message_model_validate(self):
        """SSEMessage.model_validate must round-trip valid objects without mutating input."""
        _run_harness("sse_message_model_validate")


# ===================================================================
# 7. Structural enforcement (not fuzz-marked; runs with standard suite)
# ===================================================================


class TestFuzzHarnessEnforcement:
    """Verify the harness script, test file, and corpus stay in sync.

    These are NOT fuzz tests -- they are structural checks that run with
    the standard test suite to catch drift between the harness registry
    in ``_fuzz_harnesses.py``, the pytest wrappers in this file, and the
    synthetic seed corpus in ``tests/fuzz_corpus/``.
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

    @staticmethod
    def _corpus_seed_files() -> set[str]:
        """Return the ``.bin`` seed filenames present in the corpus directory."""
        return {path.name for path in pathlib.Path(_CORPUS_DIR).glob("*.bin")}

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

    def test_corpus_dir_exists_with_readme(self):
        """The seed corpus directory must exist and carry a README."""
        corpus = pathlib.Path(_CORPUS_DIR)
        assert corpus.is_dir()
        assert (corpus / "README.md").is_file()

    def test_every_seed_documented_in_readme(self):
        """Every ``.bin`` seed file must be referenced in the corpus README."""
        readme = (pathlib.Path(_CORPUS_DIR) / "README.md").read_text(encoding="utf-8")
        seed_files = self._corpus_seed_files()
        assert seed_files, "Corpus directory contains no .bin seed files"
        missing = sorted(name for name in seed_files if name not in readme)
        assert not missing, f"Seed files not referenced in README.md: {missing}"
