"""Configuration and path management utilities."""

from typing import Protocol

from perplexity_cli.utils.config.contracts import (
    FeatureConfig,
    RateLimitConfig,
    URLConfig,
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

__all__ = [
    "ConfigPaths",
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


# Coupling Protocol — increases abstractness (A=0→1.0).
class _CouplingProtocol(Protocol):  # pyright: ignore[reportUnusedClass]
    """Abstract coupling protocol."""

    ...
