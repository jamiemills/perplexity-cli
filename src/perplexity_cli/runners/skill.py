"""Skill display command runner."""

from __future__ import annotations

# nosemgrep: python.lang.compatibility.python37.python37-compatibility-importlib2
from importlib.resources import files
from typing import Any, cast

import click

from perplexity_cli._types import OutputFormat, SchemaInclusion
from perplexity_cli.envelope import success_envelope, write_envelope
from perplexity_cli.runners._utils import resolve_json_flag


def _load_skill_content() -> str:
    """Load the skill definition content from package resources."""
    try:
        return files("perplexity_cli.resources").joinpath("skill.md").read_text(encoding="utf-8")
    except (FileNotFoundError, AttributeError):
        return (
            "Agent Skill definition not available. "
            "Run 'perplexity-cli --help' for usage information."
        )


def _resolve_ctx_flags(json_mode: bool | None) -> tuple[OutputFormat, SchemaInclusion]:
    """Resolve json_mode and include_schema from the click context."""
    ctx: click.Context | None = click.get_current_context(silent=True)
    ctx_obj: dict[str, Any] = cast(dict[str, Any], ctx.obj if ctx is not None and ctx.obj else {})
    resolved_json: bool = resolve_json_flag(json_mode, ctx_obj)
    include_schema: bool = bool(ctx_obj.get("schema", False))
    return (
        "json" if resolved_json else "human",
        "with_schema" if include_schema else "no_schema",
    )


def run_show_skill_command(*, json_mode: bool | None = None) -> None:
    """Execute the show-skill command."""
    skill_content = _load_skill_content()
    output_format, include_schema = _resolve_ctx_flags(json_mode)

    if output_format == "json":
        env = success_envelope("pxcli skill show", {"content": skill_content})
        write_envelope(env, include_schema=include_schema)
        return

    click.echo(skill_content)
