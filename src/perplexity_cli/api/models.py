"""Data models for Perplexity API requests and responses."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from perplexity_cli.api.contracts import require_list, require_mapping
from perplexity_cli.utils.version import get_api_version

if TYPE_CHECKING:
    from perplexity_cli.formatting.base import Formatter


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
class OutputOptions:
    """Presentation and serialisation switches for command output.

    Bundles the flags that control *how* a result is rendered (format,
    reference stripping, JSON envelope, schema inclusion) so that they
    can be threaded through the rendering pipeline as one argument.
    """

    output_format: str = "text"
    strip_references: bool = False
    json_mode: bool = False
    include_schema: bool = False


@dataclass(frozen=True, slots=True)
class HttpRequestContext:
    """Per-request HTTP metadata passed to transport helpers.

    Groups the URL, headers, body, and timeout so that lower-level
    methods (logging, execution) receive a single context object instead
    of four positional parameters.
    """

    url: str
    headers: dict[str, str]
    json_data: dict[str, Any] | None = None
    effective_timeout: int = 30


@dataclass(frozen=True, slots=True)
class QueryInput:
    """User query text, file attachments, and optional model selection.

    Pairs the query string with its resolved attachment URLs and an
    optional model preference so that downstream functions receive one
    domain object rather than multiple loosely-related parameters.
    """

    query: str
    attachment_urls: list[str] = field(default_factory=list)
    model_preference: str | None = None


@dataclass(frozen=True, slots=True)
class RenderContext:
    """Formatter and presentation options bundled for rendering.

    Combines the ``Formatter`` instance with the ``OutputOptions``
    flags so that rendering functions receive a single context object.
    """

    formatter: Formatter
    options: OutputOptions


class FileAttachment(BaseModel):
    """File attachment for API requests.

    Represents a file attachment with base64-encoded content to be sent
    to the Perplexity API.
    """

    filename: str = Field(
        ...,
        description="Base filename (no path), must be non-empty and ≤255 characters",
    )
    content_type: str = Field(
        ...,
        description="MIME type of the file (e.g., 'text/plain', 'application/json')",
    )
    data: str = Field(
        ...,
        description="Base64-encoded file content",
    )

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, v: str) -> str:
        """Validate filename is non-empty and within length limit."""
        if not v:
            raise ValueError("Filename must be non-empty")
        if len(v) > 255:
            raise ValueError("Filename must be ≤255 characters")
        return v

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str) -> str:
        """Validate content_type is non-empty."""
        if not v:
            raise ValueError("Content type must be non-empty")
        return v

    @field_validator("data")
    @classmethod
    def validate_data(cls, v: str) -> str:
        """Validate data is valid base64."""
        try:
            base64.b64decode(v, validate=True)
        except binascii.Error as e:
            raise ValueError(f"Invalid base64 data: {e}") from e
        return v

    @classmethod
    def from_file(cls, path: Path) -> FileAttachment:
        """Create attachment from file path.

        Args:
            path: Path to the file to attach.

        Returns:
            FileAttachment instance with file content base64-encoded.

        Raises:
            FileNotFoundError: If file does not exist.
            ValueError: If path is not a file.
        """
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not path.is_file():
            raise ValueError(f"Not a file: {path}")

        # Read file and base64 encode
        with open(path, "rb") as f:
            content = f.read()
        encoded = base64.b64encode(content).decode("ascii")

        # Detect content type from extension
        extension_to_type = {
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".json": "application/json",
            ".py": "text/plain",
            ".js": "text/plain",
            ".ts": "text/plain",
            ".tsx": "text/plain",
            ".jsx": "text/plain",
            ".yaml": "text/plain",
            ".yml": "text/plain",
            ".toml": "text/plain",
            ".csv": "text/csv",
            ".html": "text/html",
            ".xml": "text/xml",
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".rtf": "application/rtf",
        }
        content_type = extension_to_type.get(path.suffix.lower(), "application/octet-stream")

        return cls(
            filename=path.name,
            content_type=content_type,
            data=encoded,
        )


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
    sources: list[str] = Field(default_factory=lambda: ["web"])  # nosemgrep: return-not-in-function
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
    client_coordinates: Any | None = Field(default=None)
    mentions: list[Any] = Field(default_factory=list)
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

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API request."""
        return self.model_dump(mode="json")


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
    def _validate_upstream_shape(cls, data: Any) -> Any:
        """Ensure the raw input is a mapping before field validation."""
        return require_mapping(data, "Malformed web result block in upstream response")


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
    content: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _split_flat_payload(cls, data: Any) -> Any:
        """Transform a flat upstream block dict into {intended_usage, content}.

        If the data already contains a ``content`` key (e.g. from direct
        construction or a ``model_dump`` round-trip), it is passed through
        unchanged.
        """
        data = require_mapping(data, "Malformed block in upstream response")
        if "content" not in data:
            intended_usage = data.get("intended_usage", "")
            content = {k: v for k, v in data.items() if k != "intended_usage"}
            return {"intended_usage": intended_usage, "content": content}
        return data

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
        markdown_block = self.content.get("markdown_block")
        if not isinstance(markdown_block, dict):
            return None
        chunks = markdown_block.get("chunks")
        if not isinstance(chunks, list):
            return None
        return "".join(str(chunk) for chunk in chunks)

    def _extract_from_text_field(self) -> str | None:
        """Extract text from a direct text field."""
        if "text" in self.content:
            return self.content["text"]
        return None

    def _extract_from_diff_block(self) -> str | None:
        """Extract text from a diff block with patches."""
        diff_block = self.content.get("diff_block")
        if not isinstance(diff_block, dict):
            return None
        for patch in diff_block.get("patches", []):
            result = self._extract_patch_value(patch)
            if result is not None:
                return result
        return None

    @staticmethod
    def _extract_patch_value(patch: Any) -> str | None:
        """Extract text value from a single diff patch entry."""
        if not isinstance(patch, dict):
            return None
        value = patch.get("value")
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return value.get("text")
        return None

    def _extract_from_answer_block(self) -> str | None:
        """Extract text from an answer block."""
        answer_block = self.content.get("answer_block")
        if isinstance(answer_block, dict) and "text" in answer_block:
            return answer_block["text"]
        return None

    def extract_plan_info(self) -> dict[str, Any] | None:
        """Extract progress details from a plan-oriented block."""
        if self.intended_usage not in ["pro_search_steps", "plan"]:
            return None

        plan_block = self.content.get("plan_block", {})
        if not plan_block:
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

        web_result_block = self.content.get("web_result_block")
        if not isinstance(web_result_block, dict):
            return None

        results = web_result_block.get("web_results")
        if not isinstance(results, list):
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
    blocks: list[Block] = Field(default_factory=list)
    final_sse_message: bool = Field(default=False)
    cursor: str | None = Field(default=None)
    read_write_token: str | None = Field(default=None)
    web_results: list[WebResult] | None = Field(default=None)
    attachments: list[str] = Field(default_factory=list, description="S3 URLs of attached files")

    @model_validator(mode="before")
    @classmethod
    def _validate_upstream_shape(cls, data: Any) -> Any:
        """Enforce upstream contract: top-level mapping with list-shaped blocks."""
        data = require_mapping(data, "Malformed SSE message in upstream response")
        require_list(data.get("blocks", []), "Malformed SSE blocks in upstream response")
        return data

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
    references: list[WebResult] = Field(default_factory=list)
