"""Cookie helpers for curl_cffi request clients."""

from collections.abc import Mapping

from curl_cffi.requests import Cookies


def to_curl_cffi_cookies(cookies: Mapping[str, str] | None) -> Cookies | dict[str, str]:
    """Build a curl_cffi cookie jar without prefix-normalisation warnings.

    Browser cookies are stored as a plain ``{name: value}`` mapping. Passing that
    mapping directly to curl_cffi makes it construct cookies with default
    attributes, then repair ``__Secure-`` and ``__Host-`` cookies with warnings.
    Set those attributes correctly up front instead.
    """
    if not cookies:
        return {}

    jar = Cookies()
    for name, value in cookies.items():
        secure = name.startswith("__Secure-") or name.startswith("__Host-")
        jar.set(name, value, secure=secure)
    return jar
