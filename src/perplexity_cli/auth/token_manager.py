"""Token storage and management with secure file permissions and encryption."""

import json
import os
import stat

from perplexity_cli.utils.config import get_token_path
from perplexity_cli.utils.encryption import decrypt_token, encrypt_token


class TokenManager:
    """Manages persistent token storage with encryption and secure file permissions.

    Tokens are encrypted using a system-derived key and stored in
    ~/.config/perplexity-cli/token.json with restrictive file permissions (0600).
    The encryption key is derived from the machine hostname and OS user,
    making it deterministic and machine-specific.
    """

    # File permissions: owner read/write only (0600)
    SECURE_PERMISSIONS = 0o600

    def __init__(self) -> None:
        """Initialise the token manager."""
        self.token_path = get_token_path()

    def save_token(self, token: str) -> None:
        """Save authentication token securely to disk with encryption.

        Encrypts the token using a system-derived key and creates the token file
        with restricted permissions (0600). If the file already exists, it is overwritten.

        Args:
            token: The authentication token to store.

        Raises:
            IOError: If the token cannot be written or permissions cannot be set.
            RuntimeError: If encryption or key derivation fails.
        """
        try:
            # Encrypt the token
            encrypted_token = encrypt_token(token)

            # Write encrypted token to file
            with open(self.token_path, "w") as f:
                json.dump(
                    {
                        "version": 1,
                        "encrypted": True,
                        "token": encrypted_token,
                    },
                    f,
                )

            # Set restrictive permissions
            os.chmod(self.token_path, self.SECURE_PERMISSIONS)

        except OSError as e:
            raise OSError(
                f"Failed to save or set permissions on token file {self.token_path}: {e}"
            ) from e

    def load_token(self) -> str | None:
        """Load the authentication token from disk and decrypt it.

        Verifies file permissions are secure (0600) before reading.
        Decrypts the token using the system-derived key.
        Returns None if token does not exist.

        Returns:
            The decrypted authentication token, or None if not found.

        Raises:
            IOError: If the token exists but cannot be read.
            RuntimeError: If token file has insecure permissions or decryption fails.
        """
        if not self.token_path.exists():
            return None

        # Verify file permissions
        self._verify_permissions()

        try:
            with open(self.token_path) as f:
                data = json.load(f)

            # Check if token is encrypted
            if not data.get("encrypted", False):
                raise RuntimeError(
                    "Token file is not encrypted. Please re-authenticate with: perplexity-cli auth"
                )

            encrypted_token = data.get("token")
            if not encrypted_token:
                raise RuntimeError("Token file is missing encrypted token data")

            # Decrypt the token
            return decrypt_token(encrypted_token)

        except (OSError, json.JSONDecodeError) as e:
            raise OSError(f"Failed to load token from {self.token_path}: {e}") from e

    def clear_token(self) -> None:
        """Delete the stored authentication token.

        Silently succeeds if token does not exist.
        """
        if self.token_path.exists():
            try:
                self.token_path.unlink()
            except OSError as e:
                raise OSError(f"Failed to delete token file: {e}") from e

    def token_exists(self) -> bool:
        """Check if a stored token exists.

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
                f"Token file has insecure permissions: {oct(actual_permissions)}. "
                f"Expected {oct(self.SECURE_PERMISSIONS)}. "
                f"Token file may have been compromised."
            )
