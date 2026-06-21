"""Data models for Perplexity API requests and responses."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from perplexity_cli.utils.attachment_models import FileAttachment
from perplexity_cli.utils.upstream_contracts import require_list, require_mapping
from perplexity_cli.utils.version import get_api_version


def _web_sources_default() -> list[str]:
    """Default value for the sources field."""
    return ["web"]


__all__ = ["FileAttachment"]

# Module-level ``TypeAdapter`` instances used to narrow arbitrary
# upstream payloads into fully-typed containers without resorting to
# ``typing.Any`` or ``typing.cast``.  Validation against ``object``
# keys/values is a no-op at runtime (every Python value is an object),
# so behaviour is preserved while satisfying ``pyright --strict``.
_OBJECT_DICT_ADAPTER: TypeAdapter[dict[object, object]] = TypeAdapter(dict[object, object])
_OBJECT_LIST_ADAPTER: TypeAdapter[list[object]] = TypeAdapter(list[object])


def _as_object_dict(value: object) -> dict[object, object] | None:
    """Narrow ``value`` to ``dict[object, object]`` when it is a mapping.

    Args:
        value: An arbitrary value pulled from an upstream payload.

    Returns:
        A typed dict view, or ``None`` if ``value`` is not a dict.
    """
    if not isinstance(value, dict):
        return None
    return _OBJECT_DICT_ADAPTER.validate_python(value)


def _as_object_list(value: object) -> list[object] | None:
    """Narrow ``value`` to ``list[object]`` when it is a list.

    Args:
        value: An arbitrary value pulled from an upstream payload.

    Returns:
        A typed list view, or ``None`` if ``value`` is not a list.
    """
    if not isinstance(value, list):
        return None
    return _OBJECT_LIST_ADAPTER.validate_python(value)


# ---------------------------------------------------------------------------
# Typed default factories (named functions keep pyright strict happy;
# ``field(default_factory=list)`` would widen to ``list[Unknown]``).
# ---------------------------------------------------------------------------


def _new_mentions() -> list[object]:
    """Default factory for ``QueryParams.mentions``."""
    return []


def _new_block_content() -> dict[str, object]:
    """Default factory for ``Block.content``."""
    return {}


def _new_blocks() -> list[Block]:
    """Default factory for ``SSEMessage.blocks``."""
    return []


def _new_references() -> list[WebResult]:
    """Default factory for ``Answer.references``."""
    return []


# ---------------------------------------------------------------------------
# Lightweight parameter objects (dataclasses, not Pydantic)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TraceContext:
    """Timing and correlation identifiers for a single request.

    Carries the trace ID (for log correlation) and start timestamp (for
    elapsed-time calculations) through the call chain without occupying
    separate function parameters.
    """

    trace_id: str | None = None
    start_time: float | None = None


@dataclass(frozen=True, slots=True)
class HttpRequestContext:
    """Per-request HTTP metadata passed to transport helpers."""

    url: str
    headers: dict[str, str]
    json_data: dict[str, object] | None = None
    effective_timeout: int = 30


@dataclass(frozen=True, slots=True, init=False)
class QueryInput:
    """User query text, file attachments, and optional model selection.

    The custom ``__init__`` accepts a covariant ``Mapping`` for
    ``request_params`` so callers can pass ``dict[str, str]`` (from CLI
    overrides) or ``dict[str, object]`` (programmatic) interchangeably;
    values are stored as a concrete ``dict`` for downstream consumers.
    """

    query: str
    attachment_urls: list[str]
    model_preference: str | None
    request_params: dict[str, object]

    def __init__(
        self,
        query: str,
        attachment_urls: Iterable[str] | None = None,
        model_preference: str | None = None,
        request_params: Mapping[str, object] | None = None,
    ) -> None:
        """Initialise ``QueryInput``, copying mutable inputs defensively.

        Args:
            query: The user's query text.
            attachment_urls: Optional S3 attachment URLs; copied into a
                fresh ``list`` to keep the dataclass immutable.
            model_preference: Optional model override (e.g. ``pplx_pro``).
            request_params: Optional extra fields merged into the
                outbound request; copied into a fresh ``dict``.
        """
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "attachment_urls", list(attachment_urls or []))
        object.__setattr__(self, "model_preference", model_preference)
        object.__setattr__(self, "request_params", dict(request_params or {}))


class QueryParams(BaseModel):
    """Parameters for a Perplexity query request."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    language: str = Field(default="en-US")
    timezone: str = Field(default="Europe/London")
    search_focus: str = Field(default="internet")
    mode: str = Field(default="copilot")
    frontend_uuid: str = Field(default="")
    frontend_context_uuid: str = Field(default="")
    version: str = Field(default_factory=get_api_version)
    sources: list[str] = Field(default_factory=_web_sources_default)
    attachments: list[str] = Field(
        default_factory=list,
        description="S3 URLs of attached files",
    )
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
    client_coordinates: object | None = Field(default=None)
    mentions: list[object] = Field(default_factory=_new_mentions)
    skip_search_enabled: bool = Field(default=True)
    is_nav_suggestions_disabled: bool = Field(default=False)
    always_search_override: bool = Field(default=False)
    override_no_search: bool = Field(default=False)
    should_ask_for_mcp_tool_confirmation: bool = Field(default=True)
    browser_agent_allow_once_from_toggle: bool = Field(default=False)
    search_implementation_mode: str = Field(
        default="standard",
        description="Controls research depth; 'standard' = quick query (~30s), 'multi_step' = deep research (2-4 min)",
    )

    @field_validator("search_implementation_mode")
    @classmethod
    def validate_search_mode(cls, v: str) -> str:
        """Validate search implementation mode.

        Args:
            v: The search implementation mode value.

        Returns:
            The validated mode value.

        Raises:
            ValueError: If mode is not 'standard' or 'multi_step'.
        """
        if v not in ["standard", "multi_step"]:
            raise ValueError('search_implementation_mode must be "standard" or "multi_step"')
        return v

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary for API request."""
        return self.model_dump(mode="json")


class QueryRequest(BaseModel):
    """Complete query request to Perplexity API."""

    query_str: str
    params: QueryParams

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary for API request."""
        return {
            "query_str": self.query_str,
            "params": self.params.to_dict(),
        }


class WebResult(BaseModel):
    """Search result from Perplexity.

    Upstream API payloads are validated via ``model_validate()``.  The
    pre-validator enforces that the input is a mapping (raising
    ``UpstreamSchemaError`` otherwise) so that malformed upstream data
    is caught early with a domain-specific exception.
    """

    name: str = Field(default="")
    url: str = Field(default="")
    snippet: str | None = Field(default=None)
    timestamp: str | None = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def _validate_upstream_shape(cls, raw_result: object) -> object:
        """Ensure the raw input is a mapping before field validation."""
        return require_mapping(raw_result, "Malformed web result block in upstream response")


class Block(BaseModel):
    """Answer block from SSE response.

    The upstream API sends blocks as flat dictionaries with
    ``intended_usage`` alongside the payload keys.  The pre-validator
    restructures this into ``{intended_usage, content}`` so that all
    non-usage keys are stored under ``content``.

    Direct construction with ``intended_usage`` and ``content``
    keyword arguments is also supported (the pre-validator detects the
    presence of the ``content`` key and passes through unchanged).
    """

    intended_usage: str = Field(default="")
    content: dict[str, object] = Field(default_factory=_new_block_content)

    @model_validator(mode="before")
    @classmethod
    def _split_flat_payload(cls, raw_block: object) -> object:
        """Transform a flat upstream block dict into {intended_usage, content}.

        If the payload already contains a ``content`` key (e.g. from direct
        construction or a ``model_dump`` round-trip), it is passed through
        unchanged.
        """
        mapping = require_mapping(raw_block, "Malformed block in upstream response")
        if "content" not in mapping:
            intended_usage = mapping.get("intended_usage", "")
            content = {k: v for k, v in mapping.items() if k != "intended_usage"}
            return {"intended_usage": intended_usage, "content": content}
        return mapping

    def extract_text(self) -> str | None:
        """Extract answer text from a private API block shape."""
        if "web_result_block" in self.content:
            return None
        extractors = [
            self._extract_from_markdown_block,
            self._extract_from_text_field,
            self._extract_from_diff_block,
            self._extract_from_answer_block,
        ]
        for extractor in extractors:
            result = extractor()
            if result is not None:
                return result
        return None

    def _extract_from_markdown_block(self) -> str | None:
        """Extract text from a markdown block with chunks."""
        markdown_block = _as_object_dict(self.content.get("markdown_block"))
        if markdown_block is None:
            return None
        chunks = _as_object_list(markdown_block.get("chunks"))
        if chunks is None:
            return None
        return "".join(str(chunk) for chunk in chunks)

    def _extract_from_text_field(self) -> str | None:
        """Extract text from a direct text field."""
        text = self.content.get("text")
        if isinstance(text, str):
            return text
        return None

    def _extract_from_diff_block(self) -> str | None:
        """Extract text from a diff block with patches."""
        diff_block = _as_object_dict(self.content.get("diff_block"))
        if diff_block is None:
            return None
        patches = _as_object_list(diff_block.get("patches"))
        if patches is None:
            return None
        for patch in patches:
            result = self._extract_patch_value(patch)
            if result is not None:
                return result
        return None

    @staticmethod
    def _extract_patch_value(patch: object) -> str | None:
        """Extract text value from a single diff patch entry."""
        patch_dict = _as_object_dict(patch)
        if patch_dict is None:
            return None
        value = patch_dict.get("value")
        if isinstance(value, str):
            return value
        value_dict = _as_object_dict(value)
        if value_dict is None:
            return None
        text = value_dict.get("text")
        if isinstance(text, str):
            return text
        return None

    def _extract_from_answer_block(self) -> str | None:
        """Extract text from an answer block."""
        answer_block = _as_object_dict(self.content.get("answer_block"))
        if answer_block is None:
            return None
        text = answer_block.get("text")
        if isinstance(text, str):
            return text
        return None

    def extract_plan_info(self) -> dict[str, object] | None:
        """Extract progress details from a plan-oriented block."""
        if self.intended_usage not in ["pro_search_steps", "plan"]:
            return None

        plan_block = _as_object_dict(self.content.get("plan_block"))
        if plan_block is None or not plan_block:
            return None

        return {
            "progress": plan_block.get("progress"),
            "eta_seconds": plan_block.get("eta_seconds_remaining"),
            "goals": plan_block.get("goals", []),
            "pct_complete": plan_block.get("pct_complete"),
        }

    def extract_web_results(self) -> list[WebResult] | None:
        """Extract web references from a private API block shape."""
        if self.intended_usage != "web_results":
            return None

        web_result_block = _as_object_dict(self.content.get("web_result_block"))
        if web_result_block is None:
            return None

        results = _as_object_list(web_result_block.get("web_results"))
        if results is None:
            return None

        return [WebResult.model_validate(result) for result in results]


class SSEMessage(BaseModel):
    """Single SSE message from streaming response.

    The pre-validator enforces the upstream contract (mapping with a
    list-shaped ``blocks`` field).  After field validation, the
    after-validator derives ``web_results`` from the validated blocks
    when the caller has not supplied them explicitly.
    """

    backend_uuid: str = Field(default="")
    context_uuid: str = Field(default="")
    uuid: str = Field(default="")
    frontend_context_uuid: str = Field(default="")
    display_model: str = Field(default="")
    mode: str = Field(default="")
    thread_url_slug: str | None = Field(default=None)
    status: str = Field(default="")
    text_completed: bool = Field(default=False)
    blocks: list[Block] = Field(default_factory=_new_blocks)
    final_sse_message: bool = Field(default=False)
    cursor: str | None = Field(default=None)
    read_write_token: str | None = Field(default=None)
    web_results: list[WebResult] | None = Field(default=None)
    attachments: list[str] = Field(default_factory=list, description="S3 URLs of attached files")

    @model_validator(mode="before")
    @classmethod
    def _validate_upstream_shape(cls, raw_input: object) -> object:
        """Enforce upstream contract: top-level mapping with list-shaped blocks."""
        parsed = require_mapping(raw_input, "Malformed SSE message in upstream response")
        require_list(parsed.get("blocks", []), "Malformed SSE blocks in upstream response")
        return parsed

    @model_validator(mode="after")
    def _derive_web_results(self) -> SSEMessage:
        """Derive web_results from blocks when not explicitly provided."""
        if self.web_results is None:
            for block in self.blocks:
                extracted = block.extract_web_results()
                if extracted is not None:
                    self.web_results = extracted
                    break
        return self

    def extract_answer_text(self) -> str | None:
        """Extract the final answer text from message blocks."""
        for block in self.blocks:
            if block.intended_usage != "ask_text":
                continue
            text = block.extract_text()
            if text is not None:
                return text

        return None

    def describe_block_usages(self) -> str:
        """Summarise block usages for schema-drift diagnostics."""
        if not self.blocks:
            return "none"
        return ",".join(block.intended_usage or "<missing>" for block in self.blocks)


class Answer(BaseModel):
    """Complete answer with text and references."""

    text: str
    references: list[WebResult] = Field(default_factory=_new_references)
