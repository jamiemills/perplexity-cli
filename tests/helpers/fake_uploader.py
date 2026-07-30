"""Fake S3 upload endpoint for hermetic upload-boundary tests.

Replaces ``httpx.AsyncClient`` at the *outer* boundary so tests can verify
S3 upload behaviour without patching the ``httpx.AsyncClient`` constructor
or wiring deeply-nested ``__aenter__`` / ``__aexit__`` mocks.

Two collaborators are provided:

* :class:`FakeS3UploadClient` - the async client itself (an async context
  manager with an async ``post`` method that records calls);
* :class:`FakeS3UploadClientFactory` - the callable factory that produces
  clients, dropped in for the module's ``_get_httpx_async_client_factory``
  seam.
"""

from __future__ import annotations

from typing import Any

from tests.helpers.fake_transport import FakeHttpResponse, RecordedRequest


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
