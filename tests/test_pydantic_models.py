"""Tests for Pydantic models validation and serialization."""

import base64
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from perplexity_cli.api.models import FileAttachment, QueryParams
from perplexity_cli.auth.models import CookieData, TokenFormat, TokenMetadata
from perplexity_cli.threads.models import CacheContent, CacheFormat, CacheMetadata
from perplexity_cli.utils.rate_limiter_models import (
    RateLimiterConfig,
    RateLimiterState,
    RateLimiterStats,
)


class TestTokenFormat:
    """Test TokenFormat model."""

    def test_token_format_creation_valid(self):
        """Test TokenFormat creation with valid data."""
        token_fmt = TokenFormat(
            version=2,
            encrypted=True,
            token="test-token-123",
            created_at=datetime.now(),
        )
        assert token_fmt.version == 2
        assert token_fmt.encrypted is True
        assert token_fmt.token == "test-token-123"
        assert token_fmt.cookies is None

    def test_token_format_with_cookies(self):
        """Test TokenFormat with encrypted cookies."""
        token_fmt = TokenFormat(
            token="test-token",
            cookies="encrypted-cookies-string",
        )
        assert token_fmt.token == "test-token"
        assert token_fmt.cookies == "encrypted-cookies-string"

    def test_token_format_empty_token_rejected(self):
        """Test that empty tokens are rejected."""
        with pytest.raises(ValidationError):
            TokenFormat(token="")

    def test_token_format_future_created_at_rejected(self):
        """Test that future created_at is rejected."""
        future = datetime.now() + timedelta(days=1)
        with pytest.raises(ValidationError):
            TokenFormat(token="test", created_at=future)

    def test_token_format_version_bounds(self):
        """Test version field bounds."""
        # Valid versions
        TokenFormat(token="test", version=1)
        TokenFormat(token="test", version=2)

        # Invalid version
        with pytest.raises(ValidationError):
            TokenFormat(token="test", version=3)


class TestCacheMetadata:
    """Test CacheMetadata model."""

    def test_cache_metadata_creation(self):
        """Test CacheMetadata creation."""
        metadata = CacheMetadata(
            last_sync_time=datetime.now(),
            oldest_thread_date="2025-01-01",
            newest_thread_date="2025-01-15",
            total_threads=42,
        )
        assert metadata.total_threads == 42
        assert metadata.oldest_thread_date == "2025-01-01"

    def test_cache_metadata_future_sync_rejected(self):
        """Test that future sync time is rejected."""
        future = datetime.now() + timedelta(hours=1)
        with pytest.raises(ValidationError):
            CacheMetadata(last_sync_time=future)

    def test_cache_metadata_negative_threads_rejected(self):
        """Test that negative thread count is rejected."""
        with pytest.raises(ValidationError):
            CacheMetadata(
                last_sync_time=datetime.now(),
                total_threads=-1,
            )


class TestCacheFormat:
    """Test CacheFormat model."""

    def test_cache_format_creation(self):
        """Test CacheFormat creation."""
        cache_fmt = CacheFormat(
            version=1,
            encrypted=True,
            cache="encrypted-cache-string",
        )
        assert cache_fmt.version == 1
        assert cache_fmt.encrypted is True

    def test_cache_format_empty_cache_rejected(self):
        """Test that empty cache is rejected."""
        with pytest.raises(ValidationError):
            CacheFormat(cache="")

    def test_cache_format_future_created_at_rejected(self):
        """Test that future created_at is rejected."""
        future = datetime.now() + timedelta(days=1)
        with pytest.raises(ValidationError):
            CacheFormat(
                cache="test",
                created_at=future,
            )


class TestCacheContent:
    """Test CacheContent model."""

    def test_cache_content_creation(self):
        """Test CacheContent creation."""
        metadata = CacheMetadata(
            last_sync_time=datetime.now(),
            total_threads=2,
        )
        content = CacheContent(
            version=1,
            metadata=metadata,
            threads=[
                {
                    "url": "https://example.com/thread1",
                    "title": "Thread 1",
                    "created_at": "2025-01-15",
                },
                {
                    "url": "https://example.com/thread2",
                    "title": "Thread 2",
                    "created_at": "2025-01-14",
                },
            ],
        )
        assert len(content.threads) == 2
        assert content.metadata.total_threads == 2

    def test_cache_content_thread_missing_url_rejected(self):
        """Test that thread without URL is rejected."""
        metadata = CacheMetadata(last_sync_time=datetime.now())
        with pytest.raises(ValidationError):
            CacheContent(
                metadata=metadata,
                threads=[{"title": "No URL"}],
            )

    def test_cache_content_thread_missing_title_rejected(self):
        """Test that thread without title is rejected."""
        metadata = CacheMetadata(last_sync_time=datetime.now())
        with pytest.raises(ValidationError):
            CacheContent(
                metadata=metadata,
                threads=[{"url": "https://example.com"}],
            )


class TestCookieData:
    """Test CookieData model."""

    def test_cookie_data_creation(self):
        """Test CookieData creation."""
        cookie = CookieData(
            name="session_id",
            value="abc123",
            domain=".example.com",
            secure=True,
        )
        assert cookie.name == "session_id"
        assert cookie.value == "abc123"
        assert cookie.secure is True

    def test_cookie_data_empty_name_rejected(self):
        """Test that empty cookie name is rejected."""
        with pytest.raises(ValidationError):
            CookieData(name="")

    def test_cookie_data_default_value(self):
        """Test cookie with default value."""
        cookie = CookieData(name="empty_cookie")
        assert cookie.value == ""


class TestTokenMetadata:
    """Test TokenMetadata model."""

    def test_token_metadata_creation(self):
        """Test TokenMetadata creation."""
        metadata = TokenMetadata(
            is_encrypted=True,
            has_cookies=False,
            age_days=5,
            version=2,
        )
        assert metadata.age_days == 5
        assert metadata.has_cookies is False

    def test_token_metadata_negative_age_rejected(self):
        """Test that negative age is rejected."""
        with pytest.raises(ValidationError):
            TokenMetadata(age_days=-1)


class TestRateLimiterConfig:
    """Test RateLimiterConfig model."""

    def test_rate_limiter_config_creation(self):
        """Test RateLimiterConfig creation."""
        config = RateLimiterConfig(
            requests_per_period=20,
            period_seconds=60.0,
        )
        assert config.requests_per_period == 20
        assert config.period_seconds == 60.0

    def test_rate_limiter_config_zero_requests_rejected(self):
        """Test that zero requests is rejected."""
        with pytest.raises(ValidationError):
            RateLimiterConfig(
                requests_per_period=0,
                period_seconds=60.0,
            )

    def test_rate_limiter_config_zero_period_rejected(self):
        """Test that zero period is rejected."""
        with pytest.raises(ValidationError):
            RateLimiterConfig(
                requests_per_period=10,
                period_seconds=0.0,
            )


class TestRateLimiterState:
    """Test RateLimiterState model."""

    def test_rate_limiter_state_creation(self):
        """Test RateLimiterState creation."""
        now = datetime.now().timestamp()
        state = RateLimiterState(
            tokens=10.0,
            last_refill_time=now,
            requests_per_period=20,
            period_seconds=60.0,
        )
        assert state.tokens == 10.0

    def test_rate_limiter_state_negative_tokens_rejected(self):
        """Test that negative tokens are rejected."""
        with pytest.raises(ValidationError):
            RateLimiterState(
                tokens=-1.0,
                last_refill_time=datetime.now().timestamp(),
                requests_per_period=20,
                period_seconds=60.0,
            )


class TestRateLimiterStats:
    """Test RateLimiterStats model."""

    def test_rate_limiter_stats_creation(self):
        """Test RateLimiterStats creation."""
        stats = RateLimiterStats(
            total_requests=100,
            total_wait_time=5.0,
        )
        assert stats.total_requests == 100
        assert stats.total_wait_time == 5.0

    def test_rate_limiter_stats_from_data(self):
        """Test RateLimiterStats creation from raw data."""
        stats = RateLimiterStats.from_data(
            total_requests=100,
            total_wait_time=10.0,
        )
        assert stats.total_requests == 100
        assert stats.average_wait_time == 0.1  # 10.0 / 100

    def test_rate_limiter_stats_zero_requests_average(self):
        """Test average wait time with zero requests."""
        stats = RateLimiterStats.from_data(
            total_requests=0,
            total_wait_time=0.0,
        )
        assert stats.average_wait_time == 0.0

    def test_rate_limiter_stats_negative_rejected(self):
        """Test that negative stats are rejected."""
        with pytest.raises(ValidationError):
            RateLimiterStats(
                total_requests=-1,
                total_wait_time=0.0,
            )


class TestFileAttachment:
    """Test FileAttachment model."""

    def test_file_attachment_creation_valid(self):
        """Test FileAttachment creation with valid data."""
        encoded_data = base64.b64encode(b"test content").decode("ascii")
        attachment = FileAttachment(
            filename="test.txt",
            content_type="text/plain",
            data=encoded_data,
        )
        assert attachment.filename == "test.txt"
        assert attachment.content_type == "text/plain"
        assert attachment.data == encoded_data

    def test_file_attachment_empty_filename_rejected(self):
        """Test that empty filename is rejected."""
        encoded_data = base64.b64encode(b"test").decode("ascii")
        with pytest.raises(ValidationError) as exc_info:
            FileAttachment(
                filename="",
                content_type="text/plain",
                data=encoded_data,
            )
        assert "non-empty" in str(exc_info.value).lower()

    def test_file_attachment_long_filename_rejected(self):
        """Test that filename exceeding 255 characters is rejected."""
        encoded_data = base64.b64encode(b"test").decode("ascii")
        long_name = "a" * 256 + ".txt"
        with pytest.raises(ValidationError):
            FileAttachment(
                filename=long_name,
                content_type="text/plain",
                data=encoded_data,
            )

    def test_file_attachment_empty_content_type_rejected(self):
        """Test that empty content_type is rejected."""
        encoded_data = base64.b64encode(b"test").decode("ascii")
        with pytest.raises(ValidationError):
            FileAttachment(
                filename="test.txt",
                content_type="",
                data=encoded_data,
            )

    def test_file_attachment_invalid_base64_rejected(self):
        """Test that invalid base64 data is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            FileAttachment(
                filename="test.txt",
                content_type="text/plain",
                data="not-valid-base64!!!",
            )
        assert "base64" in str(exc_info.value).lower()

    def test_file_attachment_serialization(self):
        """Test FileAttachment serialization to dict."""
        encoded_data = base64.b64encode(b"test content").decode("ascii")
        attachment = FileAttachment(
            filename="test.txt",
            content_type="text/plain",
            data=encoded_data,
        )
        data_dict = attachment.model_dump()
        assert data_dict["filename"] == "test.txt"
        assert data_dict["content_type"] == "text/plain"
        assert data_dict["data"] == encoded_data

    def test_file_attachment_in_query_params(self):
        """Test S3 URL attachment integration with QueryParams."""
        s3_url = "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/test.txt"
        params = QueryParams(attachments=[s3_url])
        assert len(params.attachments) == 1
        assert params.attachments[0] == s3_url

    def test_file_attachment_multiple_in_query_params(self):
        """Test multiple S3 URL attachments in QueryParams."""
        s3_urls = [
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file1.txt",
            "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/file2.txt",
        ]
        params = QueryParams(attachments=s3_urls)
        assert len(params.attachments) == 2
        assert params.attachments[0] == s3_urls[0]
        assert params.attachments[1] == s3_urls[1]

    def test_file_attachment_serialization_in_request_dict(self):
        """Test that S3 URL attachments are properly serialized in request dict."""
        s3_url = "https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/test.txt"
        params = QueryParams(attachments=[s3_url])
        request_dict = params.to_dict()
        assert "attachments" in request_dict
        assert len(request_dict["attachments"]) == 1
        assert request_dict["attachments"][0] == s3_url


class TestQueryParamsSearchMode:
    """Test QueryParams search_implementation_mode field."""

    def test_search_mode_default_is_standard(self):
        """Test that search_implementation_mode defaults to 'standard'."""
        params = QueryParams()
        assert params.search_implementation_mode == "standard"

    def test_search_mode_standard_accepted(self):
        """Test that 'standard' mode is accepted."""
        params = QueryParams(search_implementation_mode="standard")
        assert params.search_implementation_mode == "standard"

    def test_search_mode_multi_step_accepted(self):
        """Test that 'multi_step' mode is accepted."""
        params = QueryParams(search_implementation_mode="multi_step")
        assert params.search_implementation_mode == "multi_step"

    def test_search_mode_invalid_rejected(self):
        """Test that invalid modes are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            QueryParams(search_implementation_mode="invalid_mode")
        assert "standard" in str(exc_info.value)
        assert "multi_step" in str(exc_info.value)

    def test_search_mode_serialization(self):
        """Test that search_implementation_mode is serialized correctly."""
        params = QueryParams(search_implementation_mode="multi_step")
        data = params.to_dict()
        assert data["search_implementation_mode"] == "multi_step"

    def test_search_mode_in_request_dict(self):
        """Test that search_implementation_mode is included in API request dict."""
        params = QueryParams(search_implementation_mode="multi_step")
        request_dict = params.to_dict()
        assert "search_implementation_mode" in request_dict
        assert request_dict["search_implementation_mode"] == "multi_step"
