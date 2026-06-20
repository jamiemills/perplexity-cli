"""Shared HTTP header construction for Perplexity API requests.

Both the SSE query client and the attachment uploader need the same set
of headers (Authorization, Content-Type, Origin, Referer, X-CSRFToken).
This module provides a single function so changes to the header contract
only need to be made in one place.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HeaderOptions:
    """Optional keyword arguments for :func:`build_perplexity_headers`."""

    content_type: str = "application/json"
    accept: str | None = None
    base_url: str | None = None


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


def _resolve_options(options: HeaderOptions | None) -> HeaderOptions:
    """Return the given options or the default."""
    return options if options is not None else HeaderOptions()


def build_perplexity_headers(
    token: str | None,
    cookies: dict[str, str] | None = None,
    *,
    options: HeaderOptions | None = None,
) -> dict[str, str]:
    """Build standard HTTP headers for Perplexity API requests.

    curl_cffi sets ``User-Agent`` automatically based on the impersonated
    browser, so it is not included here.  Cookies are passed separately
    via the ``cookies`` parameter on requests rather than as a header.

    Args:
        token: Optional JWT authentication token.
        cookies: Optional browser cookies; used to extract the CSRF token.
        options: Optional header configuration as :class:`HeaderOptions`.

    Returns:
        Dictionary of HTTP headers.
    """
    opts = _resolve_options(options)
    resolved_url = _resolve_base_url(opts.base_url)

    headers: dict[str, str] = {
        "Content-Type": opts.content_type,
        "Origin": resolved_url,
        "Referer": resolved_url.rstrip("/") + "/",
    }

    if opts.accept:
        headers["Accept"] = opts.accept

    if token:
        headers["Authorization"] = f"Bearer {token}"

    if cookies and "csrftoken" in cookies:
        headers["X-CSRFToken"] = cookies["csrftoken"]

    return headers
