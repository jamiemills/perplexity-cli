"""Tests for file permission verification utilities."""

import inspect
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

    def test_public_defaults_are_secure_file_defaults(self):
        """The public signature declares 0600 and the generic file label."""
        signature = inspect.signature(verify_secure_permissions)

        assert signature.parameters["expected_permissions"].default == 0o600
        assert signature.parameters["file_type"].default == "file"

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


class TestVerifySecurePermissionsMessages:
    """Error and log messages identify the file type and permission gap."""

    def test_config_error_message_reports_insecure_permissions(self, tmp_path):
        """The raised error names the insecurity and both octal modes."""
        f = tmp_path / "cache.txt"
        f.write_text("data")
        os.chmod(f, 0o644)
        with pytest.raises(ConfigurationError) as excinfo:
            verify_secure_permissions(f, file_type="cache")
        message = str(excinfo.value)
        assert "has insecure permissions" in message
        assert oct(0o644) in message
        assert oct(0o600) in message

    def test_token_error_message_starts_with_type_label(self, tmp_path):
        """Token classification leads the raised message."""
        f = tmp_path / "token.txt"
        f.write_text("data")
        os.chmod(f, 0o644)
        with pytest.raises(AuthenticationError) as excinfo:
            verify_secure_permissions(f, file_type="token")
        assert str(excinfo.value).startswith("Token")

    def test_default_file_type_label_is_file(self, tmp_path):
        """Without an explicit type the message label is File."""
        f = tmp_path / "plain.txt"
        f.write_text("data")
        os.chmod(f, 0o644)
        with pytest.raises(ConfigurationError) as excinfo:
            verify_secure_permissions(f)
        assert str(excinfo.value).startswith("File ")

    def test_logger_receives_insecure_permission_message(self, tmp_path, caplog):
        """A supplied logger records the insecure-permission detail."""
        f = tmp_path / "logged.txt"
        f.write_text("data")
        os.chmod(f, 0o644)
        logger = logging.getLogger("pxcli.test.file-permissions")
        with caplog.at_level(logging.ERROR, logger="pxcli.test.file-permissions"):
            with pytest.raises(ConfigurationError):
                verify_secure_permissions(f, logger=logger)
        messages = [r.getMessage() for r in caplog.records]
        assert any("insecure permissions" in m for m in messages)
        assert not all(m == "None" for m in messages)

    def test_matching_custom_permissions_do_not_log_or_raise(self, tmp_path):
        """A matching non-default mode is accepted even with a logger."""
        file_path = tmp_path / "custom.txt"
        file_path.write_text("data")
        logger = MagicMock(spec=logging.Logger)
        os.chmod(file_path, 0o640)

        verify_secure_permissions(file_path, expected_permissions=0o640, logger=logger)

        logger.error.assert_not_called()

    def test_permission_check_ignores_file_type_bits(self, tmp_path):
        """Permission verification compares only the mode bits, not file type bits."""
        file_path = tmp_path / "regular.txt"
        file_path.write_text("data")
        os.chmod(file_path, 0o600)

        verify_secure_permissions(file_path, expected_permissions=0o600)
