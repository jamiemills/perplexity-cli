"""Tests for authentication module."""

import builtins
import json
import logging
import os
import stat
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import IO, Any, cast
from unittest.mock import MagicMock

import pytest

from perplexity_cli.auth.token_manager import (
    TOKEN_AGE_WARNING_DAYS,
    TokenManager,
    _extract_token_string,
)
from perplexity_cli.utils.encryption import encrypt_token
from perplexity_cli.utils.exceptions import AuthenticationError
from perplexity_cli.utils.logging import redact_path

T009_TOKEN_SENTINEL = "t009-sentinel-session-token-7f3a9c2b"
T009_LOG_FORMAT_SAVED = "Token saved to %s with %s cookies"
T009_LOG_FORMAT_LOADED = "Token loaded from %s with %s cookies"


def t009_write_token_file(path: Path, record: dict[str, object]) -> None:
    """Persist a raw token record with secure permissions for loading tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f)
    os.chmod(path, 0o600)


def t009_single_record(caplog: pytest.LogCaptureFixture, msg_template: str) -> logging.LogRecord:
    """Return the single app-logger record matching an exact message template.

    Fails when the template never appears (killing mutants that reword or
    remove log format strings) or appears more than once.
    """
    matches = [r for r in caplog.records if r.msg == msg_template]
    assert len(matches) == 1, f"expected one {msg_template!r} record, got {len(matches)}"
    return matches[0]


class TestTokenManager:
    """Test cases for TokenManager class."""

    @pytest.fixture
    def temp_token_file(self):
        """Create a temporary token file for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir) / "token.json"

    @pytest.fixture
    def token_manager(self, temp_token_file, monkeypatch):
        """Create a TokenManager instance with mocked config path."""

        mock_paths = type("MockPaths", (), {"token_path": temp_token_file})()
        monkeypatch.setattr(
            "perplexity_cli.auth.token_manager.get_config_paths",
            lambda: mock_paths,
        )
        return TokenManager()

    def test_save_token_creates_file(self, token_manager, temp_token_file):
        """Test that save_token creates a token file."""
        test_token = "test_session_token_12345"
        token_manager.save_token(test_token)

        assert temp_token_file.exists()

    def test_save_token_sets_secure_permissions(self, token_manager, temp_token_file):
        """Test that save_token sets 0600 permissions."""
        test_token = "test_session_token_12345"
        token_manager.save_token(test_token)

        # Check file permissions
        file_stat = temp_token_file.stat()
        actual_permissions = stat.S_IMODE(file_stat.st_mode)

        assert actual_permissions == 0o600

    def test_save_token_stores_json(self, token_manager, temp_token_file):
        """Test that save_token stores valid encrypted JSON."""
        test_token = "test_session_token_12345"
        token_manager.save_token(test_token)

        with open(temp_token_file, encoding="utf-8") as f:
            data = json.load(f)

        # Token should be encrypted and stored with metadata
        assert data["version"] == 2  # v2 with cookie support
        assert data["encrypted"] is True
        assert "token" in data
        # Encrypted token should be a string
        assert isinstance(data["token"], str)
        # Should not contain the plaintext token
        assert data["token"] != test_token
        # No cookies provided, so cookies field should not be present
        assert "cookies" not in data or data.get("cookies") is None

    def test_load_token_returns_stored_token(self, token_manager, temp_token_file):
        """Test that load_token retrieves the stored token."""
        test_token = "test_session_token_12345"
        token_manager.save_token(test_token)

        loaded_token, loaded_cookies = token_manager.load_token()
        assert loaded_token == test_token
        assert loaded_cookies is None  # No cookies provided

    def test_load_token_returns_none_if_not_exists(self, token_manager):
        """Test that load_token returns None when token doesn't exist."""
        loaded_token, loaded_cookies = token_manager.load_token()
        assert loaded_token is None
        assert loaded_cookies is None

    def test_load_token_verifies_permissions(self, token_manager, temp_token_file):
        """Test that load_token verifies secure permissions."""
        test_token = "test_session_token_12345"
        token_manager.save_token(test_token)

        # Change permissions to insecure
        os.chmod(temp_token_file, 0o644)

        with pytest.raises(AuthenticationError, match="insecure permissions"):
            token_manager.load_token()

    def test_clear_token_deletes_file(self, token_manager, temp_token_file):
        """Test that clear_token deletes the token file."""
        test_token = "test_session_token_12345"
        token_manager.save_token(test_token)

        assert temp_token_file.exists()

        token_manager.clear_token()

        assert not temp_token_file.exists()

    def test_clear_token_succeeds_if_not_exists(self, token_manager):
        """Test that clear_token succeeds when token doesn't exist."""
        # Should not raise any exception
        token_manager.clear_token()

    def test_token_exists_returns_true(self, token_manager, temp_token_file):
        """Test that token_exists returns True when token exists."""
        test_token = "test_session_token_12345"
        token_manager.save_token(test_token)

        assert token_manager.token_exists() is True

    def test_token_exists_returns_false(self, token_manager):
        """Test that token_exists returns False when token doesn't exist."""
        assert token_manager.token_exists() is False

    def test_save_token_overwrites_existing_token(self, token_manager, temp_token_file):
        """Test that save_token overwrites existing tokens."""
        token_manager.save_token("old_token")
        token_manager.save_token("new_token")

        loaded_token, _ = token_manager.load_token()
        assert loaded_token == "new_token"

    def test_save_token_with_special_characters(self, token_manager):
        """Test saving tokens with special characters."""
        test_token = '{"sub": "user123", "exp": 9999999999}'
        token_manager.save_token(test_token)

        loaded_token, _ = token_manager.load_token()
        assert loaded_token == test_token

    def test_verify_permissions_detects_insecure_perms(self, token_manager, temp_token_file):
        """Test that _verify_permissions detects insecure permissions."""
        test_token = "test_session_token_12345"
        token_manager.save_token(test_token)

        # Change permissions to world-readable
        os.chmod(temp_token_file, 0o644)

        with pytest.raises(AuthenticationError):
            token_manager._verify_permissions()

    def test_load_token_handles_corrupted_json(self, token_manager, temp_token_file):
        """Test that load_token handles corrupted JSON."""
        # Write corrupted JSON
        with open(temp_token_file, "w", encoding="utf-8") as f:
            f.write("{invalid json")
        os.chmod(temp_token_file, 0o600)

        with pytest.raises(IOError, match="Failed to load token"):
            token_manager.load_token()

    def test_load_token_rejects_non_mapping_cookies(self, token_manager, temp_token_file):
        """Test that malformed decrypted cookies payload is rejected."""
        token_manager.save_token("test_session_token_12345")

        with open(temp_token_file, encoding="utf-8") as f:
            data = json.load(f)

        data["cookies"] = data["token"]
        with open(temp_token_file, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.chmod(temp_token_file, 0o600)

        with pytest.raises(AuthenticationError, match="malformed cookies data"):
            token_manager.load_token()


class TestOAuthHandler:
    """Test cases for OAuth handler."""

    def test_extract_token_from_local_storage(self):
        """Test token extraction from localStorage."""
        from perplexity_cli.auth.oauth_handler import _extract_token

        session_data = {"user": {"email": "test@example.com"}, "token": "abc123"}
        local_storage = {"pplx-next-auth-session": json.dumps(session_data)}

        token, _ = _extract_token([], local_storage)
        assert token is not None
        parsed = json.loads(token)
        assert parsed["user"]["email"] == "test@example.com"

    def test_extract_token_from_cookies(self):
        """Test token extraction from cookies."""
        from perplexity_cli.auth.oauth_handler import _extract_token

        cookies = [{"name": "__Secure-next-auth.session-token", "value": "cookie_token_123"}]

        token, cookies = _extract_token(cookies, {})
        assert token == "cookie_token_123"

    def test_extract_token_returns_none_if_not_found(self):
        """Test token extraction returns None if not found."""
        from perplexity_cli.auth.oauth_handler import _extract_token

        token, _ = _extract_token([], {})
        assert token is None

    def test_extract_token_prioritises_local_storage(self):
        """Test that localStorage token is prioritised over cookies."""
        from perplexity_cli.auth.oauth_handler import _extract_token

        session_data = {"user": {"email": "test@example.com"}}
        local_storage = {"pplx-next-auth-session": json.dumps(session_data)}
        cookies = [{"name": "__Secure-next-auth.session-token", "value": "cookie_token"}]

        token, cookies = _extract_token(cookies, local_storage)
        assert token is not None
        parsed = json.loads(token)
        assert parsed["user"]["email"] == "test@example.com"

    def test_extract_token_handles_invalid_json(self):
        """Test that invalid JSON in localStorage is handled gracefully."""
        from perplexity_cli.auth.oauth_handler import _extract_token

        local_storage = {"pplx-next-auth-session": "{invalid json"}

        token, _ = _extract_token([], local_storage)
        assert token is None

    def test_extract_token_handles_non_string_local_storage_value(self):
        """Test that non-string localStorage values are handled gracefully."""
        from perplexity_cli.auth.oauth_handler import _extract_token

        local_storage = {"pplx-next-auth-session": {"bad": "value"}}

        token, _ = _extract_token([], local_storage)
        assert token is None


@pytest.mark.security
class TestTokenSecurityHandling:
    """Security-focused tests for token handling."""

    @pytest.fixture
    def token_manager(self, monkeypatch):
        """Create a TokenManager instance with mocked config path."""
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "token.json"

            mock_paths = type("MockPaths", (), {"token_path": token_file})()
            monkeypatch.setattr(
                "perplexity_cli.auth.token_manager.get_config_paths",
                lambda: mock_paths,
            )
            yield TokenManager()

    def test_token_file_not_world_readable(self, token_manager):
        """Test that token file is not world-readable."""
        token_manager.save_token("secret_token")
        file_stat = token_manager.token_path.stat()
        actual_permissions = stat.S_IMODE(file_stat.st_mode)

        # Check that others don't have read permission
        assert (actual_permissions & stat.S_IROTH) == 0

    def test_token_file_not_group_readable(self, token_manager):
        """Test that token file is not group-readable."""
        token_manager.save_token("secret_token")
        file_stat = token_manager.token_path.stat()
        actual_permissions = stat.S_IMODE(file_stat.st_mode)

        # Check that group doesn't have read permission
        assert (actual_permissions & stat.S_IRGRP) == 0

    def test_token_file_only_owner_readable(self, token_manager):
        """Test that only owner can read token file."""
        token_manager.save_token("secret_token")
        file_stat = token_manager.token_path.stat()
        actual_permissions = stat.S_IMODE(file_stat.st_mode)

        # Check that owner has read permission
        assert (actual_permissions & stat.S_IRUSR) != 0


class TestT009TokenPersistenceBehaviour:
    """Behavioural coverage for token persistence diagnostics (task T009)."""

    @pytest.fixture
    def t009_token_manager(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TokenManager:
        """Create a TokenManager bound to an isolated temporary token file."""
        token_file = tmp_path / "token.json"
        mock_paths = type("MockPaths", (), {"token_path": token_file})()
        monkeypatch.setattr(
            "perplexity_cli.auth.token_manager.get_config_paths",
            lambda: mock_paths,
        )
        return TokenManager()

    @pytest.fixture
    def t009_debug_caplog(self, caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
        """Capture DEBUG-and-above records from the application logger."""
        caplog.set_level(logging.DEBUG, logger="perplexity_cli")
        return caplog

    def test_save_and_load_without_cookies_logs_zero_counts(
        self,
        t009_token_manager: TokenManager,
        t009_debug_caplog: pytest.LogCaptureFixture,
    ):
        """Token round-trip without cookies logs zero cookie counts."""
        tm = t009_token_manager

        tm.save_token(T009_TOKEN_SENTINEL)
        saved = t009_single_record(t009_debug_caplog, T009_LOG_FORMAT_SAVED)
        assert saved.args == (redact_path(tm.token_path), 0)

        token, cookies = tm.load_token()
        assert token == T009_TOKEN_SENTINEL
        assert cookies is None
        loaded = t009_single_record(t009_debug_caplog, T009_LOG_FORMAT_LOADED)
        assert loaded.args == (redact_path(tm.token_path), 0)

    def test_save_and_load_with_enabled_cookies_round_trips(
        self,
        t009_token_manager: TokenManager,
        t009_debug_caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Enabled cookie storage persists and reports the cookie count."""
        tm = t009_token_manager
        monkeypatch.setattr(
            "perplexity_cli.auth.token_manager.get_save_cookies_enabled", lambda: True
        )
        cookies = {"t009_alpha": "v1", "t009_beta": "v2", "t009_gamma": "v3"}

        tm.save_token(T009_TOKEN_SENTINEL, cookies)

        saving = t009_single_record(t009_debug_caplog, "Saving %s cookies (cookie storage enabled)")
        assert saving.args == (3,)
        saved = t009_single_record(t009_debug_caplog, T009_LOG_FORMAT_SAVED)
        assert saved.args == (redact_path(tm.token_path), 3)

        with open(tm.token_path, encoding="utf-8") as f:
            stored = json.load(f)
        assert isinstance(stored.get("cookies"), str)
        assert stored["cookies"] != json.dumps(cookies)

        token, loaded_cookies = tm.load_token()
        assert token == T009_TOKEN_SENTINEL
        assert loaded_cookies == cookies
        loaded = t009_single_record(t009_debug_caplog, T009_LOG_FORMAT_LOADED)
        assert loaded.args == (redact_path(tm.token_path), 3)

    def test_save_with_disabled_cookies_skips_cookie_field(
        self,
        t009_token_manager: TokenManager,
        t009_debug_caplog: pytest.LogCaptureFixture,
    ):
        """Disabled cookie storage omits the field and logs the skip decision."""
        tm = t009_token_manager

        tm.save_token(T009_TOKEN_SENTINEL, {"t009_alpha": "v1"})

        skipping = t009_single_record(
            t009_debug_caplog, "Skipping %s cookies (cookie storage disabled in config)"
        )
        assert skipping.args == (1,)
        saved = t009_single_record(t009_debug_caplog, T009_LOG_FORMAT_SAVED)
        assert saved.args == (redact_path(tm.token_path), 0)

        with open(tm.token_path, encoding="utf-8") as f:
            stored = json.load(f)
        assert "cookies" not in stored

    def test_save_failure_logs_message_without_traceback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A failed save raises OSError and logs once without a traceback."""
        missing_parent = tmp_path / "t009-missing-dir"
        mock_paths = type("MockPaths", (), {"token_path": missing_parent / "token.json"})()
        monkeypatch.setattr(
            "perplexity_cli.auth.token_manager.get_config_paths",
            lambda: mock_paths,
        )
        tm = TokenManager()
        tm.logger = MagicMock()

        with pytest.raises(OSError, match=r"^Failed to save or set permissions on token file"):
            tm.save_token(T009_TOKEN_SENTINEL)

        tm.logger.exception.assert_called_once()
        call = tm.logger.exception.call_args
        assert call.args[0] == "Failed to save token file"
        assert call.kwargs.get("exc_info") is False

    def test_clear_token_logs_redacted_audit_entry(self, t009_token_manager: TokenManager):
        """Clearing an existing token logs one redacted audit entry."""
        tm = t009_token_manager
        tm.save_token(T009_TOKEN_SENTINEL)
        tm.logger = MagicMock()

        tm.clear_token()

        tm.logger.info.assert_called_once()
        call = tm.logger.info.call_args
        assert call.args[0] == "Token cleared from %s"
        assert call.args[1:] == (redact_path(tm.token_path),)

    def test_clear_token_failure_logs_without_traceback(
        self, t009_token_manager: TokenManager, monkeypatch: pytest.MonkeyPatch
    ):
        """An unlink failure raises OSError and logs once without traceback."""

        def refuse(*args: object, **kwargs: object) -> None:
            raise PermissionError(13, "permission denied")

        tm = t009_token_manager
        tm.save_token(T009_TOKEN_SENTINEL)
        tm.logger = MagicMock()
        monkeypatch.setattr(Path, "unlink", refuse)

        with pytest.raises(OSError, match=r"^Failed to delete token file"):
            tm.clear_token()

        tm.logger.exception.assert_called_once()
        call = tm.logger.exception.call_args
        assert call.args[0] == "Failed to delete token file"
        assert call.kwargs.get("exc_info") is False

    def test_load_warns_when_token_older_than_threshold(
        self,
        t009_token_manager: TokenManager,
        t009_debug_caplog: pytest.LogCaptureFixture,
    ):
        """A stale token triggers exactly one age warning with its age."""
        tm = t009_token_manager
        created_at = (datetime.now() - timedelta(days=TOKEN_AGE_WARNING_DAYS + 1)).isoformat()
        t009_write_token_file(
            tm.token_path,
            {
                "version": 2,
                "encrypted": True,
                "token": encrypt_token(T009_TOKEN_SENTINEL),
                "created_at": created_at,
            },
        )

        token, _ = tm.load_token()

        assert token == T009_TOKEN_SENTINEL
        warning = t009_single_record(t009_debug_caplog, "Token is %s days old, may be expired")
        assert warning.levelno == logging.WARNING
        warning_args = cast("tuple[object, ...]", warning.args)
        assert warning_args is not None
        age_days = warning_args[0]
        assert isinstance(age_days, int)
        assert age_days > TOKEN_AGE_WARNING_DAYS

    def test_load_at_exact_threshold_does_not_warn(
        self,
        t009_token_manager: TokenManager,
        t009_debug_caplog: pytest.LogCaptureFixture,
    ):
        """A token just inside the threshold logs debug, never a warning."""
        tm = t009_token_manager
        created_at = (datetime.now() - timedelta(days=TOKEN_AGE_WARNING_DAYS, hours=1)).isoformat()
        t009_write_token_file(
            tm.token_path,
            {
                "version": 2,
                "encrypted": True,
                "token": encrypt_token(T009_TOKEN_SENTINEL),
                "created_at": created_at,
            },
        )

        token, _ = tm.load_token()

        assert token == T009_TOKEN_SENTINEL
        warnings = [
            r
            for r in t009_debug_caplog.records
            if r.name == "perplexity_cli" and r.levelno == logging.WARNING
        ]
        assert warnings == []

    def test_load_logs_fresh_token_age_debug(
        self,
        t009_token_manager: TokenManager,
        t009_debug_caplog: pytest.LogCaptureFixture,
    ):
        """A fresh token logs its age on the debug channel."""
        tm = t009_token_manager
        created_at = (datetime.now() - timedelta(minutes=5)).isoformat()
        t009_write_token_file(
            tm.token_path,
            {
                "version": 2,
                "encrypted": True,
                "token": encrypt_token(T009_TOKEN_SENTINEL),
                "created_at": created_at,
            },
        )

        token, _ = tm.load_token()

        assert token == T009_TOKEN_SENTINEL
        debug = t009_single_record(t009_debug_caplog, "Token age: %s days")
        assert debug.levelno == logging.DEBUG
        debug_args = cast("tuple[object, ...]", debug.args)
        assert debug_args is not None
        assert len(debug_args) == 1
        assert isinstance(debug_args[0], int)

    def test_load_unparseable_timestamp_logs_debug_note(
        self,
        t009_token_manager: TokenManager,
        t009_debug_caplog: pytest.LogCaptureFixture,
    ):
        """An unparseable timestamp falls back to a debug note."""
        tm = t009_token_manager
        t009_write_token_file(
            tm.token_path,
            {
                "version": 2,
                "encrypted": True,
                "token": encrypt_token(T009_TOKEN_SENTINEL),
                "created_at": "not-an-iso-timestamp",
            },
        )

        token, _ = tm.load_token()

        assert token == T009_TOKEN_SENTINEL
        debug = t009_single_record(t009_debug_caplog, "Could not parse token creation timestamp")
        assert debug.levelno == logging.DEBUG

    def test_load_missing_token_data_raises_and_logs_error(
        self,
        t009_token_manager: TokenManager,
        t009_debug_caplog: pytest.LogCaptureFixture,
    ):
        """A record without token data raises anchored error and logs it."""
        tm = t009_token_manager
        t009_write_token_file(tm.token_path, {"version": 2, "encrypted": True})

        with pytest.raises(
            AuthenticationError, match=r"^Token file is missing encrypted token data$"
        ):
            tm.load_token()

        error = t009_single_record(t009_debug_caplog, "Token file missing encrypted token data")
        assert error.levelno == logging.ERROR

    def test_load_unencrypted_file_raises_and_warns(
        self,
        t009_token_manager: TokenManager,
        t009_debug_caplog: pytest.LogCaptureFixture,
    ):
        """An unencrypted record warns once and raises an anchored error."""
        tm = t009_token_manager
        t009_write_token_file(
            tm.token_path,
            {
                "version": 2,
                "encrypted": False,
                "token": encrypt_token(T009_TOKEN_SENTINEL),
            },
        )

        with pytest.raises(AuthenticationError, match=r"^Token file is not encrypted\."):
            tm.load_token()

        warning = t009_single_record(t009_debug_caplog, "Token file is not encrypted")
        assert warning.levelno == logging.WARNING

    def test_load_corrupted_json_logs_failure_without_traceback(
        self, t009_token_manager: TokenManager
    ):
        """Corrupted JSON raises OSError and logs once without traceback."""
        tm = t009_token_manager
        with open(tm.token_path, "w", encoding="utf-8") as f:
            f.write("{invalid json")
        os.chmod(tm.token_path, 0o600)
        tm.logger = MagicMock()

        with pytest.raises(OSError, match=r"^Failed to load token from "):
            tm.load_token()

        tm.logger.exception.assert_called_once()
        call = tm.logger.exception.call_args
        assert call.args[0] == "Failed to load token file"
        assert call.kwargs.get("exc_info") is False

    def test_token_file_read_with_explicit_utf8_encoding(
        self, t009_token_manager: TokenManager, monkeypatch: pytest.MonkeyPatch
    ):
        """The token file is always opened with the explicit utf-8 codec."""
        tm = t009_token_manager
        tm.save_token(T009_TOKEN_SENTINEL)
        recorded_encodings: list[str | None] = []
        real_open = builtins.open

        def recording_open(*args: Any, **kwargs: Any) -> IO[str]:
            encoding = kwargs.get("encoding")
            recorded_encodings.append(encoding if isinstance(encoding, str) else None)
            return cast(IO[str], real_open(*args, **kwargs))

        monkeypatch.setattr(builtins, "open", recording_open)

        token, _ = tm.load_token()

        assert token == T009_TOKEN_SENTINEL
        assert recorded_encodings == ["utf-8"]

    def test_load_v2_without_cookies_logs_version_note(
        self,
        t009_token_manager: TokenManager,
        t009_debug_caplog: pytest.LogCaptureFixture,
    ):
        """A v2 record without cookies logs the v2-specific debug note."""
        tm = t009_token_manager
        tm.save_token(T009_TOKEN_SENTINEL)

        _, cookies = tm.load_token()

        assert cookies is None
        note = t009_single_record(t009_debug_caplog, "Token is v2 format but no cookies stored")
        assert note.levelno == logging.DEBUG
        assert note.args == ()

    def test_load_v1_format_ignores_cookies_field(
        self,
        t009_token_manager: TokenManager,
        t009_debug_caplog: pytest.LogCaptureFixture,
    ):
        """A v1 record never yields cookies even when the field is present."""
        tm = t009_token_manager
        t009_write_token_file(
            tm.token_path,
            {
                "version": 1,
                "encrypted": True,
                "token": encrypt_token(T009_TOKEN_SENTINEL),
                "created_at": datetime.now().isoformat(),
                "cookies": encrypt_token(json.dumps({"t009_legacy": "stale"})),
            },
        )

        token, cookies = tm.load_token()

        assert token == T009_TOKEN_SENTINEL
        assert cookies is None
        note = t009_single_record(t009_debug_caplog, "Token is v%s format (no cookies)")
        assert note.levelno == logging.DEBUG
        assert note.args == (1,)

    def test_load_logs_cloudflare_cookie_summary_redacted(
        self,
        t009_token_manager: TokenManager,
        t009_debug_caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Loaded cookies log counts plus redacted Cloudflare details only."""
        tm = t009_token_manager
        monkeypatch.setattr(
            "perplexity_cli.auth.token_manager.get_save_cookies_enabled", lambda: True
        )
        cookies = {"cf_alpha": "v1", "__cf_beta": "v2", "other": "v3"}
        tm.save_token(T009_TOKEN_SENTINEL, cookies)

        _, loaded_cookies = tm.load_token()

        assert loaded_cookies == cookies
        summary = t009_single_record(
            t009_debug_caplog,
            "Loaded %s cookies, including %s Cloudflare cookies",
        )
        assert summary.args == (3, 2)
        cf_note = t009_single_record(t009_debug_caplog, "Cloudflare cookies: %s")
        assert cf_note.args == ("<redacted:2 keys>",)


class TestT009ExtractTokenStringGuard:
    """Direct coverage of the module-level token guard.

    ``load_token`` can never reach this guard with invalid data because
    ``_read_and_validate_token_file`` rejects falsy token fields first, so
    the helper is exercised directly to pin its defensive contract.
    """

    def test_extract_token_string_returns_string_value(self):
        """A present string token is returned unchanged."""
        assert _extract_token_string({"token": "abc"}) == "abc"

    def test_extract_token_string_rejects_missing_or_invalid(self):
        """Absent, non-string, and empty tokens all raise anchored errors."""
        bad_records: list[dict[str, object]] = [{}, {"token": None}, {"token": 5}, {"token": ""}]
        for bad_record in bad_records:
            with pytest.raises(
                AuthenticationError, match=r"^Token file is missing encrypted token data$"
            ):
                _extract_token_string(bad_record)
