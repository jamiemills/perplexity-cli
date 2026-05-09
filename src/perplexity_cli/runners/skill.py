"""Skill display command runner."""

from importlib.resources import files

import click


def run_show_skill_command() -> None:
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
    click.echo(skill_content)
