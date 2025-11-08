"""Configuration and path management utilities."""

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
