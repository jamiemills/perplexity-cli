"""Shared type aliases for descriptive string-based alternatives to boolean flags.

These replace ``bool`` parameters flagged by Semgrep's ``boolean-flag-argument``
rule (Clean Code Ch.3) with self-documenting ``Literal`` types.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

OutputFormat = Literal["json", "human"]
SchemaInclusion = Literal["with_schema", "no_schema"]
DebugMode = Literal["debug", "normal"]


@dataclass(frozen=True, slots=True)
class QueryOptions:
    """Optional flags for :func:`run_query_command`, built from CLI flags."""

    output_format: str | None = None
    strip_references: bool = False
    stream: bool = False
    attachments: tuple[str, ...] = ()
    model_preference: str | None = None
    request_param_overrides: tuple[str, ...] = ()
