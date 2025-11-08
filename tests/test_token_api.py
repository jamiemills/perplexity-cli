"""Test that the extracted token works with Perplexity API.

This module tests whether the token obtained from authentication
can be used to make actual API requests to Perplexity.
"""

import json

import httpx
import pytest

from perplexity_cli.auth.token_manager import TokenManager


@pytest.mark.integration
class TestTokenAPI:
    """Tests for token validity with Perplexity API."""

    @pytest.fixture
    def token(self):
        """Load token from storage."""
        tm = TokenManager()
        token = tm.load_token()
        if not token:
            pytest.skip("No token found. Run: python tests/save_auth_token.py")
        return token

    @pytest.fixture
    def headers(self, token):
        """Create authorization headers."""
        return {
            "Authorization": f"Bearer {token}",
            "User-Agent": "perplexity-cli/0.1.0",
            "Content-Type": "application/json",
        }

    def test_token_format(self, token):
        """Test that token has valid JWT format."""
        # Check length
        assert len(token) > 100, "Token should be at least 100 characters"

        # Check it looks like a JWT (starts with 'eyJ')
        assert token.startswith("eyJ"), "Token should start with 'eyJ' (JWT format)"

        # Check it has multiple parts (JWT structure)
        parts = token.split(".")
        assert len(parts) >= 2, f"JWT should have at least 2 parts, got {len(parts)}"

    def test_token_stored_correctly(self, token):
        """Test that token is stored in correct JSON format."""
        tm = TokenManager()

        # Verify file exists
        assert tm.token_exists(), "Token file should exist"

        # Load from file and verify structure
        with open(tm.token_path) as f:
            data = json.load(f)

        assert "token" in data, "Token file should have 'token' key"
        assert data["token"] == token, "Stored token should match loaded token"

    def test_api_user_endpoint(self, token, headers):
        """Test /api/user endpoint returns user profile."""
        with httpx.Client() as client:
            response = client.get(
                "https://www.perplexity.ai/api/user",
                headers=headers,
                timeout=10,
            )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        data = response.json()
        assert isinstance(data, dict), "Response should be a dictionary"
        assert "id" in data, "Response should have 'id' field"
        assert "username" in data, "Response should have 'username' field"
        assert "email" in data, "Response should have 'email' field"

    def test_api_session_endpoint(self, headers):
        """Test /api/auth/session endpoint is accessible."""
        with httpx.Client() as client:
            response = client.get(
                "https://www.perplexity.ai/api/auth/session",
                headers=headers,
                timeout=10,
            )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    def test_library_endpoint(self, headers):
        """Test /library endpoint is accessible."""
        with httpx.Client() as client:
            response = client.get(
                "https://www.perplexity.ai/library",
                headers=headers,
                timeout=10,
            )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    def test_token_not_expired(self, headers):
        """Test that token is not expired (no 401 errors)."""
        endpoints = [
            "https://www.perplexity.ai/api/user",
            "https://www.perplexity.ai/api/auth/session",
        ]

        with httpx.Client() as client:
            for endpoint in endpoints:
                response = client.get(endpoint, headers=headers, timeout=10)

                # 200 OK means token is valid and not expired
                # 401 would mean token is invalid or expired
                assert response.status_code != 401, f"{endpoint} returned 401: token may be expired"
                assert response.status_code == 200, f"{endpoint} returned {response.status_code}"

    def test_token_has_required_permissions(self, headers):
        """Test that token has required permissions to access protected endpoints."""
        # 403 would mean token is valid but lacks permissions
        # 200 means we have the necessary permissions
        with httpx.Client() as client:
            response = client.get(
                "https://www.perplexity.ai/api/user",
                headers=headers,
                timeout=10,
            )

        assert response.status_code != 403, "Token should have required permissions (got 403)"
        assert response.status_code == 200, "Token should be authorized for /api/user"


@pytest.mark.integration
def test_token_exists_and_loadable():
    """Test that a token exists and can be loaded."""
    tm = TokenManager()
    token = tm.load_token()

    if token is None:
        pytest.skip("No token found. Run: python tests/save_auth_token.py")

    assert isinstance(token, str), "Token should be a string"
    assert len(token) > 0, "Token should not be empty"


@pytest.mark.integration
def test_token_file_permissions():
    """Test that token file has secure permissions."""
    import os
    import stat

    tm = TokenManager()

    if not tm.token_exists():
        pytest.skip("No token file found. Run: python tests/save_auth_token.py")

    # Get file permissions
    file_stat = tm.token_path.stat()
    actual_permissions = stat.S_IMODE(file_stat.st_mode)

    # Should be 0600 (owner read/write only)
    assert actual_permissions == 0o600, f"Token file should have 0600 permissions, got {oct(actual_permissions)}"

    # Verify group/others cannot read
    assert (actual_permissions & stat.S_IRGRP) == 0, "Group should not be able to read token"
    assert (actual_permissions & stat.S_IROTH) == 0, "Others should not be able to read token"
