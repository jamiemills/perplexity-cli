"""Configuration and path management utilities.

The package's public abstract contract — the :class:`ConfigProvider`
protocol — is defined here so that the stable facade honestly owns the
abstract interface its callers depend on.  The concrete implementations
live in :mod:`perplexity_cli.utils.config.impl`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from perplexity_cli.config.models import FeatureConfig, RateLimitConfig, URLConfig
from perplexity_cli.utils.config.contracts import (
    default_feature_config,
    default_rate_limiting,
    is_str_dict,
)
from perplexity_cli.utils.config.impl import (
    ConfigPaths,
    clear_feature_config_cache,
    clear_urls_cache,
    get_config_dir,
    get_config_paths,
    get_debug_mode_enabled,
    get_feature_config,
    get_feature_config_path,
    get_model_config_endpoint,
    get_perplexity_base_url,
    get_query_endpoint,
    get_rate_limiting_config,
    get_s3_bucket_url,
    get_save_cookies_enabled,
    get_thread_list_url,
    get_upload_url_endpoint,
    get_urls,
    get_user_settings_endpoint,
    set_feature,
)


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


__all__ = [
    "ConfigPaths",
    "ConfigProvider",
    "FeatureConfig",
    "RateLimitConfig",
    "URLConfig",
    "clear_feature_config_cache",
    "clear_urls_cache",
    "default_feature_config",
    "default_rate_limiting",
    "get_config_dir",
    "get_config_paths",
    "get_debug_mode_enabled",
    "get_feature_config",
    "get_feature_config_path",
    "get_model_config_endpoint",
    "get_perplexity_base_url",
    "get_query_endpoint",
    "get_rate_limiting_config",
    "get_s3_bucket_url",
    "get_save_cookies_enabled",
    "get_thread_list_url",
    "get_upload_url_endpoint",
    "get_urls",
    "get_user_settings_endpoint",
    "is_str_dict",
    "set_feature",
]
