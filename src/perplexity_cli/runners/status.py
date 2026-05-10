"""Status and diagnostics command runners."""

import stat
from datetime import datetime
from pathlib import Path

import click

from perplexity_cli.envelope import success_envelope, write_envelope
from perplexity_cli.utils.exceptions import (
    AuthenticationError,
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    UpstreamSchemaError,
)
from perplexity_cli.utils.logging import get_logger


def _get_include_schema() -> bool:
    """Read include_schema flag from Click context."""
    ctx = click.get_current_context(silent=True)
    ctx_obj = ctx.obj if ctx else {}
    return ctx_obj.get("schema", False) if ctx_obj else False


def _get_json_mode_from_ctx() -> bool:
    """Read json_mode flag from Click context."""
    ctx = click.get_current_context(silent=True)
    ctx_obj = ctx.obj if ctx else {}
    return ctx_obj.get("json", False) if ctx_obj else False


def run_doctor_security_command(*, json_mode: bool | None = None) -> None:
    """Execute the doctor security command."""
    from perplexity_cli.auth.token_manager import TokenManager
    from perplexity_cli.threads.cache_manager import ThreadCacheManager
    from perplexity_cli.utils.config import get_feature_config

    if json_mode is None:
        json_mode = _get_json_mode_from_ctx()

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

    if json_mode:
        token_perms = describe_permissions(tm.token_path, tm.SECURE_PERMISSIONS)
        cache_perms = describe_permissions(
            cache_manager.cache_path, cache_manager.SECURE_PERMISSIONS
        )
        env = success_envelope(
            "pxcli doctor security",
            {
                "storage_backend": "machine-bound encrypted file storage",
                "token_path": str(tm.token_path),
                "token_permissions": token_perms,
                "cache_path": str(cache_manager.cache_path),
                "cache_permissions": cache_perms,
                "cookies_enabled": feature_config.save_cookies,
            },
        )
        write_envelope(env, include_schema=_get_include_schema())
        return

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


def _build_status_envelope(  # nosemgrep: too-many-parameters, boolean-flag-argument
    authenticated: bool,
    tm,
    token_age_days=None,
    cookies_stored=0,
    verified=None,
):
    """Build a status envelope dictionary."""
    return success_envelope(
        "pxcli auth status",
        {
            "authenticated": authenticated,
            "token_path": str(tm.token_path),
            "token_age_days": token_age_days,
            "cookies_stored": cookies_stored,
            "verified": verified,
        },
    )


def _verify_token(token, cookies, logger) -> bool | None:
    """Run token verification against the API."""
    from perplexity_cli.api.endpoints import PerplexityAPI

    try:
        from perplexity_cli.config.defaults import DEFAULT_STATUS_CHECK_TIMEOUT

        logger.debug("Verifying token validity")
        with PerplexityAPI(
            token=token, cookies=cookies, timeout=DEFAULT_STATUS_CHECK_TIMEOUT
        ) as api:
            test_answer = api.get_complete_answer("test")
        return bool(test_answer and test_answer.text)
    except (
        PerplexityHTTPStatusError,
        PerplexityRequestError,
        UpstreamSchemaError,
        AuthenticationError,
    ):
        return False


def _get_token_age_days(token_path) -> int | None:
    """Compute the age of the token file in days."""
    try:
        stat_result = token_path.stat()
        modified_time = datetime.fromtimestamp(stat_result.st_mtime)
        return (datetime.now() - modified_time).days
    except OSError:
        return None


def _output_status_text(  # nosemgrep: too-many-parameters
    token, cookies, token_age_days, verified, verify, tm
) -> None:
    """Print human-readable status output."""
    logger = get_logger()
    click.echo("Perplexity CLI Status")
    click.echo("=" * 40)
    click.echo("Status: [OK] Authenticated")
    click.echo(f"Token file: {tm.token_path}")
    click.echo(f"Token length: {len(token)} characters")
    if cookies:
        click.echo(f"Cookies: {len(cookies)} stored")

    _output_token_modified_time(tm.token_path, token_age_days)

    if not verify:
        click.echo("\n[INFO] Live verification not run")
        click.echo("Use 'pxcli auth status --verify' to test the current token against the API.")
        return

    _output_verification_result(verified, logger)


def _output_token_modified_time(token_path, token_age_days) -> None:
    """Print token modification time if available."""
    if token_age_days is None:
        return
    try:
        stat_result = token_path.stat()
        modified_time = datetime.fromtimestamp(stat_result.st_mtime)
        click.echo(f"Token last modified: {modified_time.strftime('%Y-%m-%d %H:%M:%S')}")
    except OSError:
        click.echo("Token last modified: unavailable")


def _output_verification_result(verified, logger) -> None:
    """Print verification result."""
    if verified is True:
        click.echo("\n[OK] Token is valid and working")
        logger.info("Token verification successful")
    elif verified is False:
        click.echo("\n[ERROR] Token verification failed")
    else:
        click.echo("\n[INFO] Token verification returned empty response")
        logger.warning("Token verification returned empty response")


def _handle_no_token(  # nosemgrep: boolean-flag-argument
    json_mode: bool, tm, show_auth_hint: bool = True
) -> None:
    """Handle the case where no valid token is available."""
    if json_mode:
        write_envelope(_build_status_envelope(False, tm), include_schema=_get_include_schema())
        return
    click.echo("Perplexity CLI Status")
    click.echo("=" * 40)
    click.echo("Status: [ERROR] Not authenticated")
    if show_auth_hint:
        click.echo("\nAuthenticate with: pxcli auth login")


def _handle_authenticated_status(  # nosemgrep: too-many-parameters
    token, cookies, verify, json_mode, tm, logger
) -> None:
    """Handle status output when a valid token is present."""
    token_age_days = _get_token_age_days(tm.token_path)
    cookies_stored = len(cookies) if cookies else 0
    verified = _verify_token(token, cookies, logger) if verify else None

    if json_mode:
        write_envelope(
            _build_status_envelope(True, tm, token_age_days, cookies_stored, verified),
            include_schema=_get_include_schema(),
        )
        return

    _output_status_text(token, cookies, token_age_days, verified, verify, tm)


def run_status_command(  # nosemgrep: boolean-flag-argument
    verify: bool, *, json_mode: bool | None = None
) -> None:
    """Execute the status command."""
    from perplexity_cli.auth.token_manager import TokenManager

    if json_mode is None:
        json_mode = _get_json_mode_from_ctx()

    logger = get_logger()
    tm = TokenManager()

    if not tm.token_exists():
        _handle_no_token(json_mode, tm)
        return

    try:
        token, cookies = tm.load_token()
        if not token:
            _handle_no_token(json_mode, tm, show_auth_hint=False)
            return

        _handle_authenticated_status(token, cookies, verify, json_mode, tm, logger)

    except AuthenticationError as e:
        click.echo("Status: [INFO] Token file has insecure permissions")
        click.echo(f"Error: {e}")
        click.echo(f"\nFix with: chmod 0600 {tm.token_path}")
        logger.error(  # nosemgrep: python-logger-credential-disclosure
            "Token file has insecure permissions: %s", e
        )
