"""Tests for curl_cffi cookie conversion helpers."""

import warnings

from curl_cffi.requests.cookies import CurlCffiWarning

from perplexity_cli.utils.cookies import to_curl_cffi_cookies


def test_empty_cookies_return_empty_dict():
    """Empty cookies should keep existing request-call behaviour."""
    assert to_curl_cffi_cookies(None) == {}
    assert to_curl_cffi_cookies({}) == {}


def test_prefixed_cookies_do_not_warn():
    """__Secure- and __Host- cookies should be pre-normalised for curl_cffi."""
    cookies = {
        "__Secure-next-auth.session-token": "secure-token",
        "__Host-session": "host-token",
        "csrftoken": "csrf-token",
    }

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        jar = to_curl_cffi_cookies(cookies)

    cookie_warnings = [
        warning for warning in caught if issubclass(warning.category, CurlCffiWarning)
    ]
    assert cookie_warnings == []
    assert dict(jar) == cookies


def test_secure_prefix_cookies_get_secure_attribute():
    """__Secure- and __Host- cookies are stored with secure=True."""
    jar = to_curl_cffi_cookies(
        {
            "__Secure-next-auth.session-token": "secure-sentinel",
            "__Host-session": "host-sentinel",
            "csrftoken": "plain-sentinel",
        }
    )
    by_name = {cookie.name: cookie for cookie in jar.jar}
    assert by_name["__Secure-next-auth.session-token"].secure is True
    assert by_name["__Host-session"].secure is True
    assert by_name["csrftoken"].secure is False
