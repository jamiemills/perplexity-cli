"""``pxcli auth`` group: login, logout, status subcommands."""

from __future__ import annotations

import click

from perplexity_cli.commands._ctx import ClickValue, _ensure_ctx_obj, record_output_flags
from perplexity_cli.commands._examples import (
    AUTH_LOGIN_JSON_EXAMPLE,
    AUTH_LOGOUT_JSON_EXAMPLE,
    AUTH_STATUS_JSON_EXAMPLE,
)
from perplexity_cli.commands._help_refs import AUTH_LOGIN_HELP_REF, AUTH_STATUS_HELP_REF
from perplexity_cli.commands._help_sections import HelpSectionConfig, add_help_sections
from perplexity_cli.commands._runner_adapter import run_auth_command
from perplexity_cli.config.defaults import DEFAULT_CHROME_DEBUG_PORT


@click.group(
    "auth",
    help=(
        "Authentication commands.\n\n"
        "Manage your Perplexity.ai authentication credentials.  Authentication "
        "is performed once via Chrome DevTools Protocol and the resulting session "
        "token is stored locally in encrypted form.  Subsequent CLI commands reuse "
        "the stored token without requiring a browser.\n\n"
        "Authentication is optional for basic queries but required for features "
        "that need an authenticated session, such as file attachments and thread "
        "export.\n\n"
        "Subcommands:\n\n"
        "  login   - Extract and store a session token from Chrome\n\n"
        "  logout  - Remove stored credentials\n\n"
        "  status  - Check current authentication state\n\n"
        "Quick start:\n\n"
        "  pxcli auth login          # Authenticate\n\n"
        "  pxcli auth status         # Verify\n\n"
        "  pxcli auth status --verify  # Live API check\n\n"
        "  pxcli auth logout         # Remove credentials"
    ),
)
@click.pass_context
def auth_group(ctx: click.Context) -> None:
    """Authentication commands."""
    _ensure_ctx_obj(ctx)


@click.command(name="login")
@click.option(
    "--port",
    "-p",
    default=None,
    type=int,
    help=(
        "Chrome remote debugging port to connect to.  Chrome for Testing must be "
        "running with --remote-debugging-port set to this value.  If omitted, "
        "defaults to 9222.  Use a different port when 9222 is already in use by "
        "another process.  Example: --port 9223"
    ),
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    help=(
        "Emit output as a structured JSON envelope to stdout instead of "
        "human-readable text.  The envelope contains {ok, command, result, meta, "
        "next_actions} on success, or {ok, command, error, fix, next_actions} on "
        "failure.  Intended for programmatic consumption by scripts and agents."
    ),
)
@click.option(
    "--schema",
    "schema_flag",
    is_flag=True,
    help=(
        "Embed the full JSON Schema definition as a $schema key in the JSON "
        "envelope output.  Only effective when --json is also specified; silently "
        "ignored otherwise.  Useful for schema validation pipelines."
    ),
)
@click.pass_context
def auth_login(ctx: click.Context, port: int | None, **flags: ClickValue) -> None:
    """Authenticate with Perplexity.ai via Chrome DevTools Protocol.

    Performs a one-time authentication setup by connecting to a running
    Chrome for Testing instance, navigating to Perplexity.ai, waiting for
    you to log in (if not already logged in), and extracting the session
    token.  The token is stored locally in encrypted form at
    ~/.config/perplexity-cli/token.json and reused by all subsequent CLI
    commands.

    This command does NOT open a browser for you.  You must start Chrome
    for Testing separately with remote debugging enabled.

    \b
    SETUP INSTRUCTIONS:
      1. Install Chrome for Testing:
         npx @puppeteer/browsers install chrome@stable
      2. Create a shell alias in ~/.bashrc or ~/.zshrc:
         alias chromefortesting='open ~/.local/bin/chrome/mac_arm-*/\\
           chrome-mac-arm64/Google\\ Chrome\\ for\\ Testing.app \\
           --args "--remote-debugging-port=9222" "about:blank"'
      3. Run authentication (two terminals):
         Terminal 1:  chromefortesting
         Terminal 2:  pxcli auth login

    The authentication flow has a 120-second timeout.  If you are not
    already logged in to Perplexity.ai in the Chrome instance, you will
    need to complete the login within that window.

    \b
    Examples:
        pxcli auth login
        pxcli auth login --port 9223
        pxcli auth login -p 9223
        pxcli auth login --json
        pxcli auth login --json --schema
        pxcli auth login --json | jq '.result.token_path'

    \b
    Example Output (human):
        [OK] Authentication successful!
        Token stored at: /Users/you/.config/perplexity-cli/token.json
        Cookies stored: 12
    """
    record_output_flags(ctx, flags)
    run_auth_command(ctx.obj, port or DEFAULT_CHROME_DEBUG_PORT)


@click.command(name="logout")
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
def auth_logout(ctx: click.Context, **flags: ClickValue) -> None:
    """Log out and remove stored credentials.

    Deletes the locally stored authentication token and any cached browser
    cookies.  After logging out, commands that require authentication (such
    as file attachments and thread export) will fail until you re-authenticate
    with 'pxcli auth login'.

    Basic queries that do not require authentication will continue to work
    after logout.

    The credential file at ~/.config/perplexity-cli/token.json is removed.
    If no credentials exist, the command succeeds silently (exit code 0).

    \b
    Examples:
        pxcli auth logout
        pxcli auth logout --json
        pxcli auth logout --json | jq '.result.credentials_existed'

    \b
    Example Output (human):
        [OK] Logged out successfully.
    """
    record_output_flags(ctx, flags)
    from perplexity_cli.runners import run_logout_command

    run_logout_command()


@click.command(name="status")
@click.option(
    "--verify",
    is_flag=True,
    default=False,
    help=(
        "Perform a live API verification check against Perplexity.ai to "
        "confirm the stored token is still valid.  Without this flag, the "
        "command only checks whether a token file exists locally.  The "
        "verification request has a 10-second timeout."
    ),
)
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
def auth_status(ctx: click.Context, **flags: ClickValue) -> None:
    """Show current authentication status.

    Reports whether a valid authentication token is stored locally, where
    the token file is located, the token's age in days, and how many browser
    cookies are cached.

    By default this is a local-only check — it reads the token file without
    making any network requests.  Add --verify to perform a live API call
    that confirms the token is still accepted by Perplexity.ai.

    \b
    Result fields:
      authenticated   - Whether a token file exists (boolean)
      token_path      - Absolute path to the token file
      token_age_days  - Number of days since the token was stored (or null)
      cookies_stored  - Count of cached browser cookies
      verified        - Live verification result (null if --verify not used)

    \b
    Examples:
        pxcli auth status
        pxcli auth status --verify
        pxcli auth status --json
        pxcli auth status --json --verify
        pxcli auth status --json | jq '.result.authenticated'

    \b
    Example Output (human):
        Authenticated: Yes
        Token path:    /Users/you/.config/perplexity-cli/token.json
        Token age:     3 days
        Cookies:       12
    """
    record_output_flags(ctx, flags)
    from perplexity_cli.runners import run_status_command

    run_status_command("verify" if flags.get("verify") else "skip")


auth_group.add_command(auth_login)
auth_group.add_command(auth_logout)
auth_group.add_command(auth_status)


add_help_sections(
    auth_login,
    HelpSectionConfig(
        json_example=AUTH_LOGIN_JSON_EXAMPLE,
        json_schema=True,
        exit_codes=True,
        see_also=(AUTH_STATUS_HELP_REF, "pxcli auth logout"),
    ),
)
add_help_sections(
    auth_logout,
    HelpSectionConfig(
        json_example=AUTH_LOGOUT_JSON_EXAMPLE,
        json_schema=True,
        exit_codes=True,
        see_also=(AUTH_LOGIN_HELP_REF, AUTH_STATUS_HELP_REF),
    ),
)
add_help_sections(
    auth_status,
    HelpSectionConfig(
        json_example=AUTH_STATUS_JSON_EXAMPLE,
        json_schema=True,
        exit_codes=True,
        see_also=(AUTH_LOGIN_HELP_REF, "pxcli auth logout"),
    ),
)
