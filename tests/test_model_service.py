"""Tests for the model service.

Validates model fetching, subscription filtering, and the list of
available models returned to the CLI layer.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from perplexity_cli.models.model_config import (
    ModelConfigEntry,
    ModelConfigResponse,
    ModelInfo,
    SubscriptionLevel,
    UserSettings,
)
from perplexity_cli.services.model_service import ModelService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_model_config() -> ModelConfigResponse:
    """Return a realistic ModelConfigResponse for testing."""
    return ModelConfigResponse(
        config_schema="v1",
        models={
            "pplx_pro": ModelInfo(label="Best", description="Auto-select", mode="search"),
            "gpt54": ModelInfo(
                label="GPT-5.4",
                description="OpenAI",
                mode="search",
                provider="OPENAI",
            ),
            "gpt55": ModelInfo(
                label="GPT-5.5",
                description="OpenAI top",
                mode="search",
                provider="OPENAI",
            ),
            "claude46sonnet": ModelInfo(
                label="Claude Sonnet 4.6",
                description="Anthropic",
                mode="search",
                provider="ANTHROPIC",
            ),
            "claude47opus": ModelInfo(
                label="Claude Opus 4.7",
                description="Anthropic top",
                mode="search",
                provider="ANTHROPIC",
            ),
            "pplx_alpha": ModelInfo(
                label="Research",
                description="Research mode",
                mode="research",
            ),
        },
        config=[
            ModelConfigEntry(
                label="Best",
                description="Auto-select",
                subscription_tier="pro",
                non_reasoning_model="pplx_pro",
                is_default=True,
            ),
            ModelConfigEntry(
                label="GPT-5.4",
                description="OpenAI",
                subscription_tier="pro",
                non_reasoning_model="gpt54",
                reasoning_model="gpt54_thinking",
            ),
            ModelConfigEntry(
                label="GPT-5.5",
                description="OpenAI top",
                subscription_tier="max",
                non_reasoning_model="gpt55",
                reasoning_model="gpt55_thinking",
            ),
            ModelConfigEntry(
                label="Claude Sonnet 4.6",
                description="Anthropic",
                subscription_tier="pro",
                non_reasoning_model="claude46sonnet",
            ),
            ModelConfigEntry(
                label="Claude Opus 4.7",
                description="Anthropic top",
                subscription_tier="max",
                non_reasoning_model="claude47opus",
            ),
            ModelConfigEntry(
                label="Internal Model",
                description="Internal only",
                subscription_tier="pro",
                non_reasoning_model="internal_model",
                audience="internal",
            ),
        ],
        default_models={"search": "pplx_pro", "research": "pplx_alpha"},
    )


@pytest.fixture
def pro_user_settings() -> UserSettings:
    """Return settings for a Pro subscriber."""
    return UserSettings(
        subscription_status="active",
        subscription_source="stripe",
        subscription_tier="monthly",
        default_model="turbo",
    )


@pytest.fixture
def max_user_settings() -> UserSettings:
    """Return settings for a Max subscriber."""
    return UserSettings(
        subscription_status="active",
        subscription_source="stripe",
        subscription_tier="yearly",
        default_model="gpt54",
    )


@pytest.fixture
def free_user_settings() -> UserSettings:
    """Return settings for a free (non-subscriber) user."""
    return UserSettings(
        subscription_status="none",
        subscription_source="none",
        subscription_tier="null",
        default_model="turbo",
    )


def _make_service(
    model_config: ModelConfigResponse,
    user_settings: UserSettings,
    subscription_level: SubscriptionLevel,
) -> ModelService:
    """Create a ModelService with a mocked REST client."""
    mock_client = MagicMock()
    mock_client.get_json.side_effect = [
        model_config.model_dump(mode="json"),
        user_settings.model_dump(mode="json"),
    ]
    return ModelService(
        rest_client=mock_client,
        subscription_level=subscription_level,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestModelServiceFetchConfig:
    """Tests for fetching and parsing model configuration."""

    def test_fetch_model_config(self, sample_model_config: ModelConfigResponse) -> None:
        mock_client = MagicMock()
        mock_client.get_json.return_value = sample_model_config.model_dump(mode="json")
        service = ModelService(
            rest_client=mock_client,
            subscription_level=SubscriptionLevel.PRO,
        )
        config = service.fetch_model_config()
        assert config.config_schema == "v1"
        assert len(config.models) == 6
        assert len(config.config) == 6

    def test_fetch_user_settings(self, pro_user_settings: UserSettings) -> None:
        mock_client = MagicMock()
        mock_client.get_json.return_value = pro_user_settings.model_dump(mode="json")
        service = ModelService(
            rest_client=mock_client,
            subscription_level=SubscriptionLevel.PRO,
        )
        settings = service.fetch_user_settings()
        assert settings.subscription_status == "active"
        assert settings.is_subscriber is True


class TestModelServiceListModels:
    """Tests for listing available models with subscription filtering."""

    def test_pro_user_sees_pro_models(
        self,
        sample_model_config: ModelConfigResponse,
        pro_user_settings: UserSettings,
    ) -> None:
        service = _make_service(
            sample_model_config,
            pro_user_settings,
            SubscriptionLevel.PRO,
        )
        models = service.list_available_models()
        model_ids = [m.model_id for m in models]
        assert "pplx_pro" in model_ids
        assert "gpt54" in model_ids
        assert "claude46sonnet" in model_ids
        # Max-only models excluded
        assert "gpt55" not in model_ids
        assert "claude47opus" not in model_ids
        # Internal models excluded
        assert "internal_model" not in model_ids

    def test_max_user_sees_all_models(
        self,
        sample_model_config: ModelConfigResponse,
        max_user_settings: UserSettings,
    ) -> None:
        service = _make_service(
            sample_model_config,
            max_user_settings,
            SubscriptionLevel.MAX,
        )
        models = service.list_available_models()
        model_ids = [m.model_id for m in models]
        assert "pplx_pro" in model_ids
        assert "gpt54" in model_ids
        assert "gpt55" in model_ids
        assert "claude47opus" in model_ids
        # Internal still excluded
        assert "internal_model" not in model_ids

    def test_free_user_sees_no_models(
        self,
        sample_model_config: ModelConfigResponse,
        free_user_settings: UserSettings,
    ) -> None:
        service = _make_service(
            sample_model_config,
            free_user_settings,
            SubscriptionLevel.FREE,
        )
        models = service.list_available_models()
        assert len(models) == 0

    def test_validate_model_id_valid(
        self,
        sample_model_config: ModelConfigResponse,
        pro_user_settings: UserSettings,
    ) -> None:
        service = _make_service(
            sample_model_config,
            pro_user_settings,
            SubscriptionLevel.PRO,
        )
        assert service.validate_model_id("gpt54") is True

    def test_validate_model_id_invalid(
        self,
        sample_model_config: ModelConfigResponse,
        pro_user_settings: UserSettings,
    ) -> None:
        service = _make_service(
            sample_model_config,
            pro_user_settings,
            SubscriptionLevel.PRO,
        )
        assert service.validate_model_id("nonexistent_model") is False

    def test_validate_model_id_max_blocked_for_pro(
        self,
        sample_model_config: ModelConfigResponse,
        pro_user_settings: UserSettings,
    ) -> None:
        service = _make_service(
            sample_model_config,
            pro_user_settings,
            SubscriptionLevel.PRO,
        )
        assert service.validate_model_id("gpt55") is False
