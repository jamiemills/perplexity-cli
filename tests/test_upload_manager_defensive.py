"""Tests for defensive programming in AttachmentUploader._upload_to_s3()."""

import base64
import logging
from unittest.mock import patch

import pytest

from perplexity_cli.attachments.upload_manager import AttachmentUploader
from perplexity_cli.utils.attachment_models import FileAttachment
from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError, UpstreamSchemaError
from tests.helpers.fake_transport import FakeHttpResponse, FakeHttpTransport
from tests.helpers.fake_uploader import FakeS3UploadClientFactory

_S3_OBJECT_URL = "https://ppl-ai-file-upload.s3.amazonaws.com/test.txt"
_UPLOAD_FACTORY = "perplexity_cli.attachments.upload_manager._get_httpx_async_client_factory"


def _make_attachment(
    *, filename: str = "test.txt", body: bytes = b"Test file content"
) -> FileAttachment:
    """Build a real FileAttachment from raw bytes."""
    return FileAttachment(
        filename=filename,
        content_type="text/plain",
        data=base64.b64encode(body).decode(),
    )


def _patch_s3_upload(response: FakeHttpResponse):
    """Inject *response* as the S3 upload boundary via the factory seam."""
    factory = FakeS3UploadClientFactory(response)
    return patch(_UPLOAD_FACTORY, return_value=factory, autospec=True)


class TestUploadManagerDefensive:
    """Defensive programming tests for upload manager."""

    @pytest.fixture
    def uploader(self):
        """Create an AttachmentUploader instance."""
        return AttachmentUploader(token="test-token")

    @pytest.fixture
    def test_attachment(self):
        """Create a test FileAttachment."""
        return _make_attachment()

    @pytest.mark.asyncio
    async def test_upload_to_s3_with_null_fields(self, uploader, test_attachment):
        """Test that _upload_to_s3 handles null 'fields' value gracefully.

        Previously would crash with AttributeError: 'NoneType' object has no
        attribute 'items'.
        """
        upload_data = {"fields": None, "s3_object_url": _S3_OBJECT_URL}

        with _patch_s3_upload(FakeHttpResponse(status_code=204)):
            result = await uploader._upload_to_s3(test_attachment, upload_data)

        assert result == _S3_OBJECT_URL

    @pytest.mark.asyncio
    async def test_upload_to_s3_with_empty_fields_dict(self, uploader, test_attachment):
        """Test that _upload_to_s3 works with empty 'fields' dict."""
        upload_data = {"fields": {}, "s3_object_url": _S3_OBJECT_URL}

        factory = FakeS3UploadClientFactory(FakeHttpResponse(status_code=204))
        with patch(_UPLOAD_FACTORY, return_value=factory, autospec=True):
            result = await uploader._upload_to_s3(test_attachment, upload_data)

        assert result == _S3_OBJECT_URL
        assert "files" in factory.last_client.last_post.kwargs

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
            "s3_object_url": _S3_OBJECT_URL,
        }

        factory = FakeS3UploadClientFactory(FakeHttpResponse(status_code=204))
        with patch(_UPLOAD_FACTORY, return_value=factory, autospec=True):
            result = await uploader._upload_to_s3(test_attachment, upload_data)

        assert result == _S3_OBJECT_URL
        files_dict = factory.last_client.last_post.kwargs["files"]
        assert "policy" in files_dict
        assert "x-amz-signature" in files_dict
        assert "x-amz-credential" in files_dict

    @pytest.mark.asyncio
    async def test_upload_to_s3_with_false_fields(self, uploader, test_attachment):
        """Test that _upload_to_s3 handles falsy 'fields' values correctly."""
        falsy_values = [None, False, 0, "", []]

        for falsy_value in falsy_values:
            upload_data = {"fields": falsy_value, "s3_object_url": _S3_OBJECT_URL}

            with _patch_s3_upload(FakeHttpResponse(status_code=204)):
                result = await uploader._upload_to_s3(test_attachment, upload_data)

            assert result == _S3_OBJECT_URL

    @pytest.mark.asyncio
    async def test_request_upload_urls_logs_on_auth_error(self, uploader):
        """Test that API auth errors are logged with helpful message."""
        attachments = [_make_attachment(body=b"content")]

        response = FakeHttpResponse(
            ok=False,
            status_code=401,
            url="https://api.perplexity.ai/rest/uploads/batch_create_upload_urls",
            headers={},
            content=b'{"error": "Invalid token"}',
            text='{"error": "Invalid token"}',
        )
        session = FakeHttpTransport(response=response)

        with pytest.raises(PerplexityHTTPStatusError):
            await uploader._request_upload_urls(attachments, session)

    @pytest.mark.asyncio
    async def test_upload_files_with_null_fields_in_response(self, uploader):
        """Test full upload_files workflow when _request_upload_urls returns null fields.

        When _request_upload_urls returns data with null fields (bypassing the
        validation in that method), _upload_to_s3 handles it defensively.
        """
        attachments = [_make_attachment(body=b"Test content")]

        async def stub_request_upload_urls(attachments, session):
            """Inject null-fields upload data, bypassing response validation."""
            uuid_to_attachment = {"uuid-1": attachments[0]}
            api_response = {
                "results": {"uuid-1": {"fields": None, "s3_object_url": _S3_OBJECT_URL}}
            }
            return api_response, uuid_to_attachment

        session = FakeHttpTransport()
        s3_factory = FakeS3UploadClientFactory(FakeHttpResponse(status_code=204))

        with patch.object(uploader, "_request_upload_urls", side_effect=stub_request_upload_urls):
            with patch.object(
                uploader, "_create_async_session", return_value=session, autospec=True
            ):
                with patch(_UPLOAD_FACTORY, return_value=s3_factory, autospec=True):
                    result = await uploader.upload_files(attachments)

                    assert len(result) == 1
                    assert result[0] == _S3_OBJECT_URL


class TestUploadManagerQuotaHandling:
    """Tests for upload quota exhaustion and rate limit handling."""

    @pytest.fixture
    def uploader(self):
        """Create an AttachmentUploader instance."""
        return AttachmentUploader(token="test-token")

    @pytest.mark.asyncio
    async def test_rate_limited_response_raises_quota_error(self, uploader):
        """Test that rate_limited: true produces a clear quota exhaustion message."""
        attachments = [_make_attachment(body=b"content")]

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
        session = FakeHttpTransport(
            FakeHttpResponse(ok=True, status_code=200, json_data=api_response)
        )

        with pytest.raises(RuntimeError, match="File upload quota exhausted"):
            await uploader._request_upload_urls(attachments, session)

    @pytest.mark.asyncio
    async def test_rate_limited_error_mentions_account_settings(self, uploader):
        """Test that quota error message directs user to account settings."""
        attachments = [_make_attachment(body=b"content")]

        api_response = {
            "results": {"uuid-1": {"s3_object_url": None, "fields": None, "rate_limited": True}}
        }
        session = FakeHttpTransport(
            FakeHttpResponse(ok=True, status_code=200, json_data=api_response)
        )

        with pytest.raises(RuntimeError, match=r"perplexity\.ai/settings/account"):
            await uploader._request_upload_urls(attachments, session)

    @pytest.mark.asyncio
    async def test_api_error_in_response_body(self, uploader):
        """Test that API error field is included in error message."""
        attachments = [_make_attachment(body=b"content")]

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
        session = FakeHttpTransport(
            FakeHttpResponse(ok=True, status_code=200, json_data=api_response)
        )

        with pytest.raises(RuntimeError, match="File type not supported"):
            await uploader._request_upload_urls(attachments, session)

    @pytest.mark.asyncio
    async def test_null_fields_no_rate_limit_no_error(self, uploader):
        """Test generic error when fields null with no rate_limited or error."""
        attachments = [_make_attachment(body=b"content")]

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
        session = FakeHttpTransport(
            FakeHttpResponse(ok=True, status_code=200, json_data=api_response)
        )

        with pytest.raises(RuntimeError, match="authentication or account issue"):
            await uploader._request_upload_urls(attachments, session)

    @pytest.mark.asyncio
    async def test_valid_response_passes_through(self, uploader):
        """Test that a valid presigned URL response passes validation."""
        attachments = [_make_attachment(body=b"content")]

        api_response = {
            "results": {
                "uuid-1": {
                    "s3_object_url": _S3_OBJECT_URL,
                    "fields": {
                        "key": "uploads/test.txt",
                        "policy": "base64policy",
                        "x-amz-signature": "sig",
                    },
                    "rate_limited": False,
                }
            }
        }
        session = FakeHttpTransport(
            FakeHttpResponse(ok=True, status_code=200, json_data=api_response)
        )

        response_json, _ = await uploader._request_upload_urls(attachments, session)

        assert "uuid-1" in response_json["results"]
        assert response_json["results"]["uuid-1"]["fields"] is not None

    @pytest.mark.asyncio
    async def test_request_upload_urls_rejects_non_dict_response(self, uploader):
        """Test malformed upload URL responses raise UpstreamSchemaError."""
        attachments = [_make_attachment(body=b"content")]

        session = FakeHttpTransport(FakeHttpResponse(ok=True, json_data=[]))

        with pytest.raises(UpstreamSchemaError, match="Malformed upload URL response"):
            await uploader._request_upload_urls(attachments, session)

    @pytest.mark.asyncio
    async def test_request_upload_urls_rejects_non_dict_results(self, uploader):
        """Test malformed upload results payload raises UpstreamSchemaError."""
        attachments = [_make_attachment(body=b"content")]

        session = FakeHttpTransport(FakeHttpResponse(ok=True, json_data={"results": []}))

        with pytest.raises(UpstreamSchemaError, match="Malformed upload results payload"):
            await uploader._request_upload_urls(attachments, session)


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
        attachments = [_make_attachment(body=b"content")]

        api_response = {
            "results": {
                "uuid-1": {
                    "s3_object_url": "https://s3.example.com/test.txt",
                    "fields": {"key": "test"},
                    "rate_limited": False,
                }
            }
        }
        session = FakeHttpTransport(
            FakeHttpResponse(ok=True, status_code=200, json_data=api_response)
        )

        await uploader._request_upload_urls(attachments, session)

        # Verify cookies were passed in the request
        assert dict(session.last_post.kwargs["cookies"]) == cookies

    @pytest.mark.asyncio
    async def test_csrf_token_in_headers(self):
        """Test that X-CSRFToken header is set from cookies."""
        cookies = {"csrftoken": "test-csrf-value"}
        uploader = AttachmentUploader(token="test-token", cookies=cookies)
        attachments = [_make_attachment(body=b"content")]

        api_response = {
            "results": {
                "uuid-1": {
                    "s3_object_url": "https://s3.example.com/test.txt",
                    "fields": {"key": "test"},
                    "rate_limited": False,
                }
            }
        }
        session = FakeHttpTransport(
            FakeHttpResponse(ok=True, status_code=200, json_data=api_response)
        )

        await uploader._request_upload_urls(attachments, session)

        headers = session.last_post.kwargs["headers"]
        assert headers["X-CSRFToken"] == "test-csrf-value"

    @pytest.mark.asyncio
    async def test_origin_and_referer_headers_sent(self):
        """Test that Origin and Referer headers are included in requests."""
        uploader = AttachmentUploader(token="test-token")
        attachments = [_make_attachment(body=b"content")]

        api_response = {
            "results": {
                "uuid-1": {
                    "s3_object_url": "https://s3.example.com/test.txt",
                    "fields": {"key": "test"},
                    "rate_limited": False,
                }
            }
        }
        session = FakeHttpTransport(
            FakeHttpResponse(ok=True, status_code=200, json_data=api_response)
        )

        await uploader._request_upload_urls(attachments, session)

        headers = session.last_post.kwargs["headers"]
        assert headers["Origin"] == "https://www.perplexity.ai"
        assert headers["Referer"] == "https://www.perplexity.ai/"

    @pytest.mark.asyncio
    async def test_no_cookies_sends_empty_dict(self):
        """Test that no cookies results in empty dict (not None)."""
        uploader = AttachmentUploader(token="test-token")
        attachments = [_make_attachment(body=b"content")]

        api_response = {
            "results": {
                "uuid-1": {
                    "s3_object_url": "https://s3.example.com/test.txt",
                    "fields": {"key": "test"},
                    "rate_limited": False,
                }
            }
        }
        session = FakeHttpTransport(
            FakeHttpResponse(ok=True, status_code=200, json_data=api_response)
        )

        await uploader._request_upload_urls(attachments, session)

        assert session.last_post.kwargs["cookies"] == {}


class TestUploadManagerLogging:
    """Tests for logging and error messages in upload manager."""

    @pytest.fixture
    def uploader(self):
        """Create an AttachmentUploader instance."""
        return AttachmentUploader(token="test-token")

    @pytest.mark.asyncio
    async def test_auth_error_logging_message(self, uploader, caplog):
        """Test that helpful error message is logged on auth failure."""
        attachments = [_make_attachment(body=b"content")]

        response = FakeHttpResponse(
            ok=False,
            status_code=401,
            url="https://api.perplexity.ai/rest/uploads/batch_create_upload_urls",
            headers={},
            content=b'{"error": "Unauthorized"}',
            text='{"error": "Unauthorized"}',
        )
        session = FakeHttpTransport(response=response)

        with caplog.at_level(logging.ERROR):
            with pytest.raises(PerplexityHTTPStatusError):
                await uploader._request_upload_urls(attachments, session)

            error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
            assert any(
                "invalid or expired token" in record.message.lower() for record in error_logs
            )
            assert any("pxcli auth login" in record.message for record in error_logs)

    @pytest.mark.asyncio
    async def test_unexpected_fields_type_warning_logged(self, uploader, caplog):
        """Test that a warning is logged when fields has unexpected type."""
        test_attachment = _make_attachment(body=b"Test file content")

        upload_data = {
            "fields": ["unexpected", "list"],
            "s3_object_url": _S3_OBJECT_URL,
        }

        with _patch_s3_upload(FakeHttpResponse(status_code=204)):
            with caplog.at_level(logging.WARNING):
                await uploader._upload_to_s3(test_attachment, upload_data)

            warning_logs = [record for record in caplog.records if record.levelname == "WARNING"]
            assert any("Unexpected fields type" in record.message for record in warning_logs)
