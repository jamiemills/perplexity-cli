"""Model service for fetching and filtering Perplexity models.

Provides the business logic for listing available models based on the
user's subscription level, using the ``/rest/models/config`` and
``/rest/user/settings`` API endpoints.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from perplexity_cli.models.model_config import (
    ModelConfigEntry,
    ModelConfigResponse,
    SubscriptionLevel,
    UserSettings,
)
from perplexity_cli.utils.config import get_model_config_endpoint, get_user_settings_endpoint
from perplexity_cli.utils.logging import get_logger

if TYPE_CHECKING:
    from perplexity_cli.api.rest_client import RestClient


class ModelService:
    """Fetches and filters Perplexity models by subscription level.

    The service queries the model configuration and user settings
    endpoints, then applies subscription-tier filtering to return
    only the models accessible to the current user.
    """

    def __init__(
        self,
        rest_client: RestClient,
        subscription_level: SubscriptionLevel,
    ) -> None:
        """Initialise the model service.

        Args:
            rest_client: HTTP client for REST API calls.
            subscription_level: The user's subscription level (FREE, PRO, MAX).
        """
        self._client = rest_client
        self._level = subscription_level
        self._logger = get_logger()

    def fetch_model_config(self) -> ModelConfigResponse:
        """Fetch the model configuration from the API.

        Returns:
            Parsed model configuration response.

        Raises:
            PerplexityHTTPStatusError: For HTTP errors.
            PerplexityRequestError: For network errors.
        """
        url = get_model_config_endpoint()
        self._logger.debug("Fetching model config from %s", url)
        config_payload = self._client.get_json(url)
        return ModelConfigResponse.model_validate(config_payload)

    def fetch_user_settings(self) -> UserSettings:
        """Fetch user settings from the API.

        Returns:
            Parsed user settings.

        Raises:
            PerplexityHTTPStatusError: For HTTP errors.
            PerplexityRequestError: For network errors.
        """
        url = get_user_settings_endpoint()
        self._logger.debug("Fetching user settings from %s", url)
        settings_payload = self._client.get_json(url)
        return UserSettings.model_validate(settings_payload)

    def list_available_models(self) -> list[ModelConfigEntry]:
        """Fetch and return models accessible to the current user.

        Calls the model config endpoint, then filters the ``config``
        entries by subscription level and audience.

        Returns:
            List of accessible model config entries, sorted with
            the default model first.
        """
        config = self.fetch_model_config()
        return self._filter_accessible(config.config)

    def _filter_accessible(
        self,
        entries: list[ModelConfigEntry],
    ) -> list[ModelConfigEntry]:
        """Filter config entries by subscription level and audience.

        Args:
            entries: All model config entries from the API.

        Returns:
            Entries accessible to the current user.
        """
        return [entry for entry in entries if entry.is_accessible(self._level)]

    def validate_model_id(self, model_id: str) -> bool:
        """Check whether a model ID is valid and accessible.

        Args:
            model_id: The model identifier to validate.

        Returns:
            True if the model is available to the current user.
        """
        available = self.list_available_models()
        return self._model_id_in_entries(model_id, available)

    @staticmethod
    def _model_id_in_entries(
        model_id: str,
        entries: list[ModelConfigEntry],
    ) -> bool:
        """Check if model_id matches any entry's model identifiers."""
        for entry in entries:
            if entry.non_reasoning_model == model_id:
                return True
            if entry.reasoning_model == model_id:
                return True
        return False
