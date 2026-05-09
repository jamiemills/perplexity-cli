"""Fuzz harness runner for atheris.

Each harness is registered in the ``_HARNESSES`` dict and can be invoked
from the command line as::

    python tests/_fuzz_harnesses.py <harness_name> [iterations]

atheris.Setup() can only be called once per process, so each pytest test
in ``test_fuzz.py`` spawns a fresh subprocess running this script.
"""

import json
import os
import sys

# Ensure the src layout is on the path when run as a script.
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_repo_root, "src"))

# Set isolated config dir to avoid touching real user config.
os.environ.setdefault("PERPLEXITY_CONFIG_DIR", "/tmp/fuzz-config-dir")

import atheris  # noqa: E402, I001

# ---------------------------------------------------------------------------
# Import target modules (without instrument_imports — too slow).
# ---------------------------------------------------------------------------
from pydantic import ValidationError  # noqa: E402

from perplexity_cli.api.client import SSEParser  # noqa: E402
from perplexity_cli.api.contracts import (  # noqa: E402
    parse_thread_list_payload,
    parse_upload_url_response,
    require_list,
    require_mapping,
)
from perplexity_cli.api.models import Block, SSEMessage  # noqa: E402
from perplexity_cli.formatting.base import (  # noqa: E402
    Formatter,
    _is_structural_line,
)
from perplexity_cli.threads.scraper import (  # noqa: E402
    _extract_total_threads,
    _get_str_field,
)
from perplexity_cli.utils.encryption import decrypt_token  # noqa: E402
from perplexity_cli.utils.exceptions import (  # noqa: E402
    AuthenticationError,
    UpstreamSchemaError,
)


# ===================================================================
# Harness definitions
# ===================================================================


def _harness_sse_decode_line(data):
    fdp = atheris.FuzzedDataProvider(data)
    raw = fdp.ConsumeBytes(500)
    try:
        result = SSEParser._decode_line(raw)
        assert isinstance(result, str)
    except UnicodeDecodeError:
        pass


def _harness_sse_parse_line(data):
    fdp = atheris.FuzzedDataProvider(data)
    line = fdp.ConsumeUnicodeNoSurrogates(300)
    event_type = fdp.ConsumeUnicodeNoSurrogates(50) if fdp.ConsumeBool() else None
    result = SSEParser._parse_line(line, event_type, [])
    assert isinstance(result, tuple)
    assert len(result) == 2


def _harness_sse_yield_event(data):
    fdp = atheris.FuzzedDataProvider(data)
    num_lines = fdp.ConsumeIntInRange(1, 5)
    lines = [fdp.ConsumeUnicodeNoSurrogates(200) for _ in range(num_lines)]
    try:
        SSEParser._yield_event(lines)
    except UpstreamSchemaError:
        pass


def _harness_sse_accumulate_line(data):
    fdp = atheris.FuzzedDataProvider(data)
    line = fdp.ConsumeUnicodeNoSurrogates(300)
    event_type = fdp.ConsumeUnicodeNoSurrogates(30) if fdp.ConsumeBool() else None
    data_lines = [fdp.ConsumeUnicodeNoSurrogates(100)] if fdp.ConsumeBool() else []
    try:
        result = SSEParser._accumulate_line(line, event_type, data_lines)
        assert isinstance(result, tuple)
        assert len(result) == 3
    except UpstreamSchemaError:
        pass


def _harness_strip_citations(data):
    fdp = atheris.FuzzedDataProvider(data)
    text = fdp.ConsumeUnicodeNoSurrogates(1000)
    result = Formatter.strip_citations(text)
    assert isinstance(result, str)


def _harness_unwrap_paragraph_lines(data):
    fdp = atheris.FuzzedDataProvider(data)
    text = fdp.ConsumeUnicodeNoSurrogates(2000)
    result = Formatter.unwrap_paragraph_lines(text)
    assert isinstance(result, str)


def _harness_is_structural_line(data):
    fdp = atheris.FuzzedDataProvider(data)
    line = fdp.ConsumeUnicodeNoSurrogates(300)
    result = _is_structural_line(line)
    assert isinstance(result, bool)


def _harness_decrypt_token(data):
    fdp = atheris.FuzzedDataProvider(data)
    ciphertext = fdp.ConsumeUnicodeNoSurrogates(500)
    try:
        decrypt_token(ciphertext)
    except AuthenticationError:
        pass


def _harness_get_str_field(data):
    fdp = atheris.FuzzedDataProvider(data)
    raw_json = fdp.ConsumeUnicodeNoSurrogates(300)
    try:
        d = json.loads(raw_json)
    except (json.JSONDecodeError, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    field = fdp.ConsumeUnicodeNoSurrogates(30)
    default = fdp.ConsumeUnicodeNoSurrogates(20) if fdp.ConsumeBool() else None
    try:
        result = _get_str_field(d, field, default)
        assert isinstance(result, str)
    except UpstreamSchemaError:
        pass


def _harness_extract_total_threads(data):
    fdp = atheris.FuzzedDataProvider(data)
    raw_json = fdp.ConsumeUnicodeNoSurrogates(200)
    try:
        d = json.loads(raw_json)
    except (json.JSONDecodeError, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    existing = fdp.ConsumeIntInRange(0, 10000) if fdp.ConsumeBool() else None
    try:
        result = _extract_total_threads(d, existing)
        assert isinstance(result, int)
    except UpstreamSchemaError:
        pass


def _harness_require_mapping(data):
    fdp = atheris.FuzzedDataProvider(data)
    raw = fdp.ConsumeUnicodeNoSurrogates(300)
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        value = raw
    try:
        result = require_mapping(value, "fuzz-context")
        assert isinstance(result, dict)
    except UpstreamSchemaError:
        pass


def _harness_require_list(data):
    fdp = atheris.FuzzedDataProvider(data)
    raw = fdp.ConsumeUnicodeNoSurrogates(300)
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        value = raw
    try:
        result = require_list(value, "fuzz-context")
        assert isinstance(result, list)
    except UpstreamSchemaError:
        pass


def _harness_parse_thread_list_payload(data):
    fdp = atheris.FuzzedDataProvider(data)
    raw = fdp.ConsumeUnicodeNoSurrogates(500)
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        value = raw
    try:
        result = parse_thread_list_payload(value)
        assert isinstance(result, list)
    except UpstreamSchemaError:
        pass


def _harness_parse_upload_url_response(data):
    fdp = atheris.FuzzedDataProvider(data)
    raw = fdp.ConsumeUnicodeNoSurrogates(500)
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        value = raw
    try:
        result = parse_upload_url_response(value)
        assert isinstance(result, dict)
    except UpstreamSchemaError:
        pass


def _harness_block_model_validate(data):
    fdp = atheris.FuzzedDataProvider(data)
    raw = fdp.ConsumeUnicodeNoSurrogates(500)
    try:
        d = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        d = raw
    try:
        Block.model_validate(d)
    except (ValidationError, UpstreamSchemaError):
        pass


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
        d = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        d = raw
    try:
        SSEMessage.model_validate(d)
    except (ValidationError, UpstreamSchemaError, TypeError):
        pass


# ===================================================================
# Registry
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


# ===================================================================
# Main entry point
# ===================================================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <harness_name> [iterations]", file=sys.stderr)
        print(f"Available: {', '.join(sorted(_HARNESSES))}", file=sys.stderr)
        sys.exit(2)

    name = sys.argv[1]
    iterations = int(sys.argv[2]) if len(sys.argv) > 2 else 5000

    if name not in _HARNESSES:
        print(f"Unknown harness: {name}", file=sys.stderr)
        print(f"Available: {', '.join(sorted(_HARNESSES))}", file=sys.stderr)
        sys.exit(2)

    harness_fn = _HARNESSES[name]

    atheris.Setup(
        [sys.argv[0], f"-atheris_runs={iterations}"],
        harness_fn,
    )
    atheris.Fuzz()
