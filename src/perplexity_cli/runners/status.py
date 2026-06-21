"""Status and diagnostics command runners."""

from __future__ import annotations

import logging
import stat
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeGuard

import click

from perplexity_cli._types import OutputFormat, SchemaInclusion
from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.envelope import success_envelope, write_envelope
from perplexity_cli.utils.exceptions import (
    AuthenticationError,
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    UpstreamSchemaError,
)
from perplexity_cli.utils.logging import get_logger

if TYPE_CHECKING:
    from perplexity_cli.config.models import FeatureConfig
    from perplexity_cli.envelope import Envelope
    from perplexity_cli.threads.cache_manager import ThreadCacheManager


def _is_str_dict(value: object) -> TypeGuard[dict[str, object]]:
    """TypeGuard: value is a dict with string keys."""
    return isinstance(value, dict)


def _ctx_to_dict() -> dict[str, object]:
    """Extract the Click context object as a typed dict."""
    ctx = click.get_current_context(silent=True)
    if ctx is None:
        return {}
    raw: object = ctx.obj
    if _is_str_dict(raw):
        return raw
    return {}


def _get_include_schema() -> SchemaInclusion:
    """Read include_schema flag from Click context."""
    ctx_dict = _ctx_to_dict()
    val: object = ctx_dict.get("schema", False)
    return "with_schema" if bool(val) else "no_schema"


def _get_json_mode_from_ctx() -> OutputFormat:
    """Read json_mode flag from Click context."""
    ctx_dict = _ctx_to_dict()
    val: object = ctx_dict.get("json", False)
    return "json" if bool(val) else "human"


def _describe_file_permissions(path: Path | None, expected: int) -> str:
    """Describe the security state of a file by its permissions."""
    if path is None or not path.exists():
        return "not present"

    actual = stat.S_IMODE(path.stat().st_mode)
    if actual == expected:
        return f"secure ({oct(actual)})"
    return f"insecure ({oct(actual)}; expected {oct(expected)})"


def _output_doctor_security_json(
    tm: TokenManager,
    cache_manager: ThreadCacheManager,
    feature_config: FeatureConfig,
) -> None:
    """Write the doctor security report as a JSON envelope."""
    token_perms = _describe_file_permissions(tm.token_path, tm.SECURE_PERMISSIONS)
    cache_perms = _describe_file_permissions(
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


def _output_doctor_security_text(
    tm: TokenManager,
    cache_manager: ThreadCacheManager,
    feature_config: FeatureConfig,
) -> None:
    """Print the doctor security report as human-readable text."""
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
        f"Token file permissions: {_describe_file_permissions(tm.token_path, tm.SECURE_PERMISSIONS)}"
    )
    click.echo(f"Thread cache file: {cache_manager.cache_path}")
    click.echo(
        "Thread cache permissions: "
        f"{_describe_file_permissions(cache_manager.cache_path, cache_manager.SECURE_PERMISSIONS)}"
    )
    click.echo(f"Cookie storage enabled: {feature_config.save_cookies}")
    if feature_config.save_cookies:
        click.echo(
            "Cookie storage warning: browser cookies are sensitive and should only be stored "
            "when needed for Cloudflare/session reuse"
        )


def run_doctor_security_command(*, output_format: OutputFormat | None = None) -> None:
    """Execute the doctor security command."""
    from perplexity_cli.threads.cache_manager import ThreadCacheManager
    from perplexity_cli.utils.config import get_feature_config

    if output_format is None:
        output_format = _get_json_mode_from_ctx()

    tm: TokenManager = TokenManager()
    cache_manager: ThreadCacheManager = ThreadCacheManager()
    feature_config = get_feature_config()

    if output_format == "json":
        _output_doctor_security_json(tm, cache_manager, feature_config)
        return

    _output_doctor_security_text(tm, cache_manager, feature_config)


def _build_status_envelope(
    authenticated: bool,
    tm: TokenManager,
    token_info: tuple[object, object, object] = (None, 0, None),
) -> Envelope:
    """Build a status envelope dictionary."""
    token_age_days, cookies_stored, verified = token_info
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


def _verify_token(
    token: str,
    cookies: dict[str, str] | None,
    logger: logging.Logger,
) -> bool | None:
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


def _get_token_age_days(token_path: Any) -> int | None:
    """Compute the age of the token file in days."""
    try:
        stat_result: object = token_path.stat()
        modified_time = datetime.fromtimestamp(int(getattr(stat_result, "st_mtime", 0)))
        return (datetime.now() - modified_time).days
    except (OSError, AttributeError, TypeError, ValueError):
        return None


def _output_status_text(
    token: str,
    cookies: dict[str, str] | None,
    verify_info: tuple[object, object, object],
    tm: TokenManager,
) -> None:
    """Print human-readable status output."""
    token_age_days, verified, verify = verify_info
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


def _output_token_modified_time(token_path: Any, token_age_days: object) -> None:
    """Print token modification time if available."""
    if token_age_days is None:
        return
    try:
        stat_result: object = token_path.stat()
        modified_time = datetime.fromtimestamp(int(getattr(stat_result, "st_mtime", 0)))
        click.echo(f"Token last modified: {modified_time.strftime('%Y-%m-%d %H:%M:%S')}")
    except (OSError, AttributeError):
        click.echo("Token last modified: unavailable")


def _output_verification_result(verified: object, logger: logging.Logger) -> None:
    """Print verification result."""
    if verified is True:
        click.echo("\n[OK] Token is valid and working")
        logger.info("Token verification successful")
    elif verified is False:
        click.echo("\n[ERROR] Token verification failed")
    else:
        click.echo("\n[INFO] Token verification returned empty response")
        logger.warning("Token verification returned empty response")


def _handle_no_token(
    output_format: OutputFormat,
    tm: TokenManager,
    show_auth_hint: Literal["show", "hide"] = "show",
) -> None:
    """Handle the case where no valid token is available."""
    if output_format == "json":
        write_envelope(_build_status_envelope(False, tm), include_schema=_get_include_schema())
        return
    click.echo("Perplexity CLI Status")
    click.echo("=" * 40)
    click.echo("Status: [ERROR] Not authenticated")
    if show_auth_hint == "show":
        click.echo("\nAuthenticate with: pxcli auth login")


def _handle_authenticated_status(
    status_data: tuple[str, dict[str, str] | None, Literal["verify", "skip"], OutputFormat],
    tm: TokenManager,
    logger: logging.Logger,
) -> None:
    """Handle status output when a valid token is present."""
    token, cookies, verify, output_format = status_data
    token_age_days = _get_token_age_days(tm.token_path)
    cookies_stored = len(cookies) if cookies else 0
    verified = _verify_token(token, cookies, logger) if verify == "verify" else None

    if output_format == "json":
        write_envelope(
            _build_status_envelope(True, tm, (token_age_days, cookies_stored, verified)),
            include_schema=_get_include_schema(),
        )
        return

    _output_status_text(token, cookies, (token_age_days, verified, verify == "verify"), tm)


def run_status_command(
    verify: Literal["verify", "skip"], *, output_format: OutputFormat | None = None
) -> None:
    """Execute the status command."""
    from perplexity_cli.auth.token_manager import TokenManager

    if output_format is None:
        output_format = _get_json_mode_from_ctx()

    logger = get_logger()
    tm: TokenManager = TokenManager()

    if not tm.token_exists():
        _handle_no_token(output_format, tm)
        return

    try:
        token, cookies = tm.load_token()
        if not token:
            _handle_no_token(output_format, tm, show_auth_hint="hide")
            return

        _handle_authenticated_status((token, cookies, verify, output_format), tm, logger)

    except AuthenticationError as e:
        click.echo("Status: [INFO] Token file has insecure permissions")
        click.echo(f"Error: {e}")
        click.echo(f"\nFix with: chmod 0600 {tm.token_path}")
        logger.error(
            "Token file has insecure permissions: %s", e
        )
