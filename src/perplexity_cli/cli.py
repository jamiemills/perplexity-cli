"""Command-line interface for Perplexity CLI."""

import click

from perplexity_cli import __version__


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """Perplexity CLI - Query Perplexity.ai from the command line."""
    pass


@main.command()
def auth() -> None:
    """Authenticate with Perplexity.ai."""
    click.echo("Auth command not yet implemented")


@main.command()
@click.argument("query")
def query(query: str) -> None:
    """Submit a query to Perplexity.ai."""
    click.echo(f"Query command not yet implemented: {query}")


@main.command()
def logout() -> None:
    """Log out and remove stored credentials."""
    click.echo("Logout command not yet implemented")


@main.command()
def status() -> None:
    """Show current authentication status."""
    click.echo("Status command not yet implemented")


if __name__ == "__main__":
    main()
