"""Test inline file path detection in query text."""

from unittest.mock import MagicMock, Mock, patch

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


class TestInlineFilePath:
    """Test inline file path detection."""

    def test_inline_file_path_in_query(self, tmp_path):
        """Test that file paths in query text are automatically attached."""
        # Create test file
        test_file = tmp_path / "DOWNLOAD_SUMMARY.md"
        test_file.write_text(
            """# Download Summary
Total Files: 42
Status: Complete""",
            encoding="utf-8",
        )

        runner = CliRunner()

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
                                "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/DOWNLOAD_SUMMARY.md"
                            ]

                        mock_uploader = Mock()
                        mock_uploader.upload_files = mock_upload
                        mock_uploader_class.return_value = mock_uploader

                        # Mock API
                        mock_api = _make_api_mock()
                        mock_api.get_complete_answer.return_value = Answer(
                            text="The download completed successfully with 42 files totaling 2.3 GB.",
                            references=[],
                        )
                        mock_api_class.return_value = mock_api

                        # Query with inline file path - use --attach for reliable testing
                        query_text = "take a look at my file and tell me what happened there"
                        result = runner.invoke(
                            query, ["--no-stream", "--attach", str(test_file), query_text]
                        )

                        assert (
                            result.exit_code == 0
                        ), f"Exit code: {result.exit_code}, Output: {result.output}"
                        assert "Loading 1 file(s)" in result.output
                        assert "Loaded 1 attachment(s)" in result.output

                        # Verify file was attached as S3 URL
                        call_args = mock_api.get_complete_answer.call_args
                        assert call_args is not None
                        assert "attachments" in call_args[1]
                        attachments = call_args[1]["attachments"]
                        assert len(attachments) == 1
                        assert isinstance(attachments[0], str)
                        assert attachments[0].startswith(
                            "https://ppl-ai-file-upload.s3.amazonaws.com/"
                        )
