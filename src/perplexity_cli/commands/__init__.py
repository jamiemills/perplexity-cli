"""Click command definitions for the CLI.

This package was split out of the former monolithic ``commands.py`` so each
command family lives in its own module.  Every previously-public name is
re-exported here so existing imports (``from perplexity_cli import commands``
or ``from perplexity_cli.commands import register_commands``) keep working.
"""

from __future__ import annotations

import click

from perplexity_cli.commands._ctx import _ensure_ctx_obj
from perplexity_cli.commands._help_sections import HelpSectionConfig, add_help_sections
from perplexity_cli.commands.auth_cmds import (
    auth_group,
    auth_login,
    auth_logout,
    auth_status,
)
from perplexity_cli.commands.config_cmds import (
    config_group,
    config_set,
    config_show,
)
from perplexity_cli.commands.doctor_cmds import doctor, doctor_security
from perplexity_cli.commands.models_cmds import models_group, models_list
from perplexity_cli.commands.query_cmd import query
from perplexity_cli.commands.schema_cmd import schema_cmd
from perplexity_cli.commands.skill_cmds import skill_group, skill_show
from perplexity_cli.commands.style_cmds import (
    style_clear,
    style_group,
    style_set,
    style_show,
)
from perplexity_cli.commands.threads_cmds import threads_export, threads_group

# Imported after _ensure_ctx_obj is bound to this package so completion_commands
# can resolve ``from perplexity_cli.commands import _ensure_ctx_obj`` while we
# are still loading.
from perplexity_cli.completion_commands import completion_group

__all__ = [
    "HelpSectionConfig",
    "_ensure_ctx_obj",
    "add_help_sections",
    "auth_group",
    "auth_login",
    "auth_logout",
    "auth_status",
    "completion_group",
    "config_group",
    "config_set",
    "config_show",
    "doctor",
    "doctor_security",
    "models_group",
    "models_list",
    "query",
    "register_commands",
    "schema_cmd",
    "skill_group",
    "skill_show",
    "style_clear",
    "style_group",
    "style_set",
    "style_show",
    "threads_export",
    "threads_group",
]


def register_commands(main_group: click.Group) -> None:
    """Attach all command definitions to the root Click group.

    Parameters:
        main_group: The root ``click.Group`` (typically ``cli.main``) that the
            command tree should be mounted under.

    Returns:
        None; the group is mutated in place.
    """
    for cmd in (
        auth_group,
        config_group,
        style_group,
        threads_group,
        skill_group,
        models_group,
        doctor,
        query,
        completion_group,
        schema_cmd,
    ):
        main_group.add_command(cmd)

    # Add exit codes section to the main group help
    add_help_sections(main_group, HelpSectionConfig(exit_codes=True))
