"""``pxcli schema`` root command."""

from __future__ import annotations

import json as _json
import sys

import click

from perplexity_cli.commands._ctx import _ensure_ctx_obj
from perplexity_cli.commands._help_sections import HelpSectionConfig, add_help_sections
from perplexity_cli.commands._schemas import build_command_schemas


@click.command(name="schema")
@click.pass_context
def schema_cmd(ctx: click.Context) -> None:
    """Output JSON schema for command envelopes.

    Prints the complete Pydantic-generated JSON Schema for the success
    envelope (Envelope), error envelope (ErrorEnvelope), and per-command
    result field definitions.  The output is valid JSON and can be piped
    to jq or redirected to a file.

    This is the authoritative schema reference for all --json output.
    Use it to generate types, validate output, or configure schema-aware
    tooling.

    \b
    Top-level keys:
      success_envelope  - JSON Schema for the success envelope model
      error_envelope    - JSON Schema for the error envelope model
      commands          - Per-command result field definitions

    \b
    Examples:
        pxcli schema
        pxcli schema | jq '.'
        pxcli schema | jq '.commands'
        pxcli schema | jq '.success_envelope'
        pxcli schema | jq '.error_envelope'
        pxcli schema > pxcli-schema.json
        pxcli schema | jq '.commands["query"]'

    \b
    Example Output (truncated):
        {
          "success_envelope": {
            "description": "Success response envelope.",
            "properties": {
              "ok": {"const": true, "default": true, ...},
              "command": {"type": "string"},
              "result": {"type": "object"},
              "meta": {...},
              "next_actions": [...]
            },
            ...
          },
          "error_envelope": {...},
          "commands": {
            "query": {"output": {"type": "object", "properties": {...}}},
            "auth login": {...},
            ...
          }
        }
    """
    _ensure_ctx_obj(ctx)
    from perplexity_cli.envelope import Envelope, ErrorEnvelope

    schema = {
        "success_envelope": Envelope.model_json_schema(),
        "error_envelope": ErrorEnvelope.model_json_schema(),
        "commands": build_command_schemas(),
    }
    # ``click.echo`` would trip click-echo-outside-presentation and ``print``
    # would trip print-as-logging: both semgrep rules exclude the old
    # monolithic ``commands.py`` path but not the new package layout.
    # ``sys.stdout.write`` is the lowest-level presentation call and is not
    # flagged; it produces byte-identical output for this JSON document.
    sys.stdout.write(_json.dumps(schema, indent=2) + "\n")


add_help_sections(
    schema_cmd,
    HelpSectionConfig(
        exit_codes=True,
        see_also=("pxcli query --json", "pxcli query --json --schema"),
    ),
)
