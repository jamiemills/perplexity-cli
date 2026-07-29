"""Round 2 mutation-killing tests for api/, utils/, formatting/, mcp_server, attachments/."""

from __future__ import annotations

import json
import logging

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
    SSEParser,
    _coerce_header_pair,
    _is_deep_research_request,
    _is_deep_research_value,
    _is_json_object,
    _require_bool,
    _require_bytes_or_str,
    _require_int,
    _require_json_object_or_none,
    _require_str,
)
from perplexity_cli.api.models import (
    Answer,
    Block,
    QueryParams,
    QueryRequest,
    SSEMessage,
    WebResult,
)
from perplexity_cli.config.defaults import (
    DEFAULT_DEEP_RESEARCH_TIMEOUT,
    DEFAULT_MAX_RETRIES,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_UPLOAD_TIMEOUT,
)
from perplexity_cli.mcp_server import (
    _DEFAULT_HOST,
    _DEFAULT_PATH,
    _DEFAULT_PORT,
    _TOOL_OUTPUT_LIMIT,
    MCPQueryResult,
    ServerConfig,
    _format_json_response,
    _friendly_error_message,
    _normalise_output_format,
    _render_answer,
    _search_mode_for_query_mode,
    _server_meta,
)
from perplexity_cli.utils.cookies import to_curl_cffi_cookies
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    SimpleRequest,
    SimpleResponse,
    UpstreamSchemaError,
)
from perplexity_cli.utils.http_headers import build_perplexity_headers
from perplexity_cli.utils.logging import (
    redact_mapping_keys,
    redact_path,
    redact_response_text,
    redact_text,
    redact_url,
)
from perplexity_cli.utils.retry import (
    get_backoff_delay,
    get_retry_after_delay,
    is_retryable_error,
)
from perplexity_cli.utils.version import get_api_version


def _make_http_error(
    status: int, headers: dict[str, str] | None = None
) -> PerplexityHTTPStatusError:
    request = SimpleRequest(method="POST", url="https://www.perplexity.ai/api")
    response = SimpleResponse(
        status_code=status, headers=headers or {}, text="error body", request=request
    )
    return PerplexityHTTPStatusError(f"HTTP Error {status}", request=request, response=response)


class TestClientConstants:
    def test_http_status_unauthorised_is_401(self) -> None:
        assert HTTP_STATUS_UNAUTHORISED == 401

    def test_http_status_forbidden_is_403(self) -> None:
        assert HTTP_STATUS_FORBIDDEN == 403

    def test_http_status_too_many_requests_is_429(self) -> None:
        assert HTTP_STATUS_TOO_MANY_REQUESTS == 429

    def test_deep_research_timeout_mode_is_multi_step(self) -> None:
        assert DEEP_RESEARCH_TIMEOUT_MODE == "multi_step"

    def test_header_pair_size_is_2(self) -> None:
        assert HEADER_PAIR_SIZE == 2

    def test_deep_research_mode_keys_exact(self) -> None:
        assert DEEP_RESEARCH_MODE_KEYS == ("searchModeOverride", "search_mode", "workflow_key")

    def test_deep_research_mode_values_exact(self) -> None:
        assert frozenset({"research", "deep_research", "RESEARCH"}) == DEEP_RESEARCH_MODE_VALUES

    def test_default_request_timeout_is_60(self) -> None:
        assert DEFAULT_REQUEST_TIMEOUT == 60

    def test_default_deep_research_timeout_is_360(self) -> None:
        assert DEFAULT_DEEP_RESEARCH_TIMEOUT == 360

    def test_default_max_retries_is_3(self) -> None:
        assert DEFAULT_MAX_RETRIES == 3

    def test_default_upload_timeout_is_300(self) -> None:
        assert DEFAULT_UPLOAD_TIMEOUT == 300


class TestIsDeepResearchValue:
    def test_research_string(self) -> None:
        assert _is_deep_research_value("research") is True

    def test_deep_research_string(self) -> None:
        assert _is_deep_research_value("deep_research") is True

    def test_research_uppercase(self) -> None:
        assert _is_deep_research_value("RESEARCH") is True

    def test_standard_not_deep(self) -> None:
        assert _is_deep_research_value("standard") is False

    def test_non_string_not_deep(self) -> None:
        assert _is_deep_research_value(42) is False
        assert _is_deep_research_value(None) is False

    def test_empty_string_not_deep(self) -> None:
        assert _is_deep_research_value("") is False


class TestIsDeepResearchRequest:
    def test_multi_step_mode(self) -> None:
        assert _is_deep_research_request({"search_implementation_mode": "multi_step"}) is True

    def test_standard_mode_not_deep(self) -> None:
        assert _is_deep_research_request({"search_implementation_mode": "standard"}) is False

    def test_search_mode_override_research(self) -> None:
        assert _is_deep_research_request({"searchModeOverride": "research"}) is True

    def test_search_mode_key_deep_research(self) -> None:
        assert _is_deep_research_request({"search_mode": "deep_research"}) is True

    def test_workflow_key_research_uppercase(self) -> None:
        assert _is_deep_research_request({"workflow_key": "RESEARCH"}) is True

    def test_empty_params_not_deep(self) -> None:
        assert _is_deep_research_request({}) is False

    def test_unrelated_key_not_deep(self) -> None:
        assert _is_deep_research_request({"other_key": "research"}) is False


class TestSSEParserParseLine:
    def test_event_prefix_strips_6_chars(self) -> None:
        event_type, data_lines = SSEParser._parse_line("event: message", None, [])
        assert event_type == "message"
        assert data_lines == []

    def test_data_prefix_strips_5_chars(self) -> None:
        event_type, data_lines = SSEParser._parse_line("data: hello", None, [])
        assert event_type is None
        assert data_lines == ["hello"]

    def test_data_appends_to_existing(self) -> None:
        event_type, data_lines = SSEParser._parse_line("data: world", "msg", ["hello"])
        assert data_lines == ["hello", "world"]

    def test_unknown_prefix_ignored(self) -> None:
        event_type, data_lines = SSEParser._parse_line("id: 123", "evt", ["d"])
        assert event_type == "evt"
        assert data_lines == ["d"]

    def test_event_with_extra_whitespace(self) -> None:
        event_type, _ = SSEParser._parse_line("event:   spaced  ", None, [])
        assert event_type == "spaced"


class TestSSEParserYieldEvent:
    def test_joins_data_lines_with_newline(self) -> None:
        result = SSEParser._yield_event(['{"key":', '"value"}'])
        assert result == {"key": "value"}

    def test_invalid_json_raises_upstream_schema_error(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="Failed to parse SSE data as JSON"):
            SSEParser._yield_event(["not json"])

    def test_non_object_json_raises(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="SSE data must decode to a JSON object"):
            SSEParser._yield_event(["[1, 2, 3]"])

    def test_error_message_truncates_at_100_chars(self) -> None:
        long_data = "x" * 200
        with pytest.raises(UpstreamSchemaError) as exc_info:
            SSEParser._yield_event([long_data])
        assert len(long_data[:100]) == 100
        assert "x" * 100 in str(exc_info.value)
        assert "x" * 101 not in str(exc_info.value)


class TestSSEParserAccumulateLine:
    def test_empty_line_with_event_and_data_yields(self) -> None:
        event_type, data_lines, event = SSEParser._accumulate_line("", "msg", ['{"a": 1}'])
        assert event_type is None
        assert data_lines == []
        assert event == {"a": 1}

    def test_empty_line_without_event_returns_none(self) -> None:
        event_type, data_lines, event = SSEParser._accumulate_line("", None, ['{"a": 1}'])
        assert event is None

    def test_empty_line_without_data_returns_none(self) -> None:
        event_type, data_lines, event = SSEParser._accumulate_line("", "msg", [])
        assert event is None

    def test_non_empty_line_returns_none_event(self) -> None:
        _, _, event = SSEParser._accumulate_line("data: test", None, [])
        assert event is None


class TestRetryHandler:
    def test_401_raises_immediately(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(401)
        with pytest.raises(PerplexityHTTPStatusError, match="Authentication failed"):
            handler.handle_http_error(error, attempt=0)

    def test_401_error_message_exact(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(401)
        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            handler.handle_http_error(error, attempt=0)
        assert "Token may be invalid or expired" in str(exc_info.value)

    def test_403_retries_when_attempts_remain(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(403)
        wait = handler.handle_http_error(error, attempt=0)
        assert wait > 0

    def test_403_raises_on_last_attempt(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(403)
        with pytest.raises(PerplexityHTTPStatusError, match="Access forbidden"):
            handler.handle_http_error(error, attempt=2)

    def test_403_boundary_attempt_equals_max_minus_1(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(403)
        with pytest.raises(PerplexityHTTPStatusError):
            handler.handle_http_error(error, attempt=2)

    def test_429_retries_when_attempts_remain(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(429)
        wait = handler.handle_http_error(error, attempt=0)
        assert wait > 0

    def test_429_raises_rate_limit_message_on_exhaustion(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(429)
        with pytest.raises(PerplexityHTTPStatusError, match="Rate limit exceeded"):
            handler.handle_http_error(error, attempt=2)

    def test_500_retries_when_attempts_remain(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(500)
        wait = handler.handle_http_error(error, attempt=1)
        assert wait > 0

    def test_500_raises_on_exhaustion(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(500)
        with pytest.raises(PerplexityHTTPStatusError):
            handler.handle_http_error(error, attempt=2)

    def test_consume_sleep_attempt_clears(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(403)
        handler.handle_http_error(error, attempt=0)
        first = handler.consume_sleep_attempt()
        assert first is not None
        second = handler.consume_sleep_attempt()
        assert second is None

    def test_retry_after_header_respected(self) -> None:
        handler = RetryHandler(logging.getLogger("test"), max_retries=3)
        error = _make_http_error(429, headers={"Retry-After": "5"})
        wait = handler.handle_http_error(error, attempt=0)
        assert wait == pytest.approx(5.0)


class TestRetryUtilities:
    def test_is_retryable_500(self) -> None:
        assert is_retryable_error(_make_http_error(500)) is True

    def test_is_retryable_502(self) -> None:
        assert is_retryable_error(_make_http_error(502)) is True

    def test_is_retryable_499_not(self) -> None:
        assert is_retryable_error(_make_http_error(499)) is False

    def test_is_retryable_429(self) -> None:
        assert is_retryable_error(_make_http_error(429)) is True

    def test_is_retryable_428_not(self) -> None:
        assert is_retryable_error(_make_http_error(428)) is False

    def test_is_retryable_401_not(self) -> None:
        assert is_retryable_error(_make_http_error(401)) is False

    def test_is_retryable_request_error(self) -> None:
        assert is_retryable_error(PerplexityRequestError("timeout")) is True

    def test_is_retryable_generic_exception_not(self) -> None:
        assert is_retryable_error(RuntimeError("other")) is False

    def test_backoff_delay_attempt_0(self) -> None:
        delay = get_backoff_delay(0, base_delay=1.0, max_delay=60.0, jitter_factor=0.0)
        assert delay == pytest.approx(1.0)

    def test_backoff_delay_attempt_1(self) -> None:
        delay = get_backoff_delay(1, base_delay=1.0, max_delay=60.0, jitter_factor=0.0)
        assert delay == pytest.approx(2.0)

    def test_backoff_delay_attempt_2(self) -> None:
        delay = get_backoff_delay(2, base_delay=1.0, max_delay=60.0, jitter_factor=0.0)
        assert delay == pytest.approx(4.0)

    def test_backoff_delay_capped_at_max(self) -> None:
        delay = get_backoff_delay(10, base_delay=1.0, max_delay=60.0, jitter_factor=0.0)
        assert delay == pytest.approx(60.0)

    def test_backoff_delay_jitter_bounded(self) -> None:
        for _ in range(50):
            delay = get_backoff_delay(3, base_delay=1.0, max_delay=60.0, jitter_factor=0.1)
            assert 0.0 <= delay <= 60.0
            assert delay >= 8.0 * 0.9 - 0.01
            assert delay <= 8.0 * 1.1 + 0.01

    def test_backoff_delay_negative_jitter_factor(self) -> None:
        delay = get_backoff_delay(2, base_delay=1.0, max_delay=60.0, jitter_factor=-0.5)
        assert delay == pytest.approx(4.0)

    def test_retry_after_delay_present(self) -> None:
        error = _make_http_error(429, headers={"Retry-After": "10"})
        assert get_retry_after_delay(error) == pytest.approx(10.0)

    def test_retry_after_delay_lowercase_header(self) -> None:
        error = _make_http_error(429, headers={"retry-after": "7"})
        assert get_retry_after_delay(error) == pytest.approx(7.0)

    def test_retry_after_delay_absent(self) -> None:
        error = _make_http_error(429, headers={})
        assert get_retry_after_delay(error) is None

    def test_retry_after_delay_invalid_value(self) -> None:
        error = _make_http_error(429, headers={"Retry-After": "not-a-number"})
        assert get_retry_after_delay(error) is None

    def test_retry_after_delay_negative_clamped_to_zero(self) -> None:
        error = _make_http_error(429, headers={"Retry-After": "-5"})
        assert get_retry_after_delay(error) == pytest.approx(0.0)

    def test_retry_after_delay_non_http_error(self) -> None:
        assert get_retry_after_delay(RuntimeError("x")) is None


class TestBuildPerplexityHeaders:
    def test_content_type_default(self) -> None:
        headers = build_perplexity_headers("tok", header_extras=(None, "https://ppl.example"))
        assert headers["Content-Type"] == "application/json"

    def test_content_type_custom(self) -> None:
        headers = build_perplexity_headers(
            "tok", content_type="multipart/form-data", header_extras=(None, "https://ppl.example")
        )
        assert headers["Content-Type"] == "multipart/form-data"

    def test_authorization_bearer_prefix(self) -> None:
        headers = build_perplexity_headers(
            "my-jwt-token", header_extras=(None, "https://ppl.example")
        )
        assert headers["Authorization"] == "Bearer my-jwt-token"

    def test_no_authorization_without_token(self) -> None:
        headers = build_perplexity_headers(None, header_extras=(None, "https://ppl.example"))
        assert "Authorization" not in headers

    def test_origin_header(self) -> None:
        headers = build_perplexity_headers("tok", header_extras=(None, "https://www.perplexity.ai"))
        assert headers["Origin"] == "https://www.perplexity.ai"

    def test_referer_header_trailing_slash(self) -> None:
        headers = build_perplexity_headers("tok", header_extras=(None, "https://www.perplexity.ai"))
        assert headers["Referer"] == "https://www.perplexity.ai/"

    def test_referer_strips_existing_trailing_slash(self) -> None:
        headers = build_perplexity_headers(
            "tok", header_extras=(None, "https://www.perplexity.ai/")
        )
        assert headers["Referer"] == "https://www.perplexity.ai/"

    def test_csrf_token_from_cookies(self) -> None:
        cookies = {"csrftoken": "abc123", "other": "val"}
        headers = build_perplexity_headers(
            "tok", cookies=cookies, header_extras=(None, "https://x.com")
        )
        assert headers["X-CSRFToken"] == "abc123"

    def test_no_csrf_without_csrftoken_cookie(self) -> None:
        cookies = {"session": "val"}
        headers = build_perplexity_headers(
            "tok", cookies=cookies, header_extras=(None, "https://x.com")
        )
        assert "X-CSRFToken" not in headers

    def test_accept_header_from_extras(self) -> None:
        headers = build_perplexity_headers(
            "tok", header_extras=("text/event-stream", "https://x.com")
        )
        assert headers["Accept"] == "text/event-stream"

    def test_no_accept_header_when_none(self) -> None:
        headers = build_perplexity_headers("tok", header_extras=(None, "https://x.com"))
        assert "Accept" not in headers


class TestCookies:
    def test_none_returns_empty_dict(self) -> None:
        result = to_curl_cffi_cookies(None)
        assert result == {}

    def test_empty_dict_returns_empty_dict(self) -> None:
        result = to_curl_cffi_cookies({})
        assert result == {}

    def test_regular_cookies_returned(self) -> None:
        result = to_curl_cffi_cookies({"session": "abc"})
        assert result != {}

    def test_secure_prefix_cookies(self) -> None:
        result = to_curl_cffi_cookies({"__Secure-token": "val"})
        assert result != {}

    def test_host_prefix_cookies(self) -> None:
        result = to_curl_cffi_cookies({"__Host-token": "val"})
        assert result != {}


class TestRedactionHelpers:
    def test_redact_url_normal(self) -> None:
        assert (
            redact_url("https://www.perplexity.ai/api/query")
            == "https://www.perplexity.ai/<redacted>"
        )

    def test_redact_url_http(self) -> None:
        assert redact_url("http://example.com/path") == "http://example.com/<redacted>"

    def test_redact_url_empty(self) -> None:
        assert redact_url("") == "<empty-url>"

    def test_redact_url_none(self) -> None:
        assert redact_url(None) == "<empty-url>"

    def test_redact_url_no_scheme(self) -> None:
        assert redact_url("not-a-url") == "<redacted-url>"

    def test_redact_text_empty(self) -> None:
        assert redact_text("") == "<empty>"

    def test_redact_text_none(self) -> None:
        assert redact_text(None) == "<empty>"

    def test_redact_text_short(self) -> None:
        assert redact_text("hello") == "<redacted:5 chars>"

    def test_redact_text_truncated_at_max(self) -> None:
        assert redact_text("x" * 100, max_length=32) == "<redacted:32 chars>"

    def test_redact_text_exact_max(self) -> None:
        assert redact_text("x" * 32, max_length=32) == "<redacted:32 chars>"

    def test_redact_mapping_keys_none(self) -> None:
        assert redact_mapping_keys(None) == "<none>"

    def test_redact_mapping_keys_empty(self) -> None:
        assert redact_mapping_keys({}) == "<none>"

    def test_redact_mapping_keys_with_entries(self) -> None:
        assert redact_mapping_keys({"a": 1, "b": 2}) == "<redacted:2 keys>"

    def test_redact_path_none(self) -> None:
        assert redact_path(None) == "<none>"

    def test_redact_path_preserves_filename(self) -> None:
        result = redact_path("/home/user/secret/token.json")
        assert "token.json" in result
        assert "/home/user" not in result

    def test_redact_response_text_delegates_to_redact_text_max_0(self) -> None:
        assert redact_response_text("some text") == "<redacted:0 chars>"

    def test_redact_response_text_none(self) -> None:
        assert redact_response_text(None) == "<empty>"


class TestGetApiVersion:
    def test_returns_2_18(self) -> None:
        assert get_api_version() == "2.18"


class TestQueryParamsDefaults:
    def test_language_default(self) -> None:
        assert QueryParams().language == "en-US"

    def test_timezone_default(self) -> None:
        assert QueryParams().timezone == "Europe/London"

    def test_search_focus_default(self) -> None:
        assert QueryParams().search_focus == "internet"

    def test_mode_default(self) -> None:
        assert QueryParams().mode == "copilot"

    def test_model_preference_default(self) -> None:
        assert QueryParams().model_preference == "pplx_pro"

    def test_sources_default(self) -> None:
        assert QueryParams().sources == ["web"]

    def test_search_implementation_mode_default(self) -> None:
        assert QueryParams().search_implementation_mode == "standard"

    def test_is_related_query_default_false(self) -> None:
        assert QueryParams().is_related_query is False

    def test_is_sponsored_default_false(self) -> None:
        assert QueryParams().is_sponsored is False

    def test_prompt_source_default(self) -> None:
        assert QueryParams().prompt_source == "user"

    def test_query_source_default(self) -> None:
        assert QueryParams().query_source == "home"

    def test_is_incognito_default_false(self) -> None:
        assert QueryParams().is_incognito is False

    def test_use_schematized_api_default_true(self) -> None:
        assert QueryParams().use_schematized_api is True

    def test_skip_search_enabled_default_true(self) -> None:
        assert QueryParams().skip_search_enabled is True

    def test_should_ask_for_mcp_tool_confirmation_default_true(self) -> None:
        assert QueryParams().should_ask_for_mcp_tool_confirmation is True

    def test_validate_search_mode_standard_ok(self) -> None:
        params = QueryParams(search_implementation_mode="standard")
        assert params.search_implementation_mode == "standard"

    def test_validate_search_mode_multi_step_ok(self) -> None:
        params = QueryParams(search_implementation_mode="multi_step")
        assert params.search_implementation_mode == "multi_step"

    def test_validate_search_mode_invalid_raises(self) -> None:
        with pytest.raises(
            ValueError, match='search_implementation_mode must be "standard" or "multi_step"'
        ):
            QueryParams(search_implementation_mode="turbo")


class TestQueryRequestToDict:
    def test_exact_structure(self) -> None:
        params = QueryParams(frontend_uuid="u1", frontend_context_uuid="u2")
        request = QueryRequest(query_str="test query", params=params)
        result = request.to_dict()
        assert result["query_str"] == "test query"
        assert isinstance(result["params"], dict)
        assert result["params"]["frontend_uuid"] == "u1"
        assert result["params"]["frontend_context_uuid"] == "u2"


class TestBlockExtractText:
    def test_web_result_block_returns_none(self) -> None:
        block = Block(intended_usage="web_results", content={"web_result_block": {"results": []}})
        assert block.extract_text() is None

    def test_markdown_block_chunks(self) -> None:
        block = Block(
            intended_usage="ask_text",
            content={"markdown_block": {"chunks": ["Hello ", "world"]}},
        )
        assert block.extract_text() == "Hello world"

    def test_text_field_direct(self) -> None:
        block = Block(intended_usage="ask_text", content={"text": "direct answer"})
        assert block.extract_text() == "direct answer"

    def test_diff_block_patches(self) -> None:
        block = Block(
            intended_usage="ask_text",
            content={"diff_block": {"patches": [{"value": "patched text"}]}},
        )
        assert block.extract_text() == "patched text"

    def test_diff_block_nested_value_text(self) -> None:
        block = Block(
            intended_usage="ask_text",
            content={"diff_block": {"patches": [{"value": {"text": "nested"}}]}},
        )
        assert block.extract_text() == "nested"

    def test_answer_block(self) -> None:
        block = Block(
            intended_usage="ask_text",
            content={"answer_block": {"text": "final answer"}},
        )
        assert block.extract_text() == "final answer"

    def test_empty_content_returns_none(self) -> None:
        block = Block(intended_usage="ask_text", content={})
        assert block.extract_text() is None


class TestBlockExtractPlanInfo:
    def test_pro_search_steps_usage(self) -> None:
        block = Block(
            intended_usage="pro_search_steps",
            content={"plan_block": {"progress": "searching", "eta_seconds_remaining": 10}},
        )
        info = block.extract_plan_info()
        assert info is not None
        assert info["progress"] == "searching"
        assert info["eta_seconds"] == 10

    def test_plan_usage(self) -> None:
        block = Block(
            intended_usage="plan",
            content={"plan_block": {"pct_complete": 50, "goals": ["g1"]}},
        )
        info = block.extract_plan_info()
        assert info is not None
        assert info["pct_complete"] == 50
        assert info["goals"] == ["g1"]

    def test_wrong_usage_returns_none(self) -> None:
        block = Block(intended_usage="ask_text", content={"plan_block": {"progress": "x"}})
        assert block.extract_plan_info() is None

    def test_empty_plan_block_returns_none(self) -> None:
        block = Block(intended_usage="plan", content={"plan_block": {}})
        assert block.extract_plan_info() is None

    def test_missing_plan_block_returns_none(self) -> None:
        block = Block(intended_usage="plan", content={})
        assert block.extract_plan_info() is None


class TestBlockExtractWebResults:
    def test_web_results_usage(self) -> None:
        block = Block(
            intended_usage="web_results",
            content={
                "web_result_block": {
                    "web_results": [{"name": "Src", "url": "https://x.com", "snippet": "s"}]
                }
            },
        )
        results = block.extract_web_results()
        assert results is not None
        assert len(results) == 1
        assert results[0].name == "Src"

    def test_wrong_usage_returns_none(self) -> None:
        block = Block(intended_usage="ask_text", content={"web_result_block": {"web_results": []}})
        assert block.extract_web_results() is None

    def test_missing_web_result_block_returns_none(self) -> None:
        block = Block(intended_usage="web_results", content={})
        assert block.extract_web_results() is None


class TestSSEMessage:
    def test_extract_answer_text_ask_text_block(self) -> None:
        msg = SSEMessage.model_validate(
            {
                "blocks": [
                    {"intended_usage": "ask_text", "text": "the answer"},
                ]
            }
        )
        assert msg.extract_answer_text() == "the answer"

    def test_extract_answer_text_skips_non_ask_text(self) -> None:
        msg = SSEMessage.model_validate(
            {
                "blocks": [
                    {"intended_usage": "web_results", "text": "not this"},
                    {"intended_usage": "ask_text", "text": "this one"},
                ]
            }
        )
        assert msg.extract_answer_text() == "this one"

    def test_extract_answer_text_no_blocks_returns_none(self) -> None:
        msg = SSEMessage.model_validate({"blocks": []})
        assert msg.extract_answer_text() is None

    def test_describe_block_usages_empty(self) -> None:
        msg = SSEMessage.model_validate({"blocks": []})
        assert msg.describe_block_usages() == "none"

    def test_describe_block_usages_multiple(self) -> None:
        msg = SSEMessage.model_validate(
            {"blocks": [{"intended_usage": "ask_text"}, {"intended_usage": "web_results"}]}
        )
        assert msg.describe_block_usages() == "ask_text,web_results"

    def test_describe_block_usages_missing_usage(self) -> None:
        msg = SSEMessage.model_validate({"blocks": [{"text": "no usage"}]})
        assert msg.describe_block_usages() == "<missing>"

    def test_final_sse_message_default_false(self) -> None:
        msg = SSEMessage.model_validate({"blocks": []})
        assert msg.final_sse_message is False

    def test_text_completed_default_false(self) -> None:
        msg = SSEMessage.model_validate({"blocks": []})
        assert msg.text_completed is False


class TestMCPConstants:
    def test_tool_output_limit(self) -> None:
        assert _TOOL_OUTPUT_LIMIT == 120000

    def test_default_host(self) -> None:
        assert _DEFAULT_HOST == "127.0.0.1"

    def test_default_port(self) -> None:
        assert _DEFAULT_PORT == 8000

    def test_default_path(self) -> None:
        assert _DEFAULT_PATH == "/mcp"

    def test_server_meta_exact_key_and_value(self) -> None:
        meta = _server_meta()
        assert meta == {"anthropic/maxResultSizeChars": 120000}

    def test_server_config_port_bounds(self) -> None:
        config = ServerConfig(port=1)
        assert config.port == 1
        config = ServerConfig(port=65535)
        assert config.port == 65535


class TestMCPNormaliseOutputFormat:
    def test_json_exact(self) -> None:
        assert _normalise_output_format("json") == "json"

    def test_markdown_exact(self) -> None:
        assert _normalise_output_format("markdown") == "markdown"

    def test_md_alias(self) -> None:
        assert _normalise_output_format("md") == "markdown"

    def test_plain_exact(self) -> None:
        assert _normalise_output_format("plain") == "plain"

    def test_text_alias(self) -> None:
        assert _normalise_output_format("text") == "plain"

    def test_error_message_exact(self) -> None:
        with pytest.raises(ValueError, match="output_format must be one of: json, markdown, plain"):
            _normalise_output_format("yaml")


class TestMCPSearchModeMapping:
    def test_quick_maps_to_standard(self) -> None:
        assert _search_mode_for_query_mode("quick") == "standard"

    def test_deep_maps_to_multi_step(self) -> None:
        assert _search_mode_for_query_mode("deep") == "multi_step"


class TestMCPFormatJsonResponse:
    def test_exact_structure(self) -> None:
        answer = Answer(
            text="The answer",
            references=[WebResult(name="Ref", url="https://r.com", snippet="snip")],
        )
        result = json.loads(_format_json_response(answer))
        assert result["answer"] == "The answer"
        assert len(result["references"]) == 1
        assert result["references"][0]["title"] == "Ref"
        assert result["references"][0]["url"] == "https://r.com"
        assert result["references"][0]["snippet"] == "snip"

    def test_indent_2(self) -> None:
        answer = Answer(text="Hi", references=[])
        raw = _format_json_response(answer)
        assert '  "answer"' in raw

    def test_empty_references(self) -> None:
        answer = Answer(text="Hi", references=[])
        result = json.loads(_format_json_response(answer))
        assert result["references"] == []


class TestMCPRenderAnswer:
    def test_json_format(self) -> None:
        answer = Answer(text="test", references=[])
        result = _render_answer(answer, "json")
        parsed = json.loads(result)
        assert parsed["answer"] == "test"

    def test_markdown_format(self) -> None:
        answer = Answer(text="test", references=[])
        result = _render_answer(answer, "markdown")
        assert "test" in result

    def test_plain_format(self) -> None:
        answer = Answer(text="test", references=[])
        result = _render_answer(answer, "plain")
        assert "test" in result


class TestMCPFriendlyErrorMessage:
    def test_http_status_error_passthrough(self) -> None:
        error = _make_http_error(500)
        assert _friendly_error_message(error) == str(error)

    def test_request_error_passthrough(self) -> None:
        error = PerplexityRequestError("connection reset")
        assert _friendly_error_message(error) == "connection reset"

    def test_value_error_passthrough(self) -> None:
        error = ValueError("invalid query")
        assert _friendly_error_message(error) == "invalid query"

    def test_generic_error_prefixed(self) -> None:
        error = RuntimeError("unexpected")
        assert _friendly_error_message(error) == "Perplexity request failed: unexpected"


class TestMCPQueryResultModel:
    def test_fields(self) -> None:
        result = MCPQueryResult(
            mode="quick",
            output_format="plain",
            answer="ans",
            rendered_response="rendered",
            references=[],
            reference_count=0,
        )
        assert result.mode == "quick"
        assert result.output_format == "plain"
        assert result.answer == "ans"
        assert result.rendered_response == "rendered"
        assert result.references == []
        assert result.reference_count == 0


class TestCoerceHeaderPair:
    def test_valid_pair(self) -> None:
        assert _coerce_header_pair(("Content-Type", "application/json"), "ctx") == (
            "Content-Type",
            "application/json",
        )

    def test_wrong_size_raises(self) -> None:
        with pytest.raises(RuntimeError, match="Expected header pair items"):
            _coerce_header_pair(("only-one",), "ctx")

    def test_three_elements_raises(self) -> None:
        with pytest.raises(RuntimeError, match="Expected header pair items"):
            _coerce_header_pair(("a", "b", "c"), "ctx")

    def test_non_sized_raises(self) -> None:
        with pytest.raises(RuntimeError, match="Expected header pair items"):
            _coerce_header_pair(42, "ctx")


class TestRequireHelpers:
    def test_require_str_valid(self) -> None:
        assert _require_str("hello", "ctx") == "hello"

    def test_require_str_invalid(self) -> None:
        with pytest.raises(RuntimeError, match="Expected string transport attribute"):
            _require_str(42, "ctx")

    def test_require_int_valid(self) -> None:
        assert _require_int(200, "ctx") == 200

    def test_require_int_invalid(self) -> None:
        with pytest.raises(RuntimeError, match="Expected integer transport attribute"):
            _require_int("200", "ctx")

    def test_require_bool_valid(self) -> None:
        assert _require_bool(True, "ctx") is True

    def test_require_bool_invalid(self) -> None:
        with pytest.raises(RuntimeError, match="Expected boolean transport attribute"):
            _require_bool(1, "ctx")

    def test_require_bytes_or_str_bytes(self) -> None:
        assert _require_bytes_or_str(b"data", "ctx") == b"data"

    def test_require_bytes_or_str_str(self) -> None:
        assert _require_bytes_or_str("data", "ctx") == "data"

    def test_require_bytes_or_str_invalid(self) -> None:
        with pytest.raises(RuntimeError, match="Expected bytes-or-string transport attribute"):
            _require_bytes_or_str(42, "ctx")

    def test_require_json_object_or_none_none(self) -> None:
        assert _require_json_object_or_none(None, "ctx") is None

    def test_require_json_object_or_none_dict(self) -> None:
        assert _require_json_object_or_none({"key": "val"}, "ctx") == {"key": "val"}

    def test_require_json_object_or_none_invalid(self) -> None:
        with pytest.raises(RuntimeError, match="Expected JSON object transport attribute"):
            _require_json_object_or_none([1, 2], "ctx")

    def test_is_json_object_dict(self) -> None:
        assert _is_json_object({}) is True

    def test_is_json_object_list(self) -> None:
        assert _is_json_object([]) is False

    def test_is_json_object_none(self) -> None:
        assert _is_json_object(None) is False


class TestWebResultValidation:
    def test_non_mapping_raises_upstream_schema_error(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="Malformed web result block"):
            WebResult.model_validate("not a dict")

    def test_list_input_raises(self) -> None:
        with pytest.raises(UpstreamSchemaError):
            WebResult.model_validate(["name", "url"])

    def test_defaults_for_missing_fields(self) -> None:
        result = WebResult.model_validate({})
        assert result.name == ""
        assert result.url == ""
        assert result.snippet is None
        assert result.timestamp is None


class TestSSEMessageValidation:
    def test_non_mapping_raises(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="Malformed SSE message"):
            SSEMessage.model_validate("not a dict")

    def test_blocks_not_list_raises(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="Malformed SSE blocks"):
            SSEMessage.model_validate({"blocks": "not a list"})

    def test_derives_web_results_from_blocks(self) -> None:
        msg = SSEMessage.model_validate(
            {
                "blocks": [
                    {
                        "intended_usage": "web_results",
                        "web_result_block": {
                            "web_results": [{"name": "S", "url": "https://s.com"}]
                        },
                    }
                ]
            }
        )
        assert msg.web_results is not None
        assert len(msg.web_results) == 1
        assert msg.web_results[0].name == "S"


class TestBlockValidation:
    def test_non_mapping_raises(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="Malformed block"):
            Block.model_validate("not a dict")

    def test_flat_payload_restructured(self) -> None:
        block = Block.model_validate({"intended_usage": "ask_text", "text": "hello"})
        assert block.intended_usage == "ask_text"
        assert block.content == {"text": "hello"}

    def test_content_key_passthrough(self) -> None:
        block = Block.model_validate({"intended_usage": "ask_text", "content": {"text": "hi"}})
        assert block.intended_usage == "ask_text"
        assert block.content == {"text": "hi"}


class TestJSONFormatterEnvelope:
    def test_ok_field_true(self) -> None:
        from perplexity_cli.formatting.json import JSONFormatter

        formatter = JSONFormatter()
        answer = Answer(text="test", references=[])
        parsed = json.loads(formatter.format_complete(answer))
        assert parsed["ok"] is True

    def test_command_field_exact(self) -> None:
        from perplexity_cli.formatting.json import JSONFormatter

        formatter = JSONFormatter()
        answer = Answer(text="test", references=[])
        parsed = json.loads(formatter.format_complete(answer))
        assert parsed["command"] == "pxcli query"

    def test_meta_field_none(self) -> None:
        from perplexity_cli.formatting.json import JSONFormatter

        formatter = JSONFormatter()
        answer = Answer(text="test", references=[])
        parsed = json.loads(formatter.format_complete(answer))
        assert parsed["meta"] is None

    def test_next_actions_empty_list(self) -> None:
        from perplexity_cli.formatting.json import JSONFormatter

        formatter = JSONFormatter()
        answer = Answer(text="test", references=[])
        parsed = json.loads(formatter.format_complete(answer))
        assert parsed["next_actions"] == []

    def test_reference_index_starts_at_1(self) -> None:
        from perplexity_cli.formatting.json import JSONFormatter

        formatter = JSONFormatter()
        refs = [
            WebResult(name="A", url="https://a.com", snippet="a"),
            WebResult(name="B", url="https://b.com", snippet="b"),
        ]
        answer = Answer(text="test", references=refs)
        parsed = json.loads(formatter.format_complete(answer))
        assert parsed["result"]["references"][0]["index"] == 1
        assert parsed["result"]["references"][1]["index"] == 2


class TestMarkdownEscapeChars:
    def test_all_special_chars_escaped(self) -> None:
        from perplexity_cli.formatting.markdown import MarkdownFormatter

        special = ["\\", "`", "*", "_", "{", "}", "[", "]", "(", ")", "#", "+", "-", ".", "!"]
        for char in special:
            result = MarkdownFormatter._escape_markdown(f"a{char}b")
            assert f"\\{char}" in result


class TestPlainTextReferences:
    def test_ruler_is_50_chars(self) -> None:
        from perplexity_cli.formatting.plain import PlainTextFormatter

        formatter = PlainTextFormatter()
        refs = [WebResult(name="S", url="https://s.com", snippet="s")]
        result = formatter.format_references(refs)
        assert "─" * 50 in result

    def test_header_underline_matches_length(self) -> None:
        from perplexity_cli.formatting.plain import PlainTextFormatter

        formatter = PlainTextFormatter()
        refs = [WebResult(name="S", url="https://s.com", snippet="s")]
        result = formatter.format_references(refs)
        assert "=" * 10 in result

    def test_empty_references_returns_empty(self) -> None:
        from perplexity_cli.formatting.plain import PlainTextFormatter

        formatter = PlainTextFormatter()
        assert formatter.format_references([]) == ""


class TestUploadManagerHelpers:
    def test_s3_upload_success_status_is_204(self) -> None:
        from perplexity_cli.attachments.upload_manager import _S3_UPLOAD_SUCCESS_STATUS

        assert _S3_UPLOAD_SUCCESS_STATUS == 204

    def test_diagnose_rate_limited(self) -> None:
        from perplexity_cli.attachments.upload_manager import _diagnose_upload_entry_error

        msg = _diagnose_upload_entry_error({"rate_limited": True})
        assert "quota exhausted" in msg
        assert "https://www.perplexity.ai/settings/account" in msg

    def test_diagnose_error_field(self) -> None:
        from perplexity_cli.attachments.upload_manager import _diagnose_upload_entry_error

        msg = _diagnose_upload_entry_error({"error": "server broke"})
        assert msg == "API failed to generate upload URL: server broke"

    def test_diagnose_empty_response(self) -> None:
        from perplexity_cli.attachments.upload_manager import _diagnose_upload_entry_error

        msg = _diagnose_upload_entry_error({})
        assert "empty presigned URL response" in msg

    def test_build_upload_metadata_fields(self) -> None:
        import base64

        from perplexity_cli.attachments.upload_manager import AttachmentUploader
        from perplexity_cli.utils.attachment_models import FileAttachment

        attachment = FileAttachment(
            filename="test.txt",
            content_type="text/plain",
            data=base64.b64encode(b"hello").decode(),
        )
        metadata, uuid_map = AttachmentUploader._build_upload_metadata([attachment])
        assert len(metadata) == 1
        entry = next(iter(metadata.values()))
        assert entry["filename"] == "test.txt"
        assert entry["content_type"] == "text/plain"
        assert entry["source"] == "default"
        assert entry["file_size"] == 5
        assert entry["force_image"] is False
        assert entry["search_mode"] == "search"

    def test_build_s3_form_data_excludes_file_key(self) -> None:
        from perplexity_cli.attachments.upload_manager import AttachmentUploader

        upload_data = {
            "fields": {"key": "path/to/file", "policy": "abc", "file": "should-be-excluded"},
            "s3_object_url": "https://s3.example.com/file",
        }
        form = AttachmentUploader._build_s3_form_data(upload_data)
        assert "file" not in form
        assert form["key"] == "path/to/file"
        assert form["policy"] == "abc"

    def test_validate_s3_object_url_non_string_raises(self) -> None:
        from perplexity_cli.attachments.upload_manager import _validate_s3_object_url

        with pytest.raises(UpstreamSchemaError, match="Malformed S3 object URL"):
            _validate_s3_object_url({"s3_object_url": 123})

    def test_validate_s3_object_url_empty_string_ok(self) -> None:
        from perplexity_cli.attachments.upload_manager import _validate_s3_object_url

        _validate_s3_object_url({"s3_object_url": ""})

    def test_normalise_upload_fields_empty(self) -> None:
        from perplexity_cli.attachments.upload_manager import _normalise_upload_fields

        assert _normalise_upload_fields({}) == {}

    def test_normalise_upload_fields_non_dict(self) -> None:
        from perplexity_cli.attachments.upload_manager import _normalise_upload_fields

        assert _normalise_upload_fields({"fields": "not-a-dict"}) == {}

    def test_normalise_upload_fields_valid(self) -> None:
        from perplexity_cli.attachments.upload_manager import _normalise_upload_fields

        result = _normalise_upload_fields({"fields": {"key": "val"}})
        assert result == {"key": "val"}
