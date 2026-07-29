"""Round 3 mutation-killing tests for api/client.py and formatting/rich.py."""

from __future__ import annotations

import logging
import threading
from io import StringIO
from unittest.mock import MagicMock, Mock, patch

import pytest

from perplexity_cli.api.client import (
    HEADER_PAIR_SIZE,
    HTTP_STATUS_FORBIDDEN,
    HTTP_STATUS_TOO_MANY_REQUESTS,
    HTTP_STATUS_UNAUTHORISED,
    RetryHandler,
    SSEClient,
    SSEParser,
    _coerce_header_mapping,
    _coerce_header_pair,
    _is_deep_research_request,
    _is_json_object,
    _is_request_exception,
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
from perplexity_cli.api.models import Answer, HttpRequestContext, WebResult
from perplexity_cli.auth.models import AuthContext
from perplexity_cli.formatting.rich import RichFormatter, _HEADER_LEVEL_2, _SECTION_HEADER_STYLE
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    SimpleRequest,
    SimpleResponse,
    UpstreamSchemaError,
)
from perplexity_cli.utils.retry import get_backoff_delay


def _make_http_error(status: int, headers: dict[str, str] | None = None) -> PerplexityHTTPStatusError:
    request = SimpleRequest(method="POST", url="https://www.perplexity.ai/api")
    response = SimpleResponse(
        status_code=status, headers=headers or {}, text="error body", request=request
    )
    return PerplexityHTTPStatusError(f"HTTP Error {status}", request=request, response=response)


class TestReadTransportValue:
    def test_returns_value_on_success(self) -> None:
        result = _read_transport_value(lambda: 42, "test.ctx")
        assert result == 42

    def test_raises_runtime_error_on_attribute_error(self) -> None:
        def factory() -> object:
            raise AttributeError("missing")

        with pytest.raises(RuntimeError, match="Expected transport attribute for test.ctx"):
            _read_transport_value(factory, "test.ctx")

    def test_raises_runtime_error_on_type_error(self) -> None:
        def factory() -> object:
            raise TypeError("bad type")

        with pytest.raises(RuntimeError, match="Expected transport attribute for other.ctx"):
            _read_transport_value(factory, "other.ctx")

    def test_preserves_cause_chain(self) -> None:
        def factory() -> object:
            raise AttributeError("root cause")

        with pytest.raises(RuntimeError) as exc_info:
            _read_transport_value(factory, "ctx")
        assert isinstance(exc_info.value.__cause__, AttributeError)


class TestRequireStr:
    def test_valid_string(self) -> None:
        assert _require_str("hello", "ctx") == "hello"

    def test_empty_string_valid(self) -> None:
        assert _require_str("", "ctx") == ""

    def test_rejects_int(self) -> None:
        with pytest.raises(RuntimeError, match="Expected string transport attribute for ctx"):
            _require_str(123, "ctx")

    def test_rejects_none(self) -> None:
        with pytest.raises(RuntimeError, match="Expected string transport attribute for my.field"):
            _require_str(None, "my.field")

    def test_rejects_bytes(self) -> None:
        with pytest.raises(RuntimeError, match="Expected string transport attribute"):
            _require_str(b"bytes", "ctx")


class TestRequireInt:
    def test_valid_int(self) -> None:
        assert _require_int(200, "ctx") == 200

    def test_zero_valid(self) -> None:
        assert _require_int(0, "ctx") == 0

    def test_negative_valid(self) -> None:
        assert _require_int(-1, "ctx") == -1

    def test_rejects_string(self) -> None:
        with pytest.raises(RuntimeError, match="Expected integer transport attribute for ctx"):
            _require_int("200", "ctx")

    def test_rejects_bool(self) -> None:
        assert _require_int(True, "ctx") == 1

    def test_rejects_float(self) -> None:
        with pytest.raises(RuntimeError, match="Expected integer transport attribute"):
            _require_int(3.14, "ctx")


class TestRequireBool:
    def test_true(self) -> None:
        assert _require_bool(True, "ctx") is True

    def test_false(self) -> None:
        assert _require_bool(False, "ctx") is False

    def test_rejects_int(self) -> None:
        with pytest.raises(RuntimeError, match="Expected boolean transport attribute for ctx"):
            _require_bool(1, "ctx")

    def test_rejects_string(self) -> None:
        with pytest.raises(RuntimeError, match="Expected boolean transport attribute"):
            _require_bool("true", "ctx")


class TestRequireBytesOrStr:
    def test_bytes(self) -> None:
        assert _require_bytes_or_str(b"data", "ctx") == b"data"

    def test_str(self) -> None:
        assert _require_bytes_or_str("data", "ctx") == "data"

    def test_empty_bytes(self) -> None:
        assert _require_bytes_or_str(b"", "ctx") == b""

    def test_rejects_int(self) -> None:
        with pytest.raises(RuntimeError, match="Expected bytes-or-string transport attribute for ctx"):
            _require_bytes_or_str(42, "ctx")

    def test_rejects_list(self) -> None:
        with pytest.raises(RuntimeError, match="Expected bytes-or-string transport attribute"):
            _require_bytes_or_str(["a"], "ctx")


class TestRequireJsonObjectOrNone:
    def test_none_returns_none(self) -> None:
        assert _require_json_object_or_none(None, "ctx") is None

    def test_dict_returns_dict(self) -> None:
        result = _require_json_object_or_none({"key": "val"}, "ctx")
        assert result == {"key": "val"}

    def test_empty_dict_valid(self) -> None:
        assert _require_json_object_or_none({}, "ctx") == {}

    def test_rejects_list(self) -> None:
        with pytest.raises(RuntimeError, match="Expected JSON object transport attribute for ctx"):
            _require_json_object_or_none([1, 2], "ctx")

    def test_rejects_string(self) -> None:
        with pytest.raises(RuntimeError, match="Expected JSON object transport attribute"):
            _require_json_object_or_none("not a dict", "ctx")


class TestCoerceHeaderPair:
    def test_valid_pair(self) -> None:
        assert _coerce_header_pair(("Content-Type", "application/json"), "ctx") == (
            "Content-Type",
            "application/json",
        )

    def test_coerces_non_string_values(self) -> None:
        assert _coerce_header_pair(("status", 200), "ctx") == ("status", "200")

    def test_rejects_wrong_size_1(self) -> None:
        with pytest.raises(RuntimeError, match="Expected header pair items for ctx"):
            _coerce_header_pair(("only-one",), "ctx")

    def test_rejects_wrong_size_3(self) -> None:
        with pytest.raises(RuntimeError, match="Expected header pair items for ctx"):
            _coerce_header_pair(("a", "b", "c"), "ctx")

    def test_rejects_non_sized(self) -> None:
        with pytest.raises(RuntimeError, match="Expected header pair items for ctx"):
            _coerce_header_pair(42, "ctx")


class TestCoerceHeaderMapping:
    def test_valid_mapping(self) -> None:
        result = _coerce_header_mapping({"Content-Type": "text/html", "X-Custom": "val"}, "ctx")
        assert result == {"Content-Type": "text/html", "X-Custom": "val"}

    def test_empty_mapping(self) -> None:
        assert _coerce_header_mapping({}, "ctx") == {}

    def test_rejects_non_mapping(self) -> None:
        with pytest.raises(RuntimeError, match="Expected mapping-like transport attribute for ctx"):
            _coerce_header_mapping("not a mapping", "ctx")

    def test_rejects_list_as_mapping(self) -> None:
        with pytest.raises(RuntimeError, match="Expected mapping-like transport attribute"):
            _coerce_header_mapping([("a", "b")], "ctx")


class TestIterObjectValues:
    def test_yields_all_items(self) -> None:
        result = list(_iter_object_values([1, 2, 3], "ctx"))
        assert result == [1, 2, 3]

    def test_empty_iterable(self) -> None:
        result = list(_iter_object_values([], "ctx"))
        assert result == []

    def test_rejects_non_iterable(self) -> None:
        with pytest.raises(RuntimeError, match="Expected iterable transport value for ctx"):
            list(_iter_object_values(42, "ctx"))


class TestResponseAdapter:
    def test_status_code(self) -> None:
        mock = Mock(status_code=200)
        adapter = _ResponseAdapter(mock)
        assert adapter.status_code == 200

    def test_text(self) -> None:
        mock = Mock(text="response body")
        adapter = _ResponseAdapter(mock)
        assert adapter.text == "response body"

    def test_ok_true(self) -> None:
        mock = Mock(ok=True)
        adapter = _ResponseAdapter(mock)
        assert adapter.ok is True

    def test_ok_false(self) -> None:
        mock = Mock(ok=False)
        adapter = _ResponseAdapter(mock)
        assert adapter.ok is False

    def test_reason(self) -> None:
        mock = Mock(reason="Not Found")
        adapter = _ResponseAdapter(mock)
        assert adapter.reason == "Not Found"

    def test_url_returns_value(self) -> None:
        mock = Mock(url="https://example.com")
        adapter = _ResponseAdapter(mock)
        assert adapter.url == "https://example.com"

    def test_url_returns_none_on_attribute_error(self) -> None:
        mock = Mock(spec=[])
        adapter = _ResponseAdapter(mock)
        assert adapter.url is None

    def test_content_bytes(self) -> None:
        mock = Mock(content=b"raw bytes")
        adapter = _ResponseAdapter(mock)
        assert adapter.content == b"raw bytes"

    def test_content_str(self) -> None:
        mock = Mock(content="raw string")
        adapter = _ResponseAdapter(mock)
        assert adapter.content == "raw string"

    def test_headers_dict(self) -> None:
        mock = Mock(headers={"X-Ray": "abc123"})
        adapter = _ResponseAdapter(mock)
        assert adapter.headers == {"X-Ray": "abc123"}

    def test_iter_lines_yields_strings(self) -> None:
        mock = Mock()
        mock.iter_lines.return_value = ["line1", "line2"]
        adapter = _ResponseAdapter(mock)
        assert list(adapter.iter_lines()) == ["line1", "line2"]

    def test_iter_lines_yields_bytes(self) -> None:
        mock = Mock()
        mock.iter_lines.return_value = [b"line1", b"line2"]
        adapter = _ResponseAdapter(mock)
        assert list(adapter.iter_lines()) == [b"line1", b"line2"]

    def test_iter_lines_rejects_non_bytes_str(self) -> None:
        mock = Mock()
        mock.iter_lines.return_value = [123]
        adapter = _ResponseAdapter(mock)
        with pytest.raises(RuntimeError, match="Expected bytes or string lines"):
            list(adapter.iter_lines())

    def test_iter_lines_rejects_non_callable(self) -> None:
        mock = Mock(spec=[])
        adapter = _ResponseAdapter(mock)
        with pytest.raises(RuntimeError, match="Expected callable response.iter_lines"):
            list(adapter.iter_lines())


class TestStreamContextAdapter:
    def test_enter_returns_response_adapter(self) -> None:
        inner_response = Mock(status_code=200)
        ctx = Mock()
        ctx.__enter__ = Mock(return_value=inner_response)
        adapter = _StreamContextAdapter(ctx)
        result = adapter.__enter__()
        assert isinstance(result, _ResponseAdapter)
        assert result.status_code == 200

    def test_exit_returns_none(self) -> None:
        ctx = Mock()
        ctx.__exit__ = Mock(return_value=None)
        adapter = _StreamContextAdapter(ctx)
        assert adapter.__exit__(None, None, None) is None

    def test_exit_returns_false(self) -> None:
        ctx = Mock()
        ctx.__exit__ = Mock(return_value=False)
        adapter = _StreamContextAdapter(ctx)
        assert adapter.__exit__(None, None, None) is False

    def test_exit_returns_true(self) -> None:
        ctx = Mock()
        ctx.__exit__ = Mock(return_value=True)
        adapter = _StreamContextAdapter(ctx)
        assert adapter.__exit__(None, None, None) is True

    def test_exit_rejects_non_bool_non_none(self) -> None:
        ctx = Mock()
        ctx.__exit__ = Mock(return_value="invalid")
        adapter = _StreamContextAdapter(ctx)
        with pytest.raises(RuntimeError, match="Expected bool-or-None return"):
            adapter.__exit__(None, None, None)

    def test_enter_rejects_missing_enter(self) -> None:
        ctx = Mock(spec=[])
        adapter = _StreamContextAdapter(ctx)
        with pytest.raises(RuntimeError, match="Expected __enter__ on stream context manager"):
            adapter.__enter__()

    def test_exit_rejects_missing_exit(self) -> None:
        ctx = Mock(spec=[])
        adapter = _StreamContextAdapter(ctx)
        with pytest.raises(RuntimeError, match="Expected __exit__ on stream context manager"):
            adapter.__exit__(None, None, None)


class TestSSEParserDecodeLine:
    def test_bytes_decoded(self) -> None:
        assert SSEParser._decode_line(b"hello") == "hello"

    def test_string_passthrough(self) -> None:
        assert SSEParser._decode_line("hello") == "hello"

    def test_empty_bytes(self) -> None:
        assert SSEParser._decode_line(b"") == ""

    def test_empty_string(self) -> None:
        assert SSEParser._decode_line("") == ""

    def test_utf8_bytes(self) -> None:
        assert SSEParser._decode_line("café".encode("utf-8")) == "café"


class TestSSEParserParseEdgeCases:
    def test_data_only_no_event_type_no_yield(self) -> None:
        mock = Mock()
        mock.iter_lines.return_value = [b'data: {"a": 1}', b""]
        logger = logging.getLogger("test")
        result = list(SSEParser.parse(mock, logger))
        assert result == []

    def test_event_only_no_data_no_yield(self) -> None:
        mock = Mock()
        mock.iter_lines.return_value = [b"event: message", b""]
        logger = logging.getLogger("test")
        result = list(SSEParser.parse(mock, logger))
        assert result == []

    def test_multiple_data_lines_joined_with_newline(self) -> None:
        mock = Mock()
        mock.iter_lines.return_value = [
            b"event: msg",
            b'data: {"key":',
            b'data: "value"}',
            b"",
        ]
        logger = logging.getLogger("test")
        result = list(SSEParser.parse(mock, logger))
        assert result == [{"key": "value"}]

    def test_event_type_reset_after_yield(self) -> None:
        mock = Mock()
        mock.iter_lines.return_value = [
            b"event: msg",
            b'data: {"first": 1}',
            b"",
            b'data: {"second": 2}',
            b"",
        ]
        logger = logging.getLogger("test")
        result = list(SSEParser.parse(mock, logger))
        assert result == [{"first": 1}]

    def test_final_event_without_trailing_blank(self) -> None:
        mock = Mock()
        mock.iter_lines.return_value = [
            b"event: msg",
            b'data: {"final": true}',
        ]
        logger = logging.getLogger("test")
        result = list(SSEParser.parse(mock, logger))
        assert result == [{"final": True}]

    def test_non_json_array_raises(self) -> None:
        mock = Mock()
        mock.iter_lines.return_value = [
            b"event: msg",
            b"data: [1, 2, 3]",
            b"",
        ]
        logger = logging.getLogger("test")
        with pytest.raises(UpstreamSchemaError, match="must decode to a JSON object"):
            list(SSEParser.parse(mock, logger))

    def test_invalid_json_raises_with_truncated_message(self) -> None:
        long_payload = "x" * 150
        mock = Mock()
        mock.iter_lines.return_value = [
            b"event: msg",
            f"data: {long_payload}".encode(),
            b"",
        ]
        logger = logging.getLogger("test")
        with pytest.raises(UpstreamSchemaError) as exc_info:
            list(SSEParser.parse(mock, logger))
        assert "x" * 100 in str(exc_info.value)
        assert "x" * 101 not in str(exc_info.value)


class TestRetryHandler403:
    def test_403_attempt_0_of_3_returns_wait(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(403)
        wait = handler.handle_http_error(error, attempt=0)
        assert wait > 0

    def test_403_attempt_1_of_3_returns_wait(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(403)
        wait = handler.handle_http_error(error, attempt=1)
        assert wait > 0

    def test_403_attempt_2_of_3_raises(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(403)
        with pytest.raises(PerplexityHTTPStatusError, match="Access forbidden"):
            handler.handle_http_error(error, attempt=2)

    def test_403_sleep_attempt_set_to_next(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(403)
        handler.handle_http_error(error, attempt=0)
        assert handler.consume_sleep_attempt() == 1

    def test_403_sleep_attempt_second_retry(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(403)
        handler.handle_http_error(error, attempt=1)
        assert handler.consume_sleep_attempt() == 2

    def test_403_max_retries_1_raises_immediately(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=1)
        error = _make_http_error(403)
        with pytest.raises(PerplexityHTTPStatusError, match="Access forbidden"):
            handler.handle_http_error(error, attempt=0)

    def test_403_error_message_exact(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=1)
        error = _make_http_error(403)
        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            handler.handle_http_error(error, attempt=0)
        assert "Check API permissions or try again later" in str(exc_info.value)


class TestRetryHandler429And5xx:
    def test_429_with_retry_after_header_uses_header_value(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(429, headers={"Retry-After": "12"})
        wait = handler.handle_http_error(error, attempt=0)
        assert wait == pytest.approx(12.0)

    def test_429_without_retry_after_uses_backoff(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(429)
        wait = handler.handle_http_error(error, attempt=0)
        assert wait > 0

    def test_429_exhausted_raises_rate_limit_message(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(429)
        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            handler.handle_http_error(error, attempt=2)
        assert "Rate limit exceeded" in str(exc_info.value)

    def test_500_exhausted_reraises_original(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=2)
        error = _make_http_error(500)
        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            handler.handle_http_error(error, attempt=1)
        assert exc_info.value is error

    def test_502_retries_when_attempts_remain(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(502)
        wait = handler.handle_http_error(error, attempt=0)
        assert wait > 0

    def test_400_not_retryable_reraises(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(400)
        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            handler.handle_http_error(error, attempt=0)
        assert exc_info.value is error

    def test_429_retry_after_does_not_set_sleep_attempt(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(429, headers={"Retry-After": "5"})
        handler.handle_http_error(error, attempt=0)
        assert handler.consume_sleep_attempt() is None

    def test_429_no_retry_after_sets_sleep_attempt(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(429)
        handler.handle_http_error(error, attempt=0)
        assert handler.consume_sleep_attempt() == 1


class TestRetryHandlerNetworkError:
    def test_retryable_error_returns_incremented_attempt(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = PerplexityRequestError("timeout")
        assert handler.handle_network_error(error, attempt=0) == 1

    def test_retryable_error_attempt_1_returns_2(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = PerplexityRequestError("timeout")
        assert handler.handle_network_error(error, attempt=1) == 2

    def test_exhausted_raises_original(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=2)
        error = PerplexityRequestError("timeout")
        with pytest.raises(PerplexityRequestError) as exc_info:
            handler.handle_network_error(error, attempt=1)
        assert exc_info.value is error

    def test_non_retryable_generic_raises(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = ValueError("bad value")
        with pytest.raises(ValueError) as exc_info:
            handler.handle_network_error(error, attempt=0)
        assert exc_info.value is error

    def test_curl_request_exception_raises_perplexity_request_error(self) -> None:
        from curl_cffi.requests.exceptions import RequestException

        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = RequestException("connection reset")
        with pytest.raises(PerplexityRequestError, match="connection reset"):
            handler.handle_network_error(error, attempt=0)


class TestRetryHandlerLogContext:
    def test_debug_disabled_no_output(self) -> None:
        logger = logging.getLogger("test.no_debug")
        logger.setLevel(logging.WARNING)
        handler = RetryHandler(logger, max_retries=3)
        error = _make_http_error(500)
        assert logger.isEnabledFor(logging.DEBUG) is False
        handler._log_http_error_context(error)

    def test_debug_enabled_logs_status(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.debug_on")
        logger.setLevel(logging.DEBUG)
        handler = RetryHandler(logger, max_retries=3)
        error = _make_http_error(503)
        with caplog.at_level(logging.DEBUG, logger="test.debug_on"):
            handler._log_http_error_context(error)
        messages = [r.getMessage() for r in caplog.records]
        assert any("503" in m for m in messages)

    def test_debug_logs_cf_ray(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.cf_ray")
        logger.setLevel(logging.DEBUG)
        handler = RetryHandler(logger, max_retries=3)
        error = _make_http_error(403, headers={"cf-ray": "ray-123"})
        with caplog.at_level(logging.DEBUG, logger="test.cf_ray"):
            handler._log_http_error_context(error)
        messages = [r.getMessage() for r in caplog.records]
        assert any("ray-123" in m for m in messages)

    def test_debug_logs_cf_cache_status(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.cf_cache")
        logger.setLevel(logging.DEBUG)
        handler = RetryHandler(logger, max_retries=3)
        error = _make_http_error(403, headers={"cf-cache-status": "HIT"})
        with caplog.at_level(logging.DEBUG, logger="test.cf_cache"):
            handler._log_http_error_context(error)
        messages = [r.getMessage() for r in caplog.records]
        assert any("HIT" in m for m in messages)


class TestIsRequestException:
    def test_curl_request_exception_true(self) -> None:
        from curl_cffi.requests.exceptions import RequestException

        assert _is_request_exception(RequestException("fail")) is True

    def test_generic_exception_false(self) -> None:
        assert _is_request_exception(RuntimeError("fail")) is False

    def test_value_error_false(self) -> None:
        assert _is_request_exception(ValueError("fail")) is False


class TestSleepForRetry:
    def test_with_sleep_attempt_uses_backoff(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=3)
        client._retry._sleep_attempt = 2
        with patch("perplexity_cli.api.client.sleep_with_backoff") as mock_sleep:
            client._sleep_for_retry(5.0)
        mock_sleep.assert_called_once_with(2)

    def test_without_sleep_attempt_uses_event_wait(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=3)
        client._retry._sleep_attempt = None
        with patch("perplexity_cli.api.client.threading.Event") as mock_event_cls:
            mock_event = Mock()
            mock_event_cls.return_value = mock_event
            client._sleep_for_retry(3.5)
        mock_event.wait.assert_called_once_with(3.5)


class TestRetryStreamError:
    def test_http_status_error_returns_incremented_attempt(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=3)
        error = _make_http_error(500)
        with patch.object(client, "_sleep_for_retry"):
            result = client._retry_stream_error(error, attempt=0)
        assert result == 1

    def test_perplexity_request_error_delegates(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=3)
        error = PerplexityRequestError("timeout")
        result = client._retry_stream_error(error, attempt=0)
        assert result == 1

    def test_unknown_error_reraises(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=3)
        error = ValueError("unexpected")
        with pytest.raises(ValueError, match="unexpected"):
            client._retry_stream_error(error, attempt=0)


class TestResolveEffectiveTimeout:
    def test_no_params_key_uses_default(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), timeout=45)
        is_deep, timeout = client._resolve_effective_timeout({"query": "test"})
        assert is_deep is False
        assert timeout == 45

    def test_params_not_dict_uses_default(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), timeout=30)
        is_deep, timeout = client._resolve_effective_timeout({"params": "invalid"})
        assert is_deep is False
        assert timeout == 30

    def test_deep_research_multi_step(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), timeout=60)
        is_deep, timeout = client._resolve_effective_timeout(
            {"params": {"search_implementation_mode": "multi_step"}}
        )
        assert is_deep is True
        assert timeout == 360

    def test_deep_research_search_mode(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), timeout=60)
        is_deep, timeout = client._resolve_effective_timeout(
            {"params": {"search_mode": "deep_research"}}
        )
        assert is_deep is True
        assert timeout == 360

    def test_not_deep_research_standard_mode(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), timeout=55)
        is_deep, timeout = client._resolve_effective_timeout(
            {"params": {"search_implementation_mode": "standard"}}
        )
        assert is_deep is False
        assert timeout == 55


class TestLogResponseHeaders:
    def test_label_formatting_cf_ray(self, caplog: pytest.LogCaptureFixture) -> None:
        client = SSEClient(auth=AuthContext(token="tok"))
        client.logger.setLevel(logging.DEBUG)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.reason = "OK"
        mock_response.headers = {"cf-ray": "ray-abc"}
        adapter = _ResponseAdapter(mock_response)
        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            client._log_response_headers(adapter)
        messages = [r.getMessage() for r in caplog.records]
        assert any("Cloudflare Ray" in m for m in messages)

    def test_label_formatting_server(self, caplog: pytest.LogCaptureFixture) -> None:
        client = SSEClient(auth=AuthContext(token="tok"))
        client.logger.setLevel(logging.DEBUG)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.reason = "OK"
        mock_response.headers = {"server": "cloudflare"}
        adapter = _ResponseAdapter(mock_response)
        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            client._log_response_headers(adapter)
        messages = [r.getMessage() for r in caplog.records]
        assert any("Server" in m for m in messages)

    def test_no_debug_no_output(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"))
        client.logger.setLevel(logging.WARNING)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.reason = "OK"
        mock_response.headers = {"cf-ray": "ray-abc"}
        adapter = _ResponseAdapter(mock_response)
        assert client.logger.isEnabledFor(logging.DEBUG) is False
        client._log_response_headers(adapter)


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


class TestRichFormatterConstants:
    def test_section_header_style(self) -> None:
        assert _SECTION_HEADER_STYLE == "bold cyan"

    def test_header_level_2(self) -> None:
        assert _HEADER_LEVEL_2 == 2


class TestRichFormatterPrintFormattedText:
    def test_h1_style_bold_bright_cyan(self) -> None:
        formatter = RichFormatter()
        buffer = StringIO()
        formatter.console.file = buffer
        formatter._print_formatted_text("# Title")
        output = buffer.getvalue()
        assert "Title" in output
        assert "#" not in output

    def test_h2_style_bold_cyan(self) -> None:
        formatter = RichFormatter()
        buffer = StringIO()
        formatter.console.file = buffer
        formatter._print_formatted_text("## Section")
        output = buffer.getvalue()
        assert "Section" in output
        assert "##" not in output

    def test_h3_style_bold_white(self) -> None:
        formatter = RichFormatter()
        buffer = StringIO()
        formatter.console.file = buffer
        formatter._print_formatted_text("### Sub")
        output = buffer.getvalue()
        assert "Sub" in output
        assert "###" not in output

    def test_h4_style_bold_white(self) -> None:
        formatter = RichFormatter()
        buffer = StringIO()
        formatter.console.file = buffer
        formatter._print_formatted_text("#### Deep")
        output = buffer.getvalue()
        assert "Deep" in output

    def test_plain_text_no_styling(self) -> None:
        formatter = RichFormatter()
        buffer = StringIO()
        formatter.console.file = buffer
        formatter._print_formatted_text("just plain text")
        output = buffer.getvalue()
        assert "just plain text" in output

    def test_multiple_lines(self) -> None:
        formatter = RichFormatter()
        buffer = StringIO()
        formatter.console.file = buffer
        formatter._print_formatted_text("# H1\nplain\n## H2")
        output = buffer.getvalue()
        assert "H1" in output
        assert "plain" in output
        assert "H2" in output


class TestRichFormatterRenderCodeBlock:
    def test_fallback_format_exact(self) -> None:
        formatter = RichFormatter()
        with patch("perplexity_cli.formatting.rich.Syntax", side_effect=ValueError("unknown lexer")):
            result = formatter._render_code_block("invalid_lang_xyz_999", "some code")
        assert result == "```invalid_lang_xyz_999\nsome code\n```"

    def test_valid_python_contains_code(self) -> None:
        formatter = RichFormatter()
        result = formatter._render_code_block("python", "x = 42")
        assert "42" in result

    def test_valid_javascript(self) -> None:
        formatter = RichFormatter()
        result = formatter._render_code_block("javascript", "const x = 1;")
        assert "x" in result

    def test_text_language(self) -> None:
        formatter = RichFormatter()
        result = formatter._render_code_block("text", "plain output")
        assert "plain output" in result


class TestRichFormatterProcessAnswerText:
    def test_no_code_blocks_unchanged(self) -> None:
        formatter = RichFormatter()
        result = formatter._process_answer_text("plain text here")
        assert result == "plain text here"

    def test_code_block_without_language_defaults_to_text(self) -> None:
        formatter = RichFormatter()
        text = "```\nsome code\n```"
        result = formatter._process_answer_text(text)
        assert "some code" in result

    def test_text_before_and_after_preserved(self) -> None:
        formatter = RichFormatter()
        text = "before\n```python\nx = 1\n```\nafter"
        result = formatter._process_answer_text(text)
        assert "before" in result
        assert "after" in result
        assert "x" in result

    def test_multiple_code_blocks(self) -> None:
        formatter = RichFormatter()
        text = "```\nblock1\n```\nmiddle\n```\nblock2\n```"
        result = formatter._process_answer_text(text)
        assert "block1" in result
        assert "middle" in result
        assert "block2" in result

    def test_empty_string(self) -> None:
        formatter = RichFormatter()
        assert formatter._process_answer_text("") == ""


class TestRichFormatterFormatReferences:
    def test_empty_returns_empty(self) -> None:
        formatter = RichFormatter()
        assert formatter.format_references([]) == ""

    def test_single_reference_contains_name_and_url(self) -> None:
        formatter = RichFormatter()
        refs = [WebResult(name="Example Source", url="https://example.com/page", snippet="s")]
        result = formatter.format_references(refs)
        assert "Example Source" in result
        assert "https://example.com/page" in result

    def test_numbering_starts_at_1(self) -> None:
        formatter = RichFormatter()
        refs = [
            WebResult(name="A", url="https://a.com", snippet="a"),
            WebResult(name="B", url="https://b.com", snippet="b"),
        ]
        result = formatter.format_references(refs)
        assert "1" in result
        assert "2" in result

    def test_table_title_references(self) -> None:
        formatter = RichFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet="s")]
        result = formatter.format_references(refs)
        assert "References" in result

    def test_contains_ansi_codes(self) -> None:
        formatter = RichFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet="s")]
        result = formatter.format_references(refs)
        assert "\x1b[" in result


class TestRichFormatterFormatComplete:
    def test_separator_line_50_chars(self) -> None:
        formatter = RichFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet="s")]
        answer = Answer(text="Answer", references=refs)
        result = formatter.format_complete(answer)
        assert "─" * 50 in result

    def test_no_references_no_separator(self) -> None:
        formatter = RichFormatter()
        answer = Answer(text="Answer only", references=[])
        result = formatter.format_complete(answer)
        assert "─" * 50 not in result

    def test_strip_references_removes_citations_and_refs(self) -> None:
        formatter = RichFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet="s")]
        answer = Answer(text="Text[1] more[2]", references=refs)
        result = formatter.format_complete(answer, strip_references=True)
        assert "[1]" not in result
        assert "[2]" not in result
        assert "Src" not in result
        assert "─" * 50 not in result

    def test_contains_ansi_escape_codes(self) -> None:
        formatter = RichFormatter()
        refs = [WebResult(name="Src", url="https://src.com", snippet="s")]
        answer = Answer(text="Answer", references=refs)
        result = formatter.format_complete(answer)
        assert "\x1b[" in result

    def test_answer_text_present(self) -> None:
        formatter = RichFormatter()
        answer = Answer(text="The quick brown fox", references=[])
        result = formatter.format_complete(answer)
        assert "The quick brown fox" in result


class TestRichFormatterFormatAnswer:
    def test_strips_trailing_whitespace(self) -> None:
        formatter = RichFormatter()
        result = formatter.format_answer("text\n\n\n")
        assert not result.endswith("\n")

    def test_strip_references_removes_citations(self) -> None:
        formatter = RichFormatter()
        result = formatter.format_answer("fact[1] and[2] more", strip_references=True)
        assert "[1]" not in result
        assert "[2]" not in result
        assert "fact" in result

    def test_keeps_citations_by_default(self) -> None:
        formatter = RichFormatter()
        result = formatter.format_answer("fact[1] here")
        assert "[1]" in result

    def test_code_block_rendered(self) -> None:
        formatter = RichFormatter()
        result = formatter.format_answer("```\ncode_here\n```")
        assert "code_here" in result

    def test_empty_string(self) -> None:
        formatter = RichFormatter()
        assert formatter.format_answer("") == ""


class TestRichFormatterRenderComplete:
    def test_with_references_prints_separator(self) -> None:
        formatter = RichFormatter()
        buffer = StringIO()
        formatter.console.file = buffer
        refs = [WebResult(name="Src", url="https://src.com", snippet="s")]
        answer = Answer(text="Answer", references=refs)
        formatter.render_complete(answer)
        output = buffer.getvalue()
        assert "─" * 50 in output
        assert "References" in output

    def test_strip_references_no_separator(self) -> None:
        formatter = RichFormatter()
        buffer = StringIO()
        formatter.console.file = buffer
        refs = [WebResult(name="Src", url="https://src.com", snippet="s")]
        answer = Answer(text="Answer[1]", references=refs)
        formatter.render_complete(answer, strip_references=True)
        output = buffer.getvalue()
        assert "─" * 50 not in output
        assert "[1]" not in output

    def test_no_references_no_separator(self) -> None:
        formatter = RichFormatter()
        buffer = StringIO()
        formatter.console.file = buffer
        answer = Answer(text="Just text", references=[])
        formatter.render_complete(answer)
        output = buffer.getvalue()
        assert "─" * 50 not in output
        assert "Just text" in output


class TestSSEClientDefaults:
    def test_default_timeout(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"))
        assert client.timeout == 60

    def test_custom_timeout(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), timeout=120)
        assert client.timeout == 120

    def test_default_max_retries(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"))
        assert client.max_retries == 3

    def test_custom_max_retries(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=5)
        assert client.max_retries == 5

    def test_client_initially_none(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"))
        assert client._client is None


class TestSSEClientStreamPost:
    def test_successful_stream_yields_events(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=1)
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.reason = "OK"
        mock_response.headers = {}
        mock_response.iter_lines.return_value = [
            b"event: message",
            b'data: {"result": "ok"}',
            b"",
        ]
        mock_ctx = Mock()
        mock_ctx.__enter__ = Mock(return_value=mock_response)
        mock_ctx.__exit__ = Mock(return_value=False)
        mock_session = Mock()
        mock_session.stream.return_value = mock_ctx
        client._client = mock_session

        results = list(client.stream_post("https://api.example.com", {"query": "test"}))
        assert results == [{"result": "ok"}]

    def test_stream_passes_post_method(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=1)
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.reason = "OK"
        mock_response.headers = {}
        mock_response.iter_lines.return_value = []
        mock_ctx = Mock()
        mock_ctx.__enter__ = Mock(return_value=mock_response)
        mock_ctx.__exit__ = Mock(return_value=False)
        mock_session = Mock()
        mock_session.stream.return_value = mock_ctx
        client._client = mock_session

        list(client.stream_post("https://api.example.com", {"q": "x"}))
        call_args = mock_session.stream.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "https://api.example.com"

    def test_stream_retries_on_500(self) -> None:
        client = SSEClient(auth=AuthContext(token="tok"), max_retries=2)

        fail_response = Mock()
        fail_response.ok = False
        fail_response.status_code = 500
        fail_response.reason = "Internal Server Error"
        fail_response.url = "https://api.example.com"
        fail_response.headers = {}
        fail_response.content = b"error"

        ok_response = Mock()
        ok_response.ok = True
        ok_response.status_code = 200
        ok_response.reason = "OK"
        ok_response.headers = {}
        ok_response.iter_lines.return_value = [
            b"event: msg",
            b'data: {"ok": true}',
            b"",
        ]

        fail_ctx = Mock()
        fail_ctx.__enter__ = Mock(return_value=fail_response)
        fail_ctx.__exit__ = Mock(return_value=False)

        ok_ctx = Mock()
        ok_ctx.__enter__ = Mock(return_value=ok_response)
        ok_ctx.__exit__ = Mock(return_value=False)

        mock_session = Mock()
        mock_session.stream.side_effect = [fail_ctx, ok_ctx]
        client._client = mock_session

        with patch.object(client, "_sleep_for_retry"):
            results = list(client.stream_post("https://api.example.com", {}))
        assert results == [{"ok": True}]
        assert mock_session.stream.call_count == 2


class TestConsumeSleepAttempt:
    def test_initial_none(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        assert handler.consume_sleep_attempt() is None

    def test_returns_and_clears(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        handler._sleep_attempt = 5
        assert handler.consume_sleep_attempt() == 5
        assert handler.consume_sleep_attempt() is None

    def test_handle_http_error_resets_sleep_attempt(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        handler._sleep_attempt = 99
        error = _make_http_error(401)
        with pytest.raises(PerplexityHTTPStatusError):
            handler.handle_http_error(error, attempt=0)
        assert handler._sleep_attempt is None
