"""Tests for session-token parsing helpers."""

from __future__ import annotations

import json

import pytest

from perplexity_cli.utils.exceptions import AuthenticationError
from perplexity_cli.utils.session_token import extract_session_token

_RAW_SENTINEL = "raw-session-sentinel"


class TestExtractSessionToken:
    """Tests for extract_session_token over its public boundary."""

    def test_non_json_payload_returned_verbatim(self):
        """Payloads that are not JSON come back unchanged."""
        assert extract_session_token(_RAW_SENTINEL) == _RAW_SENTINEL

    def test_json_without_user_key_returned_verbatim(self):
        """JSON objects without a user section come back unchanged."""
        raw = json.dumps({"other": "value"})
        assert extract_session_token(raw) == raw

    def test_user_without_access_token_returned_verbatim(self):
        """A user object lacking accessToken falls back to the raw payload."""
        raw = json.dumps({"user": {"name": "someone"}})
        assert extract_session_token(raw) == raw

    def test_access_token_extracted_from_user_object(self):
        """The nested accessToken is returned when present."""
        raw = json.dumps({"user": {"accessToken": _RAW_SENTINEL}})
        assert extract_session_token(raw) == _RAW_SENTINEL

    def test_non_dict_json_payload_raises_authentication_error(self):
        """Non-object JSON is rejected with the session-format error."""
        with pytest.raises(AuthenticationError) as excinfo:
            extract_session_token(json.dumps(["not", "an", "object"]))
        message = str(excinfo.value)
        assert message.startswith("Stored token has")
        assert message.endswith("session data format")

    def test_non_dict_user_section_raises_authentication_error(self):
        """A non-object user section is rejected with the user-data error."""
        raw = json.dumps({"user": "just-a-string"})
        with pytest.raises(AuthenticationError) as excinfo:
            extract_session_token(raw)
        message = str(excinfo.value)
        assert message.startswith("Stored token has")
        assert message.endswith("session user data")

    def test_non_string_access_token_raises_authentication_error(self):
        """A non-string accessToken is rejected with the token-data error."""
        raw = json.dumps({"user": {"accessToken": 12345}})
        with pytest.raises(AuthenticationError) as excinfo:
            extract_session_token(raw)
        message = str(excinfo.value)
        assert message.startswith("Stored token has")
        assert message.endswith("access token data")

    def test_empty_access_token_raises_authentication_error(self):
        """An empty accessToken string is rejected like any invalid value."""
        raw = json.dumps({"user": {"accessToken": ""}})
        with pytest.raises(AuthenticationError):
            extract_session_token(raw)
