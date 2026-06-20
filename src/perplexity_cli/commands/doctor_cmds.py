"""``pxcli doctor`` group: security subcommand."""

from __future__ import annotations

import click

from perplexity_cli.commands._ctx import ClickValue, record_output_flags
from perplexity_cli.commands._examples import DOCTOR_SECURITY_JSON_EXAMPLE
from perplexity_cli.commands._help_sections import HelpSectionConfig, add_help_sections


@click.group(
    help=(
        "Diagnostic commands for local environment and storage state.\n\n"
        "Run checks against the local pxcli installation to verify that "
        "credential storage, file permissions, and cache state are healthy.  "
        "Useful for troubleshooting authentication or permission issues.\n\n"
        "Subcommands:\n\n"
        "  security  - Report credential and cache storage security details\n\n"
        "Usage:\n\n"
        "  pxcli doctor security\n\n"
        "  pxcli doctor security --json"
    ),
)
def doctor() -> None:
    """Diagnostic commands for local environment and storage state."""


@click.command(name="security")
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    help=(
        "Emit output as a structured JSON envelope to stdout instead of "
        "human-readable text.  The envelope contains {ok, command, result, meta, "
        "next_actions} on success.  Intended for programmatic consumption and "
        "automated security auditing."
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
def doctor_security(ctx: click.Context, **flags: ClickValue) -> None:
    """Report local credential and cache storage security details.

    Inspects the local file system to report the storage backend in use,
    file locations, file permissions, and whether cookie storage is enabled.
    This command helps you verify that credentials are stored securely and
    that file permissions are appropriately restricted (e.g. 600).

    \b
    Checks performed:
      - Storage backend type (encrypted_file, plaintext, etc.)
      - Token file path and Unix permission mode
      - Cache file path and Unix permission mode
      - Whether cookie storage is enabled in configuration

    \b
    Result fields (--json):
      storage_backend    - The storage backend in use (e.g. "encrypted_file")
      token_path         - Absolute path to the token file
      token_permissions  - Unix permission string (e.g. "600")
      cache_path         - Absolute path to the thread cache file
      cache_permissions  - Unix permission string (e.g. "600")
      cookies_enabled    - Whether cookie storage is turned on (boolean)

    \b
    Examples:
        pxcli doctor security
        pxcli doctor security --json
        pxcli doctor security --json | jq '.result.token_permissions'

    \b
    Example Output (human):
        Storage backend: encrypted_file
        Token path:      /Users/you/.config/perplexity-cli/token.json
        Token perms:     600
        Cache path:      /Users/you/.config/perplexity-cli/threads_cache.json
        Cache perms:     600
        Cookies:         enabled
    """
    record_output_flags(ctx, flags)
    from perplexity_cli.runners import run_doctor_security_command

    run_doctor_security_command()


doctor.add_command(doctor_security)


add_help_sections(
    doctor_security,
    HelpSectionConfig(
        json_example=DOCTOR_SECURITY_JSON_EXAMPLE,
        json_schema=True,
        exit_codes=True,
        see_also=("pxcli auth status", "pxcli auth login"),
    ),
)
