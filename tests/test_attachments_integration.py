"""Integration tests for file attachment feature with CLI."""

from unittest.mock import MagicMock, Mock, patch

import pytest
from click.testing import CliRunner

from perplexity_cli.api.models import Answer
from perplexity_cli.cli import query


def _make_api_mock(**kwargs):
    """Create a Mock for PerplexityAPI that supports context manager protocol."""
    mock_api = MagicMock()
    mock_api.__enter__ = Mock(return_value=mock_api)
    mock_api.__exit__ = Mock(return_value=False)
    for key, value in kwargs.items():
        setattr(mock_api, key, value)
    return mock_api


class TestAttachmentsIntegration:
    """Integration tests for file attachment feature."""

    @pytest.fixture
    def runner(self):
        """Create a CLI runner."""
        return CliRunner()

    def test_query_with_single_attachment(self, runner, tmp_path):
        """Test query with single file attachment."""
        # Create test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("Test content", encoding="utf-8")

        with patch("perplexity_cli.utils.style_manager.StyleManager") as mock_sm_class:
            with patch("perplexity_cli.auth.token_manager.TokenManager") as mock_tm_class:
                with patch("perplexity_cli.attachments.AttachmentUploader") as mock_uploader_class:
                    with patch("perplexity_cli.api.endpoints.PerplexityAPI") as mock_api_class:
                        # Mock style manager (no style configured)
                        mock_sm = Mock()
                        mock_sm.load_style.return_value = None
                        mock_sm_class.return_value = mock_sm

                        # Mock token manager
                        mock_tm = Mock()
                        mock_tm.load_token.return_value = ("test-token", None)
                        mock_tm_class.return_value = mock_tm

                        # Mock uploader to return S3 URLs
                        mock_uploader = Mock()
                        mock_uploader.upload_files = Mock(
                            return_value=[
                                "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/test.txt"
                            ]
                        )

                        # Make upload_files async
                        async def mock_upload(*args, **kwargs):
                            return [
                                "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/test.txt"
                            ]

                        mock_uploader.upload_files = mock_upload
                        mock_uploader_class.return_value = mock_uploader

                        # Mock API
                        mock_api = _make_api_mock()
                        mock_api.get_complete_answer.return_value = Answer(
                            text="Test answer", references=[]
                        )
                        mock_api_class.return_value = mock_api

                        # Run query with attachment
                        result = runner.invoke(
                            query,
                            ["--no-stream", "--attach", str(test_file), "What is this file?"],
                        )

                        assert result.exit_code == 0
                        assert "Test answer" in result.output
                        assert "Loading 1 file(s)" in result.output
                        assert "Loaded 1 attachment(s)" in result.output

                        # Verify API was called with attachment S3 URLs
                        call_args = mock_api.get_complete_answer.call_args
                        assert call_args is not None
                        assert call_args[0][0] == "What is this file?"
                        assert "attachments" in call_args[1]
                        attachments = call_args[1]["attachments"]
                        assert len(attachments) == 1
                        assert isinstance(attachments[0], str)
                        assert attachments[0].startswith(
                            "https://ppl-ai-file-upload.s3.amazonaws.com/"
                        )

    def test_query_with_multiple_attachments(self, runner, tmp_path):
        """Test query with multiple file attachments."""
        # Create test files
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.md"
        file1.write_text("Content 1", encoding="utf-8")
        file2.write_text("# Header", encoding="utf-8")

        with patch("perplexity_cli.utils.style_manager.StyleManager") as mock_sm_class:
            with patch("perplexity_cli.auth.token_manager.TokenManager") as mock_tm_class:
                with patch("perplexity_cli.attachments.AttachmentUploader") as mock_uploader_class:
                    with patch("perplexity_cli.api.endpoints.PerplexityAPI") as mock_api_class:
                        # Mock style manager
                        mock_sm = Mock()
                        mock_sm.load_style.return_value = None
                        mock_sm_class.return_value = mock_sm

                        # Mock token manager
                        mock_tm = Mock()
                        mock_tm.load_token.return_value = ("test-token", None)
                        mock_tm_class.return_value = mock_tm

                        # Mock uploader to return S3 URLs
                        async def mock_upload(*args, **kwargs):
                            return [
                                "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file1.txt",
                                "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file2.md",
                            ]

                        mock_uploader = Mock()
                        mock_uploader.upload_files = mock_upload
                        mock_uploader_class.return_value = mock_uploader

                        # Mock API
                        mock_api = _make_api_mock()
                        mock_api.get_complete_answer.return_value = Answer(
                            text="Comparison result", references=[]
                        )
                        mock_api_class.return_value = mock_api

                        # Run query with multiple attachments
                        result = runner.invoke(
                            query,
                            [
                                "--no-stream",
                                "--attach",
                                f"{file1},{file2}",
                                "Compare these files",
                            ],
                        )

                        assert result.exit_code == 0
                        assert "Comparison result" in result.output
                        assert "Loading 2 file(s)" in result.output
                        assert "Loaded 2 attachment(s)" in result.output

                        # Verify API received both S3 URL attachments
                        call_args = mock_api.get_complete_answer.call_args
                        attachments = call_args[1]["attachments"]
                        assert len(attachments) == 2
                        assert all(
                            isinstance(url, str) and url.startswith("https://")
                            for url in attachments
                        )

    def test_query_with_repeated_attach_flags(self, runner, tmp_path):
        """Test query with repeated --attach flags."""
        # Create test files
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("Content 1", encoding="utf-8")
        file2.write_text("Content 2", encoding="utf-8")

        with patch("perplexity_cli.utils.style_manager.StyleManager") as mock_sm_class:
            with patch("perplexity_cli.auth.token_manager.TokenManager") as mock_tm_class:
                with patch("perplexity_cli.attachments.AttachmentUploader") as mock_uploader_class:
                    with patch("perplexity_cli.api.endpoints.PerplexityAPI") as mock_api_class:
                        # Mock style manager
                        mock_sm = Mock()
                        mock_sm.load_style.return_value = None
                        mock_sm_class.return_value = mock_sm

                        # Mock token manager
                        mock_tm = Mock()
                        mock_tm.load_token.return_value = ("test-token", None)
                        mock_tm_class.return_value = mock_tm

                        # Mock uploader
                        async def mock_upload(*args, **kwargs):
                            return [
                                "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file1.txt",
                                "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file2.txt",
                            ]

                        mock_uploader = Mock()
                        mock_uploader.upload_files = mock_upload
                        mock_uploader_class.return_value = mock_uploader

                        # Mock API
                        mock_api = _make_api_mock()
                        mock_api.get_complete_answer.return_value = Answer(
                            text="Result", references=[]
                        )
                        mock_api_class.return_value = mock_api

                        # Run query with repeated --attach flags
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
                        assert "Loading 2 file(s)" in result.output
                        assert "Loaded 2 attachment(s)" in result.output

                        # Verify both S3 URLs received
                        call_args = mock_api.get_complete_answer.call_args
                        attachments = call_args[1]["attachments"]
                        assert len(attachments) == 2
                        assert all(
                            isinstance(url, str) and url.startswith("https://")
                            for url in attachments
                        )

    def test_query_attachment_nonexistent_file_error(self, runner):
        """Test query with nonexistent file produces error."""
        with patch("perplexity_cli.utils.style_manager.StyleManager") as mock_sm_class:
            with patch("perplexity_cli.auth.token_manager.TokenManager") as mock_tm_class:
                # Mock style manager
                mock_sm = Mock()
                mock_sm.load_style.return_value = None
                mock_sm_class.return_value = mock_sm

                # Mock token manager
                mock_tm = Mock()
                mock_tm.load_token.return_value = ("test-token", None)
                mock_tm_class.return_value = mock_tm

                # Run query with nonexistent file
                result = runner.invoke(
                    query,
                    ["--no-stream", "--attach", "/nonexistent/file.txt", "Test"],
                )

                assert result.exit_code == 1
                assert "Failed to load attachments" in result.output
                assert "File or directory not found" in result.output

    def test_query_with_directory_attachment(self, runner, tmp_path):
        """Test query with directory attachment."""
        # Create test files in directory
        (tmp_path / "file1.txt").write_text("Content 1", encoding="utf-8")
        (tmp_path / "file2.txt").write_text("Content 2", encoding="utf-8")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "file3.txt").write_text("Content 3", encoding="utf-8")

        with patch("perplexity_cli.utils.style_manager.StyleManager") as mock_sm_class:
            with patch("perplexity_cli.auth.token_manager.TokenManager") as mock_tm_class:
                with patch("perplexity_cli.attachments.AttachmentUploader") as mock_uploader_class:
                    with patch("perplexity_cli.api.endpoints.PerplexityAPI") as mock_api_class:
                        # Mock style manager
                        mock_sm = Mock()
                        mock_sm.load_style.return_value = None
                        mock_sm_class.return_value = mock_sm

                        # Mock token manager
                        mock_tm = Mock()
                        mock_tm.load_token.return_value = ("test-token", None)
                        mock_tm_class.return_value = mock_tm

                        # Mock uploader
                        async def mock_upload(*args, **kwargs):
                            return [
                                "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file1.txt",
                                "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file2.txt",
                                "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file3.txt",
                            ]

                        mock_uploader = Mock()
                        mock_uploader.upload_files = mock_upload
                        mock_uploader_class.return_value = mock_uploader

                        # Mock API
                        mock_api = _make_api_mock()
                        mock_api.get_complete_answer.return_value = Answer(
                            text="Analysis complete", references=[]
                        )
                        mock_api_class.return_value = mock_api

                        # Run query with directory attachment
                        result = runner.invoke(
                            query,
                            ["--no-stream", "--attach", str(tmp_path), "Analyse all files"],
                        )

                        assert result.exit_code == 0
                        assert "Loading 3 file(s)" in result.output
                        assert "Loaded 3 attachment(s)" in result.output

                        # Verify all files from directory are included
                        call_args = mock_api.get_complete_answer.call_args
                        attachments = call_args[1]["attachments"]
                        assert len(attachments) == 3
                        assert all(
                            isinstance(url, str) and url.startswith("https://")
                            for url in attachments
                        )
