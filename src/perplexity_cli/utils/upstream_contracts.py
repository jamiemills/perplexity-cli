"""Validation helpers for private upstream API payload contracts."""

from collections.abc import Callable
from typing import Any, TypeGuard

from perplexity_cli.utils.exceptions import UpstreamSchemaError

_ShapeDescriber = Callable[[object], str]


def _is_mapping(value: object) -> TypeGuard[dict[str, object]]:
    """Narrow JSON-shaped ``object`` values to ``dict[str, object]``."""
    return isinstance(value, dict)


def _is_sequence(value: object) -> TypeGuard[list[object]]:
    """Narrow JSON-shaped ``object`` values to ``list[object]``."""
    return isinstance(value, list)


def _describe_dict_shape(value: object) -> str:
    """Describe a dictionary-shaped payload value for diagnostics."""
    if not _is_mapping(value):
        return type(value).__name__
    keys = sorted(str(key) for key in value.keys())[:5]
    return f"object(keys=[{', '.join(keys)}])"


def _describe_list_shape(value: object) -> str:
    """Describe a list-shaped payload value for diagnostics."""
    if not _is_sequence(value):
        return type(value).__name__
    return f"array(len={len(value)})"


def _describe_str_shape(value: object) -> str:
    """Describe a string-shaped payload value for diagnostics."""
    if not isinstance(value, str):
        return type(value).__name__
    return f"string(len={len(value)})"


_SHAPE_DESCRIBERS: dict[type, _ShapeDescriber] = {
    dict: _describe_dict_shape,
    list: _describe_list_shape,
    str: _describe_str_shape,
}


def describe_payload_shape(value: object) -> str:
    """Describe a payload value briefly for schema-drift diagnostics."""
    if value is None:
        return "null"
    describer = _SHAPE_DESCRIBERS.get(type(value))
    if describer is not None:
        return describer(value)
    return type(value).__name__


def schema_error(
    context: str, expected: str, value: object, detail: str | None = None
) -> UpstreamSchemaError:
    """Build a consistent schema-drift error with payload shape details."""
    message = f"{context}: expected {expected}, got {describe_payload_shape(value)}"
    if detail:
        message = f"{message} ({detail})"
    return UpstreamSchemaError(message)


def require_mapping(
    value: object, context: str, detail: str | None = None
) -> dict[str, Any]:
    """Require a dictionary-shaped payload value."""
    if not _is_mapping(value):
        raise schema_error(context, "object", value, detail)
    return value


def require_list(
    value: object, context: str, detail: str | None = None
) -> list[Any]:
    """Require a list-shaped payload value."""
    if not _is_sequence(value):
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
