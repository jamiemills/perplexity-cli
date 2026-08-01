"""Validation tests for the production FileAttachment model.

The local duplicate model definitions were deleted; these tests exercise the
production ``perplexity_cli.utils.attachment_models.FileAttachment`` so the
test suite never diverges from the shipped model.
"""

import base64
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from perplexity_cli.utils.attachment_models import FileAttachment


def _encoded(body: bytes) -> str:
    """Base64-encode *body* as ASCII text."""
    return base64.b64encode(body).decode("ascii")


class TestFileAttachmentValidation:
    """FileAttachment creation, serialization, and field validation."""

    def test_valid_attachment_creation(self) -> None:
        """A valid attachment round-trips its core fields."""
        encoded = _encoded(b"Hello, World!")
        attachment = FileAttachment(
            filename="test.txt",
            content_type="text/plain",
            data=encoded,
        )
        assert attachment.filename == "test.txt"
        assert attachment.content_type == "text/plain"
        assert attachment.data == encoded

    def test_serialization_to_json(self) -> None:
        """The dumped attachment model serializes to JSON."""
        attachment = FileAttachment(
            filename="test.txt",
            content_type="text/plain",
            data=_encoded(b"Hello, World!"),
        )
        json_str = json.dumps(attachment.model_dump())
        assert "test.txt" in json_str

    def test_empty_filename_rejected(self) -> None:
        """An empty filename raises a validation error."""
        with pytest.raises(ValidationError, match="non-empty"):
            FileAttachment(
                filename="",
                content_type="text/plain",
                data=_encoded(b"test"),
            )

    def test_oversized_filename_rejected(self) -> None:
        """A filename longer than 255 characters is rejected."""
        with pytest.raises(ValidationError, match="255"):
            FileAttachment(
                filename="a" * 256 + ".txt",
                content_type="text/plain",
                data=_encoded(b"test"),
            )

    def test_empty_content_type_rejected(self) -> None:
        """An empty content type raises a validation error."""
        with pytest.raises(ValidationError, match="non-empty"):
            FileAttachment(
                filename="test.txt",
                content_type="",
                data=_encoded(b"test"),
            )

    def test_invalid_base64_rejected(self) -> None:
        """Invalid base64 payloads are rejected with a validation error."""
        with pytest.raises(ValidationError, match="base64"):
            FileAttachment(
                filename="test.txt",
                content_type="text/plain",
                data="not-valid-base64!!!",
            )


class TestFileAttachmentFromFile:
    """FileAttachment.from_file behaviour."""

    def test_load_from_file(self, tmp_path: Path) -> None:
        """A text file loads with its filename, type, and content."""
        test_file = tmp_path / "notes.txt"
        test_file.write_text("Test content for attachment", encoding="utf-8")

        attachment = FileAttachment.from_file(test_file)

        assert attachment.filename == test_file.name
        assert attachment.content_type == "text/plain"
        decoded = base64.b64decode(attachment.data).decode("utf-8")
        assert decoded == "Test content for attachment"

    def test_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        """from_file raises FileNotFoundError for a missing path."""
        with pytest.raises(FileNotFoundError):
            FileAttachment.from_file(tmp_path / "does-not-exist.txt")
