"""MCP server for exposing Perplexity query tools to coding agents."""

from __future__ import annotations

import argparse
import json
from typing import TYPE_CHECKING, Annotated, Literal, cast

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from pydantic import BaseModel, Field

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import Answer
from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.auth.utils import load_token_optional
from perplexity_cli.formatting import get_formatter
from perplexity_cli.formatting.base import Formatter
from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError, PerplexityRequestError
from perplexity_cli.utils.logging import get_logger

if TYPE_CHECKING:
    from perplexity_cli.api.models import WebResult

OutputFormat = Literal["json", "markdown", "plain"]
QueryMode = Literal["quick", "deep"]
Transport = Literal["stdio", "streamable-http"]

_LOGGER = get_logger(__name__)
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000
_DEFAULT_PATH = "/mcp"
_SERVER_INSTRUCTIONS = (
    "Use `perplexity_quick_info` for fast lookups, short explanations, fact checks, and "
    "recent-information questions. Use `perplexity_deep_info` for broader research, "
    "comparisons, timelines, or synthesis across sources where a quick answer may be too "
    "shallow. Prefer `output_format=json` when another tool or agent needs structured fields, "
    "`markdown` for readable summaries, and `plain` for compact raw text."
)
_TOOL_OUTPUT_LIMIT = 120000


class MCPReference(BaseModel):
    """Reference included with a Perplexity answer."""

    title: str = Field(description="Reference title from Perplexity.")
    url: str = Field(description="Reference URL.")
    snippet: str = Field(description="Reference snippet or excerpt.")


class MCPQueryResult(BaseModel):
    """Structured query result returned by the MCP tools."""

    mode: QueryMode = Field(description="Whether the tool used quick or deep research mode.")
    output_format: OutputFormat = Field(description="Requested output rendering format.")
    answer: str = Field(description="Plain answer text from Perplexity.")
    rendered_response: str = Field(
        description="Answer rendered in the requested output format.",
    )
    references: Annotated[list[MCPReference], Field(
        default_factory=list,
        description="References returned by Perplexity.",
    )]
    reference_count: int = Field(description="Number of references returned.")


class ServerConfig(BaseModel):
    """Runtime configuration for the MCP server."""

    transport: Transport = Field(default="stdio")
    host: str = Field(default=_DEFAULT_HOST)
    port: int = Field(default=_DEFAULT_PORT, ge=1, le=65535)
    mount_path: str = Field(default=_DEFAULT_PATH)


def _parse_args() -> ServerConfig:
    """Parse CLI arguments for the MCP server entrypoint."""
    parser = argparse.ArgumentParser(description="Run the Perplexity MCP server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport to use.",
    )
    parser.add_argument(
        "--host",
        default=_DEFAULT_HOST,
        help="Host to bind when using streamable HTTP.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_DEFAULT_PORT,
        help="Port to bind when using streamable HTTP.",
    )
    parser.add_argument(
        "--mount-path",
        default=_DEFAULT_PATH,
        help="HTTP mount path when using streamable HTTP.",
    )
    args = parser.parse_args()
    return ServerConfig.model_validate(vars(args))


def _normalise_output_format(output_format: str) -> OutputFormat:
    """Normalise accepted output format aliases."""
    aliases = {
        "json": "json",
        "markdown": "markdown",
        "md": "markdown",
        "plain": "plain",
        "text": "plain",
    }
    normalised = aliases.get(output_format.strip().lower())
    if normalised is None:
        raise ValueError("output_format must be one of: json, markdown, plain")
    return cast(OutputFormat, normalised)


def _search_mode_for_query_mode(mode: QueryMode) -> str:
    """Map the MCP query mode onto the upstream Perplexity mode."""
    if mode == "quick":
        return "standard"
    return "multi_step"


def _build_reference(ref: WebResult) -> MCPReference:
    """Convert an API reference into an MCP-safe shape."""
    return MCPReference(title=ref.name, url=ref.url, snippet=ref.snippet or "")


def _format_json_response(answer: Answer) -> str:
    """Render an answer as a JSON document string."""
    payload = {
        "answer": answer.text,
        "references": [
            {"title": ref.name, "url": ref.url, "snippet": ref.snippet} for ref in answer.references
        ],
    }
    return json.dumps(payload, indent=2)


def _format_text_response(answer: Answer, output_format: OutputFormat) -> str:
    """Render an answer using the existing formatter registry."""
    formatter: Formatter = get_formatter(output_format)
    return formatter.format_complete(answer)


def _render_answer(answer: Answer, output_format: OutputFormat) -> str:
    """Render the answer in the requested format."""
    if output_format == "json":
        return _format_json_response(answer)
    return _format_text_response(answer, output_format)


def _load_authentication() -> tuple[str | None, dict[str, str] | None]:
    """Load optional authentication for Perplexity requests."""
    return load_token_optional(TokenManager(), _LOGGER)


def _request_answer(query: str, mode: QueryMode) -> Answer:
    """Fetch an answer from Perplexity for the requested research depth."""
    token, cookies = _load_authentication()
    search_mode = _search_mode_for_query_mode(mode)
    with PerplexityAPI(token, cookies) as api:
        return api.get_complete_answer(query, search_implementation_mode=search_mode)


def _friendly_error_message(exc: Exception) -> str:
    """Convert internal exceptions into agent-friendly tool errors."""
    if isinstance(exc, PerplexityHTTPStatusError):
        return str(exc)
    if isinstance(exc, PerplexityRequestError):
        return str(exc)
    if isinstance(exc, ValueError):
        return str(exc)
    return f"Perplexity request failed: {exc}"


def run_mcp_query(query: str, mode: QueryMode, output_format: str) -> MCPQueryResult:
    """Run a Perplexity query for the MCP server.

    Args:
        query: User question to send to Perplexity.
        mode: Quick lookup or deep research.
        output_format: Response format to render.

    Returns:
        Structured MCP query result.

    Raises:
        RuntimeError: If the query cannot be completed.
        ValueError: If the input is invalid.
    """
    cleaned_query = query.strip()
    if not cleaned_query:
        raise ValueError("query must not be empty")

    normalised_format = _normalise_output_format(output_format)

    try:
        answer = _request_answer(cleaned_query, mode)
    except (PerplexityHTTPStatusError, PerplexityRequestError, ValueError) as exc:
        raise RuntimeError(_friendly_error_message(exc)) from exc

    references = [_build_reference(ref) for ref in answer.references]
    rendered_response = _render_answer(answer, normalised_format)
    return MCPQueryResult(
        mode=mode,
        output_format=normalised_format,
        answer=answer.text,
        rendered_response=rendered_response,
        references=references,
        reference_count=len(references),
    )


def _server_meta() -> dict[str, int]:
    """Return shared MCP metadata for large-result handling."""
    return {"anthropic/maxResultSizeChars": _TOOL_OUTPUT_LIMIT}


def create_mcp_server(config: ServerConfig | None = None) -> FastMCP:
    """Create the configured MCP server instance."""
    active_config = config or ServerConfig()
    server = FastMCP(
        name="Perplexity CLI",
        instructions=_SERVER_INSTRUCTIONS,
        host=active_config.host,
        port=active_config.port,
        streamable_http_path=active_config.mount_path,
    )

    _register_mcp_tools(server)
    return server


def _register_mcp_tools(server: FastMCP) -> None:
    """Register the Perplexity query tools on the MCP server."""
    _ = (
        server.tool(
            name="perplexity_quick_info",
            title="Perplexity Quick Info",
            description=(
                "Fast Perplexity lookup for recent facts, short explanations, and quick validation. "
                "Use this first when you need concise current information without multi-step research."
            ),
            meta=_server_meta(),
        )(_perplexity_quick_info),
        server.tool(
            name="perplexity_deep_info",
            title="Perplexity Deep Info",
            description=(
                "Deeper Perplexity research for comparisons, timelines, synthesis, or topics that need "
                "multi-step investigation across sources. Use when a quick answer may be incomplete."
            ),
            meta=_server_meta(),
        )(_perplexity_deep_info),
    )


async def _perplexity_quick_info(
    query: str,
    output_format: OutputFormat = "markdown",
    ctx: Context[ServerSession, None] | None = None,
) -> MCPQueryResult:
    """Get a fast Perplexity answer for a targeted question."""
    if ctx is not None:
        await ctx.info("Running quick Perplexity lookup")
        await ctx.report_progress(progress=0.2, total=1.0, message="Starting quick lookup")
    result = run_mcp_query(query, "quick", output_format)
    if ctx is not None:
        await ctx.report_progress(progress=1.0, total=1.0, message="Quick lookup complete")
    return result


async def _perplexity_deep_info(
    query: str,
    output_format: OutputFormat = "markdown",
    ctx: Context[ServerSession, None] | None = None,
) -> MCPQueryResult:
    """Get a deeper Perplexity answer using multi-step research."""
    if ctx is not None:
        await ctx.info("Running deep Perplexity research")
        await ctx.report_progress(progress=0.1, total=1.0, message="Starting deep research")
    result = run_mcp_query(query, "deep", output_format)
    if ctx is not None:
        await ctx.report_progress(progress=1.0, total=1.0, message="Deep research complete")
    return result


def main() -> None:
    """Run the Perplexity MCP server."""
    config = _parse_args()
    server = create_mcp_server(config)
    server.run(transport=config.transport, mount_path=config.mount_path)
