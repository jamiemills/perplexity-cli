"""Shared HTTP header construction for Perplexity API requests.

Both the SSE query client and the attachment uploader need the same set
of headers (Authorization, Content-Type, Origin, Referer, X-CSRFToken).
This module provides a single function so changes to the header contract
only need to be made in one place.
"""

from __future__ import annotations


def _resolve_base_url(base_url: str | None) -> str:
    """Resolve the base URL, loading from configuration if not provided.

    Args:
        base_url: Explicit base URL, or None to load from configuration.

    Returns:
        The resolved base URL string.
    """
    if base_url is not None:
        return base_url
    from perplexity_cli.utils.config import get_perplexity_base_url

    return get_perplexity_base_url()


def build_perplexity_headers(
    token: str | None,
    cookies: dict[str, str] | None = None,
    content_type: str = "application/json",
    header_extras: tuple[str | None, str | None] = (None, None),
) -> dict[str, str]:
    """Build standard HTTP headers for Perplexity API requests.

    curl_cffi sets ``User-Agent`` automatically based on the impersonated
    browser, so it is not included here.  Cookies are passed separately
    via the ``cookies`` parameter on requests rather than as a header.

    Args:
        token: Optional JWT authentication token.
        cookies: Optional browser cookies; used to extract the CSRF token.
        content_type: Value for the ``Content-Type`` header.
        header_extras: A tuple of (accept, base_url) for optional headers.

    Returns:
        Dictionary of HTTP headers.
    """
    accept, base_url = header_extras
    resolved_url = _resolve_base_url(base_url)

    headers: dict[str, str] = {
        "Content-Type": content_type,
        "Origin": resolved_url,
        "Referer": resolved_url.rstrip("/") + "/",
    }

    if accept:
        headers["Accept"] = accept

    if token:
        headers["Authorization"] = f"Bearer {token}"

    if cookies and "csrftoken" in cookies:
        headers["X-CSRFToken"] = cookies["csrftoken"]

    return headers
