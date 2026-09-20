"""Tests for token encryption utilities."""

import base64
import hashlib
import logging
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
from perplexity_cli.utils.exceptions import AuthenticationError, ConfigurationError


def _expected_derived_key(hostname: str, username: str) -> bytes:
    """Independently recompute the PBKDF2 key for the given identifiers."""
    material = f"{hostname}:{username}".encode()
    return base64.urlsafe_b64encode(
        hashlib.pbkdf2_hmac("sha256", material, FIXTURE_SALT, FIXTURE_PBKDF2_ITERATIONS)
    )


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

    @pytest.mark.parametrize(
        "make_fixture",
        [_make_pbkdf2_legacy_fixture, _make_sha256_legacy_fixture],
        ids=["pbkdf2", "sha256"],
    )
    def test_legacy_decrypt_logs_deprecation_warning_once(
        self,
        make_fixture: object,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A successful legacy decrypt warns exactly once, without token material."""
        fixture = make_fixture()
        monkeypatch.setattr(encryption_module, "_build_key_material", lambda: FIXTURE_KEY_MATERIAL)
        derive_encryption_key.cache_clear()
        try:
            with caplog.at_level(logging.WARNING, logger=encryption_module.logger.name):
                assert decrypt_token(fixture) == FIXTURE_PLAINTEXT
        finally:
            derive_encryption_key.cache_clear()

        legacy_warnings = [
            record
            for record in caplog.records
            if record.levelno == logging.WARNING
            and "Legacy token format detected" in record.getMessage()
        ]
        assert len(legacy_warnings) == 1
        assert "re-authenticate with 'pxcli auth login' to upgrade storage" in (
            legacy_warnings[0].getMessage()
        )
        assert FIXTURE_PLAINTEXT not in caplog.text

    def test_current_format_decrypt_does_not_log_legacy_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Decrypting a current v2 payload emits no legacy-format warning."""
        encrypted = encrypt_token("current-format-token")
        with caplog.at_level(logging.WARNING, logger=encryption_module.logger.name):
            assert decrypt_token(encrypted) == "current-format-token"
        assert "Legacy token format detected" not in caplog.text


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


class TestKeyMaterialContract:
    """Hostname and username selection inside the machine key material."""

    def test_derived_key_pins_hostname_and_username_fallbacks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The key follows hostname plus USER, USERNAME, then 'unknown'."""
        monkeypatch.setattr("socket.gethostname", lambda: "kmat-host")

        monkeypatch.setenv("USER", "alice")
        monkeypatch.delenv("USERNAME", raising=False)
        derive_encryption_key.cache_clear()
        assert derive_encryption_key() == _expected_derived_key("kmat-host", "alice")

        monkeypatch.delenv("USER")
        monkeypatch.setenv("USERNAME", "bob")
        derive_encryption_key.cache_clear()
        assert derive_encryption_key() == _expected_derived_key("kmat-host", "bob")

        monkeypatch.delenv("USER", raising=False)
        monkeypatch.delenv("USERNAME", raising=False)
        derive_encryption_key.cache_clear()
        assert derive_encryption_key() == _expected_derived_key("kmat-host", "unknown")

        derive_encryption_key.cache_clear()


class TestEncryptErrorReporting:
    """Exact failure reporting when encryption cannot proceed."""

    def test_encrypt_failure_message_is_exact(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A key-derivation failure surfaces the full wrapped message."""

        def broken_derive(_salt: bytes) -> bytes:
            raise ValueError("no usable key")

        monkeypatch.setattr(encryption_module, "_derive_fernet_key", broken_derive)
        with pytest.raises(ConfigurationError) as exc_info:
            encrypt_token("secret-input")
        assert str(exc_info.value) == "Failed to encrypt token: no usable key"


class TestDerivationParameters:
    """Exact parameters passed to the cryptographic primitives."""

    def test_pbkdf2_uses_sha256_algorithm_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Key derivation uses the documented lowercase SHA-256 name."""
        calls: list[tuple[object, ...]] = []

        def fake_pbkdf2(*args: object, **kwargs: object) -> bytes:
            calls.append((*args, *kwargs.values()))
            return b"derived-key-material".ljust(32, b"-")

        monkeypatch.setattr(encryption_module.hashlib, "pbkdf2_hmac", fake_pbkdf2)
        monkeypatch.setattr(encryption_module, "_build_key_material", lambda: b"fixture-material")

        encryption_module._derive_fernet_key(b"fixture-salt")

        assert calls[0][0] == "sha256"


class TestStrictDecodeParameters:
    """Exact text encoding used at the outer payload boundary."""

    def test_decode_uses_ascii_encoding_name(self) -> None:
        """Outer base64 decoding encodes the text with the ASCII codec."""
        calls: list[str] = []

        class EncodedPayload(str):
            __slots__ = ()

            def encode(self, encoding: str = "utf-8", errors: str = "strict") -> bytes:
                calls.append(encoding)
                return super().encode(encoding, errors)

        with pytest.raises(AuthenticationError):
            encryption_module._decode_strict(EncodedPayload("invalid"))

        assert calls == ["ascii"]


class TestStrictDecodeContract:
    """Strict outer base64url validation behaviour."""

    def test_invalid_characters_are_rejected_not_stripped(self) -> None:
        """Characters outside the alphabet abort decoding instead of being dropped."""
        with pytest.raises(AuthenticationError) as exc_info:
            decrypt_token("abcd!!!!")
        expected = (
            f"Failed to decrypt token: payload is not valid base64. "
            f"{encryption_module._DECRYPT_FAILURE_HINT}"
        )
        assert str(exc_info.value) == expected


class TestTruncationBoundary:
    """Length boundary between the per-message salt and ciphertext."""

    def test_payload_exactly_salt_sized_reports_truncated(self) -> None:
        """A v2 payload holding only the salt fails as truncated, not corrupt."""
        truncated = base64.urlsafe_b64encode(b"v2:" + b"\x07" * 16).decode()
        with pytest.raises(AuthenticationError) as exc_info:
            decrypt_token(truncated)
        expected = (
            f"Failed to decrypt token in the current format. "
            f"{encryption_module._DECRYPT_FAILURE_HINT}"
        )
        assert str(exc_info.value) == expected
        cause = exc_info.value.__cause__
        assert isinstance(cause, ValueError)
        assert str(cause) == "Encrypted token payload is truncated"


class TestKeyMaterialBytes:
    """Fast direct pinning of the machine key-material bytes (no PBKDF2)."""

    HOSTNAME = "kmat-fast-host"

    def _material(self, monkeypatch: pytest.MonkeyPatch) -> bytes:
        """Read the key material bytes with the hostname pinned."""
        monkeypatch.setattr(encryption_module.socket, "gethostname", lambda: self.HOSTNAME)
        return encryption_module._build_key_material()

    def test_username_env_selection_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """USER wins; without USER the USERNAME value is honoured verbatim."""
        monkeypatch.setenv("USER", "alice")
        monkeypatch.delenv("USERNAME", raising=False)
        assert self._material(monkeypatch) == f"{self.HOSTNAME}:alice".encode()

        monkeypatch.delenv("USER")
        monkeypatch.setenv("USERNAME", "bob")
        assert self._material(monkeypatch) == f"{self.HOSTNAME}:bob".encode()

    def test_missing_username_falls_back_to_unknown_literal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no user env vars the exact lowercase 'unknown' literal is used."""
        monkeypatch.delenv("USER", raising=False)
        monkeypatch.delenv("USERNAME", raising=False)
        assert self._material(monkeypatch) == f"{self.HOSTNAME}:unknown".encode()


class TestCurrentFormatPrefixRejection:
    """Rejection of payloads lacking the v2 prefix at the reader boundary."""

    def test_unversioned_payload_message_is_exact(self) -> None:
        """A payload without the v2 prefix raises the exact format error."""
        with pytest.raises(ValueError) as exc_info:
            encryption_module._decrypt_with_current_format(b"unversioned-token-bytes")

        assert str(exc_info.value) == "Encrypted token is not in the current format"


class TestLegacyReaderErrorChain:
    """Failure propagation from the legacy SHA-256 key reader."""

    def test_legacy_reader_preserves_exact_configuration_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An OSError during legacy derivation keeps its exact message as cause."""

        def failing_hostname() -> str:
            raise OSError("disk unavailable")

        monkeypatch.setattr(encryption_module.socket, "gethostname", failing_hostname)
        garbage = base64.urlsafe_b64encode(b"z" * 72).decode()
        try:
            with pytest.raises(AuthenticationError) as exc_info:
                decrypt_token(garbage)
            cause = exc_info.value.__cause__
            assert isinstance(cause, ConfigurationError)
            assert str(cause) == "Failed to derive encryption key (legacy): disk unavailable"
        finally:
            derive_encryption_key.cache_clear()
