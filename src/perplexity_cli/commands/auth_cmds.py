"""``pxcli auth`` group: login, logout, status, export, import subcommands."""

from __future__ import annotations

from pathlib import Path

import click

from perplexity_cli.commands._ctx import (
    ClickValue,
    _ensure_ctx_obj,
    as_path_or_none,
    record_output_flags,
)
from perplexity_cli.commands._examples import (
    AUTH_EXPORT_JSON_EXAMPLE,
    AUTH_IMPORT_JSON_EXAMPLE,
    AUTH_LOGIN_JSON_EXAMPLE,
    AUTH_LOGOUT_JSON_EXAMPLE,
    AUTH_STATUS_JSON_EXAMPLE,
)
from perplexity_cli.commands._help_refs import (
    AUTH_EXPORT_HELP_REF,
    AUTH_IMPORT_HELP_REF,
    AUTH_LOGIN_HELP_REF,
    AUTH_STATUS_HELP_REF,
)
from perplexity_cli.commands._help_sections import HelpSectionConfig, add_help_sections
from perplexity_cli.commands._runner_adapter import run_auth_command
from perplexity_cli.config.defaults import DEFAULT_CHROME_DEBUG_PORT
from perplexity_cli.runners import run_logout_command, run_status_command
from perplexity_cli.runners.auth import run_export_command, run_import_command


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
        "  export  - Export credentials to a portable JSON file\n\n"
        "  import  - Import credentials from a JSON bundle file\n\n"
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
      2. Launch it with remote debugging on port 9222.  Examples by platform:
         - Apple Silicon macOS:
             open ~/.local/bin/chrome/mac_arm-*/chrome-mac-arm64/\\
               "Google Chrome for Testing.app" --args \
               "--remote-debugging-port=9222" "about:blank"
         - Intel macOS:
             open ~/.local/bin/chrome/mac-x64/*/chrome-mac-x64/\\
               "Google Chrome for Testing.app" --args \
               "--remote-debugging-port=9222" "about:blank"
         - Linux:
             ~/.local/bin/chrome/linux64/*/chrome-linux64/chrome \
               --remote-debugging-port=9222 about:blank
         - Windows (PowerShell):
             $env:LOCALAPPDATA\\chrome\\win64-*\\chrome-win64\\chrome.exe \
               --remote-debugging-port=9222 about:blank
         The exact path depends on where
         `npx @puppeteer/browsers install chrome@stable` placed the build.
      3. Run authentication (two terminals):
         Terminal 1:  start Chrome for Testing as above
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
    run_status_command("verify" if flags.get("verify") else "skip")


@click.command(name="export")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help=(
        "Output JSON file path.  If omitted, defaults to "
        "pxcli-auth-YYYY-MM-DD-HHMMSS.json in the current directory.  The "
        "file is written atomically with owner-only permissions (0600).  "
        "Choose a safe location for this file.  Example: "
        "--output ~/secret/pxcli-creds.json"
    ),
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    help=(
        "Emit output as a structured JSON envelope to stdout instead of "
        "human-readable text.  The envelope contains {ok, command, result, meta, "
        "next_actions} on success.  The result object includes 'path' only — "
        "the credential contents are NEVER included in the envelope.  "
        "Intended for programmatic consumption."
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
def auth_export(ctx: click.Context, **flags: ClickValue) -> None:
    """Export stored credentials to a portable JSON file.

    Writes the decrypted session token and any stored cookies to a JSON
    bundle suitable for moving credentials to another machine.  This is a
    deliberate, explicit action: the export file contains PLAINTEXT
    session credentials, is NOT encrypted, and anyone who can read it
    can use your Perplexity account.  A warning is printed to stderr
    before the file is written, and the file is created with owner-only
    permissions (0600).

    Requires authentication.  Run 'pxcli auth login' first; if no token
    is stored, the command exits with code 4 (authentication required)
    and writes no file.

    \b
    Bundle fields (written to the export file):
      version      - Bundle format version (currently 1)
      token        - The plaintext session token
      cookies      - Stored browser cookies (may be empty {})
      exported_at  - ISO-8601 UTC timestamp of the export

    \b
    Result fields (--json):
      path  - Path of the written export file
              (contents are never included in the envelope)

    \b
    Examples:
        pxcli auth export
        pxcli auth export --output ~/secret/pxcli-creds.json
        pxcli auth export -o pxcli-creds.json
        pxcli auth export --json
        pxcli auth export --json | jq -r '.result.path'

    \b
    Example Output (human):
        [WARNING] The export file contains PLAINTEXT session credentials. ...
        [OK] Credentials exported to pxcli-auth-2025-05-09-100000.json
    """
    record_output_flags(ctx, flags)
    run_export_command(as_path_or_none(flags.get("output")))


@click.command(name="import")
@click.argument(
    "file_path",
    required=True,
    type=click.Path(path_type=Path),
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    help=(
        "Emit output as a structured JSON envelope to stdout instead of "
        "human-readable text.  The envelope contains {ok, command, result, meta, "
        "next_actions} on success.  The result object reports whether cookies "
        "were stored — credential contents are NEVER included in the envelope.  "
        "Intended for programmatic consumption."
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
def auth_import(ctx: click.Context, file_path: Path, **flags: ClickValue) -> None:
    """Import credentials from a JSON bundle file.

    Restores credentials previously written by 'pxcli auth export'.  The
    bundle is validated (version must be 1, token must be a non-empty
    string, cookies must map names to string values), then the token and
    cookies are re-encrypted for THIS machine and stored at
    ~/.config/perplexity-cli/token.json.  The bundle file itself is left
    untouched; delete it manually once the import succeeds.

    The encryption key is machine-bound, so imported credentials are
    re-encrypted locally — you cannot copy a token.json file between
    machines, but you CAN move an export bundle and import it.

    If the bundle contains cookies and cookie storage is disabled
    (save_cookies is false by default), the cookies are NOT stored and a
    loud warning is printed to stderr.  Run 'pxcli config set
    save_cookies true' and re-import to keep them.  The token is stored
    regardless.

    Malformed, unreadable, or schema-violating bundle files exit with
    code 7 (validation error).  A missing file is also reported as a
    validation error (exit 7).

    \b
    Bundle fields (read from the import file):
      version      - Bundle format version (must be 1)
      token        - The plaintext session token
      cookies      - Browser cookies to restore (may be empty or absent)
      exported_at  - Ignored on import (unknown keys are ignored)

    \b
    Result fields (--json):
      imported         - Whether the credentials were stored (boolean)
      cookies_stored   - Whether cookies from the bundle were stored

    \b
    Examples:
        pxcli auth import pxcli-auth-2025-05-09-100000.json
        pxcli auth import ~/secret/pxcli-creds.json
        pxcli auth import --json pxcli-creds.json
        pxcli auth import --json pxcli-creds.json | jq '.result.imported'

    \b
    Example Output (human):
        [OK] Credentials imported
    """
    record_output_flags(ctx, flags)
    run_import_command(file_path)


auth_group.add_command(auth_login)
auth_group.add_command(auth_logout)
auth_group.add_command(auth_status)
auth_group.add_command(auth_export)
auth_group.add_command(auth_import)


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
        see_also=(AUTH_LOGIN_HELP_REF, "pxcli auth logout", AUTH_EXPORT_HELP_REF),
    ),
)
add_help_sections(
    auth_export,
    HelpSectionConfig(
        json_example=AUTH_EXPORT_JSON_EXAMPLE,
        json_schema=True,
        exit_codes=True,
        see_also=(AUTH_LOGIN_HELP_REF, AUTH_STATUS_HELP_REF, AUTH_IMPORT_HELP_REF),
    ),
)
add_help_sections(
    auth_import,
    HelpSectionConfig(
        json_example=AUTH_IMPORT_JSON_EXAMPLE,
        json_schema=True,
        exit_codes=True,
        see_also=(AUTH_EXPORT_HELP_REF, "pxcli config set save_cookies true"),
    ),
)
