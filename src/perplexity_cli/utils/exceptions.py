"""Custom exception types for Perplexity CLI.

These replace httpx exception types in the query path, removing the need
to import httpx at module level. The data objects (SimpleRequest,
SimpleResponse) carry the same fields that downstream error handlers
expect from httpx.Request and httpx.Response.
"""


class SimpleRequest:
    """Minimal request data object.

    Carries the HTTP method and URL, matching the interface expected by
    error handlers that previously used ``httpx.Request``.

    Attributes:
        method: HTTP method (e.g. ``"POST"``).
        url: Request URL.
    """

    def __init__(self, method: str = "", url: str = "") -> None:
        self.method = method
        self.url = url


class SimpleResponse:
    """Minimal response data object.

    Carries status code, headers, body text, and the originating request,
    matching the interface expected by error handlers that previously used
    ``httpx.Response``.

    Attributes:
        status_code: HTTP status code.
        headers: Response headers dictionary.
        text: Response body as a string.
        request: The originating SimpleRequest.
    """

    def __init__(
        self,
        status_code: int = 0,
        headers: dict[str, str] | None = None,
        text: str = "",
        request: SimpleRequest | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers if headers is not None else {}
        self.text = text
        self.request = request if request is not None else SimpleRequest()


class PerplexityHTTPStatusError(Exception):
    """HTTP status error from the Perplexity API.

    Replaces ``httpx.HTTPStatusError`` in the query path. Carries
    ``.request`` and ``.response`` attributes so that downstream error
    handlers can inspect the status code, headers, and body text.

    Attributes:
        request: The SimpleRequest that triggered the error.
        response: The SimpleResponse containing the error details.
    """

    def __init__(
        self,
        message: str,
        request: SimpleRequest | None = None,
        response: SimpleResponse | None = None,
    ) -> None:
        super().__init__(message)
        self.request = request if request is not None else SimpleRequest()
        self.response = response if response is not None else SimpleResponse()


class PerplexityRequestError(Exception):
    """Network or connection error when contacting the Perplexity API.

    Replaces ``httpx.RequestError`` in the query path. Carries only a
    message string describing the network failure.
    """
