"""Pydantic models for thread cache management."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class CacheMetadata(BaseModel):
    """Cache metadata with date coverage information."""

    last_sync_time: datetime = Field(...)
    oldest_thread_date: str | None = Field(default=None)
    newest_thread_date: str | None = Field(default=None)
    total_threads: int = Field(default=0, ge=0)

    @field_validator("last_sync_time")
    @classmethod
    def validate_sync_time(cls, v: datetime) -> datetime:
        """Validate sync time is not in the future."""
        if v > datetime.now():
            raise ValueError("last_sync_time cannot be in the future")
        return v

    @field_validator("total_threads")
    @classmethod
    def validate_total_threads(cls, v: int) -> int:
        """Validate total_threads is non-negative."""
        if v < 0:
            raise ValueError("total_threads cannot be negative")
        return v


class CacheFormat(BaseModel):
    """Outer cache file format with encryption metadata."""

    version: int = Field(default=1, ge=1, le=1)
    encrypted: bool = Field(default=True)
    cache: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.now)

    @field_validator("cache")
    @classmethod
    def validate_cache(cls, v: str) -> str:
        """Validate encrypted cache is not empty."""
        if not v or not v.strip():
            raise ValueError("Encrypted cache cannot be empty")
        return v

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, v: datetime) -> datetime:
        """Validate created_at is not in the future."""
        if v > datetime.now():
            raise ValueError("created_at cannot be in the future")
        return v


class CacheContent(BaseModel):
    """Inner cache content (decrypted)."""

    version: int = Field(default=1, ge=1, le=1)
    metadata: CacheMetadata = Field(...)
    threads: list[dict] = Field(default_factory=list)

    @field_validator("threads")
    @classmethod
    def validate_threads(cls, v: list) -> list:
        """Validate threads list items have required structure."""
        for thread in v:
            if not isinstance(thread, dict):
                raise ValueError("Each thread must be a dictionary")
            if "url" not in thread:
                raise ValueError("Each thread must have a 'url' field")
            if "title" not in thread:
                raise ValueError("Each thread must have a 'title' field")
        return v
