"""Property-based tests using Hypothesis.

Validates invariants that should hold for any valid input, not just
the specific examples covered by unit tests.  Hypothesis generates
random inputs, runs the invariant check, and shrinks failures to
minimal counterexamples.
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from hypothesis import HealthCheck, assume, example, given, settings
from hypothesis import strategies as st

from perplexity_cli.api.contracts import (
    describe_payload_shape,
    require_list,
    require_mapping,
)
from perplexity_cli.api.models import Block, QueryParams, SSEMessage, WebResult
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
)
from perplexity_cli.error_handler import _classify_exception
from perplexity_cli.formatting.base import Formatter, _is_structural_line
from perplexity_cli.threads.cache_manager import ThreadCacheManager
from perplexity_cli.threads.date_parser import (
    is_in_date_range,
    parse_absolute_date_string,
    to_iso8601,
)
from perplexity_cli.threads.exporter import ThreadRecord
from perplexity_cli.utils.encryption import decrypt_token, encrypt_token
from perplexity_cli.utils.exceptions import (
    AttachmentError,
    AuthenticationError,
    ConfigurationError,
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    RateLimitError,
    SimpleResponse,
    UpstreamSchemaError,
)
from perplexity_cli.utils.rate_limiter import RateLimiter
from perplexity_cli.utils.retry import get_backoff_delay, get_retry_after_delay, is_retryable_error
from tests.strategies import (
    citation_text,
    markdown_text,
    ordered_utc_datetime_pair,
    thread_record_lists,
    utc_datetimes,
)

# ---------------------------------------------------------------------------
# Encryption round-trip
# ---------------------------------------------------------------------------


@given(token=st.text(min_size=1, max_size=500))
@example(token="")
@example(token="café—日本語🎉")
@settings(deadline=500)
def test_encrypt_decrypt_roundtrip(token: str) -> None:
    """encrypt_token then decrypt_token returns the original token."""
    encrypted = encrypt_token(token)
    decrypted = decrypt_token(encrypted)
    assert decrypted == token


@given(token=st.text(min_size=1, max_size=500))
@settings(deadline=500)
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
@example(uuid="", status="", display_model="")
@example(uuid="тест-123", status="完了", display_model="模型-v2")
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
@example(uuid="", status="")
@example(uuid="   ", status="   ")
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
# SSEMessage — web results derivation & describe_block_usages
# ---------------------------------------------------------------------------


@given(
    name=st.text(max_size=50),
    url=st.text(max_size=100),
    snippet=st.none() | st.text(max_size=100),
)
@example(name="", url="", snippet="")
@settings()
def test_sse_message_derives_web_results(name: str, url: str, snippet: str | None) -> None:
    """SSEMessage derives web_results from web_results blocks when not provided."""
    web_result_dict = {"name": name, "url": url, "snippet": snippet}
    block = Block(
        intended_usage="web_results",
        content={"web_result_block": {"web_results": [web_result_dict]}},
    )
    message = SSEMessage(
        uuid="test",
        status="completed",
        blocks=[block],
    )
    assert message.web_results is not None
    assert len(message.web_results) == 1
    assert message.web_results[0].name == name
    assert message.web_results[0].url == url


@given(
    explicit_results=st.lists(
        st.builds(WebResult, name=st.text(max_size=30), url=st.text(max_size=100)),
        max_size=3,
    ),
)
@example(explicit_results=[])
@settings()
def test_sse_message_preserves_explicit_web_results(
    explicit_results: list[WebResult],
) -> None:
    """SSEMessage preserves explicitly provided web_results without derivation."""
    block = Block(
        intended_usage="web_results",
        content={"web_result_block": {"web_results": []}},
    )
    message = SSEMessage(
        uuid="test",
        status="completed",
        blocks=[block],
        web_results=explicit_results,
    )
    assert message.web_results == explicit_results


@given(
    usages=st.lists(
        st.text(
            min_size=1,
            max_size=30,
            alphabet=st.characters(whitelist_categories=["L", "N"], whitelist_characters="_"),
        ),
        min_size=0,
        max_size=10,
    ),
)
@example(usages=[])
@settings()
def test_describe_block_usages_format(usages: list[str]) -> None:
    """describe_block_usages returns comma-separated usages or 'none'."""
    blocks = [Block(intended_usage=u, content={}) for u in usages]
    message = SSEMessage(uuid="test", status="completed", blocks=blocks)
    result = message.describe_block_usages()
    if not usages:
        assert result == "none"
    else:
        assert result == ",".join(usages)


def test_describe_block_usages_empty() -> None:
    """describe_block_usages returns 'none' when blocks list is empty."""
    message = SSEMessage(uuid="test", status="completed")
    assert message.describe_block_usages() == "none"


def test_describe_block_usages_missing_usage() -> None:
    """describe_block_usages returns '<missing>' for blocks with empty intended_usage."""
    block = Block(intended_usage="", content={})
    message = SSEMessage(uuid="test", status="completed", blocks=[block])
    assert message.describe_block_usages() == "<missing>"


# ---------------------------------------------------------------------------
# WebResult parsing resilience
# ---------------------------------------------------------------------------


@given(
    name=st.text(max_size=100),
    url=st.text(max_size=200),
    snippet=st.none() | st.text(max_size=200),
)
@example(name="", url="", snippet=None)
@example(name="   ", url="   ", snippet="   ")
@example(name="résumé", url="https://münchen.de/paß", snippet="garçon")
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
# QueryParams validation
# ---------------------------------------------------------------------------


@given(mode=st.text(min_size=1, max_size=20))
@settings()
def test_query_params_rejects_invalid_search_mode(mode: str) -> None:
    """search_implementation_mode rejects values other than standard or multi_step."""
    if mode in ("standard", "multi_step"):
        params = QueryParams(search_implementation_mode=mode)
        assert params.search_implementation_mode == mode
    else:
        with pytest.raises(ValueError):
            QueryParams(search_implementation_mode=mode)


@given(
    mode=st.sampled_from(["standard", "multi_step"]),
    language=st.text(min_size=1, max_size=10, alphabet=st.characters(codec="ascii")),
    timezone=st.text(min_size=1, max_size=30, alphabet=st.characters(codec="ascii")),
    model_preference=st.text(min_size=1, max_size=20, alphabet=st.characters(codec="ascii")),
)
@settings()
def test_query_params_accepts_valid_values(
    mode: str, language: str, timezone: str, model_preference: str
) -> None:
    """QueryParams accepts valid search_implementation_mode values."""
    params = QueryParams(
        search_implementation_mode=mode,
        language=language,
        timezone=timezone,
        model_preference=model_preference,
    )
    serialized = params.model_dump_json()
    deserialized = QueryParams.model_validate_json(serialized)
    assert deserialized.search_implementation_mode == mode
    assert deserialized.language == language
    assert deserialized.timezone == timezone
    assert deserialized.model_preference == model_preference


# ---------------------------------------------------------------------------
# Block.extract_text crash resilience
# ---------------------------------------------------------------------------


def _arbitrary_content_dict() -> st.SearchStrategy[dict[str, object]]:
    """Generate arbitrary dicts exercising all Block.extract_text code paths."""
    scalar = st.one_of(
        st.text(max_size=60),
        st.integers(min_value=-100, max_value=100),
        st.floats(allow_nan=False, allow_infinity=False),
        st.booleans(),
        st.none(),
    )
    nested = st.dictionaries(
        keys=st.text(min_size=1, max_size=15, alphabet=st.characters(codec="ascii")),
        values=st.one_of(
            scalar,
            st.lists(scalar, max_size=4),
        ),
        max_size=6,
    )
    return st.dictionaries(
        keys=st.text(min_size=1, max_size=20, alphabet=st.characters(codec="ascii")),
        values=st.one_of(scalar, nested, st.lists(nested, max_size=3)),
        max_size=8,
    )


@given(content=_arbitrary_content_dict())
@example(content={})
@example(content={"text": None})
@example(content={"message": {"content": [1, 2, 3]}})
@example(content={"値": "日本語"})
@settings()
def test_block_extract_text_never_crashes(content: dict[str, object]) -> None:
    """Block.extract_text never raises regardless of content shape."""
    block = Block(intended_usage="ask_text", content=content)
    result = block.extract_text()
    assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# Date parser invariants
# ---------------------------------------------------------------------------


@given(dt=utc_datetimes())
@settings()
def test_to_iso8601_always_z_suffix(dt: datetime) -> None:
    assert to_iso8601(dt).endswith("Z")


@given(dt=utc_datetimes())
@settings()
def test_to_iso8601_parseable_utc_roundtrip(dt: datetime) -> None:
    encoded = to_iso8601(dt)
    parsed = datetime.fromisoformat(encoded.replace("Z", "+00:00"))

    assert parsed.tzinfo is not None
    assert parsed.astimezone(UTC) == dt.astimezone(UTC)


@given(pair=ordered_utc_datetime_pair())
@settings()
def test_to_iso8601_order_preserving(pair: tuple[datetime, datetime]) -> None:
    earlier, later = pair

    assert to_iso8601(earlier) <= to_iso8601(later)


@given(dt=utc_datetimes())
@settings()
def test_is_in_date_range_unbounded_always_true(dt: datetime) -> None:
    assert is_in_date_range(dt, None, None) is True


@given(
    dt=st.datetimes(
        min_value=datetime(2024, 2, 29, 0, 0),
        max_value=datetime(2024, 2, 29, 23, 59, 59, 999999),
        timezones=st.just(UTC),
    )
)
@example(dt=datetime(2024, 2, 29, 12, 0, tzinfo=UTC))
@settings()
def test_is_in_date_range_same_day_range_inclusive(dt: datetime) -> None:
    assert is_in_date_range(dt, "2024-02-29", "2024-02-29") is True


@given(
    command=st.text(min_size=1, max_size=30, alphabet=st.characters(codec="ascii")),
    result=st.dictionaries(
        keys=st.text(min_size=1, max_size=10),
        values=st.text(max_size=20),
        max_size=5,
    ),
)
@settings()
def test_success_envelope_builder_always_ok(command: str, result: dict[str, str]) -> None:
    envelope = success_envelope(command, result)

    assert envelope.ok is True
    assert envelope.command == command
    assert envelope.result == result


@given(
    command=st.text(min_size=1, max_size=30, alphabet=st.characters(codec="ascii")),
    message=st.text(min_size=1, max_size=200),
)
@settings()
def test_error_envelope_builder_always_not_ok(command: str, message: str) -> None:
    envelope = error_envelope(command, ErrorCode.internal_error, message)

    assert envelope.ok is False
    assert envelope.command == command
    assert envelope.error.code == ErrorCode.internal_error
    assert envelope.error.message == message


@given(
    command=st.text(min_size=1, max_size=30, alphabet=st.characters(codec="ascii")),
    result=st.dictionaries(
        keys=st.text(min_size=1, max_size=10),
        values=st.text(max_size=20),
        max_size=5,
    ),
)
@settings()
def test_envelope_to_dict_schema_toggle_excludes_schema(
    command: str, result: dict[str, str]
) -> None:
    envelope = success_envelope(command, result)

    data = envelope_to_dict(envelope, include_schema=False)

    assert "$schema" not in data
    assert data["ok"] is True
    assert data["command"] == command


@given(
    command=st.text(min_size=1, max_size=30, alphabet=st.characters(codec="ascii")),
    message=st.text(min_size=1, max_size=200),
)
@settings()
def test_envelope_to_dict_schema_toggle_includes_schema(command: str, message: str) -> None:
    envelope = error_envelope(command, ErrorCode.validation_error, message)

    data = envelope_to_dict(envelope, include_schema=True)

    assert "$schema" in data
    assert data["$schema"] == type(envelope).model_json_schema()
    assert data["ok"] is False


@given(
    year=st.integers(min_value=2020, max_value=2030),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),
    hour=st.integers(min_value=0, max_value=23),
    minute=st.integers(min_value=0, max_value=59),
)
@example(year=2024, month=2, day=29, hour=12, minute=0)
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
# Formatter invariants
# ---------------------------------------------------------------------------


@given(text=citation_text())
@example(text="The answer is [1].")
@example(text="   \t \n ")
@settings()
def test_strip_citations_idempotent(text: str) -> None:
    once = Formatter.strip_citations(text)
    twice = Formatter.strip_citations(once)

    assert twice == once


@given(text=citation_text())
@settings()
def test_strip_citations_never_longer(text: str) -> None:
    result = Formatter.strip_citations(text)

    assert len(result) <= len(text)


@given(text=citation_text())
@example(text="Alpha [12] beta [3].")
@settings()
def test_strip_citations_removes_numeric_markers(text: str) -> None:
    result = Formatter.strip_citations(text)

    assert re.search(r"\[\d+\]", result) is None


@given(text=markdown_text())
@example(text="   \n\n   \n\n   ")
@settings()
def test_unwrap_paragraph_lines_idempotent(text: str) -> None:
    once = Formatter.unwrap_paragraph_lines(text)
    twice = Formatter.unwrap_paragraph_lines(once)

    assert twice == once


@given(text=markdown_text())
@settings()
def test_unwrap_paragraph_lines_preserves_non_whitespace_chars(text: str) -> None:
    result = Formatter.unwrap_paragraph_lines(text)

    assert "".join(ch for ch in result if not ch.isspace()) == "".join(
        ch for ch in text if not ch.isspace()
    )


@given(
    line=st.sampled_from(
        [
            "# Heading",
            "## Heading",
            "### Heading",
            "- item",
            "* item",
            "+ item",
            "1. item",
            "> quote",
            "| cell | value |",
            "---",
            "***",
        ]
    )
)
@settings()
def test_structural_line_classifier_accepts_known_markdown(line: str) -> None:
    assert _is_structural_line(line)


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
@example(value="not a dict")
@example(value=[])
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
@example(value="not a list")
@example(value={"k": "v"})
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
@example(value="")
@example(value={"key": {"nested": [1, None, 3.14]}})
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
@example(attempt=0, base_delay=1.0, max_delay=10.0)
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


# ---------------------------------------------------------------------------
# Retry logic — backoff lower bound
# ---------------------------------------------------------------------------


@given(
    attempt=st.integers(min_value=0, max_value=100),
    base_delay=st.floats(min_value=0.0, max_value=10.0),
    max_delay=st.floats(min_value=0.1, max_value=120.0),
    jitter_factor=st.floats(min_value=0.0, max_value=0.5),
)
@example(attempt=0, base_delay=0.0, max_delay=0.1, jitter_factor=0.0)
@settings()
def test_backoff_delay_non_negative(
    attempt: int, base_delay: float, max_delay: float, jitter_factor: float
) -> None:
    """get_backoff_delay never returns a negative value."""
    delay = get_backoff_delay(
        attempt, base_delay=base_delay, max_delay=max_delay, jitter_factor=jitter_factor
    )
    assert delay >= 0.0


# ---------------------------------------------------------------------------
# Retry logic — deterministic monotonicity without jitter
# ---------------------------------------------------------------------------


@given(
    attempt=st.integers(min_value=1, max_value=30),
    base_delay=st.floats(min_value=0.01, max_value=10.0),
    max_delay=st.floats(min_value=0.1, max_value=120.0),
)
@settings()
def test_backoff_delay_monotonic_without_jitter(
    attempt: int, base_delay: float, max_delay: float
) -> None:
    """When jitter_factor=0, backoff delay is non-decreasing with attempt."""
    prev = get_backoff_delay(
        attempt - 1, base_delay=base_delay, max_delay=max_delay, jitter_factor=0.0
    )
    curr = get_backoff_delay(attempt, base_delay=base_delay, max_delay=max_delay, jitter_factor=0.0)
    assert curr >= prev


# ---------------------------------------------------------------------------
# Retry logic — jitter window bounds
# ---------------------------------------------------------------------------


@given(
    attempt=st.integers(min_value=0, max_value=30),
    base_delay=st.floats(min_value=0.01, max_value=10.0),
    max_delay=st.floats(min_value=0.1, max_value=120.0),
    jitter_factor=st.floats(min_value=0.001, max_value=0.5),
)
@example(attempt=0, base_delay=0.01, max_delay=0.1, jitter_factor=0.001)
@settings()
def test_backoff_delay_within_jitter_bounds(
    attempt: int, base_delay: float, max_delay: float, jitter_factor: float
) -> None:
    """Result stays within [0.0, max_delay] even with jitter applied."""
    delay = get_backoff_delay(
        attempt, base_delay=base_delay, max_delay=max_delay, jitter_factor=jitter_factor
    )
    assert 0.0 <= delay <= max_delay


# ---------------------------------------------------------------------------
# Retry-After parsing — non-HTTP errors
# ---------------------------------------------------------------------------


@given(message=st.text(min_size=1, max_size=100))
@settings()
def test_get_retry_after_delay_none_for_non_http_error(message: str) -> None:
    """get_retry_after_delay returns None for exceptions that are not HTTP errors."""
    exc = PerplexityRequestError(message)
    assert get_retry_after_delay(exc) is None


# ---------------------------------------------------------------------------
# Retry-After parsing — case-insensitive header
# ---------------------------------------------------------------------------


@given(
    delay_seconds=st.floats(min_value=0.0, max_value=120.0),
)
@settings()
def test_get_retry_after_delay_handles_both_header_casings(
    delay_seconds: float,
) -> None:
    """get_retry_after_delay handles both Retry-After and retry-after casings."""
    for header_name in ("Retry-After", "retry-after"):
        response = SimpleResponse(status_code=429, headers={header_name: str(delay_seconds)})
        exc = PerplexityHTTPStatusError("rate limited", response=response)
        result = get_retry_after_delay(exc)
        assert result == delay_seconds, f"failed for header {header_name!r}"


# ---------------------------------------------------------------------------
# Retry-After parsing — negative values clamped to 0
# ---------------------------------------------------------------------------


@given(negative_delay=st.floats(min_value=-100.0, max_value=-0.001))
@settings()
def test_get_retry_after_delay_clamps_negative(negative_delay: float) -> None:
    """Negative Retry-After values are clamped to 0.0."""
    response = SimpleResponse(status_code=429, headers={"Retry-After": str(negative_delay)})
    exc = PerplexityHTTPStatusError("rate limited", response=response)
    result = get_retry_after_delay(exc)
    assert result == 0.0, f"expected 0.0, got {result} for delay={negative_delay}"


# ---------------------------------------------------------------------------
# Error classification — exception type → ErrorCode mapping
# ---------------------------------------------------------------------------


@given(message=st.text(min_size=1, max_size=100))
@settings()
def test_classify_exception_maps_known_types(message: str) -> None:
    """_classify_exception maps known exception classes to expected ErrorCode."""
    mappings: list[tuple[type[BaseException], ErrorCode]] = [
        (AuthenticationError, ErrorCode.authentication_required),
        (RateLimitError, ErrorCode.rate_limited),
        (PerplexityRequestError, ErrorCode.network_error),
        (ConfigurationError, ErrorCode.configuration_error),
        (UpstreamSchemaError, ErrorCode.upstream_schema_error),
        (AttachmentError, ErrorCode.attachment_error),
        (ValueError, ErrorCode.validation_error),
    ]
    for exc_type, expected_code in mappings:
        exc = exc_type(message)
        code, _ = _classify_exception(exc)
        assert code == expected_code, f"{exc_type.__name__}: expected {expected_code}, got {code}"


@given(
    status_code=st.sampled_from([401, 403, 429]),
    message=st.text(min_size=1, max_size=100),
)
@settings()
def test_classify_exception_maps_http_status_errors(status_code: int, message: str) -> None:
    """_classify_exception maps HTTP status errors from the status code table."""
    expected_by_status: dict[int, ErrorCode] = {
        401: ErrorCode.authentication_required,
        403: ErrorCode.permission_denied,
        429: ErrorCode.rate_limited,
    }
    response = SimpleResponse(status_code=status_code)
    exc = PerplexityHTTPStatusError(message, response=response)
    code, _ = _classify_exception(exc)
    assert code == expected_by_status[status_code]


@given(
    status_code=st.sampled_from([400, 404, 500, 502, 503]),
    message=st.text(min_size=1, max_size=100),
)
@settings()
def test_classify_exception_unmapped_http_status_defaults_to_network_error(
    status_code: int, message: str
) -> None:
    """_classify_exception maps unmapped HTTP status codes to network_error."""
    response = SimpleResponse(status_code=status_code)
    exc = PerplexityHTTPStatusError(message, response=response)
    code, _ = _classify_exception(exc)
    assert code == ErrorCode.network_error


# ---------------------------------------------------------------------------
# Thread cache merge
# ---------------------------------------------------------------------------


@given(lists=thread_record_lists())
@example(
    lists=(
        [
            ThreadRecord(
                title="Cache only", url="https://p.ai/c1", created_at="2024-02-01T00:00:00Z"
            ),
            ThreadRecord(
                title="Shared", url="https://p.ai/shared", created_at="2024-02-02T00:00:00Z"
            ),
        ],
        [
            ThreadRecord(
                title="New only", url="https://p.ai/n1", created_at="2024-01-01T00:00:00Z"
            ),
            ThreadRecord(
                title="Shared new", url="https://p.ai/shared", created_at="2024-01-01T00:00:00Z"
            ),
        ],
    )
)
@settings()
def test_merge_threads_no_duplicate_urls(
    lists: tuple[list[ThreadRecord], list[ThreadRecord]],
) -> None:
    """merge_threads never produces duplicate URLs."""
    cached, new = lists
    assume(len({t.url for t in cached}) == len(cached))
    assume(len({t.url for t in new}) == len(new))
    manager = ThreadCacheManager()
    merged = manager.merge_threads(cached, new)
    urls = [t.url for t in merged]
    assert len(urls) == len(set(urls))


@given(lists=thread_record_lists())
@settings()
def test_merge_threads_sorted_newest_first(
    lists: tuple[list[ThreadRecord], list[ThreadRecord]],
) -> None:
    """merge_threads returns threads sorted by created_at newest-first."""
    cached, new = lists
    manager = ThreadCacheManager()
    merged = manager.merge_threads(cached, new)
    timestamps = [t.created_at for t in merged]
    assert timestamps == sorted(timestamps, reverse=True)


@given(lists=thread_record_lists())
@settings()
def test_merge_threads_cached_record_preferred_on_duplicate(
    lists: tuple[list[ThreadRecord], list[ThreadRecord]],
) -> None:
    """When a URL appears in both lists, the cached record is kept."""
    cached, new = lists
    assume(len({t.url for t in cached}) == len(cached))
    manager = ThreadCacheManager()
    merged = manager.merge_threads(cached, new)

    cached_by_url = {t.url: t for t in cached}
    for t in merged:
        if t.url in cached_by_url:
            assert t == cached_by_url[t.url]


@given(lists=thread_record_lists())
@settings()
def test_merge_threads_idempotent(
    lists: tuple[list[ThreadRecord], list[ThreadRecord]],
) -> None:
    """Merging twice produces the same result as merging once."""
    cached, new = lists
    manager = ThreadCacheManager()
    once = manager.merge_threads(cached, new)
    twice = manager.merge_threads(once, [])
    assert twice == once


@given(lists=thread_record_lists())
@example(lists=([], []))
@settings()
def test_merge_threads_empty_lists_merge_to_empty(
    lists: tuple[list[ThreadRecord], list[ThreadRecord]],
) -> None:
    """Empty cached + empty new produces empty result."""
    cached, new = lists
    manager = ThreadCacheManager()
    merged = manager.merge_threads(cached, new)
    if not cached and not new:
        assert merged == []


# ---------------------------------------------------------------------------
# Thread cache fetch range
# ---------------------------------------------------------------------------


def _date_strategy() -> st.SearchStrategy[date]:
    return st.dates(
        min_value=date(2020, 1, 1),
        max_value=date(2030, 12, 31),
    )


_INSIDE_COVERAGE_DATES = (
    st.lists(_date_strategy(), min_size=4, max_size=4, unique=True)
    .map(sorted)
    .filter(lambda vals: (vals[1] - vals[0]) >= timedelta(days=2))
    .map(
        lambda vals: (
            vals[0],
            vals[1],
            vals[0] + timedelta(days=1),
            vals[1] - timedelta(days=1),
        )
    )
    .filter(lambda vals: vals[2] <= vals[3])
)


@given(dates=_INSIDE_COVERAGE_DATES)
@settings()
def test_calculate_fetch_range_inside_coverage_returns_none(
    dates: tuple[date, date, date, date],
) -> None:
    """_calculate_fetch_range returns (False, None, None) when request is
    fully inside cache coverage."""
    cache_oldest, cache_newest, request_from, request_to = dates
    needs_fetch, fetch_from, fetch_to = ThreadCacheManager._calculate_fetch_range(
        request_from,
        request_to,
        cache_oldest,
        cache_newest,
    )
    assert needs_fetch is False
    assert fetch_from is None
    assert fetch_to is None


_OUTSIDE_COVERAGE_DATES = (
    st.lists(_date_strategy(), min_size=4, max_size=4, unique=True)
    .map(sorted)
    .filter(lambda vals: (vals[2] - vals[1]) >= timedelta(days=3))
    .map(
        lambda vals: (
            vals[0],
            vals[1],
            vals[2],
            vals[3],
        )
    )
    .filter(lambda vals: vals[0] < vals[2] and vals[1] <= vals[3])
)


@given(dates=_OUTSIDE_COVERAGE_DATES)
@settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_calculate_fetch_range_fetch_bounds_within_request(
    dates: tuple[date, date, date, date],
) -> None:
    """When request is outside cache coverage, fetch bounds lie within the
    request bounds."""
    request_from, request_to, cache_oldest, cache_newest = dates
    needs_fetch, fetch_from_str, fetch_to_str = ThreadCacheManager._calculate_fetch_range(
        request_from,
        request_to,
        cache_oldest,
        cache_newest,
    )
    assert needs_fetch is True
    assert fetch_from_str is not None
    assert fetch_to_str is not None

    fetch_from = date.fromisoformat(fetch_from_str)
    fetch_to = date.fromisoformat(fetch_to_str)
    assert request_from <= fetch_from <= fetch_to <= request_to


# ---------------------------------------------------------------------------
# RateLimiter property tests
# ---------------------------------------------------------------------------


class _FakeSleep:
    def __init__(self) -> None:
        self.durations: list[float] = []

    async def __call__(self, duration: float) -> None:
        self.durations.append(duration)


class _MutableClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, delta: float) -> None:
        self.now += delta


@given(
    requests_per_period=st.integers(min_value=-100, max_value=100),
    period_seconds=st.floats(
        min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False
    ),
)
@settings()
def test_rate_limiter_invalid_params_raises_value_error(
    requests_per_period: int, period_seconds: float
) -> None:
    assume(requests_per_period <= 0 or period_seconds <= 0)
    with pytest.raises(ValueError):
        RateLimiter(requests_per_period=requests_per_period, period_seconds=period_seconds)


@given(
    requests_per_period=st.integers(min_value=1, max_value=50),
    period_seconds=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
    time_deltas=st.lists(
        st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False),
        min_size=0,
        max_size=20,
    ),
)
@settings()
def test_rate_limiter_stats_consistency(
    requests_per_period: int,
    period_seconds: float,
    time_deltas: list[float],
) -> None:
    clock = _MutableClock()
    fake_sleep = _FakeSleep()
    with patch.object(time, "monotonic", clock), patch.object(asyncio, "sleep", fake_sleep):
        limiter = RateLimiter(
            requests_per_period=requests_per_period, period_seconds=period_seconds
        )

        wait_times: list[float] = []
        for delta in time_deltas:
            clock.advance(delta)
            wait_time = asyncio.run(limiter.acquire())
            wait_times.append(wait_time)

        assert limiter.total_requests == len(time_deltas)
        assert limiter.total_wait_time == pytest.approx(sum(wait_times))

        stats = limiter.get_stats()
        assert stats["total_requests"] == limiter.total_requests
        assert stats["total_wait_time"] == pytest.approx(limiter.total_wait_time)
        if limiter.total_requests > 0:
            assert stats["average_wait_per_request"] == pytest.approx(
                limiter.total_wait_time / limiter.total_requests
            )
        else:
            assert stats["average_wait_per_request"] == pytest.approx(0.0)


@given(
    requests_per_period=st.integers(min_value=1, max_value=50),
    period_seconds=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
    time_deltas=st.lists(
        st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False),
        min_size=0,
        max_size=20,
    ),
)
@settings()
def test_rate_limiter_token_bounds(
    requests_per_period: int,
    period_seconds: float,
    time_deltas: list[float],
) -> None:
    clock = _MutableClock()
    fake_sleep = _FakeSleep()
    with patch.object(time, "monotonic", clock), patch.object(asyncio, "sleep", fake_sleep):
        limiter = RateLimiter(
            requests_per_period=requests_per_period, period_seconds=period_seconds
        )

        assert 0.0 <= limiter._state.tokens <= float(requests_per_period)

        for delta in time_deltas:
            clock.advance(delta)
            asyncio.run(limiter.acquire())
            assert 0.0 <= limiter._state.tokens <= float(requests_per_period)


@given(
    requests_per_period=st.integers(min_value=1, max_value=50),
    period_seconds=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
    time_deltas=st.lists(
        st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=20,
    ),
)
@settings()
def test_rate_limiter_sleep_durations_match_wait_times(
    requests_per_period: int,
    period_seconds: float,
    time_deltas: list[float],
) -> None:
    clock = _MutableClock()
    fake_sleep = _FakeSleep()
    with patch.object(time, "monotonic", clock), patch.object(asyncio, "sleep", fake_sleep):
        limiter = RateLimiter(
            requests_per_period=requests_per_period, period_seconds=period_seconds
        )

        wait_times: list[float] = []
        for delta in time_deltas:
            clock.advance(delta)
            wait_time = asyncio.run(limiter.acquire())
            wait_times.append(wait_time)

        non_zero_waits = [w for w in wait_times if w > 0.0]
        assert len(fake_sleep.durations) == len(non_zero_waits)
        for expected, actual in zip(non_zero_waits, fake_sleep.durations, strict=True):
            assert actual == pytest.approx(expected)
