"""Model listing command runner.

Orchestrates fetching the model catalogue from the Perplexity API,
filtering by subscription tier, and formatting the output as either
a human-readable table or a JSON envelope.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from perplexity_cli.services.model_service import ModelService

from perplexity_cli.models.model_config import ModelConfigEntry, SubscriptionLevel
from perplexity_cli.utils.logging import get_logger


def _get_ctx_flag(ctx_obj: dict[str, Any] | None, key: str) -> bool:
    """Read a boolean flag from the Click context object.

    Args:
        ctx_obj: The Click context object dictionary, or None.
        key: The key to look up.

    Returns:
        The flag value, defaulting to False.
    """
    if ctx_obj is None:
        return False
    return ctx_obj.get(key, False)


def _resolve_auth() -> tuple[str | None, dict[str, str] | None]:
    """Resolve authentication credentials.

    Returns:
        Tuple of (token, cookies), either or both may be None.
    """
    from perplexity_cli.auth.token_manager import TokenManager
    from perplexity_cli.auth.utils import load_token_optional

    logger = get_logger()
    token_manager = TokenManager()
    return load_token_optional(token_manager, logger)


def _create_rest_client(
    token: str,
    cookies: dict[str, str] | None,
) -> Any:
    """Create a REST client for API calls.

    Args:
        token: Authentication token.
        cookies: Optional browser cookies.

    Returns:
        Configured RestClient instance.
    """
    from perplexity_cli.api.rest_client import RestClient
    from perplexity_cli.auth.models import AuthContext

    auth = AuthContext(token=token, cookies=cookies)
    return RestClient(auth=auth)


def _detect_subscription_level(client: Any) -> SubscriptionLevel:
    """Detect the user's subscription level from the settings API.

    Fetches user settings and infers the subscription level.
    Falls back to Pro on any error, since an authenticated user
    who reaches this point is likely a subscriber.

    Args:
        client: REST client for API calls.

    Returns:
        The detected subscription level.
    """
    from perplexity_cli.models.model_config import UserSettings
    from perplexity_cli.utils.config import get_user_settings_endpoint

    logger = get_logger()
    try:
        settings_payload = client.get_json(get_user_settings_endpoint())
        settings = UserSettings.model_validate(settings_payload)
        level = settings.infer_subscription_level()
        logger.debug("Detected subscription level: %s", level.value)
        return level
    except Exception as exc:
        logger.warning(
            "Could not detect subscription level, defaulting to Pro: %s",
            exc,
        )
        return SubscriptionLevel.PRO


def _create_model_service(
    client: Any,
    subscription_level: SubscriptionLevel,
) -> ModelService:
    """Create a ModelService with the given client and subscription level.

    Args:
        client: REST client for API calls.
        subscription_level: The user's subscription level.

    Returns:
        Configured ModelService instance.
    """
    from perplexity_cli.services.model_service import ModelService

    return ModelService(
        rest_client=client,
        subscription_level=subscription_level,
    )


def format_model_table(entries: list[ModelConfigEntry]) -> str:
    """Format model entries as a plain-text table.

    Args:
        entries: List of model config entries to display.

    Returns:
        Formatted table string with headers and aligned columns.
    """
    if not entries:
        return "No models available."

    rows = _build_table_rows(entries)
    return _render_table(rows)


def _build_table_rows(
    entries: list[ModelConfigEntry],
) -> list[tuple[str, str, str, str]]:
    """Build row tuples from model config entries.

    Args:
        entries: Model config entries.

    Returns:
        List of (model_id, label, tier, description) tuples.
    """
    rows: list[tuple[str, str, str, str]] = []
    for entry in entries:
        model_id: str = entry.model_id or "(none)"  # pyright: ignore[reportUnknownMemberType]
        label: str = entry.label  # pyright: ignore[reportUnknownMemberType]
        if entry.is_default:  # pyright: ignore[reportUnknownMemberType]
            label = f"{label} (default)"
        tier: str = entry.subscription_tier.capitalize()  # pyright: ignore[reportUnknownMemberType]
        description: str = entry.description or ""  # pyright: ignore[reportUnknownMemberType]
        rows.append((model_id, label, tier, description))
    return rows


def _render_table(rows: list[tuple[str, str, str, str]]) -> str:
    """Render rows as an aligned table with headers.

    Args:
        rows: List of (model_id, label, tier, description) tuples.

    Returns:
        Formatted table string.
    """
    headers = ("MODEL ID", "LABEL", "TIER", "DESCRIPTION")
    widths = _calculate_column_widths(headers, rows)
    lines = [_format_row(headers, widths), _format_separator(widths)]
    for row in rows:
        lines.append(_format_row(row, widths))
    return "\n".join(lines)


def _calculate_column_widths(
    headers: tuple[str, str, str, str],
    rows: list[tuple[str, str, str, str]],
) -> list[int]:
    """Calculate minimum column widths for alignment.

    Args:
        headers: Column header strings.
        rows: Data row tuples.

    Returns:
        List of column widths.
    """
    widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))
    return widths


def _format_row(cells: tuple[str, str, str, str], widths: list[int]) -> str:
    """Format a single table row with padding.

    Args:
        cells: Cell values.
        widths: Column widths for alignment.

    Returns:
        Formatted row string.
    """
    parts = [cell.ljust(widths[idx]) for idx, cell in enumerate(cells)]
    return "  ".join(parts)


def _format_separator(widths: list[int]) -> str:
    """Format a separator line under the headers.

    Args:
        widths: Column widths.

    Returns:
        Dashed separator string.
    """
    return "  ".join("-" * width for width in widths)


def build_models_json_result(
    entries: list[ModelConfigEntry],
) -> dict[str, Any]:
    """Build the JSON result dictionary for the models list.

    Args:
        entries: List of model config entries.

    Returns:
        Dictionary with a ``models`` key containing serialised model data.
    """
    models = [_entry_to_dict(entry) for entry in entries]
    return {"models": models}


def _entry_to_dict(entry: ModelConfigEntry) -> dict[str, Any]:
    """Convert a single ModelConfigEntry to a result dictionary.

    Args:
        entry: The model config entry.

    Returns:
        Dictionary with model metadata.
    """
    return {
        "model_id": entry.model_id,
        "label": entry.label,
        "tier": entry.subscription_tier,
        "description": entry.description or "",
        "reasoning_model": entry.reasoning_model,
        "is_default": entry.is_default,
    }


def run_models_list_command(
    ctx_obj: dict[str, Any] | None,
) -> None:
    """Execute the models list command.

    Fetches the model catalogue, filters by accessibility, and
    outputs either a human-readable table or a JSON envelope.

    Args:
        ctx_obj: The Click context object dictionary, or None.
    """
    logger = get_logger()
    json_mode = _get_ctx_flag(ctx_obj, "json")
    include_schema = _get_ctx_flag(ctx_obj, "schema")

    token, cookies = _resolve_auth()
    if token is None:
        click.echo(
            "[ERROR] Authentication required. Run 'pxcli auth login' first.",
            err=True,
        )
        logger.error("Model listing attempted without authentication")
        sys.exit(1)

    try:
        client = _create_rest_client(token, cookies)
        level = _detect_subscription_level(client)
        service = _create_model_service(client, level)
        entries = service.list_available_models()
    except Exception as exc:
        _handle_list_error(exc, json_mode, logger)
        return  # unreachable; _handle_list_error always exits

    if json_mode:
        _output_json(entries, include_schema)
    else:
        click.echo(format_model_table(entries))


def _output_json(  # nosemgrep: boolean-flag-argument
    entries: list[ModelConfigEntry],
    include_schema: bool,
) -> None:
    """Write models list as a JSON envelope to stdout.

    Args:
        entries: Accessible model entries.
        include_schema: Whether to embed JSON schema.
    """
    from perplexity_cli.envelope import success_envelope, write_envelope

    result = build_models_json_result(entries)
    envelope = success_envelope("pxcli models list", result)
    write_envelope(envelope, include_schema=include_schema)


def _handle_list_error(  # nosemgrep: boolean-flag-argument
    exc: Exception,
    json_mode: bool,
    logger: Any,
) -> None:
    """Handle errors from the model listing operation.

    Args:
        exc: The exception raised.
        json_mode: Whether JSON output mode is active.
        logger: Logger instance.
    """
    from perplexity_cli.utils.exceptions import (
        PerplexityHTTPStatusError,
        PerplexityRequestError,
    )

    if json_mode:
        from perplexity_cli.error_handler import handle_error

        handle_error(exc, command="pxcli models list", json_mode=True)

    if isinstance(exc, PerplexityHTTPStatusError):
        logger.error("HTTP error fetching models: %s", exc)
        click.echo(f"[ERROR] Failed to fetch models: {exc}", err=True)
        sys.exit(1)

    if isinstance(exc, PerplexityRequestError):
        logger.error("Network error fetching models: %s", exc)
        click.echo(f"[ERROR] Network error: {exc}", err=True)
        sys.exit(1)

    logger.error("Unexpected error fetching models: %s", exc)
    click.echo(f"[ERROR] Unexpected error: {exc}", err=True)
    sys.exit(1)
