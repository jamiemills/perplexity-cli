"""Coverage gap tests: Click command bodies in skill_cmds and style_cmds."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from perplexity_cli.commands.skill_cmds import skill_group, skill_show
from perplexity_cli.commands.style_cmds import style_clear, style_group, style_set, style_show


class TestSkillGroup:
    def test_group_show_invokes_runner(self, runner: CliRunner) -> None:
        with patch("perplexity_cli.runners.run_show_skill_command") as mock_run:
            result = runner.invoke(skill_group, ["show"])
            assert result.exit_code == 0
            mock_run.assert_called_once()


class TestSkillShowCommand:
    def test_cli_invokes_runner(self, runner: CliRunner) -> None:
        with patch("perplexity_cli.runners.run_show_skill_command") as mock_run:
            result = runner.invoke(skill_show)
            assert result.exit_code == 0
            mock_run.assert_called_once()

    def test_json_flag_invokes_runner(self, runner: CliRunner) -> None:
        with patch("perplexity_cli.runners.run_show_skill_command") as mock_run:
            result = runner.invoke(skill_show, ["--json"])
            assert result.exit_code == 0
            mock_run.assert_called_once()


class TestStyleGroup:
    def test_group_set_invokes_runner(self, runner: CliRunner) -> None:
        with patch("perplexity_cli.runners.run_configure_command") as mock_run:
            result = runner.invoke(style_group, ["set", "be brief"])
            assert result.exit_code == 0
            mock_run.assert_called_once_with("be brief")


class TestStyleCommands:
    def test_style_set_invokes_runner(self, runner: CliRunner) -> None:
        with patch("perplexity_cli.runners.run_configure_command") as mock_run:
            result = runner.invoke(style_set, ["be brief"])
            assert result.exit_code == 0
            mock_run.assert_called_once_with("be brief")

    def test_style_show_invokes_runner(self, runner: CliRunner) -> None:
        with patch("perplexity_cli.runners.run_view_style_command") as mock_run:
            result = runner.invoke(style_show)
            assert result.exit_code == 0
            mock_run.assert_called_once()

    def test_style_clear_invokes_runner(self, runner: CliRunner) -> None:
        with patch("perplexity_cli.runners.run_clear_style_command") as mock_run:
            result = runner.invoke(style_clear)
            assert result.exit_code == 0
            mock_run.assert_called_once()
