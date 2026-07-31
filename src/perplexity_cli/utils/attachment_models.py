"""Shared attachment data models."""

from __future__ import annotations

import base64
import binascii
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

_TEXT_PLAIN_CONTENT_TYPE = "text/plain"
_MAX_FILENAME_LENGTH = 255


class FileAttachment(BaseModel):
    """File attachment for API requests."""

    filename: str = Field(
        ...,
        description="Base filename (no path), must be non-empty and <=255 characters",
    )
    content_type: str = Field(
        ...,
        description="MIME type of the file (e.g., 'text/plain', 'application/json')",
    )
    # owner: api-contract - ``data`` is a stable serialised attachment schema field.
    data: str = Field(  # nosemgrep: meaningless-name  # owner: quality-infrastructure; reason: upstream API field name must match payload
        ...,
        description="Base64-encoded file content",
    )

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        """Validate filename is non-empty and within length limit."""
        if not value:
            msg = "Filename must be non-empty"
            raise ValueError(msg)
        if len(value) > _MAX_FILENAME_LENGTH:
            msg = f"Filename must be <={_MAX_FILENAME_LENGTH} characters"
            raise ValueError(msg)
        return value

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, value: str) -> str:
        """Validate content_type is non-empty."""
        if not value:
            msg = "Content type must be non-empty"
            raise ValueError(msg)
        return value

    @field_validator("data")
    @classmethod
    def validate_data(cls, value: str) -> str:
        """Validate data is valid base64."""
        try:
            base64.b64decode(value, validate=True)
        except binascii.Error as exc:
            msg = f"Invalid base64 data: {exc}"
            raise ValueError(msg) from exc
        return value

    @classmethod
    def from_file(cls, path: Path) -> FileAttachment:
        """Create attachment from file path."""
        if not path.exists():
            msg = f"File not found: {path}"
            raise FileNotFoundError(msg)
        if not path.is_file():
            msg = f"Not a file: {path}"
            raise ValueError(msg)

        content = path.read_bytes()
        encoded = base64.b64encode(content).decode("ascii")
        extension_to_type = {
            ".txt": _TEXT_PLAIN_CONTENT_TYPE,
            ".md": "text/markdown",
            ".json": "application/json",
            ".py": _TEXT_PLAIN_CONTENT_TYPE,
            ".js": _TEXT_PLAIN_CONTENT_TYPE,
            ".ts": _TEXT_PLAIN_CONTENT_TYPE,
            ".tsx": _TEXT_PLAIN_CONTENT_TYPE,
            ".jsx": _TEXT_PLAIN_CONTENT_TYPE,
            ".yaml": _TEXT_PLAIN_CONTENT_TYPE,
            ".yml": _TEXT_PLAIN_CONTENT_TYPE,
            ".toml": _TEXT_PLAIN_CONTENT_TYPE,
            ".csv": "text/csv",
            ".html": "text/html",
            ".xml": "text/xml",
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".rtf": "application/rtf",
        }
        content_type = extension_to_type.get(path.suffix.lower(), "application/octet-stream")
        return cls(filename=path.name, content_type=content_type, data=encoded)
