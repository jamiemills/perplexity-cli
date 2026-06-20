"""``pxcli models`` group: list subcommand."""

from __future__ import annotations

import click

from perplexity_cli.commands._ctx import ClickValue, _ensure_ctx_obj, record_output_flags
from perplexity_cli.commands._help_sections import HelpSectionConfig, add_help_sections


@click.group(
    "models",
    help=(
        "Model listing and information.\n\n"
        "Query the Perplexity model catalogue to discover which models are "
        "available for your subscription tier, for use with the --model "
        "flag on the query command.\n\n"
        "Subcommands:\n\n"
        "  list  - List models available to your subscription tier\n\n"
        "Quick start:\n\n"
        "  pxcli models list                # Show available models\n\n"
        "  pxcli models list --json         # JSON envelope output\n\n"
        "  pxcli query -m gpt54 'question'  # Use a specific model"
    ),
)
@click.pass_context
def models_group(ctx: click.Context) -> None:
    """Model listing and information."""
    _ensure_ctx_obj(ctx)


@click.command(name="list")
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
def models_list(ctx: click.Context, **flags: ClickValue) -> None:
    """List available models.

    Fetches the model catalogue from Perplexity and displays the models
    accessible to your subscription tier.  Each model is shown with its
    identifier (for use with --model), display name, and a short
    description.  Models that require a higher tier are excluded.

    Requires authentication.  Run 'pxcli auth login' first if you have
    not already authenticated.

    \b
    Result fields (--json):
      models  - Array of model objects, each containing:
        model_id         - Identifier for use with --model
        label            - Human-readable display name
        tier             - Subscription tier: 'pro' or 'max'
        description      - Short model description
        reasoning_model  - Reasoning variant ID (or null)
        is_default       - Whether this is the default model

    \b
    Examples:
        pxcli models list
        pxcli models list --json
        pxcli models list --json | jq '.result.models[].model_id'
        pxcli models list --json --schema

    \b
    Example Output (human):
        MODEL ID        LABEL                  TIER  DESCRIPTION
        --------------  ---------------------  ----  -------------------------
        pplx_pro        Best (default)         Pro   Auto-select the best model
        gpt54           GPT-5.4                Pro   OpenAI GPT-5.4
        claude46sonnet  Claude Sonnet 4.6      Pro   Anthropic Claude
    """
    record_output_flags(ctx, flags)
    from perplexity_cli.runners.models import run_models_list_command

    run_models_list_command(ctx.obj)


models_group.add_command(models_list)


add_help_sections(
    models_list,
    HelpSectionConfig(
        exit_codes=True,
        see_also=("pxcli query --model",),
    ),
)
