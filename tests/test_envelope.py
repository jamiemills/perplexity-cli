"""Tests for JSON output envelope models and builders."""

from perplexity_cli.envelope import (
    Envelope,
    ErrorCode,
    ErrorDetail,
    ErrorEnvelope,
    Meta,
    NextAction,
    error_envelope,
    success_envelope,
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
