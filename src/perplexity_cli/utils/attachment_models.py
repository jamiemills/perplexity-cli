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
    data: str = Field(
        ...,
        description="Base64-encoded file content",
    )

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        """Validate filename is non-empty and within length limit."""
        if not value:
            raise ValueError("Filename must be non-empty")
        if len(value) > _MAX_FILENAME_LENGTH:
            raise ValueError(f"Filename must be <={_MAX_FILENAME_LENGTH} characters")
        return value

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, value: str) -> str:
        """Validate content_type is non-empty."""
        if not value:
            raise ValueError("Content type must be non-empty")
        return value

    @field_validator("data")
    @classmethod
    def validate_data(cls, value: str) -> str:
        """Validate data is valid base64."""
        try:
            base64.b64decode(value, validate=True)
        except binascii.Error as exc:
            raise ValueError(f"Invalid base64 data: {exc}") from exc
        return value

    @classmethod
    def from_file(cls, path: Path) -> FileAttachment:
        """Create attachment from file path."""
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not path.is_file():
            raise ValueError(f"Not a file: {path}")

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
