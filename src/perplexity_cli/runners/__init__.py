"""Runner sub-package: domain-specific command orchestration helpers.

Each module owns one bounded context (auth, config, export, status, skill)
with a standardised error-handling envelope.
"""

from perplexity_cli.runners.auth import run_auth_command, run_logout_command
from perplexity_cli.runners.config import (
    run_clear_style_command,
    run_configure_command,
    run_set_config_command,
    run_show_config_command,
    run_view_style_command,
)
from perplexity_cli.runners.export import run_export_threads_command
from perplexity_cli.runners.skill import run_show_skill_command
from perplexity_cli.runners.status import run_doctor_security_command, run_status_command

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
