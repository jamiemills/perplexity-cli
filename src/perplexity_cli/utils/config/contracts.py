"""Pure data types, constants, and type guards for configuration (no IO).

The Pydantic configuration models live in :mod:`perplexity_cli.config.models`
(domain layer), keeping this module free of implementation imports while it
owns every abstract contract and pure value type of the config package.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, TypeGuard, runtime_checkable

from perplexity_cli.config.models import FeatureConfig, RateLimitConfig, URLConfig

__all__ = [
    "ConfigPaths",
    "ConfigProvider",
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


class ConfigPaths:
    """Resolved paths for all user-writable config files."""

    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir

    @property
    def token_path(self) -> Path:
        """Path to the encrypted authentication token file."""
        return self.config_dir / "token.json"

    @property
    def style_path(self) -> Path:
        """Path to the user style preferences file."""
        return self.config_dir / "style.json"

    @property
    def urls_path(self) -> Path:
        """Path to the API endpoint URL overrides file."""
        return self.config_dir / "urls.json"

    @property
    def feature_config_path(self) -> Path:
        """Path to the feature toggle configuration file."""
        return self.config_dir / "config.json"

    @property
    def cache_path(self) -> Path:
        """Path to the encrypted thread cache file."""
        return self.config_dir / "threads-cache.json"

    @property
    def log_file_path(self) -> Path:
        """Path to the CLI log file."""
        return self.config_dir / "perplexity-cli.log"


@runtime_checkable
class ConfigProvider(Protocol):
    """Contract for reading and mutating Perplexity CLI configuration."""

    def get_urls(self) -> URLConfig:
        """Return the validated URL configuration model."""
        ...

    def get_feature_config(self) -> FeatureConfig:
        """Return the validated feature configuration model."""
        ...

    def get_rate_limiting_config(self) -> RateLimitConfig:
        """Return the validated rate limiting configuration model."""
        ...

    def get_config_paths(self) -> ConfigPaths:
        """Return the resolved config paths for the current environment."""
        ...

    def set_feature(self, key: str, value: object) -> None:
        """Set a feature configuration value, persisting it to disk."""
        ...
