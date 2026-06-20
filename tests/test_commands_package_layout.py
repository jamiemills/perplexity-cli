"""Golden help-output and public-surface tests for the ``commands`` package.

These tests pin the user-visible CLI surface and the public Python API of
``perplexity_cli.commands`` so that the file-split refactor (P0.2) cannot
regress behaviour.  They are intended to pass against the original monolithic
``commands.py`` AND against the new ``commands/`` package layout.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from perplexity_cli import commands as cmds
from perplexity_cli.cli import main


@pytest.fixture
def runner() -> CliRunner:
    """Create a Click CLI test runner."""
    return CliRunner()


# ---------------------------------------------------------------------------
# Golden help output: each group / root command must keep its subcommand set
# ---------------------------------------------------------------------------

_ROOT_CASES: dict[str, list[str]] = {
    "": [
        "auth",
        "completion",
        "config",
        "doctor",
        "models",
        "query",
        "schema",
        "skill",
        "style",
        "threads",
    ],
    "auth": ["login", "logout", "status"],
    "config": ["set", "show"],
    "style": ["set", "show", "clear"],
    "threads": ["export"],
    "skill": ["show"],
    "doctor": ["security"],
    "models": ["list"],
}


@pytest.mark.parametrize("group,expected", list(_ROOT_CASES.items()))
def test_help_lists_expected_subcommands(
    runner: CliRunner, group: str, expected: list[str]
) -> None:
    """Each group's --help output must list its expected subcommand names."""
    args = [group, "--help"] if group else ["--help"]
    result = runner.invoke(main, args)
    assert result.exit_code == 0
    for name in expected:
        assert name in result.output, f"missing {name!r} in {group!r} --help"


@pytest.mark.parametrize(
    "args",
    [
        ["query", "--help"],
        ["schema", "--help"],
    ],
)
def test_root_command_help_exits_zero(runner: CliRunner, args: list[str]) -> None:
    """Root-level commands must continue to expose --help."""
    result = runner.invoke(main, args)
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Public Python API: every previously-public name must remain importable
# ---------------------------------------------------------------------------

_PUBLIC_COMMAND_NAMES = [
    "auth_group",
    "auth_login",
    "auth_logout",
    "auth_status",
    "config_group",
    "config_set",
    "config_show",
    "style_group",
    "style_set",
    "style_show",
    "style_clear",
    "threads_group",
    "threads_export",
    "skill_group",
    "skill_show",
    "doctor",
    "doctor_security",
    "query",
    "models_group",
    "models_list",
    "schema_cmd",
    "register_commands",
]


@pytest.mark.parametrize("name", _PUBLIC_COMMAND_NAMES)
def test_commands_module_exposes_public_name(name: str) -> None:
    """Every previously-public def must remain accessible on the package."""
    assert hasattr(cmds, name), f"perplexity_cli.commands.{name} missing"


def test_commands_module_exposes_ensure_ctx_obj() -> None:
    """The private helper used by completion_commands must remain importable."""
    assert hasattr(cmds, "_ensure_ctx_obj")


def test_register_commands_attaches_all_groups_to_fresh_main() -> None:
    """register_commands must attach the full command set to a fresh group."""
    import click

    fresh = click.Group(name="fresh")
    cmds.register_commands(fresh)
    command_names = set(fresh.commands)
    expected = {
        "auth",
        "config",
        "style",
        "threads",
        "skill",
        "models",
        "doctor",
        "query",
        "completion",
        "schema",
    }
    assert expected <= command_names
