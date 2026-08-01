"""Pydantic models for configuration management."""

import ipaddress
from urllib.parse import ParseResult, urlparse

from pydantic import BaseModel, Field, field_validator

_ASCII_CONTROL_UPPER_BOUND = 0x1F
_DELETE_CHARACTER = 0x7F


def _is_forbidden_character(char: str) -> bool:
    """Return True for whitespace, control, or delete characters."""
    return (
        char.isspace() or ord(char) <= _ASCII_CONTROL_UPPER_BOUND or ord(char) == _DELETE_CHARACTER
    )


def _contains_forbidden_characters(value: str) -> bool:
    """Return True if the string contains any forbidden character."""
    return any(_is_forbidden_character(char) for char in value)


class URLConfig(BaseModel):
    """URL configuration for Perplexity API.

    All endpoint fields are stored as **full URLs** so they can be used
    directly without composition.  The ``base_url`` field is retained for
    deriving HTTP Origin/Referer headers and for any future endpoints that
    have not yet been added here.
    """

    base_url: str = Field(default="https://www.perplexity.ai")
    query_endpoint: str = Field(
        default="https://www.perplexity.ai/rest/sse/perplexity_ask",
    )
    thread_list_endpoint: str = Field(
        default="https://www.perplexity.ai/rest/thread/list_ask_threads",
    )
    upload_url_endpoint: str = Field(
        default="https://www.perplexity.ai/rest/uploads/batch_create_upload_urls",
    )
    s3_bucket_url: str = Field(
        default="https://ppl-ai-file-upload.s3.amazonaws.com/",
    )
    model_config_endpoint: str = Field(
        default="https://www.perplexity.ai/rest/models/config",
    )
    user_settings_endpoint: str = Field(
        default="https://www.perplexity.ai/rest/user/settings",
    )

    @field_validator(
        "base_url",
        "query_endpoint",
        "thread_list_endpoint",
        "upload_url_endpoint",
        "s3_bucket_url",
        "model_config_endpoint",
        "user_settings_endpoint",
    )
    @classmethod
    def validate_urls(cls, v: str) -> str:
        """Validate that URLs are absolute http/https URLs with a hostname.

        Rejects relative URLs, unsupported schemes, userinfo, fragments,
        control characters, whitespace, and backslashes.  HTTP is only
        permitted for loopback hosts (localhost, 127.0.0.0/8, ::1); HTTPS is
        required otherwise.  Surrounding whitespace is normalised; no DNS
        resolution is performed.
        """
        value = cls._normalise_url_string(v)
        parsed = cls._parse_url(value)
        cls._validate_url_structure(parsed)
        return value

    @classmethod
    def _normalise_url_string(cls, v: str) -> str:
        """Strip surrounding whitespace and reject forbidden characters."""
        value = v.strip()
        if not value:
            msg = "URLs must be non-empty strings"
            raise ValueError(msg)
        cls._reject_forbidden_characters(value)
        return value

    @classmethod
    def _reject_forbidden_characters(cls, value: str) -> None:
        """Reject whitespace, control characters, and backslashes."""
        if _contains_forbidden_characters(value):
            msg = "URLs cannot contain whitespace or control characters"
            raise ValueError(msg)
        if "\\" in value:
            msg = "URLs cannot contain backslashes"
            raise ValueError(msg)

    @classmethod
    def _parse_url(cls, value: str) -> ParseResult:
        """Parse a URL, converting parser failures into ValueError."""
        try:
            return urlparse(value)
        except ValueError as e:
            msg = f"Invalid URL: {value}"
            raise ValueError(msg) from e

    @classmethod
    def _validate_url_structure(cls, parsed: ParseResult) -> None:
        """Enforce scheme, hostname, userinfo, fragment, and loopback rules."""
        cls._validate_scheme_and_hostname(parsed)
        cls._validate_no_forbidden_parts(parsed)
        hostname = parsed.hostname or ""
        if parsed.scheme == "http" and not cls._is_loopback_host(hostname):
            msg = "HTTP URLs are only allowed for loopback hosts"
            raise ValueError(msg)

    @classmethod
    def _validate_scheme_and_hostname(cls, parsed: ParseResult) -> None:
        """Reject unsupported schemes and URLs without a hostname."""
        if parsed.scheme not in {"http", "https"}:
            msg = "URLs must use an http or https scheme"
            raise ValueError(msg)
        if not parsed.hostname:
            msg = "URLs must include a hostname"
            raise ValueError(msg)

    @classmethod
    def _validate_no_forbidden_parts(cls, parsed: ParseResult) -> None:
        """Reject userinfo and fragments in URLs."""
        if parsed.username is not None or parsed.password is not None:
            msg = "URLs cannot contain userinfo (username or password)"
            raise ValueError(msg)
        if parsed.fragment:
            msg = "URLs cannot contain a fragment"
            raise ValueError(msg)

    @classmethod
    def _is_loopback_host(cls, hostname: str) -> bool:
        """Return True if the hostname resolves to a loopback address."""
        if hostname == "localhost":
            return True
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return False
        return address.is_loopback


class RateLimitConfig(BaseModel):
    """Rate limiting configuration."""

    enabled: bool = Field(default=True)
    requests_per_period: int = Field(default=20, ge=1)
    period_seconds: float = Field(default=60.0, gt=0)


class FeatureConfig(BaseModel):
    """Feature flags configuration."""

    save_cookies: bool = Field(default=False)
    debug_mode: bool = Field(default=False)
