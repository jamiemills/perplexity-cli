"""Data models for Perplexity API requests and responses."""

from dataclasses import dataclass, field
from typing import Any

from perplexity_cli.utils.version import get_api_version


@dataclass
class QueryParams:
    """Parameters for a Perplexity query request."""

    language: str = "en-US"
    timezone: str = "Europe/London"
    search_focus: str = "internet"
    mode: str = "copilot"
    frontend_uuid: str = ""
    frontend_context_uuid: str = ""
    version: str = field(default_factory=get_api_version)
    sources: list[str] = field(default_factory=lambda: ["web"])
    attachments: list[Any] = field(default_factory=list)
    search_recency_filter: str | None = None
    model_preference: str = "pplx_pro"
    is_related_query: bool = False
    is_sponsored: bool = False
    prompt_source: str = "user"
    query_source: str = "home"
    is_incognito: bool = False
    local_search_enabled: bool = False
    use_schematized_api: bool = True
    send_back_text_in_streaming_api: bool = False
    client_coordinates: Any | None = None
    mentions: list[Any] = field(default_factory=list)
    skip_search_enabled: bool = True
    is_nav_suggestions_disabled: bool = False
    always_search_override: bool = False
    override_no_search: bool = False
    should_ask_for_mcp_tool_confirmation: bool = True
    browser_agent_allow_once_from_toggle: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API request."""
        return {
            "language": self.language,
            "timezone": self.timezone,
            "search_focus": self.search_focus,
            "mode": self.mode,
            "frontend_uuid": self.frontend_uuid,
            "frontend_context_uuid": self.frontend_context_uuid,
            "version": self.version,
            "sources": self.sources,
            "attachments": self.attachments,
            "search_recency_filter": self.search_recency_filter,
            "model_preference": self.model_preference,
            "is_related_query": self.is_related_query,
            "is_sponsored": self.is_sponsored,
            "prompt_source": self.prompt_source,
            "query_source": self.query_source,
            "is_incognito": self.is_incognito,
            "local_search_enabled": self.local_search_enabled,
            "use_schematized_api": self.use_schematized_api,
            "send_back_text_in_streaming_api": self.send_back_text_in_streaming_api,
            "client_coordinates": self.client_coordinates,
            "mentions": self.mentions,
            "skip_search_enabled": self.skip_search_enabled,
            "is_nav_suggestions_disabled": self.is_nav_suggestions_disabled,
            "always_search_override": self.always_search_override,
            "override_no_search": self.override_no_search,
            "should_ask_for_mcp_tool_confirmation": self.should_ask_for_mcp_tool_confirmation,
            "browser_agent_allow_once_from_toggle": self.browser_agent_allow_once_from_toggle,
        }


@dataclass
class QueryRequest:
    """Complete query request to Perplexity API."""

    query_str: str
    params: QueryParams

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API request."""
        return {"query_str": self.query_str, "params": self.params.to_dict()}


@dataclass
class WebResult:
    """Search result from Perplexity."""

    name: str
    url: str
    snippet: str
    timestamp: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WebResult":
        """Create from API response dictionary."""
        return cls(
            name=data.get("name", ""),
            url=data.get("url", ""),
            snippet=data.get("snippet", ""),
            timestamp=data.get("timestamp"),
        )


@dataclass
class Block:
    """Answer block from SSE response."""

    intended_usage: str
    content: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Block":
        """Create from API response dictionary."""
        intended_usage = data.get("intended_usage", "")
        # Remove intended_usage from content
        content = {k: v for k, v in data.items() if k != "intended_usage"}
        return cls(intended_usage=intended_usage, content=content)


@dataclass
class SSEMessage:
    """Single SSE message from streaming response."""

    backend_uuid: str
    context_uuid: str
    uuid: str
    frontend_context_uuid: str
    display_model: str
    mode: str
    thread_url_slug: str | None
    status: str
    text_completed: bool
    blocks: list[Block]
    final_sse_message: bool
    cursor: str | None = None
    read_write_token: str | None = None
    web_results: list[WebResult] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SSEMessage":
        """Create from SSE message data."""
        blocks = [Block.from_dict(b) for b in data.get("blocks", [])]

        # Extract web results from web_result_block if present
        web_results = None
        for block in blocks:
            if block.intended_usage == "web_results":
                if "web_result_block" in block.content:
                    web_result_block = block.content["web_result_block"]
                    if isinstance(web_result_block, dict) and "web_results" in web_result_block:
                        results = web_result_block["web_results"]
                        if isinstance(results, list):
                            web_results = [WebResult.from_dict(r) for r in results]
                            break

        return cls(
            backend_uuid=data.get("backend_uuid", ""),
            context_uuid=data.get("context_uuid", ""),
            uuid=data.get("uuid", ""),
            frontend_context_uuid=data.get("frontend_context_uuid", ""),
            display_model=data.get("display_model", ""),
            mode=data.get("mode", ""),
            thread_url_slug=data.get("thread_url_slug"),
            status=data.get("status", ""),
            text_completed=data.get("text_completed", False),
            blocks=blocks,
            final_sse_message=data.get("final_sse_message", False),
            cursor=data.get("cursor"),
            read_write_token=data.get("read_write_token"),
            web_results=web_results,
        )


@dataclass
class Answer:
    """Complete answer with text and references."""

    text: str
    references: list[WebResult] = field(default_factory=list)
