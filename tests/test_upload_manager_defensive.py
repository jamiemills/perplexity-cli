"""Tests for defensive programming in AttachmentUploader._upload_to_s3()."""

import base64
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from perplexity_cli.api.models import FileAttachment
from perplexity_cli.attachments.upload_manager import AttachmentUploader
from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError


class TestUploadManagerDefensive:
    """Defensive programming tests for upload manager."""

    @pytest.fixture
    def uploader(self):
        """Create an AttachmentUploader instance."""
        return AttachmentUploader(token="test-token")

    @pytest.fixture
    def test_attachment(self):
        """Create a test FileAttachment."""
        content = b"Test file content"
        return FileAttachment(
            filename="test.txt",
            content_type="text/plain",
            data=base64.b64encode(content).decode(),
        )

    @pytest.mark.asyncio
    async def test_upload_to_s3_with_null_fields(self, uploader, test_attachment):
        """Test that _upload_to_s3 handles null 'fields' value gracefully.

        This tests the defensive fix for the bug where API returns:
        {"fields": null, "s3_object_url": "..."}

        Previously would crash with AttributeError: 'NoneType' object has no attribute 'items'
        """
        upload_data = {
            "fields": None,  # API returned null instead of dict
            "s3_object_url": "https://ppl-ai-file-upload.s3.amazonaws.com/test.txt",
        }

        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 204  # Success
        mock_session.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient") as mock_httpx_client:
            # Mock the context manager
            mock_client_instance = AsyncMock()
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_httpx_client.return_value = mock_client_instance

            # Should not raise AttributeError, should return S3 URL
            result = await uploader._upload_to_s3(test_attachment, upload_data, mock_session)

            assert result == "https://ppl-ai-file-upload.s3.amazonaws.com/test.txt"

    @pytest.mark.asyncio
    async def test_upload_to_s3_with_empty_fields_dict(self, uploader, test_attachment):
        """Test that _upload_to_s3 works with empty 'fields' dict."""
        upload_data = {
            "fields": {},  # Empty dict (no form fields)
            "s3_object_url": "https://ppl-ai-file-upload.s3.amazonaws.com/test.txt",
        }

        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_session.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient") as mock_httpx_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_httpx_client.return_value = mock_client_instance

            result = await uploader._upload_to_s3(test_attachment, upload_data, mock_session)

            assert result == "https://ppl-ai-file-upload.s3.amazonaws.com/test.txt"
            # Verify post was called with only the file (no extra form fields)
            call_args = mock_client_instance.post.call_args
            assert "files" in call_args.kwargs

    @pytest.mark.asyncio
    async def test_upload_to_s3_with_normal_fields(self, uploader, test_attachment):
        """Test that _upload_to_s3 works normally with proper fields dict."""
        upload_data = {
            "fields": {
                "policy": "base64-encoded-policy",
                "x-amz-signature": "signature-value",
                "x-amz-credential": "credential-value",
                "key": "uploads/test.txt",
            },
            "s3_object_url": "https://ppl-ai-file-upload.s3.amazonaws.com/test.txt",
        }

        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_session.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient") as mock_httpx_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_httpx_client.return_value = mock_client_instance

            result = await uploader._upload_to_s3(test_attachment, upload_data, mock_session)

            assert result == "https://ppl-ai-file-upload.s3.amazonaws.com/test.txt"
            # Verify all form fields were included
            call_args = mock_client_instance.post.call_args
            files_dict = call_args.kwargs["files"]
            assert "policy" in files_dict
            assert "x-amz-signature" in files_dict
            assert "x-amz-credential" in files_dict

    @pytest.mark.asyncio
    async def test_upload_to_s3_with_false_fields(self, uploader, test_attachment):
        """Test that _upload_to_s3 handles falsy 'fields' values correctly."""
        # Test various falsy values that could break the code
        falsy_values = [None, False, 0, "", []]

        for falsy_value in falsy_values:
            upload_data = {
                "fields": falsy_value,
                "s3_object_url": "https://ppl-ai-file-upload.s3.amazonaws.com/test.txt",
            }

            mock_session = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_session.post = AsyncMock(return_value=mock_response)

            with patch("httpx.AsyncClient") as mock_httpx_client:
                mock_client_instance = AsyncMock()
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                mock_client_instance.post = AsyncMock(return_value=mock_response)
                mock_httpx_client.return_value = mock_client_instance

                # Should not raise, should use empty dict instead
                result = await uploader._upload_to_s3(test_attachment, upload_data, mock_session)

                assert result == "https://ppl-ai-file-upload.s3.amazonaws.com/test.txt"

    @pytest.mark.asyncio
    async def test_request_upload_urls_logs_on_auth_error(self, uploader):
        """Test that API auth errors are logged with helpful message."""
        attachments = [
            FileAttachment(
                filename="test.txt",
                content_type="text/plain",
                data=base64.b64encode(b"content").decode(),
            )
        ]

        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 401  # Unauthorized
        mock_response.url = "https://api.perplexity.ai/rest/uploads/batch_create_upload_urls"
        mock_response.headers = {}
        mock_response.text = '{"error": "Invalid token"}'
        mock_session.post = AsyncMock(return_value=mock_response)

        with patch("curl_cffi.requests.AsyncSession") as mock_session_class:
            mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(PerplexityHTTPStatusError) as exc_info:
                await uploader._request_upload_urls(attachments)

            # Verify the error was raised
            assert exc_info.value is not None

    @pytest.mark.asyncio
    async def test_upload_files_with_null_fields_in_response(self, uploader):
        """Test full upload_files workflow when API returns null fields.

        This is an integration test that verifies the defensive fix works
        in the complete upload flow.
        """
        attachments = [
            FileAttachment(
                filename="test.txt",
                content_type="text/plain",
                data=base64.b64encode(b"Test content").decode(),
            )
        ]

        # Mock S3 response
        mock_s3_response = MagicMock()
        mock_s3_response.status_code = 204  # Success

        async def mock_request_upload_urls(attachments):
            """Mock _request_upload_urls to return null fields."""
            # Create UUID->attachment mapping like the real code does
            uuid_to_attachment = {
                "uuid-1": attachments[0],
            }

            # Return response with null fields (the problematic case)
            api_response = {
                "results": {
                    "uuid-1": {
                        "fields": None,  # This is the problematic response
                        "s3_object_url": "https://ppl-ai-file-upload.s3.amazonaws.com/test.txt",
                    }
                }
            }

            return api_response, uuid_to_attachment

        with patch.object(uploader, "_request_upload_urls", side_effect=mock_request_upload_urls):
            with patch(
                "perplexity_cli.attachments.upload_manager.AsyncSession"
            ) as mock_session_class:
                with patch("httpx.AsyncClient") as mock_httpx_client:
                    # Mock S3 upload session
                    mock_s3_session = AsyncMock()
                    mock_session_class.return_value.__aenter__ = AsyncMock(
                        return_value=mock_s3_session
                    )
                    mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)

                    # Mock httpx client for S3 upload
                    mock_s3_client = AsyncMock()
                    mock_s3_client.post = AsyncMock(return_value=mock_s3_response)
                    mock_httpx_client.return_value.__aenter__ = AsyncMock(
                        return_value=mock_s3_client
                    )
                    mock_httpx_client.return_value.__aexit__ = AsyncMock(return_value=None)

                    # Should not raise, should return the S3 URL
                    result = await uploader.upload_files(attachments)

                    assert len(result) == 1
                    assert result[0] == "https://ppl-ai-file-upload.s3.amazonaws.com/test.txt"


class TestUploadManagerLogging:
    """Tests for logging and error messages in upload manager."""

    @pytest.fixture
    def uploader(self):
        """Create an AttachmentUploader instance."""
        return AttachmentUploader(token="test-token")

    @pytest.mark.asyncio
    async def test_auth_error_logging_message(self, uploader, caplog):
        """Test that helpful error message is logged on auth failure."""
        attachments = [
            FileAttachment(
                filename="test.txt",
                content_type="text/plain",
                data=base64.b64encode(b"content").decode(),
            )
        ]

        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 401
        mock_response.url = "https://api.perplexity.ai/rest/uploads/batch_create_upload_urls"
        mock_response.headers = {}
        mock_response.text = '{"error": "Unauthorized"}'
        mock_session.post = AsyncMock(return_value=mock_response)

        with patch("curl_cffi.requests.AsyncSession") as mock_session_class:
            mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)

            with caplog.at_level(logging.ERROR):
                with pytest.raises(PerplexityHTTPStatusError):
                    await uploader._request_upload_urls(attachments)

            # Verify helpful error message was logged
            error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
            assert any(
                "invalid or expired token" in record.message.lower() for record in error_logs
            )
            assert any("pxcli auth" in record.message for record in error_logs)

    @pytest.mark.asyncio
    async def test_unexpected_fields_type_warning_logged(self, uploader, caplog):
        """Test that a warning is logged when fields has unexpected type.

        The defensive fix handles when fields is:
        - None (converted to empty dict by "or {}")
        - dict (expected case)
        - Any other type (list, string, etc.) → triggers warning

        This test verifies the warning is logged for unexpected types.
        """
        # Create a test attachment
        test_attachment = FileAttachment(
            filename="test.txt",
            content_type="text/plain",
            data=base64.b64encode(b"Test file content").decode(),
        )

        upload_data = {
            "fields": ["unexpected", "list"],  # Unexpected type (not None, not dict)
            "s3_object_url": "https://ppl-ai-file-upload.s3.amazonaws.com/test.txt",
        }

        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_session.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient") as mock_httpx_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_httpx_client.return_value = mock_client_instance

            with caplog.at_level(logging.WARNING):
                await uploader._upload_to_s3(test_attachment, upload_data, mock_session)

            # Verify warning was logged
            warning_logs = [record for record in caplog.records if record.levelname == "WARNING"]
            assert any("Unexpected fields type" in record.message for record in warning_logs)
