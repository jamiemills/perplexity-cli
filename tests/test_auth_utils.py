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
        assert "pxcli auth login" in captured.err

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


T009_APP_LOGGER = "perplexity_cli"
T009_REDACTED_EMPTY = "<redacted:0 chars>"


def t009_level_records(caplog: pytest.LogCaptureFixture, level: int) -> list[logging.LogRecord]:
    """Return captured records at an exact level from any logger."""
    return [r for r in caplog.records if r.levelno == level]


class TestT009LoadOrPromptTokenDiagnostics:
    """Diagnostics coverage for load_or_prompt_token() (task T009)."""

    @pytest.fixture
    def t009_app_logger(self, caplog: pytest.LogCaptureFixture) -> logging.Logger:
        """Capture DEBUG-and-above records on the application logger."""
        caplog.set_level(logging.DEBUG, logger=T009_APP_LOGGER)
        return logging.getLogger(T009_APP_LOGGER)

    def test_authentication_error_echoes_recovery_line_and_warns(
        self,
        t009_app_logger: logging.Logger,
        caplog: pytest.LogCaptureFixture,
        capsys: pytest.CaptureFixture[str],
    ):
        """Default context, recovery line on stderr, redacted warning args."""
        mock_tm = Mock()
        mock_tm.load_token.side_effect = AuthenticationError("boom")

        with pytest.raises(SystemExit) as exc_info:
            load_or_prompt_token(mock_tm, t009_app_logger)

        assert exc_info.value.code == 1
        err_lines = capsys.readouterr().err.splitlines()
        assert "[ERROR] Authentication error: boom" in err_lines
        assert "Please authenticate again with: pxcli auth login" in err_lines

        warnings = t009_level_records(caplog, logging.WARNING)
        assert len(warnings) == 1
        assert warnings[0].msg == "Authentication state invalid during %s: %s"
        assert warnings[0].args == ("operation", T009_REDACTED_EMPTY)

    def test_authentication_error_with_empty_message_redacts_as_empty(
        self, t009_app_logger: logging.Logger, caplog: pytest.LogCaptureFixture
    ):
        """An empty exception message redacts to the empty sentinel."""
        mock_tm = Mock()
        mock_tm.load_token.side_effect = AuthenticationError("")

        with pytest.raises(SystemExit):
            load_or_prompt_token(mock_tm, t009_app_logger)

        warnings = t009_level_records(caplog, logging.WARNING)
        assert len(warnings) == 1
        assert warnings[0].args == ("operation", "<empty>")

    def test_not_authenticated_writes_guidance_to_stderr_and_warns(
        self,
        t009_app_logger: logging.Logger,
        caplog: pytest.LogCaptureFixture,
        capsys: pytest.CaptureFixture[str],
    ):
        """Missing-token guidance goes to stderr only, with context warning."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)

        with pytest.raises(SystemExit) as exc_info:
            load_or_prompt_token(mock_tm, t009_app_logger, command_context="query")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        err_lines = captured.err.splitlines()
        assert "[ERROR] Not authenticated." in err_lines
        assert "Please authenticate first with: pxcli auth login" in err_lines
        assert "pxcli auth login" not in captured.out

        warnings = t009_level_records(caplog, logging.WARNING)
        assert len(warnings) == 1
        assert warnings[0].msg == "Attempted %s without authentication"
        assert warnings[0].args == ("query",)


class TestT009LoadTokenOptionalDiagnostics:
    """Diagnostics coverage for load_token_optional() (task T009)."""

    @pytest.fixture
    def t009_app_logger(self, caplog: pytest.LogCaptureFixture) -> logging.Logger:
        """Capture DEBUG-and-above records on the application logger."""
        caplog.set_level(logging.DEBUG, logger=T009_APP_LOGGER)
        return logging.getLogger(T009_APP_LOGGER)

    def test_error_path_warns_with_fully_redacted_detail(
        self, t009_app_logger: logging.Logger, caplog: pytest.LogCaptureFixture
    ):
        """The unusable-token warning carries a fully redacted detail arg."""
        mock_tm = Mock()
        mock_tm.load_token.side_effect = AuthenticationError("boom")

        result = load_token_optional(mock_tm, t009_app_logger)

        assert result == (None, None)
        warnings = t009_level_records(caplog, logging.WARNING)
        assert len(warnings) == 1
        assert warnings[0].msg == (
            "Stored token is unusable; proceeding without authentication: %s"
        )
        assert warnings[0].args == (T009_REDACTED_EMPTY,)

    def test_error_path_with_empty_message_redacts_as_empty(
        self, t009_app_logger: logging.Logger, caplog: pytest.LogCaptureFixture
    ):
        """An empty exception message redacts to the empty sentinel."""
        mock_tm = Mock()
        mock_tm.load_token.side_effect = AuthenticationError("")

        result = load_token_optional(mock_tm, t009_app_logger)

        assert result == (None, None)
        warnings = t009_level_records(caplog, logging.WARNING)
        assert len(warnings) == 1
        assert warnings[0].args == ("<empty>",)

    def test_success_path_logs_loaded_debug(
        self, t009_app_logger: logging.Logger, caplog: pytest.LogCaptureFixture
    ):
        """A loaded token logs exactly one loaded debug note."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = ("tok", {"k": "v"})

        result = load_token_optional(mock_tm, t009_app_logger)

        assert result == ("tok", {"k": "v"})
        debugs = t009_level_records(caplog, logging.DEBUG)
        assert len(debugs) == 1
        assert debugs[0].msg == "Authentication token loaded"

    def test_absent_token_logs_absent_debug(
        self, t009_app_logger: logging.Logger, caplog: pytest.LogCaptureFixture
    ):
        """An absent token logs exactly one absent debug note."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)

        result = load_token_optional(mock_tm, t009_app_logger)

        assert result == (None, None)
        debugs = t009_level_records(caplog, logging.DEBUG)
        assert len(debugs) == 1
        assert debugs[0].msg == ("No authentication token found; proceeding without authentication")
