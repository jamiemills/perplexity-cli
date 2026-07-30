"""Pure data types, constants, and type guards for configuration (no IO)."""

from __future__ import annotations

from typing import Any, TypeGuard

from perplexity_cli.config.models import FeatureConfig, RateLimitConfig, URLConfig

__all__ = [
    "FeatureConfig",
    "RateLimitConfig",
    "URLConfig",
    "default_feature_config",
    "default_rate_limiting",
    "is_str_dict",
]


def is_str_dict(value: object) -> TypeGuard[dict[str, Any]]:
    """Type guard that narrows an object to dict[str, Any]."""
    return isinstance(value, dict)


def default_rate_limiting() -> dict[str, Any]:
    """Return default rate limiting configuration.

    Returns:
        dict: Default rate limiting settings.
    """
    return {
        "enabled": True,
        "requests_per_period": 20,
        "period_seconds": 60,
    }


def default_feature_config() -> dict[str, Any]:
    """Return default feature configuration.

    Returns:
        Dictionary with default feature settings.
    """
    return {
        "version": 1,
        "features": {
            "save_cookies": False,
            "debug_mode": False,
        },
    }
