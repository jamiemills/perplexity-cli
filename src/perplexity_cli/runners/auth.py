"""Authentication command runners."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, NoReturn, TypeGuard, cast

import click

from perplexity_cli._types import DebugMode, OutputFormat, SchemaInclusion
from perplexity_cli.auth.oauth_handler import authenticate_sync
from perplexity_cli.auth.token_manager import TokenManager  # construction-only
from perplexity_cli.envelope import success_envelope, write_envelope
from perplexity_cli.error_handler import handle_error
from perplexity_cli.runners._utils import resolve_json_flag
from perplexity_cli.utils.atomic_write import atomic_write_json
from perplexity_cli.utils.config import get_perplexity_base_url, get_save_cookies_enabled
from perplexity_cli.utils.exceptions import AuthenticationError, ConfigurationError
from perplexity_cli.utils.http_errors import handle_unexpected_cli_error
from perplexity_cli.utils.logging import get_logger, redact_path, redact_text

_AUTH_LOGIN_COMMAND = "pxcli auth login"
_AUTH_EXPORT_COMMAND = "pxcli auth export"
_AUTH_IMPORT_COMMAND = "pxcli auth import"
_BUNDLE_VERSION = 1
_EXPORT_WARNING = (
    "[WARNING] The export file contains PLAINTEXT session credentials. "
    "Anyone who can read it can use your Perplexity account. "
    "Protect it (it is written with 0600 permissions); "
    "prefer --output to choose a safe location."
)
_IMPORT_COOKIES_WARNING = (
    "[WARNING] The bundle contains cookies but save_cookies is disabled; "
    "they will NOT be stored. "
    "Run 'pxcli config set save_cookies true' and re-import to keep them."
)
_MALFORMED_BUNDLE_COOKIES_ERROR = "Bundle 'cookies' must be an object of name-to-string values."


@dataclass(frozen=True, slots=True)
class _AuthOutputOptions:
    """Resolved output options for an authentication attempt."""

    output_format: OutputFormat
    schema_inclusion: SchemaInclusion
    debug_level: DebugMode


def _is_str_dict(value: object) -> TypeGuard[dict[str, object]]:
    """TypeGuard: value is a dictionary with string keys."""
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


def _print_auth_troubleshooting(port: int, base_url: str) -> None:
    """Print authentication troubleshooting steps."""
    click.echo("\nTroubleshooting:", err=True)
    click.echo(f"  1. Start Chrome with: --remote-debugging-port={port}", err=True)
    click.echo("  2. Ensure Chrome is running and accessible", err=True)
    click.echo(f"  3. Navigate to {base_url} in Chrome", err=True)
    click.echo("  4. Log in with your Google account", err=True)
    click.echo("  5. Run this command again", err=True)


def _handle_auth_success(
    token: str,
    cookies: dict[str, str],
    output_format: OutputFormat,
    include_schema: SchemaInclusion,
) -> None:
    """Handle successful authentication output."""
    tm = TokenManager()
    tm.save_token(token, cookies=cookies)
    # owner: security - the only argument is the redacted token-file path.
    get_logger().info(  # nosemgrep: custom.credential-logging-vendored,python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure  # owner: auth-team; reason: token redacted before logging
        "Token and cookies saved to %s", redact_path(tm.token_path)
    )

    if output_format == "json":
        env = success_envelope(
            _AUTH_LOGIN_COMMAND,
            {"token_path": str(tm.token_path), "cookies_stored": len(cookies)},
        )
        write_envelope(env, include_schema=include_schema)
        return

    click.echo("[OK] Authentication successful!")
    click.echo(f"[OK] Token saved to: {tm.token_path}")

    if get_save_cookies_enabled():
        click.echo(f"[OK] {len(cookies)} cookies saved (including Cloudflare cookies)")
    else:
        click.echo("[INFO] Cookies not saved (disabled in config)")
        click.echo("  To enable cookie storage: pxcli config set save_cookies true")

    click.echo('\nYou can now use: pxcli query "<your question>"')


def _resolve_ctx_flags(ctx_obj: object) -> tuple[bool, bool, bool]:
    """Extract json_mode, include_schema, and debug_mode from context."""
    ctx_dict = (
        _ctx_to_dict() if ctx_obj is None else ctx_obj if _is_str_dict(ctx_obj) else _ctx_to_dict()
    )
    val_json: object = ctx_dict.get("json", False)
    val_schema: object = ctx_dict.get("schema", False)
    val_debug: object = ctx_dict.get("debug", False)
    return bool(val_json), bool(val_schema), bool(val_debug)


def run_auth_command(ctx_obj: object, port: int) -> None:
    """Execute the auth command."""
    logger = get_logger()
    json_mode, include_schema, debug_mode = _resolve_ctx_flags(ctx_obj)
    logger.info("Starting authentication on port %s", port)

    base_url = get_perplexity_base_url()
    if not json_mode:
        click.echo("Authenticating with Perplexity.ai...")
        click.echo(f"\nMake sure Chrome is running with --remote-debugging-port={port}")
        click.echo(f"Navigate to {base_url} and log in if needed.\n")

    try:
        _execute_auth(port, (json_mode, include_schema, debug_mode), base_url)
    except KeyboardInterrupt:
        logger.info("Authentication interrupted by user")


def _handle_auth_timeout_error(
    e: TimeoutError | AuthenticationError,
    output_format: OutputFormat,
    port: int,
    base_url: str,
) -> None:
    """Handle authentication timeout or authentication errors."""
    if output_format == "json":
        handle_error(e, _AUTH_LOGIN_COMMAND, output_format="json")
    get_logger().debug(
        "Authentication failed: %s",
        redact_text(str(e), max_length=0),
    )
    click.echo(f"[ERROR] Authentication failed: {e}", err=True)
    _print_auth_troubleshooting(port, base_url)
    sys.exit(1)


def _handle_auth_os_config_error(
    e: OSError | ConfigurationError,
    output_format: OutputFormat,
    debug_level: DebugMode,
) -> None:
    """Handle OS-level or configuration errors during authentication."""
    if output_format == "json":
        handle_error(e, _AUTH_LOGIN_COMMAND, output_format="json")
    handle_unexpected_cli_error(
        e,
        get_logger(),
        debug_mode=debug_level,
        message_tuple=(
            f"[ERROR] Unexpected error: {e}",
            "Unexpected error during authentication",
            False,
        ),
    )


def _resolve_auth_output_options(ctx_flags: tuple[bool, bool, bool]) -> _AuthOutputOptions:
    """Convert raw context flags to typed authentication output options."""
    json_mode, include_schema, debug_mode = ctx_flags
    return _AuthOutputOptions(
        output_format="json" if json_mode else "human",
        schema_inclusion="with_schema" if include_schema else "no_schema",
        debug_level="debug" if debug_mode else "normal",
    )


def _execute_auth(
    port: int,
    ctx_flags: tuple[bool, bool, bool],
    base_url: str,
) -> None:
    """Perform authentication and handle domain-specific errors."""
    options = _resolve_auth_output_options(ctx_flags)
    logger = get_logger()

    try:
        logger.debug("Calling authenticate_sync")
        token, cookies = authenticate_sync(port=port)
        # owner: security - the argument is a cookie count, never a token or cookie value.
        logger.info(  # nosemgrep: custom.credential-logging-vendored,python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure  # owner: auth-team; reason: token redacted before logging
            "Token and %s cookies extracted successfully", len(cookies)
        )
        _handle_auth_success(
            token,
            cookies,
            options.output_format,
            options.schema_inclusion,
        )
    except (TimeoutError, AuthenticationError) as e:
        # Not silent: delegated to the auth timeout handler.
        _handle_auth_timeout_error(e, options.output_format, port, base_url)
    except (OSError, ConfigurationError) as e:
        # Not silent: delegated to the OS/config error handler.
        _handle_auth_os_config_error(e, options.output_format, options.debug_level)


def _resolve_logout_ctx(
    json_mode: bool | None,
) -> tuple[OutputFormat, SchemaInclusion]:
    """Resolve json_mode and include_schema from context."""
    ctx_dict = _ctx_to_dict()
    resolved_json = resolve_json_flag(json_mode, ctx_dict)
    val_schema: object = ctx_dict.get("schema", False)
    return (
        "json" if resolved_json else "human",
        "with_schema" if bool(val_schema) else "no_schema",
    )


def _logout_emit(
    output_format: OutputFormat,
    include_schema: SchemaInclusion,
    credential_state: Literal["present", "absent"],
) -> None:
    """Emit logout result in the appropriate format."""
    if output_format == "json":
        env = success_envelope(
            "pxcli auth logout", {"credentials_existed": credential_state == "present"}
        )
        write_envelope(env, include_schema=include_schema)
        return
    if credential_state == "absent":
        click.echo("No stored credentials found.")
    else:
        click.echo("[OK] Logged out successfully.")
        click.echo("[OK] Stored credentials removed.")


def run_logout_command(*, json_mode: bool | None = None) -> None:
    """Execute the logout command."""
    resolved_json, include_schema = _resolve_logout_ctx(json_mode)
    tm = TokenManager()

    if not tm.token_exists():
        _logout_emit(resolved_json, include_schema, credential_state="absent")
        return

    try:
        tm.clear_token()
        _logout_emit(resolved_json, include_schema, credential_state="present")
    except OSError as e:
        # Not silent: surfaced via handle_error / user-facing output below.
        if resolved_json == "json":
            handle_error(e, "pxcli auth logout", output_format="json")
        logger = get_logger()
        handle_unexpected_cli_error(
            e,
            logger,
            message_tuple=(f"[ERROR] Error during logout: {e}", "Error during logout", False),
        )


def _default_export_path() -> Path:
    """Build the default timestamped export filename in the CWD."""
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    return Path(f"pxcli-auth-{timestamp}.json")


def _build_export_bundle(token: str, cookies: dict[str, str] | None) -> dict[str, object]:
    """Build the plaintext credential bundle written by the export command."""
    return {
        "version": _BUNDLE_VERSION,
        "token": token,
        "cookies": cookies or {},
        "exported_at": datetime.now(UTC).isoformat(),
    }


def _handle_export_missing_token(output_format: OutputFormat) -> NoReturn:
    """Exit with the AUTH_REQUIRED (4) taxonomy code when no token is stored.

    Uses the centralised ``handle_error`` flow so JSON mode emits the
    standard error envelope and human mode prints to stderr.
    """
    handle_error(
        AuthenticationError("No stored credentials found. Run 'pxcli auth login' first."),
        _AUTH_EXPORT_COMMAND,
        output_format=output_format,
    )


def _write_export_bundle(token: str, cookies: dict[str, str] | None, path: Path) -> None:
    """Print the plaintext warning, then atomically write the 0600 bundle."""
    click.echo(_EXPORT_WARNING, err=True)
    atomic_write_json(path, _build_export_bundle(token, cookies), mode=0o600)


def _emit_export_result(
    path: Path,
    output_format: OutputFormat,
    include_schema: SchemaInclusion,
) -> None:
    """Emit the export result as a JSON envelope or human text (path only)."""
    if output_format == "json":
        env = success_envelope(_AUTH_EXPORT_COMMAND, {"path": str(path)})
        write_envelope(env, include_schema=include_schema)
        return
    click.echo(f"[OK] Credentials exported to {path}")


def run_export_command(output: Path | None) -> None:
    """Execute the auth export command."""
    options = _resolve_auth_output_options(_resolve_ctx_flags(None))
    token, cookies = TokenManager().load_token()
    if not token:
        _handle_export_missing_token(options.output_format)

    path = output or _default_export_path()
    try:
        _write_export_bundle(token, cookies, path)
    except OSError as e:
        # Not silent: delegated to the central error handler.
        handle_error(
            e,
            _AUTH_EXPORT_COMMAND,
            output_format=options.output_format,
            include_schema=options.schema_inclusion,
        )
    # owner: security - the only argument is the redacted export-file path.
    get_logger().info(  # nosemgrep: custom.credential-logging-vendored,python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure  # owner: auth-team; reason: only the redacted export path is logged, never the token or cookies
        "Credentials exported to %s",
        redact_path(path),
    )
    _emit_export_result(path, options.output_format, options.schema_inclusion)


def _read_bundle_file(path: Path) -> dict[str, object]:
    """Read the import file and parse it as a JSON object.

    Args:
        path: Bundle file path (path only; contents are never logged).

    Returns:
        The parsed bundle dictionary.

    Raises:
        ValueError: If the file is unreadable, not valid JSON, or not an
            object.  Unreadable files are re-raised as ``ValueError`` so the
            taxonomy maps them to VALIDATION (exit 7).
    """
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        msg = f"Cannot read import file: {e}"
        raise ValueError(msg) from e
    except json.JSONDecodeError as e:
        msg = f"Import file is not valid JSON: {e}"
        raise ValueError(msg) from e
    if not _is_str_dict(raw):
        msg = "Import bundle must be a JSON object."
        raise ValueError(msg)
    return raw


def _require_bundle_version(bundle: dict[str, object]) -> None:
    """Validate the bundle's ``version`` field.

    Args:
        bundle: The parsed import bundle.

    Raises:
        ValueError: If the version is missing or unsupported.
    """
    version = bundle.get("version")
    if version != _BUNDLE_VERSION:
        msg = f"Unsupported bundle version {version!r}; expected {_BUNDLE_VERSION}."
        raise ValueError(msg)


def _require_bundle_token(bundle: dict[str, object]) -> str:
    """Extract and validate the bundle's ``token`` field.

    Args:
        bundle: The parsed import bundle.

    Returns:
        The plaintext session token.

    Raises:
        ValueError: If the token is missing, not a string, or empty.
    """
    token = bundle.get("token")
    if not isinstance(token, str) or not token:
        msg = "Bundle 'token' must be a non-empty string."
        raise ValueError(msg)
    return token


def _is_str_str_dict(value: object) -> TypeGuard[dict[str, str]]:
    """TypeGuard: value is a dictionary mapping string keys to string values."""
    if not isinstance(value, dict):
        return False
    mapping = cast("dict[object, object]", value)
    return all(isinstance(key, str) and isinstance(item, str) for key, item in mapping.items())


def _validate_import_cookies(raw: object) -> dict[str, str] | None:
    """Narrow the bundle's ``cookies`` value to a str-to-str mapping.

    Unknown top-level bundle keys are ignored leniently; this validator only
    enforces the shape of the ``cookies`` value itself.

    Args:
        raw: The parsed ``cookies`` value (may be absent).

    Returns:
        The validated cookie mapping, or ``None`` when absent/empty.

    Raises:
        ValueError: If cookies is not an object of name-to-string values.
    """
    if raw is None:
        return None
    if not _is_str_str_dict(raw):
        raise ValueError(_MALFORMED_BUNDLE_COOKIES_ERROR)
    return dict(raw) or None


def _load_import_bundle(
    path: Path,
    options: _AuthOutputOptions,
) -> tuple[str, dict[str, str] | None]:
    """Read and validate the import bundle, exiting via the taxonomy on failure.

    Args:
        path: Bundle file path (path only; contents are never logged).
        options: Resolved output options for error envelopes.

    Returns:
        Tuple of the validated token and optional cookie mapping.
    """
    try:
        bundle = _read_bundle_file(path)
        _require_bundle_version(bundle)
        token = _require_bundle_token(bundle)
        cookies = _validate_import_cookies(bundle.get("cookies"))
    except ValueError as e:
        # Not silent: delegated to the central error handler (VALIDATION, exit 7).
        handle_error(
            e,
            _AUTH_IMPORT_COMMAND,
            output_format=options.output_format,
            include_schema=options.schema_inclusion,
        )
    return token, cookies


def _cookies_will_be_stored(cookies: dict[str, str] | None) -> bool:
    """Return whether the pending save will persist cookies."""
    return bool(cookies) and get_save_cookies_enabled()


def _save_imported_credentials(
    token: str,
    cookies: dict[str, str] | None,
    options: _AuthOutputOptions,
) -> None:
    """Warn about dropped cookies, then re-encrypt and store credentials.

    Args:
        token: The plaintext session token from the bundle.
        cookies: The optional cookie mapping from the bundle.
        options: Resolved output options for error envelopes.
    """
    if cookies and not get_save_cookies_enabled():
        click.echo(_IMPORT_COOKIES_WARNING, err=True)
    try:
        TokenManager().save_token(token, cookies if cookies else None)
    except (OSError, RuntimeError) as e:
        # Not silent: delegated to the central error handler.
        handle_error(
            e,
            _AUTH_IMPORT_COMMAND,
            output_format=options.output_format,
            include_schema=options.schema_inclusion,
        )


def _emit_import_result(
    result: dict[str, object],
    output_format: OutputFormat,
    include_schema: SchemaInclusion,
) -> None:
    """Emit the import result as a JSON envelope or human text."""
    if output_format == "json":
        env = success_envelope(_AUTH_IMPORT_COMMAND, result)
        write_envelope(env, include_schema=include_schema)
        return
    click.echo("[OK] Credentials imported")


def run_import_command(bundle_path: Path) -> None:
    """Execute the auth import command."""
    options = _resolve_auth_output_options(_resolve_ctx_flags(None))
    token, cookies = _load_import_bundle(bundle_path, options)
    _save_imported_credentials(token, cookies, options)
    # owner: security - the only argument is the redacted bundle path.
    get_logger().info(  # nosemgrep: custom.credential-logging-vendored,python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure  # owner: auth-team; reason: only the redacted bundle path is logged, never the token or cookies
        "Credentials imported from %s",
        redact_path(bundle_path),
    )
    _emit_import_result(
        {"imported": True, "cookies_stored": _cookies_will_be_stored(cookies)},
        options.output_format,
        options.schema_inclusion,
    )
