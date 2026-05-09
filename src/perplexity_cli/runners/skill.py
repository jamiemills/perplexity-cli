"""Skill display command runner."""

from importlib.resources import files

import click

from perplexity_cli.envelope import success_envelope, write_envelope


def run_show_skill_command(*, json_mode: bool | None = None) -> None:
    """Execute the show-skill command."""
    try:
        skill_content = (
            files("perplexity_cli.resources").joinpath("skill.md").read_text(encoding="utf-8")
        )
    except (FileNotFoundError, AttributeError):
        skill_content = (
            "Agent Skill definition not available. "
            "Run 'perplexity-cli --help' for usage information."
        )

    ctx = click.get_current_context(silent=True)
    ctx_obj = ctx.obj if ctx else {}
    if json_mode is None:
        json_mode = ctx_obj.get("json", False) if ctx_obj else False
    include_schema = ctx_obj.get("schema", False) if ctx_obj else False

    if json_mode:
        ctx = click.get_current_context(silent=True)
        ctx_obj = ctx.obj if ctx else {}
        include_schema = ctx_obj.get("schema", False) if ctx_obj else False
        env = success_envelope("pxcli skill show", {"content": skill_content})
        write_envelope(env, include_schema=include_schema)
        return

    click.echo(skill_content)
