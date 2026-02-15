"""Tests for CLI flag compositions and combinations."""

from unittest.mock import MagicMock, Mock, patch

import pytest
from click.testing import CliRunner

from perplexity_cli.api.models import Answer, Block, SSEMessage, WebResult
from perplexity_cli.cli import query


def _make_api_mock(**kwargs):
    """Create a Mock for PerplexityAPI that supports context manager protocol."""
    mock_api = MagicMock()
    mock_api.__enter__ = Mock(return_value=mock_api)
    mock_api.__exit__ = Mock(return_value=False)
    for key, value in kwargs.items():
        setattr(mock_api, key, value)
    return mock_api


def _make_streaming_mock(text="Streamed answer", web_results=None):
    """Create a mock API that returns a single final SSE message for streaming.

    Args:
        text: The answer text to return.
        web_results: Optional list of WebResult objects.

    Returns:
        A mock PerplexityAPI configured for streaming.
    """
    mock_message = Mock(spec=SSEMessage)
    mock_message.status = "COMPLETE"
    mock_message.final_sse_message = True
    mock_message.web_results = web_results or []

    mock_block = Mock(spec=Block)
    mock_block.intended_usage = "ask_text"
    mock_block.content = {"markdown_block": {"chunks": [text]}}
    mock_message.blocks = [mock_block]

    mock_api = _make_api_mock()
    mock_api.submit_query.return_value = iter([mock_message])
    mock_api._extract_text_from_block.return_value = text
    mock_api._extract_plan_block_info.return_value = None
    return mock_api


@pytest.fixture
def runner():
    """Create a Click CLI test runner."""
    return CliRunner()


class TestDeepResearchWithStream:
    """Test --deep-research combined with --stream."""

    @patch("perplexity_cli.cli.StyleManager")
    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_deep_research_and_stream(self, mock_api_class, mock_tm_class, mock_sm_class, runner):
        """Test that --deep-research and --stream work together."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        mock_tm = Mock()
        mock_tm.load_token.return_value = ("test-token", None)
        mock_tm_class.return_value = mock_tm

        mock_api = _make_streaming_mock(text="Deep streamed answer")
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["--deep-research", "--stream", "Explain Kubernetes"])

        assert result.exit_code == 0
        assert "Deep streamed answer" in result.output
        # Verify submit_query was called with multi_step mode
        mock_api.submit_query.assert_called_once()
        call_kwargs = mock_api.submit_query.call_args
        assert call_kwargs[1]["search_implementation_mode"] == "multi_step"

    @patch("perplexity_cli.cli.StyleManager")
    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_deep_research_without_stream_uses_batch(
        self, mock_api_class, mock_tm_class, mock_sm_class, runner
    ):
        """Test that --deep-research without --stream uses batch mode."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        mock_tm = Mock()
        mock_tm.load_token.return_value = ("test-token", None)
        mock_tm_class.return_value = mock_tm

        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = Answer(text="Deep batch answer", references=[])
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["--deep-research", "Explain Kubernetes"])

        assert result.exit_code == 0
        assert "Deep batch answer" in result.output
        mock_api.get_complete_answer.assert_called_once_with(
            "Explain Kubernetes", search_implementation_mode="multi_step"
        )


class TestDeepResearchWithFormatJson:
    """Test --deep-research combined with --format json."""

    @patch("perplexity_cli.cli.StyleManager")
    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_deep_research_json_format(self, mock_api_class, mock_tm_class, mock_sm_class, runner):
        """Test that --deep-research works with --format json."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        mock_tm = Mock()
        mock_tm.load_token.return_value = ("test-token", None)
        mock_tm_class.return_value = mock_tm

        refs = [
            WebResult(name="Source", url="https://source.com", snippet="Source content"),
        ]
        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = Answer(text="Deep JSON answer", references=refs)
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["--deep-research", "--format", "json", "Explain Kubernetes"])

        assert result.exit_code == 0
        # JSON format should output valid JSON
        import json

        output = json.loads(result.output)
        assert "answer" in output or "Deep JSON answer" in result.output


class TestStripReferencesWithMarkdown:
    """Test --strip-references combined with --format markdown."""

    @patch("perplexity_cli.cli.StyleManager")
    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_strip_references_markdown(self, mock_api_class, mock_tm_class, mock_sm_class, runner):
        """Test that --strip-references works with --format markdown."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        mock_tm = Mock()
        mock_tm.load_token.return_value = ("test-token", None)
        mock_tm_class.return_value = mock_tm

        refs = [
            WebResult(name="Wiki", url="https://wiki.org", snippet="Article"),
        ]
        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = Answer(
            text="Answer with [1] citation", references=refs
        )
        mock_api_class.return_value = mock_api

        result = runner.invoke(
            query,
            ["--strip-references", "--format", "markdown", "What is Python?"],
        )

        assert result.exit_code == 0
        # With strip-references, the citation numbers and references should be stripped
        assert "wiki.org" not in result.output


class TestStreamWithPlainFormat:
    """Test --stream combined with --format plain."""

    @patch("perplexity_cli.cli.StyleManager")
    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_stream_plain_format(self, mock_api_class, mock_tm_class, mock_sm_class, runner):
        """Test that --stream works with --format plain."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        mock_tm = Mock()
        mock_tm.load_token.return_value = ("test-token", None)
        mock_tm_class.return_value = mock_tm

        mock_api = _make_streaming_mock(text="Plain streamed text")
        mock_api_class.return_value = mock_api

        result = runner.invoke(query, ["--stream", "--format", "plain", "What is 2+2?"])

        assert result.exit_code == 0
        assert "Plain streamed text" in result.output


class TestFlagPassthrough:
    """Test that flags are correctly passed through to the API layer."""

    @patch("perplexity_cli.cli.StyleManager")
    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_deep_research_passes_multi_step_mode(
        self, mock_api_class, mock_tm_class, mock_sm_class, runner
    ):
        """Test that --deep-research passes search_implementation_mode='multi_step'."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        mock_tm = Mock()
        mock_tm.load_token.return_value = ("test-token", None)
        mock_tm_class.return_value = mock_tm

        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = Answer(text="Answer", references=[])
        mock_api_class.return_value = mock_api

        runner.invoke(query, ["--deep-research", "test query"])

        mock_api.get_complete_answer.assert_called_once_with(
            "test query", search_implementation_mode="multi_step"
        )

    @patch("perplexity_cli.cli.StyleManager")
    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_no_deep_research_passes_standard_mode(
        self, mock_api_class, mock_tm_class, mock_sm_class, runner
    ):
        """Test that without --deep-research, search_implementation_mode='standard'."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        mock_tm = Mock()
        mock_tm.load_token.return_value = ("test-token", None)
        mock_tm_class.return_value = mock_tm

        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = Answer(text="Answer", references=[])
        mock_api_class.return_value = mock_api

        runner.invoke(query, ["test query"])

        mock_api.get_complete_answer.assert_called_once_with(
            "test query", search_implementation_mode="standard"
        )

    @patch("perplexity_cli.cli.StyleManager")
    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_stream_flag_uses_submit_query(
        self, mock_api_class, mock_tm_class, mock_sm_class, runner
    ):
        """Test that --stream uses submit_query instead of get_complete_answer."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        mock_tm = Mock()
        mock_tm.load_token.return_value = ("test-token", None)
        mock_tm_class.return_value = mock_tm

        mock_api = _make_streaming_mock()
        mock_api_class.return_value = mock_api

        runner.invoke(query, ["--stream", "test query"])

        mock_api.submit_query.assert_called_once()
        mock_api.get_complete_answer.assert_not_called()

    @patch("perplexity_cli.cli.StyleManager")
    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_no_stream_flag_uses_get_complete_answer(
        self, mock_api_class, mock_tm_class, mock_sm_class, runner
    ):
        """Test that --no-stream uses get_complete_answer."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        mock_tm = Mock()
        mock_tm.load_token.return_value = ("test-token", None)
        mock_tm_class.return_value = mock_tm

        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = Answer(text="Answer", references=[])
        mock_api_class.return_value = mock_api

        runner.invoke(query, ["--no-stream", "test query"])

        mock_api.get_complete_answer.assert_called_once()
        mock_api.submit_query.assert_not_called()


class TestMultipleFlagCombinations:
    """Test various multi-flag combinations work without errors."""

    @patch("perplexity_cli.cli.StyleManager")
    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_deep_research_stream_plain(self, mock_api_class, mock_tm_class, mock_sm_class, runner):
        """Test --deep-research --stream --format plain all together."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        mock_tm = Mock()
        mock_tm.load_token.return_value = ("test-token", None)
        mock_tm_class.return_value = mock_tm

        mock_api = _make_streaming_mock(text="Full combo answer")
        mock_api_class.return_value = mock_api

        result = runner.invoke(
            query,
            ["--deep-research", "--stream", "--format", "plain", "test"],
        )

        assert result.exit_code == 0
        assert "Full combo answer" in result.output

    @patch("perplexity_cli.cli.StyleManager")
    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_strip_references_json_no_stream(
        self, mock_api_class, mock_tm_class, mock_sm_class, runner
    ):
        """Test --strip-references --format json --no-stream all together."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        mock_tm = Mock()
        mock_tm.load_token.return_value = ("test-token", None)
        mock_tm_class.return_value = mock_tm

        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = Answer(
            text="JSON stripped answer", references=[]
        )
        mock_api_class.return_value = mock_api

        result = runner.invoke(
            query,
            ["--strip-references", "--format", "json", "--no-stream", "test"],
        )

        assert result.exit_code == 0

    @patch("perplexity_cli.cli.StyleManager")
    @patch("perplexity_cli.cli.TokenManager")
    @patch("perplexity_cli.cli.PerplexityAPI")
    def test_deep_research_strip_references_markdown(
        self, mock_api_class, mock_tm_class, mock_sm_class, runner
    ):
        """Test --deep-research --strip-references --format markdown together."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        mock_tm = Mock()
        mock_tm.load_token.return_value = ("test-token", None)
        mock_tm_class.return_value = mock_tm

        mock_api = _make_api_mock()
        mock_api.get_complete_answer.return_value = Answer(
            text="Deep stripped markdown", references=[]
        )
        mock_api_class.return_value = mock_api

        result = runner.invoke(
            query,
            ["--deep-research", "--strip-references", "--format", "markdown", "test"],
        )

        assert result.exit_code == 0
        assert "Deep stripped markdown" in result.output
