"""Application-owned port protocols for the service layer.

Defines the abstractions that services require from adapter layers,
following hexagonal architecture principles where the application
owns its required interfaces.
"""

from __future__ import annotations

from typing import Protocol


class QueryClient(Protocol):
    """Application port for a synchronous HTTP query client.

    Defines the minimal interface the service layer needs from any
    HTTP adapter. A concrete ``RestClient`` satisfies this protocol
    structurally via its ``get_json`` method; no explicit subclassing
    or registration is required.
    """

    def get_json(self, url: str) -> object:
        """Perform a GET request and return the parsed JSON response.

        Args:
            url: The API endpoint URL.

        Returns:
            Parsed JSON response body as an opaque object.

        Raises:
            PerplexityHTTPStatusError: For HTTP errors (401, 403, 429, etc.).
            PerplexityRequestError: For network/connection errors.
        """
        ...


class EndpointProvider(Protocol):
    """Application port for resolving API endpoint URLs.

    Satisfied structurally by adapter code that wraps ``utils.config``
    lookup helpers, allowing the application layer to depend on the
    interface rather than on a concrete adapter.
    """

    def model_config_endpoint(self) -> str:
        """Return the model configuration endpoint URL.

        Returns:
            The full URL of the ``/rest/models/config`` endpoint.
        """
        ...

    def user_settings_endpoint(self) -> str:
        """Return the user settings endpoint URL.

        Returns:
            The full URL of the ``/rest/user/settings`` endpoint.
        """
        ...
