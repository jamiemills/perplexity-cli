"""T007 mutation-closure tests: models table rendering at the public boundary.

The exact-layout assertion kills header, alignment, gutter, separator,
and cell-content mutants of the table rendering helpers behind
``format_model_table``.
"""

from __future__ import annotations

from perplexity_cli.models.model_config import ModelConfigEntry
from perplexity_cli.runners.models import format_model_table

# Column widths implied by the fixtures below: the longest cell (or
# header) per column. "Search"/"Reason" widen LABEL to 6; every other
# column is governed by its header.
COLUMN_WIDTHS = (8, 6, 4, 11)


def _entry(label: str, description: str, tier: str, model_id: str | None) -> ModelConfigEntry:
    """Build a minimal model entry for table rendering assertions."""
    return ModelConfigEntry(
        label=label,
        description=description,
        subscription_tier=tier,
        non_reasoning_model=model_id,
        reasoning_model=None,
    )


def _padded_row(cells: tuple[str, str, str, str]) -> str:
    """Render a row under the documented left-aligned two-space-gutter layout."""
    return "  ".join(cell.ljust(width) for cell, width in zip(cells, COLUMN_WIDTHS, strict=True))


def test_format_model_table_renders_exact_aligned_layout() -> None:
    """The table renders headers, separator, and left-aligned data rows exactly.

    Covers the ``(none)`` model-id placeholder, empty-description cells,
    capitalised tier text, header labels, and per-cell alignment.
    """
    entries = [
        _entry(label="Search", description="Fast", tier="pro", model_id="sonar"),
        _entry(label="Reason", description="", tier="max", model_id=None),
    ]

    expected = "\n".join(
        [
            _padded_row(("MODEL ID", "LABEL", "TIER", "DESCRIPTION")),
            "  ".join("-" * width for width in COLUMN_WIDTHS),
            _padded_row(("sonar", "Search", "Pro", "Fast")),
            _padded_row(("(none)", "Reason", "Max", "")),
        ]
    )

    assert format_model_table(entries) == expected
