"""Orchestration tests for the attachment upload pipeline.

These tests drive :meth:`AttachmentUploader.upload_files` at the transport
boundary: the presigned-URL request (``_request_upload_urls``) and the S3
multipart upload (``_upload_to_s3``) are replaced with fakes, so no real
network traffic is possible.  An autouse guard additionally blocks any
non-loopback socket connection that might escape the mocks.

The real pipeline uses ``curl_cffi.requests.AsyncSession`` for the
presigned-URL step, which links libcurl directly and bypasses Python's
socket module, so a socket-level loopback server cannot intercept it; the
transport mocks below are therefore the correct hermetic seam.
"""

from __future__ import annotations

import base64
import socket
from typing import Any

import pytest

from perplexity_cli.attachments.upload_manager import AttachmentUploader
from perplexity_cli.utils.attachment_models import FileAttachment
from perplexity_cli.utils.exceptions import (
    AttachmentUploadError,
    PerplexityHTTPStatusError,
    SimpleResponse,
)
from tests.helpers.fake_transport import FakeHttpTransport

_LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost", "0.0.0.0"})
_RealCreateConnection = socket.create_connection


def _guarded_create_connection(
    address: Any,
    timeout: float = socket._GLOBAL_DEFAULT_TIMEOUT,
    source_address: tuple[str, int] | None = None,
) -> Any:
    """Reject non-loopback connections unconditionally."""
    if isinstance(address, tuple) and len(address) >= 2:
        host = str(address[0])
    else:
        host = str(address)

    if host not in _LOOPBACK_HOSTS and not host.startswith("127."):
        msg = f"Hermetic guard: external connection to {host!r} blocked"
        raise OSError(msg)

    return _RealCreateConnection(address, timeout, source_address)


def _make_attachment(
    *, filename: str = "test.txt", body: bytes = b"Test file content"
) -> FileAttachment:
    """Build a real FileAttachment from raw bytes."""
    return FileAttachment(
        filename=filename,
        content_type="text/plain",
        data=base64.b64encode(body).decode(),
    )


@pytest.fixture(autouse=True)
def _block_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block all non-loopback socket connections for hermetic upload tests."""
    monkeypatch.setattr(socket, "create_connection", _guarded_create_connection)


@pytest.fixture
def uploader(monkeypatch: pytest.MonkeyPatch) -> AttachmentUploader:
    """Create an uploader whose network session is a fake transport."""
    uploader = AttachmentUploader(token="test-token")
    monkeypatch.setattr(uploader, "_create_async_session", lambda timeout=None: FakeHttpTransport())
    return uploader


@pytest.fixture
def mock_presigned(monkeypatch: pytest.MonkeyPatch) -> list[list[FileAttachment]]:
    """Replace the presigned-URL request with a fake returning S3 data.

    Records every call so tests can assert on the attachments that were
    passed through, then returns data in the real response shape.
    """
    recorded: list[list[FileAttachment]] = []

    async def fake_request(
        self: AttachmentUploader,
        attachments: list[FileAttachment],
        session: FakeHttpTransport,
    ) -> tuple[dict[str, object], dict[str, FileAttachment]]:
        """Return per-attachment presigned data in the real response shape."""
        recorded.append(attachments)
        results: dict[str, dict[str, object]] = {}
        uuid_to_attachment: dict[str, FileAttachment] = {}
        for index, attachment in enumerate(attachments):
            file_uuid = f"uuid-{index}"
            uuid_to_attachment[file_uuid] = attachment
            results[file_uuid] = {
                "s3_object_url": f"https://s3.example.com/upload/{index}",
                "fields": {"key": f"uploads/{attachment.filename}"},
                "rate_limited": False,
            }
        return {"results": results}, uuid_to_attachment

    monkeypatch.setattr(AttachmentUploader, "_request_upload_urls", fake_request)
    return recorded


@pytest.fixture
def mock_s3_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[FileAttachment, dict[str, object]]]:
    """Replace the S3 multipart upload with a fake returning the presigned URL.

    Records every call so tests can assert the presigned data was threaded
    through to the S3 step without any network traffic.
    """
    recorded: list[tuple[FileAttachment, dict[str, object]]] = []

    async def fake_s3_upload(
        self: AttachmentUploader,
        attachment: FileAttachment,
        upload_data: dict[str, object],
        _session: object | None = None,
    ) -> str:
        """Return the presigned S3 object URL without making a network call."""
        recorded.append((attachment, upload_data))
        return str(upload_data["s3_object_url"])

    monkeypatch.setattr(AttachmentUploader, "_upload_to_s3", fake_s3_upload)
    return recorded


class TestUploadSuccess:
    """Verify the happy-path orchestration of upload_files()."""

    @pytest.mark.asyncio
    async def test_upload_success(
        self,
        uploader: AttachmentUploader,
        mock_presigned: list[list[FileAttachment]],
        mock_s3_upload: list[tuple[FileAttachment, dict[str, object]]],
    ) -> None:
        """Presigned URLs are returned for every uploaded file."""
        attachments = [
            _make_attachment(),
            _make_attachment(filename="notes.md", body=b"hello world"),
        ]

        urls = await uploader.upload_files(attachments)

        assert urls == ["https://s3.example.com/upload/0", "https://s3.example.com/upload/1"]
        assert mock_presigned == [attachments]
        assert len(mock_s3_upload) == 2
        assert mock_s3_upload[0][1]["s3_object_url"] == "https://s3.example.com/upload/0"


class TestPresignedErrors:
    """Verify upload_files() propagates presigned-URL failures."""

    @pytest.mark.asyncio
    async def test_presigned_http_error(
        self, uploader: AttachmentUploader, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 500 from the presigned step surfaces as PerplexityHTTPStatusError."""
        response = SimpleResponse(status_code=500)

        async def fake_request(
            self: AttachmentUploader,
            attachments: list[FileAttachment],
            session: object,
        ) -> object:
            """Always raise the HTTP status error."""
            msg = "presigned URL request failed"
            raise PerplexityHTTPStatusError(msg, response=response)

        monkeypatch.setattr(AttachmentUploader, "_request_upload_urls", fake_request)

        with pytest.raises(
            PerplexityHTTPStatusError, match="presigned URL request failed"
        ) as exc_info:
            await uploader.upload_files([_make_attachment()])

        assert exc_info.value.response.status_code == 500

    @pytest.mark.asyncio
    async def test_presigned_rate_limit(
        self, uploader: AttachmentUploader, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 429 is not retried by upload_files and propagates with its status."""
        calls: list[int] = []
        response = SimpleResponse(status_code=429)

        async def fake_request(
            self: AttachmentUploader,
            attachments: list[FileAttachment],
            session: object,
        ) -> object:
            """Always raise a 429 rate-limit status error."""
            calls.append(1)
            msg = "rate limited"
            raise PerplexityHTTPStatusError(msg, response=response)

        monkeypatch.setattr(AttachmentUploader, "_request_upload_urls", fake_request)

        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            await uploader.upload_files([_make_attachment()])

        assert exc_info.value.response.status_code == 429
        assert len(calls) == 1


class TestS3UploadErrors:
    """Verify upload_files() propagates S3 upload failures."""

    @pytest.mark.asyncio
    async def test_s3_upload_failure(
        self,
        uploader: AttachmentUploader,
        mock_presigned: list[list[FileAttachment]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A failing S3 upload surfaces as AttachmentUploadError."""

        async def fake_s3_upload(
            self: AttachmentUploader,
            attachment: FileAttachment,
            upload_data: dict[str, object],
            _session: object | None = None,
        ) -> str:
            """Always raise the S3 upload error."""
            msg = f"Failed to upload {attachment.filename} to S3: boom"
            raise AttachmentUploadError(msg)

        monkeypatch.setattr(AttachmentUploader, "_upload_to_s3", fake_s3_upload)

        with pytest.raises(AttachmentUploadError, match=r"Failed to upload test\.txt to S3"):
            await uploader.upload_files([_make_attachment()])


class TestNetworkGuard:
    """Verify the autouse guard blocks external connections."""

    def test_external_connection_blocked(self) -> None:
        """Attempting a non-loopback connection raises OSError."""
        with pytest.raises(OSError, match="Hermetic guard"):
            _guarded_create_connection(("93.184.216.34", 80))
