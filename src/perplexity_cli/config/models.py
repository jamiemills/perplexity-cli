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

    @field_validator("requests_per_period")
    @classmethod
    def validate_requests_per_period(cls, v: int) -> int:
        """Validate requests per period."""
        if v < 1:
            raise ValueError("requests_per_period must be >= 1")
        return v

    @field_validator("period_seconds")
    @classmethod
    def validate_period_seconds(cls, v: float) -> float:
        """Validate period seconds."""
        if v <= 0:
            raise ValueError("period_seconds must be > 0")
        return v


class FeatureConfig(BaseModel):
    """Feature flags configuration."""

    save_cookies: bool = Field(default=False)
    debug_mode: bool = Field(default=False)


class PerplexityURLConfig(BaseModel):
    """Perplexity-specific URL configuration (nested in config files)."""

    base_url: str = Field(...)
    query_endpoint: str = Field(...)

    @field_validator("base_url", "query_endpoint")
    @classmethod
    def validate_urls(cls, v: str) -> str:
        """Validate that URLs are non-empty strings."""
        if not v or not isinstance(v, str):
            raise ValueError("URLs must be non-empty strings")
        if not v.strip():
            raise ValueError("URLs cannot be empty or whitespace-only")
        return v


class PerplexityRateLimitConfig(BaseModel):
    """Rate limiting config as stored in urls.json."""

    enabled: bool | None = Field(default=None)
    requests_per_period: int | None = Field(default=None, ge=1)
    period_seconds: float | None = Field(default=None, gt=0)


class AppConfig(BaseModel):
    """Main application configuration combining all config types."""

    urls: dict | None = Field(default=None)  # Raw URLs dict from file
    rate_limiting: dict | None = Field(default=None)  # Raw rate limiting dict from file
    features: dict | None = Field(default=None)  # Raw features dict from file

    @classmethod
    def from_dicts(
        cls,
        urls_config: dict | None = None,
        rate_limiting_config: dict | None = None,
        features_config: dict | None = None,
    ) -> "AppConfig":
        """Create AppConfig from raw configuration dictionaries.

        Args:
            urls_config: Dictionary containing URLs configuration
            rate_limiting_config: Dictionary containing rate limiting configuration
            features_config: Dictionary containing feature flags configuration

        Returns:
            AppConfig instance with validated configurations
        """
        return cls(
            urls=urls_config, rate_limiting=rate_limiting_config, features=features_config
        )
