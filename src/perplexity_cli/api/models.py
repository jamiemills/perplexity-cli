"""Data models for Perplexity API requests and responses."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from perplexity_cli.utils.version import get_api_version


class QueryParams(BaseModel):
    """Parameters for a Perplexity query request."""

    model_config = ConfigDict(populate_by_name=True)

    language: str = Field(default="en-US")
    timezone: str = Field(default="Europe/London")
    search_focus: str = Field(default="internet")
    mode: str = Field(default="copilot")
    frontend_uuid: str = Field(default="")
    frontend_context_uuid: str = Field(default="")
    version: str = Field(default_factory=get_api_version)
    sources: list[str] = Field(default_factory=lambda: ["web"])
    attachments: list[Any] = Field(default_factory=list)
    search_recency_filter: str | None = Field(default=None)
    model_preference: str = Field(default="pplx_pro")
    is_related_query: bool = Field(default=False)
    is_sponsored: bool = Field(default=False)
    prompt_source: str = Field(default="user")
    query_source: str = Field(default="home")
    is_incognito: bool = Field(default=False)
    local_search_enabled: bool = Field(default=False)
    use_schematized_api: bool = Field(default=True)
    send_back_text_in_streaming_api: bool = Field(default=False)
    client_coordinates: Any | None = Field(default=None)
    mentions: list[Any] = Field(default_factory=list)
    skip_search_enabled: bool = Field(default=True)
    is_nav_suggestions_disabled: bool = Field(default=False)
    always_search_override: bool = Field(default=False)
    override_no_search: bool = Field(default=False)
    should_ask_for_mcp_tool_confirmation: bool = Field(default=True)
    browser_agent_allow_once_from_toggle: bool = Field(default=False)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API request."""
        return self.model_dump()


class QueryRequest(BaseModel):
    """Complete query request to Perplexity API."""

    query_str: str
    params: QueryParams

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API request."""
        return {
            "query_str": self.query_str,
            "params": self.params.to_dict(),
        }


class WebResult(BaseModel):
    """Search result from Perplexity."""

    name: str
    url: str
    snippet: str | None = Field(default=None)
    timestamp: str | None = Field(default=None)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WebResult":
        """Create from API response dictionary."""
        return cls(
            name=data.get("name", ""),
            url=data.get("url", ""),
            snippet=data.get("snippet"),
            timestamp=data.get("timestamp"),
        )


class Block(BaseModel):
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


class SSEMessage(BaseModel):
    """Single SSE message from streaming response."""

    backend_uuid: str
    context_uuid: str
    uuid: str
    frontend_context_uuid: str
    display_model: str
    mode: str
    thread_url_slug: str | None = Field(default=None)
    status: str
    text_completed: bool
    blocks: list[Block] = Field(default_factory=list)
    final_sse_message: bool
    cursor: str | None = Field(default=None)
    read_write_token: str | None = Field(default=None)
    web_results: list[WebResult] | None = Field(default=None)

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


class Answer(BaseModel):
    """Complete answer with text and references."""

    text: str
    references: list[WebResult] = Field(default_factory=list)
