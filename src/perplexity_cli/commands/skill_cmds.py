"""``pxcli skill`` group: show subcommand."""

from __future__ import annotations

import click

from perplexity_cli.commands._ctx import ClickValue, _ensure_ctx_obj, record_output_flags
from perplexity_cli.commands._examples import SKILL_SHOW_JSON_EXAMPLE
from perplexity_cli.commands._help_sections import HelpSectionConfig, add_help_sections


@click.group(
    "skill",
    help=(
        "Agent skill commands.\n\n"
        "Manage and view the agent skill definition that describes how AI agents "
        "and LLM-based tools can use perplexity-cli as a web search and research "
        "tool.  The skill definition (SKILL.md) provides structured guidance for "
        "agent integration including JSON output parsing patterns, common "
        "workflows, and practical examples.\n\n"
        "Subcommands:\n\n"
        "  show  - Display the SKILL.md agent skill definition\n\n"
        "Usage:\n\n"
        "  pxcli skill show\n\n"
        "  pxcli skill show --json"
    ),
)
@click.pass_context
def skill_group(ctx: click.Context) -> None:
    """Agent skill commands."""
    _ensure_ctx_obj(ctx)


@click.command(name="show")
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    help=(
        "Emit output as a structured JSON envelope to stdout instead of "
        "rendering the SKILL.md as human-readable text.  The skill content "
        "is returned in result.content as a string.  Intended for "
        "programmatic consumption by agent frameworks."
    ),
)
@click.option(
    "--schema",
    "schema_flag",
    is_flag=True,
    help=(
        "Embed the full JSON Schema definition as a $schema key in the JSON "
        "envelope output.  Only effective when --json is also specified."
    ),
)
@click.pass_context
def skill_show(ctx: click.Context, **flags: ClickValue) -> None:
    """Display the Agent Skill definition for using perplexity-cli.

    Outputs the full SKILL.md content that describes how to use perplexity-cli
    as an agent tool.  The skill definition includes:

    \b
      - Tool description and capabilities summary
      - JSON output parsing examples with jq patterns
      - Common workflows (search, research, fact-checking)
      - Error handling guidance
      - Integration patterns for agent frameworks

    This is intended for AI agents, LLM tool-use pipelines, and developers
    building integrations with perplexity-cli.  The output can be piped into
    a file or consumed programmatically via --json.

    \b
    Result fields (--json):
      content  - The full SKILL.md content as a string.

    \b
    Examples:
        pxcli skill show
        pxcli skill show | less
        pxcli skill show > skill-definition.md
        pxcli skill show --json
        pxcli skill show --json | jq -r '.result.content'

    \b
    Example Output (human, truncated):
        # perplexity-cli Agent Skill
        Use perplexity-cli as an alternative to web search ...
    """
    record_output_flags(ctx, flags)
    from perplexity_cli.runners import run_show_skill_command

    run_show_skill_command()


skill_group.add_command(skill_show)


add_help_sections(
    skill_show,
    HelpSectionConfig(
        json_example=SKILL_SHOW_JSON_EXAMPLE,
        json_schema=True,
        exit_codes=True,
        see_also=("pxcli query", "pxcli schema"),
    ),
)
