"""Shared utility helpers for runner modules."""

from __future__ import annotations


def resolve_json_flag(json_mode: bool | None, ctx_obj: dict | None) -> bool:
    """Resolve the effective JSON mode flag from explicit arg or Click context.

    Args:
        json_mode: Explicit override; returned directly if not ``None``.
        ctx_obj: The Click ``ctx.obj`` dict, checked for a ``"json"`` key.

    Returns:
        The resolved boolean JSON-mode flag.
    """
    if json_mode is not None:
        return json_mode
    if not ctx_obj:
        return False
    return ctx_obj.get("json", False)
