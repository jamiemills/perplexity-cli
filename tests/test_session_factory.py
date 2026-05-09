"""Tests for perplexity_cli.utils.session_factory."""

from curl_cffi.requests import AsyncSession, Session

from perplexity_cli.utils.session_factory import (
    IMPERSONATE_PROFILE,
    create_async_session,
    create_sync_session,
    is_curl_cffi_available,
)


class TestSessionFactory:
    """Tests for session factory functions."""

    def test_is_curl_cffi_available(self):
        assert is_curl_cffi_available() is True

    def test_impersonate_profile_is_chrome(self):
        assert IMPERSONATE_PROFILE == "chrome"

    def test_create_sync_session_returns_session(self):
        session = create_sync_session()
        assert isinstance(session, Session)

    def test_create_async_session_returns_async_session(self):
        session = create_async_session()
        assert isinstance(session, AsyncSession)

    def test_sync_session_with_custom_timeout(self):
        session = create_sync_session(timeout=120)
        assert isinstance(session, Session)

    def test_async_session_with_custom_timeout(self):
        session = create_async_session(timeout=120)
        assert isinstance(session, AsyncSession)
