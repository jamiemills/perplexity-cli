"""Token encryption utilities using system-derived keys.

This module provides symmetric encryption for stored authentication tokens.
The encryption key is derived from system identifiers (hostname, OS user),
making it deterministic and machine-specific.
"""

import base64
import hashlib
import os
import socket

from cryptography.fernet import Fernet

# Salt used for key derivation - consistent across installations
_KEY_DERIVATION_SALT = b"perplexity-cli-token-encryption"


def derive_encryption_key() -> bytes:
    """Derive encryption key from system identifiers.

    Uses machine hostname and OS user to create a deterministic encryption key.
    The same system will always generate the same key, but different systems
    will generate different keys. This ensures tokens cannot be transferred
    between machines.

    Returns:
        bytes: A valid Fernet key (32 bytes, base64-encoded).

    Raises:
        RuntimeError: If unable to determine system identifiers.
    """
    try:
        # Get system identifiers
        hostname = socket.gethostname()
        username = os.getenv("USER") or os.getenv("USERNAME") or "unknown"

        # Create deterministic key from system identifiers
        key_material = f"{hostname}:{username}".encode()
        key_hash = hashlib.sha256(key_material + _KEY_DERIVATION_SALT).digest()

        # Convert to Fernet-compatible key (base64-encoded 32 bytes)
        fernet_key = base64.urlsafe_b64encode(key_hash)
        return fernet_key

    except Exception as e:
        raise RuntimeError(f"Failed to derive encryption key: {e}") from e


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
        key = derive_encryption_key()
        cipher = Fernet(key)
        encrypted = cipher.encrypt(token.encode())
        return base64.urlsafe_b64encode(encrypted).decode()
    except Exception as e:
        raise RuntimeError(f"Failed to encrypt token: {e}") from e


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt a token using the system-derived key.

    Args:
        encrypted_token: Base64-encoded encrypted token.

    Returns:
        str: The decrypted plaintext token.

    Raises:
        RuntimeError: If decryption fails.
    """
    try:
        key = derive_encryption_key()
        cipher = Fernet(key)
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_token.encode())
        decrypted = cipher.decrypt(encrypted_bytes)
        return decrypted.decode()
    except Exception as e:
        raise RuntimeError(
            "Failed to decrypt token. This usually means the token was "
            "encrypted on a different machine or with a different user. "
            "Please re-authenticate with: perplexity-cli auth"
        ) from e
