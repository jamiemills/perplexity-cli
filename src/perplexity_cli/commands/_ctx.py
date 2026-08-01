"""Shared Click-context helpers for command modules.

The helpers here narrow loosely-typed Click parameter values (collected via
``**params`` to keep command callbacks under the project's four-argument
ceiling) into the concrete types the runner layer expects.
"""

from __future__ import annotations

from pathlib import Path

import click

__all__ = [
    "ClickValue",
    "_ensure_ctx_obj",
    "as_bool",
    "as_int_or_none",
    "as_path_or_none",
    "as_str_or_none",
    "as_str_tuple",
    "record_output_flags",
]


#: Union of every value type a Click option decorator can produce for the
#: commands in this package.  Used as the ``**params`` value annotation so
#: isinstance-based narrowing inside the helpers yields concrete element
#: types rather than ``Unknown``.
ClickValue = str | bool | int | Path | tuple[str, ...] | None


def _ensure_ctx_obj(ctx: click.Context) -> None:
    """Ensure ``ctx.obj`` is initialised as a dict before subcommands run."""
    ctx.ensure_object(dict)


def record_output_flags(ctx: click.Context, raw: dict[str, ClickValue]) -> None:
    """Persist the ``--json`` / ``--schema`` flag values onto ``ctx.obj``.

    Click populates ``raw`` from the command's option decorators; this helper
    narrows the loosely-typed values to bools so command bodies can stay
    argument-light (``**raw`` keeps callbacks under the four-argument ceiling).
    """
    ctx.ensure_object(dict)
    ctx.obj["json"] = raw.get("json_flag") is True
    ctx.obj["schema"] = raw.get("schema_flag") is True


def as_bool(value: ClickValue) -> bool:
    """Narrow a click flag value to a Python bool."""
    return value is True


def as_str_or_none(value: ClickValue) -> str | None:
    """Narrow a click option value to ``str | None``."""
    return value if isinstance(value, str) else None


def as_int_or_none(value: ClickValue) -> int | None:
    """Narrow a click option value to ``int | None``."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def as_path_or_none(value: ClickValue) -> Path | None:
    """Narrow a click option value to ``Path | None``."""
    return value if isinstance(value, Path) else None


def as_str_tuple(value: ClickValue) -> tuple[str, ...]:
    """Narrow a click ``multiple=True`` option value to ``tuple[str, ...]``."""
    if isinstance(value, tuple):
        return value
    return ()
