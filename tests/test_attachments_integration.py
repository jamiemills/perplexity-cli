"""Integration tests for file attachment feature with CLI.

Uses a shared mock fixture to avoid deeply nested ``patch()`` blocks.
Tests exercise the ``query`` command through ``CliRunner`` with stubbed
transport and authentication layers.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from click.testing import CliRunner

from perplexity_cli.api.models import Answer
from perplexity_cli.cli import query

# ---------------------------------------------------------------------------
# Shared fixture that sets up the common mock stack once per test
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_query_app() -> Generator[tuple[Mock, Mock, Mock, Mock], None, None]:
    """Provide stubs for StyleManager, TokenManager, AttachmentUploader, and
    PerplexityAPI so every test starts with a clean, controlled environment.

    Returns ``(mock_api, mock_uploader, mock_tm, mock_sm)`` so callers can
    configure call-args assertions without their own nested ``with patch``
    blocks.
    """
    mock_api = _make_api_mock()
    mock_uploader = Mock()
    mock_uploader.upload_files = AsyncMock()
    mock_tm = Mock()
    mock_tm.load_token.return_value = ("test-token", None)
    mock_sm = Mock()
    mock_sm.load_style.return_value = None

    with (
        patch("perplexity_cli.query_runner.StyleManager", return_value=mock_sm),
        patch("perplexity_cli.query_runner.TokenManager", return_value=mock_tm),
        patch("perplexity_cli.attachments.AttachmentUploader", return_value=mock_uploader),
        patch("perplexity_cli.query_runner.PerplexityAPI", return_value=mock_api),
    ):
        yield mock_api, mock_uploader, mock_tm, mock_sm


def _make_api_mock() -> Mock:
    """Create a Mock for PerplexityAPI that supports context manager protocol."""
    mock_api = Mock()
    mock_api.__enter__ = Mock(return_value=mock_api)
    mock_api.__exit__ = Mock(return_value=False)
    mock_api.get_complete_answer.return_value = Answer(text="Test answer", references=[])
    return mock_api


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAttachmentsIntegration:
    """Integration tests for file attachment feature."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    # -- Single attachment --------------------------------------------------

    def test_query_with_single_attachment(
        self, runner: CliRunner, mock_query_app: tuple[Mock, Mock, Mock, Mock], tmp_path: Path
    ) -> None:
        mock_api, mock_uploader, _mock_tm, _mock_sm = mock_query_app

        test_file = tmp_path / "test.txt"
        test_file.write_text("Test content", encoding="utf-8")

        s3_url = "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/test.txt"
        mock_uploader.upload_files = AsyncMock(return_value=[s3_url])

        result = runner.invoke(
            query,
            ["--no-stream", "--attach", str(test_file), "What is this file?"],
        )

        assert result.exit_code == 0
        assert "Test answer" in result.output
        call_args = mock_api.get_complete_answer.call_args
        assert call_args is not None
        assert call_args[0][0] == "What is this file?"
        attachments = call_args[1]["extra_params"][0]
        assert attachments == [s3_url]

    # -- Multiple attachments -----------------------------------------------

    def test_query_with_multiple_attachments(
        self, runner: CliRunner, mock_query_app: tuple[Mock, Mock, Mock, Mock], tmp_path: Path
    ) -> None:
        mock_api, mock_uploader, _mock_tm, _mock_sm = mock_query_app

        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.md"
        file1.write_text("Content 1", encoding="utf-8")
        file2.write_text("# Header", encoding="utf-8")

        s3_urls = [
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file1.txt",
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file2.md",
        ]
        mock_uploader.upload_files = AsyncMock(return_value=s3_urls)

        result = runner.invoke(
            query,
            ["--no-stream", "--attach", f"{file1},{file2}", "Compare these files"],
        )

        assert result.exit_code == 0
        assert "Test answer" in result.output
        call_args = mock_api.get_complete_answer.call_args
        attachments = call_args[1]["extra_params"][0]
        assert len(attachments) == 2
        assert all(isinstance(url, str) and url.startswith("https://") for url in attachments)

    # -- Repeated attach flags ----------------------------------------------

    def test_query_with_repeated_attach_flags(
        self, runner: CliRunner, mock_query_app: tuple[Mock, Mock, Mock, Mock], tmp_path: Path
    ) -> None:
        mock_api, mock_uploader, _mock_tm, _mock_sm = mock_query_app

        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("Content 1", encoding="utf-8")
        file2.write_text("Content 2", encoding="utf-8")

        s3_urls = [
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file1.txt",
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file2.txt",
        ]
        mock_uploader.upload_files = AsyncMock(return_value=s3_urls)

        result = runner.invoke(
            query,
            [
                "--no-stream",
                "--attach",
                str(file1),
                "--attach",
                str(file2),
                "Process these",
            ],
        )

        assert result.exit_code == 0
        attachments = mock_api.get_complete_answer.call_args[1]["extra_params"][0]
        assert len(attachments) == 2

    # -- Nonexistent file ---------------------------------------------------

    def test_query_attachment_nonexistent_file_error(
        self, runner: CliRunner, mock_query_app: tuple[Mock, Mock, Mock, Mock]
    ) -> None:
        _mock_api, _mock_uploader, _mock_tm, _mock_sm = mock_query_app

        result = runner.invoke(
            query,
            ["--no-stream", "--attach", "/nonexistent/file.txt", "Test"],
        )

        assert result.exit_code == 1
        assert "Failed to load attachments" in result.output
        assert "File or directory not found" in result.output

    # -- Directory attachment -----------------------------------------------

    def test_query_with_directory_attachment(
        self, runner: CliRunner, mock_query_app: tuple[Mock, Mock, Mock, Mock], tmp_path: Path
    ) -> None:
        mock_api, mock_uploader, _mock_tm, _mock_sm = mock_query_app

        (tmp_path / "file1.txt").write_text("Content 1", encoding="utf-8")
        (tmp_path / "file2.txt").write_text("Content 2", encoding="utf-8")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "file3.txt").write_text("Content 3", encoding="utf-8")

        s3_urls = [
            f"https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/{name}"
            for name in ("file1.txt", "file2.txt", "file3.txt")
        ]
        mock_uploader.upload_files = AsyncMock(return_value=s3_urls)

        result = runner.invoke(
            query,
            ["--no-stream", "--attach", str(tmp_path), "Analyse all files"],
        )

        assert result.exit_code == 0
        attachments = mock_api.get_complete_answer.call_args[1]["extra_params"][0]
        assert len(attachments) == 3
        assert all(isinstance(url, str) and url.startswith("https://") for url in attachments)

    # -- Directory skips hidden / sensitive ---------------------------------

    def test_query_with_directory_attachment_skips_hidden_and_sensitive_files(
        self, runner: CliRunner, mock_query_app: tuple[Mock, Mock, Mock, Mock], tmp_path: Path
    ) -> None:
        mock_api, mock_uploader, _mock_tm, _mock_sm = mock_query_app

        (tmp_path / "file1.txt").write_text("Content 1", encoding="utf-8")
        (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
        (tmp_path / ".hidden.txt").write_text("hidden", encoding="utf-8")
        (tmp_path / "private.key").write_text("key", encoding="utf-8")

        s3_urls = [
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file1.txt"
        ]
        mock_uploader.upload_files = AsyncMock(return_value=s3_urls)

        result = runner.invoke(
            query,
            ["--no-stream", "--attach", str(tmp_path), "Analyse all files"],
        )

        assert result.exit_code == 0
        attachments = mock_api.get_complete_answer.call_args[1]["extra_params"][0]
        assert attachments == s3_urls

    # -- Too many directory files -------------------------------------------

    def test_query_with_too_many_directory_files_fails(
        self, runner: CliRunner, mock_query_app: tuple[Mock, Mock, Mock, Mock], tmp_path: Path
    ) -> None:
        _mock_api, _mock_uploader, _mock_tm, _mock_sm = mock_query_app

        from perplexity_cli.utils.file_handler import MAX_ATTACHMENT_COUNT

        for index in range(MAX_ATTACHMENT_COUNT + 1):
            (tmp_path / f"file-{index}.txt").write_text("content", encoding="utf-8")

        result = runner.invoke(
            query,
            ["--no-stream", "--attach", str(tmp_path), "Analyse all files"],
        )

        assert result.exit_code == 1
        assert "Too many attachments" in result.output
