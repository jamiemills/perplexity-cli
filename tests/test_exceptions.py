"""Tests for custom exception types."""

import pytest

from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    SimpleRequest,
    SimpleResponse,
)


class TestSimpleRequest:
    """Tests for SimpleRequest data object."""

    def test_stores_method_and_url(self):
        """Test that SimpleRequest stores method and url attributes."""
        req = SimpleRequest(method="POST", url="https://example.com/api")
        assert req.method == "POST"
        assert req.url == "https://example.com/api"

    def test_default_values(self):
        """Test SimpleRequest with default values."""
        req = SimpleRequest()
        assert req.method == ""
        assert req.url == ""


class TestSimpleResponse:
    """Tests for SimpleResponse data object."""

    def test_stores_all_fields(self):
        """Test that SimpleResponse stores all fields."""
        req = SimpleRequest(method="POST", url="https://example.com/api")
        resp = SimpleResponse(
            status_code=403,
            headers={"content-type": "text/plain"},
            text="Forbidden",
            request=req,
        )
        assert resp.status_code == 403
        assert resp.headers == {"content-type": "text/plain"}
        assert resp.text == "Forbidden"
        assert resp.request is req

    def test_default_values(self):
        """Test SimpleResponse with default values."""
        resp = SimpleResponse()
        assert resp.status_code == 0
        assert resp.headers == {}
        assert resp.text == ""
        assert isinstance(resp.request, SimpleRequest)


class TestPerplexityHTTPStatusError:
    """Tests for PerplexityHTTPStatusError exception."""

    def test_is_exception(self):
        """Test that PerplexityHTTPStatusError is an Exception."""
        error = PerplexityHTTPStatusError("test error")
        assert isinstance(error, Exception)

    def test_stores_message(self):
        """Test that the message is stored and accessible via str()."""
        error = PerplexityHTTPStatusError("Authentication failed")
        assert str(error) == "Authentication failed"

    def test_carries_request_and_response(self):
        """Test that request and response are accessible as attributes."""
        req = SimpleRequest(method="POST", url="https://example.com/api")
        resp = SimpleResponse(status_code=401, text="Unauthorized", request=req)
        error = PerplexityHTTPStatusError("Authentication failed", request=req, response=resp)
        assert error.request is req
        assert error.response is resp
        assert error.response.status_code == 401

    def test_default_request_and_response(self):
        """Test default request and response when not provided."""
        error = PerplexityHTTPStatusError("test")
        assert isinstance(error.request, SimpleRequest)
        assert isinstance(error.response, SimpleResponse)

    def test_can_be_caught_as_exception(self):
        """Test that PerplexityHTTPStatusError can be caught as Exception."""
        with pytest.raises(PerplexityHTTPStatusError):
            raise PerplexityHTTPStatusError("test error")

    def test_response_headers_accessible(self):
        """Test that response headers can be accessed from the error."""
        resp = SimpleResponse(
            status_code=429,
            headers={"retry-after": "30", "cf-ray": "abc123"},
            text="Rate limited",
        )
        error = PerplexityHTTPStatusError("Rate limit exceeded", response=resp)
        assert error.response.headers.get("retry-after") == "30"
        assert error.response.headers.get("cf-ray") == "abc123"


class TestPerplexityRequestError:
    """Tests for PerplexityRequestError exception."""

    def test_is_exception(self):
        """Test that PerplexityRequestError is an Exception."""
        error = PerplexityRequestError("Connection failed")
        assert isinstance(error, Exception)

    def test_stores_message(self):
        """Test that the message is stored and accessible via str()."""
        error = PerplexityRequestError("Connection refused")
        assert str(error) == "Connection refused"

    def test_can_be_caught_as_exception(self):
        """Test that PerplexityRequestError can be caught as Exception."""
        with pytest.raises(PerplexityRequestError):
            raise PerplexityRequestError("Network error")

    def test_can_be_raised_and_caught_specifically(self):
        """Test that it can be caught by its own type."""
        with pytest.raises(PerplexityRequestError, match="Connection failed"):
            raise PerplexityRequestError("Connection failed")


class TestExceptionHierarchy:
    """Tests for exception hierarchy independence."""

    def test_http_and_request_errors_are_distinct(self):
        """Test that the two exception types do not catch each other."""
        http_error = PerplexityHTTPStatusError("HTTP error")
        request_error = PerplexityRequestError("Request error")

        assert not isinstance(http_error, PerplexityRequestError)
        assert not isinstance(request_error, PerplexityHTTPStatusError)

    def test_not_subclass_of_httpx_types(self):
        """Test that custom exceptions are not subclasses of httpx types."""
        import httpx

        assert not issubclass(PerplexityHTTPStatusError, httpx.HTTPStatusError)
        assert not issubclass(PerplexityRequestError, httpx.RequestError)
