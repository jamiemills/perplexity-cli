"""Pydantic models for rate limiting."""

from pydantic import BaseModel, Field, field_validator


class RateLimiterConfig(BaseModel):
    """Configuration for token bucket rate limiter."""

    requests_per_period: int = Field(..., ge=1)
    period_seconds: float = Field(..., gt=0)

    @field_validator("requests_per_period")
    @classmethod
    def validate_requests(cls, v: int) -> int:
        """Validate requests per period is positive."""
        if v <= 0:
            raise ValueError("requests_per_period must be greater than 0")
        return v

    @field_validator("period_seconds")
    @classmethod
    def validate_period(cls, v: float) -> float:
        """Validate period seconds is positive."""
        if v <= 0:
            raise ValueError("period_seconds must be greater than 0")
        return v


class RateLimiterState(BaseModel):
    """Internal state of token bucket rate limiter."""

    tokens: float = Field(default=0.0, ge=0)
    last_refill_time: float = Field(...)
    requests_per_period: int = Field(..., ge=1)
    period_seconds: float = Field(..., gt=0)

    @field_validator("tokens")
    @classmethod
    def validate_tokens(cls, v: float) -> float:
        """Validate tokens is non-negative."""
        if v < 0:
            raise ValueError("tokens cannot be negative")
        return v

    @field_validator("last_refill_time")
    @classmethod
    def validate_refill_time(cls, v: float) -> float:
        """Validate refill time is a valid timestamp."""
        if v < 0:
            raise ValueError("last_refill_time cannot be negative")
        return v


class RateLimiterStats(BaseModel):
    """Statistics from rate limiter."""

    total_requests: int = Field(default=0, ge=0)
    total_wait_time: float = Field(default=0.0, ge=0)
    average_wait_time: float = Field(default=0.0, ge=0)

    @field_validator("total_requests", "total_wait_time", "average_wait_time")
    @classmethod
    def validate_non_negative(cls, v: float) -> float:
        """Validate stats are non-negative."""
        if v < 0:
            raise ValueError("Statistics cannot be negative")
        return v

    @classmethod
    def from_data(
        cls,
        total_requests: int,
        total_wait_time: float,
    ) -> "RateLimiterStats":
        """Create stats from raw data."""
        average_wait_time = (
            total_wait_time / total_requests if total_requests > 0 else 0.0
        )
        return cls(
            total_requests=total_requests,
            total_wait_time=total_wait_time,
            average_wait_time=average_wait_time,
        )
