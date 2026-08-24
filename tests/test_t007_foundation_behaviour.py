"""Public behavioural coverage for T007 foundation utilities."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from perplexity_cli.config.models import URLConfig
from perplexity_cli.envelope import (
    ErrorCode,
    Meta,
    NextAction,
    envelope_to_dict,
    error_envelope,
    success_envelope,
    write_envelope,
)
from perplexity_cli.exit_codes import format_exit_codes_help
from perplexity_cli.models.model_config import ModelConfigEntry, ModelConfigResponse, ModelInfo
from perplexity_cli.ndjson import NDJSONWriter
from perplexity_cli.runners.models import build_models_json_result, format_model_table
from perplexity_cli.utils import upstream_contracts
from perplexity_cli.utils.config import (
    clear_urls_cache,
    get_config_dir,
    get_model_config_endpoint,
    get_query_endpoint,
    get_s3_bucket_url,
    get_thread_list_url,
    get_upload_url_endpoint,
    get_user_settings_endpoint,
)
from perplexity_cli.utils.exceptions import UpstreamSchemaError
from perplexity_cli.utils.file_handler import load_attachments, resolve_file_arguments
from perplexity_cli.utils.logging import JSONLogFormatter, redact_response_text, setup_logging
from perplexity_cli.utils.style_manager import StyleManager


def test_url_config_rejects_inclusive_ascii_control_upper_bound() -> None:
    """The public URL model rejects ASCII control character 0x1f."""
    with pytest.raises(ValueError, match="whitespace or control"):
        URLConfig(base_url="https://example.com/" + chr(0x1F) + "path")


def test_config_dir_honours_explicit_directory_and_expands_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The explicit config directory is the public resolution override."""
    configured = tmp_path / "config"
    monkeypatch.setenv("PERPLEXITY_CONFIG_DIR", str(configured))
    assert get_config_dir() == configured
    assert configured.is_dir()


def test_config_dir_uses_xdg_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Linux config resolution uses XDG_CONFIG_HOME when present."""
    monkeypatch.delenv("PERPLEXITY_CONFIG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(os, "name", "posix")
    assert get_config_dir() == tmp_path / "perplexity-cli"


def test_config_dir_uses_windows_appdata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Windows resolution uses APPDATA rather than the XDG location."""
    monkeypatch.delenv("PERPLEXITY_CONFIG_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(
        "perplexity_cli.utils.config.impl.os",
        SimpleNamespace(name="nt", getenv=os.getenv),
    )
    monkeypatch.setattr("perplexity_cli.utils.config.impl.Path.home", lambda: tmp_path)
    assert get_config_dir() == tmp_path / "perplexity-cli"


@pytest.mark.parametrize(
    ("name", "accessor"),
    [
        ("PERPLEXITY_QUERY_ENDPOINT", get_query_endpoint),
        ("PERPLEXITY_THREAD_LIST_ENDPOINT", get_thread_list_url),
        ("PERPLEXITY_UPLOAD_URL_ENDPOINT", get_upload_url_endpoint),
        ("PERPLEXITY_S3_BUCKET_URL", get_s3_bucket_url),
        ("PERPLEXITY_MODEL_CONFIG_ENDPOINT", get_model_config_endpoint),
        ("PERPLEXITY_USER_SETTINGS_ENDPOINT", get_user_settings_endpoint),
    ],
)
def test_public_url_accessor_reflects_environment_override(
    name: str, accessor: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each URL accessor reflects its corresponding environment override."""
    clear_urls_cache()
    monkeypatch.setattr("perplexity_cli.utils.config.impl.get_config_dir", lambda: tmp_path)
    value = "https://example.test/value"
    monkeypatch.setenv(name, value)
    assert accessor() == value  # type: ignore[operator]
    clear_urls_cache()


def test_envelope_serialisation_preserves_meta_and_actions() -> None:
    """Envelope serialisation preserves all structured fields."""
    meta = Meta(duration_ms=4, version="1", trace_id="trace")
    action = NextAction(command="help", description="follow up", params={"x": "y"})
    envelope = success_envelope("query", {"answer": "ok"}, meta, [action])
    result = envelope_to_dict(envelope)
    assert result == {
        "ok": True,
        "command": "query",
        "result": {"answer": "ok"},
        "meta": {"duration_ms": 4, "version": "1", "trace_id": "trace", "truncated": False},
        "next_actions": [{"command": "help", "description": "follow up", "params": {"x": "y"}}],
    }


def test_error_envelope_serialisation_preserves_optional_fields() -> None:
    """Error envelopes retain code, input, fix, and actions."""
    envelope = error_envelope(
        "query",
        ErrorCode.validation_error,
        "invalid",
        ("retry", {"field": "query"}, [NextAction(command="help", description="details")]),
    )
    result = envelope_to_dict(envelope)
    assert result["ok"] is False
    assert result["error"] == {
        "code": "validation_error",
        "message": "invalid",
        "input": {"field": "query"},
    }
    assert result["fix"] == "retry"
    assert result["next_actions"][0]["command"] == "help"


def test_write_envelope_uses_supplied_output() -> None:
    """Writing to an explicit stream emits one JSON line and no extra output."""
    output = io.StringIO()
    write_envelope(success_envelope("query", {"answer": "ok"}), output=output)
    lines = output.getvalue().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["result"] == {"answer": "ok"}


def test_envelope_schema_is_opt_in_at_public_writer_boundary() -> None:
    """Schema metadata appears only when explicitly requested."""
    output = io.StringIO()
    write_envelope(
        success_envelope("query", {"answer": "ok"}),
        include_schema="with_schema",
        output=output,
    )
    payload = json.loads(output.getvalue())
    assert payload["$schema"]["title"] == "Envelope"
    assert payload["ok"] is True


def test_ndjson_result_includes_schema_and_flushes() -> None:
    """The public result writer emits optional schema metadata and flushes."""
    output = MagicMock()
    writer = NDJSONWriter(output)
    writer.result(True, "query", {"answer": "ok"}, (None, None, True))
    payload = json.loads(output.write.call_args.args[0])
    assert payload["$schema"]
    assert payload["ok"] is True
    output.flush.assert_called_once_with()


def test_ndjson_writer_emits_each_event_type() -> None:
    """Convenience methods preserve their event type and payload."""
    output = MagicMock()
    writer = NDJSONWriter(output)
    writer.start("query")
    writer.progress("working", 50)
    writer.chunk("piece")
    events = [json.loads(call.args[0]) for call in output.write.call_args_list]
    assert [(event["type"], event.get("percent"), event.get("text")) for event in events] == [
        ("start", None, None),
        ("progress", 50, None),
        ("chunk", None, "piece"),
    ]
    assert output.flush.call_count == 3


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "null"),
        ({"b": 1, "a": 2}, "object(keys=[a, b])"),
        ([1, 2], "array(len=2)"),
        ("abc", "string(len=3)"),
        (4, "int"),
    ],
)
def test_describe_payload_shape(value: object, expected: str) -> None:
    """Payload diagnostics distinguish each supported public JSON shape."""
    assert upstream_contracts.describe_payload_shape(value) == expected


def test_upstream_contract_public_parsers_validate_nested_shapes() -> None:
    """Upload and thread parsers accept valid public payloads and reject invalid ones."""
    upload = {"results": {"file-id": {"upload_url": "https://example.test"}}}
    assert upstream_contracts.parse_upload_url_response(upload) is upload
    assert upstream_contracts.parse_thread_list_payload([{"thread_id": "1"}]) == [
        {"thread_id": "1"}
    ]
    with pytest.raises(UpstreamSchemaError):
        upstream_contracts.parse_upload_url_response({"results": []})
    with pytest.raises(UpstreamSchemaError):
        upstream_contracts.parse_thread_list_payload(["wrong"])


def test_upstream_contract_parsers_reject_invalid_nested_entries() -> None:
    """Nested upload and thread entries must remain mappings."""
    with pytest.raises(UpstreamSchemaError, match="upload result entry"):
        upstream_contracts.parse_upload_url_response({"results": {"id": []}})
    with pytest.raises(UpstreamSchemaError, match="thread entry"):
        upstream_contracts.parse_thread_list_payload([{"thread_id": "1"}, None])


def test_file_paths_extract_tilde_paths_and_trailing_punctuation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inline and tilde paths resolve through the public file argument API."""
    target = tmp_path / "note.txt"
    target.write_text("content")

    def expanduser(path: Path) -> Path:
        return tmp_path / path.name

    monkeypatch.setattr(Path, "expanduser", expanduser)
    result = resolve_file_arguments([f"See {target}, and ~/note.txt!"])
    assert result == [target.resolve()]


def test_file_arguments_ignore_empty_attach_values(tmp_path: Path) -> None:
    """Empty comma-separated attach segments have no observable effect."""
    target = tmp_path / "note.txt"
    target.write_text("content")
    assert resolve_file_arguments([], [f" , {target}, "]) == [target.resolve()]


def test_load_attachments_rejects_directory(tmp_path: Path) -> None:
    """The public loader accepts files, not directories."""
    with pytest.raises(ValueError):
        load_attachments([tmp_path])


def test_resolve_directory_skips_sensitive_and_hidden_entries(tmp_path: Path) -> None:
    """Directory attachment discovery excludes credentials and hidden files."""
    (tmp_path / "safe.txt").write_text("safe")
    (tmp_path / ".env.local").write_text("secret")
    (tmp_path / "private.key").write_text("secret")
    (tmp_path / ".hidden.txt").write_text("hidden")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("secret")
    assert resolve_file_arguments([], [str(tmp_path)]) == [tmp_path / "safe.txt"]


def test_style_manager_public_validation_and_missing_style(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Style validation and missing-style loading are stable public behaviour."""
    style_path = tmp_path / "style.json"
    monkeypatch.setattr(
        "perplexity_cli.utils.style_manager.get_config_paths",
        lambda: type("Paths", (), {"style_path": style_path})(),
    )
    manager = StyleManager()
    assert manager.validate_style(" concise ") is True
    assert manager.validate_style(" " * 3) is False
    style_path.write_text(json.dumps({"created_at": "now"}))
    assert manager.load_style() is None


def test_style_manager_save_and_clear_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Saving persists the style and clearing is idempotent."""
    style_path = tmp_path / "style.json"
    monkeypatch.setattr(
        "perplexity_cli.utils.style_manager.get_config_paths",
        lambda: type("Paths", (), {"style_path": style_path})(),
    )
    manager = StyleManager()
    manager.save_style("answer briefly")
    assert manager.load_style() == "answer briefly"
    manager.clear_style()
    manager.clear_style()
    assert manager.load_style() is None


def test_model_config_search_filters_by_mode_and_falls_back() -> None:
    """Model search selects search-mode IDs and falls back when none match."""
    search = ModelConfigEntry(label="Search", subscription_tier="pro", non_reasoning_model="s")
    other = ModelConfigEntry(label="Other", subscription_tier="pro", non_reasoning_model="o")
    response = ModelConfigResponse(
        models={"s": ModelInfo(label="Search", mode="search")}, config=[search, other]
    )
    assert response.search_models() == [search]
    response.models = {"missing": ModelInfo(label="Missing", mode="search")}
    assert response.search_models() == [search, other]


def test_exit_code_help_lists_numeric_contract() -> None:
    """Human-readable exit-code help includes every documented code."""
    help_text = format_exit_codes_help()
    assert help_text.startswith("Exit codes:\n")
    for code in ("0", "1", "2", "3", "4", "5", "6", "7", "130"):
        assert f"  {code}" in help_text


def test_logging_formatter_emits_structured_record() -> None:
    """Structured logging retains level and logger identity without body leakage."""
    formatter = JSONLogFormatter(trace_id="trace")
    record = setup_logging().makeRecord("perplexity_cli", 20, "", 0, "token=%s", ("secret",), None)
    payload = json.loads(formatter.format(record))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "perplexity_cli"
    assert payload["trace_id"] == "trace"
    assert "secret" not in redact_response_text("secret")


def test_model_table_and_json_empty_inputs_are_consistent() -> None:
    """Public model formatters represent an empty model list consistently."""
    assert "No models available" in format_model_table([])
    assert build_models_json_result([]) == {"models": []}
