"""Enhanced help-section machinery for Click commands.

Provides :func:`add_help_sections`, which wraps a Click command's
``format_help`` to append standard sections (JSON examples, exit codes,
``See Also``, environment variables, JSON Schema).

The section configuration is bundled in a frozen :class:`HelpSectionConfig`
dataclass so the public entry point stays within the project's four-argument
ceiling and the inner writer dispatches over a (condition, writer) table
rather than a chain of conditional branches.
"""

from __future__ import annotations

import json as _json
from collections.abc import Callable
from dataclasses import dataclass

import click

__all__ = [
    "HelpSectionConfig",
    "add_help_sections",
]

#: Type of a function that writes one help section into a formatter.
_SectionWriter = Callable[[click.HelpFormatter], None]


@dataclass(frozen=True, slots=True)
class HelpSectionConfig:
    """Toggle bundle describing which extra sections a command's help shows.

    Attributes:
        exit_codes: Append the standard exit-code table.
        see_also: Related command references to list under ``See Also``.
        env_vars: Environment variables relevant to the command.
        json_example: Realistic JSON output example displayed under
            ``Example Output``.
        ndjson_example: NDJSON streaming output example (used by ``query``).
        json_schema: When ``True``, append the full JSON Schema for the
            success/error envelopes.
    """

    exit_codes: bool = False
    see_also: tuple[str, ...] = ()
    env_vars: tuple[str, ...] = ()
    json_example: str | None = None
    ndjson_example: str | None = None
    json_schema: bool = False


def _write_json_example(formatter: click.HelpFormatter, example: str) -> None:
    """Write a JSON output example section."""
    formatter.write("\n")
    formatter.write("Example Output (--json):\n")
    for line in example.strip().splitlines():
        formatter.write("  " + line + "\n")
    formatter.write("\n")


def _write_ndjson_example(formatter: click.HelpFormatter, example: str) -> None:
    """Write an NDJSON streaming output example section."""
    formatter.write("\n")
    formatter.write("NDJSON Streaming Output (--json --stream):\n")
    formatter.write(
        "  Each line is a self-contained JSON object.  Event types:\n"
        "  start, chunk, result (final line).\n\n"
    )
    for line in example.strip().splitlines():
        formatter.write("  " + line + "\n")
    formatter.write("\n")


def _write_json_schema(formatter: click.HelpFormatter) -> None:
    """Write Pydantic JSON schema sections for Envelope and ErrorEnvelope."""
    from perplexity_cli.envelope import Envelope, ErrorEnvelope

    formatter.write("\n")
    formatter.write("JSON Schema (Success Envelope):\n")
    schema_text = _json.dumps(Envelope.model_json_schema(), indent=2)
    for line in schema_text.splitlines():
        formatter.write("  " + line + "\n")
    formatter.write("\n")

    formatter.write("JSON Schema (Error Envelope):\n")
    err_schema_text = _json.dumps(ErrorEnvelope.model_json_schema(), indent=2)
    for line in err_schema_text.splitlines():
        formatter.write("  " + line + "\n")
    formatter.write("\n")


def _write_exit_codes(formatter: click.HelpFormatter) -> None:
    """Write the standard exit-code table section."""
    from perplexity_cli.exit_codes import format_exit_codes_help

    formatter.write("\n")
    with formatter.section("Exit Codes"):
        for line in format_exit_codes_help().strip().splitlines():
            if line.startswith("Exit codes:"):
                continue
            formatter.write_text(line.strip())


def _write_see_also(formatter: click.HelpFormatter, refs: tuple[str, ...]) -> None:
    """Write the See Also section."""
    formatter.write("\n")
    with formatter.section("See Also"):
        for ref in refs:
            formatter.write_text(ref)


def _write_env_vars(formatter: click.HelpFormatter, variables: tuple[str, ...]) -> None:
    """Write the Environment Variables section."""
    formatter.write("\n")
    with formatter.section("Environment Variables"):
        for var in variables:
            formatter.write_text(var)


def _build_section_writers(
    config: HelpSectionConfig,
) -> list[tuple[bool, _SectionWriter]]:
    """Build the (enabled, writer) dispatch table for a section config."""
    json_example = config.json_example
    ndjson_example = config.ndjson_example
    see_also = config.see_also
    env_vars = config.env_vars
    return [
        (
            json_example is not None,
            lambda f: _write_json_example(f, json_example or ""),
        ),
        (
            ndjson_example is not None,
            lambda f: _write_ndjson_example(f, ndjson_example or ""),
        ),
        (config.json_schema, _write_json_schema),
        (config.exit_codes, _write_exit_codes),
        (bool(see_also), lambda f: _write_see_also(f, see_also)),
        (bool(env_vars), lambda f: _write_env_vars(f, env_vars)),
    ]


def _write_extra_sections(formatter: click.HelpFormatter, config: HelpSectionConfig) -> None:
    """Write every enabled extra help section in canonical order."""
    for enabled, writer in _build_section_writers(config):
        if enabled:
            writer(formatter)


def add_help_sections(cmd: click.Command, config: HelpSectionConfig) -> click.Command:
    """Wrap a Click command's ``format_help`` to append standard sections.

    Parameters:
        cmd: The Click command whose help output should be extended.
        config: Toggle bundle describing which sections to append.

    Returns:
        The same ``cmd`` instance, returned for chaining convenience.
    """
    original_format_help = cmd.format_help

    def enhanced_format_help(ctx: click.Context, formatter: click.HelpFormatter) -> None:
        original_format_help(ctx, formatter)
        _write_extra_sections(formatter, config)

    # Instance-dict assignment keeps the replacement function on this specific
    # command instance without triggering ty's class-method shadowing check
    # (direct ``cmd.format_help = ...`` would be flagged as a signature
    # mismatch with the unbound class method).
    cmd.__dict__["format_help"] = enhanced_format_help
    return cmd
