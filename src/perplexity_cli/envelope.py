"""JSON output envelope models and builder functions.

Provides structured envelope types for consistent JSON output from
CLI commands, covering both success and error responses.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel


class ErrorCode(str, Enum):
    """Standardised error codes for structured error responses."""

    authentication_required = "authentication_required"
    permission_denied = "permission_denied"
    rate_limited = "rate_limited"
    network_error = "network_error"
    timeout = "timeout"
    upstream_schema_error = "upstream_schema_error"
    configuration_error = "configuration_error"
    attachment_error = "attachment_error"
    validation_error = "validation_error"
    not_found = "not_found"
    internal_error = "internal_error"


class Meta(BaseModel):
    """Metadata about the command execution."""

    duration_ms: int
    version: str
    trace_id: str
    truncated: bool = False


class NextAction(BaseModel):
    """A suggested follow-up action for the consumer."""

    command: str
    description: str
    params: dict[str, str] | None = None


class ErrorDetail(BaseModel):
    """Structured error information."""

    code: ErrorCode
    message: str
    input: dict[str, Any] = {}


class Envelope(BaseModel):
    """Success response envelope."""

    ok: Literal[True] = True
    command: str
    result: dict[str, Any]
    meta: Meta | None = None
    next_actions: list[NextAction] = []


class ErrorEnvelope(BaseModel):
    """Error response envelope."""

    ok: Literal[False] = False
    command: str
    error: ErrorDetail
    fix: str | None = None
    next_actions: list[NextAction] = []


def success_envelope(
    command: str,
    result: dict[str, Any],
    *,
    meta: Meta | None = None,
    next_actions: list[NextAction] | None = None,
) -> Envelope:
    """Build a success envelope."""
    return Envelope(
        command=command,
        result=result,
        meta=meta,
        next_actions=next_actions or [],
    )


def error_envelope(
    command: str,
    code: ErrorCode,
    message: str,
    *,
    fix: str | None = None,
    input_data: dict[str, Any] | None = None,
    next_actions: list[NextAction] | None = None,
) -> ErrorEnvelope:
    """Build an error envelope."""
    return ErrorEnvelope(
        command=command,
        error=ErrorDetail(code=code, message=message, input=input_data or {}),
        fix=fix,
        next_actions=next_actions or [],
    )


def envelope_to_dict(
    env: Envelope | ErrorEnvelope,
    *,
    include_schema: bool = False,
) -> dict[str, Any]:
    """Serialise an envelope to a dict, optionally embedding a ``$schema`` key.

    When *include_schema* is ``True`` the Pydantic-generated JSON Schema for
    the envelope's concrete type is prepended as ``$schema``, making the
    output self-describing.
    """
    data = env.model_dump(mode="json")
    if include_schema:
        schema = type(env).model_json_schema()
        data = {"$schema": schema, **data}
    return data


def write_envelope(
    env: Envelope | ErrorEnvelope,
    *,
    include_schema: bool = False,
    output: Any | None = None,
) -> None:
    """Serialise an envelope as JSON and write it as a single line.

    Parameters
    ----------
    env:
        The envelope model to serialise.
    include_schema:
        When ``True``, embed the JSON Schema under a ``$schema`` key.
    output:
        Writable file-like object.  Defaults to ``sys.stdout``.
    """
    import json
    import sys

    out = output if output is not None else sys.stdout
    data = envelope_to_dict(env, include_schema=include_schema)
    out.write(json.dumps(data, default=str) + "\n")
