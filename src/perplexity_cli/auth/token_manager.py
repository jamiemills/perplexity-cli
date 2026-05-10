"""Token storage and management with secure file permissions and encryption."""

import json
import os
from datetime import datetime

from perplexity_cli.utils.config import get_config_paths
from perplexity_cli.utils.encryption import decrypt_token, encrypt_token
from perplexity_cli.utils.exceptions import AuthenticationError
from perplexity_cli.utils.file_permissions import verify_secure_permissions
from perplexity_cli.utils.logging import get_logger, redact_mapping_keys, redact_path

TOKEN_AGE_WARNING_DAYS = 30
_MALFORMED_COOKIES_ERROR = "Token file contains malformed cookies data"


class TokenManager:
    """Manages persistent token storage with encryption and secure file permissions.

    Tokens are encrypted using a deterministic system-derived key and stored in
    ~/.config/perplexity-cli/token.json with restrictive file permissions (0600).
    The encryption key is derived from the machine hostname and OS user,
    making it machine-specific but not equivalent to OS-backed secret storage.
    """

    # File permissions: owner read/write only (0600)
    SECURE_PERMISSIONS = 0o600

    def __init__(self) -> None:
        """Initialise the token manager."""
        self.token_path = get_config_paths().token_path
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
            encrypted_token = encrypt_token(token)
            token_record = self._prepare_token_data(encrypted_token, cookies)

            with open(self.token_path, "w", encoding="utf-8") as f:
                json.dump(token_record, f)

            os.chmod(self.token_path, self.SECURE_PERMISSIONS)

            saved_cookies = "cookies" in token_record
            cookie_count = len(cookies) if cookies else 0
            cookie_msg = f" and {cookie_count} cookies" if saved_cookies else ""
            self.logger.info(  # nosemgrep: python-logger-credential-disclosure
                "Token%s saved to %s", cookie_msg, redact_path(self.token_path)
            )

        except OSError as e:
            self.logger.error(  # nosemgrep: python-logger-credential-disclosure
                "Failed to save token: %s", e, exc_info=True
            )
            raise OSError(
                f"Failed to save or set permissions on token file {self.token_path}: {e}"
            ) from e

    def _prepare_token_data(self, encrypted_token: str, cookies: dict[str, str] | None) -> dict:
        """Build the token data structure for persistence.

        Args:
            encrypted_token: The already-encrypted token string.
            cookies: Optional dictionary of browser cookies.

        Returns:
            Dictionary ready to be serialised to JSON.
        """
        token_record = {
            "version": 2,
            "encrypted": True,
            "token": encrypted_token,
            "created_at": datetime.now().isoformat(),
        }
        if cookies:
            from perplexity_cli.utils.config import get_save_cookies_enabled

            if get_save_cookies_enabled():
                encrypted_cookies = encrypt_token(json.dumps(cookies))
                token_record["cookies"] = encrypted_cookies
                self.logger.debug("Saving %s cookies (cookie storage enabled)", len(cookies))
            else:
                self.logger.debug(
                    "Skipping %s cookies (cookie storage disabled in config)", len(cookies)
                )
        return token_record

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

        self._verify_permissions()

        try:
            token_record = self._read_and_validate_token_file()
            self._check_token_age(token_record.get("created_at"))

            token = decrypt_token(token_record["token"])
            version = token_record.get("version", 1)
            cookies = self._decrypt_cookies(token_record, version)

            cookie_msg = f" and {len(cookies)} cookies" if cookies else ""
            self.logger.info(  # nosemgrep: python-logger-credential-disclosure
                "Token%s loaded from %s", cookie_msg, redact_path(self.token_path)
            )

            return (token, cookies)

        except (OSError, json.JSONDecodeError) as e:
            self.logger.error(  # nosemgrep: python-logger-credential-disclosure
                "Failed to load token: %s", e, exc_info=True
            )
            raise OSError(f"Failed to load token from {self.token_path}: {e}") from e

    def _read_and_validate_token_file(self) -> dict:
        """Read and validate the token file structure.

        Returns:
            The parsed and validated token data dictionary.

        Raises:
            AuthenticationError: If the file is not encrypted or missing token data.
        """
        with open(self.token_path, encoding="utf-8") as f:
            token_record = json.load(f)

        if not token_record.get("encrypted", False):
            self.logger.warning("Token file is not encrypted")
            raise AuthenticationError(
                "Token file is not encrypted. Please re-authenticate with: pxcli auth login"
            )

        if not token_record.get("token"):
            self.logger.error("Token file missing encrypted token data")
            raise AuthenticationError("Token file is missing encrypted token data")

        return token_record

    def _check_token_age(self, created_at_str: str | None) -> None:
        """Log a warning if the token is older than the configured threshold.

        Args:
            created_at_str: ISO-format creation timestamp, or None.
        """
        if not created_at_str:
            return
        try:
            created_at = datetime.fromisoformat(created_at_str)
            age_days = (datetime.now() - created_at).days
            if age_days > TOKEN_AGE_WARNING_DAYS:
                self.logger.warning(  # nosemgrep: python-logger-credential-disclosure
                    "Token is %s days old, may be expired", age_days
                )
            else:
                self.logger.debug(  # nosemgrep: python-logger-credential-disclosure
                    "Token age: %s days", age_days
                )
        except (ValueError, TypeError):
            self.logger.debug("Could not parse token creation timestamp")

    def _decrypt_cookies(self, token_record: dict, version: int) -> dict[str, str] | None:
        """Decrypt and validate cookies from the token data.

        Args:
            token_record: The parsed token file data.
            version: The token file format version.

        Returns:
            Dictionary of cookies, or None if not available.

        Raises:
            AuthenticationError: If cookie data is malformed.
        """
        if version != 2 or "cookies" not in token_record:
            if version == 2:
                self.logger.debug("Token is v2 format but no cookies stored")
            else:
                self.logger.debug(  # nosemgrep: python-logger-credential-disclosure
                    "Token is v%s format (no cookies)", version
                )
            return None

        encrypted_cookies = token_record.get("cookies")
        if not encrypted_cookies:
            return None

        cookies = self._parse_and_validate_cookies(decrypt_token(encrypted_cookies))
        self._log_cookie_details(cookies)
        return cookies

    def _parse_and_validate_cookies(self, cookies_json: str) -> dict[str, str]:
        """Parse and validate decrypted cookie JSON.

        Args:
            cookies_json: The decrypted JSON string of cookies.

        Returns:
            Validated dictionary of cookies.

        Raises:
            AuthenticationError: If cookie data is malformed.
        """
        try:
            cookies = json.loads(cookies_json)
        except json.JSONDecodeError as e:
            raise AuthenticationError(_MALFORMED_COOKIES_ERROR) from e

        self._validate_cookie_types(cookies)
        return cookies

    @staticmethod
    def _validate_cookie_types(cookies: object) -> None:
        """Validate that cookies is a dict of str to str.

        Args:
            cookies: The parsed cookies object.

        Raises:
            AuthenticationError: If cookie data is malformed.
        """
        if not isinstance(cookies, dict):
            raise AuthenticationError(_MALFORMED_COOKIES_ERROR)

        if not all(
            isinstance(key, str) and isinstance(value, str) for key, value in cookies.items()
        ):
            raise AuthenticationError(_MALFORMED_COOKIES_ERROR)

    def _log_cookie_details(self, cookies: dict[str, str]) -> None:
        """Log debug details about loaded cookies.

        Args:
            cookies: The validated cookies dictionary.
        """
        cf_cookies = {
            k: v for k, v in cookies.items() if k.startswith("cf") or k.startswith("__cf")
        }
        self.logger.debug(
            "Loaded %s cookies, including %s Cloudflare cookies", len(cookies), len(cf_cookies)
        )
        if cf_cookies:
            self.logger.debug("Cloudflare cookies: %s", redact_mapping_keys(cf_cookies))

    def clear_token(self) -> None:
        """Delete the stored authentication token.

        Silently succeeds if token does not exist.
        """
        if self.token_path.exists():
            try:
                self.token_path.unlink()
                # Audit log: token cleared
                self.logger.info(  # nosemgrep: python-logger-credential-disclosure
                    "Token cleared from %s", redact_path(self.token_path)
                )
            except OSError as e:
                self.logger.error(  # nosemgrep: python-logger-credential-disclosure
                    "Failed to delete token file: %s", e, exc_info=True
                )
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
        verify_secure_permissions(
            self.token_path,
            expected_permissions=self.SECURE_PERMISSIONS,
            file_type="token",
            logger=self.logger,
        )
