"""Tests for TokenManager covering encryption, cookie handling, and error paths."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from perplexity_cli.auth.token_manager import TOKEN_AGE_WARNING_DAYS, TokenManager
from perplexity_cli.utils.encryption import encrypt_token
from perplexity_cli.utils.exceptions import AuthenticationError


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


class TestPrepareTokenData:
    """Tests for _prepare_token_data with cookie encryption toggling."""

    def test_cookies_saved_when_enabled(self, token_manager, monkeypatch):
        """Cookies are encrypted and included when save_cookies is enabled."""
        monkeypatch.setattr(
            "perplexity_cli.utils.config.get_save_cookies_enabled",
            lambda: True,
        )
        data = token_manager._prepare_token_data("enc_tok", {"a": "b"})
        assert "cookies" in data

    def test_cookies_skipped_when_disabled(self, token_manager, monkeypatch):
        """Cookies are omitted when save_cookies is disabled in config."""
        monkeypatch.setattr(
            "perplexity_cli.utils.config.get_save_cookies_enabled",
            lambda: False,
        )
        data = token_manager._prepare_token_data("enc_tok", {"a": "b"})
        assert "cookies" not in data


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

    def test_invalid_date_string_handled(self, token_manager):
        """Invalid date strings are silently handled."""
        token_manager._check_token_age("not-a-date")

    def test_non_string_type_handled(self, token_manager):
        """Non-string types (triggering TypeError) are silently handled."""
        token_manager._check_token_age(12345)  # type: ignore[arg-type]


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


class TestLoadTokenRoundTrip:
    """Tests for load_token covering the main success path."""

    def test_load_token_with_cookies(self, token_manager, temp_token_file, monkeypatch):
        """Token and cookies are saved and loaded correctly."""
        monkeypatch.setattr(
            "perplexity_cli.utils.config.get_save_cookies_enabled",
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
