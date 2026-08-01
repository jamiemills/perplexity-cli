"""Tests for perplexity_cli.config.models."""

import pytest
from pydantic import ValidationError

from perplexity_cli.config.models import FeatureConfig, RateLimitConfig, URLConfig


class TestURLConfig:
    """Tests for URLConfig model."""

    def test_defaults(self):
        cfg = URLConfig()
        assert cfg.base_url == "https://www.perplexity.ai"
        assert cfg.query_endpoint == "https://www.perplexity.ai/rest/sse/perplexity_ask"
        assert cfg.thread_list_endpoint == "https://www.perplexity.ai/rest/thread/list_ask_threads"
        assert (
            cfg.upload_url_endpoint
            == "https://www.perplexity.ai/rest/uploads/batch_create_upload_urls"
        )
        assert cfg.s3_bucket_url == "https://ppl-ai-file-upload.s3.amazonaws.com/"

    def test_custom_values(self):
        cfg = URLConfig(
            base_url="https://custom.example.com",
            query_endpoint="https://custom.example.com/query",
            thread_list_endpoint="https://custom.example.com/threads",
            upload_url_endpoint="https://custom.example.com/upload",
            s3_bucket_url="https://custom.example.com/s3/",
        )
        assert cfg.base_url == "https://custom.example.com"
        assert cfg.query_endpoint == "https://custom.example.com/query"
        assert cfg.thread_list_endpoint == "https://custom.example.com/threads"
        assert cfg.upload_url_endpoint == "https://custom.example.com/upload"
        assert cfg.s3_bucket_url == "https://custom.example.com/s3/"

    def test_empty_url_raises(self):
        with pytest.raises(ValidationError):
            URLConfig(base_url="")

    def test_whitespace_url_raises(self):
        with pytest.raises(ValidationError):
            URLConfig(query_endpoint="   ")

    def test_surrounding_whitespace_normalised(self):
        cfg = URLConfig(base_url="  https://www.perplexity.ai  ")
        assert cfg.base_url == "https://www.perplexity.ai"


class TestURLConfigValidation:
    """Tests for the URLConfig URL validation contract."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.perplexity.ai",
            "https://www.perplexity.ai/rest/sse/perplexity_ask",
            "https://ppl-ai-file-upload.s3.amazonaws.com/",
            "https://custom.example.com",
            "https://custom.example.com/query?param=1",
            "https://single-label-host",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
            "http://127.0.0.0",
            "http://127.255.255.255",
            "http://[::1]:8080",
            "http://[::1]",
        ],
    )
    def test_accepts_valid_urls(self, url):
        cfg = URLConfig(base_url=url)
        assert cfg.base_url == url

    @pytest.mark.parametrize(
        "url",
        [
            "/api/custom/endpoint",
            "api/custom/endpoint",
            "www.perplexity.ai",
            "//example.com/path",
            "ftp://example.com",
            "file:///etc/passwd",
            "https://",
            "https:///path",
            "https://user:pass@example.com",
            "https://user@example.com",
            "https://example.com#fragment",
            "https://example.com/path#frag",
            "https://exa mple.com",
            "https://example.com/pa th",
            "https://example.com\\path",
            "http://example.com",
            "http://www.perplexity.ai",
            "http://10.0.0.1",
            "https://example.com/\x01",
        ],
    )
    def test_rejects_invalid_urls(self, url):
        with pytest.raises(ValidationError):
            URLConfig(base_url=url)


class TestRateLimitConfig:
    """Tests for RateLimitConfig model."""

    def test_defaults(self):
        cfg = RateLimitConfig()
        assert cfg.enabled is True
        assert cfg.requests_per_period == 20
        assert cfg.period_seconds == pytest.approx(60.0)

    def test_zero_requests_raises(self):
        with pytest.raises(ValidationError):
            RateLimitConfig(requests_per_period=0)

    def test_negative_period_raises(self):
        with pytest.raises(ValidationError):
            RateLimitConfig(period_seconds=-1)


class TestFeatureConfig:
    """Tests for FeatureConfig model."""

    def test_defaults(self):
        cfg = FeatureConfig()
        assert cfg.save_cookies is False
        assert cfg.debug_mode is False

    def test_set_values(self):
        cfg = FeatureConfig(save_cookies=True, debug_mode=True)
        assert cfg.save_cookies is True
        assert cfg.debug_mode is True

    def test_serialisation_round_trip(self):
        original = FeatureConfig(save_cookies=True, debug_mode=True)
        dumped = original.model_dump()
        restored = FeatureConfig.model_validate(dumped)
        assert restored.save_cookies == original.save_cookies
        assert restored.debug_mode == original.debug_mode
