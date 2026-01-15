"""Configuration and path management utilities."""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from perplexity_cli.config.models import FeatureConfig, RateLimitConfig, URLConfig


def get_config_dir() -> Path:
    """Get the configuration directory path, creating it if necessary.

    Returns the platform-specific configuration directory:
    - Linux/macOS: ~/.config/perplexity-cli/
    - Windows: %APPDATA%\\perplexity-cli\\

    Returns:
        Path: The configuration directory path.

    Raises:
        RuntimeError: If the directory cannot be created.
    """
    if os.name == "nt":
        # Windows
        base_dir = Path(os.getenv("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    else:
        # Linux/macOS
        base_dir = Path.home() / ".config"

    config_dir = base_dir / "perplexity-cli"

    try:
        config_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(f"Failed to create config directory {config_dir}: {e}") from e

    return config_dir


def get_token_path() -> Path:
    """Get the path to the token file.

    Returns:
        Path: Path to ~/.config/perplexity-cli/token.json (or platform equivalent).
    """
    return get_config_dir() / "token.json"


def get_style_path() -> Path:
    """Get the path to the style configuration file.

    Returns:
        Path: Path to ~/.config/perplexity-cli/style.json (or platform equivalent).
    """
    return get_config_dir() / "style.json"


def get_urls_path() -> Path:
    """Get the path to the URLs configuration file.

    Returns:
        Path: Path to ~/.config/perplexity-cli/urls.json (or platform equivalent).
    """
    return get_config_dir() / "urls.json"


def _get_default_urls() -> dict:
    """Load default URLs from the package configuration.

    Returns:
        dict: The default URLs configuration.

    Raises:
        RuntimeError: If default configuration cannot be loaded.
    """
    package_config = Path(__file__).parent.parent / "config" / "urls.json"
    try:
        with open(package_config) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Failed to load default URLs configuration: {e}") from e


def _ensure_user_urls_config() -> None:
    """Ensure user URLs configuration exists, creating from defaults if needed."""
    urls_path = get_urls_path()
    if not urls_path.exists():
        try:
            default_urls = _get_default_urls()
            with open(urls_path, "w") as f:
                json.dump(default_urls, f, indent=2)
        except (OSError, json.JSONDecodeError) as e:
            raise RuntimeError(f"Failed to create URLs configuration file: {e}") from e


def _validate_urls_config(urls: dict[str, Any]) -> None:
    """Validate URLs configuration structure.

    Args:
        urls: Configuration dictionary to validate.

    Raises:
        RuntimeError: If configuration is invalid.
    """
    if not isinstance(urls, dict):
        raise RuntimeError("URLs configuration must be a dictionary")

    if "perplexity" not in urls:
        raise RuntimeError("URLs configuration missing 'perplexity' section")

    perplexity = urls["perplexity"]
    if not isinstance(perplexity, dict):
        raise RuntimeError("'perplexity' section must be a dictionary")

    required_fields = ["base_url", "query_endpoint"]
    for field in required_fields:
        if field not in perplexity:
            raise RuntimeError(f"URLs configuration missing 'perplexity.{field}'")
        if not isinstance(perplexity[field], str):
            raise RuntimeError(f"URLs configuration 'perplexity.{field}' must be a string")
        if not perplexity[field].strip():
            raise RuntimeError(f"URLs configuration 'perplexity.{field}' cannot be empty")


@lru_cache(maxsize=1)
def get_urls() -> URLConfig:
    """Load and cache the URLs configuration as a Pydantic URLConfig model.

    Returns the user configuration if it exists, otherwise creates it from defaults.
    Environment variables can override configuration values:
    - PERPLEXITY_BASE_URL: Overrides base_url
    - PERPLEXITY_QUERY_ENDPOINT: Overrides query_endpoint

    Returns:
        URLConfig: The validated URLs configuration model.

    Raises:
        RuntimeError: If configuration cannot be loaded or is invalid.
    """
    _ensure_user_urls_config()

    urls_path = get_urls_path()
    try:
        with open(urls_path) as f:
            urls_dict = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Failed to load URLs configuration: {e}") from e

    # Extract perplexity config from dict
    if "perplexity" not in urls_dict:
        raise RuntimeError("URLs configuration missing 'perplexity' section")

    perplexity_config = urls_dict["perplexity"]
    if not isinstance(perplexity_config, dict):
        raise RuntimeError("'perplexity' section must be a dictionary")

    # Create base URLConfig from file
    try:
        url_config = URLConfig(
            base_url=perplexity_config.get("base_url", "https://www.perplexity.ai"),
            query_endpoint=perplexity_config.get("query_endpoint", "/api/pplx.generateStream"),
        )
    except ValueError as e:
        raise RuntimeError(f"Invalid URLs configuration: {e}") from e

    # Apply environment variable overrides
    if "PERPLEXITY_BASE_URL" in os.environ:
        url_config.base_url = os.environ["PERPLEXITY_BASE_URL"]

    if "PERPLEXITY_QUERY_ENDPOINT" in os.environ:
        url_config.query_endpoint = os.environ["PERPLEXITY_QUERY_ENDPOINT"]

    # Validate after environment overrides using Pydantic
    try:
        URLConfig(base_url=url_config.base_url, query_endpoint=url_config.query_endpoint)
    except ValueError as e:
        raise RuntimeError(f"Invalid URLs configuration after environment overrides: {e}") from e

    return url_config


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


def _validate_rate_limiting_config(config: dict[str, Any]) -> None:
    """Validate rate limiting configuration structure.

    Args:
        config: Configuration dictionary to validate.

    Raises:
        RuntimeError: If configuration is invalid.
    """
    if not isinstance(config, dict):
        raise RuntimeError("Rate limiting configuration must be a dictionary")

    if "enabled" in config and not isinstance(config["enabled"], bool):
        raise RuntimeError("Rate limiting 'enabled' must be a boolean")

    if "requests_per_period" in config:
        if not isinstance(config["requests_per_period"], int):
            raise RuntimeError("Rate limiting 'requests_per_period' must be an integer")
        if config["requests_per_period"] <= 0:
            raise RuntimeError("Rate limiting 'requests_per_period' must be greater than 0")

    if "period_seconds" in config:
        if not isinstance(config["period_seconds"], (int, float)):
            raise RuntimeError("Rate limiting 'period_seconds' must be a number")
        if config["period_seconds"] <= 0:
            raise RuntimeError("Rate limiting 'period_seconds' must be greater than 0")


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
    # Start with defaults
    config_dict = _get_default_rate_limiting()

    # Try to load from urls.json
    try:
        urls_path = get_urls_path()
        if urls_path.exists():
            with open(urls_path) as f:
                urls_data = json.load(f)
                if "rate_limiting" in urls_data:
                    user_config = urls_data["rate_limiting"]
                    _validate_rate_limiting_config(user_config)
                    # Merge user config with defaults
                    config_dict.update(user_config)
    except (OSError, json.JSONDecodeError, RuntimeError):
        # If urls.json doesn't have rate_limiting section, just use defaults
        pass

    # Apply environment variable overrides
    if "PERPLEXITY_RATE_LIMITING_ENABLED" in os.environ:
        enabled_str = os.environ["PERPLEXITY_RATE_LIMITING_ENABLED"].lower()
        config_dict["enabled"] = enabled_str in ("true", "1", "yes")

    if "PERPLEXITY_RATE_LIMITING_RPS" in os.environ:
        try:
            config_dict["requests_per_period"] = int(os.environ["PERPLEXITY_RATE_LIMITING_RPS"])
        except ValueError as e:
            raise RuntimeError(
                f"Invalid PERPLEXITY_RATE_LIMITING_RPS: {os.environ['PERPLEXITY_RATE_LIMITING_RPS']}"
            ) from e

    if "PERPLEXITY_RATE_LIMITING_PERIOD" in os.environ:
        try:
            config_dict["period_seconds"] = float(os.environ["PERPLEXITY_RATE_LIMITING_PERIOD"])
        except ValueError as e:
            raise RuntimeError(
                f"Invalid PERPLEXITY_RATE_LIMITING_PERIOD: {os.environ['PERPLEXITY_RATE_LIMITING_PERIOD']}"
            ) from e

    # Create and return Pydantic model (which validates)
    try:
        return RateLimitConfig(**config_dict)
    except ValueError as e:
        raise RuntimeError(f"Invalid rate limiting configuration: {e}") from e


def get_feature_config_path() -> Path:
    """Get path to feature configuration file.

    Returns:
        Path to config.json in user config directory.
    """
    return get_config_dir() / "config.json"


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


def _validate_feature_config(config: dict[str, Any]) -> None:
    """Validate feature configuration structure.

    Args:
        config: Feature configuration dictionary to validate.

    Raises:
        RuntimeError: If configuration is invalid.
    """
    if not isinstance(config, dict):
        raise RuntimeError("Feature configuration must be a dictionary")

    if "version" not in config:
        raise RuntimeError("Feature configuration missing 'version' field")

    if "features" not in config:
        raise RuntimeError("Feature configuration missing 'features' field")

    features = config["features"]
    if not isinstance(features, dict):
        raise RuntimeError("Feature configuration 'features' must be a dictionary")

    # Validate save_cookies
    if "save_cookies" in features and not isinstance(features["save_cookies"], bool):
        raise RuntimeError("Feature 'save_cookies' must be a boolean")

    # Validate debug_mode
    if "debug_mode" in features and not isinstance(features["debug_mode"], bool):
        raise RuntimeError("Feature 'debug_mode' must be a boolean")


def _ensure_user_feature_config() -> None:
    """Ensure user feature configuration file exists.

    Creates config.json from defaults if it doesn't exist.
    """
    config_path = get_feature_config_path()

    if not config_path.exists():
        defaults = _get_default_feature_config()
        config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(config_path, "w") as f:
            json.dump(defaults, f, indent=2)


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
    # Ensure config file exists
    _ensure_user_feature_config()

    # Start with defaults
    feature_dict = {"save_cookies": False, "debug_mode": False}

    # Try to load user configuration
    config_path = get_feature_config_path()
    try:
        with open(config_path) as f:
            user_config = json.load(f)

        # Merge features from user config
        if "features" in user_config and isinstance(user_config["features"], dict):
            feature_dict.update(user_config["features"])

    except (OSError, json.JSONDecodeError) as e:
        # If user config is invalid, log warning and use defaults
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to load feature config, using defaults: {e}")

    # Apply environment variable overrides
    if "PERPLEXITY_SAVE_COOKIES" in os.environ:
        value = os.environ["PERPLEXITY_SAVE_COOKIES"].lower()
        feature_dict["save_cookies"] = value in ("true", "1", "yes")

    if "PERPLEXITY_DEBUG_MODE" in os.environ:
        value = os.environ["PERPLEXITY_DEBUG_MODE"].lower()
        feature_dict["debug_mode"] = value in ("true", "1", "yes")

    # Create and return Pydantic model (which validates)
    try:
        return FeatureConfig(**feature_dict)
    except ValueError as e:
        raise RuntimeError(f"Invalid feature configuration: {e}") from e


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


def set_feature(key: str, value: bool) -> None:
    """Set a feature configuration value.

    Args:
        key: Feature key ("save_cookies" or "debug_mode").
        value: Boolean value to set.

    Raises:
        RuntimeError: If key is invalid or file cannot be written.
    """
    valid_keys = ["save_cookies", "debug_mode"]
    if key not in valid_keys:
        raise RuntimeError(f"Invalid feature key: {key}. Valid keys: {', '.join(valid_keys)}")

    if not isinstance(value, bool):
        raise RuntimeError(f"Feature value must be boolean, got {type(value).__name__}")

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
    config_path = get_feature_config_path()
    with open(config_path, "w") as f:
        json.dump(config_content, f, indent=2)

    # Clear cache so next call loads fresh config
    clear_feature_config_cache()
