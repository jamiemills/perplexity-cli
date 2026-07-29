"""Final round mutation-killing tests for api/client.py.

Targets ~55 surviving mutants with exact-value assertions on error messages,
boundary status codes, retry arithmetic, SSE parsing edge cases, transport
validation, header construction, and response parsing.
"""

from __future__ import annotations

import logging
from unittest.mock import Mock, patch

import pytest

from perplexity_cli.api.client import (
    DEEP_RESEARCH_MODE_KEYS,
    DEEP_RESEARCH_MODE_VALUES,
    DEEP_RESEARCH_TIMEOUT_MODE,
    HEADER_PAIR_SIZE,
    HTTP_STATUS_FORBIDDEN,
    HTTP_STATUS_TOO_MANY_REQUESTS,
    HTTP_STATUS_UNAUTHORISED,
    RetryHandler,
    SSEClient,
    SSEParser,
    _close_transport_session,
    _coerce_header_mapping,
    _coerce_header_pair,
    _create_transport_session,
    _is_deep_research_request,
    _is_deep_research_value,
    _is_json_object,
    _is_request_exception,
    _iter_object_values,
    _open_stream_context,
    _read_transport_value,
    _require_bool,
    _require_bytes_or_str,
    _require_int,
    _require_json_object_or_none,
    _require_str,
    _ResponseAdapter,
    _StreamContextAdapter,
)
from perplexity_cli.api.models import HttpRequestContext
from perplexity_cli.auth.models import AuthContext
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    SimpleRequest,
    SimpleResponse,
    UpstreamSchemaError,
)
from perplexity_cli.utils.retry import (
    get_backoff_delay,
    get_retry_after_delay,
    is_retryable_error,
)


def _http_error(status: int, headers: dict[str, str] | None = None) -> PerplexityHTTPStatusError:
    request = SimpleRequest(method="POST", url="https://www.perplexity.ai/api")
    response = SimpleResponse(
        status_code=status, headers=headers or {}, text="error body", request=request
    )
    return PerplexityHTTPStatusError(f"HTTP Error {status}", request=request, response=response)


class TestExactErrorMessage401:
    def test_401_exact_message(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=3)
        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            handler.handle_http_error(_http_error(401), attempt=0)
        assert str(exc_info.value) == "Authentication failed. Token may be invalid or expired."

    def test_401_preserves_request(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=3)
        original = _http_error(401)
        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            handler.handle_http_error(original, attempt=0)
        assert exc_info.value.request is original.request

    def test_401_preserves_response(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=3)
        original = _http_error(401)
        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            handler.handle_http_error(original, attempt=0)
        assert exc_info.value.response is original.response

    def test_401_cause_chain(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=3)
        original = _http_error(401)
        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            handler.handle_http_error(original, attempt=0)
        assert exc_info.value.__cause__ is original


class TestExactErrorMessage403:
    def test_403_exact_message(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=1)
        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            handler.handle_http_error(_http_error(403), attempt=0)
        assert str(exc_info.value) == "Access forbidden. Check API permissions or try again later."

    def test_403_cause_chain(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=1)
        original = _http_error(403)
        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            handler.handle_http_error(original, attempt=0)
        assert exc_info.value.__cause__ is original

    def test_403_preserves_response_status(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=1)
        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            handler.handle_http_error(_http_error(403), attempt=0)
        assert exc_info.value.response.status_code == 403


class TestExactErrorMessage429:
    def test_429_exact_message(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=1)
        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            handler.handle_http_error(_http_error(429), attempt=0)
        assert str(exc_info.value) == "Rate limit exceeded. Please wait and try again."

    def test_429_cause_chain(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=1)
        original = _http_error(429)
        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            handler.handle_http_error(original, attempt=0)
        assert exc_info.value.__cause__ is original


class TestHTTPStatusBoundaries:
    def test_428_not_retryable(self) -> None:
        assert is_retryable_error(_http_error(428)) is False

    def test_429_is_retryable(self) -> None:
        assert is_retryable_error(_http_error(429)) is True

    def test_430_not_retryable(self) -> None:
        assert is_retryable_error(_http_error(430)) is False

    def test_499_not_retryable(self) -> None:
        assert is_retryable_error(_http_error(499)) is False

    def test_500_is_retryable(self) -> None:
        assert is_retryable_error(_http_error(500)) is True

    def test_501_is_retryable(self) -> None:
        assert is_retryable_error(_http_error(501)) is True

    def test_503_is_retryable(self) -> None:
        assert is_retryable_error(_http_error(503)) is True

    def test_400_not_retryable(self) -> None:
        assert is_retryable_error(_http_error(400)) is False

    def test_401_not_retryable(self) -> None:
        assert is_retryable_error(_http_error(401)) is False

    def test_403_not_retryable_via_is_retryable(self) -> None:
        assert is_retryable_error(_http_error(403)) is False

    def test_429_exhausted_raises_not_reraise(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=2)
        original = _http_error(429)
        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            handler.handle_http_error(original, attempt=1)
        assert exc_info.value is not original
        assert str(exc_info.value) == "Rate limit exceeded. Please wait and try again."

    def test_500_exhausted_reraises_original(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=2)
        original = _http_error(500)
        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            handler.handle_http_error(original, attempt=1)
        assert exc_info.value is original

    def test_502_exhausted_reraises_original(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=1)
        original = _http_error(502)
        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            handler.handle_http_error(original, attempt=0)
        assert exc_info.value is original


class TestRetryArithmetic:
    def test_backoff_attempt_0_exact(self) -> None:
        assert get_backoff_delay(0, base_delay=1.0, max_delay=60.0, jitter_factor=0.0) == 1.0

    def test_backoff_attempt_1_exact(self) -> None:
        assert get_backoff_delay(1, base_delay=1.0, max_delay=60.0, jitter_factor=0.0) == 2.0

    def test_backoff_attempt_2_exact(self) -> None:
        assert get_backoff_delay(2, base_delay=1.0, max_delay=60.0, jitter_factor=0.0) == 4.0

    def test_backoff_attempt_3_exact(self) -> None:
        assert get_backoff_delay(3, base_delay=1.0, max_delay=60.0, jitter_factor=0.0) == 8.0

    def test_backoff_attempt_4_exact(self) -> None:
        assert get_backoff_delay(4, base_delay=1.0, max_delay=60.0, jitter_factor=0.0) == 16.0

    def test_backoff_attempt_5_exact(self) -> None:
        assert get_backoff_delay(5, base_delay=1.0, max_delay=60.0, jitter_factor=0.0) == 32.0

    def test_backoff_attempt_6_capped(self) -> None:
        assert get_backoff_delay(6, base_delay=1.0, max_delay=60.0, jitter_factor=0.0) == 60.0

    def test_backoff_custom_base(self) -> None:
        assert get_backoff_delay(0, base_delay=2.0, max_delay=60.0, jitter_factor=0.0) == 2.0

    def test_backoff_custom_base_attempt_1(self) -> None:
        assert get_backoff_delay(1, base_delay=2.0, max_delay=60.0, jitter_factor=0.0) == 4.0

    def test_403_sleep_attempt_is_next_attempt(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=5)
        handler.handle_http_error(_http_error(403), attempt=0)
        assert handler.consume_sleep_attempt() == 1

    def test_403_sleep_attempt_attempt_2(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=5)
        handler.handle_http_error(_http_error(403), attempt=2)
        assert handler.consume_sleep_attempt() == 3

    def test_429_no_retry_after_sleep_attempt(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=5)
        handler.handle_http_error(_http_error(429), attempt=0)
        assert handler.consume_sleep_attempt() == 1

    def test_429_with_retry_after_no_sleep_attempt(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=5)
        handler.handle_http_error(_http_error(429, {"Retry-After": "3"}), attempt=0)
        assert handler.consume_sleep_attempt() is None

    def test_429_retry_after_float_value(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=3)
        wait = handler.handle_http_error(_http_error(429, {"Retry-After": "2.5"}), attempt=0)
        assert wait == pytest.approx(2.5)

    def test_429_retry_after_zero(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=3)
        wait = handler.handle_http_error(_http_error(429, {"Retry-After": "0"}), attempt=0)
        assert wait == pytest.approx(0.0)

    def test_429_retry_after_negative_clamped(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=3)
        wait = handler.handle_http_error(_http_error(429, {"Retry-After": "-10"}), attempt=0)
        assert wait == pytest.approx(0.0)

    def test_429_retry_after_invalid_falls_back_to_backoff(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=3)
        wait = handler.handle_http_error(_http_error(429, {"Retry-After": "abc"}), attempt=0)
        assert wait > 0
        assert handler.consume_sleep_attempt() == 1

    def test_retry_after_delay_float(self) -> None:
        assert get_retry_after_delay(_http_error(429, {"Retry-After": "3.7"})) == pytest.approx(3.7)

    def test_retry_after_delay_zero(self) -> None:
        assert get_retry_after_delay(_http_error(429, {"Retry-After": "0"})) == pytest.approx(0.0)

    def test_retry_after_delay_negative(self) -> None:
        assert get_retry_after_delay(_http_error(429, {"Retry-After": "-1"})) == pytest.approx(0.0)

    def test_retry_after_delay_empty_string(self) -> None:
        assert get_retry_after_delay(_http_error(429, {"Retry-After": ""})) is None

    def test_retry_after_delay_lowercase_header(self) -> None:
        assert get_retry_after_delay(_http_error(429, {"retry-after": "8"})) == pytest.approx(8.0)

    def test_retry_after_delay_non_http_error(self) -> None:
        assert get_retry_after_delay(PerplexityRequestError("x")) is None

    def test_retry_after_delay_runtime_error(self) -> None:
        assert get_retry_after_delay(RuntimeError("x")) is None


class TestRetryHandlerBoundaries:
    def test_403_attempt_max_minus_2_retries(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=4)
        wait = handler.handle_http_error(_http_error(403), attempt=2)
        assert wait > 0

    def test_403_attempt_max_minus_1_raises(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=4)
        with pytest.raises(PerplexityHTTPStatusError):
            handler.handle_http_error(_http_error(403), attempt=3)

    def test_429_attempt_max_minus_2_retries(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=4)
        wait = handler.handle_http_error(_http_error(429), attempt=2)
        assert wait > 0

    def test_429_attempt_max_minus_1_raises(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=4)
        with pytest.raises(PerplexityHTTPStatusError):
            handler.handle_http_error(_http_error(429), attempt=3)

    def test_500_attempt_max_minus_2_retries(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=4)
        wait = handler.handle_http_error(_http_error(500), attempt=2)
        assert wait > 0

    def test_500_attempt_max_minus_1_raises(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=4)
        with pytest.raises(PerplexityHTTPStatusError):
            handler.handle_http_error(_http_error(500), attempt=3)

    def test_network_error_attempt_max_minus_2_retries(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=4)
        result = handler.handle_network_error(PerplexityRequestError("t"), attempt=2)
        assert result == 3

    def test_network_error_attempt_max_minus_1_raises(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=4)
        with pytest.raises(PerplexityRequestError):
            handler.handle_network_error(PerplexityRequestError("t"), attempt=3)


class TestSSEParserEdgeCases:
    def test_comment_line_ignored(self) -> None:
        mock = Mock()
        mock.iter_lines.return_value = [
            b": this is a comment",
            b"event: msg",
            b'data: {"a": 1}',
            b"",
        ]
        result = list(SSEParser.parse(mock, logging.getLogger("t")))
        assert result == [{"a": 1}]

    def test_data_with_colon_in_value(self) -> None:
        mock = Mock()
        mock.iter_lines.return_value = [
            b"event: msg",
            b'data: {"url": "https://example.com"}',
            b"",
        ]
        result = list(SSEParser.parse(mock, logging.getLogger("t")))
        assert result == [{"url": "https://example.com"}]

    def test_event_type_with_spaces(self) -> None:
        event_type, data_lines = SSEParser._parse_line("event:   my_event  ", None, [])
        assert event_type == "my_event"

    def test_data_with_leading_space_stripped(self) -> None:
        _, data_lines = SSEParser._parse_line("data:   padded_value  ", "msg", [])
        assert data_lines == ["padded_value"]

    def test_empty_event_type_string(self) -> None:
        event_type, _ = SSEParser._parse_line("event:", None, [])
        assert event_type == ""

    def test_empty_data_string(self) -> None:
        _, data_lines = SSEParser._parse_line("data:", "msg", [])
        assert data_lines == [""]

    def test_multiple_events_reset_state(self) -> None:
        mock = Mock()
        mock.iter_lines.return_value = [
            b"event: first",
            b'data: {"n": 1}',
            b"",
            b"event: second",
            b'data: {"n": 2}',
            b"",
            b"event: third",
            b'data: {"n": 3}',
            b"",
        ]
        result = list(SSEParser.parse(mock, logging.getLogger("t")))
        assert result == [{"n": 1}, {"n": 2}, {"n": 3}]

    def test_data_only_no_event_not_yielded(self) -> None:
        mock = Mock()
        mock.iter_lines.return_value = [b'data: {"orphan": true}', b""]
        result = list(SSEParser.parse(mock, logging.getLogger("t")))
        assert result == []

    def test_event_only_no_data_not_yielded(self) -> None:
        mock = Mock()
        mock.iter_lines.return_value = [b"event: msg", b""]
        result = list(SSEParser.parse(mock, logging.getLogger("t")))
        assert result == []

    def test_final_event_no_trailing_blank(self) -> None:
        mock = Mock()
        mock.iter_lines.return_value = [b"event: msg", b'data: {"final": true}']
        result = list(SSEParser.parse(mock, logging.getLogger("t")))
        assert result == [{"final": True}]

    def test_final_event_data_only_no_trailing_blank_not_yielded(self) -> None:
        mock = Mock()
        mock.iter_lines.return_value = [b'data: {"orphan": true}']
        result = list(SSEParser.parse(mock, logging.getLogger("t")))
        assert result == []

    def test_final_event_event_only_no_trailing_blank_not_yielded(self) -> None:
        mock = Mock()
        mock.iter_lines.return_value = [b"event: msg"]
        result = list(SSEParser.parse(mock, logging.getLogger("t")))
        assert result == []

    def test_yield_event_exact_error_message_prefix(self) -> None:
        with pytest.raises(UpstreamSchemaError) as exc_info:
            SSEParser._yield_event(["not json at all"])
        assert str(exc_info.value).startswith("Failed to parse SSE data as JSON: ")

    def test_yield_event_non_object_exact_message(self) -> None:
        with pytest.raises(UpstreamSchemaError) as exc_info:
            SSEParser._yield_event(['"just a string"'])
        assert str(exc_info.value) == "SSE data must decode to a JSON object"

    def test_yield_event_array_exact_message(self) -> None:
        with pytest.raises(UpstreamSchemaError) as exc_info:
            SSEParser._yield_event(["[1, 2]"])
        assert str(exc_info.value) == "SSE data must decode to a JSON object"

    def test_yield_event_number_exact_message(self) -> None:
        with pytest.raises(UpstreamSchemaError) as exc_info:
            SSEParser._yield_event(["42"])
        assert str(exc_info.value) == "SSE data must decode to a JSON object"

    def test_yield_event_null_exact_message(self) -> None:
        with pytest.raises(UpstreamSchemaError) as exc_info:
            SSEParser._yield_event(["null"])
        assert str(exc_info.value) == "SSE data must decode to a JSON object"

    def test_yield_event_truncation_exactly_100(self) -> None:
        payload = "y" * 150
        with pytest.raises(UpstreamSchemaError) as exc_info:
            SSEParser._yield_event([payload])
        msg = str(exc_info.value)
        assert "y" * 100 in msg
        assert "y" * 101 not in msg

    def test_multiline_data_joined_with_newline(self) -> None:
        result = SSEParser._yield_event(['{"a":', '"b",', '"c": 1}'])
        assert result == {"a": "b", "c": 1}

    def test_decode_line_bytes_utf8(self) -> None:
        assert SSEParser._decode_line("héllo".encode("utf-8")) == "héllo"

    def test_decode_line_string_passthrough(self) -> None:
        assert SSEParser._decode_line("already string") == "already string"

    def test_accumulate_empty_line_resets_both(self) -> None:
        event_type, data_lines, event = SSEParser._accumulate_line("", "msg", ['{"x": 1}'])
        assert event_type is None
        assert data_lines == []
        assert event == {"x": 1}

    def test_accumulate_non_empty_returns_none_event(self) -> None:
        event_type, data_lines, event = SSEParser._accumulate_line("data: test", "msg", [])
        assert event is None
        assert event_type == "msg"
        assert data_lines == ["test"]


class TestTransportValidation:
    def test_read_transport_value_exact_message_attribute_error(self) -> None:
        def factory() -> object:
            raise AttributeError("missing")

        with pytest.raises(RuntimeError) as exc_info:
            _read_transport_value(factory, "response.status_code")
        assert str(exc_info.value) == "Expected transport attribute for response.status_code"

    def test_read_transport_value_exact_message_type_error(self) -> None:
        def factory() -> object:
            raise TypeError("bad")

        with pytest.raises(RuntimeError) as exc_info:
            _read_transport_value(factory, "response.text")
        assert str(exc_info.value) == "Expected transport attribute for response.text"

    def test_require_str_exact_message(self) -> None:
        with pytest.raises(RuntimeError) as exc_info:
            _require_str(42, "response.reason")
        assert str(exc_info.value) == "Expected string transport attribute for response.reason"

    def test_require_int_exact_message(self) -> None:
        with pytest.raises(RuntimeError) as exc_info:
            _require_int("200", "response.status_code")
        assert str(exc_info.value) == "Expected integer transport attribute for response.status_code"

    def test_require_bool_exact_message(self) -> None:
        with pytest.raises(RuntimeError) as exc_info:
            _require_bool(1, "response.ok")
        assert str(exc_info.value) == "Expected boolean transport attribute for response.ok"

    def test_require_bytes_or_str_exact_message(self) -> None:
        with pytest.raises(RuntimeError) as exc_info:
            _require_bytes_or_str(42, "response.content")
        assert str(exc_info.value) == "Expected bytes-or-string transport attribute for response.content"

    def test_require_json_object_or_none_exact_message(self) -> None:
        with pytest.raises(RuntimeError) as exc_info:
            _require_json_object_or_none([1], "stream.json")
        assert str(exc_info.value) == "Expected JSON object transport attribute for stream.json"

    def test_iter_object_values_non_iterable_exact_message(self) -> None:
        with pytest.raises(RuntimeError) as exc_info:
            list(_iter_object_values(42, "response.iter_lines"))
        assert str(exc_info.value) == "Expected iterable transport value for response.iter_lines"

    def test_coerce_header_pair_non_sized_exact_message(self) -> None:
        with pytest.raises(RuntimeError) as exc_info:
            _coerce_header_pair(42, "response.headers")
        assert str(exc_info.value) == "Expected header pair items for response.headers"

    def test_coerce_header_pair_wrong_size_exact_message(self) -> None:
        with pytest.raises(RuntimeError) as exc_info:
            _coerce_header_pair(("a",), "response.headers")
        assert str(exc_info.value) == "Expected header pair items for response.headers"

    def test_coerce_header_mapping_non_mapping_exact_message(self) -> None:
        with pytest.raises(RuntimeError) as exc_info:
            _coerce_header_mapping("not a mapping", "response.headers")
        assert str(exc_info.value) == "Expected mapping-like transport attribute for response.headers"

    def test_response_adapter_iter_lines_not_callable_exact_message(self) -> None:
        resp = Mock(spec=[])
        adapter = _ResponseAdapter(resp)
        with pytest.raises(RuntimeError) as exc_info:
            list(adapter.iter_lines())
        assert str(exc_info.value) == "Expected callable response.iter_lines transport method"

    def test_response_adapter_iter_lines_bad_line_exact_message(self) -> None:
        resp = Mock()
        resp.iter_lines.return_value = [42]
        adapter = _ResponseAdapter(resp)
        with pytest.raises(RuntimeError) as exc_info:
            list(adapter.iter_lines())
        assert str(exc_info.value) == "Expected bytes or string lines from response.iter_lines"

    def test_stream_context_enter_exact_message(self) -> None:
        ctx = Mock(spec=[])
        adapter = _StreamContextAdapter(ctx)
        with pytest.raises(RuntimeError) as exc_info:
            adapter.__enter__()
        assert str(exc_info.value) == "Expected __enter__ on stream context manager"

    def test_stream_context_exit_exact_message(self) -> None:
        ctx = Mock(spec=[])
        adapter = _StreamContextAdapter(ctx)
        with pytest.raises(RuntimeError) as exc_info:
            adapter.__exit__(None, None, None)
        assert str(exc_info.value) == "Expected __exit__ on stream context manager"

    def test_stream_context_exit_non_bool_exact_message(self) -> None:
        ctx = Mock()
        ctx.__exit__ = Mock(return_value=42)
        adapter = _StreamContextAdapter(ctx)
        with pytest.raises(RuntimeError) as exc_info:
            adapter.__exit__(None, None, None)
        assert str(exc_info.value) == "Expected bool-or-None return from stream context manager"

    def test_stream_context_exit_zero_is_not_bool(self) -> None:
        ctx = Mock()
        ctx.__exit__ = Mock(return_value=0)
        adapter = _StreamContextAdapter(ctx)
        with pytest.raises(RuntimeError, match="Expected bool-or-None return"):
            adapter.__exit__(None, None, None)

    def test_stream_context_exit_empty_string_is_not_bool(self) -> None:
        ctx = Mock()
        ctx.__exit__ = Mock(return_value="")
        adapter = _StreamContextAdapter(ctx)
        with pytest.raises(RuntimeError, match="Expected bool-or-None return"):
            adapter.__exit__(None, None, None)


class TestTransportSessionErrors:
    def test_close_transport_session_attribute_error(self) -> None:
        session = Mock(spec=[])
        with pytest.raises(RuntimeError) as exc_info:
            _close_transport_session(session)
        assert str(exc_info.value) == "Expected callable session.close transport method"

    def test_close_transport_session_type_error(self) -> None:
        session = Mock()
        session.close = "not callable"
        with pytest.raises(RuntimeError) as exc_info:
            _close_transport_session(session)
        assert str(exc_info.value) == "Expected callable session.close transport method"

    def test_open_stream_context_attribute_error(self) -> None:
        session = Mock(spec=[])
        ctx = HttpRequestContext(url="https://x.com", headers={}, effective_timeout=30)
        with pytest.raises(RuntimeError) as exc_info:
            _open_stream_context(session, ctx, cookies={})
        assert str(exc_info.value) == "Expected callable session.stream transport method"

    def test_create_transport_session_bad_factory(self) -> None:
        with patch("perplexity_cli.api.client.importlib.import_module") as mock_import:
            mock_module = Mock(spec=[])
            mock_import.return_value = mock_module
            with pytest.raises(RuntimeError) as exc_info:
                _create_transport_session(timeout=60)
            assert str(exc_info.value) == "Expected callable create_sync_session transport factory"


class TestResponseAdapterProperties:
    def test_status_code_non_int_raises(self) -> None:
        resp = Mock()
        resp.status_code = "200"
        adapter = _ResponseAdapter(resp)
        with pytest.raises(RuntimeError, match="Expected integer transport attribute"):
            _ = adapter.status_code

    def test_text_non_str_raises(self) -> None:
        resp = Mock()
        resp.text = 42
        adapter = _ResponseAdapter(resp)
        with pytest.raises(RuntimeError, match="Expected string transport attribute"):
            _ = adapter.text

    def test_ok_non_bool_raises(self) -> None:
        resp = Mock()
        resp.ok = 1
        adapter = _ResponseAdapter(resp)
        with pytest.raises(RuntimeError, match="Expected boolean transport attribute"):
            _ = adapter.ok

    def test_reason_non_str_raises(self) -> None:
        resp = Mock()
        resp.reason = 404
        adapter = _ResponseAdapter(resp)
        with pytest.raises(RuntimeError, match="Expected string transport attribute"):
            _ = adapter.reason

    def test_content_non_bytes_str_raises(self) -> None:
        resp = Mock()
        resp.content = 42
        adapter = _ResponseAdapter(resp)
        with pytest.raises(RuntimeError, match="Expected bytes-or-string transport attribute"):
            _ = adapter.content

    def test_headers_non_mapping_raises(self) -> None:
        resp = Mock()
        resp.headers = "not a mapping"
        adapter = _ResponseAdapter(resp)
        with pytest.raises(RuntimeError, match="Expected mapping-like transport attribute"):
            _ = adapter.headers

    def test_url_returns_none_on_type_error(self) -> None:
        resp = Mock()
        type(resp).url = property(lambda self: (_ for _ in ()).throw(TypeError("bad")))
        adapter = _ResponseAdapter(resp)
        assert adapter.url is None

    def test_status_code_missing_attribute_raises(self) -> None:
        resp = Mock(spec=[])
        adapter = _ResponseAdapter(resp)
        with pytest.raises(RuntimeError, match="Expected transport attribute"):
            _ = adapter.status_code


class TestHeaderConstruction:
    def test_get_headers_exact_keys(self) -> None:
        client = SSEClient(auth=AuthContext(token="test-token"))
        headers = client.get_headers()
        assert set(headers.keys()) == {"Content-Type", "Origin", "Referer", "Accept", "Authorization"}

    def test_get_headers_content_type(self) -> None:
        client = SSEClient(auth=AuthContext(token="test-token"))
        assert client.get_headers()["Content-Type"] == "application/json"

    def test_get_headers_accept(self) -> None:
        client = SSEClient(auth=AuthContext(token="test-token"))
        assert client.get_headers()["Accept"] == "text/event-stream"

    def test_get_headers_authorization(self) -> None:
        client = SSEClient(auth=AuthContext(token="my-jwt"))
        assert client.get_headers()["Authorization"] == "Bearer my-jwt"

    def test_get_headers_no_user_agent(self) -> None:
        client = SSEClient(auth=AuthContext(token="test-token"))
        assert "User-Agent" not in client.get_headers()

    def test_get_headers_with_csrf(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok", cookies={"csrftoken": "csrf123"}))
        assert client.get_headers()["X-CSRFToken"] == "csrf123"

    def test_get_headers_without_csrf(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok", cookies={"other": "val"}))
        assert "X-CSRFToken" not in client.get_headers()

    def test_coerce_header_mapping_integer_values(self) -> None:
        result = _coerce_header_mapping({"status": 200, "count": 5}, "ctx")
        assert result == {"status": "200", "count": "5"}

    def test_coerce_header_pair_coerces_both(self) -> None:
        assert _coerce_header_pair((123, 456), "ctx") == ("123", "456")


class TestDeepResearchDetection:
    def test_search_mode_override_research(self) -> None:
        assert _is_deep_research_request({"searchModeOverride": "research"}) is True

    def test_search_mode_override_deep_research(self) -> None:
        assert _is_deep_research_request({"searchModeOverride": "deep_research"}) is True

    def test_search_mode_override_research_uppercase(self) -> None:
        assert _is_deep_research_request({"searchModeOverride": "RESEARCH"}) is True

    def test_search_mode_override_standard(self) -> None:
        assert _is_deep_research_request({"searchModeOverride": "standard"}) is False

    def test_search_mode_research(self) -> None:
        assert _is_deep_research_request({"search_mode": "research"}) is True

    def test_search_mode_deep_research(self) -> None:
        assert _is_deep_research_request({"search_mode": "deep_research"}) is True

    def test_workflow_key_research(self) -> None:
        assert _is_deep_research_request({"workflow_key": "research"}) is True

    def test_workflow_key_deep_research(self) -> None:
        assert _is_deep_research_request({"workflow_key": "deep_research"}) is True

    def test_workflow_key_research_uppercase(self) -> None:
        assert _is_deep_research_request({"workflow_key": "RESEARCH"}) is True

    def test_multi_step_takes_priority(self) -> None:
        assert _is_deep_research_request({"search_implementation_mode": "multi_step"}) is True

    def test_multi_step_wrong_value(self) -> None:
        assert _is_deep_research_request({"search_implementation_mode": "single_step"}) is False

    def test_non_string_value_not_deep(self) -> None:
        assert _is_deep_research_request({"search_mode": 42}) is False

    def test_none_value_not_deep(self) -> None:
        assert _is_deep_research_request({"search_mode": None}) is False

    def test_deep_research_value_list_not_deep(self) -> None:
        assert _is_deep_research_value(["research"]) is False

    def test_deep_research_value_dict_not_deep(self) -> None:
        assert _is_deep_research_value({"mode": "research"}) is False

    def test_resolve_timeout_search_mode_override(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), timeout=45)
        is_deep, timeout = client._resolve_effective_timeout(
            {"params": {"searchModeOverride": "research"}}
        )
        assert is_deep is True
        assert timeout == 360

    def test_resolve_timeout_workflow_key(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), timeout=45)
        is_deep, timeout = client._resolve_effective_timeout(
            {"params": {"workflow_key": "deep_research"}}
        )
        assert is_deep is True
        assert timeout == 360

    def test_resolve_timeout_no_params_uses_default(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), timeout=42)
        is_deep, timeout = client._resolve_effective_timeout({"query": "test"})
        assert is_deep is False
        assert timeout == 42

    def test_resolve_timeout_params_none_uses_default(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), timeout=33)
        is_deep, timeout = client._resolve_effective_timeout({"params": None})
        assert is_deep is False
        assert timeout == 33

    def test_resolve_timeout_params_list_uses_default(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), timeout=55)
        is_deep, timeout = client._resolve_effective_timeout({"params": [1, 2]})
        assert is_deep is False
        assert timeout == 55


class TestSSEClientDefaults:
    def test_default_timeout_is_60(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"))
        assert client.timeout == 60

    def test_default_max_retries_is_3(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"))
        assert client.max_retries == 3

    def test_custom_timeout(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), timeout=120)
        assert client.timeout == 120

    def test_custom_max_retries(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=7)
        assert client.max_retries == 7

    def test_client_initially_none(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"))
        assert client._client is None

    def test_auth_stored(self) -> None:
        auth = AuthContext(token="tok")
        client = SSEClient(auth=auth)
        assert client.auth is auth


class TestSSEClientStreamPost:
    def _make_ok_session(self, lines: list[bytes]) -> Mock:
        resp = Mock()
        resp.ok = True
        resp.status_code = 200
        resp.reason = "OK"
        resp.headers = {}
        resp.iter_lines.return_value = lines
        ctx = Mock()
        ctx.__enter__ = Mock(return_value=resp)
        ctx.__exit__ = Mock(return_value=False)
        session = Mock()
        session.stream.return_value = ctx
        return session

    def test_stream_post_passes_url(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=1)
        client._client = self._make_ok_session([b"event: m", b'data: {"a":1}', b""])
        list(client.stream_post("https://api.test.com/query", {"q": "x"}))
        call_args = client._client.stream.call_args
        assert call_args[0][1] == "https://api.test.com/query"

    def test_stream_post_passes_post_method(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=1)
        client._client = self._make_ok_session([])
        list(client.stream_post("https://x.com", {}))
        assert client._client.stream.call_args[0][0] == "POST"

    def test_stream_post_passes_json_data(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=1)
        client._client = self._make_ok_session([])
        list(client.stream_post("https://x.com", {"query": "test"}))
        assert client._client.stream.call_args[1]["json"] == {"query": "test"}

    def test_stream_post_passes_timeout(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), timeout=99, max_retries=1)
        client._client = self._make_ok_session([])
        list(client.stream_post("https://x.com", {}))
        assert client._client.stream.call_args[1]["timeout"] == 99

    def test_stream_post_deep_research_timeout(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), timeout=60, max_retries=1)
        client._client = self._make_ok_session([])
        list(client.stream_post("https://x.com", {"params": {"search_implementation_mode": "multi_step"}}))
        assert client._client.stream.call_args[1]["timeout"] == 360

    def test_stream_post_yields_parsed_events(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=1)
        client._client = self._make_ok_session([
            b"event: message",
            b'data: {"status": "complete"}',
            b"",
        ])
        results = list(client.stream_post("https://x.com", {}))
        assert results == [{"status": "complete"}]

    def test_stream_post_empty_stream(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=1)
        client._client = self._make_ok_session([])
        results = list(client.stream_post("https://x.com", {}))
        assert results == []


class TestRetryHandlerLogMessages:
    def test_401_logs_error(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.401.log")
        logger.setLevel(logging.DEBUG)
        handler = RetryHandler(logger, max_retries=3)
        with caplog.at_level(logging.DEBUG, logger="test.401.log"):
            with pytest.raises(PerplexityHTTPStatusError):
                handler.handle_http_error(_http_error(401), attempt=0)
        messages = [r.getMessage() for r in caplog.records]
        assert any("HTTP 401 error (not retryable)" in m for m in messages)

    def test_403_logs_warning_with_attempt(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.403.log")
        logger.setLevel(logging.DEBUG)
        handler = RetryHandler(logger, max_retries=3)
        with caplog.at_level(logging.DEBUG, logger="test.403.log"):
            handler.handle_http_error(_http_error(403), attempt=0)
        messages = [r.getMessage() for r in caplog.records]
        assert any("HTTP 403 error (may be Cloudflare blocking)" in m for m in messages)
        assert any("attempt 2/3" in m for m in messages)

    def test_403_exhausted_logs_error(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.403.exhausted")
        logger.setLevel(logging.DEBUG)
        handler = RetryHandler(logger, max_retries=2)
        with caplog.at_level(logging.DEBUG, logger="test.403.exhausted"):
            with pytest.raises(PerplexityHTTPStatusError):
                handler.handle_http_error(_http_error(403), attempt=1)
        messages = [r.getMessage() for r in caplog.records]
        assert any("not retryable after 2 attempts" in m for m in messages)

    def test_429_logs_warning_with_status(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.429.log")
        logger.setLevel(logging.DEBUG)
        handler = RetryHandler(logger, max_retries=3)
        with caplog.at_level(logging.DEBUG, logger="test.429.log"):
            handler.handle_http_error(_http_error(429), attempt=0)
        messages = [r.getMessage() for r in caplog.records]
        assert any("HTTP 429 error" in m for m in messages)

    def test_network_error_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.net.log")
        logger.setLevel(logging.DEBUG)
        handler = RetryHandler(logger, max_retries=3)
        with caplog.at_level(logging.DEBUG, logger="test.net.log"):
            handler.handle_network_error(PerplexityRequestError("timeout"), attempt=0)
        messages = [r.getMessage() for r in caplog.records]
        assert any("Network error, retrying" in m for m in messages)
        assert any("attempt 2/3" in m for m in messages)

    def test_network_error_exhausted_logs_error(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.net.exhausted")
        logger.setLevel(logging.DEBUG)
        handler = RetryHandler(logger, max_retries=2)
        with caplog.at_level(logging.DEBUG, logger="test.net.exhausted"):
            with pytest.raises(PerplexityRequestError):
                handler.handle_network_error(PerplexityRequestError("timeout"), attempt=1)
        messages = [r.getMessage() for r in caplog.records]
        assert any("Network error after 2 attempts" in m for m in messages)


class TestLogHTTPErrorContext:
    def test_debug_logs_response_body_preview(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.body.preview")
        logger.setLevel(logging.DEBUG)
        handler = RetryHandler(logger, max_retries=3)
        error = _http_error(500)
        with caplog.at_level(logging.DEBUG, logger="test.body.preview"):
            handler._log_http_error_context(error)
        messages = [r.getMessage() for r in caplog.records]
        assert any("Response body preview" in m for m in messages)

    def test_debug_logs_status(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.status.log")
        logger.setLevel(logging.DEBUG)
        handler = RetryHandler(logger, max_retries=3)
        error = _http_error(502)
        with caplog.at_level(logging.DEBUG, logger="test.status.log"):
            handler._log_http_error_context(error)
        messages = [r.getMessage() for r in caplog.records]
        assert any("HTTP Error 502" in m for m in messages)

    def test_debug_disabled_no_output(self) -> None:
        logger = logging.getLogger("test.no.debug")
        logger.setLevel(logging.WARNING)
        handler = RetryHandler(logger, max_retries=3)
        assert logger.isEnabledFor(logging.DEBUG) is False
        handler._log_http_error_context(_http_error(500))

    def test_cf_ray_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.cf.ray")
        logger.setLevel(logging.DEBUG)
        handler = RetryHandler(logger, max_retries=3)
        error = _http_error(403, {"cf-ray": "abc-ray-123"})
        with caplog.at_level(logging.DEBUG, logger="test.cf.ray"):
            handler._log_http_error_context(error)
        messages = [r.getMessage() for r in caplog.records]
        assert any("Cloudflare Ray ID: abc-ray-123" in m for m in messages)

    def test_cf_cache_status_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.cf.cache")
        logger.setLevel(logging.DEBUG)
        handler = RetryHandler(logger, max_retries=3)
        error = _http_error(403, {"cf-cache-status": "MISS"})
        with caplog.at_level(logging.DEBUG, logger="test.cf.cache"):
            handler._log_http_error_context(error)
        messages = [r.getMessage() for r in caplog.records]
        assert any("Cloudflare Cache Status: MISS" in m for m in messages)


class TestIsRequestException:
    def test_curl_request_exception(self) -> None:
        from curl_cffi.requests.exceptions import RequestException

        assert _is_request_exception(RequestException("fail")) is True

    def test_generic_exception(self) -> None:
        assert _is_request_exception(RuntimeError("fail")) is False

    def test_value_error(self) -> None:
        assert _is_request_exception(ValueError("fail")) is False

    def test_perplexity_request_error(self) -> None:
        assert _is_request_exception(PerplexityRequestError("fail")) is False


class TestIsJsonObject:
    def test_dict_true(self) -> None:
        assert _is_json_object({"a": 1}) is True

    def test_empty_dict_true(self) -> None:
        assert _is_json_object({}) is True

    def test_list_false(self) -> None:
        assert _is_json_object([1]) is False

    def test_string_false(self) -> None:
        assert _is_json_object("str") is False

    def test_none_false(self) -> None:
        assert _is_json_object(None) is False

    def test_int_false(self) -> None:
        assert _is_json_object(42) is False

    def test_bool_false(self) -> None:
        assert _is_json_object(True) is False


class TestConstants:
    def test_http_status_unauthorised(self) -> None:
        assert HTTP_STATUS_UNAUTHORISED == 401

    def test_http_status_forbidden(self) -> None:
        assert HTTP_STATUS_FORBIDDEN == 403

    def test_http_status_too_many_requests(self) -> None:
        assert HTTP_STATUS_TOO_MANY_REQUESTS == 429

    def test_deep_research_timeout_mode(self) -> None:
        assert DEEP_RESEARCH_TIMEOUT_MODE == "multi_step"

    def test_header_pair_size(self) -> None:
        assert HEADER_PAIR_SIZE == 2

    def test_deep_research_mode_keys(self) -> None:
        assert DEEP_RESEARCH_MODE_KEYS == ("searchModeOverride", "search_mode", "workflow_key")

    def test_deep_research_mode_values(self) -> None:
        assert DEEP_RESEARCH_MODE_VALUES == frozenset({"research", "deep_research", "RESEARCH"})


class TestConsumeSleepAttempt:
    def test_initial_none(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=3)
        assert handler.consume_sleep_attempt() is None

    def test_returns_and_clears(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=3)
        handler._sleep_attempt = 7
        assert handler.consume_sleep_attempt() == 7
        assert handler.consume_sleep_attempt() is None

    def test_handle_http_error_resets(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=3)
        handler._sleep_attempt = 99
        with pytest.raises(PerplexityHTTPStatusError):
            handler.handle_http_error(_http_error(401), attempt=0)
        assert handler._sleep_attempt is None


class TestRetryStreamError:
    def test_http_error_returns_incremented(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=3)
        with patch.object(client, "_sleep_for_retry"):
            result = client._retry_stream_error(_http_error(500), attempt=0)
        assert result == 1

    def test_http_error_attempt_2_returns_3(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=5)
        with patch.object(client, "_sleep_for_retry"):
            result = client._retry_stream_error(_http_error(500), attempt=2)
        assert result == 3

    def test_request_error_returns_incremented(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=3)
        result = client._retry_stream_error(PerplexityRequestError("t"), attempt=0)
        assert result == 1

    def test_curl_request_error_raises_perplexity_request_error(self) -> None:
        from curl_cffi.requests.exceptions import RequestException

        client = SSEClient(auth=AuthContext(token="tok"), max_retries=3)
        with pytest.raises(PerplexityRequestError, match="conn"):
            client._retry_stream_error(RequestException("conn"), attempt=0)

    def test_unknown_error_reraises(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=3)
        with pytest.raises(ValueError, match="unexpected"):
            client._retry_stream_error(ValueError("unexpected"), attempt=0)


class TestSleepForRetry:
    def test_with_sleep_attempt_calls_backoff(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=3)
        client._retry._sleep_attempt = 3
        with patch("perplexity_cli.api.client.sleep_with_backoff") as mock_sleep:
            client._sleep_for_retry(10.0)
        mock_sleep.assert_called_once_with(3)

    def test_without_sleep_attempt_calls_event_wait(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=3)
        client._retry._sleep_attempt = None
        with patch("perplexity_cli.api.client.threading.Event") as mock_cls:
            mock_event = Mock()
            mock_cls.return_value = mock_event
            client._sleep_for_retry(4.2)
        mock_event.wait.assert_called_once_with(4.2)


class TestLogResponseHeaders:
    def test_cf_cache_status_label(self, caplog: pytest.LogCaptureFixture) -> None:
        client = SSEClient(auth=AuthContext(token="tok"))
        client.logger.setLevel(logging.DEBUG)
        resp = Mock()
        resp.status_code = 200
        resp.reason = "OK"
        resp.headers = {"cf-cache-status": "HIT"}
        adapter = _ResponseAdapter(resp)
        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            client._log_response_headers(adapter)
        messages = [r.getMessage() for r in caplog.records]
        assert any("Cloudflare Cache Status" in m for m in messages)

    def test_server_label(self, caplog: pytest.LogCaptureFixture) -> None:
        client = SSEClient(auth=AuthContext(token="tok"))
        client.logger.setLevel(logging.DEBUG)
        resp = Mock()
        resp.status_code = 200
        resp.reason = "OK"
        resp.headers = {"server": "cloudflare"}
        adapter = _ResponseAdapter(resp)
        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            client._log_response_headers(adapter)
        messages = [r.getMessage() for r in caplog.records]
        assert any("Server: cloudflare" in m for m in messages)

    def test_no_debug_no_output(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"))
        client.logger.setLevel(logging.WARNING)
        resp = Mock()
        resp.status_code = 200
        resp.reason = "OK"
        resp.headers = {"cf-ray": "ray"}
        adapter = _ResponseAdapter(resp)
        assert client.logger.isEnabledFor(logging.DEBUG) is False
        client._log_response_headers(adapter)


class TestLogRequestContext:
    def test_deep_research_logs_timeout(self, caplog: pytest.LogCaptureFixture) -> None:
        client = SSEClient(auth=AuthContext(token="tok"))
        client.logger.setLevel(logging.DEBUG)
        ctx = HttpRequestContext(url="https://x.com/api", headers={"Content-Type": "application/json"}, effective_timeout=360)
        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            client._log_request_context(ctx, query_mode="deep_research")
        messages = [r.getMessage() for r in caplog.records]
        assert any("Deep research mode detected" in m for m in messages)
        assert any("360" in m for m in messages)

    def test_default_mode_no_deep_research_log(self, caplog: pytest.LogCaptureFixture) -> None:
        client = SSEClient(auth=AuthContext(token="tok"))
        client.logger.setLevel(logging.DEBUG)
        ctx = HttpRequestContext(url="https://x.com/api", headers={"Content-Type": "application/json"}, effective_timeout=60)
        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            client._log_request_context(ctx, query_mode="default")
        messages = [r.getMessage() for r in caplog.records]
        assert not any("Deep research mode" in m for m in messages)

    def test_logs_auth_token_present(self, caplog: pytest.LogCaptureFixture) -> None:
        client = SSEClient(auth=AuthContext(token="tok"))
        client.logger.setLevel(logging.DEBUG)
        ctx = HttpRequestContext(url="https://x.com", headers={}, effective_timeout=60)
        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            client._log_request_context(ctx)
        messages = [r.getMessage() for r in caplog.records]
        assert any("Bearer token present=True" in m for m in messages)


class TestLogCookieContext:
    def test_no_cookies_logs_none(self, caplog: pytest.LogCaptureFixture) -> None:
        client = SSEClient(auth=AuthContext(token="tok"))
        client.logger.setLevel(logging.DEBUG)
        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            client._log_cookie_context()
        messages = [r.getMessage() for r in caplog.records]
        assert any("Cookies: None (no Cloudflare bypass)" in m for m in messages)

    def test_with_cookies_logs_count(self, caplog: pytest.LogCaptureFixture) -> None:
        client = SSEClient(auth=AuthContext(token="tok", cookies={"cf_clearance": "x", "session": "y"}))
        client.logger.setLevel(logging.DEBUG)
        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            client._log_cookie_context()
        messages = [r.getMessage() for r in caplog.records]
        assert any("2 total" in m for m in messages)
        assert any("1 Cloudflare-related" in m for m in messages)


class TestNetworkErrorHandling:
    def test_curl_exception_converts_to_perplexity_error(self) -> None:
        from curl_cffi.requests.exceptions import RequestException

        handler = RetryHandler(logging.getLogger("t"), max_retries=3)
        with pytest.raises(PerplexityRequestError) as exc_info:
            handler.handle_network_error(RequestException("connection reset"), attempt=0)
        assert str(exc_info.value) == "connection reset"

    def test_curl_exception_cause_chain(self) -> None:
        from curl_cffi.requests.exceptions import RequestException

        handler = RetryHandler(logging.getLogger("t"), max_retries=3)
        original = RequestException("dns failure")
        with pytest.raises(PerplexityRequestError) as exc_info:
            handler.handle_network_error(original, attempt=0)
        assert exc_info.value.__cause__ is original

    def test_non_retryable_reraises_same_object(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=3)
        original = ValueError("bad")
        with pytest.raises(ValueError) as exc_info:
            handler.handle_network_error(original, attempt=0)
        assert exc_info.value is original

    def test_exhausted_reraises_same_object(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=1)
        original = PerplexityRequestError("timeout")
        with pytest.raises(PerplexityRequestError) as exc_info:
            handler.handle_network_error(original, attempt=0)
        assert exc_info.value is original

    def test_retryable_returns_attempt_plus_1(self) -> None:
        handler = RetryHandler(logging.getLogger("t"), max_retries=5)
        assert handler.handle_network_error(PerplexityRequestError("t"), attempt=0) == 1
        assert handler.handle_network_error(PerplexityRequestError("t"), attempt=3) == 4


class TestSSEParseLineSliceIndices:
    """Kill off-by-one mutants in _parse_line slice operations."""

    def test_event_no_space_after_colon(self) -> None:
        event_type, data_lines = SSEParser._parse_line("event:x", None, [])
        assert event_type == "x"
        assert data_lines == []

    def test_data_no_space_after_colon(self) -> None:
        event_type, data_lines = SSEParser._parse_line("data:x", "msg", [])
        assert data_lines == ["x"]
        assert event_type == "msg"

    def test_event_single_char_preserved(self) -> None:
        event_type, _ = SSEParser._parse_line("event:Z", None, [])
        assert event_type == "Z"

    def test_data_single_char_preserved(self) -> None:
        _, data_lines = SSEParser._parse_line("data:Z", "e", [])
        assert data_lines == ["Z"]

    def test_event_prefix_not_matched_by_data(self) -> None:
        event_type, data_lines = SSEParser._parse_line("data:hello", None, [])
        assert event_type is None
        assert data_lines == ["hello"]

    def test_data_prefix_not_matched_by_event(self) -> None:
        event_type, data_lines = SSEParser._parse_line("event:hello", "prev", [])
        assert event_type == "hello"
        assert data_lines == []


class TestLogResponseHeadersCfRay:
    """Kill string-replacement mutants in _log_response_headers label logic."""

    def test_cf_ray_label_exact(self, caplog: pytest.LogCaptureFixture) -> None:
        client = SSEClient(auth=AuthContext(token="tok"))
        client.logger.setLevel(logging.DEBUG)
        resp = Mock()
        resp.status_code = 200
        resp.reason = "OK"
        resp.headers = {"cf-ray": "ray-abc-123"}
        adapter = _ResponseAdapter(resp)
        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            client._log_response_headers(adapter)
        messages = [r.getMessage() for r in caplog.records]
        assert any("Cloudflare Ray: ray-abc-123" in m for m in messages)

    def test_all_three_headers_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        client = SSEClient(auth=AuthContext(token="tok"))
        client.logger.setLevel(logging.DEBUG)
        resp = Mock()
        resp.status_code = 200
        resp.reason = "OK"
        resp.headers = {"cf-ray": "r1", "cf-cache-status": "HIT", "server": "cloudflare"}
        adapter = _ResponseAdapter(resp)
        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            client._log_response_headers(adapter)
        messages = [r.getMessage() for r in caplog.records]
        assert any("Cloudflare Ray: r1" in m for m in messages)
        assert any("Cloudflare Cache Status: HIT" in m for m in messages)
        assert any("Server: cloudflare" in m for m in messages)


class TestLogHTTPErrorBodyTruncation:
    """Kill boundary mutants in _log_http_error_context body[:500] slice."""

    def test_body_truncated_at_500_chars(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.trunc500")
        logger.setLevel(logging.DEBUG)
        handler = RetryHandler(logger, max_retries=3)
        request = SimpleRequest(method="POST", url="https://x.com")
        long_body = "A" * 600
        response = SimpleResponse(status_code=500, headers={}, text=long_body, request=request)
        error = PerplexityHTTPStatusError("err", request=request, response=response)
        with patch("perplexity_cli.api.client.redact_response_text", side_effect=lambda x: x):
            with caplog.at_level(logging.DEBUG, logger="test.trunc500"):
                handler._log_http_error_context(error)
        messages = [r.getMessage() for r in caplog.records]
        body_msgs = [m for m in messages if "Response body preview" in m]
        assert len(body_msgs) == 1
        assert "A" * 500 in body_msgs[0]
        assert "A" * 501 not in body_msgs[0]


class TestNetworkErrorLogArithmetic:
    """Kill arithmetic mutants in handle_network_error log messages."""

    def test_curl_error_logs_attempt_plus_1(self, caplog: pytest.LogCaptureFixture) -> None:
        from curl_cffi.requests.exceptions import RequestException

        logger = logging.getLogger("test.net.curl.log")
        logger.setLevel(logging.DEBUG)
        handler = RetryHandler(logger, max_retries=3)
        with caplog.at_level(logging.DEBUG, logger="test.net.curl.log"):
            with pytest.raises(PerplexityRequestError):
                handler.handle_network_error(RequestException("fail"), attempt=2)
        messages = [r.getMessage() for r in caplog.records]
        assert any("Network error after 3 attempts" in m for m in messages)

    def test_exhausted_logs_attempt_plus_1(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.net.exhaust.log")
        logger.setLevel(logging.DEBUG)
        handler = RetryHandler(logger, max_retries=1)
        with caplog.at_level(logging.DEBUG, logger="test.net.exhaust.log"):
            with pytest.raises(PerplexityRequestError):
                handler.handle_network_error(PerplexityRequestError("t"), attempt=0)
        messages = [r.getMessage() for r in caplog.records]
        assert any("Network error after 1 attempts" in m for m in messages)
