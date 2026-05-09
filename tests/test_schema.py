"""Tests for schema command (spec 5.1.10-5.1.13)."""

import json

from click.testing import CliRunner

from perplexity_cli.cli import main


class TestSchemaCommand:
    """Test the schema command output."""

    def test_schema_exits_zero_with_valid_json(self, runner: CliRunner) -> None:
        """5.1.10 — pxcli schema exits 0 and produces valid JSON."""
        result = runner.invoke(main, ["schema"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)

    def test_schema_has_top_level_keys(self, runner: CliRunner) -> None:
        """5.1.13 — Schema output has success_envelope, error_envelope, commands."""
        result = runner.invoke(main, ["schema"])
        data = json.loads(result.output)
        assert "success_envelope" in data
        assert "error_envelope" in data
        assert "commands" in data

    def test_schema_envelope_has_properties(self, runner: CliRunner) -> None:
        """Envelope schemas should contain properties from Pydantic models."""
        result = runner.invoke(main, ["schema"])
        data = json.loads(result.output)
        # Success envelope should have 'ok', 'command', 'result' fields
        success_props = data["success_envelope"].get("properties", {})
        assert "ok" in success_props
        assert "command" in success_props
        assert "result" in success_props

        # Error envelope should have 'error' field
        error_props = data["error_envelope"].get("properties", {})
        assert "error" in error_props

    def test_schema_contains_known_commands(self, runner: CliRunner) -> None:
        """5.1.11 — Schema contains entries for known commands."""
        result = runner.invoke(main, ["schema"])
        data = json.loads(result.output)
        commands = data["commands"]
        expected = [
            "query",
            "auth login",
            "auth logout",
            "auth status",
            "config set",
            "config show",
            "style set",
            "style show",
            "style clear",
        ]
        for cmd_name in expected:
            assert cmd_name in commands, f"Missing command: {cmd_name}"

    def test_schema_command_entries_have_output_key(self, runner: CliRunner) -> None:
        """5.1.12 — Each command entry has an 'output' key."""
        result = runner.invoke(main, ["schema"])
        data = json.loads(result.output)
        for cmd_name, cmd_info in data["commands"].items():
            assert "output" in cmd_info, f"Command '{cmd_name}' missing 'output' key"

    def test_schema_appears_in_root_help(self, runner: CliRunner) -> None:
        """Schema command should appear in root --help output."""
        result = runner.invoke(main, ["--help"])
        assert "schema" in result.output
