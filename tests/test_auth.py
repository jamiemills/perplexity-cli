"""Tests for authentication module."""

import json
import os
import stat
import tempfile
from pathlib import Path

import pytest

from perplexity_cli.auth.token_manager import TokenManager


class TestTokenManager:
    """Test cases for TokenManager class."""

    @pytest.fixture
    def temp_token_file(self):
        """Create a temporary token file for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "token.json"
            yield token_file

    @pytest.fixture
    def token_manager(self, temp_token_file, monkeypatch):
        """Create a TokenManager instance with mocked config path."""

        def mock_get_token_path():
            return temp_token_file

        monkeypatch.setattr("perplexity_cli.auth.token_manager.get_token_path", mock_get_token_path)
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

        with open(temp_token_file) as f:
            data = json.load(f)

        # Token should be encrypted and stored with metadata
        assert data["version"] == 1
        assert data["encrypted"] is True
        assert "token" in data
        # Encrypted token should be a string
        assert isinstance(data["token"], str)
        # Should not contain the plaintext token
        assert data["token"] != test_token

    def test_load_token_returns_stored_token(self, token_manager, temp_token_file):
        """Test that load_token retrieves the stored token."""
        test_token = "test_session_token_12345"
        token_manager.save_token(test_token)

        loaded_token = token_manager.load_token()
        assert loaded_token == test_token

    def test_load_token_returns_none_if_not_exists(self, token_manager):
        """Test that load_token returns None when token doesn't exist."""
        loaded_token = token_manager.load_token()
        assert loaded_token is None

    def test_load_token_verifies_permissions(self, token_manager, temp_token_file):
        """Test that load_token verifies secure permissions."""
        test_token = "test_session_token_12345"
        token_manager.save_token(test_token)

        # Change permissions to insecure
        os.chmod(temp_token_file, 0o644)

        # Should raise RuntimeError
        with pytest.raises(RuntimeError, match="insecure permissions"):
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

        loaded_token = token_manager.load_token()
        assert loaded_token == "new_token"

    def test_save_token_with_special_characters(self, token_manager):
        """Test saving tokens with special characters."""
        test_token = '{"sub": "user123", "exp": 9999999999}'
        token_manager.save_token(test_token)

        loaded_token = token_manager.load_token()
        assert loaded_token == test_token

    def test_verify_permissions_detects_insecure_perms(self, token_manager, temp_token_file):
        """Test that _verify_permissions detects insecure permissions."""
        test_token = "test_session_token_12345"
        token_manager.save_token(test_token)

        # Change permissions to world-readable
        os.chmod(temp_token_file, 0o644)

        with pytest.raises(RuntimeError):
            token_manager._verify_permissions()

    def test_load_token_handles_corrupted_json(self, token_manager, temp_token_file):
        """Test that load_token handles corrupted JSON."""
        # Write corrupted JSON
        with open(temp_token_file, "w") as f:
            f.write("{invalid json")
        os.chmod(temp_token_file, 0o600)

        with pytest.raises(IOError, match="Failed to load token"):
            token_manager.load_token()


class TestOAuthHandler:
    """Test cases for OAuth handler."""

    def test_extract_token_from_local_storage(self):
        """Test token extraction from localStorage."""
        from perplexity_cli.auth.oauth_handler import _extract_token

        session_data = {"user": {"email": "test@example.com"}, "token": "abc123"}
        local_storage = {"pplx-next-auth-session": json.dumps(session_data)}

        token = _extract_token([], local_storage)
        assert token is not None
        parsed = json.loads(token)
        assert parsed["user"]["email"] == "test@example.com"

    def test_extract_token_from_cookies(self):
        """Test token extraction from cookies."""
        from perplexity_cli.auth.oauth_handler import _extract_token

        cookies = [{"name": "__Secure-next-auth.session-token", "value": "cookie_token_123"}]

        token = _extract_token(cookies, {})
        assert token == "cookie_token_123"

    def test_extract_token_returns_none_if_not_found(self):
        """Test token extraction returns None if not found."""
        from perplexity_cli.auth.oauth_handler import _extract_token

        token = _extract_token([], {})
        assert token is None

    def test_extract_token_prioritises_local_storage(self):
        """Test that localStorage token is prioritised over cookies."""
        from perplexity_cli.auth.oauth_handler import _extract_token

        session_data = {"user": {"email": "test@example.com"}}
        local_storage = {"pplx-next-auth-session": json.dumps(session_data)}
        cookies = [{"name": "__Secure-next-auth.session-token", "value": "cookie_token"}]

        token = _extract_token(cookies, local_storage)
        parsed = json.loads(token)
        assert parsed["user"]["email"] == "test@example.com"

    def test_extract_token_handles_invalid_json(self):
        """Test that invalid JSON in localStorage is handled gracefully."""
        from perplexity_cli.auth.oauth_handler import _extract_token

        local_storage = {"pplx-next-auth-session": "{invalid json"}

        token = _extract_token([], local_storage)
        assert token is None


@pytest.mark.security
class TestTokenSecurityHandling:
    """Security-focused tests for token handling."""

    @pytest.fixture
    def token_manager(self, monkeypatch):
        """Create a TokenManager instance with mocked config path."""
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "token.json"

            def mock_get_token_path():
                return token_file

            monkeypatch.setattr(
                "perplexity_cli.auth.token_manager.get_token_path", mock_get_token_path
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
