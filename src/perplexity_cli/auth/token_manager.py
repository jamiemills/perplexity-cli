"""Token storage and management with secure file permissions and encryption."""

import json
import os
import stat
from datetime import datetime

from perplexity_cli.utils.config import get_token_path
from perplexity_cli.utils.encryption import decrypt_token, encrypt_token
from perplexity_cli.utils.logging import get_logger


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
        self.logger = get_logger()

    def save_token(self, token: str, cookies: dict[str, str] | None = None) -> None:
        """Save authentication token and cookies securely to disk with encryption.

        Encrypts the token and cookies using a system-derived key and creates the token file
        with restricted permissions (0600). If the file already exists, it is overwritten.

        Args:
            token: The authentication token to store.
            cookies: Optional dictionary of browser cookies to store.

        Raises:
            IOError: If the token cannot be written or permissions cannot be set.
            RuntimeError: If encryption or key derivation fails.
        """
        try:
            # Encrypt the token
            encrypted_token = encrypt_token(token)

            # Prepare data structure
            data = {
                "version": 2,
                "encrypted": True,
                "token": encrypted_token,
                "created_at": datetime.now().isoformat(),
            }

            # Encrypt and store cookies if provided
            if cookies:
                encrypted_cookies = encrypt_token(json.dumps(cookies))
                data["cookies"] = encrypted_cookies

            # Write encrypted data to file
            with open(self.token_path, "w") as f:
                json.dump(data, f)

            # Set restrictive permissions
            os.chmod(self.token_path, self.SECURE_PERMISSIONS)

            # Audit log
            cookie_msg = f" and {len(cookies)} cookies" if cookies else ""
            self.logger.info(f"Token{cookie_msg} saved to {self.token_path}")

        except OSError as e:
            self.logger.error(f"Failed to save token: {e}", exc_info=True)
            raise OSError(
                f"Failed to save or set permissions on token file {self.token_path}: {e}"
            ) from e

    def load_token(self) -> tuple[str | None, dict[str, str] | None]:
        """Load the authentication token and cookies from disk and decrypt them.

        Verifies file permissions are secure (0600) before reading.
        Decrypts the token and cookies using the system-derived key.
        Returns (None, None) if token does not exist.
        Handles both v1 (token only) and v2 (token + cookies) formats.

        Returns:
            Tuple of (token, cookies) where:
                - token: The decrypted authentication token, or None if not found
                - cookies: Dictionary of cookies {name: value}, or None if not available

        Raises:
            IOError: If the token exists but cannot be read.
            RuntimeError: If token file has insecure permissions or decryption fails.
        """
        if not self.token_path.exists():
            return (None, None)

        # Verify file permissions
        self._verify_permissions()

        try:
            with open(self.token_path) as f:
                data = json.load(f)

            # Check if token is encrypted
            if not data.get("encrypted", False):
                self.logger.warning("Token file is not encrypted")
                raise RuntimeError(
                    "Token file is not encrypted. Please re-authenticate with: pxcli auth"
                )

            encrypted_token = data.get("token")
            if not encrypted_token:
                self.logger.error("Token file missing encrypted token data")
                raise RuntimeError("Token file is missing encrypted token data")

            # Check version for backward compatibility
            version = data.get("version", 1)

            # Check token age if created_at is present
            created_at_str = data.get("created_at")
            if created_at_str:
                try:
                    created_at = datetime.fromisoformat(created_at_str)
                    age_days = (datetime.now() - created_at).days
                    if age_days > 30:
                        self.logger.warning(f"Token is {age_days} days old, may be expired")
                    else:
                        self.logger.debug(f"Token age: {age_days} days")
                except (ValueError, TypeError):
                    pass

            # Decrypt the token
            token = decrypt_token(encrypted_token)

            # Decrypt cookies if v2 format
            cookies = None
            if version == 2 and "cookies" in data:
                encrypted_cookies = data.get("cookies")
                if encrypted_cookies:
                    cookies_json = decrypt_token(encrypted_cookies)
                    cookies = json.loads(cookies_json)

            # Audit log
            cookie_msg = f" and {len(cookies)} cookies" if cookies else ""
            self.logger.info(f"Token{cookie_msg} loaded from {self.token_path}")

            return (token, cookies)

        except (OSError, json.JSONDecodeError) as e:
            self.logger.error(f"Failed to load token: {e}", exc_info=True)
            raise OSError(f"Failed to load token from {self.token_path}: {e}") from e

    def clear_token(self) -> None:
        """Delete the stored authentication token.

        Silently succeeds if token does not exist.
        """
        if self.token_path.exists():
            try:
                self.token_path.unlink()
                # Audit log: token cleared
                self.logger.info(f"Token cleared from {self.token_path}")
            except OSError as e:
                self.logger.error(f"Failed to delete token file: {e}", exc_info=True)
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
            self.logger.error(
                f"Token file has insecure permissions: {oct(actual_permissions)} "
                f"(expected {oct(self.SECURE_PERMISSIONS)})"
            )
            raise RuntimeError(
                f"Token file has insecure permissions: {oct(actual_permissions)}. "
                f"Expected {oct(self.SECURE_PERMISSIONS)}. "
                f"Token file may have been compromised."
            )
