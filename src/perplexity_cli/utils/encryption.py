"""Token encryption utilities using deterministic machine-derived keys.

This module provides symmetric encryption for stored authentication tokens.
The encryption key is derived from system identifiers (hostname, OS user),
making it deterministic and machine-specific. This is best treated as
machine-bound obfuscation rather than strong OS-backed secret storage.
"""

import base64
import hashlib
import os
import secrets
import socket
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from perplexity_cli.utils.exceptions import AuthenticationError, ConfigurationError

# Salt used for key derivation - consistent across installations
_KEY_DERIVATION_SALT = b"perplexity-cli-token-encryption"
_ENCRYPTED_TOKEN_VERSION_PREFIX = b"v2:"
_PER_MESSAGE_SALT_BYTES = 16


def _build_key_material() -> bytes:
    """Build deterministic machine-specific key material."""
    hostname = socket.gethostname()
    username = os.getenv("USER") or os.getenv("USERNAME") or "unknown"
    return f"{hostname}:{username}".encode()


def _derive_fernet_key(salt: bytes) -> bytes:
    """Derive a Fernet-compatible key from machine key material and salt."""
    key_hash = hashlib.pbkdf2_hmac("sha256", _build_key_material(), salt, iterations=100000)
    return base64.urlsafe_b64encode(key_hash)


def _derive_encryption_key_legacy() -> bytes:
    """Legacy key derivation using SHA-256 (deprecated, for backward compatibility).

    This method is kept for backward compatibility with tokens encrypted
    using the original SHA-256 key derivation. New tokens use PBKDF2.

    Returns:
        bytes: A Fernet-compatible key derived using SHA-256.

    Raises:
        RuntimeError: If unable to determine system identifiers.
    """
    try:
        # Create deterministic key from system identifiers (legacy SHA-256)
        key_hash = hashlib.sha256(_build_key_material() + _KEY_DERIVATION_SALT).digest()

        # Convert to Fernet-compatible key (base64-encoded 32 bytes)
        fernet_key = base64.urlsafe_b64encode(key_hash)
        return fernet_key

    except OSError as e:
        raise ConfigurationError(f"Failed to derive encryption key (legacy): {e}") from e


@lru_cache(maxsize=1)
def derive_encryption_key() -> bytes:
    """Derive encryption key from system identifiers.

    Uses machine hostname and OS user to create a deterministic encryption key.
    The same system will always generate the same key, but different systems
    will generate different keys. This reduces portability of copied files,
    but it does not protect secrets from other local processes or users that
    can already read the encrypted files on the same machine.

    Key derivation uses PBKDF2-HMAC with SHA256 for improved security.

    Returns:
        bytes: A valid Fernet key (32 bytes, base64-encoded).

    Raises:
        RuntimeError: If unable to determine system identifiers.
    """
    try:
        # Deterministic salt required for at-rest token decryption;
        # new encryptions use per-message random salt.
        return _derive_fernet_key(_KEY_DERIVATION_SALT)  # NOSONAR

    except OSError as e:
        raise ConfigurationError(f"Failed to derive encryption key: {e}") from e


def encrypt_token(token: str) -> str:
    """Encrypt a token using the system-derived key.

    Args:
        token: The plaintext token to encrypt.

    Returns:
        str: Base64-encoded encrypted token.

    Raises:
        RuntimeError: If encryption fails.
    """
    try:
        salt = secrets.token_bytes(_PER_MESSAGE_SALT_BYTES)
        key = _derive_fernet_key(salt)
        cipher = Fernet(key)
        encrypted = cipher.encrypt(token.encode())
        payload = _ENCRYPTED_TOKEN_VERSION_PREFIX + salt + encrypted
        return base64.urlsafe_b64encode(payload).decode()
    except (ConfigurationError, ValueError, TypeError) as e:
        raise ConfigurationError(f"Failed to encrypt token: {e}") from e


def _decrypt_with_current_format(decoded_payload: bytes) -> str:
    """Decrypt a token stored in the current format with a per-message salt."""
    if not decoded_payload.startswith(_ENCRYPTED_TOKEN_VERSION_PREFIX):
        raise ValueError("Encrypted token is not in the current format")

    payload = decoded_payload[len(_ENCRYPTED_TOKEN_VERSION_PREFIX) :]
    if len(payload) <= _PER_MESSAGE_SALT_BYTES:
        raise ValueError("Encrypted token payload is truncated")

    salt = payload[:_PER_MESSAGE_SALT_BYTES]
    encrypted_bytes = payload[_PER_MESSAGE_SALT_BYTES:]
    cipher = Fernet(_derive_fernet_key(salt))
    decrypted = cipher.decrypt(encrypted_bytes)
    return decrypted.decode()


def _decrypt_with_legacy_pbkdf2(encrypted_token: str) -> str:
    """Decrypt a token stored with the legacy fixed-salt PBKDF2 format."""
    cipher = Fernet(derive_encryption_key())
    encrypted_bytes = base64.urlsafe_b64decode(encrypted_token.encode())
    decrypted = cipher.decrypt(encrypted_bytes)
    return decrypted.decode()


def _decrypt_with_legacy_sha256(encrypted_token: str) -> str:
    """Decrypt a token stored with the legacy SHA-256-derived format."""
    cipher = Fernet(_derive_encryption_key_legacy())
    encrypted_bytes = base64.urlsafe_b64decode(encrypted_token.encode())
    decrypted = cipher.decrypt(encrypted_bytes)
    return decrypted.decode()


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt a token using the system-derived key.

    Supports backward compatibility with tokens encrypted using the old SHA-256
    key derivation method. Will first try PBKDF2, then fall back to SHA-256
    if PBKDF2 fails.

    Args:
        encrypted_token: Base64-encoded encrypted token.

    Returns:
        str: The decrypted plaintext token.

    Raises:
        RuntimeError: If decryption fails with both methods.
    """
    try:
        decoded_payload = base64.urlsafe_b64decode(encrypted_token.encode())
        return _decrypt_with_current_format(decoded_payload)
    except (ConfigurationError, ValueError, TypeError, InvalidToken):
        try:
            return _decrypt_with_legacy_pbkdf2(encrypted_token)
        except (ConfigurationError, ValueError, TypeError, InvalidToken):
            try:
                return _decrypt_with_legacy_sha256(encrypted_token)
            except (ConfigurationError, ValueError, TypeError, InvalidToken) as e:
                raise AuthenticationError(
                    "Failed to decrypt token. This usually means the token was "
                    "encrypted on a different machine or with a different user. "
                    "Please re-authenticate with: perplexity-cli auth"
                ) from e
