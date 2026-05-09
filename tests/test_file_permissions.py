"""Tests for file permission verification utilities."""

import logging
import os
from unittest.mock import MagicMock

import pytest

from perplexity_cli.utils.exceptions import AuthenticationError, ConfigurationError
from perplexity_cli.utils.file_permissions import verify_secure_permissions


class TestVerifySecurePermissions:
    """Tests for verify_secure_permissions function."""

    def test_correct_permissions_pass(self, tmp_path):
        """Test that a file with correct permissions does not raise."""
        f = tmp_path / "secure.txt"
        f.write_text("data")
        os.chmod(f, 0o600)
        verify_secure_permissions(f)

    def test_wrong_permissions_token_raises_auth_error(self, tmp_path):
        """Test that wrong permissions with file_type='token' raises AuthenticationError."""
        f = tmp_path / "token.txt"
        f.write_text("data")
        os.chmod(f, 0o644)
        with pytest.raises(AuthenticationError):
            verify_secure_permissions(f, file_type="token")

    def test_wrong_permissions_other_raises_config_error(self, tmp_path):
        """Test that wrong permissions with other file_type raises ConfigurationError."""
        f = tmp_path / "cache.txt"
        f.write_text("data")
        os.chmod(f, 0o644)
        with pytest.raises(ConfigurationError):
            verify_secure_permissions(f, file_type="cache")

    def test_custom_expected_permissions(self, tmp_path):
        """Test that custom expected_permissions value is respected."""
        f = tmp_path / "exec.txt"
        f.write_text("data")
        os.chmod(f, 0o700)
        verify_secure_permissions(f, expected_permissions=0o700)

    def test_logger_called_on_error(self, tmp_path):
        """Test that logger.error is called when permissions are wrong."""
        f = tmp_path / "logged.txt"
        f.write_text("data")
        os.chmod(f, 0o644)
        mock_logger = MagicMock(spec=logging.Logger)
        with pytest.raises((AuthenticationError, ConfigurationError)):
            verify_secure_permissions(f, file_type="file", logger=mock_logger)
        mock_logger.error.assert_called_once()

    def test_nonexistent_file_raises(self, tmp_path):
        """Test that a non-existent file raises an error."""
        f = tmp_path / "nonexistent.txt"
        with pytest.raises((FileNotFoundError, OSError)):
            verify_secure_permissions(f)
