"""Mutation-killing tests for api/, threads/, query_runner, and query_streaming.

Targets survived mutants: boundary flips, arithmetic changes, string alterations,
boolean negations, and return value swaps that existing tests do not catch.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timezone
from io import StringIO
from unittest.mock import Mock, patch

import pytest

from perplexity_cli.api.client import (
    HEADER_PAIR_SIZE,
    RetryHandler,
    SSEClient,
    SSEParser,
    _coerce_header_mapping,
    _coerce_header_pair,
    _is_deep_research_request,
    _is_deep_research_value,
    _is_json_object,
    _iter_object_values,
    _read_transport_value,
    _require_bool,
    _require_bytes_or_str,
    _require_int,
    _require_json_object_or_none,
    _require_str,
    _ResponseAdapter,
    _StreamContextAdapter,
)
from perplexity_cli.api.models import (
    Answer,
    Block,
    QueryInput,
    QueryParams,
    SSEMessage,
    TraceContext,
    WebResult,
    _as_object_dict,
    _as_object_list,
)
from perplexity_cli.auth.models import AuthContext
from perplexity_cli.threads.cache_manager import ThreadCacheManager
from perplexity_cli.threads.date_parser import (
    _check_after_start,
    _check_before_end,
    _parse_day_end,
    _parse_day_start,
    to_iso8601,
)
from perplexity_cli.threads.exporter import ThreadRecord, write_threads_csv
from perplexity_cli.threads.models import CacheContent, CacheFormat, CacheMetadata, DateRange
from perplexity_cli.threads.scraper import (
    BatchProcessingContext,
    _build_batch_processing_context,
    _coerce_optional_int,
    _coerce_optional_str,
    _coerce_progress_callback,
    _extract_cache_thread_dicts,
    _get_cache_str_field,
    _get_str_field,
    _has_integer_status_code,
    _has_more_pages,
    _is_response_protocol,
    _legacy_context_value,
    _parse_single_thread,
    _report_progress,
    _require_response,
    _response_core_members,
    _validate_batch_processing_arg_count,
    _validate_date_params,
)
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    UpstreamSchemaError,
)
from perplexity_cli.utils.logging import get_logger

# ---------------------------------------------------------------------------
# api/client.py – transport validators and helpers
# ---------------------------------------------------------------------------


class TestReadTransportValue:
    """Kill mutants in _read_transport_value."""

    def test_returns_value_on_success(self):
        assert _read_transport_value(lambda: 42, "test.ctx") == 42

    def test_raises_runtime_error_on_attribute_error(self):
        def factory():
            raise AttributeError("missing")

        with pytest.raises(RuntimeError, match=r"Expected transport attribute for test\.ctx"):
            _read_transport_value(factory, "test.ctx")

    def test_raises_runtime_error_on_type_error(self):
        def factory():
            raise TypeError("bad type")

        with pytest.raises(RuntimeError, match=r"Expected transport attribute for test\.ctx"):
            _read_transport_value(factory, "test.ctx")

    def test_preserves_cause_chain(self):
        original = AttributeError("root cause")

        def factory():
            raise original

        with pytest.raises(RuntimeError) as exc_info:
            _read_transport_value(factory, "ctx")
        assert exc_info.value.__cause__ is original


class TestRequireStr:
    """Kill mutants in _require_str."""

    def test_returns_string(self):
        assert _require_str("hello", "ctx") == "hello"

    def test_returns_empty_string(self):
        assert _require_str("", "ctx") == ""

    def test_rejects_bytes(self):
        with pytest.raises(RuntimeError, match="Expected string transport attribute for ctx"):
            _require_str(b"bytes", "ctx")

    def test_rejects_none(self):
        with pytest.raises(RuntimeError, match="Expected string transport attribute for ctx"):
            _require_str(None, "ctx")

    def test_rejects_int(self):
        with pytest.raises(RuntimeError, match="Expected string transport attribute for ctx"):
            _require_str(123, "ctx")


class TestRequireInt:
    """Kill mutants in _require_int."""

    def test_returns_int(self):
        assert _require_int(200, "ctx") == 200

    def test_returns_zero(self):
        assert _require_int(0, "ctx") == 0

    def test_returns_negative(self):
        assert _require_int(-1, "ctx") == -1

    def test_bool_is_int_subclass(self):
        assert _require_int(True, "ctx") is True

    def test_rejects_string(self):
        with pytest.raises(RuntimeError, match="Expected integer transport attribute for ctx"):
            _require_int("200", "ctx")


class TestRequireBool:
    """Kill mutants in _require_bool."""

    def test_returns_true(self):
        assert _require_bool(True, "ctx") is True

    def test_returns_false(self):
        assert _require_bool(False, "ctx") is False

    def test_rejects_int_one(self):
        with pytest.raises(RuntimeError, match="Expected boolean transport attribute for ctx"):
            _require_bool(1, "ctx")

    def test_rejects_string(self):
        with pytest.raises(RuntimeError, match="Expected boolean transport attribute for ctx"):
            _require_bool("true", "ctx")


class TestRequireBytesOrStr:
    """Kill mutants in _require_bytes_or_str."""

    def test_returns_bytes(self):
        assert _require_bytes_or_str(b"data", "ctx") == b"data"

    def test_returns_str(self):
        assert _require_bytes_or_str("data", "ctx") == "data"

    def test_returns_empty_bytes(self):
        assert _require_bytes_or_str(b"", "ctx") == b""

    def test_rejects_int(self):
        with pytest.raises(RuntimeError, match="Expected bytes-or-string transport attribute"):
            _require_bytes_or_str(42, "ctx")


class TestRequireJsonObjectOrNone:
    """Kill mutants in _require_json_object_or_none."""

    def test_returns_none_for_none(self):
        assert _require_json_object_or_none(None, "ctx") is None

    def test_returns_dict(self):
        result = _require_json_object_or_none({"key": "val"}, "ctx")
        assert result == {"key": "val"}

    def test_returns_empty_dict(self):
        assert _require_json_object_or_none({}, "ctx") == {}

    def test_rejects_list(self):
        with pytest.raises(RuntimeError, match="Expected JSON object transport attribute"):
            _require_json_object_or_none([1, 2], "ctx")

    def test_rejects_string(self):
        with pytest.raises(RuntimeError, match="Expected JSON object transport attribute"):
            _require_json_object_or_none("not a dict", "ctx")


class TestIsDeepResearchValue:
    """Kill mutants in _is_deep_research_value."""

    def test_research(self):
        assert _is_deep_research_value("research") is True

    def test_deep_research(self):
        assert _is_deep_research_value("deep_research") is True

    def test_research_uppercase(self):
        assert _is_deep_research_value("RESEARCH") is True

    def test_standard(self):
        assert _is_deep_research_value("standard") is False

    def test_empty_string(self):
        assert _is_deep_research_value("") is False

    def test_non_string(self):
        assert _is_deep_research_value(42) is False

    def test_none(self):
        assert _is_deep_research_value(None) is False


class TestIsDeepResearchRequest:
    """Kill mutants in _is_deep_research_request."""

    def test_multi_step_mode(self):
        assert _is_deep_research_request({"search_implementation_mode": "multi_step"}) is True

    def test_standard_mode(self):
        assert _is_deep_research_request({"search_implementation_mode": "standard"}) is False

    def test_search_mode_override(self):
        assert _is_deep_research_request({"searchModeOverride": "research"}) is True

    def test_search_mode_key(self):
        assert _is_deep_research_request({"search_mode": "deep_research"}) is True

    def test_workflow_key(self):
        assert _is_deep_research_request({"workflow_key": "RESEARCH"}) is True

    def test_empty_params(self):
        assert _is_deep_research_request({}) is False

    def test_non_matching_values(self):
        assert _is_deep_research_request({"search_mode": "standard"}) is False


class TestIterObjectValues:
    """Kill mutants in _iter_object_values."""

    def test_iterates_list(self):
        assert list(_iter_object_values([1, 2, 3], "ctx")) == [1, 2, 3]

    def test_iterates_empty(self):
        assert list(_iter_object_values([], "ctx")) == []

    def test_iterates_tuple(self):
        assert list(_iter_object_values(("a", "b"), "ctx")) == ["a", "b"]

    def test_raises_on_non_iterable(self):
        with pytest.raises(RuntimeError, match="Expected iterable transport value for ctx"):
            list(_iter_object_values(42, "ctx"))


class TestCoerceHeaderPair:
    """Kill mutants in _coerce_header_pair."""

    def test_valid_pair(self):
        assert _coerce_header_pair(("Content-Type", "application/json"), "ctx") == (
            "Content-Type",
            "application/json",
        )

    def test_coerces_non_string_values(self):
        assert _coerce_header_pair(("key", 123), "ctx") == ("key", "123")

    def test_rejects_single_element(self):
        with pytest.raises(RuntimeError, match="Expected header pair items for ctx"):
            _coerce_header_pair(("only-one",), "ctx")

    def test_rejects_three_elements(self):
        with pytest.raises(RuntimeError, match="Expected header pair items for ctx"):
            _coerce_header_pair(("a", "b", "c"), "ctx")

    def test_rejects_non_sized(self):
        with pytest.raises(RuntimeError, match="Expected header pair items for ctx"):
            _coerce_header_pair(42, "ctx")

    def test_header_pair_size_constant(self):
        assert HEADER_PAIR_SIZE == 2


class TestCoerceHeaderMapping:
    """Kill mutants in _coerce_header_mapping."""

    def test_valid_mapping(self):
        result = _coerce_header_mapping({"Content-Type": "application/json"}, "ctx")
        assert result == {"Content-Type": "application/json"}

    def test_empty_mapping(self):
        assert _coerce_header_mapping({}, "ctx") == {}

    def test_rejects_non_mapping(self):
        with pytest.raises(RuntimeError, match="Expected mapping-like transport attribute"):
            _coerce_header_mapping([("a", "b")], "ctx")

    def test_rejects_none(self):
        with pytest.raises(RuntimeError, match="Expected mapping-like transport attribute"):
            _coerce_header_mapping(None, "ctx")


class TestResponseAdapter:
    """Kill mutants in _ResponseAdapter property accessors."""

    def _make_response(self, **kwargs):
        resp = Mock()
        resp.status_code = kwargs.get("status_code", 200)
        resp.headers = kwargs.get("headers", {})
        resp.text = kwargs.get("text", "OK")
        resp.ok = kwargs.get("ok", True)
        resp.reason = kwargs.get("reason", "OK")
        resp.url = kwargs.get("url", "https://example.com")
        resp.content = kwargs.get("content", b"body")
        return resp

    def test_status_code(self):
        adapter = _ResponseAdapter(self._make_response(status_code=404))
        assert adapter.status_code == 404

    def test_text(self):
        adapter = _ResponseAdapter(self._make_response(text="response body"))
        assert adapter.text == "response body"

    def test_ok_true(self):
        adapter = _ResponseAdapter(self._make_response(ok=True))
        assert adapter.ok is True

    def test_ok_false(self):
        adapter = _ResponseAdapter(self._make_response(ok=False))
        assert adapter.ok is False

    def test_reason(self):
        adapter = _ResponseAdapter(self._make_response(reason="Not Found"))
        assert adapter.reason == "Not Found"

    def test_url(self):
        adapter = _ResponseAdapter(self._make_response(url="https://test.com"))
        assert adapter.url == "https://test.com"

    def test_url_missing_returns_none(self):
        resp = Mock(spec=[])
        adapter = _ResponseAdapter(resp)
        assert adapter.url is None

    def test_content_bytes(self):
        adapter = _ResponseAdapter(self._make_response(content=b"raw"))
        assert adapter.content == b"raw"

    def test_content_str(self):
        adapter = _ResponseAdapter(self._make_response(content="raw"))
        assert adapter.content == "raw"

    def test_headers(self):
        adapter = _ResponseAdapter(self._make_response(headers={"X-Key": "val"}))
        assert adapter.headers == {"X-Key": "val"}

    def test_iter_lines_yields_bytes_and_str(self):
        resp = self._make_response()
        resp.iter_lines.return_value = [b"line1", "line2"]
        adapter = _ResponseAdapter(resp)
        assert list(adapter.iter_lines()) == [b"line1", "line2"]

    def test_iter_lines_rejects_non_bytes_str(self):
        resp = self._make_response()
        resp.iter_lines.return_value = [123]
        adapter = _ResponseAdapter(resp)
        with pytest.raises(RuntimeError, match="Expected bytes or string lines"):
            list(adapter.iter_lines())

    def test_iter_lines_not_callable(self):
        resp = Mock(spec=[])
        adapter = _ResponseAdapter(resp)
        with pytest.raises(RuntimeError, match=r"Expected callable response\.iter_lines"):
            list(adapter.iter_lines())


class TestStreamContextAdapter:
    """Kill mutants in _StreamContextAdapter."""

    def test_enter_returns_response_adapter(self):
        inner = Mock()
        inner.__enter__ = Mock(return_value=Mock(status_code=200))
        adapter = _StreamContextAdapter(inner)
        result = adapter.__enter__()
        assert isinstance(result, _ResponseAdapter)

    def test_enter_raises_on_bad_context(self):
        inner = Mock(spec=[])
        adapter = _StreamContextAdapter(inner)
        with pytest.raises(RuntimeError, match="Expected __enter__ on stream context manager"):
            adapter.__enter__()

    def test_exit_returns_none(self):
        inner = Mock()
        inner.__exit__ = Mock(return_value=None)
        adapter = _StreamContextAdapter(inner)
        assert adapter.__exit__(None, None, None) is None

    def test_exit_returns_false(self):
        inner = Mock()
        inner.__exit__ = Mock(return_value=False)
        adapter = _StreamContextAdapter(inner)
        assert adapter.__exit__(None, None, None) is False

    def test_exit_returns_true(self):
        inner = Mock()
        inner.__exit__ = Mock(return_value=True)
        adapter = _StreamContextAdapter(inner)
        assert adapter.__exit__(None, None, None) is True

    def test_exit_rejects_non_bool(self):
        inner = Mock()
        inner.__exit__ = Mock(return_value="yes")
        adapter = _StreamContextAdapter(inner)
        with pytest.raises(RuntimeError, match="Expected bool-or-None return"):
            adapter.__exit__(None, None, None)

    def test_exit_raises_on_bad_context(self):
        inner = Mock(spec=[])
        adapter = _StreamContextAdapter(inner)
        with pytest.raises(RuntimeError, match="Expected __exit__ on stream context manager"):
            adapter.__exit__(None, None, None)


class TestRetryHandlerConsumeSleepAttempt:
    """Kill mutants in RetryHandler.consume_sleep_attempt."""

    def test_returns_none_initially(self):
        handler = RetryHandler(get_logger(), max_retries=3)
        assert handler.consume_sleep_attempt() is None

    def test_returns_and_clears(self):
        handler = RetryHandler(get_logger(), max_retries=3)
        handler._sleep_attempt = 2
        assert handler.consume_sleep_attempt() == 2
        assert handler.consume_sleep_attempt() is None


class TestRetryHandler401:
    """Kill mutants in 401 handling."""

    def test_401_raises_immediately(self):
        handler = RetryHandler(get_logger(), max_retries=5)
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.headers = {}
        error = PerplexityHTTPStatusError("unauth", request=Mock(), response=mock_response)
        with pytest.raises(PerplexityHTTPStatusError, match="Authentication failed"):
            handler.handle_http_error(error, attempt=0)


class TestRetryHandler403:
    """Kill mutants in 403 handling."""

    def test_403_retries_when_attempts_remain(self):
        handler = RetryHandler(get_logger(), max_retries=3)
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.headers = {}
        error = PerplexityHTTPStatusError("forbidden", request=Mock(), response=mock_response)
        wait = handler.handle_http_error(error, attempt=0)
        assert wait > 0

    def test_403_raises_on_last_attempt(self):
        handler = RetryHandler(get_logger(), max_retries=2)
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.headers = {}
        error = PerplexityHTTPStatusError("forbidden", request=Mock(), response=mock_response)
        with pytest.raises(PerplexityHTTPStatusError, match="Access forbidden"):
            handler.handle_http_error(error, attempt=1)

    def test_403_boundary_attempt_equals_max_minus_one(self):
        handler = RetryHandler(get_logger(), max_retries=1)
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.headers = {}
        error = PerplexityHTTPStatusError("forbidden", request=Mock(), response=mock_response)
        with pytest.raises(PerplexityHTTPStatusError, match="Access forbidden"):
            handler.handle_http_error(error, attempt=0)


class TestRetryHandler429:
    """Kill mutants in 429 handling."""

    def test_429_exhausted_raises_rate_limit(self):
        handler = RetryHandler(get_logger(), max_retries=1)
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {}
        error = PerplexityHTTPStatusError("rate limited", request=Mock(), response=mock_response)
        with pytest.raises(PerplexityHTTPStatusError, match="Rate limit exceeded"):
            handler._handle_retryable_error(error, attempt=0)

    def test_429_with_retries_remaining_returns_wait(self):
        handler = RetryHandler(get_logger(), max_retries=3)
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {}
        error = PerplexityHTTPStatusError("rate limited", request=Mock(), response=mock_response)
        wait = handler._handle_retryable_error(error, attempt=0)
        assert wait > 0


class TestRetryHandlerNetworkError:
    """Kill mutants in handle_network_error."""

    def test_non_retryable_non_curl_raises_original(self):
        handler = RetryHandler(get_logger(), max_retries=3)
        error = ValueError("not retryable")
        with pytest.raises(ValueError, match="not retryable"):
            handler.handle_network_error(error, attempt=0)

    def test_retryable_increments_attempt(self):
        handler = RetryHandler(get_logger(), max_retries=3)
        error = PerplexityRequestError("timeout")
        result = handler.handle_network_error(error, attempt=1)
        assert result == 2

    def test_exhausted_raises(self):
        handler = RetryHandler(get_logger(), max_retries=2)
        error = PerplexityRequestError("timeout")
        with pytest.raises(PerplexityRequestError):
            handler.handle_network_error(error, attempt=1)


class TestSSEParserDecodeLine:
    """Kill mutants in SSEParser._decode_line."""

    def test_decodes_bytes(self):
        assert SSEParser._decode_line(b"hello") == "hello"

    def test_passes_string(self):
        assert SSEParser._decode_line("hello") == "hello"

    def test_decodes_empty_bytes(self):
        assert SSEParser._decode_line(b"") == ""

    def test_passes_empty_string(self):
        assert SSEParser._decode_line("") == ""


class TestSSEParserParseLine:
    """Kill mutants in SSEParser._parse_line."""

    def test_event_line(self):
        event_type, data_lines = SSEParser._parse_line("event: message", None, [])
        assert event_type == "message"
        assert data_lines == []

    def test_data_line(self):
        event_type, data_lines = SSEParser._parse_line('data: {"key": "val"}', "msg", [])
        assert event_type == "msg"
        assert data_lines == ['{"key": "val"}']

    def test_unknown_line_ignored(self):
        event_type, data_lines = SSEParser._parse_line("id: 123", "msg", ["prev"])
        assert event_type == "msg"
        assert data_lines == ["prev"]

    def test_event_line_strips_whitespace(self):
        event_type, _ = SSEParser._parse_line("event:   spaced  ", None, [])
        assert event_type == "spaced"

    def test_data_line_strips_whitespace(self):
        _, data_lines = SSEParser._parse_line("data:   padded  ", "msg", [])
        assert data_lines == ["padded"]


class TestSSEParserAccumulateLine:
    """Kill mutants in SSEParser._accumulate_line."""

    def test_empty_line_with_event_and_data_yields(self):
        event_type, data_lines, event = SSEParser._accumulate_line("", "message", ['{"a": 1}'])
        assert event_type is None
        assert data_lines == []
        assert event == {"a": 1}

    def test_empty_line_without_event_returns_none(self):
        event_type, data_lines, event = SSEParser._accumulate_line("", None, ['{"a": 1}'])
        assert event is None
        assert event_type is None
        assert data_lines == []

    def test_empty_line_without_data_returns_none(self):
        event_type, data_lines, event = SSEParser._accumulate_line("", "message", [])
        assert event is None

    def test_non_empty_line_returns_none_event(self):
        event_type, data_lines, event = SSEParser._accumulate_line("event: msg", None, [])
        assert event is None
        assert event_type == "msg"


class TestSSEParserYieldEvent:
    """Kill mutants in SSEParser._yield_event."""

    def test_joins_multiline_data(self):
        result = SSEParser._yield_event(['{"a":', '"b"}'])
        assert result == {"a": "b"}

    def test_invalid_json_raises(self):
        with pytest.raises(UpstreamSchemaError, match="Failed to parse SSE data as JSON"):
            SSEParser._yield_event(["{invalid}"])

    def test_non_object_raises(self):
        with pytest.raises(UpstreamSchemaError, match="must decode to a JSON object"):
            SSEParser._yield_event(["[1, 2, 3]"])

    def test_truncates_long_data_in_error(self):
        long_data = "x" * 200
        with pytest.raises(UpstreamSchemaError, match="Failed to parse SSE data as JSON"):
            SSEParser._yield_event([long_data])


class TestSSEClientSleepForRetry:
    """Kill mutants in SSEClient._sleep_for_retry."""

    def test_uses_backoff_when_sleep_attempt_set(self):
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=3)
        client._retry._sleep_attempt = 1
        with patch("perplexity_cli.api.client.sleep_with_backoff") as mock_sleep:
            client._sleep_for_retry(5.0)
            mock_sleep.assert_called_once_with(1)

    def test_uses_event_wait_when_no_sleep_attempt(self):
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=3)
        client._retry._sleep_attempt = None
        with patch("perplexity_cli.api.client.threading.Event") as mock_event:
            mock_instance = Mock()
            mock_event.return_value = mock_instance
            client._sleep_for_retry(2.5)
            mock_instance.wait.assert_called_once_with(2.5)


class TestSSEClientRetryStreamError:
    """Kill mutants in SSEClient._retry_stream_error."""

    def test_http_error_returns_incremented_attempt(self):
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=3)
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.headers = {}
        error = PerplexityHTTPStatusError("err", request=Mock(), response=mock_response)
        with patch.object(client, "_sleep_for_retry"):
            result = client._retry_stream_error(error, attempt=0)
        assert result == 1

    def test_request_error_delegates_to_network_handler(self):
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=3)
        error = PerplexityRequestError("timeout")
        result = client._retry_stream_error(error, attempt=0)
        assert result == 1

    def test_unknown_error_reraises(self):
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=3)
        error = ValueError("unknown")
        with pytest.raises(ValueError, match="unknown"):
            client._retry_stream_error(error, attempt=0)


class TestSSEClientResolveEffectiveTimeout:
    """Kill mutants in _resolve_effective_timeout edge cases."""

    def test_no_params_key(self):
        client = SSEClient(auth=AuthContext(token="tok"), timeout=30)
        is_deep, timeout = client._resolve_effective_timeout({})
        assert is_deep is False
        assert timeout == 30

    def test_params_not_dict(self):
        client = SSEClient(auth=AuthContext(token="tok"), timeout=30)
        is_deep, timeout = client._resolve_effective_timeout({"params": "not-a-dict"})
        assert is_deep is False
        assert timeout == 30

    def test_deep_research_uses_360(self):
        client = SSEClient(auth=AuthContext(token="tok"), timeout=30)
        is_deep, timeout = client._resolve_effective_timeout(
            {"params": {"search_implementation_mode": "multi_step"}}
        )
        assert is_deep is True
        assert timeout == 360


class TestIsJsonObject:
    """Kill mutants in _is_json_object."""

    def test_dict_is_json_object(self):
        assert _is_json_object({}) is True

    def test_list_is_not(self):
        assert _is_json_object([]) is False

    def test_none_is_not(self):
        assert _is_json_object(None) is False

    def test_string_is_not(self):
        assert _is_json_object("str") is False


# ---------------------------------------------------------------------------
# api/models.py – Block extraction and model edge cases
# ---------------------------------------------------------------------------


class TestAsObjectDict:
    """Kill mutants in _as_object_dict."""

    def test_returns_dict(self):
        assert _as_object_dict({"a": 1}) == {"a": 1}

    def test_returns_none_for_list(self):
        assert _as_object_dict([1]) is None

    def test_returns_none_for_string(self):
        assert _as_object_dict("str") is None

    def test_returns_none_for_none(self):
        assert _as_object_dict(None) is None

    def test_returns_empty_dict(self):
        assert _as_object_dict({}) == {}


class TestAsObjectList:
    """Kill mutants in _as_object_list."""

    def test_returns_list(self):
        assert _as_object_list([1, 2]) == [1, 2]

    def test_returns_none_for_dict(self):
        assert _as_object_list({"a": 1}) is None

    def test_returns_none_for_string(self):
        assert _as_object_list("str") is None

    def test_returns_empty_list(self):
        assert _as_object_list([]) == []


class TestBlockExtractText:
    """Kill mutants in Block.extract_text paths."""

    def test_web_result_block_returns_none(self):
        block = Block(intended_usage="web_results", content={"web_result_block": {}})
        assert block.extract_text() is None

    def test_text_field(self):
        block = Block(intended_usage="ask_text", content={"text": "direct text"})
        assert block.extract_text() == "direct text"

    def test_diff_block_with_string_value(self):
        block = Block(
            intended_usage="ask_text",
            content={"diff_block": {"patches": [{"value": "patch text"}]}},
        )
        assert block.extract_text() == "patch text"

    def test_diff_block_with_nested_text(self):
        block = Block(
            intended_usage="ask_text",
            content={"diff_block": {"patches": [{"value": {"text": "nested"}}]}},
        )
        assert block.extract_text() == "nested"

    def test_diff_block_no_patches(self):
        block = Block(intended_usage="ask_text", content={"diff_block": {}})
        assert block.extract_text() is None

    def test_diff_block_empty_patches(self):
        block = Block(intended_usage="ask_text", content={"diff_block": {"patches": []}})
        assert block.extract_text() is None

    def test_diff_block_patch_not_dict(self):
        block = Block(
            intended_usage="ask_text",
            content={"diff_block": {"patches": ["not-a-dict"]}},
        )
        assert block.extract_text() is None

    def test_diff_block_patch_value_not_str_or_dict(self):
        block = Block(
            intended_usage="ask_text",
            content={"diff_block": {"patches": [{"value": 42}]}},
        )
        assert block.extract_text() is None

    def test_answer_block(self):
        block = Block(
            intended_usage="ask_text",
            content={"answer_block": {"text": "answer text"}},
        )
        assert block.extract_text() == "answer text"

    def test_answer_block_no_text(self):
        block = Block(intended_usage="ask_text", content={"answer_block": {}})
        assert block.extract_text() is None

    def test_answer_block_text_not_str(self):
        block = Block(intended_usage="ask_text", content={"answer_block": {"text": 42}})
        assert block.extract_text() is None

    def test_no_matching_extractor(self):
        block = Block(intended_usage="ask_text", content={"unknown_field": "val"})
        assert block.extract_text() is None

    def test_markdown_block_no_chunks(self):
        block = Block(intended_usage="ask_text", content={"markdown_block": {}})
        assert block.extract_text() is None

    def test_markdown_block_chunks_not_list(self):
        block = Block(intended_usage="ask_text", content={"markdown_block": {"chunks": "str"}})
        assert block.extract_text() is None

    def test_text_field_not_str(self):
        block = Block(intended_usage="ask_text", content={"text": 42})
        assert block.extract_text() is None


class TestBlockExtractPlanInfo:
    """Kill mutants in Block.extract_plan_info."""

    def test_non_plan_usage_returns_none(self):
        block = Block(intended_usage="ask_text", content={"plan_block": {"progress": "x"}})
        assert block.extract_plan_info() is None

    def test_pro_search_steps_usage(self):
        block = Block(
            intended_usage="pro_search_steps",
            content={"plan_block": {"progress": "Searching", "eta_seconds_remaining": 10}},
        )
        result = block.extract_plan_info()
        assert result is not None
        assert result["progress"] == "Searching"
        assert result["eta_seconds"] == 10

    def test_empty_plan_block_returns_none(self):
        block = Block(intended_usage="plan", content={"plan_block": {}})
        assert block.extract_plan_info() is None

    def test_no_plan_block_returns_none(self):
        block = Block(intended_usage="plan", content={})
        assert block.extract_plan_info() is None

    def test_goals_default_empty_list(self):
        block = Block(
            intended_usage="plan",
            content={"plan_block": {"progress": "x"}},
        )
        result = block.extract_plan_info()
        assert result is not None
        assert result["goals"] == []


class TestBlockExtractWebResults:
    """Kill mutants in Block.extract_web_results."""

    def test_non_web_results_usage(self):
        block = Block(intended_usage="ask_text", content={"web_result_block": {}})
        assert block.extract_web_results() is None

    def test_no_web_result_block(self):
        block = Block(intended_usage="web_results", content={})
        assert block.extract_web_results() is None

    def test_no_web_results_key(self):
        block = Block(intended_usage="web_results", content={"web_result_block": {}})
        assert block.extract_web_results() is None

    def test_web_results_not_list(self):
        block = Block(
            intended_usage="web_results",
            content={"web_result_block": {"web_results": "not-a-list"}},
        )
        assert block.extract_web_results() is None


class TestSSEMessageDescribeBlockUsages:
    """Kill mutants in SSEMessage.describe_block_usages."""

    def test_no_blocks(self):
        msg = SSEMessage.model_validate({"blocks": []})
        assert msg.describe_block_usages() == "none"

    def test_single_block(self):
        msg = SSEMessage.model_validate({"blocks": [{"intended_usage": "ask_text"}]})
        assert msg.describe_block_usages() == "ask_text"

    def test_multiple_blocks(self):
        msg = SSEMessage.model_validate(
            {"blocks": [{"intended_usage": "ask_text"}, {"intended_usage": "web_results"}]}
        )
        assert msg.describe_block_usages() == "ask_text,web_results"

    def test_empty_usage_shows_missing(self):
        msg = SSEMessage.model_validate({"blocks": [{"intended_usage": ""}]})
        assert msg.describe_block_usages() == "<missing>"


class TestSSEMessageExtractAnswerText:
    """Kill mutants in SSEMessage.extract_answer_text."""

    def test_skips_non_ask_text_blocks(self):
        msg = SSEMessage.model_validate(
            {
                "blocks": [
                    {"intended_usage": "web_results", "text": "not this"},
                    {"intended_usage": "ask_text", "text": "this one"},
                ]
            }
        )
        assert msg.extract_answer_text() == "this one"

    def test_returns_none_when_no_ask_text(self):
        msg = SSEMessage.model_validate(
            {"blocks": [{"intended_usage": "web_results", "text": "nope"}]}
        )
        assert msg.extract_answer_text() is None

    def test_returns_none_when_no_blocks(self):
        msg = SSEMessage.model_validate({"blocks": []})
        assert msg.extract_answer_text() is None


class TestQueryParamsValidation:
    """Kill mutants in QueryParams.validate_search_mode."""

    def test_standard_valid(self):
        params = QueryParams(search_implementation_mode="standard")
        assert params.search_implementation_mode == "standard"

    def test_multi_step_valid(self):
        params = QueryParams(search_implementation_mode="multi_step")
        assert params.search_implementation_mode == "multi_step"

    def test_invalid_mode_raises(self):
        with pytest.raises(
            ValueError, match='search_implementation_mode must be "standard" or "multi_step"'
        ):
            QueryParams(search_implementation_mode="invalid")


class TestQueryInput:
    """Kill mutants in QueryInput defensive copies."""

    def test_attachment_urls_copied(self):
        original = ["url1"]
        qi = QueryInput(query="q", attachment_urls=original)
        original.append("url2")
        assert qi.attachment_urls == ["url1"]

    def test_request_params_copied(self):
        original = {"key": "val"}
        qi = QueryInput(query="q", request_params=original)
        original["key2"] = "val2"
        assert qi.request_params == {"key": "val"}

    def test_none_attachment_urls(self):
        qi = QueryInput(query="q", attachment_urls=None)
        assert qi.attachment_urls == []

    def test_none_request_params(self):
        qi = QueryInput(query="q", request_params=None)
        assert qi.request_params == {}


class TestWebResultValidation:
    """Kill mutants in WebResult pre-validator."""

    def test_rejects_non_mapping(self):
        with pytest.raises(UpstreamSchemaError, match="Malformed web result"):
            WebResult.model_validate("not a dict")

    def test_rejects_list(self):
        with pytest.raises(UpstreamSchemaError, match="Malformed web result"):
            WebResult.model_validate(["not", "a", "dict"])


class TestSSEMessageValidation:
    """Kill mutants in SSEMessage pre-validator."""

    def test_rejects_non_mapping(self):
        with pytest.raises(UpstreamSchemaError, match="Malformed SSE message"):
            SSEMessage.model_validate("not a dict")

    def test_rejects_non_list_blocks(self):
        with pytest.raises(UpstreamSchemaError, match="Malformed SSE blocks"):
            SSEMessage.model_validate({"blocks": "not-a-list"})


# ---------------------------------------------------------------------------
# threads/scraper.py – module-level helpers
# ---------------------------------------------------------------------------


class TestResponseCoreMembers:
    """Kill mutants in _response_core_members."""

    def test_returns_ok_and_json(self):
        resp = Mock()
        resp.ok = True
        resp.json = Mock()
        result = _response_core_members(resp)
        assert result is not None
        assert result[0] is True

    def test_returns_none_on_attribute_error(self):
        resp = Mock(spec=[])
        assert _response_core_members(resp) is None


class TestHasIntegerStatusCode:
    """Kill mutants in _has_integer_status_code."""

    def test_true_for_int(self):
        resp = Mock()
        resp.status_code = 200
        assert _has_integer_status_code(resp) is True

    def test_false_for_string(self):
        resp = Mock()
        resp.status_code = "200"
        assert _has_integer_status_code(resp) is False

    def test_false_on_attribute_error(self):
        resp = Mock(spec=[])
        assert _has_integer_status_code(resp) is False


class TestIsResponseProtocol:
    """Kill mutants in _is_response_protocol."""

    def test_valid_ok_response(self):
        resp = Mock()
        resp.ok = True
        resp.json = Mock()
        assert _is_response_protocol(resp) is True

    def test_not_ok_with_int_status(self):
        resp = Mock()
        resp.ok = False
        resp.status_code = 500
        resp.json = Mock()
        assert _is_response_protocol(resp) is True

    def test_not_ok_without_int_status(self):
        resp = Mock()
        resp.ok = False
        resp.status_code = "500"
        resp.json = Mock()
        assert _is_response_protocol(resp) is False

    def test_ok_not_bool(self):
        resp = Mock()
        resp.ok = "yes"
        resp.json = Mock()
        assert _is_response_protocol(resp) is False

    def test_json_not_callable(self):
        resp = Mock()
        resp.ok = True
        resp.json = "not callable"
        assert _is_response_protocol(resp) is False

    def test_missing_members(self):
        resp = Mock(spec=[])
        assert _is_response_protocol(resp) is False


class TestGetCacheStrField:
    """Kill mutants in _get_cache_str_field."""

    def test_returns_string(self):
        assert _get_cache_str_field({"title": "Test"}, "title") == "Test"

    def test_raises_on_missing(self):
        with pytest.raises(UpstreamSchemaError, match="missing title"):
            _get_cache_str_field({}, "title")

    def test_raises_on_non_string(self):
        with pytest.raises(UpstreamSchemaError, match="missing url"):
            _get_cache_str_field({"url": 42}, "url")


class TestExtractCacheThreadDicts:
    """Kill mutants in _extract_cache_thread_dicts."""

    def test_valid_entries(self):
        result = _extract_cache_thread_dicts([{"title": "T", "url": "U"}])
        assert len(result) == 1
        assert result[0]["title"] == "T"

    def test_rejects_non_list(self):
        with pytest.raises(UpstreamSchemaError, match="Malformed cached thread records"):
            _extract_cache_thread_dicts("not a list")

    def test_rejects_non_mapping_entry(self):
        with pytest.raises(UpstreamSchemaError, match="Malformed cached thread records"):
            _extract_cache_thread_dicts(["not a dict"])

    def test_empty_list(self):
        assert _extract_cache_thread_dicts([]) == []


class TestCoerceOptionalStr:
    """Kill mutants in _coerce_optional_str."""

    def test_none(self):
        assert _coerce_optional_str(None, "field") is None

    def test_string(self):
        assert _coerce_optional_str("value", "field") == "value"

    def test_empty_string(self):
        assert _coerce_optional_str("", "field") == ""

    def test_rejects_int(self):
        with pytest.raises(TypeError, match="field must be a string or None"):
            _coerce_optional_str(42, "field")


class TestCoerceOptionalInt:
    """Kill mutants in _coerce_optional_int."""

    def test_none(self):
        assert _coerce_optional_int(None, "field") is None

    def test_int(self):
        assert _coerce_optional_int(42, "field") == 42

    def test_zero(self):
        assert _coerce_optional_int(0, "field") == 0

    def test_rejects_string(self):
        with pytest.raises(TypeError, match="field must be an integer or None"):
            _coerce_optional_int("42", "field")


class TestCoerceProgressCallback:
    """Kill mutants in _coerce_progress_callback."""

    def test_none(self):
        assert _coerce_progress_callback(None) is None

    def test_callable(self):
        def cb(current, total):
            return None

        assert _coerce_progress_callback(cb) is cb

    def test_rejects_non_callable(self):
        with pytest.raises(TypeError, match="progress_callback must be callable or None"):
            _coerce_progress_callback("not callable")


class TestValidateBatchProcessingArgCount:
    """Kill mutants in _validate_batch_processing_arg_count."""

    def test_three_args_ok(self):
        _validate_batch_processing_arg_count(3)

    def test_four_args_raises(self):
        with pytest.raises(TypeError, match="expected at most three"):
            _validate_batch_processing_arg_count(4)

    def test_zero_args_ok(self):
        _validate_batch_processing_arg_count(0)


class TestLegacyContextValue:
    """Kill mutants in _legacy_context_value."""

    def test_present(self):
        assert _legacy_context_value(("a", "b", "c"), 1) == "b"

    def test_absent(self):
        assert _legacy_context_value(("a",), 5) is None

    def test_index_zero(self):
        assert _legacy_context_value(("first",), 0) == "first"

    def test_empty_tuple(self):
        assert _legacy_context_value((), 0) is None


class TestBuildBatchProcessingContext:
    """Kill mutants in _build_batch_processing_context."""

    def test_no_args(self):
        ctx = _build_batch_processing_context()
        assert ctx.from_date is None
        assert ctx.total_threads is None
        assert ctx.progress_callback is None

    def test_context_object_passthrough(self):
        original = BatchProcessingContext(from_date="2025-01-01")
        ctx = _build_batch_processing_context(original)
        assert ctx is original

    def test_legacy_args(self):
        ctx = _build_batch_processing_context("2025-01-01", 100, None)
        assert ctx.from_date == "2025-01-01"
        assert ctx.total_threads == 100
        assert ctx.progress_callback is None


class TestRequireResponse:
    """Kill mutants in _require_response."""

    def test_valid_response(self):
        resp = Mock()
        resp.ok = True
        resp.json = Mock()
        assert _require_response(resp) is resp

    def test_invalid_response_raises(self):
        resp = Mock(spec=[])
        with pytest.raises(UpstreamSchemaError, match="Malformed HTTP response"):
            _require_response(resp)


class TestValidateDateParams:
    """Kill mutants in _validate_date_params."""

    def test_valid_dates(self):
        _validate_date_params("2025-01-01", "2025-12-31")

    def test_none_dates(self):
        _validate_date_params(None, None)

    def test_invalid_from_date(self):
        with pytest.raises(ValueError, match="Invalid from_date"):
            _validate_date_params("not-a-date", None)

    def test_invalid_to_date(self):
        with pytest.raises(ValueError, match="Invalid to_date"):
            _validate_date_params(None, "not-a-date")


class TestGetStrField:
    """Kill mutants in _get_str_field."""

    def test_returns_value(self):
        assert _get_str_field({"title": "Test"}, "title") == "Test"

    def test_returns_default(self):
        assert _get_str_field({}, "title", "Untitled") == "Untitled"

    def test_raises_on_non_string(self):
        with pytest.raises(UpstreamSchemaError, match="Malformed thread title"):
            _get_str_field({"title": 42}, "title")

    def test_raises_on_missing_no_default(self):
        with pytest.raises(UpstreamSchemaError, match="Malformed thread title"):
            _get_str_field({}, "title")


class TestParseSingleThread:
    """Kill mutants in _parse_single_thread."""

    def test_valid_thread(self):
        thread_dict = {
            "last_query_datetime": "2025-06-15T12:00:00+00:00",
            "slug": "test-slug",
            "title": "Test Thread",
        }
        record, should_stop = _parse_single_thread(thread_dict, None)
        assert should_stop is False
        assert record is not None
        assert record.title == "Test Thread"
        assert "test-slug" in record.url

    def test_empty_timestamp_raises(self):
        thread_dict = {"last_query_datetime": "", "slug": "s", "title": "T"}
        with pytest.raises(UpstreamSchemaError, match="Malformed thread timestamp"):
            _parse_single_thread(thread_dict, None)

    def test_old_thread_signals_stop(self):
        thread_dict = {
            "last_query_datetime": "2020-01-01T00:00:00+00:00",
            "slug": "old",
            "title": "Old",
        }
        record, should_stop = _parse_single_thread(thread_dict, "2025-01-01")
        assert should_stop is True
        assert record is None

    def test_default_slug_and_title(self):
        thread_dict = {"last_query_datetime": "2025-06-15T12:00:00+00:00"}
        record, should_stop = _parse_single_thread(thread_dict, None)
        assert should_stop is False
        assert record is not None
        assert record.title == "Untitled"


class TestHasMorePages:
    """Kill mutants in _has_more_pages."""

    def test_empty_list(self):
        assert _has_more_pages([]) is False

    def test_has_next_page_true(self):
        assert _has_more_pages([{"has_next_page": True}]) is True

    def test_has_next_page_false(self):
        assert _has_more_pages([{"has_next_page": False}]) is False

    def test_missing_key(self):
        assert _has_more_pages([{"other": "val"}]) is False


class TestReportProgress:
    """Kill mutants in _report_progress."""

    def test_calls_callback(self):
        cb = Mock()
        _report_progress(cb, 5, 10)
        cb.assert_called_once_with(5, 10)

    def test_no_callback(self):
        _report_progress(None, 5, 10)

    def test_no_total(self):
        cb = Mock()
        _report_progress(cb, 5, None)
        cb.assert_not_called()

    def test_zero_total(self):
        cb = Mock()
        _report_progress(cb, 5, 0)
        cb.assert_not_called()


# ---------------------------------------------------------------------------
# threads/cache_manager.py – edge cases
# ---------------------------------------------------------------------------


class TestCacheManagerValidateOuterFormat:
    """Kill mutants in _validate_outer_format."""

    def test_not_encrypted_raises(self, cache_manager):
        with pytest.raises(Exception, match="not encrypted"):
            cache_manager._validate_outer_format(
                {
                    "version": 1,
                    "encrypted": False,
                    "cache": "data",
                    "created_at": "2025-01-01T00:00:00",
                }
            )

    def test_empty_cache_raises(self, cache_manager):
        with pytest.raises(Exception, match="Cache file has invalid format"):
            cache_manager._validate_outer_format(
                {"version": 1, "encrypted": True, "cache": "", "created_at": "2025-01-01T00:00:00"}
            )

    def test_whitespace_cache_raises(self, cache_manager):
        with pytest.raises(Exception, match="Cache file has invalid format"):
            cache_manager._validate_outer_format(
                {
                    "version": 1,
                    "encrypted": True,
                    "cache": "   ",
                    "created_at": "2025-01-01T00:00:00",
                }
            )


class TestCacheManagerBuildMetadata:
    """Kill mutants in _build_cache_metadata."""

    def test_empty_threads(self, cache_manager):
        metadata = cache_manager._build_cache_metadata([])
        assert metadata["total_threads"] == 0
        assert metadata["oldest_thread_date"] is None
        assert metadata["newest_thread_date"] is None

    def test_single_thread(self, cache_manager):
        threads = [ThreadRecord(title="T", url="U", created_at="2025-06-15T12:00:00Z")]
        metadata = cache_manager._build_cache_metadata(threads)
        assert metadata["total_threads"] == 1
        assert metadata["oldest_thread_date"] == "2025-06-15T12:00:00Z"
        assert metadata["newest_thread_date"] == "2025-06-15T12:00:00Z"

    def test_multiple_threads_uses_first_and_last(self, cache_manager):
        threads = [
            ThreadRecord(title="New", url="U1", created_at="2025-12-25T00:00:00Z"),
            ThreadRecord(title="Mid", url="U2", created_at="2025-12-20T00:00:00Z"),
            ThreadRecord(title="Old", url="U3", created_at="2025-12-15T00:00:00Z"),
        ]
        metadata = cache_manager._build_cache_metadata(threads)
        assert metadata["newest_thread_date"] == "2025-12-25T00:00:00Z"
        assert metadata["oldest_thread_date"] == "2025-12-15T00:00:00Z"
        assert metadata["total_threads"] == 3


class TestCalculateFetchRange:
    """Kill mutants in _calculate_fetch_range."""

    def test_no_fetch_needed(self):
        from datetime import date

        needs, fetch_from, fetch_to = ThreadCacheManager._calculate_fetch_range(
            date(2025, 6, 10), date(2025, 6, 20), date(2025, 6, 1), date(2025, 6, 30)
        )
        assert needs is False
        assert fetch_from is None
        assert fetch_to is None

    def test_needs_older(self):
        from datetime import date

        needs, fetch_from, fetch_to = ThreadCacheManager._calculate_fetch_range(
            date(2025, 5, 1), date(2025, 6, 20), date(2025, 6, 1), date(2025, 6, 30)
        )
        assert needs is True
        assert fetch_from == "2025-05-01"
        assert fetch_to == "2025-06-20"

    def test_needs_newer(self):
        from datetime import date

        needs, fetch_from, fetch_to = ThreadCacheManager._calculate_fetch_range(
            date(2025, 6, 10), date(2025, 7, 15), date(2025, 6, 1), date(2025, 6, 30)
        )
        assert needs is True
        assert fetch_from == "2025-06-30"
        assert fetch_to == "2025-07-15"

    def test_request_to_equals_cache_newest(self):
        from datetime import date

        needs, _, _ = ThreadCacheManager._calculate_fetch_range(
            date(2025, 6, 10), date(2025, 6, 30), date(2025, 6, 1), date(2025, 6, 30)
        )
        assert needs is True


class TestCacheManagerGetCoverageError:
    """Kill mutants in get_cache_coverage error path."""

    def test_returns_none_on_configuration_error(self, cache_manager):
        cache_manager.cache_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "encrypted": False,
                    "cache": "x",
                    "created_at": "2025-01-01T00:00:00",
                }
            ),
            encoding="utf-8",
        )
        os.chmod(cache_manager.cache_path, 0o600)
        oldest, newest = cache_manager.get_cache_coverage()
        assert oldest is None
        assert newest is None


class TestCacheManagerSaveAndLoadRoundtrip:
    """Kill mutants in save_cache/load_cache roundtrip."""

    def test_save_empty_threads(self, cache_manager):
        cache_manager.save_cache([])
        loaded = cache_manager.load_cache()
        assert loaded is not None
        assert loaded["threads"] == []
        assert loaded["metadata"]["total_threads"] == 0

    def test_save_with_custom_metadata(self, cache_manager):
        threads = [ThreadRecord(title="T", url="U", created_at="2025-06-15T12:00:00Z")]
        custom_meta = {
            "last_sync_time": "2025-06-15T12:00:00Z",
            "oldest_thread_date": "2025-06-15T12:00:00Z",
            "newest_thread_date": "2025-06-15T12:00:00Z",
            "total_threads": 1,
        }
        cache_manager.save_cache(threads, metadata=custom_meta)
        loaded = cache_manager.load_cache()
        assert loaded["metadata"]["total_threads"] == 1


class TestCacheManagerClearCache:
    """Kill mutants in clear_cache."""

    def test_clear_nonexistent_is_safe(self, cache_manager):
        cache_manager.clear_cache()
        assert not cache_manager.cache_exists()

    def test_clear_existing(self, cache_manager):
        cache_manager.save_cache(
            [ThreadRecord(title="T", url="U", created_at="2025-01-01T00:00:00Z")]
        )
        assert cache_manager.cache_exists()
        cache_manager.clear_cache()
        assert not cache_manager.cache_exists()


# ---------------------------------------------------------------------------
# threads/date_parser.py – boundary conditions
# ---------------------------------------------------------------------------


class TestParseDayStart:
    """Kill mutants in _parse_day_start."""

    def test_sets_midnight(self):
        result = _parse_day_start("2025-06-15", UTC)
        assert result.hour == 0
        assert result.minute == 0
        assert result.second == 0
        assert result.microsecond == 0

    def test_preserves_date(self):
        result = _parse_day_start("2025-06-15", UTC)
        assert result.year == 2025
        assert result.month == 6
        assert result.day == 15


class TestParseDayEnd:
    """Kill mutants in _parse_day_end."""

    def test_sets_end_of_day(self):
        result = _parse_day_end("2025-06-15", UTC)
        assert result.hour == 23
        assert result.minute == 59
        assert result.second == 59
        assert result.microsecond == 999999

    def test_preserves_date(self):
        result = _parse_day_end("2025-12-31", UTC)
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 31


class TestCheckAfterStart:
    """Kill mutants in _check_after_start."""

    def test_none_from_date(self):
        dt = datetime(2025, 1, 1, tzinfo=UTC)
        assert _check_after_start(dt, None) is True

    def test_on_boundary(self):
        dt = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        assert _check_after_start(dt, "2025-06-01") is True

    def test_before_boundary(self):
        dt = datetime(2025, 5, 31, 23, 59, 59, tzinfo=UTC)
        assert _check_after_start(dt, "2025-06-01") is False


class TestCheckBeforeEnd:
    """Kill mutants in _check_before_end."""

    def test_none_to_date(self):
        dt = datetime(2025, 12, 31, tzinfo=UTC)
        assert _check_before_end(dt, None) is True

    def test_on_boundary(self):
        dt = datetime(2025, 6, 30, 23, 59, 59, 999999, tzinfo=UTC)
        assert _check_before_end(dt, "2025-06-30") is True

    def test_after_boundary(self):
        dt = datetime(2025, 7, 1, 0, 0, 0, tzinfo=UTC)
        assert _check_before_end(dt, "2025-06-30") is False


class TestToIso8601EdgeCases:
    """Kill mutants in to_iso8601 edge cases."""

    def test_negative_offset_timezone(self):
        from datetime import timedelta

        tz_minus5 = timezone(timedelta(hours=-5))
        dt = datetime(2025, 7, 20, 10, 0, 0, tzinfo=tz_minus5)
        result = to_iso8601(dt)
        assert result == "2025-07-20T15:00:00Z"

    def test_already_utc_no_double_conversion(self):
        dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = to_iso8601(dt)
        assert result == "2025-01-01T12:00:00Z"


# ---------------------------------------------------------------------------
# threads/exporter.py – CSV export edge cases
# ---------------------------------------------------------------------------


class TestWriteThreadsCsv:
    """Kill mutants in write_threads_csv."""

    def test_empty_records_raises(self):
        with pytest.raises(ValueError, match="Cannot write CSV with empty records list"):
            write_threads_csv([])

    def test_writes_correct_csv(self, tmp_path):
        records = [
            ThreadRecord(
                title="Thread 1", url="https://example.com/1", created_at="2025-01-01T00:00:00Z"
            ),
        ]
        output = tmp_path / "out.csv"
        result = write_threads_csv(records, output_path=output)
        assert result == output
        content = output.read_text()
        lines = content.strip().split("\n")
        assert lines[0] == "created_at,title,url"
        assert "2025-01-01T00:00:00Z" in lines[1]
        assert "Thread 1" in lines[1]

    def test_multiple_records_order(self, tmp_path):
        records = [
            ThreadRecord(
                title="First", url="https://example.com/1", created_at="2025-01-02T00:00:00Z"
            ),
            ThreadRecord(
                title="Second", url="https://example.com/2", created_at="2025-01-01T00:00:00Z"
            ),
        ]
        output = tmp_path / "out.csv"
        write_threads_csv(records, output_path=output)
        content = output.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 3
        assert "First" in lines[1]
        assert "Second" in lines[2]


# ---------------------------------------------------------------------------
# threads/models.py – validation edge cases
# ---------------------------------------------------------------------------


class TestDateRange:
    """Kill mutants in DateRange dataclass."""

    def test_defaults(self):
        dr = DateRange()
        assert dr.from_date is None
        assert dr.to_date is None

    def test_with_values(self):
        dr = DateRange(from_date="2025-01-01", to_date="2025-12-31")
        assert dr.from_date == "2025-01-01"
        assert dr.to_date == "2025-12-31"


class TestCacheMetadataValidation:
    """Kill mutants in CacheMetadata validators."""

    def test_future_sync_time_raises(self):
        future = datetime(2099, 1, 1, tzinfo=UTC)
        with pytest.raises(ValueError, match="last_sync_time cannot be in the future"):
            CacheMetadata(last_sync_time=future)

    def test_negative_total_threads_raises(self):
        with pytest.raises(ValueError):
            CacheMetadata(
                last_sync_time=datetime(2025, 1, 1, tzinfo=UTC),
                total_threads=-1,
            )

    def test_zero_total_threads_ok(self):
        meta = CacheMetadata(
            last_sync_time=datetime(2025, 1, 1, tzinfo=UTC),
            total_threads=0,
        )
        assert meta.total_threads == 0


class TestCacheFormatValidation:
    """Kill mutants in CacheFormat validators."""

    def test_empty_cache_raises(self):
        with pytest.raises(ValueError):
            CacheFormat(cache="   ")

    def test_valid_cache(self):
        fmt = CacheFormat(cache="encrypted-data")
        assert fmt.encrypted is True
        assert fmt.version == 1


class TestCacheContentValidation:
    """Kill mutants in CacheContent validators."""

    def test_thread_without_url_raises(self):
        with pytest.raises(ValueError, match="must have a 'url' field"):
            CacheContent(
                version=1,
                metadata=CacheMetadata(last_sync_time=datetime(2025, 1, 1, tzinfo=UTC)),
                threads=[{"title": "T"}],
            )

    def test_thread_without_title_raises(self):
        with pytest.raises(ValueError, match="must have a 'title' field"):
            CacheContent(
                version=1,
                metadata=CacheMetadata(last_sync_time=datetime(2025, 1, 1, tzinfo=UTC)),
                threads=[{"url": "U"}],
            )

    def test_thread_not_dict_raises(self):
        with pytest.raises((ValueError, Exception), match=r"dictionary|dict"):
            CacheContent(
                version=1,
                metadata=CacheMetadata(last_sync_time=datetime(2025, 1, 1, tzinfo=UTC)),
                threads=["not-a-dict"],
            )


# ---------------------------------------------------------------------------
# query_runner.py – helper edge cases
# ---------------------------------------------------------------------------


class TestIsUvxEnvironment:
    """Kill mutants in _is_uvx_environment."""

    def test_uv_active(self, monkeypatch):
        from perplexity_cli.query_runner import _is_uvx_environment

        monkeypatch.setenv("UV_ACTIVE", "1")
        monkeypatch.delenv("UVXENV", raising=False)
        assert _is_uvx_environment() is True

    def test_uvxenv(self, monkeypatch):
        from perplexity_cli.query_runner import _is_uvx_environment

        monkeypatch.delenv("UV_ACTIVE", raising=False)
        monkeypatch.setenv("UVXENV", "1")
        assert _is_uvx_environment() is True

    def test_neither(self, monkeypatch):
        from perplexity_cli.query_runner import _is_uvx_environment

        monkeypatch.delenv("UV_ACTIVE", raising=False)
        monkeypatch.delenv("UVXENV", raising=False)
        assert _is_uvx_environment() is False


class TestDetectExecutionEnvironment:
    """Kill mutants in _detect_execution_environment."""

    def test_uvx(self, monkeypatch):
        from perplexity_cli.query_runner import _detect_execution_environment

        monkeypatch.setenv("UV_ACTIVE", "1")
        assert _detect_execution_environment() == "uvx"

    def test_venv(self, monkeypatch):
        from perplexity_cli.query_runner import _detect_execution_environment

        monkeypatch.delenv("UV_ACTIVE", raising=False)
        monkeypatch.delenv("UVXENV", raising=False)
        monkeypatch.setenv("VIRTUAL_ENV", "/path/to/venv")
        assert _detect_execution_environment() == "venv"


class TestHasPotentialFileReferences:
    """Kill mutants in _has_potential_file_references."""

    def test_with_attachments(self):
        from perplexity_cli.query_runner import _has_potential_file_references

        assert _has_potential_file_references("query", ["file.txt"]) is True

    def test_forward_slash(self):
        from perplexity_cli.query_runner import _has_potential_file_references

        assert _has_potential_file_references("path/to/file", []) is True

    def test_backslash(self):
        from perplexity_cli.query_runner import _has_potential_file_references

        assert _has_potential_file_references("path\\to\\file", []) is True

    def test_no_references(self):
        from perplexity_cli.query_runner import _has_potential_file_references

        assert _has_potential_file_references("simple query", []) is False


class TestReadQueryFromStdin:
    """Kill mutants in _read_query_from_stdin."""

    def test_non_dash_passthrough(self):
        from perplexity_cli.query_runner import _read_query_from_stdin

        assert _read_query_from_stdin("hello") == "hello"

    def test_dash_with_tty_exits(self):
        from perplexity_cli.query_runner import _read_query_from_stdin

        with patch("perplexity_cli.query_runner.sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            with pytest.raises(SystemExit) as exc_info:
                _read_query_from_stdin("-")
            assert exc_info.value.code == 2

    def test_dash_with_empty_input_exits(self):
        from perplexity_cli.query_runner import _read_query_from_stdin

        with patch("perplexity_cli.query_runner.sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            mock_stdin.read.return_value = "   "
            with pytest.raises(SystemExit) as exc_info:
                _read_query_from_stdin("-")
            assert exc_info.value.code == 2

    def test_dash_with_valid_input(self):
        from perplexity_cli.query_runner import _read_query_from_stdin

        with patch("perplexity_cli.query_runner.sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            mock_stdin.read.return_value = "piped query"
            assert _read_query_from_stdin("-") == "piped query"


class TestReadCtxOptions:
    """Kill mutants in _read_ctx_options."""

    def test_none_ctx(self):
        from perplexity_cli.query_runner import _read_ctx_options

        json_mode, timeout, schema = _read_ctx_options(None)
        assert json_mode is False
        assert timeout is None
        assert schema is False

    def test_with_values(self):
        from perplexity_cli.query_runner import _read_ctx_options

        json_mode, timeout, schema = _read_ctx_options(
            {"json": True, "timeout": 60, "schema": True}
        )
        assert json_mode is True
        assert timeout == 60
        assert schema is True

    def test_timeout_non_int(self):
        from perplexity_cli.query_runner import _read_ctx_options

        _, timeout, _ = _read_ctx_options({"timeout": "60"})
        assert timeout is None


class TestParseRequestParamOverrides:
    """Kill mutants in parse_request_param_overrides edge cases."""

    def test_empty_overrides(self):
        from perplexity_cli.query_runner import parse_request_param_overrides

        assert parse_request_param_overrides(()) == {}

    def test_value_with_equals(self):
        from perplexity_cli.query_runner import parse_request_param_overrides

        result = parse_request_param_overrides(("key=val=ue",))
        assert result == {"key": "val=ue"}

    def test_empty_key_raises(self):
        from perplexity_cli.query_runner import parse_request_param_overrides

        with pytest.raises(ValueError, match="key=value"):
            parse_request_param_overrides(("=value",))

    def test_empty_value_raises(self):
        from perplexity_cli.query_runner import parse_request_param_overrides

        with pytest.raises(ValueError, match="key=value"):
            parse_request_param_overrides(("key=",))


class TestBuildJsonEnvelope:
    """Kill mutants in _build_json_envelope."""

    def test_envelope_structure(self):
        from perplexity_cli.query_runner import _build_json_envelope

        answer = Answer(
            text="Test answer",
            references=[
                WebResult(name="Ref", url="https://example.com", snippet="Snip"),
            ],
        )
        trace = TraceContext(trace_id="trace-1", start_time=time.monotonic())
        result = _build_json_envelope(answer, trace, "no_schema")
        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert parsed["result"]["answer"] == "Test answer"
        assert len(parsed["result"]["references"]) == 1
        assert parsed["result"]["references"][0]["url"] == "https://example.com"
        assert parsed["meta"]["trace_id"] == "trace-1"

    def test_none_start_time_uses_fallback(self):
        from perplexity_cli.query_runner import _build_json_envelope

        answer = Answer(text="T", references=[])
        trace = TraceContext(trace_id=None, start_time=None)
        result = _build_json_envelope(answer, trace, "no_schema")
        parsed = json.loads(result)
        assert parsed["meta"]["trace_id"] == ""
        assert isinstance(parsed["meta"]["duration_ms"], int)


class TestTryDispatchKnownError:
    """Kill mutants in _try_dispatch_known_error."""

    def test_upstream_schema_error_exits(self):
        from perplexity_cli.query_runner import _try_dispatch_known_error

        logger = get_logger()
        with pytest.raises(SystemExit) as exc_info:
            _try_dispatch_known_error(UpstreamSchemaError("bad"), logger, "normal")
        assert exc_info.value.code == 1

    def test_value_error_exits(self):
        from perplexity_cli.query_runner import _try_dispatch_known_error

        logger = get_logger()
        with pytest.raises(SystemExit) as exc_info:
            _try_dispatch_known_error(ValueError("bad"), logger, "normal")
        assert exc_info.value.code == 1

    def test_unknown_error_returns_false(self):
        from perplexity_cli.query_runner import _try_dispatch_known_error

        logger = get_logger()
        result = _try_dispatch_known_error(RuntimeError("unknown"), logger, "normal")
        assert result is False

    def test_http_error_returns_true(self):
        from perplexity_cli.query_runner import _try_dispatch_known_error

        logger = get_logger()
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.headers = {}
        error = PerplexityHTTPStatusError("err", request=Mock(), response=mock_response)
        with patch("perplexity_cli.query_runner.handle_http_error"):
            result = _try_dispatch_known_error(error, logger, "normal")
        assert result is True

    def test_request_error_returns_true(self):
        from perplexity_cli.query_runner import _try_dispatch_known_error

        logger = get_logger()
        error = PerplexityRequestError("timeout")
        with patch("perplexity_cli.query_runner.handle_network_error"):
            result = _try_dispatch_known_error(error, logger, "normal")
        assert result is True


class TestHandleKeyboardInterrupt:
    """Kill mutants in _handle_keyboard_interrupt."""

    def test_json_mode_calls_handle_error(self):
        from perplexity_cli.query_runner import _handle_keyboard_interrupt

        logger = get_logger()
        with patch("perplexity_cli.query_runner.handle_error") as mock_handle:
            with pytest.raises(SystemExit) as exc_info:
                _handle_keyboard_interrupt("json", logger)
            mock_handle.assert_called_once()
            assert exc_info.value.code == 130

    def test_human_mode_exits_130(self):
        from perplexity_cli.query_runner import _handle_keyboard_interrupt

        logger = get_logger()
        with pytest.raises(SystemExit) as exc_info:
            _handle_keyboard_interrupt("human", logger)
        assert exc_info.value.code == 130


# ---------------------------------------------------------------------------
# query_streaming.py – edge cases
# ---------------------------------------------------------------------------


class TestProcessStreamMessageEdgeCases:
    """Kill mutants in _process_stream_message."""

    def test_empty_text_returns_accumulated(self):
        from perplexity_cli.query_streaming import _process_stream_message

        message = Mock()
        message.extract_answer_text.return_value = ""
        result = _process_stream_message(message, "existing", None)
        assert result == "existing"

    def test_first_chunk_from_empty(self):
        from perplexity_cli.query_streaming import _process_stream_message

        message = Mock()
        message.extract_answer_text.return_value = "Hello"
        result = _process_stream_message(message, "", None)
        assert result == "Hello"

    def test_ndjson_chunk_content(self):
        from perplexity_cli.query_streaming import _process_stream_message

        writer = Mock()
        message = Mock()
        message.extract_answer_text.return_value = "Hello world"
        result = _process_stream_message(message, "Hello", writer)
        writer.chunk.assert_called_once_with(" world")
        assert result == "Hello world"


class TestRenderStreamReferences:
    """Kill mutants in _render_stream_references."""

    def test_strip_references_skips_rendering(self):
        from perplexity_cli.query_streaming import _render_stream_references

        render = Mock()
        render.options.strip_references = True
        render.options.output_format = "plain"
        refs = [WebResult(name="R", url="https://example.com", snippet="S")]
        _render_stream_references(render, "text", refs)
        render.formatter.format_references.assert_not_called()

    def test_empty_references_skips_rendering(self):
        from perplexity_cli.query_streaming import _render_stream_references

        render = Mock()
        render.options.strip_references = False
        render.options.output_format = "plain"
        _render_stream_references(render, "text", [])
        render.formatter.format_references.assert_not_called()

    def test_plain_format_calls_format_references(self):
        from perplexity_cli.query_streaming import _render_stream_references

        render = Mock()
        render.options.strip_references = False
        render.options.output_format = "plain"
        render.formatter.format_references.return_value = "[1] ref"
        refs = [WebResult(name="R", url="https://example.com", snippet="S")]
        with patch("perplexity_cli.query_streaming.click.echo"):
            _render_stream_references(render, "text", refs)
        render.formatter.format_references.assert_called_once_with(refs)

    def test_rich_format_calls_render_complete(self):
        from perplexity_cli.query_streaming import _render_stream_references

        render = Mock()
        render.options.strip_references = False
        render.options.output_format = "rich"
        refs = [WebResult(name="R", url="https://example.com", snippet="S")]
        with patch("perplexity_cli.query_streaming.click.echo"):
            _render_stream_references(render, "text", refs)
        render.formatter.render_complete.assert_called_once()


class TestStreamErrorHandlers:
    """Kill mutants in _StreamErrorHandlers cache."""

    def test_cache_is_populated(self):
        from perplexity_cli.query_streaming import _StreamErrorHandlers

        handlers = _StreamErrorHandlers.get()
        assert len(handlers) == 5

    def test_cache_is_reused(self):
        from perplexity_cli.query_streaming import _StreamErrorHandlers

        handlers1 = _StreamErrorHandlers.get()
        handlers2 = _StreamErrorHandlers.get()
        assert handlers1 is handlers2


class TestHandleStreamErrorDispatch:
    """Kill mutants in _handle_stream_error dispatch."""

    def test_upstream_schema_error_exits_1(self):
        from perplexity_cli.query_streaming import _handle_stream_error

        with pytest.raises(SystemExit) as exc_info:
            _handle_stream_error(UpstreamSchemaError("bad schema"))
        assert exc_info.value.code == 1

    def test_keyboard_interrupt_exits_130(self):
        from perplexity_cli.query_streaming import _handle_stream_error

        with pytest.raises(SystemExit) as exc_info:
            _handle_stream_error(KeyboardInterrupt())
        assert exc_info.value.code == 130


class TestRunStreamLoop:
    """Kill mutants in _run_stream_loop."""

    def test_accumulates_text_and_references(self):
        from perplexity_cli.query_streaming import _run_stream_loop

        api = Mock()
        msg1 = Mock()
        msg1.status = "STREAMING"
        msg1.final_sse_message = False
        msg1.web_results = []
        msg1.extract_answer_text.return_value = "Hello"

        msg2 = Mock()
        msg2.status = "COMPLETE"
        msg2.final_sse_message = True
        refs = [WebResult(name="R", url="https://example.com", snippet="S")]
        msg2.web_results = refs
        msg2.extract_answer_text.return_value = "Hello world"

        api.submit_query.return_value = iter([msg1, msg2])
        query_input = QueryInput(query="test")

        text, references = _run_stream_loop(api, query_input, None)
        assert text == "Hello world"
        assert len(references) == 1
        assert references[0].url == "https://example.com"

    def test_no_final_message_no_references(self):
        from perplexity_cli.query_streaming import _run_stream_loop

        api = Mock()
        msg = Mock()
        msg.status = "STREAMING"
        msg.final_sse_message = False
        msg.web_results = []
        msg.extract_answer_text.return_value = "partial"
        api.submit_query.return_value = iter([msg])
        query_input = QueryInput(query="test")

        text, references = _run_stream_loop(api, query_input, None)
        assert text == "partial"
        assert references == []


class TestWriteNdjsonResultEdgeCases:
    """Kill mutants in _write_ndjson_result."""

    def test_empty_references(self):
        from perplexity_cli.ndjson import NDJSONWriter
        from perplexity_cli.query_streaming import _write_ndjson_result

        output = StringIO()
        writer = NDJSONWriter(output)
        trace = TraceContext(start_time=time.monotonic(), trace_id="t-1")
        _write_ndjson_result(writer, "answer", [], trace)
        data = json.loads(output.getvalue().strip())
        assert data["result"]["references"] == []
        assert data["result"]["answer"] == "answer"

    def test_reference_fields(self):
        from perplexity_cli.ndjson import NDJSONWriter
        from perplexity_cli.query_streaming import _write_ndjson_result

        output = StringIO()
        writer = NDJSONWriter(output)
        refs = [WebResult(name="N", url="https://u.com", snippet="S")]
        trace = TraceContext(start_time=time.monotonic(), trace_id="t-2")
        _write_ndjson_result(writer, "text", refs, trace)
        data = json.loads(output.getvalue().strip())
        ref = data["result"]["references"][0]
        assert ref["name"] == "N"
        assert ref["url"] == "https://u.com"
        assert ref["snippet"] == "S"


# ---------------------------------------------------------------------------
# api/endpoints.py – edge cases
# ---------------------------------------------------------------------------


class TestPerplexityAPISubmitQueryEmptyQuery:
    """Kill mutants in submit_query empty query validation."""

    def test_empty_query_raises(self):
        from perplexity_cli.api.endpoints import PerplexityAPI

        api = PerplexityAPI(token="tok")
        with pytest.raises(ValueError, match="Query must not be empty"):
            list(api.submit_query(QueryInput(query="")))

    def test_whitespace_only_query_raises(self):
        from perplexity_cli.api.endpoints import PerplexityAPI

        api = PerplexityAPI(token="tok")
        with pytest.raises(ValueError, match="Query must not be empty"):
            list(api.submit_query(QueryInput(query="   ")))


class TestExtractAnswerFromFinal:
    """Kill mutants in _extract_answer_from_final."""

    def test_none_final_message_raises(self):
        from perplexity_cli.api.endpoints import PerplexityAPI

        with pytest.raises(UpstreamSchemaError, match="No final SSE message"):
            PerplexityAPI._extract_answer_from_final(None)

    def test_no_answer_raises_with_status(self):
        from perplexity_cli.api.endpoints import PerplexityAPI

        msg = Mock()
        msg.extract_answer_text.return_value = None
        msg.status = "FAILED"
        msg.describe_block_usages.return_value = "none"
        msg.web_results = None
        with pytest.raises(UpstreamSchemaError, match="status=FAILED"):
            PerplexityAPI._extract_answer_from_final(msg)

    def test_empty_status_shows_empty(self):
        from perplexity_cli.api.endpoints import PerplexityAPI

        msg = Mock()
        msg.extract_answer_text.return_value = None
        msg.status = ""
        msg.describe_block_usages.return_value = "none"
        msg.web_results = None
        with pytest.raises(UpstreamSchemaError, match="status=<empty>"):
            PerplexityAPI._extract_answer_from_final(msg)


class TestBuildQueryParams:
    """Kill mutants in _build_query_params."""

    def test_default_model(self):
        from perplexity_cli.api.endpoints import PerplexityAPI

        qi = QueryInput(query="q")
        params = PerplexityAPI._build_query_params(qi, "uuid1", "uuid2", "standard")
        assert params.model_preference == "pplx_pro"

    def test_custom_model(self):
        from perplexity_cli.api.endpoints import PerplexityAPI

        qi = QueryInput(query="q", model_preference="custom_model")
        params = PerplexityAPI._build_query_params(qi, "uuid1", "uuid2", "standard")
        assert params.model_preference == "custom_model"

    def test_with_request_params(self):
        from perplexity_cli.api.endpoints import PerplexityAPI

        qi = QueryInput(query="q", request_params={"workflow_key": "deep_research"})
        params = PerplexityAPI._build_query_params(qi, "uuid1", "uuid2", "standard")
        assert params.workflow_key == "deep_research"

    def test_without_request_params(self):
        from perplexity_cli.api.endpoints import PerplexityAPI

        qi = QueryInput(query="q")
        params = PerplexityAPI._build_query_params(qi, "uuid1", "uuid2", "standard")
        assert params.frontend_uuid == "uuid1"
        assert params.frontend_context_uuid == "uuid2"


# ---------------------------------------------------------------------------
# api/rest_client.py – edge cases
# ---------------------------------------------------------------------------


class TestRestClientHeaders:
    """Kill mutants in RestClient.get_headers."""

    def test_accept_header_is_json(self):
        from perplexity_cli.api.rest_client import RestClient

        client = RestClient(auth=AuthContext(token="tok"))
        headers = client.get_headers()
        assert headers["Accept"] == "application/json"
        assert headers["Authorization"] == "Bearer tok"

    def test_csrf_from_cookies(self):
        from perplexity_cli.api.rest_client import RestClient

        client = RestClient(auth=AuthContext(token="tok", cookies={"csrftoken": "csrf123"}))
        headers = client.get_headers()
        assert headers["X-CSRFToken"] == "csrf123"


class TestRestClientClose:
    """Kill mutants in RestClient.close."""

    def test_close_when_no_client(self):
        from perplexity_cli.api.rest_client import RestClient

        client = RestClient(auth=AuthContext(token="tok"))
        client.close()
        assert client._client is None

    def test_close_resets_client(self):
        from perplexity_cli.api.rest_client import RestClient

        client = RestClient(auth=AuthContext(token="tok"))
        mock_session = Mock()
        client._client = mock_session
        client.close()
        mock_session.close.assert_called_once()
        assert client._client is None


class TestRestClientContextManager:
    """Kill mutants in RestClient context manager."""

    def test_enter_returns_self(self):
        from perplexity_cli.api.rest_client import RestClient

        client = RestClient(auth=AuthContext(token="tok"))
        assert client.__enter__() is client

    def test_exit_calls_close(self):
        from perplexity_cli.api.rest_client import RestClient

        client = RestClient(auth=AuthContext(token="tok"))
        client._client = Mock()
        client.__exit__(None, None, None)
        assert client._client is None
