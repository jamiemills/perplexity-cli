"""CLI tests for the models command group.

Validates the Click integration for ``pxcli models list`` and the
``--model`` flag on the query command, using the Click CliRunner.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from perplexity_cli.cli import main
from perplexity_cli.models.model_config import (
    ModelConfigEntry,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_entries() -> list[ModelConfigEntry]:
    """Return accessible model entries for testing."""
    return [
        ModelConfigEntry(
            label="Best",
            description="Auto-select",
            subscription_tier="pro",
            non_reasoning_model="pplx_pro",
            is_default=True,
        ),
        ModelConfigEntry(
            label="GPT-5.4",
            description="OpenAI GPT-5.4",
            subscription_tier="pro",
            non_reasoning_model="gpt54",
            reasoning_model="gpt54_thinking",
        ),
        ModelConfigEntry(
            label="GPT-5.5",
            description="OpenAI GPT-5.5",
            subscription_tier="max",
            non_reasoning_model="gpt55",
        ),
    ]


# ---------------------------------------------------------------------------
# Tests: models group appears in help
# ---------------------------------------------------------------------------


class TestModelsGroupHelp:
    """Tests that the models group is registered and accessible."""

    def test_models_in_main_help(self, runner) -> None:
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "models" in result.output

    def test_models_group_help(self, runner) -> None:
        result = runner.invoke(main, ["models", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output

    def test_models_list_help(self, runner) -> None:
        result = runner.invoke(main, ["models", "list", "--help"])
        assert result.exit_code == 0
        assert "--json" in result.output
        assert "--schema" in result.output


# ---------------------------------------------------------------------------
# Tests: models list command
# ---------------------------------------------------------------------------


class TestModelsListCommand:
    """Tests for the models list CLI command."""

    def test_list_outputs_table(
        self,
        runner,
        sample_entries: list[ModelConfigEntry],
    ) -> None:
        with patch(
            "perplexity_cli.runners.models.run_models_list_command",
        ) as mock_run:
            result = runner.invoke(main, ["models", "list"])

        assert result.exit_code == 0
        mock_run.assert_called_once()
        # Verify ctx_obj was passed
        call_args = mock_run.call_args
        ctx_obj = call_args[0][0]
        assert ctx_obj["json"] is False

    def test_list_json_flag(
        self,
        runner,
        sample_entries: list[ModelConfigEntry],
    ) -> None:
        with patch(
            "perplexity_cli.runners.models.run_models_list_command",
        ) as mock_run:
            result = runner.invoke(main, ["models", "list", "--json"])

        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        ctx_obj = call_args[0][0]
        assert ctx_obj["json"] is True

    def test_list_schema_flag(
        self,
        runner,
        sample_entries: list[ModelConfigEntry],
    ) -> None:
        with patch(
            "perplexity_cli.runners.models.run_models_list_command",
        ) as mock_run:
            result = runner.invoke(main, ["models", "list", "--json", "--schema"])

        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        ctx_obj = call_args[0][0]
        assert ctx_obj["schema"] is True


# ---------------------------------------------------------------------------
# Tests: --model flag on query command
# ---------------------------------------------------------------------------


class TestQueryModelFlag:
    """Tests for the --model / -m flag on the query command."""

    def test_model_flag_passed_to_runner(self, runner) -> None:
        with patch(
            "perplexity_cli.query_runner.run_query_command",
        ) as mock_run:
            result = runner.invoke(
                main,
                ["query", "--model", "gpt54", "What is Python?"],
            )

        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["model_preference"] == "gpt54"

    def test_model_short_flag(self, runner) -> None:
        with patch(
            "perplexity_cli.query_runner.run_query_command",
        ) as mock_run:
            result = runner.invoke(
                main,
                ["query", "-m", "claude46sonnet", "Explain Docker"],
            )

        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["model_preference"] == "claude46sonnet"

    def test_no_model_flag_passes_none(self, runner) -> None:
        with patch(
            "perplexity_cli.query_runner.run_query_command",
        ) as mock_run:
            result = runner.invoke(
                main,
                ["query", "What is Python?"],
            )

        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["model_preference"] is None
