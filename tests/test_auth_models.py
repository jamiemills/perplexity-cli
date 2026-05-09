"""Tests for authentication Pydantic models."""

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from perplexity_cli.auth.models import CookieData, TokenFormat, TokenMetadata


class TestTokenFormat:
    """Tests for TokenFormat model."""

    def test_valid_token_format(self):
        """Test creation with valid data and check all fields."""
        now = datetime.now()
        tf = TokenFormat(token="abc123", version=1, encrypted=False, created_at=now, cookies="c")
        assert tf.token == "abc123"
        assert tf.version == 1
        assert tf.encrypted is False
        assert tf.created_at == now
        assert tf.cookies == "c"

    def test_default_version_is_2(self):
        """Test that default version is 2."""
        tf = TokenFormat(token="abc123")
        assert tf.version == 2

    def test_default_encrypted_is_true(self):
        """Test that default encrypted is True."""
        tf = TokenFormat(token="abc123")
        assert tf.encrypted is True

    def test_token_cannot_be_empty(self):
        """Test that empty token raises ValidationError."""
        with pytest.raises(ValidationError):
            TokenFormat(token="")

    def test_token_cannot_be_whitespace(self):
        """Test that whitespace-only token raises ValidationError."""
        with pytest.raises(ValidationError):
            TokenFormat(token="   ")

    def test_created_at_cannot_be_future(self):
        """Test that a future created_at raises ValidationError."""
        future = datetime.now() + timedelta(days=1)
        with pytest.raises(ValidationError):
            TokenFormat(token="abc123", created_at=future)

    def test_serialisation_round_trip(self):
        """Test that model_dump then model_validate preserves fields."""
        tf = TokenFormat(token="abc123", version=1, encrypted=False)
        data = tf.model_dump()
        restored = TokenFormat.model_validate(data)
        assert restored.token == tf.token
        assert restored.version == tf.version
        assert restored.encrypted == tf.encrypted

    def test_cookies_optional(self):
        """Test that cookies defaults to None."""
        tf = TokenFormat(token="abc123")
        assert tf.cookies is None


class TestCookieData:
    """Tests for CookieData model."""

    def test_valid_cookie(self):
        """Test creation with valid data."""
        cd = CookieData(name="session", value="xyz", domain=".example.com", path="/", secure=True)
        assert cd.name == "session"
        assert cd.value == "xyz"
        assert cd.domain == ".example.com"
        assert cd.secure is True

    def test_name_cannot_be_empty(self):
        """Test that empty name raises ValidationError."""
        with pytest.raises(ValidationError):
            CookieData(name="")

    def test_defaults(self):
        """Test default values for optional fields."""
        cd = CookieData(name="sid")
        assert cd.value == ""
        assert cd.secure is False
        assert cd.httponly is False


class TestTokenMetadata:
    """Tests for TokenMetadata model."""

    def test_valid_metadata(self):
        """Test creation with valid data."""
        now = datetime.now()
        tm = TokenMetadata(
            is_encrypted=False, has_cookies=True, age_days=5, version=1, created_at=now
        )
        assert tm.is_encrypted is False
        assert tm.has_cookies is True
        assert tm.age_days == 5
        assert tm.version == 1
        assert tm.created_at == now

    def test_age_days_cannot_be_negative(self):
        """Test that negative age_days raises ValidationError."""
        with pytest.raises(ValidationError):
            TokenMetadata(age_days=-1)

    def test_defaults(self):
        """Test default values."""
        tm = TokenMetadata()
        assert tm.is_encrypted is True
        assert tm.has_cookies is False
        assert tm.age_days is None
        assert tm.version == 2
