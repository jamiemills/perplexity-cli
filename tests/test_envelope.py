"""Tests for JSON output envelope models and builders."""

import inspect
import io
import json

import pytest

from perplexity_cli.envelope import (
    Envelope,
    ErrorCode,
    ErrorDetail,
    ErrorEnvelope,
    Meta,
    NextAction,
    envelope_to_dict,
    error_envelope,
    success_envelope,
    write_envelope,
)


class TestEnvelope:
    """Tests for Envelope and related models."""

    def test_required_fields(self):
        """Test that Envelope requires command and result."""
        env = Envelope(command="ask", result={"answer": "42"})
        assert env.ok is True
        assert env.command == "ask"
        assert env.result == {"answer": "42"}

    def test_optional_fields(self):
        """Test that meta and next_actions default correctly."""
        env = Envelope(command="ask", result={})
        assert env.meta is None
        assert env.next_actions == []

    def test_serialisation_round_trip(self):
        """Test that model_dump -> model_validate preserves all fields."""
        meta = Meta(duration_ms=100, version="1.0.0", trace_id="abc-123", truncated=True)
        action = NextAction(command="follow-up", description="Ask a follow-up question")
        env = Envelope(command="ask", result={"answer": "42"}, meta=meta, next_actions=[action])
        data = env.model_dump()
        restored = Envelope.model_validate(data)
        assert restored == env

    def test_error_envelope_required_fields(self):
        """Test that ErrorEnvelope requires ok=False, command, and error."""
        detail = ErrorDetail(code=ErrorCode.internal_error, message="Something broke")
        env = ErrorEnvelope(command="ask", error=detail)
        assert env.ok is False
        assert env.command == "ask"
        assert env.error.code == ErrorCode.internal_error

    def test_error_envelope_optional_fields(self):
        """Test that fix and next_actions default correctly on ErrorEnvelope."""
        detail = ErrorDetail(code=ErrorCode.internal_error, message="fail")
        env = ErrorEnvelope(command="ask", error=detail)
        assert env.fix is None
        assert env.next_actions == []

    def test_next_action_model(self):
        """Test NextAction requires command and description, params optional."""
        action = NextAction(command="retry", description="Try again")
        assert action.command == "retry"
        assert action.description == "Try again"
        assert action.params is None

        action_with_params = NextAction(
            command="retry", description="Try again", params={"delay": "5"}
        )
        assert action_with_params.params == {"delay": "5"}

    def test_meta_model(self):
        """Test Meta requires all fields, truncated defaults to False."""
        meta = Meta(duration_ms=50, version="0.1.0", trace_id="t-1")
        assert meta.duration_ms == 50
        assert meta.version == "0.1.0"
        assert meta.trace_id == "t-1"
        assert meta.truncated is False

    def test_success_envelope_builder(self):
        """Test success_envelope produces a valid Envelope with ok=True."""
        env = success_envelope("ask", {"answer": "hello"})
        assert isinstance(env, Envelope)
        assert env.ok is True
        assert env.command == "ask"
        assert env.result == {"answer": "hello"}

    def test_error_envelope_builder(self):
        """Test error_envelope produces a valid ErrorEnvelope with ok=False."""
        env = error_envelope("ask", ErrorCode.rate_limited, "Too many requests")
        assert isinstance(env, ErrorEnvelope)
        assert env.ok is False
        assert env.error.code == ErrorCode.rate_limited
        assert env.error.message == "Too many requests"


class TestErrorCode:
    """Tests for ErrorCode enum."""

    def test_all_error_codes_are_valid_members(self):
        """Test that all expected error code strings are valid enum members."""
        expected = [
            "authentication_required",
            "permission_denied",
            "rate_limited",
            "network_error",
            "timeout",
            "upstream_schema_error",
            "configuration_error",
            "attachment_error",
            "validation_error",
            "not_found",
            "internal_error",
        ]
        for code_str in expected:
            assert isinstance(ErrorCode(code_str), ErrorCode)


class TestEnvelopeBuilderExtras:
    """Tests for optional extras passed to the envelope builders."""

    def test_error_envelope_preserves_all_extras(self):
        """Fix, error input, and next actions are stored when provided."""
        action = NextAction(command="retry", description="Try again")
        env = error_envelope(
            "ask",
            ErrorCode.validation_error,
            "bad input",
            extras=("check the query", {"field": "q"}, [action]),
        )
        assert env.fix == "check the query"
        assert env.error.input == {"field": "q"}
        assert env.next_actions == [action]

    def test_error_envelope_defaults_without_extras(self):
        """Missing extras fall back to None fix, empty input, no actions."""
        env = error_envelope("ask", ErrorCode.internal_error, "boom")
        assert env.fix is None
        assert env.error.input == {}
        assert env.next_actions == []

    def test_success_envelope_preserves_next_actions(self):
        """Explicit next actions survive envelope construction."""
        action = NextAction(command="follow-up", description="Ask more")
        env = success_envelope("ask", {}, next_actions=[action])
        assert env.next_actions == [action]


class TestEnvelopeToDict:
    """Tests for envelope_to_dict serialisation semantics."""

    def test_json_mode_serialises_enum_values_as_strings(self):
        """model_dump(mode="json") renders error codes as their string values."""
        env = error_envelope("ask", ErrorCode.internal_error, "boom")
        data = envelope_to_dict(env)
        assert data["ok"] is False
        assert data["error"]["code"] == "internal_error"
        assert isinstance(data["error"]["code"], str)

    def test_with_schema_prepends_schema_key(self):
        """Schema inclusion embeds a $schema key ahead of the envelope."""
        env = success_envelope("ask", {"answer": "42"})
        data = envelope_to_dict(env, include_schema="with_schema")
        assert next(iter(data)) == "$schema"
        assert data["command"] == "ask"

    def test_default_inclusion_omits_schema(self):
        """The default serialisation contains no $schema key."""
        env = success_envelope("ask", {})
        assert "$schema" not in envelope_to_dict(env)

    def test_default_include_schema_is_documented_literal(self):
        """The documented default for include_schema is the no-schema literal."""
        default = inspect.signature(envelope_to_dict).parameters["include_schema"].default
        assert default == "no_schema"


class TestWriteEnvelope:
    """Tests for write_envelope output contract."""

    def test_writes_single_json_line_with_trailing_newline(self):
        """The envelope is serialised as exactly one JSON line."""
        buffer = io.StringIO()
        write_envelope(success_envelope("ask", {"n": 1}), output=buffer)
        lines = buffer.getvalue().splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["result"] == {"n": 1}

    def test_with_schema_embeds_schema_in_output(self):
        """Schema inclusion reaches the written JSON payload."""
        buffer = io.StringIO()
        write_envelope(
            success_envelope("ask", {}),
            include_schema="with_schema",
            output=buffer,
        )
        assert "$schema" in json.loads(buffer.getvalue())

    def test_defaults_to_stdout_when_output_omitted(self, capsys):
        """Without an explicit output the envelope goes to stdout."""
        write_envelope(success_envelope("ask", {"n": 1}))
        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["result"] == {"n": 1}

    def test_unserialisable_payload_values_are_rejected(self):
        """Payloads pydantic cannot serialise never reach the output stream."""

        class _Opaque:
            def __str__(self) -> str:
                return "opaque-sentinel"

        buffer = io.StringIO()
        with pytest.raises(Exception, match="Unable to serialize"):
            write_envelope(success_envelope("ask", {"weird": _Opaque()}), output=buffer)
        assert buffer.getvalue() == ""

    def test_default_include_schema_is_documented_literal(self):
        """The documented default for include_schema is the no-schema literal."""
        default = inspect.signature(write_envelope).parameters["include_schema"].default
        assert default == "no_schema"
