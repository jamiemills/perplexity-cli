"""Pydantic models for authentication and token storage."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


class TokenFormat(BaseModel):
    """Token storage format with encryption metadata.

    Represents the JSON structure stored in the token file.
    Supports both v1 (token only) and v2 (token + cookies) formats.
    """

    model_config = ConfigDict(ser_json_timedelta="float")

    version: int = Field(default=2, ge=1, le=2)
    encrypted: bool = Field(default=True)
    token: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.now)
    cookies: str | None = Field(default=None)

    @field_validator("token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        """Validate token is not empty."""
        if not v or not isinstance(v, str):
            raise ValueError("Token must be a non-empty string")
        if not v.strip():
            raise ValueError("Token cannot be whitespace-only")
        return v

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, v: datetime) -> datetime:
        """Validate created_at is not in the future."""
        if v > datetime.now():
            raise ValueError("created_at cannot be in the future")
        return v

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        """Serialize datetime to ISO format string."""
        return value.isoformat()


class CookieData(BaseModel):
    """Browser cookie data structure."""

    name: str = Field(..., min_length=1)
    value: str = Field(default="")
    domain: str | None = Field(default=None)
    path: str | None = Field(default=None)
    secure: bool = Field(default=False)
    httponly: bool = Field(default=False)
    expires: str | None = Field(default=None)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate cookie name is not empty."""
        if not v or not v.strip():
            raise ValueError("Cookie name cannot be empty")
        return v


class TokenMetadata(BaseModel):
    """Metadata about stored token."""

    is_encrypted: bool = Field(default=True)
    has_cookies: bool = Field(default=False)
    age_days: int | None = Field(default=None)
    version: int = Field(default=2, ge=1, le=2)
    created_at: datetime | None = Field(default=None)

    @field_validator("age_days")
    @classmethod
    def validate_age_days(cls, v: int | None) -> int | None:
        """Validate age_days is non-negative if provided."""
        if v is not None and v < 0:
            raise ValueError("age_days cannot be negative")
        return v
