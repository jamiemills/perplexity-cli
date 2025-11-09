"""GitLab token storage and management with secure file permissions."""

import json
import os
import stat
from pathlib import Path


class GitLabTokenManager:
    """Manages persistent GitLab token storage with secure file permissions.

    Tokens are stored in ~/.config/perplexity-cli/gitlab_token.json with
    restrictive file permissions (0600) so only the user can read them.
    """

    # File permissions: owner read/write only (0600)
    SECURE_PERMISSIONS = 0o600

    def __init__(self, gitlab_url: str = "https://gitlab.com") -> None:
        """Initialize the GitLab token manager.

        Args:
            gitlab_url: GitLab instance URL (default: https://gitlab.com).
        """
        self.gitlab_url = gitlab_url
        self.token_path = self._get_token_path()

    def _get_token_path(self) -> Path:
        """Get the path to the GitLab token file.

        Returns:
            Path to the token file.
        """
        # Use same config directory as Perplexity CLI
        config_dir = Path.home() / ".config" / "perplexity-cli"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "gitlab_token.json"

    def save_token(self, token: str) -> None:
        """Save GitLab authentication token securely to disk.

        Creates the token file with restricted permissions (0600).
        If the file already exists, it is overwritten.

        Args:
            token: The GitLab personal access token to store.

        Raises:
            IOError: If the token cannot be written or permissions cannot be set.
        """
        try:
            # Write token to file
            with open(self.token_path, "w") as f:
                json.dump(
                    {"token": token, "gitlab_url": self.gitlab_url},
                    f,
                )

            # Set restrictive permissions
            os.chmod(self.token_path, self.SECURE_PERMISSIONS)

        except OSError as e:
            raise OSError(
                f"Failed to save or set permissions on GitLab token file {self.token_path}: {e}"
            ) from e

    def load_token(self) -> str | None:
        """Load the GitLab authentication token from disk.

        Verifies file permissions are secure (0600) before reading.
        Returns None if token does not exist.

        Returns:
            The stored GitLab authentication token, or None if not found.

        Raises:
            IOError: If the token exists but cannot be read.
            RuntimeError: If token file has insecure permissions.
        """
        if not self.token_path.exists():
            return None

        # Verify file permissions
        self._verify_permissions()

        try:
            with open(self.token_path) as f:
                data = json.load(f)
                return data.get("token")
        except (OSError, json.JSONDecodeError) as e:
            raise OSError(f"Failed to load GitLab token from {self.token_path}: {e}") from e

    def load_gitlab_url(self) -> str:
        """Load the GitLab URL from disk.

        Returns:
            The stored GitLab URL, or default if not found.
        """
        if not self.token_path.exists():
            return "https://gitlab.com"

        try:
            with open(self.token_path) as f:
                data = json.load(f)
                return data.get("gitlab_url", "https://gitlab.com")
        except (OSError, json.JSONDecodeError):
            return "https://gitlab.com"

    def clear_token(self) -> None:
        """Delete the stored GitLab authentication token.

        Silently succeeds if token does not exist.
        """
        if self.token_path.exists():
            try:
                self.token_path.unlink()
            except OSError as e:
                raise OSError(f"Failed to delete GitLab token file: {e}") from e

    def token_exists(self) -> bool:
        """Check if a stored GitLab token exists.

        Returns:
            True if token file exists, False otherwise.
        """
        return self.token_path.exists()

    def _verify_permissions(self) -> None:
        """Verify that token file has secure permissions (0600).

        Raises:
            RuntimeError: If file permissions are not 0600.
        """
        file_stat = self.token_path.stat()
        actual_permissions = stat.S_IMODE(file_stat.st_mode)

        if actual_permissions != self.SECURE_PERMISSIONS:
            raise RuntimeError(
                f"GitLab token file has insecure permissions: {oct(actual_permissions)}. "
                f"Expected {oct(self.SECURE_PERMISSIONS)}. "
                f"Token file may have been compromised."
            )
