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
