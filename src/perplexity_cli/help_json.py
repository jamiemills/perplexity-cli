"""Build a machine-readable JSON representation of CLI help from a Click group."""

from __future__ import annotations

from typing import Any

import click


def build_help_json(group: click.Group, version: str | None = None) -> dict[str, Any]:
    """Build machine-readable JSON help from a Click group.

    Args:
        group: The root Click group to extract help from.
        version: Optional version string to include.

    Returns:
        Dictionary suitable for JSON serialisation containing command
        hierarchy, options, and arguments.
    """
    result: dict[str, Any] = {}
    if version is not None:
        result["version"] = version
    result["commands"] = {
        name: _extract_command_info(cmd) for name, cmd in sorted(group.commands.items())
    }
    return result


def _extract_group_info(cmd: click.Group) -> dict[str, Any]:
    """Extract help info from a Click group command.

    Args:
        cmd: The Click group to extract info from.

    Returns:
        Dictionary with help text and nested subcommands.
    """
    return {
        "help": cmd.help or "",
        "commands": {
            name: _extract_command_info(sub) for name, sub in sorted(cmd.commands.items())
        },
    }


def _extract_options(cmd: click.Command) -> list[dict[str, Any]]:
    """Extract option info from a Click command's parameters."""
    return [_extract_option_info(p) for p in cmd.params if isinstance(p, click.Option)]


def _extract_arguments(cmd: click.Command) -> list[dict[str, Any]]:
    """Extract argument info from a Click command's parameters."""
    return [_extract_argument_info(p) for p in cmd.params if isinstance(p, click.Argument)]


def _extract_leaf_command_info(cmd: click.Command) -> dict[str, Any]:
    """Extract help info from a leaf (non-group) Click command.

    Args:
        cmd: The Click command to extract info from.

    Returns:
        Dictionary with help text, options, and arguments.
    """
    return {
        "help": cmd.help or "",
        "options": _extract_options(cmd),
        "arguments": _extract_arguments(cmd),
    }


def _extract_command_info(cmd: click.Command) -> dict[str, Any]:
    """Extract help info from a single Click command."""
    if isinstance(cmd, click.Group):
        return _extract_group_info(cmd)
    return _extract_leaf_command_info(cmd)


def _extract_option_info(param: click.Option) -> dict[str, Any]:
    """Extract info from a Click option parameter."""
    type_name = param.type.name if param.type else "STRING"
    return {
        "name": param.opts[0] if param.opts else param.name,
        "type": type_name,
        "required": param.required,
        "help": param.help or "",
    }


def _extract_argument_info(param: click.Argument) -> dict[str, Any]:
    """Extract info from a Click argument parameter."""
    return {
        "name": param.name,
        "required": param.required,
    }
