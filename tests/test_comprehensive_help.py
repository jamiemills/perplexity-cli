"""Tests for comprehensive --help output across all commands.

Every leaf command must include:
  - Detailed description (minimum length thresholds)
  - Usage examples
  - Example output showing realistic data
  - JSON envelope schema (for commands with --json)
  - Comprehensive option/argument help text

Group commands must include:
  - Substantive description of the group's purpose
  - Subcommand listing with descriptions
"""

import pytest
from click.testing import CliRunner

from perplexity_cli.cli import main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _help(runner: CliRunner, args: list[str]) -> str:
    """Invoke --help and return output, asserting exit 0."""
    result = runner.invoke(main, [*args, "--help"])
    assert result.exit_code == 0, f"--help failed for {args}: {result.output}"
    return result.output


# ---------------------------------------------------------------------------
# Group commands: substantive descriptions
# ---------------------------------------------------------------------------


class TestGroupHelpComprehensiveness:
    """Group commands must have a moderate overview, not just a one-liner."""

    @pytest.mark.parametrize(
        "group,expected_phrases",
        [
            ("auth", ["authentication", "login", "logout", "status"]),
            ("config", ["configuration", "set", "show"]),
            ("style", ["style", "set", "show", "clear"]),
            ("threads", ["thread", "export"]),
            ("skill", ["skill", "agent"]),
            ("doctor", ["diagnostic", "security"]),
            ("completion", ["shell", "completion"]),
        ],
    )
    def test_group_has_substantive_description(
        self, runner: CliRunner, group: str, expected_phrases: list[str]
    ) -> None:
        output = _help(runner, [group])
        for phrase in expected_phrases:
            assert phrase.lower() in output.lower(), f"{group} --help missing phrase: {phrase!r}"
        # Group help should be more than just "X commands." — at least 200 chars
        assert len(output) > 200, f"{group} --help too short ({len(output)} chars)"


# ---------------------------------------------------------------------------
# Leaf commands: examples section
# ---------------------------------------------------------------------------


class TestLeafCommandExamples:
    """Every leaf command must have an Examples section with realistic usage."""

    @pytest.mark.parametrize(
        "args,expected_example_fragment",
        [
            (["query"], "pxcli query"),
            (["auth", "login"], "pxcli auth login"),
            (["auth", "logout"], "pxcli auth logout"),
            (["auth", "status"], "pxcli auth status"),
            (["config", "set"], "pxcli config set"),
            (["config", "show"], "pxcli config show"),
            (["style", "set"], "pxcli style set"),
            (["style", "show"], "pxcli style show"),
            (["style", "clear"], "pxcli style clear"),
            (["threads", "export"], "pxcli threads export"),
            (["skill", "show"], "pxcli skill show"),
            (["doctor", "security"], "pxcli doctor security"),
            (["schema"], "pxcli schema"),
            (["completion", "bash"], "pxcli completion bash"),
            (["completion", "zsh"], "pxcli completion zsh"),
            (["completion", "fish"], "pxcli completion fish"),
        ],
    )
    def test_command_has_examples(
        self, runner: CliRunner, args: list[str], expected_example_fragment: str
    ) -> None:
        output = _help(runner, args)
        assert expected_example_fragment in output, (
            f"{' '.join(args)} --help missing example: {expected_example_fragment!r}"
        )


# ---------------------------------------------------------------------------
# Leaf commands with --json: example output section
# ---------------------------------------------------------------------------

_JSON_COMMANDS = [
    ["query"],
    ["auth", "login"],
    ["auth", "logout"],
    ["auth", "status"],
    ["config", "set"],
    ["config", "show"],
    ["style", "set"],
    ["style", "show"],
    ["style", "clear"],
    ["threads", "export"],
    ["skill", "show"],
    ["doctor", "security"],
]


class TestExampleOutput:
    """Commands with --json must show realistic example output."""

    @pytest.mark.parametrize("args", _JSON_COMMANDS)
    def test_has_example_output_section(self, runner: CliRunner, args: list[str]) -> None:
        """Each --json command's help must contain an example output section."""
        output = _help(runner, args)
        # Must contain a section header indicating example output
        assert "Example Output" in output or "example output" in output.lower(), (
            f"{' '.join(args)} --help missing 'Example Output' section"
        )

    @pytest.mark.parametrize("args", _JSON_COMMANDS)
    def test_example_output_shows_json_envelope(self, runner: CliRunner, args: list[str]) -> None:
        """Example output must show the JSON envelope shape with 'ok' field."""
        output = _help(runner, args)
        assert '"ok"' in output, (
            f"{' '.join(args)} --help example output missing '\"ok\"' envelope field"
        )


# ---------------------------------------------------------------------------
# Leaf commands with --json: JSON schema section
# ---------------------------------------------------------------------------


class TestJsonSchemaInHelp:
    """Commands with --json must show the full JSON Schema for the output envelope."""

    @pytest.mark.parametrize("args", _JSON_COMMANDS)
    def test_has_json_schema_section(self, runner: CliRunner, args: list[str]) -> None:
        output = _help(runner, args)
        assert "JSON Schema" in output, f"{' '.join(args)} --help missing 'JSON Schema' section"

    @pytest.mark.parametrize("args", _JSON_COMMANDS)
    def test_schema_contains_envelope_properties(self, runner: CliRunner, args: list[str]) -> None:
        """The schema section must reference key envelope properties."""
        output = _help(runner, args)
        # The Envelope schema should mention these fields
        for field in ("ok", "command", "result"):
            assert f'"{field}"' in output, (
                f"{' '.join(args)} --help schema missing field: {field!r}"
            )


# ---------------------------------------------------------------------------
# Query command: NDJSON streaming examples
# ---------------------------------------------------------------------------


class TestQueryNDJSONExamples:
    """The query command must include NDJSON streaming output examples."""

    def test_ndjson_section_present(self, runner: CliRunner) -> None:
        output = _help(runner, ["query"])
        assert "NDJSON" in output or "ndjson" in output.lower(), (
            "query --help missing NDJSON streaming section"
        )

    def test_ndjson_shows_event_types(self, runner: CliRunner) -> None:
        output = _help(runner, ["query"])
        for event_type in ("start", "chunk", "result"):
            assert f'"type": "{event_type}"' in output or f'"type":"{event_type}"' in output, (
                f"query --help missing NDJSON event type: {event_type!r}"
            )


# ---------------------------------------------------------------------------
# Comprehensive option/argument help text
# ---------------------------------------------------------------------------


class TestOptionHelpComprehensiveness:
    """Every option must have help text that is more than a trivial label."""

    def test_query_format_option_describes_all_choices(self, runner: CliRunner) -> None:
        output = _help(runner, ["query"])
        for fmt in ("plain", "markdown", "rich", "json"):
            assert fmt in output

    def test_query_stream_option_detailed(self, runner: CliRunner) -> None:
        output = _help(runner, ["query"])
        # Should explain what streaming does, not just "Stream response"
        assert "real-time" in output.lower() or "incremental" in output.lower()

    def test_query_attach_option_detailed(self, runner: CliRunner) -> None:
        output = _help(runner, ["query"])
        assert "directory" in output.lower()
        assert "recursive" in output.lower()

    def test_query_json_flag_detailed(self, runner: CliRunner) -> None:
        output = _help(runner, ["query"])
        # --json help should mention envelope or structured output
        assert "envelope" in output.lower() or "structured" in output.lower()

    def test_query_schema_flag_detailed(self, runner: CliRunner) -> None:
        output = _help(runner, ["query"])
        # --schema help should explain what it does
        assert "schema" in output.lower()

    def test_query_timeout_option_detailed(self, runner: CliRunner) -> None:
        output = _help(runner, ["query"])
        # Should mention default value
        assert "60" in output or "default" in output.lower()

    def test_auth_login_port_option_detailed(self, runner: CliRunner) -> None:
        output = _help(runner, ["auth", "login"])
        assert "9222" in output
        assert "Chrome" in output or "chrome" in output

    def test_auth_status_verify_option_detailed(self, runner: CliRunner) -> None:
        output = _help(runner, ["auth", "status"])
        assert "API" in output or "live" in output.lower()

    def test_threads_export_date_options_detailed(self, runner: CliRunner) -> None:
        output = _help(runner, ["threads", "export"])
        assert "ISO 8601" in output or "YYYY-MM-DD" in output
        assert "--from-date" in output
        assert "--to-date" in output

    def test_threads_export_cache_options_detailed(self, runner: CliRunner) -> None:
        output = _help(runner, ["threads", "export"])
        assert "cache" in output.lower()
        assert "--force-refresh" in output
        assert "--clear-cache" in output


# ---------------------------------------------------------------------------
# Help sections: exit codes, see also, env vars on more commands
# ---------------------------------------------------------------------------


class TestHelpSectionsExpanded:
    """All leaf commands should have exit codes; relevant commands get see-also and env-vars."""

    @pytest.mark.parametrize("args", _JSON_COMMANDS)
    def test_all_json_commands_have_exit_codes(self, runner: CliRunner, args: list[str]) -> None:
        output = _help(runner, args)
        assert "Exit Codes" in output or "EXIT CODES" in output, (
            f"{' '.join(args)} --help missing Exit Codes section"
        )

    @pytest.mark.parametrize(
        "args,expected_refs",
        [
            (["auth", "login"], ["pxcli auth status", "pxcli auth logout"]),
            (["auth", "logout"], ["pxcli auth login"]),
            (["auth", "status"], ["pxcli auth login", "pxcli auth logout"]),
            (["config", "set"], ["pxcli config show"]),
            (["config", "show"], ["pxcli config set"]),
            (["style", "set"], ["pxcli style show", "pxcli style clear"]),
            (["style", "show"], ["pxcli style set"]),
            (["style", "clear"], ["pxcli style set"]),
            (["threads", "export"], ["pxcli auth login"]),
            (["doctor", "security"], ["pxcli auth status"]),
        ],
    )
    def test_see_also_references(
        self, runner: CliRunner, args: list[str], expected_refs: list[str]
    ) -> None:
        output = _help(runner, args)
        assert "See Also" in output or "SEE ALSO" in output, (
            f"{' '.join(args)} --help missing See Also section"
        )
        for ref in expected_refs:
            assert ref in output, f"{' '.join(args)} --help See Also missing reference: {ref!r}"

    def test_query_has_env_vars(self, runner: CliRunner) -> None:
        output = _help(runner, ["query"])
        for var in ("PERPLEXITY_BASE_URL", "NO_COLOR", "XDG_CONFIG_HOME"):
            assert var in output

    def test_config_commands_have_env_vars(self, runner: CliRunner) -> None:
        output = _help(runner, ["config", "show"])
        assert "PERPLEXITY_CONFIG_DIR" in output or "XDG_CONFIG_HOME" in output


# ---------------------------------------------------------------------------
# Minimum help length thresholds
# ---------------------------------------------------------------------------


class TestHelpLengthThresholds:
    """Help output should be substantive — not terse one-liners."""

    @pytest.mark.parametrize(
        "args,min_chars",
        [
            # Complex commands need substantial help
            (["query"], 3000),
            (["auth", "login"], 2000),
            (["threads", "export"], 2000),
            # Simpler commands still need reasonable detail
            (["auth", "logout"], 1000),
            (["auth", "status"], 1500),
            (["config", "set"], 1000),
            (["config", "show"], 1000),
            (["style", "set"], 1000),
            (["style", "show"], 1000),
            (["style", "clear"], 1000),
            (["skill", "show"], 1000),
            (["doctor", "security"], 1000),
            (["schema"], 800),
            (["completion", "bash"], 500),
            (["completion", "zsh"], 500),
            (["completion", "fish"], 500),
        ],
    )
    def test_help_meets_minimum_length(
        self, runner: CliRunner, args: list[str], min_chars: int
    ) -> None:
        output = _help(runner, args)
        assert len(output) >= min_chars, (
            f"{' '.join(args)} --help too short: {len(output)} < {min_chars}"
        )
