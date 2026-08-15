"""Tests for TokenManager covering encryption, cookie handling, and error paths."""

from __future__ import annotations

import json
import logging
import os
import stat
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from perplexity_cli.auth.token_manager import (
    TOKEN_AGE_WARNING_DAYS,
    TokenManager,
    _extract_created_at,
    _extract_token_string,
    _extract_version,
)
from perplexity_cli.utils.encryption import encrypt_token
from perplexity_cli.utils.exceptions import AuthenticationError

_POSIX = sys.platform != "win32"


def _temp_files(directory: Path) -> list[Path]:
    """Return any temporary siblings left behind in a directory."""
    return [p for p in directory.iterdir() if p.name.endswith(".tmp")]


@pytest.fixture
def temp_token_file():
    """Create a temporary token file path for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir) / "token.json"


@pytest.fixture
def token_manager(temp_token_file, monkeypatch):
    """Create a TokenManager with a mocked config path."""
    mock_paths = type("MockPaths", (), {"token_path": temp_token_file})()
    monkeypatch.setattr(
        "perplexity_cli.auth.token_manager.get_config_paths",
        lambda: mock_paths,
    )
    return TokenManager()


def _write_token_file(path: Path, data: dict) -> None:
    """Write token data to file with secure permissions."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.chmod(path, 0o600)


class TestSaveTokenOSError:
    """Tests for OSError handling during token save."""

    def test_save_token_raises_on_oserror(self, token_manager, temp_token_file):
        """OSError during file write is re-raised with context."""
        with patch("builtins.open", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="Failed to save or set permissions"):
                token_manager.save_token("tok")


class TestTokenRecordHelpers:
    """Tests for token record field extraction helpers."""

    def test_extract_created_at_only_accepts_strings(self):
        """Creation timestamps reject missing and non-string values."""
        assert _extract_created_at({"created_at": "2026-01-01"}) == "2026-01-01"
        assert _extract_created_at({"created_at": 123}) is None
        assert _extract_created_at({}) is None

    @pytest.mark.parametrize("value", [None, "", 123, []])
    def test_extract_token_string_rejects_invalid_values(self, value):
        """Encrypted token data must be a non-empty string."""
        with pytest.raises(AuthenticationError, match="missing encrypted token data"):
            _extract_token_string({"token": value})

    def test_extract_token_string_returns_non_empty_string(self):
        """Valid encrypted token data passes through unchanged."""
        assert _extract_token_string({"token": "encrypted"}) == "encrypted"

    def test_extract_version_uses_v2_default_and_v1_fallback(self):
        """Missing or malformed versions use the documented compatibility defaults."""
        assert _extract_version({}) == 2
        assert _extract_version({"version": 1}) == 1
        assert _extract_version({"version": "2"}) == 1


class TestSaveTokenAtomicPreservation:
    """A failure in any atomic-write stage preserves the previous valid token."""

    @pytest.mark.parametrize(
        "stage",
        ["_write_content", "_flush_file", "_fsync_file", "_set_permissions", "_replace_temp"],
    )
    def test_stage_failure_preserves_previous_token(
        self, token_manager, temp_token_file, monkeypatch, stage
    ):
        """A failure during the given stage keeps the old token loadable."""

        def _fail(*args, **kwargs):
            raise OSError("injected failure")

        token_manager.save_token("original-token")
        original_bytes = temp_token_file.read_bytes()
        monkeypatch.setattr(f"perplexity_cli.utils.atomic_write.{stage}", _fail)
        with pytest.raises(OSError, match="Failed to save or set permissions"):
            token_manager.save_token("replacement-token")
        assert temp_token_file.read_bytes() == original_bytes
        token, _ = token_manager.load_token()
        assert token == "original-token"
        assert _temp_files(temp_token_file.parent) == []
        if _POSIX:
            assert stat.S_IMODE(temp_token_file.stat().st_mode) == 0o600

    @pytest.mark.skipif(not _POSIX, reason="POSIX mode bits are not asserted on Windows")
    def test_saved_token_file_mode_0600(self, token_manager, temp_token_file):
        """A successful save writes a 0600 token file."""
        token_manager.save_token("tok")
        assert stat.S_IMODE(temp_token_file.stat().st_mode) == 0o600

    def test_successful_save_leaves_no_temp_residue(self, token_manager, temp_token_file):
        """A successful save leaves no temporary siblings behind."""
        token_manager.save_token("tok")
        assert temp_token_file.exists()
        assert _temp_files(temp_token_file.parent) == []

    def test_failed_save_does_not_log_plaintext_token(self, token_manager, monkeypatch, caplog):
        """A failed save never logs the plaintext token value."""
        token_manager.save_token("original-token")
        secret = "super-secret-plaintext-token"

        def _fail(*args, **kwargs):
            raise OSError("injected failure")

        monkeypatch.setattr("perplexity_cli.utils.atomic_write._write_content", _fail)
        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            with pytest.raises(OSError, match="Failed to save or set permissions"):
                token_manager.save_token(secret)
        combined = "\n".join(record.getMessage() for record in caplog.records)
        assert secret not in combined
        assert "original-token" not in combined

    def test_successful_save_does_not_log_plaintext_token(self, token_manager, caplog):
        """A successful save never logs the plaintext token value."""
        secret = "super-secret-plaintext-token"
        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            token_manager.save_token(secret)
        combined = "\n".join(record.getMessage() for record in caplog.records)
        assert secret not in combined

    def test_atomic_write_receives_secure_mode_and_encrypted_record(
        self, token_manager, temp_token_file
    ):
        """Token persistence delegates one encrypted record with mode 0600."""
        with (
            patch("perplexity_cli.auth.token_manager.encrypt_token", return_value="ciphertext"),
            patch("perplexity_cli.auth.token_manager.atomic_write_json") as atomic_write,
        ):
            token_manager.save_token("plaintext")

        path, record = atomic_write.call_args.args
        assert path == temp_token_file
        assert record["token"] == "ciphertext"
        assert record["encrypted"] is True
        assert atomic_write.call_args.kwargs == {"mode": 0o600}

    def test_encryption_failure_preserves_existing_token(self, token_manager, temp_token_file):
        """Failure before the atomic write cannot replace a valid token."""
        token_manager.save_token("original-token")
        original_bytes = temp_token_file.read_bytes()

        with patch(
            "perplexity_cli.auth.token_manager.encrypt_token",
            side_effect=RuntimeError("key unavailable"),
        ):
            with pytest.raises(RuntimeError, match="key unavailable"):
                token_manager.save_token("replacement-token")

        assert temp_token_file.read_bytes() == original_bytes
        assert _temp_files(temp_token_file.parent) == []


class TestPrepareTokenData:
    """Tests for _prepare_token_data with cookie encryption toggling."""

    def test_cookies_saved_when_enabled(self, token_manager, monkeypatch):
        """Cookies are encrypted and included when save_cookies is enabled."""
        monkeypatch.setattr(
            "perplexity_cli.auth.token_manager.get_save_cookies_enabled",
            lambda: True,
        )
        data = token_manager._prepare_token_data("enc_tok", {"a": "b"})
        assert "cookies" in data

    def test_cookies_skipped_when_disabled(self, token_manager, monkeypatch):
        """Cookies are omitted when save_cookies is disabled in config."""
        monkeypatch.setattr(
            "perplexity_cli.auth.token_manager.get_save_cookies_enabled",
            lambda: False,
        )
        data = token_manager._prepare_token_data("enc_tok", {"a": "b"})
        assert "cookies" not in data

    def test_token_record_contains_format_and_timestamp(self, token_manager, monkeypatch):
        """Prepared records contain the v2 encrypted marker and creation time."""
        monkeypatch.setattr(
            "perplexity_cli.auth.token_manager.datetime",
            Mock(now=Mock(return_value=datetime(2026, 1, 2, 3, 4, 5))),
        )

        data = token_manager._prepare_token_data("enc_tok", None)

        assert data["version"] == 2
        assert data["encrypted"] is True
        assert data["token"] == "enc_tok"
        assert data["created_at"] == "2026-01-02T03:04:05"


class TestReadAndValidateTokenFile:
    """Tests for _read_and_validate_token_file edge cases."""

    def test_unencrypted_token_raises(self, token_manager, temp_token_file):
        """An unencrypted token file raises AuthenticationError."""
        _write_token_file(temp_token_file, {"encrypted": False, "token": "x"})
        with pytest.raises(AuthenticationError, match="not encrypted"):
            token_manager._read_and_validate_token_file()

    def test_missing_token_data_raises(self, token_manager, temp_token_file):
        """A file with encrypted=True but no token raises AuthenticationError."""
        _write_token_file(temp_token_file, {"encrypted": True, "token": ""})
        with pytest.raises(AuthenticationError, match="missing encrypted token data"):
            token_manager._read_and_validate_token_file()


class TestCheckTokenAge:
    """Tests for _check_token_age edge cases."""

    def test_falsy_created_at_returns_early(self, token_manager):
        """None or empty created_at does not raise."""
        token_manager._check_token_age(None)
        token_manager._check_token_age("")

    def test_old_token_logs_warning(self, token_manager):
        """A token older than TOKEN_AGE_WARNING_DAYS triggers a warning."""
        old_date = (datetime.now() - timedelta(days=TOKEN_AGE_WARNING_DAYS + 5)).isoformat()
        # Should not raise; just logs
        token_manager._check_token_age(old_date)

    def test_old_token_warning_contains_age(self, token_manager, caplog, monkeypatch):
        """Old-token warnings include the computed age in days."""
        expected_age = TOKEN_AGE_WARNING_DAYS + 5
        current_time = datetime(2026, 8, 15, 12, 0, 0)
        datetime_mock = Mock(wraps=datetime)
        datetime_mock.now.return_value = current_time
        monkeypatch.setattr("perplexity_cli.auth.token_manager.datetime", datetime_mock)
        old_date = (current_time - timedelta(days=expected_age)).isoformat()

        with caplog.at_level(logging.WARNING, logger="perplexity_cli"):
            token_manager._check_token_age(old_date)

        assert any(str(expected_age) in record.getMessage() for record in caplog.records)

    def test_invalid_date_string_handled(self, token_manager):
        """Invalid date strings are silently handled."""
        token_manager._check_token_age("not-a-date")

    def test_non_string_type_handled(self, token_manager):
        """Non-string types (triggering TypeError) are silently handled."""
        token_manager._check_token_age(12345)  # type: ignore[arg-type]  # owner: test-infrastructure; reason: deliberately passes a non-string to exercise the TypeError path


class TestDecryptCookies:
    """Tests for _decrypt_cookies edge cases."""

    def test_v1_format_returns_none(self, token_manager):
        """v1 format (version != 2) returns None."""
        result = token_manager._decrypt_cookies({"token": "x"}, version=1)
        assert result is None

    def test_v2_no_cookies_key_returns_none(self, token_manager):
        """v2 format without cookies key returns None."""
        result = token_manager._decrypt_cookies({"token": "x"}, version=2)
        assert result is None

    def test_falsy_encrypted_cookies_returns_none(self, token_manager):
        """v2 format with empty/falsy cookies value returns None."""
        result = token_manager._decrypt_cookies({"token": "x", "cookies": ""}, version=2)
        assert result is None

    def test_v2_non_string_encrypted_cookies_returns_none(self, token_manager):
        """Malformed non-string cookie payloads are ignored before decryption."""
        assert token_manager._decrypt_cookies({"cookies": 123}, version=2) is None

    def test_valid_cookies_decrypted(self, token_manager):
        """Valid encrypted cookies are decrypted and returned."""
        cookies = {"session": "abc", "cf_clearance": "xyz"}
        encrypted = encrypt_token(json.dumps(cookies))
        result = token_manager._decrypt_cookies({"token": "x", "cookies": encrypted}, version=2)
        assert result == cookies


class TestParseAndValidateCookies:
    """Tests for _parse_and_validate_cookies."""

    def test_valid_cookies_parsed(self, token_manager):
        """Valid JSON cookie string is parsed correctly."""
        result = token_manager._parse_and_validate_cookies('{"a": "b"}')
        assert result == {"a": "b"}

    def test_invalid_json_raises(self, token_manager):
        """Invalid JSON raises AuthenticationError."""
        with pytest.raises(AuthenticationError, match="malformed cookies"):
            token_manager._parse_and_validate_cookies("{bad")


class TestValidateCookieTypes:
    """Tests for _validate_cookie_types."""

    def test_non_dict_raises(self):
        """Non-dict cookies raise AuthenticationError."""
        with pytest.raises(AuthenticationError, match="malformed cookies"):
            TokenManager._validate_cookie_types(["not", "a", "dict"])

    def test_non_string_key_raises(self):
        """Non-string keys raise AuthenticationError."""
        with pytest.raises(AuthenticationError, match="malformed cookies"):
            TokenManager._validate_cookie_types({1: "value"})

    def test_non_string_value_raises(self):
        """Non-string values raise AuthenticationError."""
        with pytest.raises(AuthenticationError, match="malformed cookies"):
            TokenManager._validate_cookie_types({"key": 123})

    def test_valid_dict_passes(self):
        """Valid str->str dict passes validation."""
        TokenManager._validate_cookie_types({"a": "b", "c": "d"})


class TestLogCookieDetails:
    """Tests for _log_cookie_details."""

    def test_logs_with_cloudflare_cookies(self, token_manager):
        """Cloudflare cookies are identified and logged."""
        cookies = {"cf_clearance": "abc", "__cf_bm": "xyz", "session": "123"}
        # Should not raise
        token_manager._log_cookie_details(cookies)

    def test_logs_without_cloudflare_cookies(self, token_manager):
        """Non-Cloudflare cookies are logged without Cloudflare details."""
        token_manager._log_cookie_details({"session": "abc"})

    def test_cloudflare_cookie_log_redacts_names_and_values(self, token_manager, caplog):
        """Cloudflare cookie diagnostics expose only a redacted key count."""
        sentinels = (
            "cf_cookie_name_sentinel_70d1",
            "cf_cookie_value_sentinel_129b",
            "session_cookie_name_sentinel_ea46",
            "session_cookie_value_sentinel_5fc8",
        )
        cookies = {sentinels[0]: sentinels[1], sentinels[2]: sentinels[3]}
        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            token_manager._log_cookie_details(cookies)
        messages = [record.getMessage() for record in caplog.records]
        assert all(sentinel not in message for message in messages for sentinel in sentinels)
        assert messages


class TestLoadTokenRoundTrip:
    """Tests for load_token covering the main success path."""

    def test_load_token_with_cookies(self, token_manager, temp_token_file, monkeypatch):
        """Token and cookies are saved and loaded correctly."""
        monkeypatch.setattr(
            "perplexity_cli.auth.token_manager.get_save_cookies_enabled",
            lambda: True,
        )
        token_manager.save_token("my_token", cookies={"cf_clearance": "val"})
        token, cookies = token_manager.load_token()
        assert token == "my_token"
        assert cookies == {"cf_clearance": "val"}

    def test_load_token_no_file_returns_none(self, token_manager):
        """Missing token file returns (None, None)."""
        assert token_manager.load_token() == (None, None)

    def test_load_token_young_token(self, token_manager, temp_token_file):
        """A recently created token logs debug, not warning."""
        token_manager.save_token("tok")
        token, _ = token_manager.load_token()
        assert token == "tok"

    def test_token_exists(self, token_manager, temp_token_file):
        """token_exists returns True after saving."""
        assert not token_manager.token_exists()
        token_manager.save_token("tok")
        assert token_manager.token_exists()

    def test_clear_token_success(self, token_manager, temp_token_file):
        """clear_token removes the file successfully."""
        token_manager.save_token("tok")
        token_manager.clear_token()
        assert not temp_token_file.exists()

    def test_load_verifies_exact_security_contract_before_reading(
        self, token_manager, temp_token_file
    ):
        """Loading verifies the token path with mode 0600 and the active logger."""
        token_manager.save_token("tok")

        with patch(
            "perplexity_cli.auth.token_manager.verify_secure_permissions"
        ) as verify_permissions:
            assert token_manager.load_token()[0] == "tok"

        verify_permissions.assert_called_once_with(
            temp_token_file,
            expected_permissions=0o600,
            file_type="token",
            logger=token_manager.logger,
        )


class TestClearTokenOSError:
    """Tests for OSError handling during token deletion."""

    def test_clear_token_raises_on_oserror(self, token_manager, temp_token_file):
        """OSError during file deletion is re-raised."""
        # Create the file first
        token_manager.save_token("tok")
        assert temp_token_file.exists()

        with patch.object(Path, "unlink", side_effect=OSError("permission denied")):
            with pytest.raises(OSError, match="Failed to delete token file"):
                token_manager.clear_token()

    def test_clear_token_without_file_is_noop(self, token_manager):
        """Clearing an absent token does not touch the filesystem."""
        token_manager.clear_token()
        assert token_manager.token_exists() is False
