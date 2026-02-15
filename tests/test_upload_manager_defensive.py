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

        Previously would crash with AttributeError: 'NoneType' object has no
        attribute 'items'.
        """
        upload_data = {
            "fields": None,
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

    @pytest.mark.asyncio
    async def test_upload_to_s3_with_empty_fields_dict(self, uploader, test_attachment):
        """Test that _upload_to_s3 works with empty 'fields' dict."""
        upload_data = {
            "fields": {},
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
            call_args = mock_client_instance.post.call_args
            files_dict = call_args.kwargs["files"]
            assert "policy" in files_dict
            assert "x-amz-signature" in files_dict
            assert "x-amz-credential" in files_dict

    @pytest.mark.asyncio
    async def test_upload_to_s3_with_false_fields(self, uploader, test_attachment):
        """Test that _upload_to_s3 handles falsy 'fields' values correctly."""
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
        mock_response.status_code = 401
        mock_response.url = "https://api.perplexity.ai/rest/uploads/batch_create_upload_urls"
        mock_response.headers = {}
        mock_response.text = '{"error": "Invalid token"}'
        mock_session.post = AsyncMock(return_value=mock_response)

        with patch("curl_cffi.requests.AsyncSession") as mock_session_class:
            mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(PerplexityHTTPStatusError):
                await uploader._request_upload_urls(attachments)

    @pytest.mark.asyncio
    async def test_upload_files_with_null_fields_in_response(self, uploader):
        """Test full upload_files workflow when _request_upload_urls returns null fields.

        When _request_upload_urls returns data with null fields (bypassing the
        validation in that method), _upload_to_s3 handles it defensively.
        """
        attachments = [
            FileAttachment(
                filename="test.txt",
                content_type="text/plain",
                data=base64.b64encode(b"Test content").decode(),
            )
        ]

        mock_s3_response = MagicMock()
        mock_s3_response.status_code = 204

        async def mock_request_upload_urls(attachments):
            """Mock _request_upload_urls to return null fields."""
            uuid_to_attachment = {"uuid-1": attachments[0]}
            api_response = {
                "results": {
                    "uuid-1": {
                        "fields": None,
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
                    mock_s3_session = AsyncMock()
                    mock_session_class.return_value.__aenter__ = AsyncMock(
                        return_value=mock_s3_session
                    )
                    mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)

                    mock_s3_client = AsyncMock()
                    mock_s3_client.post = AsyncMock(return_value=mock_s3_response)
                    mock_httpx_client.return_value.__aenter__ = AsyncMock(
                        return_value=mock_s3_client
                    )
                    mock_httpx_client.return_value.__aexit__ = AsyncMock(return_value=None)

                    result = await uploader.upload_files(attachments)

                    assert len(result) == 1
                    assert result[0] == "https://ppl-ai-file-upload.s3.amazonaws.com/test.txt"


class TestUploadManagerQuotaHandling:
    """Tests for upload quota exhaustion and rate limit handling."""

    @pytest.fixture
    def uploader(self):
        """Create an AttachmentUploader instance."""
        return AttachmentUploader(token="test-token")

    @pytest.mark.asyncio
    async def test_rate_limited_response_raises_quota_error(self, uploader):
        """Test that rate_limited: true produces a clear quota exhaustion message."""
        attachments = [
            FileAttachment(
                filename="test.txt",
                content_type="text/plain",
                data=base64.b64encode(b"content").decode(),
            )
        ]

        api_response = {
            "results": {
                "uuid-1": {
                    "s3_bucket_url": None,
                    "s3_object_url": None,
                    "fields": None,
                    "rate_limited": True,
                    "file_uuid": None,
                    "error": None,
                }
            }
        }

        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value=api_response)
        mock_session.post = AsyncMock(return_value=mock_response)

        with patch("perplexity_cli.attachments.upload_manager.AsyncSession") as mock_session_class:
            mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(RuntimeError, match="File upload quota exhausted"):
                await uploader._request_upload_urls(attachments)

    @pytest.mark.asyncio
    async def test_rate_limited_error_mentions_account_settings(self, uploader):
        """Test that quota error message directs user to account settings."""
        attachments = [
            FileAttachment(
                filename="test.txt",
                content_type="text/plain",
                data=base64.b64encode(b"content").decode(),
            )
        ]

        api_response = {
            "results": {
                "uuid-1": {
                    "s3_object_url": None,
                    "fields": None,
                    "rate_limited": True,
                }
            }
        }

        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value=api_response)
        mock_session.post = AsyncMock(return_value=mock_response)

        with patch("perplexity_cli.attachments.upload_manager.AsyncSession") as mock_session_class:
            mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(RuntimeError, match="perplexity.ai/settings/account"):
                await uploader._request_upload_urls(attachments)

    @pytest.mark.asyncio
    async def test_api_error_in_response_body(self, uploader):
        """Test that API error field is included in error message."""
        attachments = [
            FileAttachment(
                filename="test.txt",
                content_type="text/plain",
                data=base64.b64encode(b"content").decode(),
            )
        ]

        api_response = {
            "results": {
                "uuid-1": {
                    "s3_object_url": None,
                    "fields": None,
                    "rate_limited": False,
                    "error": "File type not supported",
                }
            }
        }

        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value=api_response)
        mock_session.post = AsyncMock(return_value=mock_response)

        with patch("perplexity_cli.attachments.upload_manager.AsyncSession") as mock_session_class:
            mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(RuntimeError, match="File type not supported"):
                await uploader._request_upload_urls(attachments)

    @pytest.mark.asyncio
    async def test_null_fields_no_rate_limit_no_error(self, uploader):
        """Test generic error when fields null with no rate_limited or error."""
        attachments = [
            FileAttachment(
                filename="test.txt",
                content_type="text/plain",
                data=base64.b64encode(b"content").decode(),
            )
        ]

        api_response = {
            "results": {
                "uuid-1": {
                    "s3_object_url": None,
                    "fields": None,
                    "rate_limited": False,
                    "error": None,
                }
            }
        }

        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value=api_response)
        mock_session.post = AsyncMock(return_value=mock_response)

        with patch("perplexity_cli.attachments.upload_manager.AsyncSession") as mock_session_class:
            mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(RuntimeError, match="authentication or account issue"):
                await uploader._request_upload_urls(attachments)

    @pytest.mark.asyncio
    async def test_valid_response_passes_through(self, uploader):
        """Test that a valid presigned URL response passes validation."""
        attachments = [
            FileAttachment(
                filename="test.txt",
                content_type="text/plain",
                data=base64.b64encode(b"content").decode(),
            )
        ]

        api_response = {
            "results": {
                "uuid-1": {
                    "s3_object_url": "https://ppl-ai-file-upload.s3.amazonaws.com/test.txt",
                    "fields": {
                        "key": "uploads/test.txt",
                        "policy": "base64policy",
                        "x-amz-signature": "sig",
                    },
                    "rate_limited": False,
                }
            }
        }

        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value=api_response)
        mock_session.post = AsyncMock(return_value=mock_response)

        with patch("perplexity_cli.attachments.upload_manager.AsyncSession") as mock_session_class:
            mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)

            # Patch uuid4 to return a known UUID matching our response
            with patch("perplexity_cli.attachments.upload_manager.uuid.uuid4") as mock_uuid:
                mock_uuid.return_value = type("UUID", (), {"__str__": lambda s: "uuid-1"})()
                response_json, uuid_map = await uploader._request_upload_urls(attachments)

            assert "uuid-1" in response_json["results"]
            assert response_json["results"]["uuid-1"]["fields"] is not None


class TestUploadManagerCookies:
    """Tests for cookie passing in upload manager."""

    @pytest.mark.asyncio
    async def test_cookies_passed_to_api_request(self):
        """Test that cookies are sent with the presigned URL request."""
        cookies = {
            "cf_clearance": "test-clearance",
            "csrftoken": "test-csrf",
            "pplx.session-id": "test-session",
        }
        uploader = AttachmentUploader(token="test-token", cookies=cookies)

        attachments = [
            FileAttachment(
                filename="test.txt",
                content_type="text/plain",
                data=base64.b64encode(b"content").decode(),
            )
        ]

        api_response = {
            "results": {
                "uuid-1": {
                    "s3_object_url": "https://s3.example.com/test.txt",
                    "fields": {"key": "test"},
                    "rate_limited": False,
                }
            }
        }

        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value=api_response)
        mock_session.post = AsyncMock(return_value=mock_response)

        with patch("perplexity_cli.attachments.upload_manager.AsyncSession") as mock_session_class:
            mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("perplexity_cli.attachments.upload_manager.uuid.uuid4") as mock_uuid:
                mock_uuid.return_value = type("UUID", (), {"__str__": lambda s: "uuid-1"})()
                await uploader._request_upload_urls(attachments)

            # Verify cookies were passed in the request
            call_args = mock_session.post.call_args
            assert call_args.kwargs["cookies"] == cookies

    @pytest.mark.asyncio
    async def test_csrf_token_in_headers(self):
        """Test that X-CSRFToken header is set from cookies."""
        cookies = {"csrftoken": "test-csrf-value"}
        uploader = AttachmentUploader(token="test-token", cookies=cookies)

        attachments = [
            FileAttachment(
                filename="test.txt",
                content_type="text/plain",
                data=base64.b64encode(b"content").decode(),
            )
        ]

        api_response = {
            "results": {
                "uuid-1": {
                    "s3_object_url": "https://s3.example.com/test.txt",
                    "fields": {"key": "test"},
                    "rate_limited": False,
                }
            }
        }

        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value=api_response)
        mock_session.post = AsyncMock(return_value=mock_response)

        with patch("perplexity_cli.attachments.upload_manager.AsyncSession") as mock_session_class:
            mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("perplexity_cli.attachments.upload_manager.uuid.uuid4") as mock_uuid:
                mock_uuid.return_value = type("UUID", (), {"__str__": lambda s: "uuid-1"})()
                await uploader._request_upload_urls(attachments)

            call_args = mock_session.post.call_args
            headers = call_args.kwargs["headers"]
            assert headers["X-CSRFToken"] == "test-csrf-value"

    @pytest.mark.asyncio
    async def test_origin_and_referer_headers_sent(self):
        """Test that Origin and Referer headers are included in requests."""
        uploader = AttachmentUploader(token="test-token")

        attachments = [
            FileAttachment(
                filename="test.txt",
                content_type="text/plain",
                data=base64.b64encode(b"content").decode(),
            )
        ]

        api_response = {
            "results": {
                "uuid-1": {
                    "s3_object_url": "https://s3.example.com/test.txt",
                    "fields": {"key": "test"},
                    "rate_limited": False,
                }
            }
        }

        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value=api_response)
        mock_session.post = AsyncMock(return_value=mock_response)

        with patch("perplexity_cli.attachments.upload_manager.AsyncSession") as mock_session_class:
            mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("perplexity_cli.attachments.upload_manager.uuid.uuid4") as mock_uuid:
                mock_uuid.return_value = type("UUID", (), {"__str__": lambda s: "uuid-1"})()
                await uploader._request_upload_urls(attachments)

            call_args = mock_session.post.call_args
            headers = call_args.kwargs["headers"]
            assert headers["Origin"] == "https://www.perplexity.ai"
            assert headers["Referer"] == "https://www.perplexity.ai/"

    @pytest.mark.asyncio
    async def test_no_cookies_sends_empty_dict(self):
        """Test that no cookies results in empty dict (not None)."""
        uploader = AttachmentUploader(token="test-token")

        attachments = [
            FileAttachment(
                filename="test.txt",
                content_type="text/plain",
                data=base64.b64encode(b"content").decode(),
            )
        ]

        api_response = {
            "results": {
                "uuid-1": {
                    "s3_object_url": "https://s3.example.com/test.txt",
                    "fields": {"key": "test"},
                    "rate_limited": False,
                }
            }
        }

        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value=api_response)
        mock_session.post = AsyncMock(return_value=mock_response)

        with patch("perplexity_cli.attachments.upload_manager.AsyncSession") as mock_session_class:
            mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("perplexity_cli.attachments.upload_manager.uuid.uuid4") as mock_uuid:
                mock_uuid.return_value = type("UUID", (), {"__str__": lambda s: "uuid-1"})()
                await uploader._request_upload_urls(attachments)

            call_args = mock_session.post.call_args
            assert call_args.kwargs["cookies"] == {}


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

            error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
            assert any(
                "invalid or expired token" in record.message.lower() for record in error_logs
            )
            assert any("pxcli auth" in record.message for record in error_logs)

    @pytest.mark.asyncio
    async def test_unexpected_fields_type_warning_logged(self, uploader, caplog):
        """Test that a warning is logged when fields has unexpected type."""
        test_attachment = FileAttachment(
            filename="test.txt",
            content_type="text/plain",
            data=base64.b64encode(b"Test file content").decode(),
        )

        upload_data = {
            "fields": ["unexpected", "list"],
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

            warning_logs = [record for record in caplog.records if record.levelname == "WARNING"]
            assert any("Unexpected fields type" in record.message for record in warning_logs)
