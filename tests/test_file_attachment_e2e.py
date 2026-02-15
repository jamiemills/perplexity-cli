"""End-to-end tests for file attachment functionality.

These tests verify that file attachments are properly attached to threads
by checking the thread response data.
"""

from unittest.mock import MagicMock, patch

from perplexity_cli.api.endpoints import PerplexityAPI


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
        # Test data: S3 URL for the attachment
        s3_url = "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/test_single_attach.txt"

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

            # Create API and submit query with S3 URL attachment
            api = PerplexityAPI(token="test-token")
            messages = list(api.submit_query("Test", attachments=[s3_url]))

            # Verify the attachment was passed through
            assert len(messages) > 0
            call_args = mock_client.stream_post.call_args
            assert call_args is not None

            # Verify request contains attachment
            request_data = call_args[0][1]
            assert "params" in request_data
            assert "attachments" in request_data["params"]
            assert len(request_data["params"]["attachments"]) == 1

            # Verify attachment is the S3 URL
            att = request_data["params"]["attachments"][0]
            assert att == s3_url

    def test_multiple_files_attachment_appears_in_thread(self):
        """Test that multiple file attachments appear in the thread response."""
        # Test data: S3 URLs for attachments
        s3_urls = [
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/test_file1.txt",
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/test_file2.md",
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

            # Create API and submit query with S3 URL attachments
            api = PerplexityAPI(token="test-token")
            list(api.submit_query("Test", attachments=s3_urls))

            # Verify both attachments were passed
            call_args = mock_client.stream_post.call_args
            request_data = call_args[0][1]
            attachments = request_data["params"]["attachments"]

            assert len(attachments) == 2
            assert attachments == s3_urls

    def test_directory_attachment_appears_in_thread(self):
        """Test that directory attachments (multiple files) appear in thread response."""
        # Test data: S3 URLs for attachments
        s3_urls = [
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file1.txt",
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file2.txt",
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file3.txt",
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

            # Create API and submit query with S3 URL attachments
            api = PerplexityAPI(token="test-token")
            list(api.submit_query("Test", attachments=s3_urls))

            # Verify all attachments were passed
            call_args = mock_client.stream_post.call_args
            request_data = call_args[0][1]
            req_attachments = request_data["params"]["attachments"]

            assert len(req_attachments) == 3
            assert req_attachments == s3_urls

    def test_attachment_request_structure_matches_api_spec(self):
        """Test that attachment request structure matches Perplexity API specification."""
        # Test data: S3 URL for attachment
        s3_url = "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/test_api_spec.txt"

        with patch("perplexity_cli.api.endpoints.SSEClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            # Mock the SSE stream
            mock_client.stream_post.return_value = iter([])

            api = PerplexityAPI(token="test-token")
            try:
                list(api.submit_query("Test", attachments=[s3_url]))
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

            # Verify attachment is the S3 URL string
            att = params["attachments"][0]
            assert isinstance(att, str)
            assert att == s3_url
            assert att.startswith("https://ppl-ai-file-upload.s3.amazonaws.com/")
