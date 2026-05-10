"""Click command definitions for the CLI."""

from __future__ import annotations

import json as _json
import textwrap
from pathlib import Path
from typing import Any

import click

# ---------------------------------------------------------------------------
# Group callbacks - ensure ctx.obj is always a dict
# ---------------------------------------------------------------------------


def _ensure_ctx_obj(ctx: click.Context) -> None:
    ctx.ensure_object(dict)


# ---------------------------------------------------------------------------
# Enhanced help formatting
# ---------------------------------------------------------------------------


def _add_help_sections(
    cmd: click.Command,
    *,
    exit_codes: bool = False,
    see_also: list[str] | None = None,
    env_vars: list[str] | None = None,
    json_example: str | None = None,
    ndjson_example: str | None = None,
    json_schema: bool = False,
) -> click.Command:
    """Wrap a Click command's format_help to append standard sections.

    Parameters
    ----------
    exit_codes:
        Append the standard exit-code table.
    see_also:
        List of related commands to reference.
    env_vars:
        Environment variables relevant to this command.
    json_example:
        A realistic JSON output example to display under "Example Output".
    ndjson_example:
        An NDJSON streaming output example (used by ``query``).
    json_schema:
        When ``True``, append the full Pydantic JSON Schema for
        ``Envelope`` and ``ErrorEnvelope``.
    """
    original_format_help = cmd.format_help

    def enhanced_format_help(ctx: click.Context, formatter: click.HelpFormatter) -> None:
        original_format_help(ctx, formatter)

        if json_example:
            formatter.write("\n")
            formatter.write("Example Output (--json):\n")
            for line in json_example.strip().splitlines():
                formatter.write("  " + line + "\n")
            formatter.write("\n")

        if ndjson_example:
            formatter.write("\n")
            formatter.write("NDJSON Streaming Output (--json --stream):\n")
            formatter.write(
                "  Each line is a self-contained JSON object.  Event types:\n"
                "  start, progress, chunk, result (final line).\n\n"
            )
            for line in ndjson_example.strip().splitlines():
                formatter.write("  " + line + "\n")
            formatter.write("\n")

        if json_schema:
            formatter.write("\n")
            formatter.write("JSON Schema (Success Envelope):\n")
            from perplexity_cli.envelope import Envelope

            schema_text = _json.dumps(Envelope.model_json_schema(), indent=2)
            for line in schema_text.splitlines():
                formatter.write("  " + line + "\n")
            formatter.write("\n")

            formatter.write("JSON Schema (Error Envelope):\n")
            from perplexity_cli.envelope import ErrorEnvelope

            err_schema_text = _json.dumps(ErrorEnvelope.model_json_schema(), indent=2)
            for line in err_schema_text.splitlines():
                formatter.write("  " + line + "\n")
            formatter.write("\n")

        if exit_codes:
            formatter.write("\n")
            with formatter.section("Exit Codes"):
                from perplexity_cli.exit_codes import format_exit_codes_help

                for line in format_exit_codes_help().strip().splitlines():
                    if line.startswith("Exit codes:"):
                        continue
                    formatter.write_text(line.strip())

        if see_also:
            formatter.write("\n")
            with formatter.section("See Also"):
                for ref in see_also:
                    formatter.write_text(ref)

        if env_vars:
            formatter.write("\n")
            with formatter.section("Environment Variables"):
                for var in env_vars:
                    formatter.write_text(var)

    setattr(cmd, "format_help", enhanced_format_help)  # noqa: B010 - monkey-patching Click command
    return cmd


# ---------------------------------------------------------------------------
# Shell completion scripts
# ---------------------------------------------------------------------------

_BASH_COMPLETION = """\
_pxcli_completion() {
    local IFS=$'\\n'
    COMPREPLY=( $( env COMP_WORDS="${COMP_WORDS[*]}" \\
                   COMP_CWORD=$COMP_CWORD \\
                   _PXCLI_COMPLETE=bash_complete pxcli ) )
    return 0
}
complete -o default -F _pxcli_completion pxcli
"""

_ZSH_COMPLETION = """\
#compdef pxcli

_pxcli() {
    local -a completions
    local -a completions_with_descriptions
    local -a response
    (( ! $+commands[pxcli] )) && return 1
    response=("${(@f)$(env COMP_WORDS="${words[*]}" COMP_CWORD=$((CURRENT-1)) \\
        _PXCLI_COMPLETE=zsh_complete pxcli)}")
    for key descr in ${(kv)response}; do
        if [[ "$descr" == "_" ]]; then
            completions+=("$key")
        else
            completions_with_descriptions+=("$key":"$descr")
        fi
    done
    if [ -n "$completions_with_descriptions" ]; then
        _describe -V unsorted completions_with_descriptions -U
    fi
    if [ -n "$completions" ]; then
        compadd -U -V unsorted -a completions
    fi
}
if [[ $zsh_eval_context[-1] == loadautofun ]]; then
    _pxcli "$@"
else
    compdef _pxcli pxcli
fi
"""

_FISH_COMPLETION = """\
function __fish_pxcli_complete
    set -lx COMP_WORDS (commandline -cp)
    set -lx COMP_CWORD (math (count (commandline -oc)) - 1)
    set -lx _PXCLI_COMPLETE fish_complete
    set -lx _PXCLI_PROG_NAME pxcli
    pxcli
end
complete -c pxcli -f -a "(__fish_pxcli_complete)"
"""

_AUTH_LOGIN_HELP_REF = "pxcli auth login"
_AUTH_STATUS_HELP_REF = "pxcli auth status"
_STYLE_SET_HELP_REF = "pxcli style set"


# ---------------------------------------------------------------------------
# Schema command result definitions
# ---------------------------------------------------------------------------

_COMMAND_RESULT_SCHEMAS: dict[str, dict[str, Any]] = {
    "query": {
        "answer": {"type": "string"},
        "references": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "snippet": {"type": "string"},
                },
            },
        },
    },
    "auth login": {
        "token_path": {"type": "string"},
        "cookies_stored": {"type": "integer"},
    },
    "auth logout": {
        "credentials_existed": {"type": "boolean"},
    },
    "auth status": {
        "authenticated": {"type": "boolean"},
        "token_path": {"type": "string"},
        "token_age_days": {"type": ["integer", "null"]},
        "cookies_stored": {"type": "integer"},
        "verified": {"type": ["boolean", "null"]},
    },
    "config set": {
        "key": {"type": "string"},
        "value": {"type": "boolean"},
    },
    "config show": {
        "config_path": {"type": "string"},
        "save_cookies": {"type": "boolean"},
        "debug_mode": {"type": "boolean"},
        "env_overrides": {"type": "array", "items": {"type": "string"}},
    },
    "style set": {
        "style": {"type": "string"},
    },
    "style show": {
        "style": {"type": ["string", "null"]},
    },
    "style clear": {
        "had_style": {"type": "boolean"},
    },
    "threads export": {
        "threads": {"type": "array"},
        "total": {"type": "integer"},
        "output_path": {"type": "string"},
        "date_range": {"type": "object"},
    },
    "doctor security": {
        "storage_backend": {"type": "string"},
        "token_path": {"type": "string"},
        "token_permissions": {"type": "string"},
        "cache_path": {"type": "string"},
        "cache_permissions": {"type": "string"},
        "cookies_enabled": {"type": "boolean"},
    },
}


def _build_command_schemas() -> dict[str, dict[str, Any]]:
    """Build per-command schema entries with output definitions."""
    result: dict[str, dict[str, Any]] = {}
    for cmd_name, output_schema in _COMMAND_RESULT_SCHEMAS.items():
        result[cmd_name] = {
            "output": {
                "type": "object",
                "properties": output_schema,
            },
        }
    return result


# ---------------------------------------------------------------------------
# Realistic JSON example output strings used by _add_help_sections
# ---------------------------------------------------------------------------

_QUERY_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "query",
      "result": {
        "answer": "Python is a high-level, general-purpose programming\\n"
                  "language created by Guido van Rossum ...",
        "references": [
          {
            "index": 1,
            "title": "Python (programming language) - Wikipedia",
            "url": "https://en.wikipedia.org/wiki/Python_(programming_language)",
            "snippet": "Python is a high-level, general-purpose programming language."
          }
        ]
      },
      "meta": {
        "duration_ms": 2340,
        "version": "0.7.0",
        "trace_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "truncated": false
      },
      "next_actions": [
        {
          "command": "pxcli query",
          "description": "Ask a follow-up question"
        }
      ]
    }""")

_QUERY_NDJSON_EXAMPLE = textwrap.dedent("""\
    {"type": "start", "ts": "2025-05-09T10:00:00+00:00", "command": "query"}
    {"type": "chunk", "ts": "2025-05-09T10:00:01+00:00", "text": "Python is a"}
    {"type": "chunk", "ts": "2025-05-09T10:00:01+00:00", "text": " high-level"}
    {"type": "chunk", "ts": "2025-05-09T10:00:02+00:00", "text": " programming language..."}
    {"type": "result", "ts": "2025-05-09T10:00:03+00:00", "ok": true, "command": "query", "result": {"answer": "Python is a high-level programming language...", "references": [...]}, "meta": {"duration_ms": 3000, "version": "0.7.0", "trace_id": "...", "truncated": false}, "next_actions": []}""")

_AUTH_LOGIN_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "auth login",
      "result": {
        "token_path": "/Users/you/.config/perplexity-cli/token.json",
        "cookies_stored": 12
      },
      "meta": {
        "duration_ms": 450,
        "version": "0.7.0",
        "trace_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
        "truncated": false
      },
      "next_actions": [
        {
          "command": "pxcli auth status",
          "description": "Verify authentication is working"
        }
      ]
    }""")

_AUTH_LOGOUT_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "auth logout",
      "result": {
        "credentials_existed": true
      },
      "meta": {
        "duration_ms": 15,
        "version": "0.7.0",
        "trace_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
        "truncated": false
      },
      "next_actions": [
        {
          "command": "pxcli auth login",
          "description": "Re-authenticate when needed"
        }
      ]
    }""")

_AUTH_STATUS_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "auth status",
      "result": {
        "authenticated": true,
        "token_path": "/Users/you/.config/perplexity-cli/token.json",
        "token_age_days": 3,
        "cookies_stored": 12,
        "verified": null
      },
      "meta": {
        "duration_ms": 20,
        "version": "0.7.0",
        "trace_id": "d4e5f6a7-b8c9-0123-defa-234567890123",
        "truncated": false
      },
      "next_actions": []
    }""")

_CONFIG_SET_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "config set",
      "result": {
        "key": "save_cookies",
        "value": true
      },
      "meta": {
        "duration_ms": 8,
        "version": "0.7.0",
        "trace_id": "e5f6a7b8-c9d0-1234-efab-345678901234",
        "truncated": false
      },
      "next_actions": [
        {
          "command": "pxcli config show",
          "description": "View updated configuration"
        }
      ]
    }""")

_CONFIG_SHOW_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "config show",
      "result": {
        "config_path": "/Users/you/.config/perplexity-cli/config.json",
        "save_cookies": true,
        "debug_mode": false,
        "env_overrides": []
      },
      "meta": {
        "duration_ms": 5,
        "version": "0.7.0",
        "trace_id": "f6a7b8c9-d0e1-2345-fabc-456789012345",
        "truncated": false
      },
      "next_actions": []
    }""")

_STYLE_SET_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "style set",
      "result": {
        "style": "be brief and concise"
      },
      "meta": {
        "duration_ms": 6,
        "version": "0.7.0",
        "trace_id": "a7b8c9d0-e1f2-3456-abcd-567890123456",
        "truncated": false
      },
      "next_actions": [
        {
          "command": "pxcli style show",
          "description": "Verify the configured style"
        }
      ]
    }""")

_STYLE_SHOW_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "style show",
      "result": {
        "style": "be brief and concise"
      },
      "meta": {
        "duration_ms": 3,
        "version": "0.7.0",
        "trace_id": "b8c9d0e1-f2a3-4567-bcde-678901234567",
        "truncated": false
      },
      "next_actions": []
    }""")

_STYLE_CLEAR_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "style clear",
      "result": {
        "had_style": true
      },
      "meta": {
        "duration_ms": 4,
        "version": "0.7.0",
        "trace_id": "c9d0e1f2-a3b4-5678-cdef-789012345678",
        "truncated": false
      },
      "next_actions": [
        {
          "command": "pxcli style set",
          "description": "Configure a new style"
        }
      ]
    }""")

_THREADS_EXPORT_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "threads export",
      "result": {
        "threads": [
          {
            "title": "How does quantum computing work?",
            "created_at": "2025-05-08T14:30:00+00:00",
            "url": "https://www.perplexity.ai/search/how-does-quantum-abc123"
          },
          {
            "title": "Best Python testing frameworks",
            "created_at": "2025-05-07T09:15:00+00:00",
            "url": "https://www.perplexity.ai/search/best-python-testing-def456"
          }
        ],
        "total": 2,
        "output_path": "threads-20250509-100000.csv",
        "date_range": {
          "from": null,
          "to": null
        }
      },
      "meta": {
        "duration_ms": 1250,
        "version": "0.7.0",
        "trace_id": "d0e1f2a3-b4c5-6789-defa-890123456789",
        "truncated": false
      },
      "next_actions": []
    }""")

_SKILL_SHOW_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "skill show",
      "result": {
        "skill_md": "# perplexity-cli Agent Skill\\n\\nUse perplexity-cli ..."
      },
      "meta": {
        "duration_ms": 2,
        "version": "0.7.0",
        "trace_id": "e1f2a3b4-c5d6-7890-efab-901234567890",
        "truncated": false
      },
      "next_actions": []
    }""")

_DOCTOR_SECURITY_JSON_EXAMPLE = textwrap.dedent("""\
    {
      "ok": true,
      "command": "doctor security",
      "result": {
        "storage_backend": "encrypted_file",
        "token_path": "/Users/you/.config/perplexity-cli/token.json",
        "token_permissions": "600",
        "cache_path": "/Users/you/.config/perplexity-cli/threads_cache.json",
        "cache_permissions": "600",
        "cookies_enabled": true
      },
      "meta": {
        "duration_ms": 10,
        "version": "0.7.0",
        "trace_id": "f2a3b4c5-d6e7-8901-fabc-012345678901",
        "truncated": false
      },
      "next_actions": [
        {
          "command": "pxcli auth status",
          "description": "Check authentication state"
        }
      ]
    }""")


# ---------------------------------------------------------------------------
# Auth group
# ---------------------------------------------------------------------------


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
def auth_login(ctx: click.Context, port: int | None, json_flag: bool, schema_flag: bool) -> None:
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
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_flag
    ctx.obj["schema"] = schema_flag
    from perplexity_cli.config.defaults import DEFAULT_CHROME_DEBUG_PORT
    from perplexity_cli.runners import run_auth_command

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
def auth_logout(ctx: click.Context, json_flag: bool, schema_flag: bool) -> None:
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
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_flag
    ctx.obj["schema"] = schema_flag
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
def auth_status(ctx: click.Context, verify: bool, json_flag: bool, schema_flag: bool) -> None:
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
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_flag
    ctx.obj["schema"] = schema_flag
    from perplexity_cli.runners import run_status_command

    run_status_command(verify)


auth_group.add_command(auth_login)
auth_group.add_command(auth_logout)
auth_group.add_command(auth_status)


# ---------------------------------------------------------------------------
# Config group
# ---------------------------------------------------------------------------


@click.group(
    "config",
    help=(
        "Configuration commands.\n\n"
        "Read and write persistent feature toggles that control CLI behaviour.  "
        "Configuration is stored in a JSON file at the path determined by "
        "(in order of precedence): PERPLEXITY_CONFIG_DIR, XDG_CONFIG_HOME, "
        "or ~/.config/perplexity-cli/config.json.\n\n"
        "Available configuration keys:\n\n"
        "  save_cookies  - When true, browser cookies captured during 'auth login'\n"
        "                  are stored alongside the token and reused for API\n"
        "                  requests.  Improves reliability of some operations.\n\n"
        "  debug_mode    - When true, enables DEBUG-level logging for all commands\n"
        "                  without needing the --debug flag.\n\n"
        "Subcommands:\n\n"
        "  set   - Write a configuration value\n\n"
        "  show  - Display all current configuration values and their sources\n\n"
        "Quick start:\n\n"
        "  pxcli config show                  # View current settings\n\n"
        "  pxcli config set save_cookies true  # Enable cookie storage\n\n"
        "  pxcli config set debug_mode false   # Disable debug logging"
    ),
)
@click.pass_context
def config_group(ctx: click.Context) -> None:
    """Configuration commands."""
    _ensure_ctx_obj(ctx)


@click.command(name="set")
@click.argument("key", type=click.Choice(["save_cookies", "debug_mode"]))
@click.argument("value", type=click.Choice(["true", "false"]))
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
def config_set(
    ctx: click.Context, key: str, value: str, json_flag: bool, schema_flag: bool
) -> None:
    """Set a configuration option.

    Writes a boolean feature toggle to the persistent configuration file.
    The value takes effect immediately for all subsequent CLI invocations.

    \b
    Arguments:
      KEY    Configuration key to set.  Must be one of:
               save_cookies - Control whether browser cookies are stored
                              and reused for API requests.
               debug_mode   - Control whether DEBUG-level logging is enabled
                              by default (equivalent to --debug flag).
      VALUE  The boolean value to set.  Must be 'true' or 'false'.

    The configuration file is created automatically if it does not exist.
    The file path is determined by PERPLEXITY_CONFIG_DIR, XDG_CONFIG_HOME,
    or defaults to ~/.config/perplexity-cli/config.json.

    \b
    Examples:
        pxcli config set save_cookies true
        pxcli config set save_cookies false
        pxcli config set debug_mode true
        pxcli config set debug_mode false
        pxcli config set save_cookies true --json
        pxcli config set save_cookies true --json | jq '.result'

    \b
    Example Output (human):
        [OK] save_cookies set to true
    """
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_flag
    ctx.obj["schema"] = schema_flag
    from perplexity_cli.runners import run_set_config_command

    run_set_config_command(key, value)


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
def config_show(ctx: click.Context, json_flag: bool, schema_flag: bool) -> None:
    """Display current configuration.

    Reads the persistent configuration file and displays all feature toggle
    settings along with their current values.  Also reports the configuration
    file path and any environment variable overrides that are in effect.

    \b
    Result fields:
      config_path    - Absolute path to the configuration file
      save_cookies   - Whether browser cookie storage is enabled (boolean)
      debug_mode     - Whether debug logging is enabled by default (boolean)
      env_overrides  - List of config keys overridden by environment variables

    \b
    Examples:
        pxcli config show
        pxcli config show --json
        pxcli config show --json | jq '.result.save_cookies'

    \b
    Example Output (human):
        Configuration (/Users/you/.config/perplexity-cli/config.json):
          save_cookies: true
          debug_mode:   false
    """
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_flag
    ctx.obj["schema"] = schema_flag
    from perplexity_cli.runners import run_show_config_command

    run_show_config_command()


config_group.add_command(config_set)
config_group.add_command(config_show)


# ---------------------------------------------------------------------------
# Style group
# ---------------------------------------------------------------------------


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
def style_set(ctx: click.Context, style: str, json_flag: bool, schema_flag: bool) -> None:
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
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_flag
    ctx.obj["schema"] = schema_flag
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
def style_show(ctx: click.Context, json_flag: bool, schema_flag: bool) -> None:
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
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_flag
    ctx.obj["schema"] = schema_flag
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
def style_clear(ctx: click.Context, json_flag: bool, schema_flag: bool) -> None:
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
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_flag
    ctx.obj["schema"] = schema_flag
    from perplexity_cli.runners import run_clear_style_command

    run_clear_style_command()


style_group.add_command(style_set)
style_group.add_command(style_show)
style_group.add_command(style_clear)


# ---------------------------------------------------------------------------
# Threads group
# ---------------------------------------------------------------------------


@click.group(
    "threads",
    help=(
        "Thread management commands.\n\n"
        "Manage your Perplexity.ai conversation threads.  Currently supports "
        "exporting your full thread library (titles, dates, URLs) to CSV or JSON "
        "format.\n\n"
        "Requires authentication — run 'pxcli auth login' first.\n\n"
        "Subcommands:\n\n"
        "  export  - Export thread library as CSV or JSON\n\n"
        "Quick start:\n\n"
        "  pxcli threads export\n\n"
        "  pxcli threads export --from-date 2025-01-01\n\n"
        "  pxcli threads export --json"
    ),
)
@click.pass_context
def threads_group(ctx: click.Context) -> None:
    """Thread management commands."""
    _ensure_ctx_obj(ctx)


@click.command(name="export")
@click.option(
    "--from-date",
    type=str,
    default=None,
    help=(
        "Start date for filtering exported threads (inclusive).  Only threads "
        "created on or after this date are included.  Format: ISO 8601 date "
        "(YYYY-MM-DD).  Example: --from-date 2025-01-01.  If omitted, no lower "
        "bound is applied."
    ),
)
@click.option(
    "--to-date",
    type=str,
    default=None,
    help=(
        "End date for filtering exported threads (inclusive).  Only threads "
        "created on or before this date are included.  Format: ISO 8601 date "
        "(YYYY-MM-DD).  Example: --to-date 2025-12-31.  If omitted, no upper "
        "bound is applied."
    ),
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help=(
        "Output CSV file path.  If omitted, defaults to "
        "threads-YYYYMMDD-HHMMSS.csv in the current directory.  The file is "
        "created with UTF-8 encoding and includes a header row.  "
        "Example: --output my-threads.csv"
    ),
)
@click.option(
    "--force-refresh",
    is_flag=True,
    default=False,
    help=(
        "Ignore the local thread cache and fetch fresh data from the "
        "Perplexity.ai API.  The cache is updated with the newly fetched data "
        "after a successful export.  Use this when you know there are new "
        "threads that are not yet reflected in the cache."
    ),
)
@click.option(
    "--clear-cache",
    is_flag=True,
    default=False,
    help=(
        "Delete the local thread cache file before performing the export.  "
        "This forces a full re-fetch from the API.  The cache file is located "
        "at ~/.config/perplexity-cli/threads_cache.json.  Use this to recover "
        "from a corrupted cache."
    ),
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    help=(
        "Emit output as a structured JSON envelope to stdout instead of "
        "writing a CSV file.  The envelope contains the full thread list in "
        "the result.threads array.  Intended for programmatic consumption."
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
def threads_export(
    ctx: click.Context,
    from_date: str | None,
    to_date: str | None,
    output: Path | None,
    force_refresh: bool,
    clear_cache: bool,
    json_flag: bool,
    schema_flag: bool,
) -> None:
    """Export thread library with titles and creation dates.

    Extracts all conversation threads from your Perplexity.ai library using
    your stored authentication token.  No browser is required after the
    initial 'pxcli auth login' setup.

    By default, output is written as a CSV file with columns: title,
    created_at (ISO 8601 with timezone), and url.  Use --json for structured
    JSON output instead.

    \b
    Features:
      - Exports thread title, creation timestamp, and URL
      - Local encrypted cache avoids redundant API calls
      - Cache is incrementally updated on each export
      - Date filtering via --from-date and --to-date
      - Reuses saved browser cookies when available

    \b
    Result fields (--json):
      threads      - Array of thread objects {title, created_at, url}
      total        - Total number of exported threads (integer)
      output_path  - Path to the CSV file written (or "stdout" for --json)
      date_range   - Applied date filter {from, to} (null values if unfiltered)

    \b
    Examples:
        pxcli threads export
        pxcli threads export --from-date 2025-01-01
        pxcli threads export --from-date 2025-01-01 --to-date 2025-06-30
        pxcli threads export --output my-threads.csv
        pxcli threads export -o my-threads.csv
        pxcli threads export --force-refresh
        pxcli threads export --clear-cache
        pxcli threads export --json
        pxcli threads export --json | jq '.result.threads[] | .title'
        pxcli threads export --json --from-date 2025-01-01 | jq '.result.total'

    \b
    Example Output (human):
        Fetching threads...
        Exported 47 threads to threads-20250509-143022.csv

    \b
    CSV format:
        title,created_at,url
        "How does quantum computing work?",2025-05-08T14:30:00+00:00,https://...
        "Best Python testing frameworks",2025-05-07T09:15:00+00:00,https://...
    """
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_flag
    ctx.obj["schema"] = schema_flag
    from perplexity_cli.runners import run_export_threads_command

    run_export_threads_command(
        ctx.obj,
        from_date,
        to_date,
        output,
        force_refresh,
        clear_cache,
    )


threads_group.add_command(threads_export)


# ---------------------------------------------------------------------------
# Skill group
# ---------------------------------------------------------------------------


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
        "is returned in result.skill_md as a string.  Intended for "
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
def skill_show(ctx: click.Context, json_flag: bool, schema_flag: bool) -> None:
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
      skill_md  - The full SKILL.md content as a string.

    \b
    Examples:
        pxcli skill show
        pxcli skill show | less
        pxcli skill show > skill-definition.md
        pxcli skill show --json
        pxcli skill show --json | jq -r '.result.skill_md'

    \b
    Example Output (human, truncated):
        # perplexity-cli Agent Skill
        Use perplexity-cli as an alternative to web search ...
    """
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_flag
    ctx.obj["schema"] = schema_flag
    from perplexity_cli.runners import run_show_skill_command

    run_show_skill_command()


skill_group.add_command(skill_show)


# ---------------------------------------------------------------------------
# Doctor group (existing - kept as-is)
# ---------------------------------------------------------------------------


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
def doctor_security(ctx: click.Context, json_flag: bool, schema_flag: bool) -> None:
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
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_flag
    ctx.obj["schema"] = schema_flag
    from perplexity_cli.runners import run_doctor_security_command

    run_doctor_security_command()


doctor.add_command(doctor_security)


# ---------------------------------------------------------------------------
# Root-level commands
# ---------------------------------------------------------------------------


@click.command()
@click.argument("query_text", metavar="QUERY")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["plain", "markdown", "rich", "json"]),
    default=None,
    help=(
        "Output format for the response.  Defaults to 'rich' when stdout is a "
        "terminal, or 'plain' when piped.  Available formats:\n\n"
        "  plain    - Plain text with underlined section headers.  Clean output "
        "suitable for piping to other commands or saving to .txt files.\n\n"
        "  markdown - GitHub-flavoured Markdown with proper heading levels, "
        "fenced code blocks, and reference links.  Suitable for .md files.\n\n"
        "  rich     - Colourful terminal output with syntax highlighting, "
        "tables, and styled headers.  Best for interactive use.\n\n"
        "  json     - Legacy JSON format (prefer --json flag for the structured "
        "envelope format).  Returns {answer, references} as JSON."
    ),
)
@click.option(
    "--strip-references",
    "-S",
    is_flag=True,
    help=(
        "Remove all inline citation numbers [1], [2], etc. and the references "
        "section from the response.  Useful when you want clean prose without "
        "source attributions, e.g. for embedding in documents or feeding to "
        "other tools."
    ),
)
@click.option(
    "--stream/--no-stream",
    "-s/",
    default=False,
    help=(
        "Enable real-time streaming of the response.  With --stream, text is "
        "printed incrementally as it arrives from the API rather than waiting "
        "for the complete response.  When combined with --json, produces NDJSON "
        "(newline-delimited JSON) output with one event per line: start, chunk, "
        "and result events.  Default: --no-stream (batch mode)."
    ),
)
@click.option(
    "--attach",
    "-a",
    "attachments_str",
    multiple=True,
    help=(
        "Attach file(s) to the query for analysis.  Requires authentication "
        "(run 'pxcli auth login' first).  Supports multiple input methods:\n\n"
        "  Single file:       --attach report.pdf\n\n"
        "  Comma-separated:   --attach 'file1.txt,file2.txt'\n\n"
        "  Directory:         --attach ./docs  (recursive, all files)\n\n"
        "  Repeated flag:     -a file1.txt -a file2.txt\n\n"
        "Files are uploaded to Perplexity.ai and included as context for the "
        "query.  Supported file types include text, PDF, images, and code files."
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
        "failure.  The result object includes 'answer' (string) and 'references' "
        "(array).  Intended for programmatic consumption by scripts and agents.  "
        "When combined with --stream, produces NDJSON output."
    ),
)
@click.option(
    "--schema",
    "schema_flag",
    is_flag=True,
    help=(
        "Embed the full JSON Schema definition as a $schema key in the JSON "
        "envelope output.  Only effective when --json is also specified; silently "
        "ignored otherwise.  For NDJSON streaming, the schema is included only "
        "in the final result event."
    ),
)
@click.option(
    "--timeout",
    "-t",
    type=int,
    default=None,
    help=(
        "Request timeout in seconds.  If the API does not respond within this "
        "duration, the request is aborted and an error is returned (exit code 6). "
        "Default: 60 seconds for standard queries.  Set a higher value for "
        "complex queries that may take longer to process.  Example: --timeout 120"
    ),
)
@click.option(
    "--model",
    "-m",
    "model_preference",
    type=str,
    default=None,
    help=(
        "Model to use for this query.  Accepts a model identifier string "
        "as returned by 'pxcli models list'.  When not specified, the "
        "default model 'Best' (pplx_pro) is used, which auto-selects the "
        "most appropriate model for the query.\n\n"
        "Examples:\n\n"
        "  --model gpt54           GPT-5.4\n\n"
        "  --model claude46sonnet  Claude Sonnet 4.6\n\n"
        "  -m experimental         Sonar 2\n\n"
        "Run 'pxcli models list' to see available models for your "
        "subscription tier."
    ),
)
@click.option(
    "--request-param",
    "request_param_overrides",
    type=str,
    multiple=True,
    help=(
        "Experimental: inject an extra key=value pair into the outbound "
        "request params.  Repeat for multiple fields.  Intended for private "
        "API investigation only.  Example: --request-param workflow_key=deep_research"
    ),
)
@click.pass_context
def query(
    ctx: click.Context,
    query_text: str,
    output_format: str,
    strip_references: bool,
    stream: bool,
    attachments_str: tuple[str, ...],
    json_flag: bool,
    schema_flag: bool,
    timeout: int | None,
    model_preference: str | None,
    request_param_overrides: tuple[str, ...],
) -> None:
    """Submit a query to Perplexity.ai and get an answer.

    Sends a natural-language question to Perplexity.ai and returns the
    answer along with source references.  Works with or without
    authentication; authentication is only required when using file
    attachments (--attach).

    The response is printed to stdout, making it straightforward to pipe to
    other commands, redirect to files, or parse programmatically.  By
    default, responses are fetched in batch mode (the complete answer is
    displayed after the API finishes).  Use --stream for real-time
    incremental output.

    \b
    OUTPUT FORMATS:
      plain    - Plain text with underlined headers (good for scripts)
      markdown - GitHub-flavoured Markdown with proper structure
      rich     - Colourful terminal output with tables (default for TTY)
      json     - Legacy JSON format; prefer --json for the envelope format

    \b
    JSON ENVELOPE (--json):
      The --json flag produces a structured envelope:
        {ok, command, result, meta, next_actions}
      where result contains:
        {answer: string, references: [{index, title, url, snippet}, ...]}

    \b
    NDJSON STREAMING (--json --stream):
      When --json and --stream are combined, output is newline-delimited
      JSON (NDJSON).  Each line is a typed event:
        start   - Emitted when the query begins
        chunk   - Emitted for each piece of streamed text
        result  - Final line containing the complete envelope

    \b
    FILE ATTACHMENTS (--attach):
      Attach files for Perplexity.ai to analyse alongside your query.
      Requires authentication.  Supports:
        --attach file.txt             Single file
        --attach file1.txt,file2.txt  Comma-separated files
        --attach ./directory          All files recursively
        -a file1.txt -a file2.txt     Repeated flags

    \b
    Examples:
        pxcli query "What is Python?"
        pxcli query "What is the capital of France?" > answer.txt
        pxcli query --format plain "What is Python?"
        pxcli query --format markdown "Explain Docker" > docker.md
        pxcli query --strip-references "What is Python?"
        pxcli query -f plain -S "What is Python?"
        pxcli query --stream "What is Python?"
        pxcli query -s "What is Python?"
        pxcli query --json "What is Python?"
        pxcli query --json "What is Python?" | jq -r '.result.answer'
        pxcli query --json --stream "What is Python?"
        pxcli query --json --schema "What is Python?"
        pxcli query --attach README.md "What is this project?"
        pxcli query --attach config.json,data.txt "Analyse these files"
        pxcli query --attach ./docs "Summarise all documentation"
        pxcli query --timeout 120 "Complex research question"
        pxcli query --model gpt54 "What is Python?"
        pxcli query -m claude46sonnet "Explain Docker"

    \b
    Example Output (rich, default):
        Python
        ======
        Python is a high-level, general-purpose programming language
        created by Guido van Rossum and first released in 1991 [1].
        ...

    References:
        ----------
        [1] Python (programming language) - Wikipedia
            https://en.wikipedia.org/wiki/Python_(programming_language)

    \b
    JSON format tip: Use jq -r to render newlines properly:
        pxcli query --json "Question" | jq -r '.result.answer'
    """
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_flag
    ctx.obj["schema"] = schema_flag
    ctx.obj["timeout"] = timeout
    from perplexity_cli.query_runner import run_query_command

    run_query_command(
        ctx.obj,
        query_text,
        output_format,
        strip_references,
        stream,
        attachments_str,
        model_preference=model_preference,
        request_param_overrides=request_param_overrides,
    )


# ---------------------------------------------------------------------------
# Models group
# ---------------------------------------------------------------------------


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
def models_list(ctx: click.Context, json_flag: bool, schema_flag: bool) -> None:
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
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_flag
    ctx.obj["schema"] = schema_flag
    from perplexity_cli.runners.models import run_models_list_command

    run_models_list_command(ctx.obj)


models_group.add_command(models_list)


# ---------------------------------------------------------------------------
# Completion group
# ---------------------------------------------------------------------------


@click.group(
    "completion",
    help=(
        "Generate shell completion scripts.\n\n"
        "Outputs a shell-specific completion script that enables tab-completion "
        "for pxcli commands, subcommands, and options.  Supports Bash, Zsh, and "
        "Fish shells.\n\n"
        "The generated script should be evaluated by your shell at startup.  "
        "See the subcommand help for shell-specific installation instructions.\n\n"
        "Subcommands:\n\n"
        "  bash  - Generate Bash completion script\n\n"
        "  zsh   - Generate Zsh completion script\n\n"
        "  fish  - Generate Fish completion script\n\n"
        "Quick start:\n\n"
        '  eval "$(pxcli completion bash)"   # Bash\n\n'
        '  eval "$(pxcli completion zsh)"    # Zsh\n\n'
        "  pxcli completion fish | source    # Fish"
    ),
)
@click.pass_context
def completion_group(ctx: click.Context) -> None:
    """Generate shell completion scripts."""
    _ensure_ctx_obj(ctx)


@click.command(name="bash")
def completion_bash() -> None:
    """Generate Bash completion script.

    Outputs a Bash completion function that provides tab-completion for all
    pxcli commands, subcommands, options, and arguments.  The script uses
    the COMP_WORDS and COMP_CWORD environment variables to communicate with
    Click's built-in completion machinery.

    \b
    Installation:
      Add the following line to your ~/.bashrc (or ~/.bash_profile on macOS):
        eval "$(pxcli completion bash)"
      Then restart your shell or run:
        source ~/.bashrc

    \b
    Examples:
        pxcli completion bash                     # Print to stdout
        pxcli completion bash >> ~/.bashrc        # Append to bashrc
        pxcli completion bash > /etc/bash_completion.d/pxcli  # System-wide

    \b
    After installation, tab-completion works for:
        pxcli <TAB>              # Lists commands
        pxcli auth <TAB>         # Lists auth subcommands
        pxcli query --<TAB>      # Lists query options
    """
    click.echo(_BASH_COMPLETION)


@click.command(name="zsh")
def completion_zsh() -> None:
    """Generate Zsh completion script.

    Outputs a Zsh completion function (_pxcli) that provides tab-completion
    for all pxcli commands, subcommands, options, and arguments.  The script
    registers itself with Zsh's compdef system.

    \b
    Installation:
      Add the following line to your ~/.zshrc:
        eval "$(pxcli completion zsh)"
      Then restart your shell or run:
        source ~/.zshrc

    \b
    Alternative (site-functions):
      pxcli completion zsh > ~/.zsh/completions/_pxcli
      # Ensure ~/.zsh/completions is in your fpath

    \b
    Examples:
        pxcli completion zsh                       # Print to stdout
        pxcli completion zsh >> ~/.zshrc            # Append to zshrc
        pxcli completion zsh > ~/.zsh/completions/_pxcli  # Site function

    \b
    After installation, tab-completion works for:
        pxcli <TAB>              # Lists commands
        pxcli auth <TAB>         # Lists auth subcommands
        pxcli query --<TAB>      # Lists query options
    """
    click.echo(_ZSH_COMPLETION)


@click.command(name="fish")
def completion_fish() -> None:
    """Generate Fish completion script.

    Outputs a Fish shell completion function that provides tab-completion
    for all pxcli commands, subcommands, options, and arguments.

    \b
    Installation:
      Run the following command (persists across sessions):
        pxcli completion fish > ~/.config/fish/completions/pxcli.fish

    \b
    Temporary (current session only):
        pxcli completion fish | source

    \b
    Examples:
        pxcli completion fish                                     # Print to stdout
        pxcli completion fish > ~/.config/fish/completions/pxcli.fish  # Persist
        pxcli completion fish | source                            # Current session

    \b
    After installation, tab-completion works for:
        pxcli <TAB>              # Lists commands
        pxcli auth <TAB>         # Lists auth subcommands
        pxcli query --<TAB>      # Lists query options
    """
    click.echo(_FISH_COMPLETION)


completion_group.add_command(completion_bash)
completion_group.add_command(completion_zsh)
completion_group.add_command(completion_fish)


# ---------------------------------------------------------------------------
# Schema command
# ---------------------------------------------------------------------------


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
        "commands": _build_command_schemas(),
    }
    click.echo(_json.dumps(schema, indent=2))


# ---------------------------------------------------------------------------
# Apply enhanced help sections
# ---------------------------------------------------------------------------

# query — full treatment: example output, NDJSON, schema, exit codes, see also, env vars
_add_help_sections(
    query,
    json_example=_QUERY_JSON_EXAMPLE,
    ndjson_example=_QUERY_NDJSON_EXAMPLE,
    json_schema=True,
    exit_codes=True,
    see_also=[_AUTH_LOGIN_HELP_REF, "pxcli config show", _STYLE_SET_HELP_REF, "pxcli schema"],
    env_vars=["PERPLEXITY_BASE_URL", "NO_COLOR", "XDG_CONFIG_HOME", "PERPLEXITY_CONFIG_DIR"],
)

# auth login
_add_help_sections(
    auth_login,
    json_example=_AUTH_LOGIN_JSON_EXAMPLE,
    json_schema=True,
    exit_codes=True,
    see_also=[_AUTH_STATUS_HELP_REF, "pxcli auth logout"],
)

# auth logout
_add_help_sections(
    auth_logout,
    json_example=_AUTH_LOGOUT_JSON_EXAMPLE,
    json_schema=True,
    exit_codes=True,
    see_also=[_AUTH_LOGIN_HELP_REF, _AUTH_STATUS_HELP_REF],
)

# auth status
_add_help_sections(
    auth_status,
    json_example=_AUTH_STATUS_JSON_EXAMPLE,
    json_schema=True,
    exit_codes=True,
    see_also=[_AUTH_LOGIN_HELP_REF, "pxcli auth logout"],
)

# config set
_add_help_sections(
    config_set,
    json_example=_CONFIG_SET_JSON_EXAMPLE,
    json_schema=True,
    exit_codes=True,
    see_also=["pxcli config show"],
    env_vars=["PERPLEXITY_CONFIG_DIR", "XDG_CONFIG_HOME"],
)

# config show
_add_help_sections(
    config_show,
    json_example=_CONFIG_SHOW_JSON_EXAMPLE,
    json_schema=True,
    exit_codes=True,
    see_also=["pxcli config set"],
    env_vars=["PERPLEXITY_CONFIG_DIR", "XDG_CONFIG_HOME"],
)

# style set
_add_help_sections(
    style_set,
    json_example=_STYLE_SET_JSON_EXAMPLE,
    json_schema=True,
    exit_codes=True,
    see_also=["pxcli style show", "pxcli style clear"],
)

# style show
_add_help_sections(
    style_show,
    json_example=_STYLE_SHOW_JSON_EXAMPLE,
    json_schema=True,
    exit_codes=True,
    see_also=[_STYLE_SET_HELP_REF, "pxcli style clear"],
)

# style clear
_add_help_sections(
    style_clear,
    json_example=_STYLE_CLEAR_JSON_EXAMPLE,
    json_schema=True,
    exit_codes=True,
    see_also=[_STYLE_SET_HELP_REF],
)

# threads export
_add_help_sections(
    threads_export,
    json_example=_THREADS_EXPORT_JSON_EXAMPLE,
    json_schema=True,
    exit_codes=True,
    see_also=[_AUTH_LOGIN_HELP_REF],
    env_vars=["PERPLEXITY_CONFIG_DIR", "XDG_CONFIG_HOME"],
)

# skill show
_add_help_sections(
    skill_show,
    json_example=_SKILL_SHOW_JSON_EXAMPLE,
    json_schema=True,
    exit_codes=True,
    see_also=["pxcli query", "pxcli schema"],
)

# doctor security
_add_help_sections(
    doctor_security,
    json_example=_DOCTOR_SECURITY_JSON_EXAMPLE,
    json_schema=True,
    exit_codes=True,
    see_also=["pxcli auth status", "pxcli auth login"],
)

# schema (no --json flag, but still gets exit codes)
_add_help_sections(
    schema_cmd,
    exit_codes=True,
    see_also=["pxcli query --json", "pxcli query --json --schema"],
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_commands(main_group: click.Group) -> None:
    """Attach all command definitions to the root Click group."""
    for cmd in (
        auth_group,
        config_group,
        style_group,
        threads_group,
        skill_group,
        models_group,
        doctor,
        query,
        completion_group,
        schema_cmd,
    ):
        main_group.add_command(cmd)

    # Add exit codes section to the main group help
    _add_help_sections(main_group, exit_codes=True)
