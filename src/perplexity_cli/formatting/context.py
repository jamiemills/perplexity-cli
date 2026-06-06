"""Presentation rendering context objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from perplexity_cli.formatting.base import Formatter


@dataclass(frozen=True, slots=True)
class OutputOptions:
    """Presentation and serialisation switches for command output."""

    output_format: str = "text"
    strip_references: bool = False
    json_mode: bool = False
    include_schema: bool = False


@dataclass(frozen=True, slots=True)
class RenderContext:
    """Formatter and presentation options bundled for rendering."""

    formatter: Formatter
    options: OutputOptions
