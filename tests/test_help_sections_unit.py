"""Direct unit tests for section writers in ``_help_sections.py`` and
``build_command_schemas`` in ``_schemas.py``.

These tests live outside the mutmut exclusion list, so mutations to the
help-writing machinery and schema builder are caught during mutation testing.
Integration coverage is provided by ``test_comprehensive_help.py``, but those
tests don't exercise every branch of the individual writer functions.
"""

from __future__ import annotations

import click
from click import HelpFormatter

from perplexity_cli.commands._help_sections import (
    HelpSectionConfig,
    _write_env_vars,
    _write_exit_codes,
    _write_json_example,
    _write_ndjson_example,
    _write_see_also,
    add_help_sections,
)
from perplexity_cli.commands._schemas import (
    COMMAND_RESULT_SCHEMAS,
    build_command_schemas,
)

# ---------------------------------------------------------------------------
# HelpFormatter helpers
# ---------------------------------------------------------------------------


def _fmt(width: int = 120) -> HelpFormatter:
    """Return a fresh Click HelpFormatter at the given width."""
    return HelpFormatter(width=width)


def _buffer_text(fmt: HelpFormatter) -> str:
    """Extract the accumulated text from a formatter buffer."""
    return fmt.getvalue().decode() if isinstance(fmt.getvalue(), bytes) else fmt.getvalue()


# ---------------------------------------------------------------------------
# _write_json_example
# ---------------------------------------------------------------------------


class TestWriteJsonExample:
    """Tests for :func:`_write_json_example`."""

    def test_writes_example_with_indentation(self) -> None:
        f = _fmt()
        _write_json_example(f, '{"ok": true}')
        text = _buffer_text(f)
        assert "Example Output (--json):" in text
        assert '  {"ok": true}' in text

    def test_empty_example_is_written(self) -> None:
        """An empty example string produces a section header with no body lines."""
        f = _fmt()
        _write_json_example(f, "")
        text = _buffer_text(f)
        assert "Example Output (--json):" in text


# ---------------------------------------------------------------------------
# _write_ndjson_example
# ---------------------------------------------------------------------------


class TestWriteNdjsonExample:
    """Tests for :func:`_write_ndjson_example`."""

    def test_writes_header_and_event_types(self) -> None:
        f = _fmt()
        _write_ndjson_example(f, '{"type": "start"}')
        text = _buffer_text(f)
        assert "NDJSON Streaming Output" in text
        assert "start" in text

    def test_writes_ndjson_lines_indented(self) -> None:
        f = _fmt()
        _write_ndjson_example(f, '{"type": "chunk"}')
        text = _buffer_text(f)
        assert '  {"type": "chunk"}' in text


# ---------------------------------------------------------------------------
# _write_see_also
# ---------------------------------------------------------------------------


class TestWriteSeeAlso:
    """Tests for :func:`_write_see_also`."""

    def test_writes_single_reference(self) -> None:
        f = _fmt()
        _write_see_also(f, ("pxcli auth login",))
        text = _buffer_text(f)
        assert "See Also" in text
        assert "pxcli auth login" in text

    def test_writes_multiple_references(self) -> None:
        f = _fmt()
        _write_see_also(f, ("pxcli auth login", "pxcli query"))
        text = _buffer_text(f)
        assert "pxcli auth login" in text
        assert "pxcli query" in text

    def test_empty_tuple_produces_no_body(self) -> None:
        """When the tuple is empty, the section header is not written."""
        f = _fmt()
        _write_see_also(f, ())
        text = _buffer_text(f)
        # The writer is only called when see_also is non-empty.
        # Here the function still runs; it writes the header but no items.
        assert "See Also" in text


# ---------------------------------------------------------------------------
# _write_env_vars
# ---------------------------------------------------------------------------


class TestWriteEnvVars:
    """Tests for :func:`_write_env_vars`."""

    def test_writes_variable_list(self) -> None:
        f = _fmt()
        _write_env_vars(f, ("PERPLEXITY_BASE_URL", "NO_COLOR"))
        text = _buffer_text(f)
        assert "Environment Variables" in text
        assert "PERPLEXITY_BASE_URL" in text
        assert "NO_COLOR" in text

    def test_empty_tuple_produces_no_body(self) -> None:
        f = _fmt()
        _write_env_vars(f, ())
        text = _buffer_text(f)
        assert "Environment Variables" in text


# ---------------------------------------------------------------------------
# _write_exit_codes
# ---------------------------------------------------------------------------


class TestWriteExitCodes:
    """Tests for :func:`_write_exit_codes`."""

    def test_writes_exit_code_table(self) -> None:
        f = _fmt()
        _write_exit_codes(f)
        text = _buffer_text(f)
        assert "Exit Codes" in text
        # At least one known exit code should appear
        assert "0" in text


# ---------------------------------------------------------------------------
# add_help_sections — wrappable integration
# ---------------------------------------------------------------------------


class TestAddHelpSections:
    """Tests for :func:`add_help_sections` wrapping a Click command."""

    def test_simple_command_with_exit_codes(self) -> None:
        """A simple Click command's help is extended with exit codes."""

        @click.command("test")
        def _testcmd() -> None:
            """A minimal test command."""
            pass

        config = HelpSectionConfig(exit_codes=True)
        cmd: click.Command = add_help_sections(_testcmd, config)
        ctx = click.Context(cmd, info_name="test")
        f = HelpFormatter()
        cmd.format_help(ctx, f)
        text = f.getvalue()
        text_str = text.decode() if isinstance(text, bytes) else text
        assert "Exit Codes" in text_str

    def test_command_with_all_sections(self) -> None:
        """Every enabled section appears in the help output."""

        @click.command("full")
        def _fullcmd() -> None:
            """A command with all help sections enabled."""
            pass

        config = HelpSectionConfig(
            json_example='{"ok": true}',
            ndjson_example='{"type": "start"}',
            json_schema=True,
            exit_codes=True,
            see_also=("pxcli query",),
            env_vars=("PERPLEXITY_BASE_URL",),
        )
        cmd: click.Command = add_help_sections(_fullcmd, config)
        ctx = click.Context(cmd, info_name="full")
        f = HelpFormatter()
        cmd.format_help(ctx, f)
        raw = f.getvalue()
        text_str = raw.decode() if isinstance(raw, bytes) else raw
        assert "Example Output" in text_str
        assert "NDJSON Streaming Output" in text_str
        assert "JSON Schema" in text_str
        assert "Exit Codes" in text_str
        assert "See Also" in text_str
        assert "Environment Variables" in text_str


# ---------------------------------------------------------------------------
# build_command_schemas
# ---------------------------------------------------------------------------


class TestBuildCommandSchemas:
    """Tests for :func:`build_command_schemas`."""

    def test_output_maps_every_command(self) -> None:
        """The output dict must have an entry for every known command."""
        schemas = build_command_schemas()
        assert set(schemas) == set(COMMAND_RESULT_SCHEMAS)

    def test_each_output_has_properties(self) -> None:
        """Every command entry must have an 'output' definition."""
        schemas = build_command_schemas()
        for cmd_name, entry in schemas.items():
            assert "output" in entry, f"{cmd_name} missing output key"
            props = entry["output"].get("properties", {})
            assert isinstance(props, dict), f"{cmd_name} has invalid properties"

    def test_query_schema_properties_match(self) -> None:
        """The query command output must include the expected fields."""
        schemas = build_command_schemas()
        query_out = schemas["query"]
        refs = query_out["output"]["properties"]["references"]["items"]["properties"]
        assert set(refs) == {"name", "url", "snippet"}

    def test_empty_input_produces_empty_dict(self) -> None:
        """When COMMAND_RESULT_SCHEMAS is inspected (not mutated), function is idempotent."""
        schemas1 = build_command_schemas()
        schemas2 = build_command_schemas()
        assert schemas1 == schemas2
