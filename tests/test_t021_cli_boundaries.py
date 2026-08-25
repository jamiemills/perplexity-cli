"""Public-boundary tests for the T021 CLI remainder."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import click
from click.testing import CliRunner

from perplexity_cli._types import QueryOptions
from perplexity_cli.commands import register_commands
from perplexity_cli.commands._runner_adapter import (
    ExportRequest,
    run_auth_command,
    run_export_threads_command,
    run_query_command,
)


def test_register_commands_adds_each_root_command_once() -> None:
    group = click.Group(name="test")
    register_commands(group)
    assert set(group.commands) == {
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


def test_register_commands_adds_exit_codes_to_root_help() -> None:
    group = click.Group(name="test")
    register_commands(group)

    output = CliRunner().invoke(group, ["--help"])

    assert output.exit_code == 0
    assert "Exit Codes" in output.output
    assert "Authentication required" in output.output


def test_auth_adapter_forwards_context_and_port() -> None:
    with patch("perplexity_cli.commands._runner_adapter.importlib.import_module") as importer:
        runner = Mock()
        importer.return_value = runner
        ctx = {"debug": True}
        run_auth_command(ctx, 9333)
    runner.run_auth_command.assert_called_once_with(ctx, 9333)


def test_export_adapter_forwards_every_request_field() -> None:
    request = ExportRequest("2025-01-01", "2025-01-31", Path("out.csv"), True, False)
    with patch("perplexity_cli.commands._runner_adapter.importlib.import_module") as importer:
        runner = Mock()
        importer.return_value = runner
        run_export_threads_command({"json": True}, request)
    runner.run_export_threads_command.assert_called_once_with(
        {"json": True}, "2025-01-01", "2025-01-31", Path("out.csv"), True, False
    )


def test_query_adapter_forwards_query_options() -> None:
    options = Mock(spec=QueryOptions)
    with patch("perplexity_cli.commands._runner_adapter.importlib.import_module") as importer:
        runner = Mock()
        importer.return_value = runner
        ctx = {"json": True}
        run_query_command(ctx, "question", options)
    runner.run_query_command.assert_called_once_with(ctx, "question", options)
