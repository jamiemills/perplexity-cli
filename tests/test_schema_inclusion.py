"""Tests for optional $schema inclusion in JSON envelope output.

Covers:
- envelope_to_dict() with and without include_schema
- write_envelope() convenience function
- $schema key positioning and content validity
- CLI --schema flag integration with --json
- NDJSON ResultEvent $schema support
"""

import json
from io import StringIO
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from perplexity_cli.envelope import (
    Envelope,
    ErrorCode,
    ErrorEnvelope,
    Meta,
    NextAction,
    envelope_to_dict,
    error_envelope,
    success_envelope,
    write_envelope,
)

# ---------------------------------------------------------------------------
# Unit tests: envelope_to_dict
# ---------------------------------------------------------------------------


class TestEnvelopeToDict:
    """Tests for the envelope_to_dict helper function."""

    def test_without_schema_matches_model_dump(self) -> None:
        """Without include_schema, output matches model_dump(mode='json')."""
        env = success_envelope("test", {"key": "value"})
        result = envelope_to_dict(env)
        expected = env.model_dump(mode="json")
        assert result == expected

    def test_with_schema_adds_dollar_schema_key(self) -> None:
        """With include_schema=True, the dict gains a $schema key."""
        env = success_envelope("test", {"key": "value"})
        result = envelope_to_dict(env, include_schema=True)
        assert "$schema" in result

    def test_without_schema_omits_dollar_schema_key(self) -> None:
        """With include_schema=False (default), no $schema key is present."""
        env = success_envelope("test", {"key": "value"})
        result = envelope_to_dict(env)
        assert "$schema" not in result

    def test_schema_is_first_key(self) -> None:
        """$schema should be the first key in the dict (convention)."""
        env = success_envelope("test", {"key": "value"})
        result = envelope_to_dict(env, include_schema=True)
        keys = list(result.keys())
        assert keys[0] == "$schema"

    def test_schema_content_is_valid_json_schema(self) -> None:
        """The $schema value should be a valid JSON Schema object."""
        env = success_envelope("test", {"answer": "42"})
        result = envelope_to_dict(env, include_schema=True)
        schema = result["$schema"]
        assert isinstance(schema, dict)
        assert "properties" in schema
        assert "ok" in schema["properties"]
        assert "command" in schema["properties"]
        assert "result" in schema["properties"]

    def test_schema_matches_envelope_model_json_schema(self) -> None:
        """$schema value should match Envelope.model_json_schema()."""
        env = success_envelope("test", {"key": "value"})
        result = envelope_to_dict(env, include_schema=True)
        expected_schema = Envelope.model_json_schema()
        assert result["$schema"] == expected_schema

    def test_error_envelope_schema_matches_error_model(self) -> None:
        """For ErrorEnvelope, $schema should match ErrorEnvelope.model_json_schema()."""
        env = error_envelope("test", ErrorCode.internal_error, "Something broke")
        result = envelope_to_dict(env, include_schema=True)
        expected_schema = ErrorEnvelope.model_json_schema()
        assert result["$schema"] == expected_schema

    def test_error_envelope_without_schema(self) -> None:
        """ErrorEnvelope without include_schema matches model_dump."""
        env = error_envelope("test", ErrorCode.internal_error, "fail")
        result = envelope_to_dict(env)
        expected = env.model_dump(mode="json")
        assert result == expected

    def test_schema_does_not_affect_other_fields(self) -> None:
        """All non-$schema fields should be identical with or without schema."""
        meta = Meta(duration_ms=100, version="0.7.0", trace_id="abc-123")
        action = NextAction(command="retry", description="Try again")
        env = success_envelope("test", {"answer": "42"}, meta=meta, next_actions=[action])

        without = envelope_to_dict(env, include_schema=False)
        with_schema = envelope_to_dict(env, include_schema=True)

        # Remove $schema and compare
        with_schema_copy = {k: v for k, v in with_schema.items() if k != "$schema"}
        assert with_schema_copy == without

    def test_schema_is_json_serialisable(self) -> None:
        """The entire output including $schema should be JSON-serialisable."""
        env = success_envelope("test", {"answer": "42"})
        result = envelope_to_dict(env, include_schema=True)
        serialised = json.dumps(result)
        restored = json.loads(serialised)
        assert restored == result


# ---------------------------------------------------------------------------
# Unit tests: write_envelope
# ---------------------------------------------------------------------------


class TestWriteEnvelope:
    """Tests for the write_envelope convenience function."""

    def test_writes_json_line_to_output(self) -> None:
        """write_envelope should write a single JSON line to the given stream."""
        env = success_envelope("test", {"key": "value"})
        buf = StringIO()
        write_envelope(env, output=buf)
        line = buf.getvalue()
        assert line.endswith("\n")
        data = json.loads(line)
        assert data["ok"] is True
        assert data["command"] == "test"

    def test_writes_to_stdout_by_default(self) -> None:
        """write_envelope should default to sys.stdout."""
        env = success_envelope("test", {"key": "value"})
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            write_envelope(env)
            output = mock_stdout.getvalue()
        data = json.loads(output)
        assert data["command"] == "test"

    def test_writes_with_schema_when_requested(self) -> None:
        """write_envelope with include_schema=True should include $schema."""
        env = success_envelope("test", {"key": "value"})
        buf = StringIO()
        write_envelope(env, include_schema=True, output=buf)
        data = json.loads(buf.getvalue())
        assert "$schema" in data

    def test_writes_without_schema_by_default(self) -> None:
        """write_envelope defaults to no $schema."""
        env = success_envelope("test", {"key": "value"})
        buf = StringIO()
        write_envelope(env, output=buf)
        data = json.loads(buf.getvalue())
        assert "$schema" not in data

    def test_error_envelope_writes_correctly(self) -> None:
        """write_envelope handles ErrorEnvelope correctly."""
        env = error_envelope("test", ErrorCode.rate_limited, "Too many requests")
        buf = StringIO()
        write_envelope(env, include_schema=True, output=buf)
        data = json.loads(buf.getvalue())
        assert data["ok"] is False
        assert "$schema" in data
        assert data["error"]["code"] == "rate_limited"


# ---------------------------------------------------------------------------
# CLI integration tests: --schema flag
# ---------------------------------------------------------------------------


class TestSchemaFlagIntegration:
    """Test --schema flag on CLI commands."""

    def test_config_show_json_schema(self, runner: CliRunner) -> None:
        """pxcli config show --json --schema should include $schema."""
        from perplexity_cli.cli import main

        result = runner.invoke(main, ["config", "show", "--json", "--schema"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "$schema" in data
        assert data["ok"] is True

    def test_config_show_json_without_schema(self, runner: CliRunner) -> None:
        """pxcli config show --json (no --schema) should not include $schema."""
        from perplexity_cli.cli import main

        result = runner.invoke(main, ["config", "show", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "$schema" not in data

    def test_schema_flag_without_json_is_ignored(self, runner: CliRunner) -> None:
        """--schema without --json should not affect output."""
        from perplexity_cli.cli import main

        result = runner.invoke(main, ["config", "show", "--schema"])
        assert result.exit_code == 0
        # Output should be human-readable, not JSON
        # Should not crash or produce JSON
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.output)

    def test_auth_status_json_schema(self, runner: CliRunner) -> None:
        """pxcli auth status --json --schema should include $schema."""
        from perplexity_cli.cli import main

        result = runner.invoke(main, ["auth", "status", "--json", "--schema"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "$schema" in data

    def test_schema_value_has_envelope_properties(self, runner: CliRunner) -> None:
        """The $schema value should describe the envelope structure."""
        from perplexity_cli.cli import main

        result = runner.invoke(main, ["config", "show", "--json", "--schema"])
        data = json.loads(result.output)
        schema = data["$schema"]
        assert "properties" in schema
        assert "ok" in schema["properties"]
        assert "command" in schema["properties"]
        assert "result" in schema["properties"]


# ---------------------------------------------------------------------------
# NDJSON $schema support
# ---------------------------------------------------------------------------


class TestNDJSONSchemaSupport:
    """Test $schema inclusion in NDJSON ResultEvent."""

    def test_result_event_with_schema(self) -> None:
        """NDJSONWriter.result() with include_schema should include $schema in output."""
        from perplexity_cli.ndjson import NDJSONWriter

        buf = StringIO()
        writer = NDJSONWriter(output=buf)
        writer.result(
            ok=True,
            command="test",
            result={"answer": "42"},
            include_schema=True,
        )
        data = json.loads(buf.getvalue())
        assert "$schema" in data

    def test_result_event_without_schema(self) -> None:
        """NDJSONWriter.result() without include_schema should omit $schema."""
        from perplexity_cli.ndjson import NDJSONWriter

        buf = StringIO()
        writer = NDJSONWriter(output=buf)
        writer.result(
            ok=True,
            command="test",
            result={"answer": "42"},
        )
        data = json.loads(buf.getvalue())
        assert "$schema" not in data

    def test_result_schema_is_result_event_schema(self) -> None:
        """The $schema in NDJSON result should be the ResultEvent JSON schema."""
        from perplexity_cli.ndjson import NDJSONWriter, ResultEvent

        buf = StringIO()
        writer = NDJSONWriter(output=buf)
        writer.result(
            ok=True,
            command="test",
            result={"answer": "42"},
            include_schema=True,
        )
        data = json.loads(buf.getvalue())
        assert data["$schema"] == ResultEvent.model_json_schema()

    def test_non_result_events_unaffected(self) -> None:
        """Start, progress, and chunk events should not have $schema."""
        from perplexity_cli.ndjson import NDJSONWriter

        buf = StringIO()
        writer = NDJSONWriter(output=buf)
        writer.start("test")
        writer.progress("Loading...", percent=50.0)
        writer.chunk("Hello")

        lines = buf.getvalue().strip().split("\n")
        for line in lines:
            data = json.loads(line)
            assert "$schema" not in data
