"""Data models for Perplexity model configuration and user settings.

Represents the responses from ``/rest/models/config`` and
``/rest/user/settings`` private API endpoints.  These models are used
by the model service to determine which models are available to the
current user based on their subscription level.
"""

from __future__ import annotations

import enum
from typing import cast

from pydantic import BaseModel, Field, field_validator


class SubscriptionLevel(enum.Enum):
    """User subscription level determining model access.

    Distinct from the ``subscription_tier`` field in the user settings
    response, which indicates billing frequency (monthly/yearly).
    """

    FREE = "free"
    PRO = "pro"
    MAX = "max"

    def can_access_tier(self, tier: str) -> bool:
        """Check whether this subscription level grants access to a model tier.

        Args:
            tier: The model's ``subscription_tier`` value (``"pro"`` or ``"max"``).

        Returns:
            True if the user can access models of the given tier.
        """
        if self is SubscriptionLevel.MAX:
            return tier in ("pro", "max")
        if self is SubscriptionLevel.PRO:
            return tier == "pro"
        return False


class ModelInfo(BaseModel):
    """Individual model metadata from the ``models`` dictionary.

    Represents a single entry in the flat ``models`` map returned by
    ``/rest/models/config``.
    """

    label: str = Field(..., min_length=1, description="Human-readable display name")
    description: str = Field(default="", description="Short description")
    mode: str | None = Field(default=None, description="Operating mode (search, research, etc.)")
    provider: str | None = Field(
        default=None,
        description="Model provider (OPENAI, ANTHROPIC, GOOGLE, etc.)",
    )

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        """Validate that the label is non-empty."""
        if not value.strip():
            raise ValueError("Label must be non-empty")
        return value


class ModelConfigEntry(BaseModel):
    """UI model selector entry from the ``config`` array.

    Each entry represents a model choice shown in the Perplexity web
    UI's model dropdown, including its subscription tier requirement.
    """

    label: str = Field(..., description="Display name")
    description: str = Field(default="", description="Short description")
    subheading: str | None = Field(default=None, description="Additional context")
    has_new_tag: bool = Field(default=False, description="Whether marked as 'New' in the UI")
    subscription_tier: str = Field(..., description="Required tier: 'pro' or 'max'")
    non_reasoning_model: str | None = Field(
        default=None,
        description="Model ID for standard queries",
    )
    reasoning_model: str | None = Field(
        default=None,
        description="Model ID for reasoning/thinking queries",
    )
    text_only_model: bool = Field(default=False, description="Whether the model is text-only")
    audience: str | None = Field(
        default=None,
        description="Audience restriction; 'internal' for internal-only models",
    )
    is_default: bool = Field(default=False, description="Whether this is the default selection")

    @property
    def model_id(self) -> str | None:
        """Return the primary model identifier.

        Prefers the non-reasoning model; falls back to the reasoning model
        if the non-reasoning variant is absent.
        """
        return self.non_reasoning_model or self.reasoning_model

    def is_accessible(self, level: SubscriptionLevel) -> bool:
        """Check whether a user at the given subscription level can use this model.

        Internal-audience models are never accessible to regular users.

        Args:
            level: The user's subscription level.

        Returns:
            True if the model is accessible.
        """
        if self.audience == "internal":
            return False
        return level.can_access_tier(self.subscription_tier)


class ModelConfigResponse(BaseModel):
    """Full response from ``GET /rest/models/config``.

    Contains the complete model catalogue, the UI selector entries
    (with subscription tiers), and per-mode default model mappings.
    """

    config_schema: str = Field(default="v1", description="Schema version identifier")
    models: dict[str, ModelInfo] = Field(
        default_factory=dict,
        description="Flat map of model ID to metadata",
    )
    config: list[ModelConfigEntry] = cast(
        list[ModelConfigEntry],
        Field(
            default_factory=list,
            description="UI-visible model entries with subscription tiers",
        ),
    )
    default_models: dict[str, str] = Field(
        default_factory=dict,
        description="Per-mode default model ID mappings",
    )

    def search_models(self) -> list[ModelConfigEntry]:
        """Return config entries whose model IDs exist in the models dict with mode 'search'.

        Falls back to returning all config entries if mode filtering
        yields no results (the API may not annotate mode on all models).
        """
        search_ids = self._search_model_ids()
        if not search_ids:
            return list(self.config)
        return self._filter_config_by_ids(search_ids)

    def _search_model_ids(self) -> set[str]:
        """Collect model IDs that have mode 'search'."""
        return {model_id for model_id, info in self.models.items() if info.mode == "search"}

    def _filter_config_by_ids(self, model_ids: set[str]) -> list[ModelConfigEntry]:
        """Filter config entries to those whose model_id is in the given set.

        Falls back to all config entries if the intersection is empty.
        """
        filtered = [entry for entry in self.config if entry.model_id in model_ids]
        return filtered if filtered else list(self.config)


class UserSettings(BaseModel):
    """Relevant fields from ``GET /rest/user/settings``.

    Only the subscription and model-preference fields are captured;
    the full response contains many more fields that are not relevant
    to model selection.
    """

    subscription_status: str = Field(
        default="none",
        description="Subscription status: 'active' or 'none'",
    )
    subscription_source: str = Field(
        default="none",
        description="Payment provider: 'stripe', 'none', etc.",
    )
    subscription_tier: str = Field(
        default="null",
        description="Billing frequency: 'monthly', 'yearly', or 'null'",
    )
    default_model: str = Field(
        default="turbo",
        description="User's default model preference",
    )

    @property
    def is_subscriber(self) -> bool:
        """Return whether the user has an active subscription."""
        return self.subscription_status not in ("none", "", "null")

    def infer_subscription_level(self) -> SubscriptionLevel:
        """Infer the user's subscription level from settings fields.

        Active subscribers are assumed to be Pro.  The API does not
        currently expose a reliable field to distinguish Pro from Max;
        if such a field is discovered in future, detection should be
        added here.

        Returns:
            The inferred subscription level.
        """
        if not self.is_subscriber:
            return SubscriptionLevel.FREE
        return SubscriptionLevel.PRO
