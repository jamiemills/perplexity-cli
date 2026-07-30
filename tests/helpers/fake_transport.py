"""Fake HTTP transport for hermetic upload-boundary tests.

These fakes replace ``curl_cffi.AsyncSession`` and the response objects it
returns at the *outer* boundary, so tests no longer need to patch internal
constructors or build deeply-nested ``MagicMock`` chains.

The fakes implement only the small subset of the response/session interface
that :class:`AttachmentUploader` actually depends on:

* responses expose ``ok``, ``status_code``, ``url``, ``headers``, ``text``,
  ``content`` and a ``json()`` method;
* transports are async context managers with a single async ``post`` method
  that records every call for later assertion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RecordedRequest:
    """Snapshot of a single request issued through a fake transport."""

    method: str
    url: str
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FakeHttpResponse:
    """Minimal response shaped like a curl_cffi/httpx ``Response``.

    Attributes:
        ok: Convenience success flag mirroring ``Response.ok``.
        status_code: HTTP status code.
        text: Decoded body text (``None`` simulates a falsy body so callers
            exercise the ``content`` fallback path).
        content: Raw body bytes.
        url: Request URL as recorded on the response.
        headers: Response headers mapping.
        json_data: Payload returned by :meth:`json`; ``None`` raises so
            accidental ``json()`` calls surface loudly.
    """

    ok: bool = True
    status_code: int = 200
    text: str | None = ""
    content: bytes = b""
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    json_data: Any = None

    def json(self) -> Any:
        """Return the configured JSON payload.

        Raises:
            ValueError: If no payload was configured, mirroring a real
                response that has no JSON body.
        """
        if self.json_data is None:
            msg = "FakeHttpResponse has no JSON payload configured"
            raise ValueError(msg)
        return self.json_data


class FakeHttpTransport:
    """Async session-shaped fake that returns a configured response.

    Acts as a drop-in for the subset of ``curl_cffi.AsyncSession`` used by
    :meth:`AttachmentUploader._request_upload_urls`: it is an async context
    manager exposing an async ``post`` method.  Every call is recorded on
    :attr:`posts` for later inspection.

    Example:
        >>> transport = FakeHttpTransport(FakeHttpResponse(ok=True, json_data={"results": {}}))
        >>> async with transport as session:
        ...     await session.post("https://example/api", json={})
        >>> transport.last_post.kwargs["json"]
        {}
    """

    def __init__(self, response: FakeHttpResponse | None = None) -> None:
        """Initialise the transport with the response to return.

        Args:
            response: The response returned for every ``post`` call.  Defaults
                to a generic ``200 OK`` response.
        """
        self._response: FakeHttpResponse = response if response is not None else FakeHttpResponse()
        self.posts: list[RecordedRequest] = []

    @property
    def last_post(self) -> RecordedRequest:
        """Return the most recently recorded request.

        Raises:
            IndexError: If no request has been issued yet.
        """
        return self.posts[-1]

    def set_response(self, response: FakeHttpResponse) -> None:
        """Swap the response returned by subsequent ``post`` calls."""
        self._response = response

    async def __aenter__(self) -> FakeHttpTransport:
        """Enter the async context, returning self as the session."""
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Exit the async context without suppressing exceptions."""
        return

    async def post(self, url: str, **kwargs: Any) -> FakeHttpResponse:
        """Record the call and return the configured response."""
        self.posts.append(RecordedRequest(method="POST", url=url, kwargs=kwargs))
        return self._response
