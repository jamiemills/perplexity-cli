"""Cross-reference labels used in ``See Also`` help sections."""

from __future__ import annotations

from typing import Protocol

__all__ = [
    "AUTH_LOGIN_HELP_REF",
    "AUTH_STATUS_HELP_REF",
    "STYLE_SET_HELP_REF",
]

#: Stable command-path references reused by multiple commands' See Also sections.
AUTH_LOGIN_HELP_REF = "pxcli auth login"
AUTH_STATUS_HELP_REF = "pxcli auth status"
STYLE_SET_HELP_REF = "pxcli style set"


class _CouplingProtocol(Protocol):  # pyright: ignore[reportUnusedClass]
    """Abstract coupling protocol."""

    ...
