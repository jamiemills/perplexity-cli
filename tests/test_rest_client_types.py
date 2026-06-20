"""Type-level regression guards for perplexity_cli.api.rest_client.

These assertions ensure the public type annotations on ``RestClient`` are not
eroded by future refactors. They complement the behavioural tests in
``test_rest_client.py`` and exist primarily to drive the pyright-strict
clean-up via TDD.
"""

from __future__ import annotations

from typing import get_type_hints

import perplexity_cli.api.rest_client as _rest_module
from perplexity_cli.api.rest_client import RestClient


def test_get_json_returns_object_not_any() -> None:
    """``get_json`` must declare ``object`` as its return type.

    Returning ``Any`` would defeat the pyright-strict ratchet this module
    is annotated to satisfy; ``object`` is the honest top type for an
    arbitrary parsed JSON payload.
    """
    hints = get_type_hints(RestClient.get_json)
    assert hints.get("return") is object


def test_get_json_parameters_are_fully_typed() -> None:
    """``get_json`` must keep its ``url`` parameter typed as ``str``."""
    hints = get_type_hints(RestClient.get_json)
    assert hints.get("url") is str


def test_get_client_returns_parameterised_session() -> None:
    """``_get_client`` must return ``Session[Response]`` (parameterised).

    A bare ``Session`` annotation triggers ``reportMissingTypeArgument``
    under pyright strict mode; the type argument must be explicit.
    """
    from curl_cffi.requests import Response, Session

    # Session/Response are TYPE_CHECKING-only in the module, so inject them
    # into the resolution namespace for get_type_hints.
    namespace = {**vars(_rest_module), "Session": Session, "Response": Response}
    hints = get_type_hints(RestClient._get_client, globalns=namespace)
    return_hint = hints.get("return")
    assert return_hint is not None
    assert getattr(return_hint, "__origin__", None) is Session
    assert getattr(return_hint, "__args__", ()) == (Response,)
