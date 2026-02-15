"""Tests for file handler utilities."""

from pathlib import Path

import pytest

from perplexity_cli.utils.file_handler import (
    load_attachments,
    resolve_file_arguments,
)


class TestResolveFileArguments:
    """Test resolve_file_arguments function."""

    def test_resolve_single_inline_file(self, tmp_path):
        """Test resolving a single inline file path."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        result = resolve_file_arguments([str(test_file)])
        assert len(result) == 1
        assert result[0].name == "test.txt"

    def test_resolve_multiple_inline_files(self, tmp_path):
        """Test resolving multiple inline file paths."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("content1")
        file2.write_text("content2")

        result = resolve_file_arguments([str(file1), str(file2)])
        assert len(result) == 2
        assert {p.name for p in result} == {"file1.txt", "file2.txt"}

    def test_resolve_from_attach_flag(self, tmp_path):
        """Test resolving files from --attach flag."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        result = resolve_file_arguments([], attach_args=[str(test_file)])
        assert len(result) == 1
        assert result[0].name == "test.txt"

    def test_resolve_comma_separated_attach(self, tmp_path):
        """Test resolving comma-separated files from --attach flag."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("content1")
        file2.write_text("content2")

        attach_str = f"{file1},{file2}"
        result = resolve_file_arguments([], attach_args=[attach_str])
        assert len(result) == 2
        assert {p.name for p in result} == {"file1.txt", "file2.txt"}

    def test_resolve_directory(self, tmp_path):
        """Test resolving all files from a directory."""
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.txt").write_text("content2")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "file3.txt").write_text("content3")

        result = resolve_file_arguments([], attach_args=[str(tmp_path)])
        assert len(result) == 3
        names = {p.name for p in result}
        assert "file1.txt" in names
        assert "file2.txt" in names
        assert "file3.txt" in names

    def test_resolve_nonexistent_file_raises(self):
        """Test that nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            resolve_file_arguments(["/nonexistent/file.txt"])

    def test_resolve_nonexistent_directory_raises(self):
        """Test that nonexistent directory raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            resolve_file_arguments([], attach_args=["/nonexistent/directory"])

    def test_resolve_duplicates_deduped(self, tmp_path):
        """Test that duplicate file paths are deduplicated."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        # Pass same file twice
        result = resolve_file_arguments([str(test_file), str(test_file)])
        assert len(result) == 1
        assert result[0].name == "test.txt"

    def test_resolve_sorted_output(self, tmp_path):
        """Test that output is sorted by path."""
        file_b = tmp_path / "b.txt"
        file_a = tmp_path / "a.txt"
        file_b.write_text("content")
        file_a.write_text("content")

        result = resolve_file_arguments([str(file_b), str(file_a)])
        assert len(result) == 2
        assert result[0].name == "a.txt"
        assert result[1].name == "b.txt"

    def test_resolve_whitespace_handling_in_comma_separated(self, tmp_path):
        """Test that whitespace in comma-separated list is handled."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("content1")
        file2.write_text("content2")

        # Include spaces around comma
        attach_str = f"{file1} , {file2}"
        result = resolve_file_arguments([], attach_args=[attach_str])
        assert len(result) == 2


class TestLoadAttachments:
    """Test load_attachments function."""

    def test_load_single_file(self, tmp_path):
        """Test loading a single file as attachment."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content", encoding="utf-8")

        files = [test_file]
        attachments = load_attachments(files)

        assert len(attachments) == 1
        assert attachments[0].filename == "test.txt"
        assert attachments[0].content_type == "text/plain"

    def test_load_multiple_files(self, tmp_path):
        """Test loading multiple files as attachments."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.md"
        file1.write_text("content1", encoding="utf-8")
        file2.write_text("# Header", encoding="utf-8")

        files = [file1, file2]
        attachments = load_attachments(files)

        assert len(attachments) == 2
        assert attachments[0].filename == "file1.txt"
        assert attachments[0].content_type == "text/plain"
        assert attachments[1].filename == "file2.md"
        assert attachments[1].content_type == "text/markdown"

    def test_load_json_file(self, tmp_path):
        """Test loading a JSON file with correct content type."""
        json_file = tmp_path / "config.json"
        json_file.write_text('{"key": "value"}', encoding="utf-8")

        attachments = load_attachments([json_file])

        assert len(attachments) == 1
        assert attachments[0].filename == "config.json"
        assert attachments[0].content_type == "application/json"

    def test_load_python_file(self, tmp_path):
        """Test loading a Python file."""
        py_file = tmp_path / "script.py"
        py_file.write_text('print("hello")', encoding="utf-8")

        attachments = load_attachments([py_file])

        assert len(attachments) == 1
        assert attachments[0].filename == "script.py"
        assert attachments[0].content_type == "text/plain"

    def test_load_unknown_file_type(self, tmp_path):
        """Test loading a file with unknown extension."""
        unknown_file = tmp_path / "data.xyz"
        unknown_file.write_bytes(b"binary data")

        attachments = load_attachments([unknown_file])

        assert len(attachments) == 1
        assert attachments[0].filename == "data.xyz"
        assert attachments[0].content_type == "application/octet-stream"

    def test_load_nonexistent_file_raises(self):
        """Test that loading nonexistent file raises FileNotFoundError."""
        nonexistent = Path("/nonexistent/file.txt")
        with pytest.raises(FileNotFoundError):
            load_attachments([nonexistent])

    def test_load_data_is_base64_encoded(self, tmp_path):
        """Test that file content is base64-encoded."""
        import base64

        test_file = tmp_path / "test.txt"
        test_content = "test content"
        test_file.write_text(test_content, encoding="utf-8")

        attachments = load_attachments([test_file])

        # Verify the data is base64-encoded
        decoded = base64.b64decode(attachments[0].data).decode("utf-8")
        assert decoded == test_content

    def test_load_binary_file(self, tmp_path):
        """Test loading a binary file."""
        binary_file = tmp_path / "image.bin"
        binary_file.write_bytes(b"\x89PNG\r\n\x1a\n")

        attachments = load_attachments([binary_file])

        assert len(attachments) == 1
        assert attachments[0].filename == "image.bin"


class TestIntegrationResolveAndLoad:
    """Integration tests for resolve and load."""

    def test_resolve_and_load_workflow(self, tmp_path):
        """Test the typical resolve -> load workflow."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.md"
        file1.write_text("content1", encoding="utf-8")
        file2.write_text("# Header", encoding="utf-8")

        # Resolve files
        files = resolve_file_arguments([str(file1)], attach_args=[str(file2)])

        # Load as attachments
        attachments = load_attachments(files)

        assert len(attachments) == 2
        assert attachments[0].filename == "file1.txt"
        assert attachments[1].filename == "file2.md"

    def test_resolve_directory_and_load(self, tmp_path):
        """Test resolving directory and loading all files."""
        (tmp_path / "file1.txt").write_text("content1", encoding="utf-8")
        (tmp_path / "file2.txt").write_text("content2", encoding="utf-8")

        # Resolve directory
        files = resolve_file_arguments([], attach_args=[str(tmp_path)])

        # Load as attachments
        attachments = load_attachments(files)

        assert len(attachments) == 2
