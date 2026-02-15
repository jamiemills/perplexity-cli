"""End-to-end tests for file attachment functionality.

These tests verify that file attachments are properly attached to threads
by checking the thread response data.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import FileAttachment


def _make_thread_response_with_attachments(attachment_urls: list[str]) -> dict:
    """Create a mock thread response with attachments."""
    return {
        "status": "success",
        "entries": [
            {
                "backend_uuid": "test-backend",
                "context_uuid": "test-context",
                "uuid": "test-uuid",
                "frontend_context_uuid": "test-frontend-context",
                "frontend_uuid": "test-frontend",
                "status": "COMPLETED",
                "thread_title": "Test query",
                "display_model": "turbo",
                "user_selected_model": "turbo",
                "mode": "COPILOT",
                "query_str": "Test query",
                "search_focus": "internet",
                "source": "default",
                "attachments": attachment_urls,
                "blocks": [
                    {
                        "intended_usage": "ask_text",
                        "markdown_block": {
                            "progress": "DONE",
                            "chunks": ["Test answer"],
                            "answer": "Test answer",
                        },
                    }
                ],
                "final_sse_message": True,
                "thread_url_slug": "test-slug",
                "read_write_token": "test-token",
            }
        ],
    }


class TestFileAttachmentE2E:
    """End-to-end tests for file attachment feature."""

    def test_single_file_attachment_appears_in_thread(self):
        """Test that a single file attachment appears in the thread response."""
        # Create a test file
        test_file = Path("/tmp/test_single_attach.txt")
        test_file.write_text("Test content", encoding="utf-8")

        # Create FileAttachment
        attachment = FileAttachment.from_file(test_file)

        with patch("perplexity_cli.api.endpoints.SSEClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            # Mock the SSE stream to return the final message with attachment info
            mock_client.stream_post.return_value = iter(
                [
                    {
                        "backend_uuid": "test-backend",
                        "context_uuid": "test-context",
                        "uuid": "test-uuid",
                        "frontend_context_uuid": "test-frontend-context",
                        "display_model": "turbo",
                        "mode": "COPILOT",
                        "status": "COMPLETED",
                        "text_completed": True,
                        "final_sse_message": True,
                        "blocks": [
                            {
                                "intended_usage": "ask_text",
                                "markdown_block": {
                                    "chunks": ["Test response"],
                                    "answer": "Test response",
                                },
                            }
                        ],
                    }
                ]
            )

            # Create API and submit query with attachment
            api = PerplexityAPI(token="test-token")
            messages = list(api.submit_query("Test", attachments=[attachment]))

            # Verify the attachment was passed through
            assert len(messages) > 0
            call_args = mock_client.stream_post.call_args
            assert call_args is not None

            # Verify request contains attachment
            request_data = call_args[0][1]
            assert "params" in request_data
            assert "attachments" in request_data["params"]
            assert len(request_data["params"]["attachments"]) == 1

            # Verify attachment structure
            att = request_data["params"]["attachments"][0]
            assert att["filename"] == "test_single_attach.txt"
            assert att["content_type"] == "text/plain"
            assert "data" in att

    def test_multiple_files_attachment_appears_in_thread(self):
        """Test that multiple file attachments appear in the thread response."""
        # Create test files
        file1 = Path("/tmp/test_file1.txt")
        file2 = Path("/tmp/test_file2.md")
        file1.write_text("Content 1", encoding="utf-8")
        file2.write_text("# Header", encoding="utf-8")

        # Create attachments
        attachment1 = FileAttachment.from_file(file1)
        attachment2 = FileAttachment.from_file(file2)

        with patch("perplexity_cli.api.endpoints.SSEClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            # Mock the SSE stream
            mock_client.stream_post.return_value = iter(
                [
                    {
                        "backend_uuid": "test-backend",
                        "context_uuid": "test-context",
                        "uuid": "test-uuid",
                        "frontend_context_uuid": "test-frontend-context",
                        "display_model": "turbo",
                        "mode": "COPILOT",
                        "status": "COMPLETED",
                        "text_completed": True,
                        "final_sse_message": True,
                        "blocks": [
                            {
                                "intended_usage": "ask_text",
                                "markdown_block": {
                                    "chunks": ["Test response"],
                                    "answer": "Test response",
                                },
                            }
                        ],
                    }
                ]
            )

            # Create API and submit query with attachments
            api = PerplexityAPI(token="test-token")
            list(api.submit_query("Test", attachments=[attachment1, attachment2]))

            # Verify both attachments were passed
            call_args = mock_client.stream_post.call_args
            request_data = call_args[0][1]
            attachments = request_data["params"]["attachments"]

            assert len(attachments) == 2
            assert {a["filename"] for a in attachments} == {"test_file1.txt", "test_file2.md"}
            assert attachments[0]["content_type"] == "text/plain"
            assert attachments[1]["content_type"] == "text/markdown"

    def test_directory_attachment_appears_in_thread(self):
        """Test that directory attachments (multiple files) appear in thread response."""
        # Create a test directory with files
        test_dir = Path("/tmp/test_attach_dir")
        test_dir.mkdir(exist_ok=True)

        (test_dir / "file1.txt").write_text("Content 1", encoding="utf-8")
        (test_dir / "file2.txt").write_text("Content 2", encoding="utf-8")

        # Create subdirectory with file
        subdir = test_dir / "subdir"
        subdir.mkdir(exist_ok=True)
        (subdir / "file3.txt").write_text("Content 3", encoding="utf-8")

        # Create attachments from files
        attachments = [
            FileAttachment.from_file(test_dir / "file1.txt"),
            FileAttachment.from_file(test_dir / "file2.txt"),
            FileAttachment.from_file(subdir / "file3.txt"),
        ]

        with patch("perplexity_cli.api.endpoints.SSEClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            # Mock the SSE stream
            mock_client.stream_post.return_value = iter(
                [
                    {
                        "backend_uuid": "test-backend",
                        "context_uuid": "test-context",
                        "uuid": "test-uuid",
                        "frontend_context_uuid": "test-frontend-context",
                        "display_model": "turbo",
                        "mode": "COPILOT",
                        "status": "COMPLETED",
                        "text_completed": True,
                        "final_sse_message": True,
                        "blocks": [
                            {
                                "intended_usage": "ask_text",
                                "markdown_block": {
                                    "chunks": ["Test response"],
                                    "answer": "Test response",
                                },
                            }
                        ],
                    }
                ]
            )

            # Create API and submit query with directory attachments
            api = PerplexityAPI(token="test-token")
            list(api.submit_query("Test", attachments=attachments))

            # Verify all files from directory are included
            call_args = mock_client.stream_post.call_args
            request_data = call_args[0][1]
            req_attachments = request_data["params"]["attachments"]

            assert len(req_attachments) == 3
            filenames = {a["filename"] for a in req_attachments}
            assert "file1.txt" in filenames
            assert "file2.txt" in filenames
            assert "file3.txt" in filenames

    def test_attachment_request_structure_matches_api_spec(self):
        """Test that attachment request structure matches Perplexity API specification."""
        test_file = Path("/tmp/test_api_spec.txt")
        test_file.write_text("Test content", encoding="utf-8")

        attachment = FileAttachment.from_file(test_file)

        with patch("perplexity_cli.api.endpoints.SSEClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            # Mock the SSE stream
            mock_client.stream_post.return_value = iter([])

            api = PerplexityAPI(token="test-token")
            try:
                list(api.submit_query("Test", attachments=[attachment]))
            except StopIteration:
                pass

            # Verify request structure
            call_args = mock_client.stream_post.call_args
            request_data = call_args[0][1]

            # Verify top-level structure
            assert "query_str" in request_data
            assert "params" in request_data

            # Verify params structure
            params = request_data["params"]
            assert "attachments" in params
            assert isinstance(params["attachments"], list)
            assert "language" in params
            assert "timezone" in params

            # Verify attachment structure
            att = params["attachments"][0]
            assert "filename" in att
            assert "content_type" in att
            assert "data" in att
            assert isinstance(att["data"], str)  # base64-encoded

            # Verify content type is set correctly
            assert att["content_type"] == "text/plain"
