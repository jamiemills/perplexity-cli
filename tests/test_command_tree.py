"""Tests for the noun-verb command tree structure."""

import pytest

from perplexity_cli.cli import main


class TestCommandGroups:
    """Test that all command groups are invocable."""

    @pytest.mark.parametrize("group", ["auth", "config", "style", "threads", "skill"])
    def test_group_help_exits_zero(self, runner, group):
        result = runner.invoke(main, [group, "--help"])
        assert result.exit_code == 0

    def test_doctor_group_help(self, runner):
        result = runner.invoke(main, ["doctor", "--help"])
        assert result.exit_code == 0


class TestSubcommands:
    """Test that all subcommands are invocable."""

    @pytest.mark.parametrize(
        "args",
        [
            ["auth", "login", "--help"],
            ["auth", "logout", "--help"],
            ["auth", "status", "--help"],
            ["config", "set", "--help"],
            ["config", "show", "--help"],
            ["style", "set", "--help"],
            ["style", "show", "--help"],
            ["style", "clear", "--help"],
            ["threads", "export", "--help"],
            ["skill", "show", "--help"],
            ["doctor", "security", "--help"],
            ["query", "--help"],
        ],
    )
    def test_subcommand_help_exits_zero(self, runner, args):
        result = runner.invoke(main, args)
        assert result.exit_code == 0


class TestOldCommandsRemoved:
    """Test that old flat command names are gone."""

    @pytest.mark.parametrize(
        "old_cmd",
        [
            "logout",
            "status",
            "set-config",
            "show-config",
            "configure",
            "view-style",
            "clear-style",
            "export-threads",
            "show-skill",
        ],
    )
    def test_old_command_exits_with_usage_error(self, runner, old_cmd):
        result = runner.invoke(main, [old_cmd])
        assert result.exit_code == 2


class TestRootHelp:
    """Test root --help output."""

    def test_root_help_lists_groups(self, runner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        for name in ("auth", "config", "style", "threads", "doctor", "skill", "query"):
            assert name in result.output

    def test_root_help_omits_old_commands(self, runner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        # Check the Commands section specifically - old flat commands should not appear
        # as top-level commands. We split on "Commands:" to check only the command listing.
        output = result.output
        commands_section = output.split("Commands:")[-1] if "Commands:" in output else output
        for old in (
            "set-config",
            "show-config",
            "configure",
            "view-style",
            "clear-style",
            "export-threads",
            "show-skill",
        ):
            assert old not in commands_section


class TestFlagStubs:
    """Test new flag stubs are accepted."""

    def test_json_on_query_help(self, runner):
        result = runner.invoke(main, ["query", "--help"])
        assert "--json" in result.output

    def test_short_stream_flag(self, runner):
        result = runner.invoke(main, ["query", "--help"])
        assert "-s" in result.output

    def test_short_strip_references_flag(self, runner):
        result = runner.invoke(main, ["query", "--help"])
        assert "-S" in result.output

    def test_timeout_on_query_help(self, runner):
        result = runner.invoke(main, ["query", "--help"])
        assert "--timeout" in result.output

    def test_quiet_on_main_help(self, runner):
        result = runner.invoke(main, ["--help"])
        assert "--quiet" in result.output

    def test_no_color_on_main_help(self, runner):
        result = runner.invoke(main, ["--help"])
        assert "--no-color" in result.output

    def test_short_output_on_threads_export(self, runner):
        result = runner.invoke(main, ["threads", "export", "--help"])
        assert "-o" in result.output

    def test_short_port_on_auth_login(self, runner):
        result = runner.invoke(main, ["auth", "login", "--help"])
        assert "-p" in result.output
