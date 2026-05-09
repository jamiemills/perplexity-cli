"""Backward-compatibility shim.

All command orchestration logic now lives in :mod:`perplexity_cli.runners`.
This module re-exports every public name so that existing ``from
perplexity_cli.command_runner import …`` statements continue to work.
"""

from perplexity_cli.runners import (  # noqa: F401 – re-exports for backward compat
    run_auth_command,
    run_clear_style_command,
    run_configure_command,
    run_doctor_security_command,
    run_export_threads_command,
    run_logout_command,
    run_set_config_command,
    run_show_config_command,
    run_show_skill_command,
    run_status_command,
    run_view_style_command,
)

__all__ = [
    "run_auth_command",
    "run_logout_command",
    "run_configure_command",
    "run_view_style_command",
    "run_clear_style_command",
    "run_set_config_command",
    "run_show_config_command",
    "run_export_threads_command",
    "run_status_command",
    "run_doctor_security_command",
    "run_show_skill_command",
]
