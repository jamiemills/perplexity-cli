"""Tests for model configuration Pydantic models.

Validates the data models used to represent Perplexity's
``/rest/models/config`` and ``/rest/user/settings`` API responses.
"""

from __future__ import annotations

import pytest

from perplexity_cli.models.model_config import (
    ModelConfigEntry,
    ModelConfigResponse,
    ModelInfo,
    SubscriptionLevel,
    UserSettings,
)

# ---------------------------------------------------------------------------
# ModelInfo
# ---------------------------------------------------------------------------


class TestModelInfo:
    """Tests for individual model metadata."""

    def test_minimal_valid(self) -> None:
        info = ModelInfo(label="GPT-5.4", description="OpenAI model")
        assert info.label == "GPT-5.4"
        assert info.description == "OpenAI model"
        assert info.mode is None
        assert info.provider is None

    def test_full_fields(self) -> None:
        info = ModelInfo(
            label="GPT-5.4",
            description="OpenAI model",
            mode="search",
            provider="OPENAI",
        )
        assert info.mode == "search"
        assert info.provider == "OPENAI"

    def test_empty_label_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least 1 character"):
            ModelInfo(label="", description="desc")

    def test_empty_description_accepted(self) -> None:
        """API may return empty descriptions for some models."""
        info = ModelInfo(label="test", description="")
        assert info.description == ""


# ---------------------------------------------------------------------------
# ModelConfigEntry
# ---------------------------------------------------------------------------


class TestModelConfigEntry:
    """Tests for UI selector model entries."""

    def test_minimal_valid(self) -> None:
        entry = ModelConfigEntry(
            label="Best",
            description="Auto-selects the best model",
            subscription_tier="pro",
        )
        assert entry.label == "Best"
        assert entry.subscription_tier == "pro"
        assert entry.non_reasoning_model is None
        assert entry.reasoning_model is None
        assert entry.is_default is False
        assert entry.has_new_tag is False

    def test_full_entry(self) -> None:
        entry = ModelConfigEntry(
            label="GPT-5.4",
            description="OpenAI latest",
            subscription_tier="pro",
            non_reasoning_model="gpt54",
            reasoning_model="gpt54_thinking",
            text_only_model=False,
            audience=None,
            is_default=False,
            has_new_tag=True,
            subheading=None,
        )
        assert entry.non_reasoning_model == "gpt54"
        assert entry.reasoning_model == "gpt54_thinking"
        assert entry.has_new_tag is True

    def test_max_tier(self) -> None:
        entry = ModelConfigEntry(
            label="Claude Opus 4.7",
            description="Anthropic top-tier",
            subscription_tier="max",
            non_reasoning_model="claude47opus",
        )
        assert entry.subscription_tier == "max"

    def test_internal_audience(self) -> None:
        entry = ModelConfigEntry(
            label="Internal Model",
            description="Internal only",
            subscription_tier="pro",
            audience="internal",
        )
        assert entry.audience == "internal"

    def test_is_accessible_pro_tier(self) -> None:
        entry = ModelConfigEntry(
            label="GPT-5.4",
            description="desc",
            subscription_tier="pro",
        )
        assert entry.is_accessible(SubscriptionLevel.PRO) is True
        assert entry.is_accessible(SubscriptionLevel.MAX) is True
        assert entry.is_accessible(SubscriptionLevel.FREE) is False

    def test_is_accessible_max_tier(self) -> None:
        entry = ModelConfigEntry(
            label="Claude Opus 4.7",
            description="desc",
            subscription_tier="max",
        )
        assert entry.is_accessible(SubscriptionLevel.PRO) is False
        assert entry.is_accessible(SubscriptionLevel.MAX) is True
        assert entry.is_accessible(SubscriptionLevel.FREE) is False

    def test_is_accessible_internal_blocked(self) -> None:
        entry = ModelConfigEntry(
            label="Internal",
            description="desc",
            subscription_tier="pro",
            audience="internal",
        )
        assert entry.is_accessible(SubscriptionLevel.MAX) is False

    def test_model_id_prefers_non_reasoning(self) -> None:
        entry = ModelConfigEntry(
            label="GPT-5.4",
            description="desc",
            subscription_tier="pro",
            non_reasoning_model="gpt54",
            reasoning_model="gpt54_thinking",
        )
        assert entry.model_id == "gpt54"

    def test_model_id_falls_back_to_reasoning(self) -> None:
        entry = ModelConfigEntry(
            label="Gemini 3.1 Pro",
            description="desc",
            subscription_tier="pro",
            non_reasoning_model=None,
            reasoning_model="gemini31pro_high",
        )
        assert entry.model_id == "gemini31pro_high"

    def test_model_id_none_when_both_absent(self) -> None:
        entry = ModelConfigEntry(
            label="Unknown",
            description="desc",
            subscription_tier="pro",
        )
        assert entry.model_id is None


# ---------------------------------------------------------------------------
# ModelConfigResponse
# ---------------------------------------------------------------------------


class TestModelConfigResponse:
    """Tests for the full /rest/models/config response."""

    @pytest.fixture
    def sample_response_data(self) -> dict:
        return {
            "config_schema": "v1",
            "models": {
                "pplx_pro": {
                    "label": "Best",
                    "description": "Auto-selects the best model",
                    "mode": "search",
                    "provider": None,
                },
                "gpt54": {
                    "label": "GPT-5.4",
                    "description": "OpenAI latest",
                    "mode": "search",
                    "provider": "OPENAI",
                },
            },
            "config": [
                {
                    "label": "Best",
                    "description": "Auto-selects",
                    "subscription_tier": "pro",
                    "non_reasoning_model": "pplx_pro",
                    "reasoning_model": None,
                    "is_default": True,
                },
                {
                    "label": "GPT-5.4",
                    "description": "OpenAI",
                    "subscription_tier": "pro",
                    "non_reasoning_model": "gpt54",
                    "reasoning_model": "gpt54_thinking",
                    "is_default": False,
                },
            ],
            "default_models": {
                "search": "pplx_pro",
                "research": "pplx_alpha",
            },
        }

    def test_parse_full_response(self, sample_response_data: dict) -> None:
        resp = ModelConfigResponse.model_validate(sample_response_data)
        assert resp.config_schema == "v1"
        assert len(resp.models) == 2
        assert len(resp.config) == 2
        assert resp.default_models["search"] == "pplx_pro"

    def test_models_are_model_info(self, sample_response_data: dict) -> None:
        resp = ModelConfigResponse.model_validate(sample_response_data)
        assert isinstance(resp.models["gpt54"], ModelInfo)
        assert resp.models["gpt54"].provider == "OPENAI"

    def test_config_entries_are_typed(self, sample_response_data: dict) -> None:
        resp = ModelConfigResponse.model_validate(sample_response_data)
        assert isinstance(resp.config[0], ModelConfigEntry)
        assert resp.config[0].is_default is True

    def test_empty_models_accepted(self) -> None:
        resp = ModelConfigResponse(
            config_schema="v1",
            models={},
            config=[],
            default_models={},
        )
        assert len(resp.models) == 0

    def test_search_models_filter(self, sample_response_data: dict) -> None:
        resp = ModelConfigResponse.model_validate(sample_response_data)
        search = resp.search_models()
        assert len(search) >= 1


# ---------------------------------------------------------------------------
# UserSettings
# ---------------------------------------------------------------------------


class TestUserSettings:
    """Tests for the /rest/user/settings response model."""

    def test_active_subscriber(self) -> None:
        settings = UserSettings(
            subscription_status="active",
            subscription_source="stripe",
            subscription_tier="monthly",
            default_model="turbo",
        )
        assert settings.subscription_status == "active"
        assert settings.is_subscriber is True

    def test_free_user(self) -> None:
        settings = UserSettings(
            subscription_status="none",
            subscription_source="none",
            subscription_tier="null",
            default_model="turbo",
        )
        assert settings.is_subscriber is False

    def test_default_model(self) -> None:
        settings = UserSettings(
            subscription_status="active",
            default_model="gpt54",
        )
        assert settings.default_model == "gpt54"

    def test_optional_fields_have_defaults(self) -> None:
        settings = UserSettings()
        assert settings.subscription_status == "none"
        assert settings.default_model == "turbo"
        assert settings.is_subscriber is False


# ---------------------------------------------------------------------------
# SubscriptionLevel
# ---------------------------------------------------------------------------


class TestSubscriptionLevel:
    """Tests for the subscription level enumeration."""

    def test_free_level(self) -> None:
        assert SubscriptionLevel.FREE.value == "free"

    def test_pro_level(self) -> None:
        assert SubscriptionLevel.PRO.value == "pro"

    def test_max_level(self) -> None:
        assert SubscriptionLevel.MAX.value == "max"

    def test_can_access_tier_pro(self) -> None:
        assert SubscriptionLevel.PRO.can_access_tier("pro") is True
        assert SubscriptionLevel.PRO.can_access_tier("max") is False

    def test_can_access_tier_max(self) -> None:
        assert SubscriptionLevel.MAX.can_access_tier("pro") is True
        assert SubscriptionLevel.MAX.can_access_tier("max") is True

    def test_can_access_tier_free(self) -> None:
        assert SubscriptionLevel.FREE.can_access_tier("pro") is False
        assert SubscriptionLevel.FREE.can_access_tier("max") is False
