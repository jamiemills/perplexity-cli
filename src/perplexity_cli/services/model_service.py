"""Model service for fetching and filtering Perplexity models.

Provides the business logic for listing available models based on the
user's subscription level, using the ``/rest/models/config`` and
``/rest/user/settings`` API endpoints.
"""

from __future__ import annotations

import logging

from perplexity_cli.config.models import URLConfig
from perplexity_cli.models.model_config import (
    ModelConfigEntry,
    ModelConfigResponse,
    SubscriptionLevel,
    UserSettings,
)
from perplexity_cli.services.ports import EndpointProvider, QueryClient

_DEFAULT_URLS = URLConfig()


class _DefaultEndpointProvider:
    """Fallback endpoint provider using the domain-layer default URLs.

    Satisfies the ``EndpointProvider`` port when no concrete provider is
    injected by the composition layer.  Adapter implementations that wrap
    ``utils.config`` lookup helpers may be injected instead to honour
    user or environment URL overrides.
    """

    def model_config_endpoint(self) -> str:
        """Return the default model configuration endpoint URL.

        Returns:
            The full URL of the ``/rest/models/config`` endpoint.
        """
        return _DEFAULT_URLS.model_config_endpoint

    def user_settings_endpoint(self) -> str:
        """Return the default user settings endpoint URL.

        Returns:
            The full URL of the ``/rest/user/settings`` endpoint.
        """
        return _DEFAULT_URLS.user_settings_endpoint


class ModelService:
    """Fetches and filters Perplexity models by subscription level.

    The service queries the model configuration and user settings
    endpoints, then applies subscription-tier filtering to return
    only the models accessible to the current user.
    """

    def __init__(
        self,
        rest_client: QueryClient,
        subscription_level: SubscriptionLevel,
        endpoints: EndpointProvider | None = None,
    ) -> None:
        """Initialise the model service.

        Args:
            rest_client: HTTP query client satisfying the QueryClient port.
            subscription_level: The user's subscription level (FREE, PRO, MAX).
            endpoints: Optional endpoint provider satisfying the
                EndpointProvider port; defaults to the domain-layer URLs.
        """
        self._client = rest_client
        self._level = subscription_level
        self._endpoints = endpoints if endpoints is not None else _DefaultEndpointProvider()
        self._logger = logging.getLogger(__name__)

    def fetch_model_config(self) -> ModelConfigResponse:
        """Fetch the model configuration from the API.

        Returns:
            Parsed model configuration response.

        Raises:
            PerplexityHTTPStatusError: For HTTP errors.
            PerplexityRequestError: For network errors.
        """
        url = self._endpoints.model_config_endpoint()
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
        url = self._endpoints.user_settings_endpoint()
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

        Accessible entries are stable-partitioned so that default entries
        come first, preserving the upstream relative order within each
        partition.

        Args:
            entries: All model config entries from the API.

        Returns:
            Entries accessible to the current user, defaults first.
        """
        accessible = [entry for entry in entries if entry.is_accessible(self._level)]
        return self._defaults_first(accessible)

    @staticmethod
    def _defaults_first(
        entries: list[ModelConfigEntry],
    ) -> list[ModelConfigEntry]:
        """Stable-partition entries so defaults precede non-defaults.

        Args:
            entries: Accessible entries in upstream order.

        Returns:
            Entries with ``is_default`` entries first, preserving the
            relative order within each partition.
        """
        defaults = [entry for entry in entries if entry.is_default]
        others = [entry for entry in entries if not entry.is_default]
        return defaults + others

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
