"""Tests for file handler utilities."""

import logging
import os
from pathlib import Path

import pytest

import perplexity_cli.utils.file_handler as file_handler_module
from perplexity_cli.utils.exceptions import AttachmentError
from perplexity_cli.utils.file_handler import (
    MAX_ATTACHMENT_COUNT,
    MAX_ATTACHMENT_FILE_SIZE,
    MAX_TOTAL_ATTACHMENT_SIZE,
    load_attachments,
    resolve_file_arguments,
)
from perplexity_cli.utils.logging import redact_path


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return rendered message text for every captured log record."""
    return [record.getMessage() for record in caplog.records]


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

    def test_resolve_directory_skips_hidden_and_sensitive_files(self, tmp_path):
        """Test directory attachments skip risky files by default."""
        (tmp_path / "visible.txt").write_text("content")
        (tmp_path / ".env").write_text("SECRET=1")
        (tmp_path / ".hidden.txt").write_text("hidden")
        (tmp_path / "private.key").write_text("key")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("git config")

        result = resolve_file_arguments([], attach_args=[str(tmp_path)])

        assert [path.name for path in result] == ["visible.txt"]

    def test_resolve_directory_skips_symlinks(self, tmp_path):
        """Test directory attachments skip symlinked files."""
        target = tmp_path / "target.txt"
        target.write_text("content")
        linked = tmp_path / "linked.txt"
        linked.symlink_to(target)

        result = resolve_file_arguments([], attach_args=[str(tmp_path)])

        assert [path.name for path in result] == ["target.txt"]

    def test_resolve_too_many_files_raises(self, tmp_path):
        """Test attachment count limit is enforced during resolution."""
        for index in range(MAX_ATTACHMENT_COUNT + 1):
            (tmp_path / f"file-{index}.txt").write_text("content")

        with pytest.raises(AttachmentError, match="Too many attachments"):
            resolve_file_arguments([], attach_args=[str(tmp_path)])

    def test_resolve_exact_count_limit_is_accepted(self, tmp_path: Path) -> None:
        """Resolving exactly the attachment count limit must not raise."""
        for index in range(MAX_ATTACHMENT_COUNT):
            (tmp_path / f"file-{index}.txt").write_text("content")

        result = resolve_file_arguments([], attach_args=[str(tmp_path)])

        assert len(result) == MAX_ATTACHMENT_COUNT

    def test_resolve_special_file_raises_with_path_in_message(self, tmp_path: Path) -> None:
        """ValueError for non-file entries quotes the offending path."""
        pipe = tmp_path / "pipe"
        os.mkfifo(pipe)

        with pytest.raises(ValueError) as excinfo:
            resolve_file_arguments([], attach_args=[str(pipe)])

        assert str(excinfo.value) == f"Not a file or directory: {pipe}"

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


class TestQueryTextExtraction:
    """Tilde-path extraction behaviour exercised via resolve_file_arguments."""

    @staticmethod
    def _home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
        """Create an isolated HOME directory so tilde expansion is deterministic."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        return home

    def test_tilde_path_lowercase_is_extracted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Lowercase tilde paths resolve to files inside the isolated HOME."""
        home = self._home(monkeypatch, tmp_path)
        (home / "notes.txt").write_text("content")

        result = resolve_file_arguments(["~/notes.txt"])

        assert [path.name for path in result] == ["notes.txt"]

    def test_tilde_path_uppercase_is_extracted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Uppercase characters survive in extracted tilde paths."""
        home = self._home(monkeypatch, tmp_path)
        (home / "Report.TXT").write_text("content")

        result = resolve_file_arguments(["~/Report.TXT"])

        assert [path.name for path in result] == ["Report.TXT"]

    def test_unix_candidate_trailing_x_is_preserved(self, tmp_path: Path) -> None:
        """A trailing uppercase X in a matched unix path is not stripped."""
        nested = tmp_path / "nested"
        nested.mkdir()
        candidate = nested / "BOX.X"
        candidate.write_text("content")

        result = resolve_file_arguments([str(candidate)])

        assert [path.name for path in result] == ["BOX.X"]

    def test_tilde_candidate_trailing_x_is_preserved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A trailing uppercase X in a matched tilde path is not stripped."""
        home = self._home(monkeypatch, tmp_path)
        (home / "BOX.X").write_text("content")

        result = resolve_file_arguments(["~/BOX.X"])

        assert [path.name for path in result] == ["BOX.X"]


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

    def test_load_attachment_too_large_raises(self, tmp_path):
        """Test per-file size limit is enforced before loading."""
        large_file = tmp_path / "large.txt"
        large_file.write_bytes(b"a" * (MAX_ATTACHMENT_FILE_SIZE + 1))

        with pytest.raises(AttachmentError, match="Attachment too large"):
            load_attachments([large_file])

    def test_load_attachments_total_size_limit_raises(self, tmp_path):
        """Test total attachment size limit is enforced."""
        file1 = tmp_path / "file1.bin"
        file2 = tmp_path / "file2.bin"
        file3 = tmp_path / "file3.bin"
        file1.write_bytes(b"a" * MAX_ATTACHMENT_FILE_SIZE)
        file2.write_bytes(b"b" * MAX_ATTACHMENT_FILE_SIZE)
        file3.write_bytes(b"c" * (MAX_TOTAL_ATTACHMENT_SIZE - (2 * MAX_ATTACHMENT_FILE_SIZE) + 1))

        with pytest.raises(AttachmentError, match="Total attachment size exceeds"):
            load_attachments([file1, file2, file3])

    def test_load_exactly_max_count_is_accepted(self, tmp_path: Path) -> None:
        """Loading exactly the attachment count limit must not raise."""
        files = []
        for index in range(MAX_ATTACHMENT_COUNT):
            path = tmp_path / f"file-{index}.txt"
            path.write_text("content")
            files.append(path)

        attachments = load_attachments(files)

        assert len(attachments) == MAX_ATTACHMENT_COUNT

    def test_load_count_limit_message_quotes_actual_and_limit(self, tmp_path: Path) -> None:
        """The count-limit error message quotes the real count and limit."""
        files = []
        for index in range(MAX_ATTACHMENT_COUNT + 1):
            path = tmp_path / f"file-{index}.txt"
            path.write_text("content")
            files.append(path)

        with pytest.raises(AttachmentError) as excinfo:
            load_attachments(files)

        assert str(excinfo.value) == (
            f"Too many attachments: {MAX_ATTACHMENT_COUNT + 1} files exceeds "
            f"the limit of {MAX_ATTACHMENT_COUNT}"
        )

    def test_load_total_size_equal_to_limit_is_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A cumulative size exactly equal to the total limit is accepted."""
        monkeypatch.setattr(file_handler_module, "MAX_ATTACHMENT_FILE_SIZE", 10)
        monkeypatch.setattr(file_handler_module, "MAX_TOTAL_ATTACHMENT_SIZE", 10)
        first = tmp_path / "first.bin"
        second = tmp_path / "second.bin"
        first.write_bytes(b"a" * 6)
        second.write_bytes(b"b" * 4)

        attachments = load_attachments([first, second])

        assert [attachment.filename for attachment in attachments] == [
            "first.bin",
            "second.bin",
        ]


class TestFileHandlerDiagnosticLogs:
    """Exact log output emitted by the file handler at public boundaries."""

    def test_query_extraction_logs_redacted_path(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Extracted inline paths are logged once with a redacted path argument."""
        target = tmp_path / "test.txt"
        target.write_text("content")

        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            resolve_file_arguments([str(target)])

        assert _messages(caplog) == [f"Extracted path from query: {redact_path(target)}"]

    def test_symlink_skip_logs_redacted_path(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Symlinked directory entries are skipped and logged with a redacted path."""
        target = tmp_path / "target.txt"
        target.write_text("content")
        linked = tmp_path / "linked.txt"
        linked.symlink_to(target)

        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            result = resolve_file_arguments([], attach_args=[str(tmp_path)])

        assert [path.name for path in result] == ["target.txt"]
        assert _messages(caplog) == [
            f"Skipping symlink during directory attachment: {redact_path(linked)}",
        ]

    def test_loaded_attachment_logs_name_and_content_type(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Each loaded attachment is logged with its redacted name and content type."""
        note = tmp_path / "note.txt"
        note.write_text("content")

        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            load_attachments([note])

        assert _messages(caplog) == [f"Loaded attachment: {redact_path(note.name)} (text/plain)"]

    def test_missing_attachment_logs_failure_with_exception(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Missing files log a failure record quoting the path and exception."""
        ghost = tmp_path / "ghost.txt"

        with caplog.at_level(logging.ERROR, logger="perplexity_cli"):
            with pytest.raises(FileNotFoundError) as excinfo:
                load_attachments([ghost])

        assert _messages(caplog) == [f"Failed to load attachment: {ghost}: {excinfo.value}"]

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
    def test_unreadable_attachment_logs_read_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Unreadable files log a read-error record quoting the path and exception."""
        locked = tmp_path / "locked.txt"
        locked.write_text("secret")
        locked.chmod(0o000)

        with caplog.at_level(logging.ERROR, logger="perplexity_cli"):
            with pytest.raises(PermissionError) as excinfo:
                load_attachments([locked])

        assert _messages(caplog) == [f"Error reading file: {locked}: {excinfo.value}"]


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
