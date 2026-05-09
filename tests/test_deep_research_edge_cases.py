"""Tests for deep research edge cases including Block and QueryParams."""

import pytest
from pydantic import ValidationError

from perplexity_cli.api.models import Block, QueryParams


class TestExtractPlanBlockInfo:
    """Test the extract_plan_info() method on Block."""

    def test_non_plan_block_returns_none(self):
        """Test that a block with intended_usage other than plan returns None."""
        block = Block(intended_usage="ask_text", content={"markdown_block": {"chunks": ["text"]}})
        result = block.extract_plan_info()
        assert result is None

    def test_web_results_block_returns_none(self):
        """Test that a web_results block returns None."""
        block = Block(intended_usage="web_results", content={"web_result_block": {}})
        result = block.extract_plan_info()
        assert result is None

    def test_plan_block_with_full_data(self):
        """Test extracting info from a plan block with all fields."""
        block = Block(
            intended_usage="plan",
            content={
                "plan_block": {
                    "progress": "Researching step 3 of 5",
                    "eta_seconds_remaining": 120,
                    "goals": ["Analyse sources", "Synthesise findings", "Verify claims"],
                    "pct_complete": 60,
                }
            },
        )

        result = block.extract_plan_info()

        assert result is not None
        assert result["progress"] == "Researching step 3 of 5"
        assert result["eta_seconds"] == 120
        assert len(result["goals"]) == 3
        assert result["pct_complete"] == 60

    def test_pro_search_steps_intended_usage(self):
        """Test that 'pro_search_steps' intended_usage is also handled."""
        block = Block(
            intended_usage="pro_search_steps",
            content={
                "plan_block": {
                    "progress": "Step 2",
                    "eta_seconds_remaining": 60,
                    "goals": ["Goal A"],
                    "pct_complete": 40,
                }
            },
        )

        result = block.extract_plan_info()

        assert result is not None
        assert result["progress"] == "Step 2"

    def test_plan_block_missing_plan_block_key(self):
        """Test that a plan block without 'plan_block' key returns None."""
        block = Block(intended_usage="plan", content={"other_data": "value"})
        result = block.extract_plan_info()
        assert result is None

    def test_plan_block_empty_plan_block(self):
        """Test that a plan block with an empty plan_block dict returns None."""
        block = Block(intended_usage="plan", content={"plan_block": {}})
        result = block.extract_plan_info()
        assert result is None

    def test_plan_block_missing_optional_keys(self):
        """Test that missing optional keys in plan_block return None values."""
        block = Block(
            intended_usage="plan",
            content={"plan_block": {"progress": "In progress"}},
        )

        result = block.extract_plan_info()

        assert result is not None
        assert result["progress"] == "In progress"
        assert result["eta_seconds"] is None
        assert result["goals"] == []
        assert result["pct_complete"] is None

    def test_plan_block_with_many_goals(self):
        """Test plan block with a large number of goals."""
        goals = [f"Goal {i}" for i in range(20)]
        block = Block(
            intended_usage="plan",
            content={
                "plan_block": {
                    "progress": "Multi-goal research",
                    "eta_seconds_remaining": 300,
                    "goals": goals,
                    "pct_complete": 10,
                }
            },
        )

        result = block.extract_plan_info()

        assert result is not None
        assert len(result["goals"]) == 20
        assert result["goals"][0] == "Goal 0"
        assert result["goals"][19] == "Goal 19"

    def test_plan_block_with_zero_eta(self):
        """Test plan block with zero ETA (almost complete)."""
        block = Block(
            intended_usage="plan",
            content={
                "plan_block": {
                    "progress": "Finalising",
                    "eta_seconds_remaining": 0,
                    "goals": ["Final step"],
                    "pct_complete": 99,
                }
            },
        )

        result = block.extract_plan_info()

        assert result is not None
        assert result["eta_seconds"] == 0
        assert result["pct_complete"] == 99

    def test_plan_block_with_100_percent_complete(self):
        """Test plan block at 100% completion."""
        block = Block(
            intended_usage="plan",
            content={
                "plan_block": {
                    "progress": "Complete",
                    "eta_seconds_remaining": 0,
                    "goals": ["Done"],
                    "pct_complete": 100,
                }
            },
        )

        result = block.extract_plan_info()

        assert result is not None
        assert result["pct_complete"] == 100


class TestQueryParamsDeepResearch:
    """Test QueryParams with deep research search_implementation_mode."""

    def test_multi_step_mode_accepted(self):
        """Test that 'multi_step' is a valid search_implementation_mode."""
        params = QueryParams(search_implementation_mode="multi_step")
        assert params.search_implementation_mode == "multi_step"

    def test_standard_mode_accepted(self):
        """Test that 'standard' is a valid search_implementation_mode."""
        params = QueryParams(search_implementation_mode="standard")
        assert params.search_implementation_mode == "standard"

    def test_invalid_mode_raises_validation_error(self):
        """Test that an invalid mode raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            QueryParams(search_implementation_mode="invalid_mode")
        error_str = str(exc_info.value)
        assert "standard" in error_str
        assert "multi_step" in error_str

    def test_empty_string_mode_raises_validation_error(self):
        """Test that empty string mode raises ValidationError."""
        with pytest.raises(ValidationError):
            QueryParams(search_implementation_mode="")

    def test_case_sensitive_validation(self):
        """Test that mode validation is case-sensitive."""
        with pytest.raises(ValidationError):
            QueryParams(search_implementation_mode="Multi_Step")

    def test_multi_step_serialisation(self):
        """Test multi_step mode appears in serialised output."""
        params = QueryParams(search_implementation_mode="multi_step")
        data = params.to_dict()
        assert data["search_implementation_mode"] == "multi_step"

    def test_standard_serialisation(self):
        """Test standard mode appears in serialised output."""
        params = QueryParams(search_implementation_mode="standard")
        data = params.to_dict()
        assert data["search_implementation_mode"] == "standard"

    def test_default_mode_is_standard(self):
        """Test that the default mode is 'standard'."""
        params = QueryParams()
        assert params.search_implementation_mode == "standard"

    def test_deep_research_mode_in_full_request(self):
        """Test that multi_step mode is preserved through full request building."""
        from perplexity_cli.api.models import QueryRequest

        params = QueryParams(
            search_implementation_mode="multi_step",
            language="en-GB",
        )
        request = QueryRequest(query_str="test query", params=params)
        request_dict = request.to_dict()

        assert request_dict["params"]["search_implementation_mode"] == "multi_step"
        assert request_dict["params"]["language"] == "en-GB"
        assert request_dict["query_str"] == "test query"

    def test_whitespace_mode_raises_validation_error(self):
        """Test that whitespace-only mode raises ValidationError."""
        with pytest.raises(ValidationError):
            QueryParams(search_implementation_mode="   ")

    def test_none_mode_raises_validation_error(self):
        """Test that None mode raises ValidationError."""
        with pytest.raises(ValidationError):
            QueryParams(search_implementation_mode=None)


class TestExtractTextFromBlock:
    """Test the Block.extract_text() method for completeness."""

    def test_extract_from_markdown_block(self):
        """Test extracting text from a markdown_block with chunks."""
        block = Block(
            intended_usage="", content={"markdown_block": {"chunks": ["Hello ", "world"]}}
        )
        assert block.extract_text() == "Hello world"

    def test_extract_from_text_field(self):
        """Test extracting text from a direct 'text' field."""
        block = Block(intended_usage="", content={"text": "Direct text content"})
        assert block.extract_text() == "Direct text content"

    def test_extract_from_answer_block(self):
        """Test extracting text from an answer_block."""
        block = Block(intended_usage="", content={"answer_block": {"text": "Answer text"}})
        assert block.extract_text() == "Answer text"

    def test_extract_from_diff_block(self):
        """Test extracting text from a diff_block with patches."""
        block = Block(
            intended_usage="", content={"diff_block": {"patches": [{"value": "Diff text"}]}}
        )
        assert block.extract_text() == "Diff text"

    def test_extract_from_web_result_block_returns_none(self):
        """Test that web_result_block does not produce answer text."""
        block = Block(intended_usage="", content={"web_result_block": {"web_results": []}})
        assert block.extract_text() is None

    def test_extract_from_empty_content_returns_none(self):
        """Test that empty content dict returns None."""
        block = Block(intended_usage="", content={})
        assert block.extract_text() is None

    def test_extract_from_markdown_block_empty_chunks(self):
        """Test extracting text from markdown_block with empty chunks list."""
        block = Block(intended_usage="", content={"markdown_block": {"chunks": []}})
        assert block.extract_text() == ""
