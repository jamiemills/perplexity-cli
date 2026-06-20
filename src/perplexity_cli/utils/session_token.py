"""Session-token parsing helpers."""

from __future__ import annotations

import json
from typing import TypeGuard

from perplexity_cli.utils.exceptions import AuthenticationError


def _is_str_dict(obj: object) -> TypeGuard[dict[str, object]]:
    """Narrow an object to ``dict[str, object]`` for pyright strict mode."""
    return isinstance(obj, dict)


def extract_session_token(raw_token: str) -> str:
    """Extract a usable session token from the raw decrypted token data."""
    try:
        token_data = json.loads(raw_token)
    except json.JSONDecodeError:
        return raw_token

    if not _is_str_dict(token_data):
        raise AuthenticationError("Stored token has invalid session data format")

    return _extract_access_token_from_json(token_data, raw_token)


def _extract_access_token_from_json(token_data: dict[str, object], raw_token: str) -> str:
    """Extract the access token from parsed JSON token data."""
    user_data = token_data.get("user")
    if user_data is None:
        return raw_token

    if not _is_str_dict(user_data):
        raise AuthenticationError("Stored token has invalid session user data")

    return _validate_access_token(user_data, raw_token)


def _validate_access_token(user_data: dict[str, object], raw_token: str) -> str:
    """Validate and return the access token from user data."""
    access_token = user_data.get("accessToken")
    if access_token is None:
        return raw_token

    if not isinstance(access_token, str) or not access_token:
        raise AuthenticationError("Stored token has invalid access token data")

    return access_token
