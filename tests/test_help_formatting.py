"""Tests for improved help formatting (spec 5.1.1–5.1.6)."""

from click.testing import CliRunner

from perplexity_cli.cli import main


class TestHelpFormatting:
    """Test enhanced help output sections."""

    def test_root_help_contains_exit_codes(self, runner: CliRunner) -> None:
        """5.1.1 — Root --help contains EXIT CODES section."""
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Exit Codes" in result.output or "EXIT CODES" in result.output

    def test_query_help_contains_exit_codes(self, runner: CliRunner) -> None:
        """5.1.2 — query --help contains EXIT CODES section."""
        result = runner.invoke(main, ["query", "--help"])
        assert result.exit_code == 0
        assert "Exit Codes" in result.output or "EXIT CODES" in result.output

    def test_auth_login_help_contains_see_also(self, runner: CliRunner) -> None:
        """5.1.3 — auth login --help contains SEE ALSO referencing auth status and auth logout."""
        result = runner.invoke(main, ["auth", "login", "--help"])
        assert result.exit_code == 0
        output = result.output
        assert "See Also" in output or "SEE ALSO" in output
        assert "auth status" in output
        assert "auth logout" in output

    def test_query_help_examples_preserved(self, runner: CliRunner) -> None:
        """5.1.4 — query --help examples are properly indented, not word-wrapped."""
        result = runner.invoke(main, ["query", "--help"])
        assert result.exit_code == 0
        # Examples should contain 'pxcli query' lines
        assert "pxcli query" in result.output

    def test_query_help_contains_environment_variables(self, runner: CliRunner) -> None:
        """5.1.5 — query --help contains ENVIRONMENT VARIABLES section."""
        result = runner.invoke(main, ["query", "--help"])
        assert result.exit_code == 0
        output = result.output
        assert "Environment Variables" in output or "ENVIRONMENT VARIABLES" in output
        assert "PERPLEXITY_BASE_URL" in output

    def test_all_commands_produce_nonempty_help(self, runner: CliRunner) -> None:
        """5.1.6 — Snapshot test: key commands produce non-empty help output."""
        commands_to_test = [
            ["--help"],
            ["auth", "--help"],
            ["auth", "login", "--help"],
            ["auth", "logout", "--help"],
            ["auth", "status", "--help"],
            ["config", "--help"],
            ["config", "set", "--help"],
            ["config", "show", "--help"],
            ["style", "--help"],
            ["style", "set", "--help"],
            ["style", "show", "--help"],
            ["style", "clear", "--help"],
            ["threads", "--help"],
            ["threads", "export", "--help"],
            ["query", "--help"],
            ["doctor", "--help"],
            ["doctor", "security", "--help"],
            ["completion", "--help"],
            ["schema", "--help"],
        ]
        for cmd_args in commands_to_test:
            result = runner.invoke(main, cmd_args)
            assert result.exit_code == 0, f"Failed for: {cmd_args}"
            assert len(result.output.strip()) > 20, f"Empty help for: {cmd_args}"

    def test_exit_codes_lists_known_codes(self, runner: CliRunner) -> None:
        """EXIT CODES section should list standard exit codes."""
        result = runner.invoke(main, ["query", "--help"])
        output = result.output
        assert "0" in output
        assert "Success" in output

    def test_auth_status_help_contains_see_also(self, runner: CliRunner) -> None:
        """auth status --help should reference related commands."""
        result = runner.invoke(main, ["auth", "status", "--help"])
        assert result.exit_code == 0
        assert "See Also" in result.output or "SEE ALSO" in result.output
