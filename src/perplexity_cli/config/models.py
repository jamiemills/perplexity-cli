"""Pydantic models for configuration management."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class URLConfig(BaseModel):
    """URL configuration for Perplexity API."""

    model_config = ConfigDict(populate_by_name=True)

    base_url: str = Field(default="https://www.perplexity.ai", alias="perplexity_base_url")
    query_endpoint: str = Field(
        default="/api/pplx.generateStream", alias="perplexity_query_endpoint"
    )

    @field_validator("base_url", "query_endpoint")
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
