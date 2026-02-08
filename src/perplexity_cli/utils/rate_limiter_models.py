"""Pydantic models for rate limiting."""

from pydantic import BaseModel, Field


class RateLimiterConfig(BaseModel):
    """Configuration for token bucket rate limiter."""

    requests_per_period: int = Field(..., ge=1)
    period_seconds: float = Field(..., gt=0)


class RateLimiterState(BaseModel):
    """Internal state of token bucket rate limiter."""

    tokens: float = Field(default=0.0, ge=0)
    last_refill_time: float = Field(..., ge=0)
    requests_per_period: int = Field(..., ge=1)
    period_seconds: float = Field(..., gt=0)


class RateLimiterStats(BaseModel):
    """Statistics from rate limiter."""

    total_requests: int = Field(default=0, ge=0)
    total_wait_time: float = Field(default=0.0, ge=0)
    average_wait_time: float = Field(default=0.0, ge=0)

    @classmethod
    def from_data(
        cls,
        total_requests: int,
        total_wait_time: float,
    ) -> "RateLimiterStats":
        """Create stats from raw data."""
        average_wait_time = total_wait_time / total_requests if total_requests > 0 else 0.0
        return cls(
            total_requests=total_requests,
            total_wait_time=total_wait_time,
            average_wait_time=average_wait_time,
        )
