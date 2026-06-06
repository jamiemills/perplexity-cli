"""Tests for the Perplexity MCP server helpers."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from perplexity_cli.api.models import Answer, WebResult
from perplexity_cli.mcp_server import (
    ServerConfig,
    _build_reference,
    _format_json_response,
    _friendly_error_message,
    _load_authentication,
    _normalise_output_format,
    _parse_args,
    _render_answer,
    _search_mode_for_query_mode,
    _server_meta,
    create_mcp_server,
    run_mcp_query,
)
from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError, PerplexityRequestError

# ---------------------------------------------------------------------------
# _parse_args
# ---------------------------------------------------------------------------


def test_parse_args_defaults_to_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["pxcli-mcp"])
    config = _parse_args()
    assert config.transport == "stdio"
    assert config.host == "127.0.0.1"
    assert config.port == 8000


def test_parse_args_streamable_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys, "argv", ["pxcli-mcp", "--transport", "streamable-http", "--port", "9000"]
    )
    config = _parse_args()
    assert config.transport == "streamable-http"
    assert config.port == 9000


# ---------------------------------------------------------------------------
# _normalise_output_format
# ---------------------------------------------------------------------------


def test_normalise_output_format_aliases() -> None:
    assert _normalise_output_format("json") == "json"
    assert _normalise_output_format("markdown") == "markdown"
    assert _normalise_output_format("md") == "markdown"
    assert _normalise_output_format("plain") == "plain"
    assert _normalise_output_format("text") == "plain"


def test_normalise_output_format_case_insensitive_and_whitespace() -> None:
    assert _normalise_output_format("  JSON  ") == "json"
    assert _normalise_output_format("MarkDown") == "markdown"


def test_normalise_output_format_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="output_format must be one of"):
        _normalise_output_format("xml")


# ---------------------------------------------------------------------------
# _search_mode_for_query_mode
# ---------------------------------------------------------------------------


def test_search_mode_mapping() -> None:
    assert _search_mode_for_query_mode("quick") == "standard"  # type: ignore[arg-type]
    assert _search_mode_for_query_mode("deep") == "multi_step"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _friendly_error_message
# ---------------------------------------------------------------------------


def test_friendly_error_http_status() -> None:
    from perplexity_cli.utils.exceptions import SimpleResponse

    response = SimpleResponse(status_code=429, text="rate limited")
    exc = PerplexityHTTPStatusError("rate limited", response=response)
    assert "rate limited" in _friendly_error_message(exc)


def test_friendly_error_request() -> None:
    exc = PerplexityRequestError("network down")
    assert "network down" in _friendly_error_message(exc)


def test_friendly_error_value_error() -> None:
    exc = ValueError("bad input")
    assert "bad input" in _friendly_error_message(exc)


def test_friendly_error_generic() -> None:
    exc = RuntimeError("something broke")
    assert "Perplexity request failed" in _friendly_error_message(exc)


# ---------------------------------------------------------------------------
# _server_meta
# ---------------------------------------------------------------------------


def test_server_meta_returns_dict() -> None:
    meta = _server_meta()
    assert isinstance(meta, dict)
    assert "anthropic/maxResultSizeChars" in meta


# ---------------------------------------------------------------------------
# ServerConfig validation
# ---------------------------------------------------------------------------


def test_server_config_defaults() -> None:
    config = ServerConfig()
    assert config.transport == "stdio"
    assert config.host == "127.0.0.1"
    assert config.port == 8000
    assert config.mount_path == "/mcp"


def test_server_config_rejects_invalid_port() -> None:
    with pytest.raises(ValueError):
        ServerConfig(port=0)
    with pytest.raises(ValueError):
        ServerConfig(port=99999)


# ---------------------------------------------------------------------------
# create_mcp_server — default (stdio) path
# ---------------------------------------------------------------------------


def test_create_mcp_server_defaults() -> None:
    server = create_mcp_server()
    assert server.settings.host == "127.0.0.1"
    assert server.settings.port == 8000


# ---------------------------------------------------------------------------
# run_mcp_query — error paths
# ---------------------------------------------------------------------------


def test_run_mcp_query_handles_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("perplexity_cli.mcp_server._load_authentication", lambda: (None, None))
    api_factory = MagicMock()
    api_factory.return_value.__enter__.side_effect = PerplexityRequestError("boom")
    monkeypatch.setattr("perplexity_cli.mcp_server.PerplexityAPI", api_factory)

    with pytest.raises(RuntimeError, match="boom"):
        run_mcp_query("test", "quick", "plain")


def test_run_mcp_query_wraps_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("perplexity_cli.mcp_server._load_authentication", lambda: (None, None))
    monkeypatch.setattr(
        "perplexity_cli.mcp_server._request_answer",
        lambda query, mode: (_ for _ in ()).throw(ValueError("bad input")),
    )

    with pytest.raises(RuntimeError, match="bad input") as excinfo:
        run_mcp_query("test", "quick", "plain")

    assert isinstance(excinfo.value.__cause__, ValueError)


def test_run_mcp_query_plain_format(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = Answer(text="Plain text.", references=[])
    mock_api = Mock()
    mock_api.get_complete_answer.return_value = answer
    api_factory = MagicMock()
    api_factory.return_value.__enter__.return_value = mock_api
    monkeypatch.setattr("perplexity_cli.mcp_server.PerplexityAPI", api_factory)
    monkeypatch.setattr("perplexity_cli.mcp_server._load_authentication", lambda: (None, None))

    result = run_mcp_query("Query", "quick", "plain")
    assert result.output_format == "plain"
    assert "Plain text." in result.rendered_response


# ---------------------------------------------------------------------------
# Direct helper function tests
# ---------------------------------------------------------------------------


def test_build_reference() -> None:
    ref = _build_reference(WebResult(name="Title", url="http://x.com", snippet="Snippet"))
    assert ref.title == "Title"
    assert ref.url == "http://x.com"
    assert ref.snippet == "Snippet"


def test_build_reference_with_none_snippet() -> None:
    ref = _build_reference(WebResult(name="T", url="http://x.com", snippet=None))
    assert ref.snippet == ""


def test_format_json_response() -> None:
    answer = Answer(
        text="Hello",
        references=[WebResult(name="R", url="http://x.com", snippet="S")],
    )
    result = _format_json_response(answer)
    assert '"answer": "Hello"' in result
    assert '"title": "R"' in result


def test_render_answer_json() -> None:
    answer = Answer(text="Hi", references=[])
    result = _render_answer(answer, "json")
    assert '"answer": "Hi"' in result


def test_render_answer_markdown() -> None:
    answer = Answer(text="Hi", references=[])
    result = _render_answer(answer, "markdown")
    assert "Hi" in result


def test_load_authentication_returns_tuple(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "perplexity_cli.mcp_server.load_token_optional",
        lambda tm, logger: ("fake-token", None),
    )
    result = _load_authentication()
    assert result == ("fake-token", None)


# ---------------------------------------------------------------------------
# run_mcp_query — input validation
# ---------------------------------------------------------------------------


def test_run_mcp_query_rejects_empty_query() -> None:
    with pytest.raises(ValueError, match="query must not be empty"):
        run_mcp_query("", "quick", "plain")

    with pytest.raises(ValueError, match="query must not be empty"):
        run_mcp_query("   ", "quick", "plain")


# ---------------------------------------------------------------------------
# create_mcp_server — tool ctx paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quick_info_reports_progress_via_ctx(monkeypatch: pytest.MonkeyPatch) -> None:
    """Progress is reported through the MCP context when ctx is provided."""
    monkeypatch.setattr(
        "perplexity_cli.mcp_server._request_answer",
        lambda q, m: Answer(text="test", references=[]),
    )
    server = create_mcp_server()
    tool = server._tool_manager._tools["perplexity_quick_info"]
    fn = tool.fn

    mock_ctx = AsyncMock()
    result = await fn(query="test", output_format="plain", ctx=mock_ctx)

    assert result.answer == "test"
    mock_ctx.info.assert_called_once()
    assert mock_ctx.report_progress.call_count == 2


@pytest.mark.asyncio
async def test_deep_info_reports_progress_via_ctx(monkeypatch: pytest.MonkeyPatch) -> None:
    """Progress is reported for deep research when ctx is provided."""
    monkeypatch.setattr(
        "perplexity_cli.mcp_server._request_answer",
        lambda q, m: Answer(text="deep result", references=[]),
    )
    server = create_mcp_server()
    tool = server._tool_manager._tools["perplexity_deep_info"]
    fn = tool.fn

    mock_ctx = AsyncMock()
    result = await fn(query="research question", output_format="plain", ctx=mock_ctx)

    assert result.answer == "deep result"
    mock_ctx.info.assert_called_once()
    assert mock_ctx.report_progress.call_count == 2
