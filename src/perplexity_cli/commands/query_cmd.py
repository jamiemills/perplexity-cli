"""``pxcli query`` root command."""

from __future__ import annotations

import click

from perplexity_cli.commands._ctx import (
    ClickValue,
    as_bool,
    as_int_or_none,
    as_str_or_none,
    as_str_tuple,
)
from perplexity_cli.commands._examples import (
    QUERY_JSON_EXAMPLE,
    QUERY_NDJSON_EXAMPLE,
)
from perplexity_cli.commands._help_refs import (
    AUTH_LOGIN_HELP_REF,
    STYLE_SET_HELP_REF,
)
from perplexity_cli.commands._help_sections import HelpSectionConfig, add_help_sections
from perplexity_cli.commands._runner_adapter import QueryOptions, run_query_command


@click.command()
@click.argument("query_text", metavar="QUERY")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["plain", "markdown", "rich", "json"]),
    default=None,
    help=(
        "Output format for the response.  Defaults to 'rich' when stdout is a "
        "terminal, or 'plain' when piped.  Available formats:\n\n"
        "  plain    - Plain text with underlined section headers.  Clean output "
        "suitable for piping to other commands or saving to .txt files.\n\n"
        "  markdown - GitHub-flavoured Markdown with proper heading levels, "
        "fenced code blocks, and reference links.  Suitable for .md files.\n\n"
        "  rich     - Colourful terminal output with syntax highlighting, "
        "tables, and styled headers.  Best for interactive use.\n\n"
        "  json     - Legacy JSON format (prefer --json flag for the structured "
        "envelope format).  Returns {answer, references} as JSON."
    ),
)
@click.option(
    "--strip-references",
    "-S",
    is_flag=True,
    help=(
        "Remove all inline citation numbers [1], [2], etc. and the references "
        "section from the response.  Useful when you want clean prose without "
        "source attributions, e.g. for embedding in documents or feeding to "
        "other tools."
    ),
)
@click.option(
    "--stream/--no-stream",
    "-s/",
    default=False,
    help=(
        "Enable real-time streaming of the response.  With --stream, text is "
        "printed incrementally as it arrives from the API rather than waiting "
        "for the complete response.  When combined with --json, produces NDJSON "
        "(newline-delimited JSON) output with one event per line: start, chunk, "
        "and result events.  Default: --no-stream (batch mode)."
    ),
)
@click.option(
    "--attach",
    "-a",
    "attachments_str",
    multiple=True,
    help=(
        "Attach file(s) to the query for analysis.  Requires authentication "
        "(run 'pxcli auth login' first).  Supports multiple input methods:\n\n"
        "  Single file:       --attach report.pdf\n\n"
        "  Comma-separated:   --attach 'file1.txt,file2.txt'\n\n"
        "  Directory:         --attach ./docs  (recursive, all files)\n\n"
        "  Repeated flag:     -a file1.txt -a file2.txt\n\n"
        "Files are uploaded to Perplexity.ai and included as context for the "
        "query.  Supported file types include text, PDF, images, and code files."
    ),
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    help=(
        "Emit output as a structured JSON envelope to stdout instead of "
        "human-readable text.  The envelope contains {ok, command, result, meta, "
        "next_actions} on success, or {ok, command, error, fix, next_actions} on "
        "failure.  The result object includes 'answer' (string) and 'references' "
        "(array).  Intended for programmatic consumption by scripts and agents.  "
        "When combined with --stream, produces NDJSON output."
    ),
)
@click.option(
    "--schema",
    "schema_flag",
    is_flag=True,
    help=(
        "Embed the full JSON Schema definition as a $schema key in the JSON "
        "envelope output.  Only effective when --json is also specified; silently "
        "ignored otherwise.  For NDJSON streaming, the schema is included only "
        "in the final result event."
    ),
)
@click.option(
    "--timeout",
    "-t",
    type=int,
    default=None,
    help=(
        "Request timeout in seconds.  If the API does not respond within this "
        "duration, the request is aborted and an error is returned (exit code 6). "
        "Default: 60 seconds for standard queries.  Set a higher value for "
        "complex queries that may take longer to process.  Example: --timeout 120"
    ),
)
@click.option(
    "--model",
    "-m",
    "model_preference",
    type=str,
    default=None,
    help=(
        "Model to use for this query.  Accepts a model identifier string "
        "as returned by 'pxcli models list'.  When not specified, the "
        "default model 'Best' (pplx_pro) is used, which auto-selects the "
        "most appropriate model for the query.\n\n"
        "Examples:\n\n"
        "  --model gpt54           GPT-5.4\n\n"
        "  --model claude46sonnet  Claude Sonnet 4.6\n\n"
        "  -m experimental         Sonar 2\n\n"
        "Run 'pxcli models list' to see available models for your "
        "subscription tier."
    ),
)
@click.option(
    "--request-param",
    "request_param_overrides",
    type=str,
    multiple=True,
    help=(
        "Experimental: inject an extra key=value pair into the outbound "
        "request params.  Repeat for multiple fields.  Intended for private "
        "API investigation only.  Example: --request-param workflow_key=deep_research"
    ),
)
@click.pass_context
def query(ctx: click.Context, query_text: str, **params: ClickValue) -> None:
    """Submit a query to Perplexity.ai and get an answer.

    Sends a natural-language question to Perplexity.ai and returns the
    answer along with source references.  Works with or without
    authentication; authentication is only required when using file
    attachments (--attach).

    The response is printed to stdout, making it straightforward to pipe to
    other commands, redirect to files, or parse programmatically.  By
    default, responses are fetched in batch mode (the complete answer is
    displayed after the API finishes).  Use --stream for real-time
    incremental output.

    \b
    OUTPUT FORMATS:
      plain    - Plain text with underlined headers (good for scripts)
      markdown - GitHub-flavoured Markdown with proper structure
      rich     - Colourful terminal output with tables (default for TTY)
      json     - Legacy JSON format; prefer --json for the envelope format

    \b
    JSON ENVELOPE (--json):
      The --json flag produces a structured envelope:
        {ok, command, result, meta, next_actions}
      where result contains:
        {answer: string, references: [{index, title, url, snippet}, ...]}

    \b
    NDJSON STREAMING (--json --stream):
      When --json and --stream are combined, output is newline-delimited
      JSON (NDJSON).  Each line is a typed event:
        start   - Emitted when the query begins
        chunk   - Emitted for each piece of streamed text
        result  - Final line containing the complete envelope

    \b
    FILE ATTACHMENTS (--attach):
      Attach files for Perplexity.ai to analyse alongside your query.
      Requires authentication.  Supports:
        --attach file.txt             Single file
        --attach file1.txt,file2.txt  Comma-separated files
        --attach ./directory          All files recursively
        -a file1.txt -a file2.txt     Repeated flags

    \b
    Examples:
        pxcli query "What is Python?"
        pxcli query "What is the capital of France?" > answer.txt
        pxcli query --format plain "What is Python?"
        pxcli query --format markdown "Explain Docker" > docker.md
        pxcli query --strip-references "What is Python?"
        pxcli query -f plain -S "What is Python?"
        pxcli query --stream "What is Python?"
        pxcli query -s "What is Python?"
        pxcli query --json "What is Python?"
        pxcli query --json "What is Python?" | jq -r '.result.answer'
        pxcli query --json --stream "What is Python?"
        pxcli query --json --schema "What is Python?"
        pxcli query --attach README.md "What is this project?"
        pxcli query --attach config.json,data.txt "Analyse these files"
        pxcli query --attach ./docs "Summarise all documentation"
        pxcli query --timeout 120 "Complex research question"
        pxcli query --model gpt54 "What is Python?"
        pxcli query -m claude46sonnet "Explain Docker"

    \b
    Example Output (rich, default):
        Python
        ======
        Python is a high-level, general-purpose programming language
        created by Guido van Rossum and first released in 1991 [1].
        ...

    References:
        ----------
        [1] Python (programming language) - Wikipedia
            https://en.wikipedia.org/wiki/Python_(programming_language)

    \b
    JSON format tip: Use jq -r to render newlines properly:
        pxcli query --json "Question" | jq -r '.result.answer'
    """
    ctx.ensure_object(dict)
    ctx.obj["json"] = params.get("json_flag") is True
    ctx.obj["schema"] = params.get("schema_flag") is True
    ctx.obj["timeout"] = as_int_or_none(params.get("timeout"))
    options = QueryOptions(
        output_format=as_str_or_none(params.get("output_format")),
        strip_references=as_bool(params.get("strip_references")),
        stream=as_bool(params.get("stream")),
        attachments=as_str_tuple(params.get("attachments_str")),
        model_preference=as_str_or_none(params.get("model_preference")),
        request_param_overrides=as_str_tuple(params.get("request_param_overrides")),
    )
    run_query_command(ctx.obj, query_text, options)


add_help_sections(
    query,
    HelpSectionConfig(
        json_example=QUERY_JSON_EXAMPLE,
        ndjson_example=QUERY_NDJSON_EXAMPLE,
        json_schema=True,
        exit_codes=True,
        see_also=(
            AUTH_LOGIN_HELP_REF,
            "pxcli config show",
            STYLE_SET_HELP_REF,
            "pxcli schema",
        ),
        env_vars=("PERPLEXITY_BASE_URL", "NO_COLOR", "XDG_CONFIG_HOME", "PERPLEXITY_CONFIG_DIR"),
    ),
)
