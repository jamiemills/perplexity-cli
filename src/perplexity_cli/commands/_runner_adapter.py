"""Typed bridge to the runner layer.

The runner functions exposed here originate in modules whose ``ctx_obj``
parameter is typed as bare ``dict | None`` (partially unknown under strict
checking).  This adapter presents a fully-typed facade to the command modules
so that:

* partially-typed upstream signatures do not propagate as
  ``reportUnknownVariableType`` diagnostics into ``commands/``;
* CLI startup cost stays low — heavy sub-modules load lazily inside each
  adapter via :func:`importlib.import_module`, only when their command runs.

Multi-parameter runners accept a frozen :class:`~dataclasses.dataclass`
bundle rather than a long argument list, keeping every adapter well under the
project's four-argument ceiling.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path

import click

from perplexity_cli.exit_codes import ActionResult


@dataclass(frozen=True, slots=True)
class ExportRequest:
    """Parameter bundle for :func:`run_export_threads_command`."""

    from_date: str | None
    to_date: str | None
    output: Path | None
    force_refresh: bool
    clear_cache: bool


@dataclass(frozen=True, slots=True)
class QueryOptions:
    """Optional flags for :func:`run_query_command`, built from CLI flags."""

    output_format: str | None
    strip_references: bool
    stream: bool
    attachments: tuple[str, ...]
    model_preference: str | None
    request_param_overrides: tuple[str, ...]


def run_auth_command(ctx_obj: dict[str, object] | None, port: int) -> None:
    """Delegate to :func:`perplexity_cli.runners.run_auth_command`."""
    runners = importlib.import_module("perplexity_cli.runners")
    runners.run_auth_command(ctx_obj, port)


def run_export_threads_command(ctx_obj: object, request: ExportRequest) -> None:
    """Delegate to :func:`perplexity_cli.runners.run_export_threads_command`."""
    runners = importlib.import_module("perplexity_cli.runners")
    runners.run_export_threads_command(
        ctx_obj,
        request.from_date,
        request.to_date,
        request.output,
        request.force_refresh,
        request.clear_cache,
    )


def run_query_command(ctx_obj: dict[str, object] | None, query_text: str, options: QueryOptions) -> None:
    query_runner = importlib.import_module("perplexity_cli.query_runner")
    result: ActionResult = query_runner.run_query_command(ctx_obj, query_text, options.output_format, options.strip_references, options.stream, options.attachments, model_preference=options.model_preference, request_param_overrides=options.request_param_overrides, output_fn=click.echo)
    if result.message:
        if result.stream_to_stderr:
            click.echo(result.message, err=True)
        else:
            click.echo(result.message)
    if result.exit_code != 0:
        sys.exit(result.exit_code)
