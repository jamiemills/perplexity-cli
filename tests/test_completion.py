"""Tests for shell completion command group (spec 5.1.7-5.1.9)."""

from click.testing import CliRunner

from perplexity_cli.cli import main


class TestCompletionCommands:
    """Test shell completion script generation."""

    def test_completion_bash_exits_zero_with_output(self, runner: CliRunner) -> None:
        """5.1.7 — pxcli completion bash exits 0 and produces non-empty output."""
        result = runner.invoke(main, ["completion", "bash"])
        assert result.exit_code == 0
        assert len(result.output.strip()) > 0

    def test_completion_bash_contains_function_name(self, runner: CliRunner) -> None:
        """Bash completion script should define the completion function."""
        result = runner.invoke(main, ["completion", "bash"])
        assert "_pxcli_completion" in result.output
        assert "complete" in result.output

    def test_completion_zsh_exits_zero_with_output(self, runner: CliRunner) -> None:
        """5.1.8 — pxcli completion zsh exits 0 and produces non-empty output."""
        result = runner.invoke(main, ["completion", "zsh"])
        assert result.exit_code == 0
        assert len(result.output.strip()) > 0

    def test_completion_zsh_contains_compdef(self, runner: CliRunner) -> None:
        """Zsh completion script should contain compdef directive."""
        result = runner.invoke(main, ["completion", "zsh"])
        assert "compdef" in result.output

    def test_completion_fish_exits_zero_with_output(self, runner: CliRunner) -> None:
        """5.1.9 — pxcli completion fish exits 0 and produces non-empty output."""
        result = runner.invoke(main, ["completion", "fish"])
        assert result.exit_code == 0
        assert len(result.output.strip()) > 0

    def test_completion_fish_contains_complete_command(self, runner: CliRunner) -> None:
        """Fish completion script should contain the complete command."""
        result = runner.invoke(main, ["completion", "fish"])
        assert "complete" in result.output
        assert "pxcli" in result.output

    def test_completion_group_help(self, runner: CliRunner) -> None:
        """Completion group --help should list subcommands."""
        result = runner.invoke(main, ["completion", "--help"])
        assert result.exit_code == 0
        assert "bash" in result.output
        assert "zsh" in result.output
        assert "fish" in result.output

    def test_completion_appears_in_root_help(self, runner: CliRunner) -> None:
        """Completion group should appear in root --help output."""
        result = runner.invoke(main, ["--help"])
        assert "completion" in result.output
