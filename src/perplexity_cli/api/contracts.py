"""Validation helpers for private upstream API payload contracts."""

from typing import Any

from perplexity_cli.utils.exceptions import UpstreamSchemaError


def describe_payload_shape(value: Any) -> str:
    """Describe a payload value briefly for schema-drift diagnostics."""

    if value is None:
        return "null"
    if isinstance(value, dict):
        keys = ", ".join(sorted(str(key) for key in value.keys())[:5])
        return f"object(keys=[{keys}])"
    if isinstance(value, list):
        return f"array(len={len(value)})"
    if isinstance(value, str):
        return f"string(len={len(value)})"
    return type(value).__name__


def schema_error(
    context: str, expected: str, value: Any, detail: str | None = None
) -> UpstreamSchemaError:
    """Build a consistent schema-drift error with payload shape details."""

    message = f"{context}: expected {expected}, got {describe_payload_shape(value)}"
    if detail:
        message = f"{message} ({detail})"
    return UpstreamSchemaError(message)


def require_mapping(value: Any, context: str, detail: str | None = None) -> dict[str, Any]:
    """Require a dictionary-shaped payload value."""

    if not isinstance(value, dict):
        raise schema_error(context, "object", value, detail)
    return value


def require_list(value: Any, context: str, detail: str | None = None) -> list[Any]:
    """Require a list-shaped payload value."""

    if not isinstance(value, list):
        raise schema_error(context, "array", value, detail)
    return value


def parse_upload_url_response(payload: Any) -> dict[str, Any]:
    """Validate the private upload URL response shape."""

    response = require_mapping(payload, "Malformed upload URL response from upstream API")
    results = require_mapping(
        response.get("results"),
        "Malformed upload results payload from upstream API",
        detail="missing or invalid 'results' field",
    )

    for file_uuid, upload_data in results.items():
        require_mapping(
            upload_data,
            "Malformed upload result entry from upstream API",
            detail=f"file_uuid={file_uuid}",
        )

    return response


def parse_thread_list_payload(payload: Any) -> list[dict[str, Any]]:
    """Validate the private thread-list response shape."""

    thread_entries = require_list(payload, "Malformed thread list payload from upstream API")
    return [
        require_mapping(entry, "Malformed thread entry in upstream API response")
        for entry in thread_entries
    ]
