"""Command-line interface for Perplexity CLI."""

import os
import sys

import click
import httpx

from perplexity_cli import __version__
from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.auth.oauth_handler import authenticate_sync
from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.formatting import get_formatter, list_formatters


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
    click.echo("Authenticating with Perplexity.ai...")
    click.echo(f"\nMake sure Chrome is running with --remote-debugging-port={port}")
    click.echo("Navigate to https://www.perplexity.ai and log in if needed.\n")

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
            "  2. Navigate to https://www.perplexity.ai in Chrome",
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
def query(query_text: str, format: str) -> None:
    """Submit a query to Perplexity.ai and get an answer.

    The answer is printed to stdout, making it easy to pipe to other commands.

    Example:
        perplexity-cli query "What is Python?"
        perplexity-cli query "What is the capital of France?"
        perplexity-cli query "Explain quantum computing" > answer.txt
        perplexity-cli query --format plain "What is Python?"
        perplexity-cli query --format markdown "What is Python?"
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
        output_format = format or os.environ.get("PERPLEXITY_FORMAT", "rich")

        # Get formatter instance
        try:
            formatter = get_formatter(output_format)
        except ValueError as e:
            click.echo(f"✗ {e}", err=True)
            available = ", ".join(list_formatters())
            click.echo(f"Available formats: {available}", err=True)
            sys.exit(1)

        # Create API client
        api = PerplexityAPI(token=token)

        # Submit query and get answer
        answer_obj = api.get_complete_answer(query_text)

        # Format and output the answer
        formatted_output = formatter.format_complete(answer_obj)
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

                    headers = api.client.get_headers()
                    response = httpx.get(
                        "https://www.perplexity.ai/api/user",
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
