"""Public Click-boundary tests for the query command."""

from unittest.mock import patch

from perplexity_cli._types import QueryOptions
from perplexity_cli.commands.query_cmd import query


def test_query_command_maps_all_options_to_runner(runner):
    """Click converts query flags into the runner's typed option bundle."""
    with patch("perplexity_cli.commands.query_cmd.run_query_command") as run_query:
        result = runner.invoke(
            query,
            [
                "--format",
                "markdown",
                "--strip-references",
                "--stream",
                "--attach",
                "first.txt",
                "--attach",
                "second.txt",
                "--json",
                "--schema",
                "--timeout",
                "45",
                "--model",
                "sonar-pro",
                "--request-param",
                "workflow_key=deep_research",
                "--request-param",
                "search_mode=research",
                "What is Python?",
            ],
        )

    assert result.exit_code == 0
    run_query.assert_called_once_with(
        {"json": True, "schema": True, "timeout": 45},
        "What is Python?",
        QueryOptions(
            output_format="markdown",
            strip_references=True,
            stream=True,
            attachments=("first.txt", "second.txt"),
            model_preference="sonar-pro",
            request_param_overrides=("workflow_key=deep_research", "search_mode=research"),
        ),
    )


def test_query_command_defaults_to_batch_without_optional_flags(runner):
    """Omitted flags produce the documented neutral option values."""
    with patch("perplexity_cli.commands.query_cmd.run_query_command") as run_query:
        result = runner.invoke(query, ["What is Python?"])

    assert result.exit_code == 0
    run_query.assert_called_once_with(
        {"json": False, "schema": False, "timeout": None},
        "What is Python?",
        QueryOptions(),
    )


def test_query_command_rejects_unknown_output_format(runner):
    """The public command rejects formats outside the advertised choices."""
    result = runner.invoke(query, ["--format", "xml", "question"])

    assert result.exit_code == 2
    assert "Invalid value for '--format'" in result.output
