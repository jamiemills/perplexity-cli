"""Style configuration manager for standardising answer formats."""

import json
import os
from datetime import datetime

from perplexity_cli.utils.config import get_style_path


class StyleManager:
    """Manages user-defined style/prompt configurations."""

    def __init__(self) -> None:
        """Initialize style manager."""
        self.style_path = get_style_path()

    def load_style(self) -> str | None:
        """Load configured style from file.

        Returns:
            Style string if configured, None if not set.

        Raises:
            OSError: If style file exists but cannot be read.
        """
        if not self.style_path.exists():
            return None

        try:
            with open(self.style_path, encoding="utf-8") as f:
                data = json.load(f)
                return data.get("style")
        except (json.JSONDecodeError, KeyError) as e:
            raise OSError(f"Failed to load style from {self.style_path}: {e}") from e

    def save_style(self, style: str) -> None:
        """Save style configuration to file.

        Args:
            style: The style/prompt string to save.

        Raises:
            ValueError: If style is empty or invalid.
            OSError: If file cannot be written.
        """
        if not style or not isinstance(style, str):
            raise ValueError("Style must be a non-empty string")

        if len(style.strip()) == 0:
            raise ValueError("Style cannot be blank or whitespace only")

        # Create config directory if it doesn't exist
        self.style_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "style": style,
            "created_at": datetime.now().isoformat(),
        }

        try:
            with open(self.style_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            # Set file permissions to 0600 (owner read/write only)
            os.chmod(self.style_path, 0o600)
        except OSError as e:
            raise OSError(f"Failed to save style to {self.style_path}: {e}") from e

    def clear_style(self) -> None:
        """Remove style configuration.

        Does nothing if style file doesn't exist (idempotent).
        """
        if self.style_path.exists():
            try:
                self.style_path.unlink()
            except OSError as e:
                raise OSError(f"Failed to delete style file {self.style_path}: {e}") from e

    def validate_style(self, style: str) -> bool:
        """Validate style format.

        Args:
            style: The style string to validate.

        Returns:
            True if valid, False otherwise.
        """
        if not isinstance(style, str):
            return False
        if len(style.strip()) == 0:
            return False
        if len(style) > 10000:  # Reasonable max length
            return False
        return True
