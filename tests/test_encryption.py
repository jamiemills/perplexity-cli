"""Tests for token encryption utilities."""

import base64
import hashlib
import os
from unittest import mock

import pytest
from cryptography.fernet import Fernet

from perplexity_cli.utils import encryption as encryption_module
from perplexity_cli.utils.encryption import (
    decrypt_token,
    derive_encryption_key,
    encrypt_token,
)
from perplexity_cli.utils.exceptions import AuthenticationError

# ---------------------------------------------------------------------------
# Synthetic NON-secret legacy fixtures.  These are generated locally from the
# fixed constants below (never real credentials) so the legacy readers' format
# is locked without shipping any secret material.
# ---------------------------------------------------------------------------

FIXTURE_KEY_MATERIAL = b"fixture-host:fixture-user"
FIXTURE_PLAINTEXT = "synthetic-test-token"
FIXTURE_SALT = b"perplexity-cli-token-encryption"
FIXTURE_PBKDF2_ITERATIONS = 100000


def _make_pbkdf2_legacy_fixture() -> str:
    """Generate a fixed-salt PBKDF2 legacy token from the fixture constants."""
    key = hashlib.pbkdf2_hmac(
        "sha256", FIXTURE_KEY_MATERIAL, FIXTURE_SALT, FIXTURE_PBKDF2_ITERATIONS
    )
    fernet_key = base64.urlsafe_b64encode(key)
    token = Fernet(fernet_key).encrypt(FIXTURE_PLAINTEXT.encode())
    return base64.urlsafe_b64encode(token).decode()


def _make_sha256_legacy_fixture() -> str:
    """Generate a legacy SHA-256 token from the fixture constants."""
    key = hashlib.sha256(FIXTURE_KEY_MATERIAL + FIXTURE_SALT).digest()
    fernet_key = base64.urlsafe_b64encode(key)
    token = Fernet(fernet_key).encrypt(FIXTURE_PLAINTEXT.encode())
    return base64.urlsafe_b64encode(token).decode()


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
        derive_encryption_key.cache_clear()
        with mock.patch("socket.gethostname", return_value="host1"):
            key1 = derive_encryption_key()

        derive_encryption_key.cache_clear()
        with mock.patch("socket.gethostname", return_value="host2"):
            key2 = derive_encryption_key()

        derive_encryption_key.cache_clear()
        assert key1 != key2

    def test_different_username_produces_different_key(self) -> None:
        """Test that different usernames produce different keys."""
        derive_encryption_key.cache_clear()
        with mock.patch.dict(os.environ, {"USER": "user1"}):
            key1 = derive_encryption_key()

        derive_encryption_key.cache_clear()
        with mock.patch.dict(os.environ, {"USER": "user2"}):
            key2 = derive_encryption_key()

        derive_encryption_key.cache_clear()
        assert key1 != key2

    def test_derive_encryption_key_is_cached(self) -> None:
        """Test that derive_encryption_key results are cached across calls."""
        derive_encryption_key.cache_clear()

    def test_derive_key_failure_raises_runtime_error(self) -> None:
        """Test socket failures are surfaced as RuntimeError."""
        derive_encryption_key.cache_clear()
        with mock.patch("socket.gethostname", side_effect=OSError("no hostname")):
            with pytest.raises(RuntimeError, match="Failed to derive encryption key"):
                derive_encryption_key()
        derive_encryption_key.cache_clear()
        with mock.patch("perplexity_cli.utils.encryption.socket.gethostname") as mock_hostname:
            mock_hostname.return_value = "cached-host"
            key1 = derive_encryption_key()
            key2 = derive_encryption_key()

            assert key1 == key2
            mock_hostname.assert_called_once()

        derive_encryption_key.cache_clear()


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


class TestV2Format:
    """Versioned per-message-salt format behaviour."""

    def test_encrypt_always_produces_random_salt_v2(self) -> None:
        """Every encrypted token carries the v2 prefix."""
        encrypted = encrypt_token("some-token")
        decoded = base64.b64decode(encrypted.encode("ascii"), altchars=b"-_", validate=True)
        assert decoded.startswith(b"v2:")

    def test_encrypt_same_token_produces_different_salt(self) -> None:
        """Two encryptions of the same token carry different random salts."""
        decoded1 = base64.b64decode(
            encrypt_token("same-token").encode("ascii"), altchars=b"-_", validate=True
        )
        decoded2 = base64.b64decode(
            encrypt_token("same-token").encode("ascii"), altchars=b"-_", validate=True
        )
        assert decoded1[len(b"v2:") :][:16] != decoded2[len(b"v2:") :][:16]

    def test_v2_round_trip(self) -> None:
        """A v2 payload round-trips through decrypt_token."""
        token = "roundtrip-token"
        assert decrypt_token(encrypt_token(token)) == token

    def test_malformed_v2_never_touches_legacy(self, monkeypatch) -> None:
        """A tampered v2 payload must not silently downgrade to legacy readers."""

        def fail_if_called(*args, **kwargs):
            raise AssertionError("legacy decoder must not be called")

        monkeypatch.setattr(encryption_module, "_decrypt_with_legacy_pbkdf2", fail_if_called)
        monkeypatch.setattr(encryption_module, "_decrypt_with_legacy_sha256", fail_if_called)

        truncated = base64.urlsafe_b64encode(b"v2:" + b"\x00" * 5).decode()
        with pytest.raises(AuthenticationError, match="Failed to decrypt token"):
            decrypt_token(truncated)

        garbage = base64.urlsafe_b64encode(
            b"v2:" + b"\x00" * 16 + b"not-a-valid-fernet-payload"
        ).decode()
        with pytest.raises(AuthenticationError, match="Failed to decrypt token"):
            decrypt_token(garbage)

    def test_malformed_v2_message_does_not_leak_payload(self) -> None:
        """The v2 failure message never contains ciphertext bytes."""
        garbage = base64.urlsafe_b64encode(
            b"v2:" + b"\x00" * 16 + b"supersecretciphertext-bytes"
        ).decode()
        with pytest.raises(AuthenticationError) as exc_info:
            decrypt_token(garbage)
        assert garbage not in str(exc_info.value)
        assert "supersecretciphertext" not in str(exc_info.value)


class TestLegacyCompatibility:
    """Read-only decryption of synthetic legacy fixtures."""

    def test_pbkdf2_legacy_fixture_decrypts(self, monkeypatch) -> None:
        """A fixed-salt PBKDF2 fixture decrypts with the legacy reader."""
        fixture = _make_pbkdf2_legacy_fixture()
        monkeypatch.setattr(encryption_module, "_build_key_material", lambda: FIXTURE_KEY_MATERIAL)
        derive_encryption_key.cache_clear()
        try:
            assert decrypt_token(fixture) == FIXTURE_PLAINTEXT
        finally:
            derive_encryption_key.cache_clear()

    def test_sha256_legacy_fixture_decrypts(self, monkeypatch) -> None:
        """A SHA-256 fixture decrypts with the legacy SHA-256 reader."""
        fixture = _make_sha256_legacy_fixture()
        monkeypatch.setattr(encryption_module, "_build_key_material", lambda: FIXTURE_KEY_MATERIAL)
        derive_encryption_key.cache_clear()
        try:
            assert decrypt_token(fixture) == FIXTURE_PLAINTEXT
        finally:
            derive_encryption_key.cache_clear()

    def test_legacy_decrypt_is_read_only(self, monkeypatch) -> None:
        """Decrypting a legacy fixture never rewrites or migrates the payload."""
        fixture = _make_pbkdf2_legacy_fixture()
        monkeypatch.setattr(encryption_module, "_build_key_material", lambda: FIXTURE_KEY_MATERIAL)
        derive_encryption_key.cache_clear()
        try:
            result = decrypt_token(fixture)
            assert result == FIXTURE_PLAINTEXT
            assert decrypt_token(fixture) == FIXTURE_PLAINTEXT
        finally:
            derive_encryption_key.cache_clear()

    def test_both_legacy_failing_raises_auth_error(self) -> None:
        """A wrong unversioned payload raises AuthenticationError."""
        garbage = base64.urlsafe_b64encode(b"not-a-valid-fernet-token").decode()
        with pytest.raises(AuthenticationError) as exc_info:
            decrypt_token(garbage)
        assert "Failed to decrypt token" in str(exc_info.value)
        assert garbage not in str(exc_info.value)


class TestStrictDecoding:
    """Strict outer base64 decoding."""

    def test_invalid_base64_raises_auth_error(self) -> None:
        """A payload outside the base64url alphabet raises AuthenticationError."""
        with pytest.raises(AuthenticationError, match="Failed to decrypt token"):
            decrypt_token("not_valid_base64!!!!")

    def test_non_ascii_payload_raises_auth_error(self) -> None:
        """A non-ASCII payload raises AuthenticationError."""
        with pytest.raises(AuthenticationError, match="Failed to decrypt token"):
            decrypt_token("\u00e9\u00e8")
