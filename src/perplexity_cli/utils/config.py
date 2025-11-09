"""Configuration and path management utilities."""

import json
import os
from pathlib import Path


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
        with open(package_config, "r") as f:
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


_urls_cache = None


def get_urls() -> dict:
    """Load and cache the URLs configuration.

    Returns the user configuration if it exists, otherwise creates it from defaults.

    Returns:
        dict: The URLs configuration containing perplexity base_url and query_endpoint.

    Raises:
        RuntimeError: If configuration cannot be loaded or is invalid.
    """
    global _urls_cache

    if _urls_cache is not None:
        return _urls_cache

    _ensure_user_urls_config()

    urls_path = get_urls_path()
    try:
        with open(urls_path, "r") as f:
            _urls_cache = json.load(f)
        return _urls_cache
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Failed to load URLs configuration: {e}") from e


def get_perplexity_base_url() -> str:
    """Get the Perplexity base URL from configuration.

    Returns:
        str: The Perplexity base URL (e.g., https://www.perplexity.ai).

    Raises:
        RuntimeError: If configuration is invalid or missing required fields.
    """
    urls = get_urls()
    try:
        return urls["perplexity"]["base_url"]
    except (KeyError, TypeError) as e:
        raise RuntimeError(
            "Invalid URLs configuration: missing perplexity.base_url"
        ) from e


def get_query_endpoint() -> str:
    """Get the Perplexity query endpoint URL from configuration.

    Returns:
        str: The Perplexity query endpoint URL.

    Raises:
        RuntimeError: If configuration is invalid or missing required fields.
    """
    urls = get_urls()
    try:
        return urls["perplexity"]["query_endpoint"]
    except (KeyError, TypeError) as e:
        raise RuntimeError(
            "Invalid URLs configuration: missing perplexity.query_endpoint"
        ) from e
