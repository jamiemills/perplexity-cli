"""Data models for Perplexity API requests and responses."""

import hashlib
from dataclasses import dataclass, field
from typing import Any

from perplexity_cli.utils.version import get_api_version


def generate_thread_hash(slug: str, length: int = 8) -> str:
    """Generate a short, consistent hash from a thread slug.
    
    This hash can be used to identify threads when the full slug is truncated
    in display. The hash is deterministic - same slug always produces same hash.
    
    Args:
        slug: The thread slug to hash.
        length: Length of hash to return (default: 8).
    
    Returns:
        Short hash string (hexadecimal).
    """
    hash_obj = hashlib.sha256(slug.encode('utf-8'))
    return hash_obj.hexdigest()[:length]


@dataclass
class QueryParams:
    """Parameters for a Perplexity query request."""

    language: str = "en-US"
    timezone: str = "Europe/London"
    search_focus: str = "internet"
    mode: str = "copilot"
    frontend_uuid: str = ""
    frontend_context_uuid: str = ""
    context_uuid: str | None = None  # Backend context UUID for follow-up queries
    read_write_token: str | None = None  # Token for thread operations
    thread_url_slug: str | None = None  # Thread slug for follow-up queries
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
        result = {
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
        
        # Include context fields only if they have values (for follow-up queries)
        if self.context_uuid is not None:
            result["context_uuid"] = self.context_uuid
        if self.read_write_token is not None:
            result["read_write_token"] = self.read_write_token
        if self.thread_url_slug is not None:
            result["thread_url_slug"] = self.thread_url_slug
        
        return result


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


@dataclass
class SocialInfo:
    """Social information for a thread."""

    view_count: int = 0
    fork_count: int = 0
    like_count: int = 0
    user_likes: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SocialInfo":
        """Create from API response dictionary."""
        return cls(
            view_count=data.get("view_count", 0),
            fork_count=data.get("fork_count", 0),
            like_count=data.get("like_count", 0),
            user_likes=data.get("user_likes", False),
        )


@dataclass
class ThreadContext:
    """Thread context for follow-up queries."""

    thread_url_slug: str
    frontend_context_uuid: str
    context_uuid: str
    read_write_token: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "thread_url_slug": self.thread_url_slug,
            "frontend_context_uuid": self.frontend_context_uuid,
            "context_uuid": self.context_uuid,
            "read_write_token": self.read_write_token,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ThreadContext":
        """Create from dictionary."""
        return cls(
            thread_url_slug=data.get("thread_url_slug", ""),
            frontend_context_uuid=data.get("frontend_context_uuid", ""),
            context_uuid=data.get("context_uuid", ""),
            read_write_token=data.get("read_write_token"),
        )


@dataclass
class Thread:
    """Thread/conversation from Perplexity library."""

    thread_number: int
    slug: str
    title: str
    context_uuid: str
    frontend_context_uuid: str
    read_write_token: str
    first_answer: str  # JSON string
    last_query_datetime: str
    query_count: int
    total_threads: int
    has_next_page: bool
    mode: str
    uuid: str
    frontend_uuid: str
    thread_access: int
    status: str
    first_entry_model_preference: str
    display_model: str
    expiry_time: str | None = None
    source: str = "default"
    source_metadata: dict[str, Any] | None = None
    thread_status: str = "completed"
    is_personal_intent: bool = False
    is_mission_control: bool = False
    stream_created_at: str | None = None
    unread: bool = False
    search_focus: str = "internet"
    search_recency_filter: str | None = None
    sources: list[str] = field(default_factory=lambda: ["web"])
    featured_images: list[Any] = field(default_factory=list)
    social_info: SocialInfo = field(default_factory=SocialInfo)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Thread":
        """Create from API response dictionary."""
        social_info_data = data.get("social_info", {})
        social_info = (
            SocialInfo.from_dict(social_info_data)
            if isinstance(social_info_data, dict)
            else SocialInfo()
        )

        return cls(
            thread_number=data.get("thread_number", 0),
            slug=data.get("slug", ""),
            title=data.get("title", ""),
            context_uuid=data.get("context_uuid", ""),
            frontend_context_uuid=data.get("frontend_context_uuid", ""),
            read_write_token=data.get("read_write_token", ""),
            first_answer=data.get("first_answer", ""),
            last_query_datetime=data.get("last_query_datetime", ""),
            query_count=data.get("query_count", 0),
            total_threads=data.get("total_threads", 0),
            has_next_page=data.get("has_next_page", False),
            mode=data.get("mode", "copilot"),
            uuid=data.get("uuid", ""),
            frontend_uuid=data.get("frontend_uuid", ""),
            thread_access=data.get("thread_access", 1),
            status=data.get("status", "COMPLETED"),
            first_entry_model_preference=data.get("first_entry_model_preference", "PPLX_PRO"),
            display_model=data.get("display_model", "pplx_pro"),
            expiry_time=data.get("expiry_time"),
            source=data.get("source", "default"),
            source_metadata=data.get("source_metadata"),
            thread_status=data.get("thread_status", "completed"),
            is_personal_intent=data.get("is_personal_intent", False),
            is_mission_control=data.get("is_mission_control", False),
            stream_created_at=data.get("stream_created_at"),
            unread=data.get("unread", False),
            search_focus=data.get("search_focus", "internet"),
            search_recency_filter=data.get("search_recency_filter"),
            sources=data.get("sources", ["web"]),
            featured_images=data.get("featured_images", []),
            social_info=social_info,
        )

    def to_thread_context(self) -> ThreadContext:
        """Convert to ThreadContext for follow-up queries."""
        return ThreadContext(
            thread_url_slug=self.slug,
            frontend_context_uuid=self.frontend_context_uuid,
            context_uuid=self.context_uuid,
            read_write_token=self.read_write_token if self.read_write_token else None,
        )
    
    @property
    def thread_hash(self) -> str:
        """Generate a short hash identifier for this thread.
        
        Returns:
            Short hash string (8 characters) that can be used to identify the thread.
        """
        return generate_thread_hash(self.slug)


@dataclass
class Collection:
    """Collection from Perplexity library."""

    number: int
    uuid: str
    title: str
    description: str
    slug: str
    updated_datetime: str
    has_next_page: bool
    thread_count: int
    page_count: int
    access: int
    user_permission: int
    emoji: str | None = None
    instructions: str = ""
    suggested_queries: list[str] | None = None
    s3_social_preview_url: str | None = None
    model_selection: dict[str, Any] | None = None
    template_id: str | None = None
    file_count: int = 0
    focused_web_config: dict[str, Any] | None = None
    max_contributors: int | None = None
    enable_web_by_default: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Collection":
        """Create from API response dictionary."""
        return cls(
            number=data.get("number", 0),
            uuid=data.get("uuid", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            slug=data.get("slug", ""),
            updated_datetime=data.get("updated_datetime", ""),
            has_next_page=data.get("has_next_page", False),
            thread_count=data.get("thread_count", 0),
            page_count=data.get("page_count", 0),
            access=data.get("access", 1),
            user_permission=data.get("user_permission", 4),
            emoji=data.get("emoji"),
            instructions=data.get("instructions", ""),
            suggested_queries=data.get("suggested_queries"),
            s3_social_preview_url=data.get("s3_social_preview_url"),
            model_selection=data.get("model_selection"),
            template_id=data.get("template_id"),
            file_count=data.get("file_count", 0),
            focused_web_config=data.get("focused_web_config"),
            max_contributors=data.get("max_contributors"),
            enable_web_by_default=data.get("enable_web_by_default", True),
        )
