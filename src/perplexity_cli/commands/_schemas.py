"""Per-command result-field schema definitions used by ``pxcli schema``.

Each entry describes the shape of the ``result`` object that a command emits
when invoked with ``--json``.  The schema data is intentionally permissive
(``dict[str, object]``) because it mirrors free-form JSON Schema fragments.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "COMMAND_RESULT_SCHEMAS",
    "build_command_schemas",
]

COMMAND_RESULT_SCHEMAS: dict[str, dict[str, Any]] = {
    "query": {
        "answer": {"type": "string"},
        "references": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "snippet": {"type": "string"},
                },
            },
        },
    },
    "auth login": {
        "token_path": {"type": "string"},
        "cookies_stored": {"type": "integer"},
    },
    "auth logout": {
        "credentials_existed": {"type": "boolean"},
    },
    "auth status": {
        "authenticated": {"type": "boolean"},
        "token_path": {"type": "string"},
        "token_age_days": {"type": ["integer", "null"]},
        "cookies_stored": {"type": "integer"},
        "verified": {"type": ["boolean", "null"]},
    },
    "config set": {
        "key": {"type": "string"},
        "value": {"type": "boolean"},
    },
    "config show": {
        "config_path": {"type": "string"},
        "save_cookies": {"type": "boolean"},
        "debug_mode": {"type": "boolean"},
        "env_overrides": {"type": "array", "items": {"type": "string"}},
    },
    "style set": {
        "style": {"type": "string"},
    },
    "style show": {
        "style": {"type": ["string", "null"]},
    },
    "style clear": {
        "had_style": {"type": "boolean"},
    },
    "threads export": {
        "threads": {"type": "array"},
        "total": {"type": "integer"},
        "output_path": {"type": "string"},
        "date_range": {"type": "object"},
    },
    "doctor security": {
        "storage_backend": {"type": "string"},
        "token_path": {"type": "string"},
        "token_permissions": {"type": "string"},
        "cache_path": {"type": "string"},
        "cache_permissions": {"type": "string"},
        "cookies_enabled": {"type": "boolean"},
    },
}


def build_command_schemas() -> dict[str, dict[str, Any]]:
    """Build per-command schema entries with output definitions.

    Each command name maps to an envelope describing the ``result`` object's
    field shape, suitable for inclusion in the top-level ``pxcli schema``
    output.
    """
    result: dict[str, dict[str, Any]] = {}
    for cmd_name, output_schema in COMMAND_RESULT_SCHEMAS.items():
        result[cmd_name] = {
            "output": {
                "type": "object",
                "properties": output_schema,
            },
        }
    return result
