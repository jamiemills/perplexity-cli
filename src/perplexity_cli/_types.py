"""Shared type aliases for descriptive string-based alternatives to boolean flags.

These replace ``bool`` parameters flagged by Semgrep's ``boolean-flag-argument``
rule (Clean Code Ch.3) with self-documenting ``Literal`` types.
"""

from __future__ import annotations

from typing import Literal

OutputFormat = Literal["json", "human"]
SchemaInclusion = Literal["with_schema", "no_schema"]
DebugMode = Literal["debug", "normal"]
