"""Integration tests for authentication flow."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from perplexity_cli.auth.oauth_handler import (
    authenticate_sync,
    authenticate_with_browser,
)
from perplexity_cli.auth.token_manager import TokenManager


@pytest.mark.integration
class TestAuthenticationFlow:
    """Test complete authentication workflows."""

    @pytest.fixture
    def token_manager(self, monkeypatch):
        """Create a TokenManager with temporary directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "token.json"

            def mock_get_token_path():
                return token_file

            monkeypatch.setattr(
                "perplexity_cli.auth.token_manager.get_token_path", mock_get_token_path
            )
            yield TokenManager()

    def test_token_persists_across_invocations(self, token_manager):
        """Test that token persists across multiple TokenManager instances."""
        # First instance saves token
        token1 = "test_token_abc123"
        token_manager.save_token(token1)

        # Second instance loads token
        token_manager2 = TokenManager()
        token_manager2.token_path = token_manager.token_path

        loaded_token, _ = token_manager2.load_token()
        assert loaded_token == token1

    def test_logout_and_reauthentication(self, token_manager):
        """Test logout followed by re-authentication."""
        # Initial authentication
        token_manager.save_token("initial_token")
        assert token_manager.token_exists()

        # Logout
        token_manager.clear_token()
        assert not token_manager.token_exists()

        # Re-authenticate with new token
        token_manager.save_token("new_token")
        loaded_token, _ = token_manager.load_token()
        assert loaded_token == "new_token"

    @pytest.mark.asyncio
    async def test_authenticate_with_browser_error_handling(self):
        """Test error handling when Chrome is unavailable."""
        with pytest.raises(RuntimeError, match="Failed to connect to Chrome"):
            await authenticate_with_browser(port=9999)

    def test_authenticate_sync_wrapper(self):
        """Test synchronous wrapper for async authentication."""
        # Mock the async function
        with patch("perplexity_cli.auth.oauth_handler.asyncio.run") as mock_run:
            mock_run.return_value = "mocked_token"

            token = authenticate_sync(port=9222)
            assert token == "mocked_token"
            mock_run.assert_called_once()


@pytest.mark.integration
class TestTokenLifecycle:
    """Test token lifecycle management."""

    @pytest.fixture
    def token_manager(self, monkeypatch):
        """Create a TokenManager with temporary directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "token.json"

            def mock_get_token_path():
                return token_file

            monkeypatch.setattr(
                "perplexity_cli.auth.token_manager.get_token_path", mock_get_token_path
            )
            yield TokenManager()

    def test_save_load_delete_cycle(self, token_manager):
        """Test complete save-load-delete cycle."""
        test_token = "lifecycle_test_token"

        # Save
        token_manager.save_token(test_token)
        assert token_manager.token_exists()

        # Load
        loaded, _ = token_manager.load_token()
        assert loaded == test_token

        # Delete
        token_manager.clear_token()
        assert not token_manager.token_exists()
        token, cookies = token_manager.load_token()
        assert token is None
        assert cookies is None

    def test_token_refresh_workflow(self, token_manager):
        """Test token refresh scenario."""
        # Initial token
        old_token = "old_token_123"
        token_manager.save_token(old_token)

        # Refresh token (simulated)
        new_token = "new_token_456"
        token_manager.save_token(new_token)

        # Verify new token is loaded
        loaded, _ = token_manager.load_token()
        assert loaded == new_token
        assert loaded != old_token

    def test_concurrent_token_access(self, token_manager):
        """Test token access from multiple TokenManager instances."""
        test_token = "concurrent_test_token"

        # Save with first instance
        token_manager.save_token(test_token)

        # Create multiple instances and verify they all read the same token
        for _ in range(5):
            tm = TokenManager()
            tm.token_path = token_manager.token_path
            loaded, _ = tm.load_token()
            assert loaded == test_token


@pytest.mark.integration
class TestErrorRecovery:
    """Test error recovery scenarios."""

    @pytest.fixture
    def token_manager(self, monkeypatch):
        """Create a TokenManager with temporary directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "token.json"

            def mock_get_token_path():
                return token_file

            monkeypatch.setattr(
                "perplexity_cli.auth.token_manager.get_token_path", mock_get_token_path
            )
            yield TokenManager()

    def test_recover_from_corrupted_token(self, token_manager):
        """Test recovery when token file is corrupted."""
        # Write corrupted file
        with open(token_manager.token_path, "w") as f:
            f.write("not valid json")

        import os

        os.chmod(token_manager.token_path, 0o600)

        # Should raise error when loading
        with pytest.raises(OSError):
            token_manager.load_token()

        # Can recover by clearing and saving new token
        token_manager.clear_token()
        token_manager.save_token("recovered_token")
        loaded_token, _ = token_manager.load_token()
        assert loaded_token == "recovered_token"

    def test_recover_from_permission_error(self, token_manager):
        """Test recovery from permission errors."""
        test_token = "permission_test_token"
        token_manager.save_token(test_token)

        # Change to insecure permissions
        import os

        os.chmod(token_manager.token_path, 0o644)

        # Should detect insecure permissions
        with pytest.raises(RuntimeError):
            token_manager.load_token()

        # Can recover by fixing permissions
        os.chmod(token_manager.token_path, 0o600)
        loaded_token, _ = token_manager.load_token()
        assert loaded_token == test_token
