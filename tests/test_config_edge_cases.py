"""Tests for configuration edge cases including corrupt files, missing files, and env overrides."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from perplexity_cli.config.models import FeatureConfig, URLConfig
from perplexity_cli.utils.config import (
    clear_feature_config_cache,
    clear_urls_cache,
    get_feature_config,
    get_rate_limiting_config,
    get_urls,
)


class TestCorruptedConfigJson:
    """Test behaviour when config.json contains invalid JSON."""

    def test_corrupted_feature_config_uses_defaults(self, tmp_path, monkeypatch):
        """Test that corrupted config.json falls back to defaults."""
        clear_feature_config_cache()

        config_dir = tmp_path / ".config" / "perplexity-cli"
        config_dir.mkdir(parents=True)
        config_path = config_dir / "config.json"
        config_path.write_text("{invalid json content!!!", encoding="utf-8")

        monkeypatch.setattr(
            "perplexity_cli.utils.config.get_feature_config_path",
            lambda: config_path,
        )
        # Prevent _ensure_user_feature_config from overwriting our corrupt file
        monkeypatch.setattr(
            "perplexity_cli.utils.config._ensure_user_feature_config",
            lambda: None,
        )

        config = get_feature_config()

        # Should fall back to defaults
        assert config.save_cookies is False
        assert config.debug_mode is False

        clear_feature_config_cache()

    def test_corrupted_urls_json_raises_runtime_error(self, tmp_path, monkeypatch):
        """Test that corrupted urls.json raises RuntimeError."""
        clear_urls_cache()

        urls_path = tmp_path / "urls.json"
        urls_path.write_text("not valid json!", encoding="utf-8")

        monkeypatch.setattr(
            "perplexity_cli.utils.config.get_urls_path",
            lambda: urls_path,
        )
        monkeypatch.setattr(
            "perplexity_cli.utils.config._ensure_user_urls_config",
            lambda: None,
        )

        with pytest.raises(RuntimeError, match="Failed to load URLs configuration"):
            get_urls()

        clear_urls_cache()


class TestMissingUrlsJson:
    """Test behaviour when urls.json does not exist."""

    def test_urls_json_created_from_defaults(self, tmp_path, monkeypatch):
        """Test that missing urls.json is created from package defaults."""
        clear_urls_cache()

        config_dir = tmp_path / ".config" / "perplexity-cli"
        config_dir.mkdir(parents=True)
        urls_path = config_dir / "urls.json"

        monkeypatch.setattr(
            "perplexity_cli.utils.config.get_urls_path",
            lambda: urls_path,
        )
        monkeypatch.setattr(
            "perplexity_cli.utils.config.get_config_dir",
            lambda: config_dir,
        )

        assert not urls_path.exists()

        url_config = get_urls()

        # Should have created the file
        assert urls_path.exists()
        assert isinstance(url_config, URLConfig)
        assert url_config.base_url == "https://www.perplexity.ai"

        clear_urls_cache()


class TestEnvironmentVariableOverridesUrl:
    """Test environment variable overrides for URL configuration."""

    def test_perplexity_base_url_override(self, monkeypatch):
        """Test that PERPLEXITY_BASE_URL overrides config file value."""
        clear_urls_cache()
        monkeypatch.setenv("PERPLEXITY_BASE_URL", "https://custom-base.example.com")

        url_config = get_urls()
        assert url_config.base_url == "https://custom-base.example.com"

        clear_urls_cache()

    def test_perplexity_query_endpoint_override(self, monkeypatch):
        """Test that PERPLEXITY_QUERY_ENDPOINT overrides config file value."""
        clear_urls_cache()
        monkeypatch.setenv("PERPLEXITY_QUERY_ENDPOINT", "/api/custom/endpoint")

        url_config = get_urls()
        assert url_config.query_endpoint == "/api/custom/endpoint"

        clear_urls_cache()


class TestEnvironmentVariableOverridesRateLimiting:
    """Test environment variable overrides for rate limiting configuration."""

    def test_rate_limiting_enabled_override_true(self, monkeypatch):
        """Test PERPLEXITY_RATE_LIMITING_ENABLED=true enables rate limiting."""
        monkeypatch.setenv("PERPLEXITY_RATE_LIMITING_ENABLED", "true")

        config = get_rate_limiting_config()
        assert config.enabled is True

    def test_rate_limiting_enabled_override_false(self, monkeypatch):
        """Test PERPLEXITY_RATE_LIMITING_ENABLED=false disables rate limiting."""
        monkeypatch.setenv("PERPLEXITY_RATE_LIMITING_ENABLED", "false")

        config = get_rate_limiting_config()
        assert config.enabled is False

    def test_rate_limiting_enabled_override_yes(self, monkeypatch):
        """Test PERPLEXITY_RATE_LIMITING_ENABLED=yes enables rate limiting."""
        monkeypatch.setenv("PERPLEXITY_RATE_LIMITING_ENABLED", "yes")

        config = get_rate_limiting_config()
        assert config.enabled is True

    def test_rate_limiting_rps_override(self, monkeypatch):
        """Test PERPLEXITY_RATE_LIMITING_RPS overrides requests per period."""
        monkeypatch.setenv("PERPLEXITY_RATE_LIMITING_RPS", "50")

        config = get_rate_limiting_config()
        assert config.requests_per_period == 50

    def test_rate_limiting_period_override(self, monkeypatch):
        """Test PERPLEXITY_RATE_LIMITING_PERIOD overrides period seconds."""
        monkeypatch.setenv("PERPLEXITY_RATE_LIMITING_PERIOD", "120.5")

        config = get_rate_limiting_config()
        assert config.period_seconds == 120.5

    def test_rate_limiting_rps_invalid_raises(self, monkeypatch):
        """Test that non-integer PERPLEXITY_RATE_LIMITING_RPS raises RuntimeError."""
        monkeypatch.setenv("PERPLEXITY_RATE_LIMITING_RPS", "not_a_number")

        with pytest.raises(RuntimeError, match="Invalid PERPLEXITY_RATE_LIMITING_RPS"):
            get_rate_limiting_config()

    def test_rate_limiting_period_invalid_raises(self, monkeypatch):
        """Test that non-float PERPLEXITY_RATE_LIMITING_PERIOD raises RuntimeError."""
        monkeypatch.setenv("PERPLEXITY_RATE_LIMITING_PERIOD", "not_a_number")

        with pytest.raises(RuntimeError, match="Invalid PERPLEXITY_RATE_LIMITING_PERIOD"):
            get_rate_limiting_config()


class TestEnvironmentVariableOverridesFeatureConfig:
    """Test environment variable overrides for feature configuration."""

    def test_save_cookies_override_true(self, monkeypatch):
        """Test PERPLEXITY_SAVE_COOKIES=true enables cookie saving."""
        clear_feature_config_cache()
        monkeypatch.setenv("PERPLEXITY_SAVE_COOKIES", "true")

        config = get_feature_config()
        assert config.save_cookies is True

        clear_feature_config_cache()

    def test_save_cookies_override_false(self, monkeypatch):
        """Test PERPLEXITY_SAVE_COOKIES=false disables cookie saving."""
        clear_feature_config_cache()
        monkeypatch.setenv("PERPLEXITY_SAVE_COOKIES", "false")

        config = get_feature_config()
        assert config.save_cookies is False

        clear_feature_config_cache()

    def test_save_cookies_override_1(self, monkeypatch):
        """Test PERPLEXITY_SAVE_COOKIES=1 enables cookie saving."""
        clear_feature_config_cache()
        monkeypatch.setenv("PERPLEXITY_SAVE_COOKIES", "1")

        config = get_feature_config()
        assert config.save_cookies is True

        clear_feature_config_cache()

    def test_debug_mode_override_true(self, monkeypatch):
        """Test PERPLEXITY_DEBUG_MODE=true enables debug mode."""
        clear_feature_config_cache()
        monkeypatch.setenv("PERPLEXITY_DEBUG_MODE", "true")

        config = get_feature_config()
        assert config.debug_mode is True

        clear_feature_config_cache()

    def test_debug_mode_override_false(self, monkeypatch):
        """Test PERPLEXITY_DEBUG_MODE=false disables debug mode."""
        clear_feature_config_cache()
        monkeypatch.setenv("PERPLEXITY_DEBUG_MODE", "false")

        config = get_feature_config()
        assert config.debug_mode is False

        clear_feature_config_cache()

    def test_debug_mode_override_yes(self, monkeypatch):
        """Test PERPLEXITY_DEBUG_MODE=yes enables debug mode."""
        clear_feature_config_cache()
        monkeypatch.setenv("PERPLEXITY_DEBUG_MODE", "yes")

        config = get_feature_config()
        assert config.debug_mode is True

        clear_feature_config_cache()


class TestRateLimitingValidation:
    """Test rate limiting configuration validation."""

    def test_negative_requests_per_period_raises(self):
        """Test that negative requests_per_period in config raises RuntimeError."""
        with patch("perplexity_cli.utils.config.get_urls_path") as mock_path:
            import tempfile

            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(
                    {
                        "rate_limiting": {
                            "enabled": True,
                            "requests_per_period": -1,
                            "period_seconds": 60,
                        }
                    },
                    f,
                )
                f.flush()
                mock_path.return_value = Path(f.name)

                with pytest.raises(RuntimeError, match="Invalid rate limiting configuration"):
                    get_rate_limiting_config()

    def test_zero_period_seconds_raises(self):
        """Test that zero period_seconds in config raises RuntimeError."""
        with patch("perplexity_cli.utils.config.get_urls_path") as mock_path:
            import tempfile

            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(
                    {
                        "rate_limiting": {
                            "enabled": True,
                            "requests_per_period": 10,
                            "period_seconds": 0,
                        }
                    },
                    f,
                )
                f.flush()
                mock_path.return_value = Path(f.name)

                with pytest.raises(RuntimeError, match="Invalid rate limiting configuration"):
                    get_rate_limiting_config()

    def test_non_boolean_enabled_uses_pydantic_coercion(self):
        """Test that non-boolean enabled value is coerced by Pydantic.

        The runtime code does not perform manual validation of the enabled field;
        Pydantic's bool coercion accepts string values like 'yes'.
        """
        with patch("perplexity_cli.utils.config.get_urls_path") as mock_path:
            import tempfile

            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(
                    {"rate_limiting": {"enabled": "yes"}},
                    f,
                )
                f.flush()
                mock_path.return_value = Path(f.name)

                # Pydantic coerces "yes" to a boolean; no RuntimeError raised
                config = get_rate_limiting_config()
                assert isinstance(config.enabled, bool)


class TestGetUrlsEdgeCases:
    """Test edge cases in get_urls() function."""

    def test_urls_json_missing_perplexity_section_raises(self, tmp_path, monkeypatch):
        """Test that urls.json without 'perplexity' section raises RuntimeError."""
        clear_urls_cache()

        urls_path = tmp_path / "urls.json"
        urls_path.write_text(json.dumps({"other": "data"}), encoding="utf-8")

        monkeypatch.setattr("perplexity_cli.utils.config.get_urls_path", lambda: urls_path)
        monkeypatch.setattr("perplexity_cli.utils.config._ensure_user_urls_config", lambda: None)

        with pytest.raises(RuntimeError, match="missing 'perplexity' section"):
            get_urls()

        clear_urls_cache()

    def test_urls_json_perplexity_not_dict_raises(self, tmp_path, monkeypatch):
        """Test that urls.json with non-dict 'perplexity' raises RuntimeError."""
        clear_urls_cache()

        urls_path = tmp_path / "urls.json"
        urls_path.write_text(json.dumps({"perplexity": "not a dict"}), encoding="utf-8")

        monkeypatch.setattr("perplexity_cli.utils.config.get_urls_path", lambda: urls_path)
        monkeypatch.setattr("perplexity_cli.utils.config._ensure_user_urls_config", lambda: None)

        with pytest.raises(RuntimeError, match="must be a dictionary"):
            get_urls()

        clear_urls_cache()


class TestCacheClearFunctions:
    """Test cache clearing functions."""

    def test_clear_urls_cache_does_not_raise(self):
        """Test that clear_urls_cache() can be called without error."""
        clear_urls_cache()

    def test_clear_feature_config_cache_does_not_raise(self):
        """Test that clear_feature_config_cache() can be called without error."""
        clear_feature_config_cache()

    def test_clear_urls_cache_allows_reload(self):
        """Test that clearing cache allows fresh config reload."""
        clear_urls_cache()

        config1 = get_urls()
        clear_urls_cache()
        config2 = get_urls()

        # Both should return valid config (values may be same)
        assert isinstance(config1, URLConfig)
        assert isinstance(config2, URLConfig)

        clear_urls_cache()

    def test_clear_feature_config_cache_allows_reload(self):
        """Test that clearing feature config cache allows fresh reload."""
        clear_feature_config_cache()

        config1 = get_feature_config()
        clear_feature_config_cache()
        config2 = get_feature_config()

        assert isinstance(config1, FeatureConfig)
        assert isinstance(config2, FeatureConfig)

        clear_feature_config_cache()
