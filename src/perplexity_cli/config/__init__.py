"""Configuration management for Perplexity CLI.

This package provides configuration models and utilities for managing:
- API URLs (base_url, endpoints)
- Rate limiting settings (requests per period, throttling)
- Feature flags (cookie storage, debug mode)

Models are Pydantic-based for runtime validation and automatic serialisation.
"""

from perplexity_cli.config.models import (
    FeatureConfig,
    RateLimitConfig,
    URLConfig,
)

__all__ = [
    "URLConfig",
    "RateLimitConfig",
    "FeatureConfig",
]
