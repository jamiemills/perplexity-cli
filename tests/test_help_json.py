"""Tests for the help_json module."""

import click

from perplexity_cli.help_json import build_help_json


@click.group()
def sample_group():
    """Sample group help."""


@sample_group.command()
@click.option("--verbose", is_flag=True, help="Enable verbose output")
@click.argument("name")
def greet(verbose, name):
    """Greet someone."""


@sample_group.group()
def sub():
    """Sub-group help."""


@sub.command()
def leaf():
    """Leaf command help."""


class TestBuildHelpJson:
    def test_returns_dict(self):
        result = build_help_json(sample_group)
        assert isinstance(result, dict)

    def test_contains_version(self):
        result = build_help_json(sample_group, version="1.2.3")
        assert result["version"] == "1.2.3"

    def test_contains_commands(self):
        result = build_help_json(sample_group)
        assert "commands" in result
        assert isinstance(result["commands"], dict)

    def test_leaf_command_has_help(self):
        result = build_help_json(sample_group)
        assert result["commands"]["greet"]["help"] == "Greet someone."

    def test_leaf_command_has_options(self):
        result = build_help_json(sample_group)
        options = result["commands"]["greet"]["options"]
        assert isinstance(options, list)
        names = [o["name"] for o in options]
        assert "--verbose" in names

    def test_leaf_command_has_arguments(self):
        result = build_help_json(sample_group)
        arguments = result["commands"]["greet"]["arguments"]
        assert isinstance(arguments, list)
        names = [a["name"] for a in arguments]
        assert "name" in names

    def test_group_has_nested_commands(self):
        result = build_help_json(sample_group)
        sub_entry = result["commands"]["sub"]
        assert "commands" in sub_entry
        assert "leaf" in sub_entry["commands"]

    def test_group_preserves_help_and_sorted_nested_command_contract(self):
        result = build_help_json(sample_group)

        assert result["commands"]["sub"] == {
            "help": "Sub-group help.",
            "commands": {
                "leaf": {
                    "help": "Leaf command help.",
                    "options": [],
                    "arguments": [],
                }
            },
        }

    def test_empty_group_help_is_an_empty_string(self):
        empty_group = click.Group(name="empty")
        group = click.Group(commands={"empty": empty_group})

        assert build_help_json(group) == {"commands": {"empty": {"help": "", "commands": {}}}}

    def test_option_info_includes_name_and_type(self):
        result = build_help_json(sample_group)
        options = result["commands"]["greet"]["options"]
        verbose_opt = next(o for o in options if o["name"] == "--verbose")
        for key in ("name", "type", "required", "help"):
            assert key in verbose_opt

    def test_help_json_preserves_option_contract(self):
        result = build_help_json(sample_group)
        option = next(
            option
            for option in result["commands"]["greet"]["options"]
            if option["name"] == "--verbose"
        )
        assert option == {
            "name": "--verbose",
            "type": "boolean",
            "required": False,
            "help": "Enable verbose output",
        }

    def test_help_json_preserves_argument_contract(self):
        result = build_help_json(sample_group)
        assert result["commands"]["greet"]["arguments"] == [{"name": "name", "required": True}]

    def test_help_json_preserves_option_fallback_contract(self):
        option = click.Option(["--fallback"], help=None)
        option.type = None

        @click.command(params=[option])
        def fallback():
            pass

        group = click.Group(commands={"fallback": fallback})
        result = build_help_json(group)

        assert result["commands"]["fallback"]["options"] == [
            {
                "name": "--fallback",
                "type": "STRING",
                "required": False,
                "help": "",
            }
        ]

    def test_help_json_preserves_empty_help_and_sorted_commands(self):
        @click.command("z-command")
        def z_command():
            pass

        @click.command("a-command")
        def a_command():
            pass

        group = click.Group(commands={"z-command": z_command, "a-command": a_command})
        result = build_help_json(group)
        assert list(result["commands"]) == ["a-command", "z-command"]
        assert result["commands"]["a-command"] == {
            "help": "",
            "options": [],
            "arguments": [],
        }
