"""Data models for Perplexity API requests and responses."""

import base64
import binascii
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from perplexity_cli.api.contracts import require_list, require_mapping
from perplexity_cli.utils.version import get_api_version


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
    def from_file(cls, path: Path) -> "FileAttachment":
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
    sources: list[str] = Field(default_factory=lambda: ["web"])
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
    """Search result from Perplexity."""

    name: str
    url: str
    snippet: str | None = Field(default=None)
    timestamp: str | None = Field(default=None)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WebResult":
        """Create from API response dictionary."""
        data = require_mapping(data, "Malformed web result block in upstream response")
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
        data = require_mapping(data, "Malformed block in upstream response")
        intended_usage = data.get("intended_usage", "")
        # Remove intended_usage from content
        content = {k: v for k, v in data.items() if k != "intended_usage"}
        return cls(intended_usage=intended_usage, content=content)

    def extract_text(self) -> str | None:
        """Extract answer text from a private API block shape."""
        # 1. Markdown block with chunks (most common for answers)
        if "markdown_block" in self.content:
            markdown_block = self.content["markdown_block"]
            if isinstance(markdown_block, dict) and "chunks" in markdown_block:
                chunks = markdown_block["chunks"]
                if isinstance(chunks, list):
                    return "".join(str(chunk) for chunk in chunks)

        # 2. Direct text field
        if "text" in self.content:
            return self.content["text"]

        # 3. Web results block (skip - these are sources, not answers)
        if "web_result_block" in self.content:
            return None

        # 4. Diff block with patches
        if "diff_block" in self.content:
            diff_block = self.content["diff_block"]
            if isinstance(diff_block, dict) and "patches" in diff_block:
                for patch in diff_block["patches"]:
                    if isinstance(patch, dict) and "value" in patch:
                        value = patch["value"]
                        if isinstance(value, str):
                            return value
                        if isinstance(value, dict) and "text" in value:
                            return value["text"]

        # 5. Answer block
        if "answer_block" in self.content:
            answer_block = self.content["answer_block"]
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

    def extract_web_results(self) -> list["WebResult"] | None:
        """Extract web references from a private API block shape."""
        if self.intended_usage != "web_results":
            return None

        web_result_block = self.content.get("web_result_block")
        if not isinstance(web_result_block, dict) or "web_results" not in web_result_block:
            return None

        results = web_result_block["web_results"]
        if not isinstance(results, list):
            return None

        return [WebResult.from_dict(result) for result in results]


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
    attachments: list[str] = Field(default_factory=list, description="S3 URLs of attached files")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SSEMessage":
        """Create from SSE message data."""
        data = require_mapping(data, "Malformed SSE message in upstream response")
        raw_blocks = require_list(
            data.get("blocks", []), "Malformed SSE blocks in upstream response"
        )

        blocks = [Block.from_dict(b) for b in raw_blocks]

        web_results = None
        for block in blocks:
            extracted_results = block.extract_web_results()
            if extracted_results is not None:
                web_results = extracted_results
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
            attachments=data.get("attachments", []),
        )

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
