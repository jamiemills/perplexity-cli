"""Tests for HTTP header construction utilities."""

from perplexity_cli.utils.http_headers import build_perplexity_headers


class TestBuildPerplexityHeaders:
    """Tests for build_perplexity_headers function."""

    def test_basic_headers(self):
        """Test that basic headers include Content-Type, Origin and Referer."""
        headers = build_perplexity_headers(token=None, base_url="https://example.com")
        assert headers["Content-Type"] == "application/json"
        assert headers["Origin"] == "https://example.com"
        assert "Referer" in headers

    def test_authorization_with_token(self):
        """Test that providing a token adds an Authorization header."""
        headers = build_perplexity_headers(token="abc", base_url="https://example.com")
        assert headers["Authorization"] == "Bearer abc"

    def test_no_authorization_without_token(self):
        """Test that no Authorization header is present when token is None."""
        headers = build_perplexity_headers(token=None, base_url="https://example.com")
        assert "Authorization" not in headers

    def test_csrf_token_from_cookies(self):
        """Test that csrftoken cookie value is added as X-CSRFToken header."""
        headers = build_perplexity_headers(
            token=None, cookies={"csrftoken": "xyz"}, base_url="https://example.com"
        )
        assert headers["X-CSRFToken"] == "xyz"

    def test_no_csrf_without_cookies(self):
        """Test that no X-CSRFToken header is present when cookies is None."""
        headers = build_perplexity_headers(token=None, cookies=None, base_url="https://example.com")
        assert "X-CSRFToken" not in headers

    def test_custom_content_type(self):
        """Test that a custom content type is used."""
        headers = build_perplexity_headers(
            token=None, content_type="multipart/form-data", base_url="https://example.com"
        )
        assert headers["Content-Type"] == "multipart/form-data"

    def test_accept_header(self):
        """Test that the Accept header is set when provided."""
        headers = build_perplexity_headers(
            token=None, accept="text/event-stream", base_url="https://example.com"
        )
        assert headers["Accept"] == "text/event-stream"

    def test_referer_has_trailing_slash(self):
        """Test that the Referer header ends with a trailing slash."""
        headers = build_perplexity_headers(token=None, base_url="https://example.com")
        assert headers["Referer"].endswith("/")
