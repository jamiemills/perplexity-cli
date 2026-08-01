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

The orchestration contract under test:
* at most ``MAX_CONCURRENT_UPLOADS`` S3 uploads run concurrently;
* one HTTP client serves an entire batch;
* results retain input order;
* the first failure (or caller cancellation) cancels and drains siblings;
* no partial success list is returned;
* the requested/result UUID sets must be an exact bijection before uploads.
"""

from __future__ import annotations

import asyncio
import base64
import socket
from typing import Any

import pytest

from perplexity_cli.attachments.upload_manager import (
    MAX_CONCURRENT_UPLOADS,
    AttachmentUploader,
)
from perplexity_cli.utils.attachment_models import FileAttachment
from perplexity_cli.utils.exceptions import (
    AttachmentUploadError,
    PerplexityHTTPStatusError,
    SimpleResponse,
    UpstreamSchemaError,
)
from tests.helpers.fake_transport import FakeHttpResponse, FakeHttpTransport
from tests.helpers.fake_uploader import FakeS3UploadClientFactory

_LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost", "0.0.0.0"})
_RealCreateConnection = socket.create_connection
_FACTORY_TARGET = "perplexity_cli.attachments.upload_manager._get_httpx_async_client_factory"


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
        client: object | None = None,
    ) -> str:
        """Return the presigned S3 object URL without making a network call."""
        recorded.append((attachment, upload_data))
        return str(upload_data["s3_object_url"])

    monkeypatch.setattr(AttachmentUploader, "_upload_to_s3", fake_s3_upload)
    return recorded


@pytest.fixture
def mock_s3_factory(monkeypatch: pytest.MonkeyPatch) -> FakeS3UploadClientFactory:
    """Route the shared S3 client through a fake factory recording clients."""
    factory = FakeS3UploadClientFactory(FakeHttpResponse(status_code=204))
    monkeypatch.setattr(_FACTORY_TARGET, lambda: factory)
    return factory


class TestUploadSuccess:
    """Verify the happy-path orchestration of upload_files()."""

    @pytest.mark.asyncio
    async def test_upload_success(
        self,
        uploader: AttachmentUploader,
        mock_presigned: list[list[FileAttachment]],
        mock_s3_upload: list[tuple[FileAttachment, dict[str, object]]],
        mock_s3_factory: FakeS3UploadClientFactory,
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

    @pytest.mark.asyncio
    async def test_empty_attachments_returns_empty_list(
        self, uploader: AttachmentUploader, mock_s3_factory: FakeS3UploadClientFactory
    ) -> None:
        """An empty attachment list short-circuits with no network work."""
        urls = await uploader.upload_files([])

        assert urls == []
        assert mock_s3_factory.created == []


class TestConcurrencyContract:
    """Verify bounded concurrency and one HTTP client per batch."""

    @pytest.mark.asyncio
    async def test_max_four_concurrent_uploads(
        self,
        uploader: AttachmentUploader,
        mock_presigned: list[list[FileAttachment]],
        mock_s3_factory: FakeS3UploadClientFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """At most MAX_CONCURRENT_UPLOADS S3 uploads run at once."""
        active = 0
        max_active = 0
        lock = asyncio.Lock()

        async def fake_s3_upload(
            self: AttachmentUploader,
            attachment: FileAttachment,
            upload_data: dict[str, object],
            client: object | None = None,
        ) -> str:
            """Track the maximum number of concurrently active uploads."""
            nonlocal active, max_active
            async with lock:
                active += 1
                max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            async with lock:
                active -= 1
            return str(upload_data["s3_object_url"])

        monkeypatch.setattr(AttachmentUploader, "_upload_to_s3", fake_s3_upload)

        attachments = [_make_attachment(filename=f"file-{index}.txt") for index in range(8)]
        urls = await uploader.upload_files(attachments)

        assert max_active == MAX_CONCURRENT_UPLOADS
        assert len(urls) == 8

    @pytest.mark.asyncio
    async def test_one_http_client_per_batch(
        self,
        uploader: AttachmentUploader,
        mock_presigned: list[list[FileAttachment]],
        mock_s3_factory: FakeS3UploadClientFactory,
    ) -> None:
        """A single HTTP client serves the whole batch of S3 uploads."""
        attachments = [
            _make_attachment(filename="a.txt"),
            _make_attachment(filename="b.txt"),
            _make_attachment(filename="c.txt"),
        ]

        urls = await uploader.upload_files(attachments)

        assert len(mock_s3_factory.created) == 1
        assert len(mock_s3_factory.last_client.posts) == 3
        assert urls == [
            "https://s3.example.com/upload/0",
            "https://s3.example.com/upload/1",
            "https://s3.example.com/upload/2",
        ]

    @pytest.mark.asyncio
    async def test_results_preserve_input_order_despite_out_of_order_completion(
        self,
        uploader: AttachmentUploader,
        mock_presigned: list[list[FileAttachment]],
        mock_s3_factory: FakeS3UploadClientFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Results come back in input order even when later files finish first."""

        async def fake_s3_upload(
            self: AttachmentUploader,
            attachment: FileAttachment,
            upload_data: dict[str, object],
            client: object | None = None,
        ) -> str:
            """Finish earlier-indexed files last."""
            index = int(attachment.filename.split("-")[1].split(".")[0])
            await asyncio.sleep((4 - index) * 0.01)
            return str(upload_data["s3_object_url"])

        monkeypatch.setattr(AttachmentUploader, "_upload_to_s3", fake_s3_upload)

        attachments = [_make_attachment(filename=f"file-{index}.txt") for index in range(4)]
        urls = await uploader.upload_files(attachments)

        assert urls == [
            "https://s3.example.com/upload/0",
            "https://s3.example.com/upload/1",
            "https://s3.example.com/upload/2",
            "https://s3.example.com/upload/3",
        ]


class TestFailureCancellation:
    """Verify first-failure and caller-cancellation drain behaviour."""

    @pytest.mark.asyncio
    async def test_first_failure_cancels_and_drains_siblings(
        self,
        uploader: AttachmentUploader,
        mock_presigned: list[list[FileAttachment]],
        mock_s3_factory: FakeS3UploadClientFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A first failure cancels unfinished siblings and never returns a partial list."""
        events: list[str] = []
        started = asyncio.Event()
        sibling_count = 0

        async def fake_s3_upload(
            self: AttachmentUploader,
            attachment: FileAttachment,
            upload_data: dict[str, object],
            client: object | None = None,
        ) -> str:
            """Fail one file once all siblings have begun uploading."""
            nonlocal sibling_count
            if attachment.filename == "fail.txt":
                await started.wait()
                raise AttachmentUploadError("boom: fail.txt")
            events.append(f"started:{attachment.filename}")
            sibling_count += 1
            if sibling_count == 3:
                started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                events.append(f"cancelled:{attachment.filename}")
                raise
            events.append(f"done:{attachment.filename}")
            return str(upload_data["s3_object_url"])

        monkeypatch.setattr(AttachmentUploader, "_upload_to_s3", fake_s3_upload)

        attachments = [
            _make_attachment(filename="fail.txt"),
            _make_attachment(filename="b.txt"),
            _make_attachment(filename="c.txt"),
            _make_attachment(filename="d.txt"),
        ]

        with pytest.raises(AttachmentUploadError, match=r"boom: fail\.txt"):
            await uploader.upload_files(attachments)

        assert set(events) == {
            "started:b.txt",
            "started:c.txt",
            "started:d.txt",
            "cancelled:b.txt",
            "cancelled:c.txt",
            "cancelled:d.txt",
        }

    @pytest.mark.asyncio
    async def test_caller_cancellation_cancels_and_drains_siblings(
        self,
        uploader: AttachmentUploader,
        mock_presigned: list[list[FileAttachment]],
        mock_s3_factory: FakeS3UploadClientFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cancelling upload_files cancels and drains every running sibling."""
        events: list[str] = []
        started = asyncio.Event()
        sibling_count = 0

        async def fake_s3_upload(
            self: AttachmentUploader,
            attachment: FileAttachment,
            upload_data: dict[str, object],
            client: object | None = None,
        ) -> str:
            """Record start, then block until cancelled."""
            nonlocal sibling_count
            events.append(f"started:{attachment.filename}")
            sibling_count += 1
            if sibling_count == 4:
                started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                events.append(f"cancelled:{attachment.filename}")
                raise
            events.append(f"done:{attachment.filename}")
            return str(upload_data["s3_object_url"])

        monkeypatch.setattr(AttachmentUploader, "_upload_to_s3", fake_s3_upload)

        attachments = [_make_attachment(filename=f"file-{index}.txt") for index in range(4)]
        task = asyncio.create_task(uploader.upload_files(attachments))
        await started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert {event for event in events if event.startswith("cancelled")} == {
            f"cancelled:file-{index}.txt" for index in range(4)
        }
        assert not any(event.startswith("done") for event in events)


class TestUuidBijection:
    """Verify the exact requested/result UUID bijection runs before uploads."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("remove_index", [0, 1])
    async def test_missing_result_uuid_fails_before_upload(
        self,
        uploader: AttachmentUploader,
        mock_s3_factory: FakeS3UploadClientFactory,
        monkeypatch: pytest.MonkeyPatch,
        remove_index: int,
    ) -> None:
        """A result set missing a requested UUID fails before any S3 upload."""
        uploads_started: list[str] = []

        async def fake_request(
            self: AttachmentUploader,
            attachments: list[FileAttachment],
            session: object,
        ) -> tuple[dict[str, object], dict[str, FileAttachment]]:
            """Return results for every requested UUID except *remove_index*."""
            uuid_to_attachment = {
                f"uuid-{index}": attachment for index, attachment in enumerate(attachments)
            }
            results = {
                file_uuid: {
                    "s3_object_url": f"https://s3.example.com/upload/{index}",
                    "fields": {"key": f"uploads/{attachment.filename}"},
                }
                for index, (file_uuid, attachment) in enumerate(uuid_to_attachment.items())
                if index != remove_index
            }
            return {"results": results}, uuid_to_attachment

        async def fake_s3_upload(
            self: AttachmentUploader,
            attachment: FileAttachment,
            upload_data: dict[str, object],
            client: object | None = None,
        ) -> str:
            """Record that an S3 upload actually began."""
            uploads_started.append(attachment.filename)
            return str(upload_data["s3_object_url"])

        monkeypatch.setattr(AttachmentUploader, "_request_upload_urls", fake_request)
        monkeypatch.setattr(AttachmentUploader, "_upload_to_s3", fake_s3_upload)

        attachments = [
            _make_attachment(filename="a.txt"),
            _make_attachment(filename="b.txt"),
        ]

        with pytest.raises(UpstreamSchemaError, match="does not match requested files"):
            await uploader.upload_files(attachments)

        assert uploads_started == []

    @pytest.mark.asyncio
    async def test_extra_result_uuid_fails_before_upload(
        self,
        uploader: AttachmentUploader,
        mock_s3_factory: FakeS3UploadClientFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A result set containing an unrequested UUID fails before any upload."""
        uploads_started: list[str] = []

        async def fake_request(
            self: AttachmentUploader,
            attachments: list[FileAttachment],
            session: object,
        ) -> tuple[dict[str, object], dict[str, FileAttachment]]:
            """Return an extra result UUID beyond the requested set."""
            uuid_to_attachment = {"uuid-0": attachments[0]}
            results = {
                "uuid-0": {
                    "s3_object_url": "https://s3.example.com/upload/0",
                    "fields": {"key": "uploads/a.txt"},
                },
                "ghost-uuid": {
                    "s3_object_url": "https://s3.example.com/upload/ghost",
                    "fields": {"key": "uploads/ghost.txt"},
                },
            }
            return {"results": results}, uuid_to_attachment

        async def fake_s3_upload(
            self: AttachmentUploader,
            attachment: FileAttachment,
            upload_data: dict[str, object],
            client: object | None = None,
        ) -> str:
            """Record that an S3 upload actually began."""
            uploads_started.append(attachment.filename)
            return str(upload_data["s3_object_url"])

        monkeypatch.setattr(AttachmentUploader, "_request_upload_urls", fake_request)
        monkeypatch.setattr(AttachmentUploader, "_upload_to_s3", fake_s3_upload)

        with pytest.raises(UpstreamSchemaError, match="does not match requested files"):
            await uploader.upload_files([_make_attachment()])

        assert uploads_started == []


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
            client: object | None = None,
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
