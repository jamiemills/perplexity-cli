"""Tests for the Perplexity MCP server helpers."""

from __future__ import annotations

import json
import sys
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from perplexity_cli import mcp_server
from perplexity_cli.api.models import Answer, WebResult
from perplexity_cli.mcp_server import (
    ServerConfig,
    _build_reference,
    _format_json_response,
    _friendly_error_message,
    _load_authentication,
    _normalise_output_format,
    _parse_args,
    _perplexity_deep_info,
    _perplexity_quick_info,
    _render_answer,
    _request_answer,
    _search_mode_for_query_mode,
    _server_meta,
    create_mcp_server,
    main,
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


def test_parse_args_forwards_all_http_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pxcli-mcp",
            "--transport",
            "streamable-http",
            "--host",
            "0.0.0.0",
            "--port",
            "9100",
            "--mount-path",
            "/agent",
        ],
    )

    assert _parse_args() == ServerConfig(
        transport="streamable-http",
        host="0.0.0.0",
        port=9100,
        mount_path="/agent",
    )


# ---------------------------------------------------------------------------
# _normalise_output_format
# ---------------------------------------------------------------------------


def test_normalise_output_format_aliases() -> None:
    assert {
        value: _normalise_output_format(value)
        for value in ("json", "markdown", "md", "plain", "text")
    } == {
        "json": "json",
        "markdown": "markdown",
        "md": "markdown",
        "plain": "plain",
        "text": "plain",
    }


def test_normalise_output_format_case_insensitive_and_whitespace() -> None:
    assert _normalise_output_format("  JSON  ") == "json"
    assert _normalise_output_format("MarkDown") == "markdown"


def test_normalise_output_format_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="output_format must be one of"):
        _normalise_output_format("xml")


def test_invalid_user_inputs_raise_validation_errors() -> None:
    with pytest.raises(ValueError):
        _normalise_output_format("xml")
    with pytest.raises(ValueError):
        run_mcp_query(" ", "quick", "plain")


# ---------------------------------------------------------------------------
# _search_mode_for_query_mode
# ---------------------------------------------------------------------------


def test_search_mode_mapping() -> None:
    assert _search_mode_for_query_mode("quick") == "standard"  # type: ignore[arg-type]  # owner: test-infrastructure; reason: exercise the public string values accepted by the MCP query-mode boundary
    assert _search_mode_for_query_mode("deep") == "multi_step"  # type: ignore[arg-type]  # owner: test-infrastructure; reason: exercise the public string values accepted by the MCP query-mode boundary


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
    assert meta["anthropic/maxResultSizeChars"] == 120000


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


def test_create_mcp_server_forwards_custom_http_configuration() -> None:
    """Custom host, port and mount path reach the FastMCP settings."""
    server = create_mcp_server(
        ServerConfig(transport="streamable-http", host="0.0.0.0", port=9001, mount_path="/api/mcp")
    )

    assert server.settings.host == "0.0.0.0"
    assert server.settings.port == 9001
    assert server.settings.streamable_http_path == "/api/mcp"


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


def test_run_mcp_query_builds_complete_structured_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP results preserve mode, answer, rendering and reference counts."""
    answer = Answer(
        text="Research answer",
        references=[WebResult(name="Source", url="https://source.test", snippet="Excerpt")],
    )
    request = Mock(return_value=answer)
    render = Mock(return_value="rendered")
    monkeypatch.setattr("perplexity_cli.mcp_server._request_answer", request)
    monkeypatch.setattr("perplexity_cli.mcp_server._render_answer", render)

    result = run_mcp_query("  Research this  ", "deep", "md")

    request.assert_called_once_with("Research this", "deep")
    render.assert_called_once_with(answer, "markdown")
    assert result.model_dump() == {
        "mode": "deep",
        "output_format": "markdown",
        "answer": "Research answer",
        "rendered_response": "rendered",
        "reference_count": 1,
        "references": [{"title": "Source", "url": "https://source.test", "snippet": "Excerpt"}],
    }


def test_request_answer_passes_auth_and_search_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deep mode requests use the multi-step upstream search mode."""
    monkeypatch.setattr(
        "perplexity_cli.mcp_server._load_authentication",
        lambda: ("token", {"cf": "cookie"}),
    )
    api = Mock()
    api.get_complete_answer.return_value = Answer(text="answer", references=[])
    api_context = MagicMock()
    api_context.__enter__.return_value = api
    api_context.__exit__.return_value = False
    factory = Mock(return_value=api_context)
    monkeypatch.setattr("perplexity_cli.mcp_server.PerplexityAPI", factory)

    result = _request_answer("question", "deep")

    assert result.text == "answer"
    factory.assert_called_once_with("token", {"cf": "cookie"})
    api.get_complete_answer.assert_called_once_with(
        "question", search_implementation_mode="multi_step"
    )


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


def test_format_json_response_has_complete_schema() -> None:
    answer = Answer(
        text="Hello",
        references=[WebResult(name="R", url="http://x.com", snippet=None)],
    )
    expected = {
        "answer": "Hello",
        "references": [{"title": "R", "url": "http://x.com", "snippet": None}],
    }

    assert json.loads(_format_json_response(answer)) == expected


def test_render_answer_json() -> None:
    answer = Answer(text="Hi", references=[])
    result = _render_answer(answer, "json")
    assert '"answer": "Hi"' in result


def test_render_answer_markdown() -> None:
    answer = Answer(text="Hi", references=[])
    result = _render_answer(answer, "markdown")
    assert "Hi" in result


def test_render_answer_dispatches_json_and_text_formats(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = Answer(text="Hi", references=[])
    json_renderer = Mock(return_value="json result")
    text_renderer = Mock(return_value="text result")
    monkeypatch.setattr("perplexity_cli.mcp_server._format_json_response", json_renderer)
    monkeypatch.setattr("perplexity_cli.mcp_server._format_text_response", text_renderer)

    assert _render_answer(answer, "json") == "json result"
    assert _render_answer(answer, "markdown") == "text result"
    json_renderer.assert_called_once_with(answer)
    text_renderer.assert_called_once_with(answer, "markdown")


def test_load_authentication_returns_tuple(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "perplexity_cli.mcp_server.load_token_optional",
        lambda tm, logger: ("fake-token", None),
    )
    result = _load_authentication()
    assert result == ("fake-token", None)


def test_load_authentication_uses_token_manager_and_module_logger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = object()
    loader = Mock(return_value=("token", {"session": "cookie"}))
    monkeypatch.setattr("perplexity_cli.mcp_server.TokenManager", Mock(return_value=manager))
    monkeypatch.setattr("perplexity_cli.mcp_server.load_token_optional", loader)

    assert _load_authentication() == ("token", {"session": "cookie"})
    loader.assert_called_once_with(manager, mcp_server._LOGGER)


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

    mock_ctx = AsyncMock()
    result = await _perplexity_quick_info(query="test", output_format="plain", ctx=mock_ctx)

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

    mock_ctx = AsyncMock()
    result = await _perplexity_deep_info(
        query="research question", output_format="plain", ctx=mock_ctx
    )

    assert result.answer == "deep result"
    mock_ctx.info.assert_called_once()
    assert mock_ctx.report_progress.call_count == 2


@pytest.mark.asyncio
async def test_quick_info_without_context_skips_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tool calls without an MCP context still return the query result."""
    run_query = Mock(return_value="result")
    monkeypatch.setattr("perplexity_cli.mcp_server.run_mcp_query", run_query)

    result = await _perplexity_quick_info("question", "plain", None)

    assert result == "result"
    run_query.assert_called_once_with("question", "quick", "plain")


# ---------------------------------------------------------------------------
# main — config forwarding
# ---------------------------------------------------------------------------


def test_main_forwards_config_to_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() passes the parsed config to create_mcp_server and run exactly."""
    config = ServerConfig(
        transport="streamable-http", host="127.0.0.1", port=9876, mount_path="/custom"
    )
    monkeypatch.setattr("perplexity_cli.mcp_server._parse_args", lambda: config)
    server_mock = Mock()
    monkeypatch.setattr(
        "perplexity_cli.mcp_server.create_mcp_server", Mock(return_value=server_mock)
    )

    main()

    from perplexity_cli.mcp_server import create_mcp_server

    create_mcp_server.assert_called_once_with(config)
    server_mock.run.assert_called_once_with(transport="streamable-http", mount_path="/custom")
