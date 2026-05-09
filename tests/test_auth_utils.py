"""Tests for authentication utility functions."""

import json
import logging
from unittest.mock import Mock

import pytest

from perplexity_cli.auth.utils import (
    extract_session_token,
    load_or_prompt_token,
    load_token_optional,
)
from perplexity_cli.utils.exceptions import AuthenticationError


class TestExtractSessionToken:
    """Tests for extract_session_token()."""

    def test_returns_raw_token_when_not_json(self):
        """Test that a non-JSON string is returned as-is."""
        token = extract_session_token("raw-jwt-token-string")
        assert token == "raw-jwt-token-string"

    def test_returns_access_token_from_valid_json(self):
        """Test extraction of accessToken from valid JSON structure."""
        raw = json.dumps({"user": {"accessToken": "extracted-token"}})
        assert extract_session_token(raw) == "extracted-token"

    def test_raises_when_token_data_is_not_dict(self):
        """Test that non-dict JSON (e.g. a list) raises AuthenticationError."""
        raw = json.dumps(["not", "a", "dict"])
        with pytest.raises(AuthenticationError, match="invalid session data format"):
            extract_session_token(raw)

    def test_returns_raw_when_user_data_is_none(self):
        """Test that missing 'user' key returns the raw token."""
        raw = json.dumps({"other_key": "value"})
        assert extract_session_token(raw) == raw

    def test_raises_when_user_data_is_not_dict(self):
        """Test that non-dict user data raises AuthenticationError."""
        raw = json.dumps({"user": "not-a-dict"})
        with pytest.raises(AuthenticationError, match="invalid session user data"):
            extract_session_token(raw)

    def test_returns_raw_when_access_token_is_none(self):
        """Test that missing accessToken returns the raw token."""
        raw = json.dumps({"user": {"email": "test@example.com"}})
        assert extract_session_token(raw) == raw

    def test_raises_when_access_token_is_empty_string(self):
        """Test that empty accessToken raises AuthenticationError."""
        raw = json.dumps({"user": {"accessToken": ""}})
        with pytest.raises(AuthenticationError, match="invalid access token data"):
            extract_session_token(raw)

    def test_raises_when_access_token_is_not_string(self):
        """Test that non-string accessToken raises AuthenticationError."""
        raw = json.dumps({"user": {"accessToken": 12345}})
        with pytest.raises(AuthenticationError, match="invalid access token data"):
            extract_session_token(raw)


class TestLoadOrPromptToken:
    """Tests for load_or_prompt_token()."""

    def test_returns_token_and_cookies_on_success(self):
        """Test successful token loading returns tuple."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = ("token-abc", {"cookie": "val"})
        logger = logging.getLogger("test")

        token, cookies = load_or_prompt_token(mock_tm, logger)

        assert token == "token-abc"
        assert cookies == {"cookie": "val"}

    def test_exits_on_authentication_error(self, capsys):
        """Test that AuthenticationError causes sys.exit(1)."""
        mock_tm = Mock()
        mock_tm.load_token.side_effect = AuthenticationError("corrupt token")
        logger = logging.getLogger("test")

        with pytest.raises(SystemExit) as exc_info:
            load_or_prompt_token(mock_tm, logger, command_context="query")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Authentication error: corrupt token" in captured.err
        assert "pxcli auth" in captured.err

    def test_exits_when_token_is_none(self, capsys):
        """Test that None token causes sys.exit(1)."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        logger = logging.getLogger("test")

        with pytest.raises(SystemExit) as exc_info:
            load_or_prompt_token(mock_tm, logger, command_context="export")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Not authenticated" in captured.err

    def test_exits_when_token_is_empty_string(self, capsys):
        """Test that empty string token causes sys.exit(1)."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = ("", None)
        logger = logging.getLogger("test")

        with pytest.raises(SystemExit) as exc_info:
            load_or_prompt_token(mock_tm, logger)

        assert exc_info.value.code == 1


class TestLoadTokenOptionalErrors:
    """Tests for load_token_optional() error paths."""

    def test_returns_none_on_authentication_error(self):
        """Test that AuthenticationError returns (None, None) without exiting."""
        mock_tm = Mock()
        mock_tm.load_token.side_effect = AuthenticationError("bad state")
        logger = logging.getLogger("test")

        token, cookies = load_token_optional(mock_tm, logger)

        assert token is None
        assert cookies is None
