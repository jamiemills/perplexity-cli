"""Streaming query response handler.

This module contains the logic for streaming query responses from the
Perplexity API in real-time, extracted from cli.py for independent testability.
"""

import sys

import click
from click import ClickException

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import Answer, WebResult
from perplexity_cli.formatting.base import Formatter
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    UpstreamSchemaError,
)
from perplexity_cli.utils.http_errors import (
    handle_http_error,
    handle_network_error,
    handle_unexpected_cli_error,
)
from perplexity_cli.utils.logging import get_logger


def stream_query_response(
    api: PerplexityAPI,
    query: str,
    formatter: Formatter,
    output_format: str,
    strip_references: bool,
    attachments: list[str] | None = None,
) -> None:
    """Stream query response in real-time.

    Args:
        api: PerplexityAPI instance.
        query: Query text.
        formatter: Formatter instance.
        output_format: Output format name.
        strip_references: Whether to strip references.
        attachments: Optional list of S3 URLs for file attachments.
    """
    logger = get_logger()
    accumulated_text = ""
    references: list[WebResult] = []

    try:
        for message in api.submit_query(query, attachments=attachments):
            logger.debug(
                f"Received SSE message: status={message.status}, final={message.final_sse_message}"
            )

            text = message.extract_answer_text()
            if text and text != accumulated_text:
                # Only print new text
                new_text = text[len(accumulated_text) :]
                if new_text:
                    if output_format == "rich":
                        # For rich, print incrementally
                        click.echo(new_text, nl=False)
                    else:
                        click.echo(new_text, nl=False)
                    accumulated_text = text

            # Extract references from final message
            if message.final_sse_message and message.web_results:
                references = message.web_results
                logger.debug(f"Extracted {len(references)} references")

        # Print newline after streaming
        click.echo()

        # Print references if not stripped
        if references and not strip_references:
            click.echo()
            if output_format == "rich":
                formatter.render_complete(
                    Answer(text=accumulated_text, references=references),
                    strip_references=True,  # Already printed text
                )
            else:
                formatted_refs = formatter.format_references(references)
                if formatted_refs:
                    click.echo(formatted_refs)

    except PerplexityHTTPStatusError as e:
        click.echo()  # Newline after streamed content
        handle_http_error(e, logger, debug_mode=False, context="during streaming")

    except PerplexityRequestError as e:
        click.echo()  # Newline after streamed content
        handle_network_error(e, logger, debug_mode=False, context="during streaming")

    except UpstreamSchemaError as e:
        logger.error(f"Malformed upstream response during streaming: {e}")
        click.echo()  # Newline after streamed content
        click.echo(f"[ERROR] Upstream response format changed: {e}", err=True)
        sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Streaming interrupted by user")
        click.echo("\n[ERROR] Streaming interrupted.", err=True)
        sys.exit(130)

    except (ClickException, OSError) as e:
        logger.error(f"Streaming output failed: {e}")
        click.echo()  # Newline after streamed content
        click.echo(f"[ERROR] Failed to render streaming output: {e}", err=True)
        sys.exit(1)

    except Exception as e:
        click.echo()  # Newline after streamed content
        handle_unexpected_cli_error(
            e,
            logger,
            user_message="[ERROR] An unexpected error occurred.",
            log_message="Unexpected error during streaming",
            include_debug_hint=True,
        )
