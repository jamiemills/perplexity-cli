"""Status and diagnostics command runners."""

import stat
from datetime import datetime
from pathlib import Path

import click

from perplexity_cli.utils.exceptions import (
    AuthenticationError,
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    UpstreamSchemaError,
)
from perplexity_cli.utils.logging import get_logger


def run_doctor_security_command() -> None:
    """Execute the doctor security command."""
    from perplexity_cli.auth.token_manager import TokenManager
    from perplexity_cli.threads.cache_manager import ThreadCacheManager
    from perplexity_cli.utils.config import get_feature_config

    tm = TokenManager()
    cache_manager = ThreadCacheManager()
    feature_config = get_feature_config()

    def describe_permissions(path: Path | None, expected: int) -> str:
        if path is None or not path.exists():
            return "not present"

        actual = stat.S_IMODE(path.stat().st_mode)
        if actual == expected:
            return f"secure ({oct(actual)})"
        return f"insecure ({oct(actual)}; expected {oct(expected)})"

    click.echo("Perplexity CLI Security")
    click.echo("=" * 40)
    click.echo("Storage backend: machine-bound encrypted file storage")
    click.echo(
        "Threat model: protects against casual file copying between machines, not against "
        "other local processes or users that can already read these files"
    )
    click.echo()
    click.echo(f"Token file: {tm.token_path}")
    click.echo(
        f"Token file permissions: {describe_permissions(tm.token_path, tm.SECURE_PERMISSIONS)}"
    )
    click.echo(f"Thread cache file: {cache_manager.cache_path}")
    click.echo(
        "Thread cache permissions: "
        f"{describe_permissions(cache_manager.cache_path, cache_manager.SECURE_PERMISSIONS)}"
    )
    click.echo(f"Cookie storage enabled: {feature_config.save_cookies}")
    if feature_config.save_cookies:
        click.echo(
            "Cookie storage warning: browser cookies are sensitive and should only be stored "
            "when needed for Cloudflare/session reuse"
        )


def run_status_command(verify: bool) -> None:
    """Execute the status command."""
    from perplexity_cli.api.endpoints import PerplexityAPI
    from perplexity_cli.auth.token_manager import TokenManager

    logger = get_logger()
    tm = TokenManager()

    click.echo("Perplexity CLI Status")
    click.echo("=" * 40)

    if not tm.token_exists():
        click.echo("Status: [ERROR] Not authenticated")
        click.echo("\nAuthenticate with: pxcli auth")
        return

    try:
        token, cookies = tm.load_token()
        if not token:
            click.echo("Status: [ERROR] Not authenticated")
            return

        click.echo("Status: [OK] Authenticated")
        click.echo(f"Token file: {tm.token_path}")
        click.echo(f"Token length: {len(token)} characters")
        if cookies:
            click.echo(f"Cookies: {len(cookies)} stored")

        try:
            stat_result = tm.token_path.stat()
            modified_time = datetime.fromtimestamp(stat_result.st_mtime)
            click.echo(f"Token last modified: {modified_time.strftime('%Y-%m-%d %H:%M:%S')}")
        except OSError:
            pass

        if not verify:
            click.echo("\n[INFO] Live verification not run")
            click.echo("Use 'pxcli status --verify' to test the current token against the API.")
            return

        try:
            from perplexity_cli.config.defaults import DEFAULT_STATUS_CHECK_TIMEOUT

            logger.debug("Verifying token validity")
            with PerplexityAPI(
                token=token, cookies=cookies, timeout=DEFAULT_STATUS_CHECK_TIMEOUT
            ) as api:
                test_answer = api.get_complete_answer("test")
            if test_answer and len(test_answer.text) > 0:
                click.echo("\n[OK] Token is valid and working")
                logger.info("Token verification successful")
            else:
                click.echo("\n[INFO] Token verification returned empty response")
                logger.warning("Token verification returned empty response")
        except PerplexityHTTPStatusError as e:
            if e.response.status_code == 401:
                click.echo("\n[ERROR] Token is invalid or expired")
                logger.warning("Token verification failed: 401 Unauthorized")
            else:
                click.echo(f"\n[INFO] Token verification failed (HTTP {e.response.status_code})")
                logger.warning(f"Token verification failed: HTTP {e.response.status_code}")
        except (PerplexityRequestError, UpstreamSchemaError, AuthenticationError) as e:
            click.echo("\n[INFO] Token verification failed (unable to test)")
            logger.debug(f"Token verification error: {e}", exc_info=True)

    except AuthenticationError as e:
        click.echo("Status: [INFO] Token file has insecure permissions")
        click.echo(f"Error: {e}")
        click.echo(f"\nFix with: chmod 0600 {tm.token_path}")
        logger.error(f"Token file has insecure permissions: {e}")
