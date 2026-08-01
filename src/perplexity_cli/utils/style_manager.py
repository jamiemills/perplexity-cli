"""Style configuration manager for standardising answer formats."""

import json
from datetime import datetime

from perplexity_cli.utils.atomic_write import atomic_write_text
from perplexity_cli.utils.config import get_config_paths

MAX_STYLE_LENGTH = 10_000


class StyleManager:
    """Manages user-defined style/prompt configurations."""

    def __init__(self) -> None:
        """Initialise style manager."""
        self.style_path = get_config_paths().style_path

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
                style_config = json.load(f)
                return style_config.get("style")
        except (json.JSONDecodeError, KeyError) as e:
            msg = f"Failed to load style from {self.style_path}: {e}"
            raise OSError(msg) from e

    def _validate_style_input(self, style: str) -> None:
        """Validate that a style string meets requirements.

        Args:
            style: The style string to validate.

        Raises:
            ValueError: If style is empty, blank, or exceeds maximum length.
        """
        if type(style) is not str or not style:
            msg = "Style must be a non-empty string"
            raise ValueError(msg)
        if not style.strip():
            msg = "Style cannot be blank or whitespace only"
            raise ValueError(msg)
        if len(style) > MAX_STYLE_LENGTH:
            msg = (
                f"Style exceeds maximum length of {MAX_STYLE_LENGTH} characters "
                f"(current length: {len(style)} characters)"
            )
            raise ValueError(msg)

    def save_style(self, style: str) -> None:
        """Save style configuration to file.

        Args:
            style: The style/prompt string to save.

        Raises:
            ValueError: If style is empty, invalid, or exceeds maximum length.
            OSError: If file cannot be written.
        """
        self._validate_style_input(style)

        self.style_path.parent.mkdir(parents=True, exist_ok=True)

        style_config = {
            "style": style,
            "created_at": datetime.now().isoformat(),
        }

        try:
            atomic_write_text(self.style_path, json.dumps(style_config, indent=2), mode=0o600)
        except OSError as e:
            msg = f"Failed to save style to {self.style_path}: {e}"
            raise OSError(msg) from e

    def clear_style(self) -> None:
        """Remove style configuration.

        Does nothing if style file doesn't exist (idempotent).
        """
        if self.style_path.exists():
            try:
                self.style_path.unlink()
            except OSError as e:
                msg = f"Failed to delete style file {self.style_path}: {e}"
                raise OSError(msg) from e

    def validate_style(self, style: str) -> bool:
        """Validate style format.

        Args:
            style: The style string to validate.

        Returns:
            True if valid, False otherwise.
        """
        if type(style) is not str:
            return False
        if not style.strip():
            return False
        return not len(style) > MAX_STYLE_LENGTH
