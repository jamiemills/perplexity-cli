"""Quick validation test for FileAttachment model concept."""

import base64
import json
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class FileAttachment(BaseModel):
    """File attachment for API requests."""

    filename: str
    content_type: str
    data: str  # Base64-encoded content

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, v: str) -> str:
        """Validate filename."""
        if not v or len(v) > 255:
            raise ValueError("Filename must be non-empty and ≤ 255 characters")
        return v

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str) -> str:
        """Validate content type."""
        if not v:
            raise ValueError("Content type cannot be empty")
        return v

    @field_validator("data")
    @classmethod
    def validate_data(cls, v: str) -> str:
        """Validate base64 data."""
        try:
            base64.b64decode(v, validate=True)
        except Exception as e:
            raise ValueError(f"Invalid base64 data: {e}") from e
        return v

    @classmethod
    def from_file(cls, path: Path) -> "FileAttachment":
        """Create attachment from file path."""
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
            ".yaml": "text/plain",
            ".yml": "text/plain",
        }
        content_type = extension_to_type.get(path.suffix.lower(), "application/octet-stream")

        return cls(
            filename=path.name,
            content_type=content_type,
            data=encoded,
        )


class QueryParams(BaseModel):
    """Query parameters with attachments."""

    query: str
    attachments: list[FileAttachment] = Field(default_factory=list)


def test_file_attachment_model():
    """Test FileAttachment model creation and validation."""
    # Test 1: Create attachment from dict
    attachment = FileAttachment(
        filename="test.txt",
        content_type="text/plain",
        data=base64.b64encode(b"Hello, World!").decode("ascii"),
    )
    assert attachment.filename == "test.txt"
    assert attachment.content_type == "text/plain"
    print("✓ Test 1: Valid attachment creation passed")

    # Test 2: Serialization to JSON
    attachment_dict = attachment.model_dump()
    json_str = json.dumps(attachment_dict)
    assert "test.txt" in json_str
    print("✓ Test 2: Serialization passed")

    # Test 3: Invalid filename (empty)
    try:
        FileAttachment(
            filename="",
            content_type="text/plain",
            data=base64.b64encode(b"test").decode("ascii"),
        )
        raise AssertionError("Should have raised ValueError")
    except ValueError as e:
        assert "non-empty" in str(e)
        print("✓ Test 3: Empty filename validation passed")

    # Test 4: Invalid base64 data
    try:
        FileAttachment(
            filename="test.txt",
            content_type="text/plain",
            data="not-valid-base64!!!",
        )
        raise AssertionError("Should have raised ValueError")
    except ValueError as e:
        assert "base64" in str(e).lower()
        print("✓ Test 4: Invalid base64 validation passed")


def test_file_attachment_from_file():
    """Test creating attachment from actual file."""
    import tempfile

    # Create a temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("Test content for attachment")
        test_file = Path(f.name)

    try:
        # Test 5: Load from file
        attachment = FileAttachment.from_file(test_file)
        assert attachment.filename == "test_attachment.txt"
        assert attachment.content_type == "text/plain"

        # Verify we can decode it
        decoded = base64.b64decode(attachment.data).decode("utf-8")
        assert decoded == "Test content for attachment"
        print("✓ Test 5: Load from file passed")

        # Test 6: Query with attachments
        query = QueryParams(
            query="Explain this file",
            attachments=[attachment],
        )
        query_dict = query.model_dump()
        assert len(query_dict["attachments"]) == 1
        assert query_dict["attachments"][0]["filename"] == "test_attachment.txt"
        print("✓ Test 6: QueryParams with attachments passed")

        # Test 7: Serialize to JSON (simulating API request)
        json_str = json.dumps(query_dict)
        parsed = json.loads(json_str)
        assert parsed["attachments"][0]["filename"] == "test_attachment.txt"
        print("✓ Test 7: JSON serialization for API passed")

    finally:
        test_file.unlink()


if __name__ == "__main__":
    print("Running FileAttachment validation tests...\n")
    test_file_attachment_model()
    print()
    test_file_attachment_from_file()
    print("\n✅ All validation tests passed!")
