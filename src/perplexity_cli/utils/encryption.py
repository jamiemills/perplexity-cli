"""Token encryption utilities using deterministic machine-derived keys.

This module provides symmetric encryption for stored authentication tokens.
The encryption key is derived from system identifiers (hostname, OS user),
making it deterministic and machine-specific. This is best treated as
machine-bound obfuscation rather than strong OS-backed secret storage.
"""

from __future__ import annotations

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

_DECRYPT_FAILURE_HINT = (
    "This usually means the token was encrypted on a different machine or "
    "with a different user. Please re-authenticate with: perplexity-cli auth"
)


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
        return base64.urlsafe_b64encode(key_hash)

    except OSError as e:
        msg = f"Failed to derive encryption key (legacy): {e}"
        raise ConfigurationError(msg) from e


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
        msg = f"Failed to derive encryption key: {e}"
        raise ConfigurationError(msg) from e


def encrypt_token(token: str) -> str:
    """Encrypt a token using the system-derived key.

    Always produces a versioned payload with a fresh random per-message salt.

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
        msg = f"Failed to encrypt token: {e}"
        raise ConfigurationError(msg) from e


def _decode_strict(encrypted_token: str) -> bytes:
    """Strictly decode the outer base64url payload exactly once.

    Rejects any character outside the base64url alphabet and any incorrect
    padding so malformed payloads fail fast instead of silently downgrading.

    Args:
        encrypted_token: The base64url-encoded encrypted token.

    Returns:
        The decoded payload bytes.

    Raises:
        AuthenticationError: If the token is not valid base64url.
    """
    try:
        return base64.b64decode(encrypted_token.encode("ascii"), altchars=b"-_", validate=True)
    except ValueError as e:
        msg = f"Failed to decrypt token: payload is not valid base64. {_DECRYPT_FAILURE_HINT}"
        raise AuthenticationError(msg) from e


def _decrypt_with_current_format(decoded_payload: bytes) -> str:
    """Decrypt a token stored in the current format with a per-message salt.

    Args:
        decoded_payload: The decoded outer payload, expected to start with the
            v2 version prefix.

    Returns:
        The decrypted plaintext token.

    Raises:
        ValueError: If the payload does not carry the version prefix or is
            truncated.
        InvalidToken: If the payload fails to authenticate with the derived key.
    """
    if not decoded_payload.startswith(_ENCRYPTED_TOKEN_VERSION_PREFIX):
        msg = "Encrypted token is not in the current format"
        raise ValueError(msg)

    payload = decoded_payload[len(_ENCRYPTED_TOKEN_VERSION_PREFIX) :]
    if len(payload) <= _PER_MESSAGE_SALT_BYTES:
        msg = "Encrypted token payload is truncated"
        raise ValueError(msg)

    salt = payload[:_PER_MESSAGE_SALT_BYTES]
    encrypted_bytes = payload[_PER_MESSAGE_SALT_BYTES:]
    cipher = Fernet(_derive_fernet_key(salt))
    decrypted = cipher.decrypt(encrypted_bytes)
    return decrypted.decode()


def _decrypt_with_legacy_pbkdf2(decoded_payload: bytes) -> str:
    """Decrypt a token stored with the legacy fixed-salt PBKDF2 format.

    Args:
        decoded_payload: The decoded Fernet token bytes.

    Returns:
        The decrypted plaintext token.

    Raises:
        InvalidToken: If the token does not decrypt with the legacy key.
        ConfigurationError: If key derivation fails.
    """
    cipher = Fernet(derive_encryption_key())
    decrypted = cipher.decrypt(decoded_payload)
    return decrypted.decode()


def _decrypt_with_legacy_sha256(decoded_payload: bytes) -> str:
    """Decrypt a token stored with the legacy SHA-256-derived format.

    Args:
        decoded_payload: The decoded Fernet token bytes.

    Returns:
        The decrypted plaintext token.

    Raises:
        InvalidToken: If the token does not decrypt with the legacy key.
        ConfigurationError: If key derivation fails.
    """
    cipher = Fernet(_derive_encryption_key_legacy())
    decrypted = cipher.decrypt(decoded_payload)
    return decrypted.decode()


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt a token using the system-derived key.

    A payload starting with the ``v2:`` prefix is decrypted with the current
    per-message-salt format only; any v2 failure raises ``AuthenticationError``
    with no legacy fallback.  Unversioned payloads are tried with the fixed-salt
    PBKDF2 reader first, then the legacy SHA-256 reader, in that order.

    Read-only compatibility: no migration-on-read and no silent rewrite happens
    here; ``encrypt_token`` always emits fresh random-salt v2 payloads.

    Args:
        encrypted_token: Base64url-encoded encrypted token.

    Returns:
        str: The decrypted plaintext token.

    Raises:
        AuthenticationError: If decryption fails in every applicable format.
    """
    decoded_payload = _decode_strict(encrypted_token)
    if decoded_payload.startswith(_ENCRYPTED_TOKEN_VERSION_PREFIX):
        try:
            return _decrypt_with_current_format(decoded_payload)
        except (InvalidToken, ValueError, TypeError, ConfigurationError, OSError) as e:
            msg = f"Failed to decrypt token in the current format. {_DECRYPT_FAILURE_HINT}"
            raise AuthenticationError(msg) from e
    try:
        return _decrypt_with_legacy_pbkdf2(decoded_payload)
    except (ConfigurationError, ValueError, TypeError, InvalidToken):
        try:
            return _decrypt_with_legacy_sha256(decoded_payload)
        except (ConfigurationError, ValueError, TypeError, InvalidToken) as e:
            msg = f"Failed to decrypt token. {_DECRYPT_FAILURE_HINT}"
            raise AuthenticationError(msg) from e
