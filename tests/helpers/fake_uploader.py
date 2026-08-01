"""Fake upload endpoints for hermetic upload-boundary tests.

Two boundaries are covered:

* **S3 HTTP boundary** — replaces ``httpx.AsyncClient`` so tests can verify
  S3 upload behaviour without patching the ``httpx.AsyncClient`` constructor
  or wiring deeply-nested ``__aenter__`` / ``__aexit__`` mocks
  (:class:`FakeS3UploadClient` and :class:`FakeS3UploadClientFactory`).
* **Uploader boundary** — a typed drop-in for
  :class:`~perplexity_cli.attachments.AttachmentUploader` at the CLI/query
  component boundary (:class:`FakeAttachmentUploader`), so component tests
  never construct real S3 sessions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tests.helpers.fake_transport import FakeHttpResponse, RecordedRequest

if TYPE_CHECKING:
    from perplexity_cli.utils.attachment_models import FileAttachment


class FakeS3UploadClient:
    """Async client shaped like ``httpx.AsyncClient`` for S3 uploads.

    Implements the async context-manager protocol and an async ``post``
    method, matching the subset of ``httpx.AsyncClient`` used by
    :meth:`AttachmentUploader._execute_s3_upload`.

    Attributes:
        posts: Every recorded ``post`` call issued through this client.
    """

    def __init__(self, response: FakeHttpResponse) -> None:
        """Initialise the client with the response to return.

        Args:
            response: The response returned for every ``post`` call.
        """
        self._response: FakeHttpResponse = response
        self.posts: list[RecordedRequest] = []

    @property
    def last_post(self) -> RecordedRequest:
        """Return the most recently recorded S3 upload request.

        Raises:
            IndexError: If no request has been issued yet.
        """
        return self.posts[-1]

    async def __aenter__(self) -> FakeS3UploadClient:
        """Enter the async context, returning self as the client."""
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Exit the async context without suppressing exceptions."""
        return

    async def post(self, url: str, **kwargs: Any) -> FakeHttpResponse:
        """Record the S3 upload request and return the configured response."""
        self.posts.append(RecordedRequest(method="POST", url=url, kwargs=kwargs))
        return self._response


class FakeS3UploadClientFactory:
    """Callable factory producing :class:`FakeS3UploadClient` instances.

    Drop-in for ``httpx.AsyncClient`` (or the module-level
    ``_get_httpx_async_client_factory`` seam).  Calling the factory records
    each created client so tests can assert on the upload request.

    Example:
        >>> factory = FakeS3UploadClientFactory(FakeHttpResponse(status_code=204))
        >>> client = factory(timeout=30)
        >>> async with client as c:
        ...     await c.post("https://bucket/upload", files={})

    Attributes:
        created: Every client produced by this factory, in creation order.
    """

    def __init__(self, response: FakeHttpResponse) -> None:
        """Initialise the factory with the shared S3 upload response.

        Args:
            response: The response every produced client will return.
        """
        self._response: FakeHttpResponse = response
        self.created: list[FakeS3UploadClient] = []

    @property
    def last_client(self) -> FakeS3UploadClient:
        """Return the most recently produced client.

        Raises:
            IndexError: If no client has been produced yet.
        """
        return self.created[-1]

    def __call__(self, *args: Any, **kwargs: Any) -> FakeS3UploadClient:
        """Produce a new :class:`FakeS3UploadClient` bound to the response."""
        client = FakeS3UploadClient(self._response)
        self.created.append(client)
        return client


class FakeAttachmentUploader:
    """Typed uploader fake for the CLI/query component boundary.

    Drop-in for :class:`~perplexity_cli.attachments.AttachmentUploader` used
    by the ``query`` command path.  ``upload_files`` records the attachments
    it received and returns a preconfigured list of S3 URL strings, so tests
    can assert the exact attachment order and body without real S3 traffic.

    Example:
        >>> fake = FakeAttachmentUploader(["https://s3.example.com/a.txt"])
        >>> urls = await fake.upload_files(attachments)
        >>> assert urls == ["https://s3.example.com/a.txt"]

    Attributes:
        results: S3 URLs returned by :meth:`upload_files`.
        received: Every attachment list passed to :meth:`upload_files`.
        upload_calls: Number of :meth:`upload_files` invocations.
    """

    def __init__(self, results: list[str] | None = None) -> None:
        """Initialise the fake with the S3 URLs to return.

        Args:
            results: S3 URL strings returned on every upload.  Defaults to an
                empty list.
        """
        self.results: list[str] = list(results or [])
        self.received: list[list[FileAttachment]] = []
        self.upload_calls: int = 0

    def set_results(self, results: list[str]) -> None:
        """Override the S3 URLs returned by subsequent uploads.

        Args:
            results: S3 URL strings to return.
        """
        self.results = list(results)

    async def upload_files(self, attachments: list[FileAttachment]) -> list[str]:
        """Record the attachment list and return the configured S3 URLs.

        Args:
            attachments: File attachment objects to upload.

        Returns:
            The configured S3 URL strings.
        """
        self.received.append(list(attachments))
        self.upload_calls += 1
        return list(self.results)
