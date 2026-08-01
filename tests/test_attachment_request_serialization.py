"""Test the file attachment wire contract for query requests.

Query attachments are uploaded **S3 URL strings** (see
``src/perplexity_cli/api/models.py``), never embedded base64 file objects.
These tests verify the full contract chain: ``FileAttachment`` objects are
uploaded to S3 URL strings, which then flow through
``QueryInput.attachment_urls`` into the ``params.attachments`` field of the
outbound query request body.
"""

from __future__ import annotations

import base64
import json

import pytest

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import QueryInput
from perplexity_cli.attachments import upload_manager
from perplexity_cli.attachments.upload_manager import AttachmentUploader
from perplexity_cli.utils.attachment_models import FileAttachment
from tests.helpers.fake_transport import FakeHttpResponse, FakeHttpTransport
from tests.helpers.fake_uploader import FakeS3UploadClientFactory

_SSE_CLIENT_TARGET = "perplexity_cli.api.endpoints.SSEClient"


class FakeSSEClient:
    """Typed outer-boundary fake for ``SSEClient.stream_post``.

    Records every outbound request body and returns a configurable iterable
    of SSE message payloads, so endpoint tests never touch the network.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialise the fake with no captured requests yet."""
        self.stream_posts: list[tuple[str, dict[str, object]]] = []
        self.messages: list[dict[str, object]] = []

    def set_messages(self, messages: list[dict[str, object]]) -> None:
        """Configure the SSE message payloads yielded by ``stream_post``."""
        self.messages = list(messages)

    def stream_post(self, url: str, json_data: dict[str, object]) -> object:
        """Record the request and yield the configured SSE messages."""
        self.stream_posts.append((url, json_data))
        return iter(self.messages)

    def close(self) -> None:
        """No-op close to satisfy the real client interface."""


@pytest.fixture
def mock_sse_client(monkeypatch: pytest.MonkeyPatch) -> FakeSSEClient:
    """Patch the SSE client at the endpoint boundary with a typed fake."""
    fake_client = FakeSSEClient()
    fake_client.set_messages([])
    monkeypatch.setattr(_SSE_CLIENT_TARGET, lambda *args, **kwargs: fake_client)
    return fake_client


def _make_attachment(
    *, filename: str = "test.txt", body: bytes = b"Test file content"
) -> FileAttachment:
    """Build a real FileAttachment from raw bytes."""
    return FileAttachment(
        filename=filename,
        content_type="text/plain",
        data=base64.b64encode(body).decode(),
    )


def _submit_with_urls(fake_client: FakeSSEClient, s3_urls: list[str]) -> None:
    """Submit a query with *s3_urls* through the real endpoint layer."""
    api = PerplexityAPI(token="test-token")
    list(api.submit_query(QueryInput(query="Test", attachment_urls=s3_urls)))


@pytest.fixture
def uploader_with_fake_transport(monkeypatch: pytest.MonkeyPatch) -> AttachmentUploader:
    """An uploader whose presigned-URL session is a fake transport.

    ``_request_upload_urls`` is replaced with a fake that returns valid
    presigned data in the real response shape, so the upload flow is
    hermetic.
    """
    uploader = AttachmentUploader(token="test-token")
    monkeypatch.setattr(
        uploader,
        "_create_async_session",
        lambda timeout=None: FakeHttpTransport(),
    )

    async def fake_request(
        self: AttachmentUploader,
        attachments: list[FileAttachment],
        session: FakeHttpTransport,
    ) -> tuple[dict[str, object], dict[str, FileAttachment]]:
        """Return per-attachment presigned data in the real response shape."""
        uuid_to_attachment: dict[str, FileAttachment] = {}
        results: dict[str, dict[str, object]] = {}
        for index, attachment in enumerate(attachments):
            file_uuid = f"uuid-{index}"
            uuid_to_attachment[file_uuid] = attachment
            results[file_uuid] = {
                "s3_object_url": f"https://s3.example.com/upload/{index}.txt",
                "fields": {"key": f"uploads/{attachment.filename}"},
                "rate_limited": False,
            }
        return {"results": results}, uuid_to_attachment

    monkeypatch.setattr(AttachmentUploader, "_request_upload_urls", fake_request)
    return uploader


@pytest.fixture
def s3_client_factory(monkeypatch: pytest.MonkeyPatch) -> FakeS3UploadClientFactory:
    """Route S3 uploads through a fake client factory recording every post."""
    factory = FakeS3UploadClientFactory(FakeHttpResponse(status_code=204))
    monkeypatch.setattr(
        upload_manager,
        "_get_httpx_async_client_factory",
        lambda: factory,
    )
    return factory


class TestUploadFlowProducesUrlStrings:
    """FileAttachment -> upload flow -> S3 URL strings."""

    @pytest.mark.asyncio
    async def test_upload_files_returns_s3_url_strings(
        self,
        uploader_with_fake_transport: AttachmentUploader,
        s3_client_factory: FakeS3UploadClientFactory,
    ) -> None:
        """The upload flow returns plain S3 URL strings, never base64 objects."""
        attachments = [
            _make_attachment(filename="a.txt", body=b"content a"),
            _make_attachment(filename="b.txt", body=b"content b"),
        ]

        urls = await uploader_with_fake_transport.upload_files(attachments)

        assert urls == [
            "https://s3.example.com/upload/0.txt",
            "https://s3.example.com/upload/1.txt",
        ]
        assert all(isinstance(url, str) for url in urls)
        assert all(url.startswith("https://") for url in urls)

    @pytest.mark.asyncio
    async def test_uploaded_urls_are_json_serializable_strings(
        self,
        uploader_with_fake_transport: AttachmentUploader,
        s3_client_factory: FakeS3UploadClientFactory,
    ) -> None:
        """Uploaded URLs serialize as plain JSON strings."""
        urls = await uploader_with_fake_transport.upload_files([_make_attachment()])

        serialized = json.loads(json.dumps(urls))
        assert serialized == urls
        assert all(isinstance(url, str) for url in serialized)


class TestAttachmentUrlSerialization:
    """S3 URL strings -> QueryInput.attachment_urls -> request params."""

    def test_s3_urls_serialize_into_request_params(self, mock_sse_client) -> None:
        """S3 URL strings land in ``params.attachments`` of the request body."""
        s3_urls = [
            "https://ppl-ai-file-upload.s3.amazonaws.com/direct/a.txt",
            "https://ppl-ai-file-upload.s3.amazonaws.com/direct/b.md",
        ]

        _submit_with_urls(mock_sse_client, s3_urls)

        _url, json_data = mock_sse_client.stream_posts[-1]
        assert json_data["params"]["attachments"] == s3_urls

    def test_attachments_are_plain_strings_not_file_objects(self, mock_sse_client) -> None:
        """params.attachments entries are URL strings, not base64 objects."""
        s3_url = "https://ppl-ai-file-upload.s3.amazonaws.com/direct/only.txt"
        _submit_with_urls(mock_sse_client, [s3_url])

        _url, json_data = mock_sse_client.stream_posts[-1]
        attachments = json_data["params"]["attachments"]
        assert all(isinstance(item, str) for item in attachments)
        assert attachments == [s3_url]

    def test_request_body_with_attachments_is_json_serializable(self, mock_sse_client) -> None:
        """The full request body round-trips through JSON with URL attachments."""
        s3_url = "https://ppl-ai-file-upload.s3.amazonaws.com/direct/serial.txt"
        _submit_with_urls(mock_sse_client, [s3_url])

        _url, json_data = mock_sse_client.stream_posts[-1]
        round_tripped = json.loads(json.dumps(json_data))
        assert round_tripped["params"]["attachments"][0] == s3_url

    def test_file_attachment_data_is_never_embedded_in_request(self, mock_sse_client) -> None:
        """Raw base64 file data must not appear in the query request body."""
        _submit_with_urls(mock_sse_client, ["https://s3.example.com/upload/0.txt"])

        _url, json_data = mock_sse_client.stream_posts[-1]
        serialized = json.dumps(json_data)
        assert "base64" not in serialized
        assert "content_type" not in serialized
