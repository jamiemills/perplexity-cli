"""``pxcli style`` group: set, show, clear subcommands."""

from __future__ import annotations

import click

from perplexity_cli.commands._ctx import ClickValue, _ensure_ctx_obj, record_output_flags
from perplexity_cli.commands._examples import (
    STYLE_CLEAR_JSON_EXAMPLE,
    STYLE_SET_JSON_EXAMPLE,
    STYLE_SHOW_JSON_EXAMPLE,
)
from perplexity_cli.commands._help_refs import STYLE_SET_HELP_REF
from perplexity_cli.commands._help_sections import HelpSectionConfig, add_help_sections


@click.group(
    "style",
    help=(
        "Style prompt commands.\n\n"
        "Manage a persistent style prompt that is automatically appended to all "
        "queries.  This is useful for standardising response formatting (e.g. "
        "'be brief and concise') without repeating instructions in every query.\n\n"
        "The style is stored in ~/.config/perplexity-cli/style.json and persists "
        "across CLI sessions.\n\n"
        "Subcommands:\n\n"
        "  set   - Configure a style prompt\n\n"
        "  show  - View the currently configured style\n\n"
        "  clear - Remove the configured style\n\n"
        "Quick start:\n\n"
        "  pxcli style set 'be brief and concise'\n\n"
        "  pxcli style show\n\n"
        "  pxcli style clear"
    ),
)
@click.pass_context
def style_group(ctx: click.Context) -> None:
    """Style prompt commands."""
    _ensure_ctx_obj(ctx)


@click.command(name="set")
@click.argument("style", required=True)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    help=(
        "Emit output as a structured JSON envelope to stdout instead of "
        "human-readable text.  The envelope contains {ok, command, result, meta, "
        "next_actions} on success.  Intended for programmatic consumption."
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
def style_set(ctx: click.Context, style: str, **flags: ClickValue) -> None:
    """Configure a style prompt to apply to all queries.

    Sets a custom style instruction that is automatically appended to every
    subsequent query.  This allows you to control response formatting,
    length, tone, or focus without repeating the instruction each time.

    The STYLE argument is a free-text string.  Wrap it in quotes if it
    contains spaces.  The style is stored persistently in
    ~/.config/perplexity-cli/style.json and survives CLI restarts.

    Setting a new style replaces any previously configured style.  Use
    'pxcli style clear' to remove it entirely.

    \b
    Arguments:
      STYLE  The style instruction to apply.  This text is appended to
             every query sent to Perplexity.ai.  Examples:
               "be brief and concise"
               "respond in bullet points"
               "answer as if explaining to a 10-year-old"
               "provide academic references where possible"

    \b
    Examples:
        pxcli style set "be brief and concise"
        pxcli style set "respond in bullet points"
        pxcli style set "provide super brief answers in minimal words"
        pxcli style set "be brief" --json
        pxcli style set "be brief" --json | jq '.result.style'

    \b
    Example Output (human):
        [OK] Style set to: be brief and concise
    """
    record_output_flags(ctx, flags)
    from perplexity_cli.runners import run_configure_command

    run_configure_command(style)


@click.command(name="show")
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    help=(
        "Emit output as a structured JSON envelope to stdout instead of "
        "human-readable text.  The envelope contains {ok, command, result, meta, "
        "next_actions} on success.  Intended for programmatic consumption."
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
def style_show(ctx: click.Context, **flags: ClickValue) -> None:
    """View currently configured style.

    Displays the style prompt that is being appended to all queries.  If no
    style is configured, reports that no style is set.

    The style value is read from ~/.config/perplexity-cli/style.json.

    \b
    Result fields:
      style  - The currently configured style string, or null if none is set.

    \b
    Examples:
        pxcli style show
        pxcli style show --json
        pxcli style show --json | jq -r '.result.style'

    \b
    Example Output (human, style configured):
        Current style: be brief and concise

    \b
    Example Output (human, no style):
        No style configured.
    """
    record_output_flags(ctx, flags)
    from perplexity_cli.runners import run_view_style_command

    run_view_style_command()


@click.command(name="clear")
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    help=(
        "Emit output as a structured JSON envelope to stdout instead of "
        "human-readable text.  The envelope contains {ok, command, result, meta, "
        "next_actions} on success.  Intended for programmatic consumption."
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
def style_clear(ctx: click.Context, **flags: ClickValue) -> None:
    """Clear configured style.

    Removes the style prompt so that queries are no longer modified.  If no
    style was configured, the command succeeds silently (exit code 0).

    \b
    Result fields:
      had_style  - Whether a style was previously configured (boolean).

    \b
    Examples:
        pxcli style clear
        pxcli style clear --json
        pxcli style clear --json | jq '.result.had_style'

    \b
    Example Output (human, style existed):
        [OK] Style cleared.

    \b
    Example Output (human, no style):
        No style was configured.
    """
    record_output_flags(ctx, flags)
    from perplexity_cli.runners import run_clear_style_command

    run_clear_style_command()


style_group.add_command(style_set)
style_group.add_command(style_show)
style_group.add_command(style_clear)


add_help_sections(
    style_set,
    HelpSectionConfig(
        json_example=STYLE_SET_JSON_EXAMPLE,
        json_schema=True,
        exit_codes=True,
        see_also=("pxcli style show", "pxcli style clear"),
    ),
)
add_help_sections(
    style_show,
    HelpSectionConfig(
        json_example=STYLE_SHOW_JSON_EXAMPLE,
        json_schema=True,
        exit_codes=True,
        see_also=(STYLE_SET_HELP_REF, "pxcli style clear"),
    ),
)
add_help_sections(
    style_clear,
    HelpSectionConfig(
        json_example=STYLE_CLEAR_JSON_EXAMPLE,
        json_schema=True,
        exit_codes=True,
        see_also=(STYLE_SET_HELP_REF,),
    ),
)
