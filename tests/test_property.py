"""Property-based tests using Hypothesis.

Validates invariants that should hold for any valid input, not just
the specific examples covered by unit tests.  Hypothesis generates
random inputs, runs the invariant check, and shrinks failures to
minimal counterexamples.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from perplexity_cli.api.contracts import (
    describe_payload_shape,
    require_list,
    require_mapping,
)
from perplexity_cli.api.models import SSEMessage, WebResult
from perplexity_cli.envelope import (
    Envelope,
    ErrorCode,
    ErrorDetail,
    ErrorEnvelope,
    Meta,
    NextAction,
)
from perplexity_cli.threads.date_parser import parse_absolute_date_string
from perplexity_cli.utils.encryption import decrypt_token, encrypt_token
from perplexity_cli.utils.exceptions import (
    AuthenticationError,
    ConfigurationError,
    PerplexityRequestError,
    RateLimitError,
    UpstreamSchemaError,
)
from perplexity_cli.utils.retry import get_backoff_delay, is_retryable_error

# ---------------------------------------------------------------------------
# Encryption round-trip
# ---------------------------------------------------------------------------


@given(token=st.text(min_size=1, max_size=500))
@settings()
def test_encrypt_decrypt_roundtrip(token: str) -> None:
    """encrypt_token then decrypt_token returns the original token."""
    encrypted = encrypt_token(token)
    decrypted = decrypt_token(encrypted)
    assert decrypted == token


@given(token=st.text(min_size=1, max_size=500))
@settings()
def test_encrypt_produces_different_ciphertexts(token: str) -> None:
    """Encrypting the same token twice produces different ciphertexts."""
    encrypted1 = encrypt_token(token)
    encrypted2 = encrypt_token(token)
    assert encrypted1 != encrypted2


# ---------------------------------------------------------------------------
# Envelope serialization round-trip
# ---------------------------------------------------------------------------


def _meta_strategy() -> st.SearchStrategy[Meta]:
    return st.builds(
        Meta,
        duration_ms=st.integers(min_value=0, max_value=600_000),
        version=st.text(min_size=1, max_size=20, alphabet=st.characters(codec="ascii")),
        trace_id=st.text(min_size=1, max_size=40, alphabet=st.characters(codec="ascii")),
        truncated=st.booleans(),
    )


def _next_action_strategy() -> st.SearchStrategy[NextAction]:
    return st.builds(
        NextAction,
        command=st.text(min_size=1, max_size=30, alphabet=st.characters(codec="ascii")),
        description=st.text(min_size=1, max_size=100),
        params=st.none()
        | st.dictionaries(
            keys=st.text(min_size=1, max_size=10),
            values=st.text(min_size=1, max_size=20),
            max_size=5,
        ),
    )


@given(
    meta=_meta_strategy(),
    next_actions=st.lists(_next_action_strategy(), max_size=10),
    answer=st.text(max_size=500),
    references=st.lists(
        st.builds(
            dict,
            index=st.integers(min_value=1, max_value=100),
            title=st.text(min_size=1, max_size=100),
            url=st.text(min_size=1, max_size=200),
            snippet=st.text(max_size=200),
        ),
        max_size=10,
    ),
)
@settings(suppress_health_check=[HealthCheck.too_slow])
def test_success_envelope_roundtrip(
    meta: Meta,
    next_actions: list[NextAction],
    answer: str,
    references: list[dict],
) -> None:
    """Envelope → JSON → Envelope preserves all fields."""
    envelope = Envelope(
        ok=True,
        command="pxcli query",
        result={"answer": answer, "references": references},
        meta=meta,
        next_actions=next_actions,
    )

    serialized = envelope.model_dump_json()
    deserialized = Envelope.model_validate_json(serialized)

    assert deserialized.ok is True
    assert deserialized.command == envelope.command
    assert deserialized.result["answer"] == answer
    assert deserialized.result["references"] == references
    assert deserialized.meta == meta
    assert deserialized.next_actions == next_actions


@given(
    error_code=st.sampled_from(list(ErrorCode)),
    message=st.text(min_size=1, max_size=200),
)
@settings()
def test_error_envelope_roundtrip(error_code: ErrorCode, message: str) -> None:
    """ErrorEnvelope → JSON → ErrorEnvelope preserves all fields."""
    envelope = ErrorEnvelope(
        ok=False,
        command="pxcli query",
        error=ErrorDetail(code=error_code, message=message),
        fix="Run pxcli auth login",
        next_actions=[NextAction(command="pxcli auth login", description="Authenticate")],
    )

    serialized = envelope.model_dump_json()
    deserialized = ErrorEnvelope.model_validate_json(serialized)

    assert deserialized.ok is False
    assert deserialized.error.code == error_code
    assert deserialized.error.message == message
    assert deserialized.fix == envelope.fix


# ---------------------------------------------------------------------------
# SSE message parsing
# ---------------------------------------------------------------------------


@given(
    uuid=st.text(min_size=1, max_size=50, alphabet=st.characters(codec="ascii")),
    status=st.text(max_size=20, alphabet=st.characters(codec="ascii")),
    display_model=st.text(max_size=30, alphabet=st.characters(codec="ascii")),
)
@settings()
def test_sse_message_roundtrip(uuid: str, status: str, display_model: str) -> None:
    """SSEMessage → JSON → SSEMessage preserves core fields."""
    message = SSEMessage(uuid=uuid, status=status, display_model=display_model)

    serialized = message.model_dump_json()
    deserialized = SSEMessage.model_validate_json(serialized)

    assert deserialized.uuid == uuid
    assert deserialized.status == status
    assert deserialized.display_model == display_model


@given(
    uuid=st.text(min_size=1, max_size=50, alphabet=st.characters(codec="ascii")),
    status=st.text(max_size=20),
)
@settings()
def test_sse_message_defaults(uuid: str, status: str) -> None:
    """SSEMessage with minimal fields still serializes and deserializes."""
    message = SSEMessage(uuid=uuid, status=status)
    serialized = message.model_dump_json()
    deserialized = SSEMessage.model_validate_json(serialized)
    assert deserialized.uuid == uuid
    assert deserialized.status == status
    assert deserialized.blocks == []


# ---------------------------------------------------------------------------
# WebResult parsing resilience
# ---------------------------------------------------------------------------


@given(
    name=st.text(max_size=100),
    url=st.text(max_size=200),
    snippet=st.none() | st.text(max_size=200),
)
@settings()
def test_web_result_roundtrip(name: str, url: str, snippet: str | None) -> None:
    """WebResult → JSON → WebResult preserves all fields."""
    result = WebResult(name=name, url=url, snippet=snippet)

    serialized = result.model_dump_json()
    deserialized = WebResult.model_validate_json(serialized)

    assert deserialized.name == name
    assert deserialized.url == url
    assert deserialized.snippet == snippet


# ---------------------------------------------------------------------------
# Date parser invariants
# ---------------------------------------------------------------------------


@given(
    year=st.integers(min_value=2020, max_value=2030),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),
    hour=st.integers(min_value=0, max_value=23),
    minute=st.integers(min_value=0, max_value=59),
)
@settings()
def test_date_parser_roundtrip_iso(year: int, month: int, day: int, hour: int, minute: int) -> None:
    """Parsing an ISO-format date string produces the correct datetime."""
    date_str = f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:00Z"
    result = parse_absolute_date_string(date_str)

    assert result.year == year
    assert result.month == month
    assert result.day == day
    assert result.hour == hour
    assert result.minute == minute
    assert result.tzinfo is not None


@given(
    dt=st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2030, 12, 31),
    ).map(lambda d: d.replace(tzinfo=UTC))
)
@settings()
def test_date_parser_handles_formatted_dates(dt: datetime) -> None:
    """parse_absolute_date_string handles various date formats without crashing."""
    date_str = dt.strftime("%A, %B %d, %Y at %I:%M:%S %p Greenwich Mean Time")
    result = parse_absolute_date_string(date_str)

    # The result should be within a few seconds of the original (rounding)
    delta = abs((result - dt).total_seconds())
    assert delta < 5, f"Expected within 5s of {dt}, got {result}"


# ---------------------------------------------------------------------------
# Exit code mapping
# ---------------------------------------------------------------------------


@given(
    message=st.text(min_size=1, max_size=200),
    error_input=st.dictionaries(
        keys=st.text(min_size=1, max_size=20),
        values=st.text(max_size=50),
        max_size=5,
    ),
)
@settings()
def test_error_detail_accepts_arbitrary_input(message: str, error_input: dict[str, str]) -> None:
    """ErrorDetail accepts arbitrary input data without crashing."""
    detail = ErrorDetail(
        code=ErrorCode.internal_error,
        message=message,
        input=error_input,
    )

    serialized = detail.model_dump_json()
    deserialized = ErrorDetail.model_validate_json(serialized)

    assert deserialized.code == ErrorCode.internal_error
    assert deserialized.message == message
    assert deserialized.input == error_input


# ---------------------------------------------------------------------------
# Contract validation — require_mapping / require_list
# ---------------------------------------------------------------------------


@given(
    value=st.one_of(
        st.integers(),
        st.floats(),
        st.text(),
        st.lists(st.integers()),
        st.booleans(),
        st.none(),
    )
)
@settings()
def test_require_mapping_raises_on_non_dict(value: object) -> None:
    """require_mapping raises UpstreamSchemaError for any non-dict input."""
    if isinstance(value, dict):
        result = require_mapping(value, "test context")
        assert result is value
    else:
        with pytest.raises(UpstreamSchemaError):
            require_mapping(value, "test context")


@given(
    value=st.one_of(
        st.integers(),
        st.floats(),
        st.text(),
        st.dictionaries(keys=st.text(), values=st.integers()),
        st.booleans(),
        st.none(),
    )
)
@settings()
def test_require_list_raises_on_non_list(value: object) -> None:
    """require_list raises UpstreamSchemaError for any non-list input."""
    if isinstance(value, list):
        result = require_list(value, "test context")
        assert result is value
    else:
        with pytest.raises(UpstreamSchemaError):
            require_list(value, "test context")


@given(
    value=st.one_of(
        st.integers(),
        st.floats(),
        st.text(max_size=500),
        st.lists(st.text(), max_size=20),
        st.dictionaries(keys=st.text(max_size=20), values=st.text(max_size=50), max_size=10),
        st.booleans(),
        st.none(),
    )
)
@settings()
def test_describe_payload_shape_never_crashes(value: object) -> None:
    """describe_payload_shape always returns a string, never crashes."""
    result = describe_payload_shape(value)
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# Retry logic — backoff invariants
# ---------------------------------------------------------------------------


@given(
    attempt=st.integers(min_value=0, max_value=100),
    base_delay=st.floats(min_value=0.01, max_value=10.0),
    max_delay=st.floats(min_value=0.1, max_value=120.0),
)
@settings()
def test_backoff_delay_never_exceeds_max(attempt: int, base_delay: float, max_delay: float) -> None:
    """get_backoff_delay never returns a value greater than max_delay."""
    delay = get_backoff_delay(attempt, base_delay=base_delay, max_delay=max_delay)
    assert delay <= max_delay


@given(
    attempt=st.integers(min_value=1, max_value=100),
    base_delay=st.floats(min_value=0.01, max_value=10.0),
    max_delay=st.floats(min_value=0.1, max_value=120.0),
)
@settings()
def test_backoff_delay_increases_with_attempts(
    attempt: int, base_delay: float, max_delay: float
) -> None:
    """Backoff delay is non-decreasing with attempt number (until capped)."""
    earlier = get_backoff_delay(attempt - 1, base_delay=base_delay, max_delay=max_delay)
    later = get_backoff_delay(attempt, base_delay=base_delay, max_delay=max_delay)
    # Not strictly monotonic once capped at max, but never decreases
    assert later >= earlier or later == max_delay


@given(
    status_code=st.integers(min_value=100, max_value=599),
)
@settings()
def test_is_retryable_error_only_for_5xx_and_429(status_code: int) -> None:
    """is_retryable_error returns True only for server errors (>=500) and 429."""
    from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError, SimpleResponse

    response = SimpleResponse(
        status_code=status_code,
        text="test",
    )
    exc = PerplexityHTTPStatusError("test", response=response)
    result = is_retryable_error(exc)

    expected = status_code >= 500 or status_code == 429
    assert result is expected, f"status {status_code}: expected {expected}, got {result}"


# ---------------------------------------------------------------------------
# Exception hierarchy — proper wrapping
# ---------------------------------------------------------------------------


@given(
    message=st.text(min_size=1, max_size=200),
    cause_message=st.text(min_size=1, max_size=100),
)
@settings()
def test_exceptions_preserve_cause(message: str, cause_message: str) -> None:
    """Exceptions raised with 'from' preserve their __cause__ chain."""
    try:
        raise ValueError(cause_message)
    except ValueError as cause:
        exc = ConfigurationError(message)
        exc.__cause__ = cause

    assert exc.__cause__ is not None
    assert str(exc.__cause__) == cause_message
    assert str(exc) == message


@given(message=st.text(min_size=1, max_size=200))
@settings()
def test_all_exception_types_are_importable_and_stringable(message: str) -> None:
    """Every exception type can be instantiated and converted to string."""
    exceptions = [
        AuthenticationError(message),
        ConfigurationError(message),
        PerplexityRequestError(message),
        RateLimitError(message),
    ]
    for exc in exceptions:
        assert isinstance(str(exc), str)
        assert message in str(exc)
