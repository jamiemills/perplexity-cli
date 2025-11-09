"""Command-line interface for Perplexity CLI."""

import sys

import click
import httpx

from perplexity_cli import __version__
from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.auth.oauth_handler import authenticate_sync
from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.formatting import get_formatter, list_formatters
from perplexity_cli.utils.config import get_perplexity_base_url
from perplexity_cli.utils.style_manager import StyleManager


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """Perplexity CLI - Query Perplexity.ai from the command line."""
    pass


@main.command()
@click.option(
    "--port",
    default=9222,
    help="Chrome remote debugging port (default: 9222)",
)
def auth(port: int) -> None:
    """Authenticate with Perplexity.ai.

    Opens Chrome browser to Perplexity.ai and extracts authentication token.
    Requires Chrome to be running with --remote-debugging-port=<port>.

    Example:
        perplexity-cli auth
        perplexity-cli auth --port 9222
    """
    base_url = get_perplexity_base_url()
    click.echo("Authenticating with Perplexity.ai...")
    click.echo(f"\nMake sure Chrome is running with --remote-debugging-port={port}")
    click.echo(f"Navigate to {base_url} and log in if needed.\n")

    try:
        # Authenticate and extract token
        token = authenticate_sync(port=port)

        # Save token
        tm = TokenManager()
        tm.save_token(token)

        click.echo("✓ Authentication successful!")
        click.echo(f"✓ Token saved to: {tm.token_path}")
        click.echo('\nYou can now use: perplexity-cli query "<your question>"')

    except RuntimeError as e:
        click.echo(f"✗ Authentication failed: {e}", err=True)
        click.echo("\nTroubleshooting:", err=True)
        click.echo(
            f"  1. Start Chrome with: --remote-debugging-port={port}",
            err=True,
        )
        click.echo(
            f"  2. Navigate to {base_url} in Chrome",
            err=True,
        )
        click.echo("  3. Log in with your Google account", err=True)
        click.echo("  4. Run this command again", err=True)
        sys.exit(1)

    except Exception as e:
        click.echo(f"✗ Unexpected error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.argument("query_text", metavar="QUERY")
@click.option(
    "--format",
    "-f",
    type=click.Choice(["plain", "markdown", "rich"]),
    default=None,
    help="Output format: plain (text), markdown (GitHub-flavoured), or rich (terminal with colours and tables). Defaults to 'rich'.",
)
@click.option(
    "--strip-references",
    is_flag=True,
    help="Remove all references section and inline citation numbers [1], [2], etc. from the answer.",
)
def query(query_text: str, format: str, strip_references: bool) -> None:
    """Submit a query to Perplexity.ai and get an answer.

    The answer is printed to stdout, making it easy to pipe to other commands.

    Output formats:
        plain   - Plain text with underlined headers (good for scripts)
        markdown - GitHub-flavoured Markdown with proper structure
        rich    - Colourful terminal output with tables (default)

    Use --strip-references to remove all citations [1], [2], etc. and the
    references section from the output.

    Examples:
        perplexity-cli query "What is Python?"
        perplexity-cli query "What is the capital of France?" > answer.txt
        perplexity-cli query --format plain "What is Python?"
        perplexity-cli query --format markdown "What is Python?" > answer.md
        perplexity-cli query --strip-references "What is Python?"
        perplexity-cli query -f plain --strip-references "What is Python?"
    """
    # Load token
    tm = TokenManager()
    token = tm.load_token()

    if not token:
        click.echo("✗ Not authenticated.", err=True)
        click.echo(
            "\nPlease authenticate first with: perplexity-cli auth",
            err=True,
        )
        sys.exit(1)

    try:
        # Determine output format
        output_format = format or "rich"

        # Get formatter instance
        try:
            formatter = get_formatter(output_format)
        except ValueError as e:
            click.echo(f"✗ {e}", err=True)
            available = ", ".join(list_formatters())
            click.echo(f"Available formats: {available}", err=True)
            sys.exit(1)

        # Load style if configured
        sm = StyleManager()
        style = sm.load_style()

        # Append style to query if one is configured
        final_query = query_text
        if style:
            final_query = f"{query_text}\n\n{style}"

        # Create API client
        api = PerplexityAPI(token=token)

        # Submit query and get answer
        answer_obj = api.get_complete_answer(final_query)

        # Format and output the answer
        if output_format == "rich":
            # Use Rich formatter's direct rendering for proper styling
            formatter.render_complete(answer_obj, strip_references=strip_references)
        else:
            # For plain and markdown, use click.echo
            formatted_output = formatter.format_complete(
                answer_obj, strip_references=strip_references
            )
            click.echo(formatted_output)

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status == 401:
            click.echo("✗ Authentication failed. Token may be expired.", err=True)
            click.echo("\nPlease re-authenticate with: perplexity-cli auth", err=True)
        elif status == 403:
            click.echo("✗ Access forbidden. Check your permissions.", err=True)
        elif status == 429:
            click.echo("✗ Rate limit exceeded. Please wait and try again.", err=True)
        else:
            click.echo(f"✗ HTTP error {status}: {e}", err=True)
        sys.exit(1)

    except httpx.RequestError as e:
        click.echo(f"✗ Network error: {e}", err=True)
        click.echo("\nPlease check your internet connection.", err=True)
        sys.exit(1)

    except ValueError as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)

    except Exception as e:
        click.echo(f"✗ Unexpected error: {e}", err=True)
        sys.exit(1)


@main.command()
def logout() -> None:
    """Log out and remove stored credentials.

    This deletes the stored authentication token. You will need to
    re-authenticate with 'perplexity-cli auth' before making queries.

    Example:
        perplexity-cli logout
    """
    tm = TokenManager()

    if not tm.token_exists():
        click.echo("No stored credentials found.")
        return

    try:
        tm.clear_token()
        click.echo("✓ Logged out successfully.")
        click.echo("✓ Stored credentials removed.")

    except Exception as e:
        click.echo(f"✗ Error during logout: {e}", err=True)
        sys.exit(1)


@main.command()
@click.argument("style", required=True)
def configure(style: str) -> None:
    """Configure a style prompt to apply to all queries.

    Sets a custom style/prompt that will be automatically appended to all
    subsequent queries. This allows you to standardise response formatting
    without repeating instructions.

    The style is stored in ~/.config/perplexity-cli/style.json and persists
    across CLI sessions.

    Example:
        perplexity-cli configure "be brief and concise"
        perplexity-cli configure "provide super brief answers in minimal words"
    """
    sm = StyleManager()

    try:
        sm.save_style(style)
        click.echo("✓ Style configured successfully.")
        click.echo("✓ Style will be applied to all future queries.")
        click.echo("\nStyle preview:")
        click.echo(f"  {style}")
    except ValueError as e:
        click.echo(f"✗ Invalid style: {e}", err=True)
        sys.exit(1)
    except OSError as e:
        click.echo(f"✗ Failed to save style: {e}", err=True)
        sys.exit(1)


@main.command()
def view_style() -> None:
    """View currently configured style.

    Displays the style prompt that is being applied to queries, or a message
    if no style is configured.

    Example:
        perplexity-cli view-style
    """
    sm = StyleManager()

    try:
        style = sm.load_style()

        if style is None:
            click.echo("No style configured.")
            click.echo("\nSet a style with:")
            click.echo("  perplexity-cli configure <STYLE>")
        else:
            click.echo("Current style:")
            click.echo("-" * 50)
            click.echo(style)
            click.echo("-" * 50)
    except OSError as e:
        click.echo(f"✗ Error reading style: {e}", err=True)
        sys.exit(1)


@main.command()
def clear_style() -> None:
    """Clear configured style.

    Removes the style configuration. Queries will no longer have any style
    prompt appended.

    Example:
        perplexity-cli clear-style
    """
    sm = StyleManager()

    try:
        style = sm.load_style()

        if style is None:
            click.echo("No style is currently configured.")
            return

        sm.clear_style()
        click.echo("✓ Style cleared successfully.")
        click.echo("✓ Queries will no longer include a style prompt.")

    except OSError as e:
        click.echo(f"✗ Error clearing style: {e}", err=True)
        sys.exit(1)


@main.command()
def status() -> None:
    """Show current authentication status.

    Displays whether you are authenticated and where the token is stored.

    Example:
        perplexity-cli status
    """
    tm = TokenManager()

    click.echo("Perplexity CLI Status")
    click.echo("=" * 40)

    if tm.token_exists():
        try:
            token = tm.load_token()
            if token:
                click.echo("Status: ✓ Authenticated")
                click.echo(f"Token file: {tm.token_path}")
                click.echo(f"Token length: {len(token)} characters")

                # Try to verify token works
                try:
                    api = PerplexityAPI(token=token)
                    # Make a simple request to verify token
                    import httpx

                    base_url = get_perplexity_base_url()
                    headers = api.client.get_headers()
                    response = httpx.get(
                        f"{base_url}/api/user",
                        headers=headers,
                        timeout=5,
                    )
                    if response.status_code == 200:
                        data = response.json()
                        click.echo(f"User: {data.get('username', 'Unknown')}")
                        click.echo(f"Email: {data.get('email', 'Unknown')}")
                        click.echo("\n✓ Token is valid and working")
                    else:
                        click.echo("\n⚠ Token may be expired (unable to verify)")
                except Exception:
                    click.echo("\n⚠ Token verification failed")

            else:
                click.echo("Status: ✗ Not authenticated")
        except RuntimeError as e:
            click.echo("Status: ⚠ Token file has insecure permissions")
            click.echo(f"Error: {e}")
            click.echo(f"\nFix with: chmod 0600 {tm.token_path}")
    else:
        click.echo("Status: ✗ Not authenticated")
        click.echo("\nAuthenticate with: perplexity-cli auth")


if __name__ == "__main__":
    main()
