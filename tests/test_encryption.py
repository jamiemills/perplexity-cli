"""Tests for token encryption utilities."""

import os
import socket
from unittest import mock

import pytest

from perplexity_cli.utils.encryption import (
    decrypt_token,
    derive_encryption_key,
    encrypt_token,
)


class TestKeyDerivation:
    """Test encryption key derivation."""

    def test_derive_key_is_deterministic(self) -> None:
        """Test that key derivation produces same key for same system."""
        key1 = derive_encryption_key()
        key2 = derive_encryption_key()
        assert key1 == key2

    def test_derive_key_returns_bytes(self) -> None:
        """Test that derived key is bytes."""
        key = derive_encryption_key()
        assert isinstance(key, bytes)

    def test_derive_key_is_valid_fernet_key(self) -> None:
        """Test that derived key is valid for Fernet."""
        from cryptography.fernet import Fernet

        key = derive_encryption_key()
        # This will raise InvalidToken if key is invalid
        Fernet(key)

    def test_different_hostname_produces_different_key(self) -> None:
        """Test that different hostnames produce different keys."""
        with mock.patch("socket.gethostname", return_value="host1"):
            key1 = derive_encryption_key()

        with mock.patch("socket.gethostname", return_value="host2"):
            key2 = derive_encryption_key()

        assert key1 != key2

    def test_different_username_produces_different_key(self) -> None:
        """Test that different usernames produce different keys."""
        with mock.patch.dict(os.environ, {"USER": "user1"}):
            key1 = derive_encryption_key()

        with mock.patch.dict(os.environ, {"USER": "user2"}):
            key2 = derive_encryption_key()

        assert key1 != key2


class TestTokenEncryption:
    """Test token encryption and decryption."""

    def test_encrypt_token_returns_string(self) -> None:
        """Test that encryption returns a string."""
        encrypted = encrypt_token("test_token")
        assert isinstance(encrypted, str)

    def test_encrypt_decrypt_roundtrip(self) -> None:
        """Test encryption followed by decryption recovers original token."""
        original_token = "test_authentication_token_12345"
        encrypted = encrypt_token(original_token)
        decrypted = decrypt_token(encrypted)
        assert decrypted == original_token

    def test_encrypt_different_tokens_produce_different_ciphertext(self) -> None:
        """Test that different tokens produce different ciphertexts."""
        encrypted1 = encrypt_token("token1")
        encrypted2 = encrypt_token("token2")
        assert encrypted1 != encrypted2

    def test_encrypt_same_token_produces_different_ciphertext(self) -> None:
        """Test that encryption is non-deterministic (uses IV)."""
        token = "same_token"
        encrypted1 = encrypt_token(token)
        encrypted2 = encrypt_token(token)
        # Should be different because Fernet uses IV
        assert encrypted1 != encrypted2

    def test_decrypt_same_token_consistently(self) -> None:
        """Test that decryption of different ciphertexts recovers same token."""
        token = "consistent_token"
        encrypted1 = encrypt_token(token)
        encrypted2 = encrypt_token(token)
        assert decrypt_token(encrypted1) == token
        assert decrypt_token(encrypted2) == token

    def test_encrypt_empty_token(self) -> None:
        """Test encryption of empty token."""
        encrypted = encrypt_token("")
        decrypted = decrypt_token(encrypted)
        assert decrypted == ""

    def test_encrypt_long_token(self) -> None:
        """Test encryption of very long token."""
        long_token = "x" * 10000
        encrypted = encrypt_token(long_token)
        decrypted = decrypt_token(encrypted)
        assert decrypted == long_token

    def test_encrypt_token_with_special_characters(self) -> None:
        """Test encryption of token with special characters."""
        special_token = "token!@#$%^&*()_+-=[]{}|;:',.<>?/~`\n\t"
        encrypted = encrypt_token(special_token)
        decrypted = decrypt_token(encrypted)
        assert decrypted == special_token

    def test_encrypt_json_token(self) -> None:
        """Test encryption of JSON-formatted token."""
        import json

        json_token = json.dumps(
            {
                "sub": "user123",
                "iss": "https://perplexity.ai",
                "aud": "api",
                "exp": 1234567890,
            }
        )
        encrypted = encrypt_token(json_token)
        decrypted = decrypt_token(encrypted)
        assert decrypted == json_token


class TestDecryptionErrors:
    """Test error handling in decryption."""

    def test_decrypt_invalid_base64_raises_error(self) -> None:
        """Test that invalid base64 raises error."""
        with pytest.raises(RuntimeError, match="Failed to decrypt token"):
            decrypt_token("not_valid_base64!!!!")

    def test_decrypt_wrong_data_raises_error(self) -> None:
        """Test that decrypting wrong data raises error."""
        import base64

        wrong_data = base64.urlsafe_b64encode(b"wrong_data").decode("utf-8")
        with pytest.raises(RuntimeError, match="Failed to decrypt token"):
            decrypt_token(wrong_data)

    def test_decrypt_error_message_is_helpful(self) -> None:
        """Test that decryption error message is helpful."""
        with pytest.raises(RuntimeError) as exc_info:
            decrypt_token("invalid_data")
        error_message = str(exc_info.value)
        assert "different machine" in error_message or "Failed to decrypt" in error_message
