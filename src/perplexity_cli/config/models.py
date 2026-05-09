"""Pydantic models for configuration management."""

from pydantic import BaseModel, Field, field_validator


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

    @field_validator(
        "base_url",
        "query_endpoint",
        "thread_list_endpoint",
        "upload_url_endpoint",
        "s3_bucket_url",
    )
    @classmethod
    def validate_urls(cls, v: str) -> str:
        """Validate that URLs are non-empty strings."""
        if not v or not isinstance(v, str):
            raise ValueError("URLs must be non-empty strings")
        if not v.strip():
            raise ValueError("URLs cannot be empty or whitespace-only")
        return v


class RateLimitConfig(BaseModel):
    """Rate limiting configuration."""

    enabled: bool = Field(default=True)
    requests_per_period: int = Field(default=20, ge=1)
    period_seconds: float = Field(default=60.0, gt=0)


class FeatureConfig(BaseModel):
    """Feature flags configuration."""

    save_cookies: bool = Field(default=False)
    debug_mode: bool = Field(default=False)
