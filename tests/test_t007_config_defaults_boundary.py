"""Mutation-closure boundary tests for configuration default contracts (T007).

Exercises the pure default-constructors exported by the
``perplexity_cli.utils.config`` facade — whose mapping shapes are the on-disk
serialisation contract consumed by ``impl`` — and the forbidden-character
rule that ``URLConfig`` enforces at its public validation boundary.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from perplexity_cli.config.models import FeatureConfig, RateLimitConfig, URLConfig
from perplexity_cli.utils.config import default_feature_config, default_rate_limiting

EXPECTED_RATE_LIMITING: dict[str, Any] = {
    "enabled": True,
    "requests_per_period": 20,
    "period_seconds": 60,
}

EXPECTED_FEATURE_CONFIG: dict[str, Any] = {
    "version": 1,
    "features": {
        "save_cookies": False,
        "debug_mode": False,
    },
}


class TestDefaultRateLimitingContract:
    """The default rate-limiting mapping is the documented on-disk contract."""

    def test_returns_documented_default_mapping(self):
        assert default_rate_limiting() == EXPECTED_RATE_LIMITING

    def test_validates_to_canonical_model_defaults(self):
        assert RateLimitConfig.model_validate(default_rate_limiting()) == RateLimitConfig()


class TestDefaultFeatureConfigContract:
    """The default feature mapping is the documented on-disk contract."""

    def test_returns_documented_default_mapping(self):
        assert default_feature_config() == EXPECTED_FEATURE_CONFIG

    def test_features_validate_to_canonical_model_defaults(self):
        features = default_feature_config()["features"]
        assert FeatureConfig.model_validate(features) == FeatureConfig()


class TestURLConfigForbiddenCharacterBoundary:
    """URLConfig rejects embedded control and delete codepoints.

    Codepoints are placed mid-path because ``str.strip()`` in the validator
    normalises leading/trailing whitespace-classified characters (CPython
    treats the 0x1C-0x1F information separators as whitespace).
    """

    @pytest.mark.parametrize(
        "codepoint",
        [
            pytest.param(0x00, id="nul"),
            pytest.param(0x1F, id="unit-separator"),
            pytest.param(0x7F, id="delete"),
        ],
    )
    def test_embedded_control_codepoints_are_rejected(self, codepoint: int):
        url = "https://example.com/pa" + chr(codepoint) + "th"
        with pytest.raises(ValidationError):
            URLConfig(base_url=url)

    def test_clean_path_is_accepted(self):
        cfg = URLConfig(base_url="https://example.com/path")
        assert cfg.base_url == "https://example.com/path"
