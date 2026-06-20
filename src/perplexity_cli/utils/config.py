"""Configuration and path management utilities."""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from importlib import resources  # nosemgrep: python37-compatibility-importlib2
from pathlib import Path
from typing import Any, TypeGuard

from perplexity_cli.config.models import FeatureConfig, RateLimitConfig, URLConfig
from perplexity_cli.utils.exceptions import ConfigurationError


def _is_str_dict(value: object) -> TypeGuard[dict[str, Any]]:
    """Type guard that narrows an object to dict[str, Any]."""
    return isinstance(value, dict)


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


def get_config_paths() -> ConfigPaths:
    """Return the resolved config paths for the current environment."""
    return ConfigPaths(get_config_dir())


def get_config_dir() -> Path:
    """Get the configuration directory path, creating it if necessary.

    If ``PERPLEXITY_CONFIG_DIR`` is set, that directory is used directly.

    Returns the platform-specific configuration directory:
    - Linux/macOS: ~/.config/perplexity-cli/
    - Windows: %APPDATA%\\perplexity-cli\\

    Returns:
        Path: The configuration directory path.

    Raises:
        RuntimeError: If the directory cannot be created.
    """
    configured_dir = os.getenv("PERPLEXITY_CONFIG_DIR")
    if configured_dir:
        config_dir = Path(configured_dir).expanduser()
    elif os.name == "nt":
        # Windows
        base_dir = Path(os.getenv("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        config_dir = base_dir / "perplexity-cli"
    else:
        # Linux/macOS — respect XDG_CONFIG_HOME
        xdg_config = os.getenv("XDG_CONFIG_HOME")
        if xdg_config:
            base_dir = Path(xdg_config)
        else:
            base_dir = Path.home() / ".config"
        config_dir = base_dir / "perplexity-cli"

    try:
        config_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ConfigurationError(f"Failed to create config directory {config_dir}: {e}") from e

    return config_dir


def _get_default_urls() -> dict[str, Any]:
    """Load default URLs from the package configuration.

    Returns:
        dict: The default URLs configuration.

    Raises:
        RuntimeError: If default configuration cannot be loaded.
    """
    try:
        package_config = resources.files("perplexity_cli.config").joinpath("urls.json")
        with package_config.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigurationError(f"Failed to load default URLs configuration: {e}") from e


def _ensure_user_urls_config() -> None:
    """Ensure user URLs configuration exists, creating from defaults if needed."""
    urls_path = get_config_paths().urls_path
    if not urls_path.exists():
        try:
            default_urls = _get_default_urls()
            with open(urls_path, "w", encoding="utf-8") as f:
                json.dump(default_urls, f, indent=2)
        except (OSError, json.JSONDecodeError) as e:
            raise ConfigurationError(f"Failed to create URLs configuration file: {e}") from e


def _apply_url_env_overrides(perplexity_config: dict[str, Any]) -> None:
    """Apply environment variable overrides to URL configuration in place.

    Args:
        perplexity_config: Mutable dictionary of URL configuration fields.
    """
    env_overrides = {
        "PERPLEXITY_BASE_URL": "base_url",
        "PERPLEXITY_QUERY_ENDPOINT": "query_endpoint",
        "PERPLEXITY_THREAD_LIST_ENDPOINT": "thread_list_endpoint",
        "PERPLEXITY_UPLOAD_URL_ENDPOINT": "upload_url_endpoint",
        "PERPLEXITY_S3_BUCKET_URL": "s3_bucket_url",
        "PERPLEXITY_MODEL_CONFIG_ENDPOINT": "model_config_endpoint",
        "PERPLEXITY_USER_SETTINGS_ENDPOINT": "user_settings_endpoint",
    }
    for env_var, field_name in env_overrides.items():
        if env_var in os.environ:
            perplexity_config[field_name] = os.environ[env_var]


@lru_cache(maxsize=1)
def get_urls() -> URLConfig:
    """Load and cache the URLs configuration as a Pydantic URLConfig model.

    Returns the user configuration if it exists, otherwise creates it from
    defaults.  Missing fields fall through to the Pydantic model defaults
    defined in :class:`~perplexity_cli.config.models.URLConfig`.

    Environment variables can override configuration values:

    - ``PERPLEXITY_BASE_URL``
    - ``PERPLEXITY_QUERY_ENDPOINT``
    - ``PERPLEXITY_THREAD_LIST_ENDPOINT``
    - ``PERPLEXITY_UPLOAD_URL_ENDPOINT``
    - ``PERPLEXITY_S3_BUCKET_URL``

    Returns:
        URLConfig: The validated URLs configuration model.

    Raises:
        RuntimeError: If configuration cannot be loaded or is invalid.
    """
    _ensure_user_urls_config()

    urls_path = get_config_paths().urls_path
    try:
        with open(urls_path, encoding="utf-8") as f:
            urls_dict = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigurationError(f"Failed to load URLs configuration: {e}") from e

    if "perplexity" not in urls_dict:
        raise ConfigurationError("URLs configuration missing 'perplexity' section")

    perplexity_config = urls_dict["perplexity"]
    if not _is_str_dict(perplexity_config):
        raise ConfigurationError("'perplexity' section must be a dictionary")

    _apply_url_env_overrides(perplexity_config)

    try:
        return URLConfig.model_validate(perplexity_config)
    except ValueError as e:
        raise ConfigurationError(f"Invalid URLs configuration: {e}") from e


def clear_urls_cache() -> None:
    """Clear the URLs configuration cache.

    Useful for testing or when configuration files are modified externally.
    """
    get_urls.cache_clear()


def get_perplexity_base_url() -> str:
    """Get the Perplexity base URL from configuration.

    Returns:
        str: The Perplexity base URL (e.g., https://www.perplexity.ai).

    Raises:
        RuntimeError: If configuration is invalid or missing required fields.
    """
    url_config = get_urls()
    return url_config.base_url


def get_query_endpoint() -> str:
    """Get the Perplexity query endpoint URL from configuration.

    Returns:
        str: The Perplexity query endpoint URL.

    Raises:
        RuntimeError: If configuration is invalid or missing required fields.
    """
    url_config = get_urls()
    return url_config.query_endpoint


def get_thread_list_url() -> str:
    """Get the full URL for the Perplexity thread list API endpoint.

    Returns:
        str: The full thread list URL (e.g.,
            https://www.perplexity.ai/rest/thread/list_ask_threads).

    Raises:
        RuntimeError: If configuration is invalid or missing required fields.
    """
    url_config = get_urls()
    return url_config.thread_list_endpoint


def get_upload_url_endpoint() -> str:
    """Get the full URL for the Perplexity upload-URL endpoint.

    Returns:
        str: The upload URL endpoint (e.g.,
            https://www.perplexity.ai/rest/uploads/batch_create_upload_urls).

    Raises:
        RuntimeError: If configuration is invalid or missing required fields.
    """
    url_config = get_urls()
    return url_config.upload_url_endpoint


def get_s3_bucket_url() -> str:
    """Get the S3 bucket URL used for file uploads.

    Returns:
        str: The S3 bucket URL (e.g.,
            https://ppl-ai-file-upload.s3.amazonaws.com/).

    Raises:
        RuntimeError: If configuration is invalid or missing required fields.
    """
    url_config = get_urls()
    return url_config.s3_bucket_url


def get_model_config_endpoint() -> str:
    """Get the full URL for the model configuration endpoint.

    Returns:
        str: The model config endpoint URL (e.g.,
            https://www.perplexity.ai/rest/models/config).

    Raises:
        RuntimeError: If configuration is invalid or missing required fields.
    """
    url_config = get_urls()
    return url_config.model_config_endpoint


def get_user_settings_endpoint() -> str:
    """Get the full URL for the user settings endpoint.

    Returns:
        str: The user settings endpoint URL (e.g.,
            https://www.perplexity.ai/rest/user/settings).

    Raises:
        RuntimeError: If configuration is invalid or missing required fields.
    """
    url_config = get_urls()
    return url_config.user_settings_endpoint


def _get_default_rate_limiting() -> dict[str, Any]:
    """Get default rate limiting configuration.

    Returns:
        dict: Default rate limiting settings.
    """
    return {
        "enabled": True,
        "requests_per_period": 20,
        "period_seconds": 60,
    }


def _load_rate_limiting_from_file(config_dict: dict[str, Any]) -> None:
    """Load rate limiting settings from urls.json into config_dict in place.

    Args:
        config_dict: Mutable dictionary to update with file-based settings.

    Raises:
        ConfigurationError: If the rate_limiting section is not a dictionary.
    """
    try:
        urls_path = get_config_paths().urls_path
        if not urls_path.exists():
            return
        with open(urls_path, encoding="utf-8") as f:
            urls_data = json.load(f)
        _merge_rate_limiting_section(urls_data, config_dict)
    except ConfigurationError:
        raise
    except (OSError, json.JSONDecodeError):
        logging.getLogger(__name__).debug("Could not load or parse urls configuration file")


def _merge_rate_limiting_section(urls_data: dict[str, Any], config_dict: dict[str, Any]) -> None:
    """Merge the rate_limiting section from urls data into config_dict.

    Args:
        urls_data: Parsed urls.json data.
        config_dict: Mutable dictionary to update.

    Raises:
        ConfigurationError: If the rate_limiting section is not a dictionary.
    """
    if "rate_limiting" not in urls_data:
        return
    user_config = urls_data["rate_limiting"]
    if not _is_str_dict(user_config):
        raise ConfigurationError("rate_limiting section must be a dictionary")
    config_dict.update(user_config)


def _apply_rate_limiting_env_overrides(config_dict: dict[str, Any]) -> None:
    """Apply environment variable overrides to rate limiting configuration.

    Args:
        config_dict: Mutable dictionary to update with environment overrides.

    Raises:
        ConfigurationError: If environment variable values are invalid.
    """
    _apply_rate_limiting_enabled(config_dict)
    _apply_rate_limiting_rps(config_dict)
    _apply_rate_limiting_period(config_dict)


def _apply_rate_limiting_enabled(config_dict: dict[str, Any]) -> None:
    """Apply the PERPLEXITY_RATE_LIMITING_ENABLED override if set."""
    if "PERPLEXITY_RATE_LIMITING_ENABLED" in os.environ:
        enabled_str = os.environ["PERPLEXITY_RATE_LIMITING_ENABLED"].lower()
        config_dict["enabled"] = enabled_str in ("true", "1", "yes")


def _apply_rate_limiting_rps(config_dict: dict[str, Any]) -> None:
    """Apply the PERPLEXITY_RATE_LIMITING_RPS override if set."""
    if "PERPLEXITY_RATE_LIMITING_RPS" not in os.environ:
        return
    try:
        config_dict["requests_per_period"] = int(os.environ["PERPLEXITY_RATE_LIMITING_RPS"])
    except ValueError as e:
        raise ConfigurationError(
            f"Invalid PERPLEXITY_RATE_LIMITING_RPS: {os.environ['PERPLEXITY_RATE_LIMITING_RPS']}"
        ) from e


def _apply_rate_limiting_period(config_dict: dict[str, Any]) -> None:
    """Apply the PERPLEXITY_RATE_LIMITING_PERIOD override if set."""
    if "PERPLEXITY_RATE_LIMITING_PERIOD" not in os.environ:
        return
    try:
        config_dict["period_seconds"] = float(os.environ["PERPLEXITY_RATE_LIMITING_PERIOD"])
    except ValueError as e:
        raise ConfigurationError(
            f"Invalid PERPLEXITY_RATE_LIMITING_PERIOD: {os.environ['PERPLEXITY_RATE_LIMITING_PERIOD']}"
        ) from e


def get_rate_limiting_config() -> RateLimitConfig:
    """Load and return rate limiting configuration as a Pydantic RateLimitConfig model.

    Returns the configuration from urls.json if present, otherwise returns defaults.
    Environment variables can override configuration values:
    - PERPLEXITY_RATE_LIMITING_ENABLED: "true" or "false"
    - PERPLEXITY_RATE_LIMITING_RPS: requests_per_period (e.g., "10")
    - PERPLEXITY_RATE_LIMITING_PERIOD: period_seconds (e.g., "60")

    Returns:
        RateLimitConfig: The validated rate limiting configuration model.

    Raises:
        RuntimeError: If configuration is invalid.
    """
    config_dict = _get_default_rate_limiting()
    _load_rate_limiting_from_file(config_dict)
    _apply_rate_limiting_env_overrides(config_dict)

    try:
        return RateLimitConfig(**config_dict)
    except ValueError as e:
        raise ConfigurationError(f"Invalid rate limiting configuration: {e}") from e


def get_feature_config_path() -> Path:
    """Get path to feature configuration file.

    Returns:
        Path to config.json in user config directory.
    """
    return get_config_paths().feature_config_path


def _get_default_feature_config() -> dict[str, Any]:
    """Get default feature configuration.

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


def _ensure_user_feature_config() -> None:
    """Ensure user feature configuration file exists.

    Creates config.json from defaults if it doesn't exist.
    """
    config_path = get_config_paths().feature_config_path

    if not config_path.exists():
        defaults = _get_default_feature_config()
        config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(defaults, f, indent=2)


def _load_feature_config_from_file() -> dict[str, Any]:
    """Load feature settings from user configuration file.

    Returns:
        Dictionary of feature settings, falling back to defaults on read errors.

    Raises:
        ConfigurationError: If the features section is not a dictionary.
    """
    feature_dict: dict[str, Any] = {"save_cookies": False, "debug_mode": False}
    config_path = get_config_paths().feature_config_path
    try:
        with open(config_path, encoding="utf-8") as f:
            user_config = json.load(f)
        if "features" in user_config:
            features = user_config["features"]
            if not _is_str_dict(features):
                raise ConfigurationError(
                    "Feature configuration 'features' section must be a dictionary"
                )
            feature_dict.update(features)
    except (OSError, json.JSONDecodeError) as e:
        from perplexity_cli.utils.logging import get_logger as _get_logger

        _get_logger().warning("Failed to load feature config, using defaults: %s", e)
    return feature_dict


def _apply_feature_env_overrides(feature_dict: dict[str, Any]) -> None:
    """Apply environment variable overrides to feature configuration in place.

    Args:
        feature_dict: Mutable dictionary to update with environment overrides.
    """
    if "PERPLEXITY_SAVE_COOKIES" in os.environ:
        value = os.environ["PERPLEXITY_SAVE_COOKIES"].lower()
        feature_dict["save_cookies"] = value in ("true", "1", "yes")

    if "PERPLEXITY_DEBUG_MODE" in os.environ:
        value = os.environ["PERPLEXITY_DEBUG_MODE"].lower()
        feature_dict["debug_mode"] = value in ("true", "1", "yes")


@lru_cache(maxsize=1)
def get_feature_config() -> FeatureConfig:
    """Load feature configuration with defaults and environment overrides.

    Precedence (highest to lowest):
    1. Environment variables
    2. User config file (~/.config/perplexity-cli/config.json)
    3. Defaults

    Environment variables:
    - PERPLEXITY_SAVE_COOKIES: "true" or "false"
    - PERPLEXITY_DEBUG_MODE: "true" or "false"

    Returns:
        FeatureConfig: The validated feature configuration model.

    Raises:
        RuntimeError: If configuration is invalid.
    """
    _ensure_user_feature_config()
    feature_dict = _load_feature_config_from_file()
    _apply_feature_env_overrides(feature_dict)

    try:
        return FeatureConfig(**feature_dict)
    except ValueError as e:
        raise ConfigurationError(f"Invalid feature configuration: {e}") from e


def clear_feature_config_cache() -> None:
    """Clear the feature configuration cache.

    Useful for testing or when configuration changes.
    """
    get_feature_config.cache_clear()


def get_save_cookies_enabled() -> bool:
    """Check if cookie saving is enabled.

    Returns:
        True if cookies should be saved, False otherwise.
    """
    config = get_feature_config()
    return config.save_cookies


def get_debug_mode_enabled() -> bool:
    """Check if debug mode is enabled in configuration.

    Note: This does not check CLI --debug flag, only config file.

    Returns:
        True if debug mode is enabled in config, False otherwise.
    """
    config = get_feature_config()
    return config.debug_mode


def set_feature(key: str, value: object) -> None:  # nosemgrep: boolean-flag-argument
    """Set a feature configuration value.

    Args:
        key: Feature key ("save_cookies" or "debug_mode").
        value: Boolean value to set.

    Raises:
        RuntimeError: If key is invalid or file cannot be written.
    """
    valid_keys = ["save_cookies", "debug_mode"]
    if key not in valid_keys:
        raise ConfigurationError(f"Invalid feature key: {key}. Valid keys: {', '.join(valid_keys)}")

    if not isinstance(value, bool):
        raise ConfigurationError(f"Feature value must be boolean, got {type(value).__name__}")

    # Load current config (as Pydantic model)
    feature_config = get_feature_config()

    # Create updated feature dict
    feature_dict = {
        "save_cookies": feature_config.save_cookies,
        "debug_mode": feature_config.debug_mode,
    }
    feature_dict[key] = value

    # Prepare the file content with version and features structure
    config_content = {"version": 1, "features": feature_dict}

    # Write to file
    config_path = get_config_paths().feature_config_path
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_content, f, indent=2)

    # Clear cache so next call loads fresh config
    clear_feature_config_cache()
