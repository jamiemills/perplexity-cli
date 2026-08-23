"""Behavioural tests for ``perplexity_cli.api.models`` extractors.

These pin the public extraction contracts of ``Block`` and
``SSEMessage`` — web-result suppression, usage diagnostics, answer-text
selection order and JSON-mode serialisation of the request parameters.
"""

from __future__ import annotations

from datetime import datetime

from perplexity_cli.api.models import Block, QueryParams, SSEMessage


class TestBlockTextExtraction:
    """Block.extract_text contract."""

    def test_web_result_blocks_never_yield_text(self) -> None:
        """Blocks carrying a web_result_block are excluded from text extraction."""
        block = Block(
            intended_usage="ask_text",
            content={
                "web_result_block": {"web_results": []},
                "text": "t008-should-not-leak",
            },
        )

        assert block.extract_text() is None

    def test_markdown_chunks_are_joined(self) -> None:
        """Markdown chunk lists are concatenated in order."""
        block = Block(
            intended_usage="ask_text",
            content={"markdown_block": {"chunks": ["t008-a", "t008-b"]}},
        )

        assert block.extract_text() == "t008-at008-b"


class TestSSEMessageDiagnostics:
    """SSEMessage diagnostic and selection contracts."""

    def test_empty_message_reports_no_usages(self) -> None:
        """Messages without blocks report the empty sentinel."""
        message = SSEMessage.model_validate({"blocks": []})

        assert message.describe_block_usages() == "none"

    def test_usages_join_in_order_with_missing_placeholder(self) -> None:
        """Usages join in block order; empty usages become <missing>."""
        message = SSEMessage(
            blocks=[
                Block(intended_usage="t008-step"),
                Block(intended_usage=""),
                Block(intended_usage="t008-final"),
            ]
        )

        assert message.describe_block_usages() == "t008-step,<missing>,t008-final"

    def test_answer_extraction_continues_past_other_blocks(self) -> None:
        """Non ask_text blocks do not stop the answer search."""
        message = SSEMessage(
            blocks=[
                Block(intended_usage="plan", content={}),
                Block(
                    intended_usage="ask_text",
                    content={"markdown_block": {"chunks": ["t008-answer"]}},
                ),
            ]
        )

        assert message.extract_answer_text() == "t008-answer"


class TestQueryParamsSerialisation:
    """QueryParams.to_dict serialisation mode contract."""

    def test_to_dict_serialises_values_as_json(self) -> None:
        """Extra non-scalar values are serialised to their JSON form."""
        params = QueryParams(t008_timestamp=datetime(2026, 1, 2, 3, 4, 5))

        payload = params.to_dict()

        assert payload["t008_timestamp"] == "2026-01-02T03:04:05"
