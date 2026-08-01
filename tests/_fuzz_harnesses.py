"""Coverage-guided, seed-driven, oracle-based fuzz harness runner for atheris.

Each harness is registered in the ``_HARNESSES`` dict and can be invoked
from the command line as::

    python tests/_fuzz_harnesses.py <harness_name> [iterations] [corpus_dir] [state_path]

Design (see task T025):

1. **Instrumentation** -- target modules are imported inside a
   ``with atheris.instrument_imports(include=["perplexity_cli"])`` block so
   every harness exercises bytecode-instrumented target code.  Each harness
   also verifies (and reports) that its target functions carry the
   ``__ATHERIS_INSTRUMENTED__`` sentinel before fuzzing begins.

2. **Corpus** -- ``tests/fuzz_corpus/`` holds small synthetic seeds covering
   valid and near-valid inputs.  Every seed is deterministically replayed
   (sorted by filename) *before* mutation, then the corpus directory is
   passed to ``atheris.Setup`` as the libFuzzer seed corpus.

3. **Oracles** -- harnesses assert target-specific invariants (SSE parser
   equivalence against reference re-implementations, encryption round-trips,
   model round-trips, no-mutation of caller-owned inputs) and exact
   allowed-exception sets.  Any other exception is an uncaught crash that
   fails the fuzz run.

4. **Reporting** -- executed iterations and replayed seeds are written to a
   machine-readable JSON state file (path passed as the fourth argument) so
   the pytest wrapper can assert non-zero execution and corpus replay.

atheris.Setup() can only be called once per process, so each pytest test in
``test_fuzz.py`` spawns a fresh subprocess running this script.
"""

import json
import os
import re
import sys
from pathlib import Path

# Ensure the src layout is on the path when run as a script.
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_repo_root, "src"))

# Set isolated config dir to avoid touching real user config.
os.environ.setdefault("PERPLEXITY_CONFIG_DIR", "/tmp/fuzz-config-dir")

import atheris  # noqa: E402  # owner: quality-infrastructure; reason: repo-relative import after sys.path setup

# ---------------------------------------------------------------------------
# Import target modules under atheris instrumentation so that fuzzing is
# coverage-guided rather than bounded random execution.
# ---------------------------------------------------------------------------
with atheris.instrument_imports(include=["perplexity_cli"]):
    from pydantic import ValidationError

    from perplexity_cli.api.client import SSEParser
    from perplexity_cli.api.contracts import (
        parse_thread_list_payload,
        parse_upload_url_response,
        require_list,
        require_mapping,
    )
    from perplexity_cli.api.models import Block, SSEMessage
    from perplexity_cli.formatting.base import Formatter, _is_structural_line
    from perplexity_cli.threads.scraper import _extract_total_threads, _get_str_field
    from perplexity_cli.utils.encryption import decrypt_token, encrypt_token
    from perplexity_cli.utils.exceptions import AuthenticationError, UpstreamSchemaError


# ===================================================================
# Instrumentation verification
# ===================================================================

_ATHERIS_SENTINEL = "__ATHERIS_INSTRUMENTED__"


def _is_instrumented(func) -> bool:
    """Return True when *func* was patched with atheris instrumentation."""
    function = getattr(func, "__func__", func)
    return any(
        isinstance(constant, str) and constant == _ATHERIS_SENTINEL
        for constant in function.__code__.co_consts
    )


def _func_name(func) -> str:
    """Return a stable ``module.qualname`` label for a target function."""
    function = getattr(func, "__func__", func)
    return f"{function.__module__}.{function.__qualname__}"


# ===================================================================
# Machine-readable state reporting (written from inside the fuzz loop
# because ``atheris.Fuzz()`` never returns).
# ===================================================================


class _FuzzRunState:
    """Mutable per-run state shared across harness helpers."""

    def __init__(self) -> None:
        self.state_path: str | None = None
        self.iterations: int = 0
        self.seed_replays: list[str] = []
        self.instrumented_functions: list[str] = []
        self.roundtrip_enabled: bool = False


_run_state = _FuzzRunState()


def _write_state() -> None:
    """Persist the current run state as JSON, atomically replaced."""
    state_path = _run_state.state_path
    if state_path is None:
        return
    state = {
        "iterations": _run_state.iterations,
        "seed_replays": list(_run_state.seed_replays),
        "instrumented_functions": list(_run_state.instrumented_functions),
    }
    tmp_path = Path(f"{state_path}.tmp")
    tmp_path.write_text(json.dumps(state), encoding="utf-8")
    tmp_path.replace(state_path)


def _make_counted(harness_fn):
    """Wrap a harness so every completed execution increments the counter."""

    def counted(data: bytes) -> None:
        harness_fn(data)
        _run_state.iterations += 1
        _write_state()

    return counted


def _replay_corpus(counted, corpus_dir: str) -> list[Path]:
    """Deterministically replay every ``.bin`` seed before mutation."""
    corpus_path = Path(corpus_dir)
    seed_files = sorted(
        path for path in corpus_path.iterdir() if path.is_file() and path.suffix == ".bin"
    )
    if not seed_files:
        print(
            f"ERROR: no .bin seed files found in corpus dir {corpus_dir}",
            file=sys.stderr,
        )
        sys.exit(4)
    for seed_path in seed_files:
        data = seed_path.read_bytes()
        try:
            counted(data)
        except Exception as exc:
            print(
                f"SEED_REPLAY_FAILED:{seed_path.name}:{type(exc).__name__}:{exc}",
                file=sys.stderr,
            )
            raise
        _run_state.seed_replays.append(seed_path.name)
        _write_state()
    return seed_files


# ===================================================================
# Reference oracle helpers
# ===================================================================


def _reference_is_structural_line(stripped: str) -> bool:
    """Reference re-implementation of the structural-line predicate."""
    return bool(
        re.match(r"^#{1,6}\s", stripped)
        or re.match(r"^[-*+]\s", stripped)
        or re.match(r"^\d+\.\s", stripped)
        or re.match(r"^[>\|]", stripped)
        or re.match(r"^[\*\-]{3,}$", stripped)
    )


def _reference_parse_line(
    line: str, event_type: str | None, data_lines: list[str]
) -> tuple[str | None, list[str]]:
    """Reference re-implementation of ``SSEParser._parse_line``."""
    if line.startswith("event:"):
        return line[6:].strip(), data_lines
    if line.startswith("data:"):
        return event_type, [*data_lines, line[5:].strip()]
    return event_type, data_lines


# ===================================================================
# Harness definitions
# ===================================================================


def _harness_sse_decode_line(data):
    fdp = atheris.FuzzedDataProvider(data)
    raw = fdp.ConsumeBytes(500)
    try:
        result = SSEParser._decode_line(raw)
    except UnicodeDecodeError:
        return
    assert isinstance(result, str)
    assert result == raw.decode("utf-8")


def _harness_sse_parse_line(data):
    fdp = atheris.FuzzedDataProvider(data)
    line = fdp.ConsumeUnicodeNoSurrogates(300)
    event_type = fdp.ConsumeUnicodeNoSurrogates(50) if fdp.ConsumeBool() else None
    data_lines: list[str] = []
    result_type, result_lines = SSEParser._parse_line(line, event_type, data_lines)
    assert isinstance(result_lines, list)
    if line.startswith("event:"):
        assert result_type == line[6:].strip()
        assert result_lines is data_lines
    elif line.startswith("data:"):
        assert result_type is event_type
        assert result_lines is data_lines
        assert result_lines[-1] == line[5:].strip()
    else:
        assert result_type is event_type
        assert result_lines is data_lines


def _harness_sse_yield_event(data):
    fdp = atheris.FuzzedDataProvider(data)
    num_lines = fdp.ConsumeIntInRange(0, 5)
    lines = [fdp.ConsumeUnicodeNoSurrogates(200) for _ in range(num_lines)]
    data_str = "\n".join(lines)
    try:
        result = SSEParser._yield_event(lines)
    except UpstreamSchemaError:
        try:
            parsed = json.loads(data_str)
        except json.JSONDecodeError:
            return
        assert not isinstance(parsed, dict)
        return
    assert isinstance(result, dict)
    assert json.loads(data_str) == result


def _harness_sse_accumulate_line(data):
    fdp = atheris.FuzzedDataProvider(data)
    line = fdp.ConsumeUnicodeNoSurrogates(300)
    event_type = fdp.ConsumeUnicodeNoSurrogates(30) if fdp.ConsumeBool() else None
    data_lines = [fdp.ConsumeUnicodeNoSurrogates(100)] if fdp.ConsumeBool() else []
    try:
        result_type, result_lines, event = SSEParser._accumulate_line(line, event_type, data_lines)
    except UpstreamSchemaError:
        try:
            parsed = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            return
        assert not isinstance(parsed, dict)
        return
    assert isinstance(result_lines, list)
    if not line:
        assert result_type is None
        assert result_lines == []
        if data_lines:
            assert isinstance(event, dict)
            assert json.loads("\n".join(data_lines)) == event
        else:
            assert event is None
    else:
        assert event is None
        reference_type, reference_lines = _reference_parse_line(line, event_type, data_lines)
        assert result_type == reference_type
        assert result_lines == reference_lines


def _harness_strip_citations(data):
    fdp = atheris.FuzzedDataProvider(data)
    text = fdp.ConsumeUnicodeNoSurrogates(1000)
    result = Formatter.strip_citations(text)
    assert isinstance(result, str)
    assert result == re.sub(r"\[\d+\]", "", text)


def _harness_unwrap_paragraph_lines(data):
    fdp = atheris.FuzzedDataProvider(data)
    text = fdp.ConsumeUnicodeNoSurrogates(2000)
    result = Formatter.unwrap_paragraph_lines(text)
    assert isinstance(result, str)
    assert result.count("\n") <= text.count("\n")


def _harness_is_structural_line(data):
    fdp = atheris.FuzzedDataProvider(data)
    line = fdp.ConsumeUnicodeNoSurrogates(300)
    result = _is_structural_line(line)
    assert isinstance(result, bool)
    assert result == _reference_is_structural_line(line)


def _harness_decrypt_token(data):
    fdp = atheris.FuzzedDataProvider(data)
    ciphertext = fdp.ConsumeUnicodeNoSurrogates(500)
    try:
        result = decrypt_token(ciphertext)
    except AuthenticationError:
        pass
    else:
        assert isinstance(result, str)
    if _run_state.roundtrip_enabled:
        plaintext = fdp.ConsumeUnicodeNoSurrogates(100) or "roundtrip-token"
        cipher = encrypt_token(plaintext)
        assert decrypt_token(cipher) == plaintext


def _harness_get_str_field(data):
    fdp = atheris.FuzzedDataProvider(data)
    raw_json = fdp.ConsumeUnicodeNoSurrogates(300)
    try:
        value = json.loads(raw_json)
    except (json.JSONDecodeError, ValueError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    field = fdp.ConsumeUnicodeNoSurrogates(30)
    default = fdp.ConsumeUnicodeNoSurrogates(20) if fdp.ConsumeBool() else None
    snapshot = dict(value)
    try:
        result = _get_str_field(value, field, default)
    except UpstreamSchemaError:
        assert value == snapshot
        return
    assert isinstance(result, str)
    assert value == snapshot
    assert result == value.get(field, default)


def _harness_extract_total_threads(data):
    fdp = atheris.FuzzedDataProvider(data)
    raw_json = fdp.ConsumeUnicodeNoSurrogates(200)
    try:
        value = json.loads(raw_json)
    except (json.JSONDecodeError, ValueError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    existing = fdp.ConsumeIntInRange(0, 10000) if fdp.ConsumeBool() else None
    snapshot = dict(value)
    try:
        result = _extract_total_threads(value, existing)
    except UpstreamSchemaError:
        assert value == snapshot
        return
    assert isinstance(result, int)
    assert value == snapshot
    if existing is not None:
        assert result == existing
    else:
        raw = value.get("total_threads", 0)
        assert isinstance(raw, int)
        assert result == raw


def _harness_require_mapping(data):
    fdp = atheris.FuzzedDataProvider(data)
    raw = fdp.ConsumeUnicodeNoSurrogates(300)
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        value = raw
    try:
        result = require_mapping(value, "fuzz-context")
    except UpstreamSchemaError:
        return
    assert isinstance(result, dict)
    assert result is value


def _harness_require_list(data):
    fdp = atheris.FuzzedDataProvider(data)
    raw = fdp.ConsumeUnicodeNoSurrogates(300)
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        value = raw
    try:
        result = require_list(value, "fuzz-context")
    except UpstreamSchemaError:
        return
    assert isinstance(result, list)
    assert result is value


def _harness_parse_thread_list_payload(data):
    fdp = atheris.FuzzedDataProvider(data)
    raw = fdp.ConsumeUnicodeNoSurrogates(500)
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        value = raw
    snapshot = list(value) if isinstance(value, list) else None
    try:
        result = parse_thread_list_payload(value)
    except UpstreamSchemaError:
        return
    assert isinstance(result, list)
    if snapshot is not None:
        assert list(value) == snapshot
    assert [id(entry) for entry in result] == [id(entry) for entry in value]


def _harness_parse_upload_url_response(data):
    fdp = atheris.FuzzedDataProvider(data)
    raw = fdp.ConsumeUnicodeNoSurrogates(500)
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        value = raw
    try:
        result = parse_upload_url_response(value)
    except UpstreamSchemaError:
        return
    assert isinstance(result, dict)
    assert result is value


def _harness_block_model_validate(data):
    fdp = atheris.FuzzedDataProvider(data)
    raw = fdp.ConsumeUnicodeNoSurrogates(500)
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        value = raw
    snapshot = dict(value) if isinstance(value, dict) else None
    try:
        block = Block.model_validate(value)
    except (ValidationError, UpstreamSchemaError):
        return
    assert isinstance(block, Block)
    if snapshot is not None:
        assert value == snapshot
    revalidated = Block.model_validate(block.model_dump())
    assert revalidated == block


def _harness_block_extract_text(data):
    fdp = atheris.FuzzedDataProvider(data)
    raw = fdp.ConsumeUnicodeNoSurrogates(500)
    try:
        content = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        content = {}
    if not isinstance(content, dict):
        content = {"fuzzed": content}
    usage = fdp.PickValueInList(["ask_text", "web_results", "plan_info", "unknown_type"])
    block = Block(intended_usage=usage, content=content)
    result = block.extract_text()
    assert result is None or isinstance(result, str)


def _harness_sse_message_model_validate(data):
    fdp = atheris.FuzzedDataProvider(data)
    raw = fdp.ConsumeUnicodeNoSurrogates(500)
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        value = raw
    snapshot = dict(value) if isinstance(value, dict) else None
    try:
        message = SSEMessage.model_validate(value)
    except (ValidationError, UpstreamSchemaError, TypeError):
        return
    assert isinstance(message, SSEMessage)
    if snapshot is not None:
        assert value == snapshot
    revalidated = SSEMessage.model_validate(message.model_dump())
    assert revalidated == message


# ===================================================================
# Registry and instrumentation targets
# ===================================================================

_HARNESSES = {
    "sse_decode_line": _harness_sse_decode_line,
    "sse_parse_line": _harness_sse_parse_line,
    "sse_yield_event": _harness_sse_yield_event,
    "sse_accumulate_line": _harness_sse_accumulate_line,
    "strip_citations": _harness_strip_citations,
    "unwrap_paragraph_lines": _harness_unwrap_paragraph_lines,
    "is_structural_line": _harness_is_structural_line,
    "decrypt_token": _harness_decrypt_token,
    "get_str_field": _harness_get_str_field,
    "extract_total_threads": _harness_extract_total_threads,
    "require_mapping": _harness_require_mapping,
    "require_list": _harness_require_list,
    "parse_thread_list_payload": _harness_parse_thread_list_payload,
    "parse_upload_url_response": _harness_parse_upload_url_response,
    "block_model_validate": _harness_block_model_validate,
    "block_extract_text": _harness_block_extract_text,
    "sse_message_model_validate": _harness_sse_message_model_validate,
}

_HARNESS_TARGETS = {
    "sse_decode_line": (SSEParser._decode_line,),
    "sse_parse_line": (SSEParser._parse_line,),
    "sse_yield_event": (SSEParser._yield_event,),
    "sse_accumulate_line": (SSEParser._accumulate_line,),
    "strip_citations": (Formatter.strip_citations,),
    "unwrap_paragraph_lines": (Formatter.unwrap_paragraph_lines,),
    "is_structural_line": (_is_structural_line,),
    "decrypt_token": (decrypt_token, encrypt_token),
    "get_str_field": (_get_str_field,),
    "extract_total_threads": (_extract_total_threads,),
    "require_mapping": (require_mapping,),
    "require_list": (require_list,),
    "parse_thread_list_payload": (parse_thread_list_payload,),
    "parse_upload_url_response": (parse_upload_url_response,),
    "block_model_validate": (Block._split_flat_payload,),
    "block_extract_text": (Block.extract_text,),
    "sse_message_model_validate": (SSEMessage._validate_upstream_shape,),
}


# ===================================================================
# Main entry point
# ===================================================================

_DEFAULT_CORPUS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "fuzz_corpus"
)


def _make_working_corpus(corpus_dir: str, name: str) -> str:
    """Copy the seed corpus to a writable scratch dir for libFuzzer.

    libFuzzer writes newly discovered "interesting" inputs back into the
    corpus directory it is given, so the committed corpus in
    ``tests/fuzz_corpus/`` must never be passed directly.  The scratch
    corpus lives beside the state file (inside pytest's temporary
    directory) when one is configured, otherwise in the system temp dir.
    """
    parent = Path(_run_state.state_path).parent if _run_state.state_path else Path("/tmp")
    working_dir = parent / f"fuzz-corpus-{name}"
    working_dir.mkdir(exist_ok=True)
    for seed_path in sorted(Path(corpus_dir).glob("*.bin")):
        (working_dir / seed_path.name).write_bytes(seed_path.read_bytes())
    return str(working_dir)


def _main(argv: list[str]) -> int:
    """Run one fuzz harness with instrumentation, corpus replay, and oracles."""
    if len(argv) < 2:
        print(
            f"Usage: {argv[0]} <harness_name> [iterations] [corpus_dir] [state_path]",
            file=sys.stderr,
        )
        print(f"Available: {', '.join(sorted(_HARNESSES))}", file=sys.stderr)
        return 2

    name = argv[1]
    if name not in _HARNESSES:
        print(f"Unknown harness: {name}", file=sys.stderr)
        print(f"Available: {', '.join(sorted(_HARNESSES))}", file=sys.stderr)
        return 2

    iterations = int(argv[2]) if len(argv) > 2 else 5000
    corpus_dir = argv[3] if len(argv) > 3 else _DEFAULT_CORPUS_DIR
    _run_state.state_path = argv[4] if len(argv) > 4 else None

    harness_fn = _HARNESSES[name]

    for target_func in _HARNESS_TARGETS[name]:
        if not _is_instrumented(target_func):
            print(
                f"ERROR: {_func_name(target_func)} is not instrumented; "
                "coverage-guided fuzzing would be disabled",
                file=sys.stderr,
            )
            return 3
        _run_state.instrumented_functions.append(_func_name(target_func))

    counted = _make_counted(harness_fn)
    _run_state.roundtrip_enabled = True
    _replay_corpus(counted, corpus_dir)
    _run_state.roundtrip_enabled = False

    working_corpus = _make_working_corpus(corpus_dir, name)
    atheris.Setup(
        [sys.argv[0], f"-atheris_runs={iterations}", working_corpus],
        counted,
    )
    atheris.Fuzz()
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
