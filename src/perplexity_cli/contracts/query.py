"""Shared query contract types.

These types were promoted from ``api.models`` to fix a hexagonal-architecture
violation where ``ports/__init__.py`` depended on ``api/models.py``.  They
live here so that ports, API, formatting, and runners can all depend on a
standalone contracts package without creating a dependency cycle.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from pydantic import (
    BaseModel,
    Field,
    model_validator,
)

from perplexity_cli.utils.upstream_contracts import require_mapping

# ---------------------------------------------------------------------------
# Lightweight parameter objects (dataclasses, not Pydantic)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TraceContext:
    """Timing and correlation identifiers for a single request.

    Carries the trace ID (for log correlation) and start timestamp (for
    elapsed-time calculations) through the call chain without occupying
    separate function parameters.
    """

    trace_id: str | None = None
    start_time: float | None = None


@dataclass(frozen=True, slots=True, init=False)
class QueryInput:
    """User query text, file attachments, and optional model selection.

    The custom ``__init__`` accepts a covariant ``Mapping`` for
    ``request_params`` so callers can pass ``dict[str, str]`` (from CLI
    overrides) or ``dict[str, object]`` (programmatic) interchangeably;
    values are stored as a concrete ``dict`` for downstream consumers.
    """

    query: str
    attachment_urls: list[str]
    model_preference: str | None
    request_params: dict[str, object]

    def __init__(
        self,
        query: str,
        attachment_urls: Iterable[str] | None = None,
        model_preference: str | None = None,
        request_params: Mapping[str, object] | None = None,
    ) -> None:
        """Initialise ``QueryInput``, copying mutable inputs defensively.

        Args:
            query: The user's query text.
            attachment_urls: Optional S3 attachment URLs; copied into a
                fresh ``list`` to keep the dataclass immutable.
            model_preference: Optional model override (e.g. ``pplx_pro``).
            request_params: Optional extra fields merged into the
                outbound request; copied into a fresh ``dict``.
        """
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "attachment_urls", list(attachment_urls or []))
        object.__setattr__(self, "model_preference", model_preference)
        object.__setattr__(self, "request_params", dict(request_params or {}))


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


def _new_references() -> list[WebResult]:
    """Default factory for ``Answer.references``."""
    return []


class WebResult(BaseModel):
    """Search result from Perplexity.

    Upstream API payloads are validated via ``model_validate()``.  The
    pre-validator enforces that the input is a mapping (raising
    ``UpstreamSchemaError`` otherwise) so that malformed upstream data
    is caught early with a domain-specific exception.
    """

    name: str = Field(default="")
    url: str = Field(default="")
    snippet: str | None = Field(default=None)
    timestamp: str | None = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def _validate_upstream_shape(cls, raw_result: object) -> object:
        """Ensure the raw input is a mapping before field validation."""
        return require_mapping(raw_result, "Malformed web result block in upstream response")


class Answer(BaseModel):
    """Complete answer with text and references."""

    text: str
    references: list[WebResult] = Field(default_factory=_new_references)
