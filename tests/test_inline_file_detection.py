"""Tests for automatic file detection in query text.

These tests verify that files mentioned in query text are automatically
detected, validated, and attached without requiring the --attach flag.
"""

from pathlib import Path

import pytest

from perplexity_cli.utils.file_handler import resolve_file_arguments


class TestInlineFileDetection:
    """Test automatic file detection in query text."""

    def test_single_file_in_query_text(self, tmp_path):
        """Test detection of a single file mentioned in query text."""
        test_file = tmp_path / "report.md"
        test_file.write_text("Test content")

        query = f"analyze this file {test_file}"
        result = resolve_file_arguments([query])

        assert len(result) == 1
        assert result[0].name == "report.md"
        assert result[0].resolve() == test_file.resolve()

    def test_multiple_files_in_query_text(self, tmp_path):
        """Test detection of multiple files mentioned in query text."""
        file1 = tmp_path / "file1.md"
        file2 = tmp_path / "file2.txt"
        file1.write_text("Content 1")
        file2.write_text("Content 2")

        query = f"compare {file1} and {file2}"
        result = resolve_file_arguments([query])

        assert len(result) == 2
        assert {p.name for p in result} == {"file1.md", "file2.txt"}

    def test_file_with_absolute_path(self, tmp_path):
        """Test detection of absolute file paths."""
        test_file = tmp_path / "absolute.txt"
        test_file.write_text("Absolute path test")

        # Use full absolute path
        query = f"read {test_file.absolute()}"
        result = resolve_file_arguments([query])

        assert len(result) == 1
        assert result[0].name == "absolute.txt"

    def test_file_with_relative_tilde_path(self, tmp_path):
        """Test detection of absolute paths (tilde expansion happens in regex extraction)."""
        # Create a temp file with absolute path in home
        home = Path.home()
        test_file = home / "test_inline_detection_temp.md"
        test_file.write_text("Absolute path test")

        try:
            # Use absolute path (tilde paths are expanded during extraction)
            query = f"check {test_file.absolute()}"
            result = resolve_file_arguments([query])

            assert len(result) == 1
            assert result[0].name == "test_inline_detection_temp.md"
        finally:
            # Cleanup
            test_file.unlink(missing_ok=True)

    def test_multiple_same_file_mentioned(self, tmp_path):
        """Test that same file mentioned multiple times is only included once."""
        test_file = tmp_path / "unique.txt"
        test_file.write_text("Only once")

        query = f"look at {test_file} and then {test_file} again"
        result = resolve_file_arguments([query])

        # Should only include the file once even though mentioned twice
        assert len(result) == 1
        assert result[0].name == "unique.txt"

    def test_nonexistent_file_raises_error(self, tmp_path):
        """Test that mentioning nonexistent file raises FileNotFoundError."""
        nonexistent = tmp_path / "does_not_exist.md"
        query = f"read {nonexistent}"

        with pytest.raises(FileNotFoundError) as exc_info:
            resolve_file_arguments([query])

        assert "does_not_exist.md" in str(exc_info.value)
        assert "not found" in str(exc_info.value).lower()

    def test_path_without_extension_not_detected(self, tmp_path):
        """Test that paths without file extensions are not detected."""
        # Create a file with extension
        real_file = tmp_path / "real.txt"
        real_file.write_text("Real file")

        # Create a directory without extension
        test_dir = tmp_path / "somedir"
        test_dir.mkdir()

        # Query mentions directory path and file path separately
        # The directory shouldn't be detected because regex requires file extensions
        query = f"check the somedir folder and process {real_file}"
        result = resolve_file_arguments([query])

        # Should only find the file with extension, not the directory
        assert len(result) == 1
        assert result[0].name == "real.txt"

    def test_file_in_query_with_surrounding_text(self, tmp_path):
        """Test file detection works with surrounding text."""
        test_file = tmp_path / "embedded.md"
        test_file.write_text("Embedded in query")

        query = (
            f"Please analyze this important file {test_file} for me. "
            "I need to understand its contents."
        )
        result = resolve_file_arguments([query])

        assert len(result) == 1
        assert result[0].name == "embedded.md"

    def test_path_with_special_characters(self, tmp_path):
        """Test file detection with hyphens and underscores."""
        test_file = tmp_path / "my-report_v2.txt"
        test_file.write_text("Special chars in name")

        query = f"analyze {test_file}"
        result = resolve_file_arguments([query])

        assert len(result) == 1
        assert result[0].name == "my-report_v2.txt"

    def test_file_with_trailing_punctuation(self, tmp_path):
        """Test file path followed by sentence punctuation is handled."""
        test_file = tmp_path / "sentence.md"
        test_file.write_text("Test content")

        # File path followed by period, comma, question mark, etc.
        queries = [
            f"read {test_file}.",
            f"analyze {test_file},",
            f"check {test_file}?",
            f"examine {test_file};",
        ]

        for query in queries:
            result = resolve_file_arguments([query])
            assert len(result) == 1, f"Failed for query: {query}"
            assert result[0].name == "sentence.md"

    def test_combined_inline_and_attach_flag(self, tmp_path):
        """Test using both inline file mention and --attach flag together."""
        inline_file = tmp_path / "inline.txt"
        attach_file = tmp_path / "attach.txt"
        inline_file.write_text("Inline file")
        attach_file.write_text("Attach flag file")

        query = f"compare {inline_file} with another"
        result = resolve_file_arguments([query], attach_args=[str(attach_file)])

        assert len(result) == 2
        assert {p.name for p in result} == {"inline.txt", "attach.txt"}

    def test_combined_inline_comma_separated_attach(self, tmp_path):
        """Test inline file with comma-separated --attach values."""
        inline_file = tmp_path / "inline.md"
        attach_file1 = tmp_path / "attach1.txt"
        attach_file2 = tmp_path / "attach2.txt"
        inline_file.write_text("Inline")
        attach_file1.write_text("Attach 1")
        attach_file2.write_text("Attach 2")

        query = f"check {inline_file}"
        attach_str = f"{attach_file1},{attach_file2}"
        result = resolve_file_arguments([query], attach_args=[attach_str])

        assert len(result) == 3
        assert {p.name for p in result} == {"inline.md", "attach1.txt", "attach2.txt"}

    def test_nested_directory_files_not_detected(self, tmp_path):
        """Test that directory paths are not detected (only files with extensions)."""
        test_dir = tmp_path / "documents"
        test_dir.mkdir()
        real_file = tmp_path / "real.txt"
        real_file.write_text("Real file")

        # Directory path without extension should not be detected
        # Reference the dir by name without full path to avoid matching nested dots
        query = f"check in documents folder and process {real_file}"
        result = resolve_file_arguments([query])

        # Should only find the file with extension
        assert len(result) == 1
        assert result[0].name == "real.txt"

    def test_tmp_directory_with_file(self, tmp_path):
        """Test detection of files in /tmp directory."""
        test_file = tmp_path / "tmptest.txt"
        test_file.write_text("Temp file")

        query = f"analyze {test_file}"
        result = resolve_file_arguments([query])

        assert len(result) == 1
        assert result[0].name == "tmptest.txt"

    def test_file_path_case_sensitive(self, tmp_path):
        """Test that file detection is case-sensitive."""
        test_file = tmp_path / "CaseSensitive.txt"
        test_file.write_text("Case test")

        query = f"read {test_file}"
        result = resolve_file_arguments([query])

        assert len(result) == 1
        assert result[0].name == "CaseSensitive.txt"

    def test_multiple_queries_with_files(self, tmp_path):
        """Test file detection across multiple query arguments."""
        file1 = tmp_path / "file1.md"
        file2 = tmp_path / "file2.txt"
        file1.write_text("File 1")
        file2.write_text("File 2")

        # Pass multiple query strings
        queries = [f"check {file1}", f"and compare with {file2}"]
        result = resolve_file_arguments(queries)

        assert len(result) == 2
        assert {p.name for p in result} == {"file1.md", "file2.txt"}

    def test_file_with_numbers_in_name(self, tmp_path):
        """Test file detection with numbers in filename."""
        test_file = tmp_path / "report2024_v1.pdf"
        test_file.write_text("Report")

        query = f"summarize {test_file}"
        result = resolve_file_arguments([query])

        assert len(result) == 1
        assert result[0].name == "report2024_v1.pdf"

    def test_deeply_nested_file_path(self, tmp_path):
        """Test detection of deeply nested file paths."""
        # Create nested directory structure
        nested = tmp_path / "a" / "b" / "c" / "d"
        nested.mkdir(parents=True)
        test_file = nested / "deep.txt"
        test_file.write_text("Deep file")

        query = f"read {test_file}"
        result = resolve_file_arguments([query])

        assert len(result) == 1
        assert result[0].name == "deep.txt"
        assert "a" in str(result[0])
        assert "b" in str(result[0])
        assert "c" in str(result[0])
        assert "d" in str(result[0])

    def test_file_detection_sorted_output(self, tmp_path):
        """Test that detected files are returned in sorted order."""
        file_z = tmp_path / "z_file.txt"
        file_a = tmp_path / "a_file.txt"
        file_m = tmp_path / "m_file.txt"
        file_z.write_text("Z")
        file_a.write_text("A")
        file_m.write_text("M")

        query = f"compare {file_z} {file_a} {file_m}"
        result = resolve_file_arguments([query])

        assert len(result) == 3
        # Verify they're sorted
        names = [p.name for p in result]
        assert names == sorted(names)
        assert names == ["a_file.txt", "m_file.txt", "z_file.txt"]
