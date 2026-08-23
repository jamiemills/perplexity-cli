"""Tests for Perplexity API endpoints."""

import uuid
from unittest.mock import Mock, patch

import pytest

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import Answer, QueryInput, SSEMessage, WebResult
from perplexity_cli.auth.models import AuthContext
from perplexity_cli.utils.exceptions import UpstreamSchemaError


class TestPerplexityAPIGetCompleteAnswer:
    """Test get_complete_answer method."""

    @patch("perplexity_cli.api.endpoints.PerplexityAPI.submit_query")
    def test_get_complete_answer_text_only(self, mock_submit):
        """Test get_complete_answer returns text without references."""
        # Create mock SSE message with text but no web results
        mock_message = Mock(spec=SSEMessage)
        mock_message.final_sse_message = True
        mock_message.blocks = [
            Mock(
                intended_usage="ask_text",
                content={"markdown_block": {"chunks": ["This is ", "the answer"]}},
            )
        ]
        mock_message.extract_answer_text.return_value = "This is the answer"
        mock_message.web_results = None

        mock_submit.return_value = [mock_message]

        api = PerplexityAPI(token="test-token")
        result = api.get_complete_answer("test query")

        assert isinstance(result, Answer)
        assert result.text == "This is the answer"
        assert result.references == []

    @patch("perplexity_cli.api.endpoints.PerplexityAPI.submit_query")
    def test_get_complete_answer_with_references(self, mock_submit):
        """Test get_complete_answer returns text with references."""
        web_refs = [
            WebResult(name="Wiki", url="https://wiki.org", snippet="Wikipedia"),
            WebResult(
                name="Official",
                url="https://official.org",
                snippet="Official site",
            ),
        ]

        mock_message = Mock(spec=SSEMessage)
        mock_message.final_sse_message = True
        mock_message.blocks = [
            Mock(
                intended_usage="ask_text",
                content={"markdown_block": {"chunks": ["Complete answer"]}},
            )
        ]
        mock_message.extract_answer_text.return_value = "Complete answer"
        mock_message.web_results = web_refs

        mock_submit.return_value = [mock_message]

        api = PerplexityAPI(token="test-token")
        result = api.get_complete_answer("test query")

        assert isinstance(result, Answer)
        assert result.text == "Complete answer"
        assert len(result.references) == 2
        assert result.references[0].url == "https://wiki.org"
        assert result.references[1].url == "https://official.org"

    @patch("perplexity_cli.api.endpoints.PerplexityAPI.submit_query")
    def test_get_complete_answer_ignores_non_final_messages(self, mock_submit):
        """Test that non-final messages are ignored."""
        # Create mock messages - intermediate and final
        intermediate_message = Mock(spec=SSEMessage)
        intermediate_message.final_sse_message = False
        intermediate_message.extract_answer_text.return_value = None

        final_message = Mock(spec=SSEMessage)
        final_message.final_sse_message = True
        final_message.blocks = [
            Mock(
                intended_usage="ask_text",
                content={"markdown_block": {"chunks": ["Final answer"]}},
            )
        ]
        final_message.extract_answer_text.return_value = "Final answer"
        final_message.web_results = None

        mock_submit.return_value = [intermediate_message, final_message]

        api = PerplexityAPI(token="test-token")
        result = api.get_complete_answer("test query")

        assert result.text == "Final answer"

    @patch("perplexity_cli.api.endpoints.PerplexityAPI.submit_query")
    def test_get_complete_answer_no_answer_raises_error(self, mock_submit):
        """Test that UpstreamSchemaError is raised when no answer is found."""
        mock_message = Mock(spec=SSEMessage)
        mock_message.final_sse_message = True
        mock_message.blocks = []  # No blocks
        mock_message.extract_answer_text.return_value = None
        mock_message.web_results = None
        mock_message.status = ""

        mock_submit.return_value = [mock_message]

        api = PerplexityAPI(token="test-token")
        with pytest.raises(UpstreamSchemaError, match="No answer found"):
            api.get_complete_answer("test query")

    @patch("perplexity_cli.api.endpoints.PerplexityAPI.submit_query")
    def test_get_complete_answer_extracts_from_multiple_chunks(self, mock_submit):
        """Test text extraction from multiple chunks."""
        mock_message = Mock(spec=SSEMessage)
        mock_message.final_sse_message = True
        mock_message.blocks = [
            Mock(
                intended_usage="ask_text",
                content={
                    "markdown_block": {"chunks": ["This ", "is ", "a ", "multi-chunk ", "answer"]}
                },
            )
        ]
        mock_message.extract_answer_text.return_value = "This is a multi-chunk answer"
        mock_message.web_results = None

        mock_submit.return_value = [mock_message]

        api = PerplexityAPI(token="test-token")
        result = api.get_complete_answer("test query")

        assert result.text == "This is a multi-chunk answer"


class TestPerplexityAPISubmitQuery:
    """Test submit_query request construction."""

    @patch(
        "perplexity_cli.api.endpoints.get_query_endpoint", return_value="https://example.com/query"
    )
    def test_submit_query_merges_request_param_overrides(self, mock_endpoint):
        """Experimental request params are merged into the outbound payload."""
        api = PerplexityAPI(token="test-token")
        api.client = Mock()
        api.client.stream_post.return_value = iter(())

        list(
            api.submit_query(
                QueryInput(
                    query="test query",
                    request_params={"workflow_key": "deep_research", "search_mode": "research"},
                )
            )
        )

        mock_endpoint.assert_called_once_with()
        _, payload = api.client.stream_post.call_args.args
        assert payload["params"]["workflow_key"] == "deep_research"
        assert payload["params"]["search_mode"] == "research"


class TestPerplexityAPIWiring:
    """Constructor and request-construction wiring contracts."""

    def test_init_forwards_token_cookies_and_timeout(self) -> None:
        """Credentials and timeout reach the underlying SSE client intact."""
        api = PerplexityAPI(
            token="t008-token",
            cookies={"cf_clearance": "t008-cookie"},
            timeout=77,
        )

        assert api.client.auth.token == "t008-token"
        assert api.client.auth.cookies == {"cf_clearance": "t008-cookie"}
        assert api.client.timeout == 77
        api.close()

    @patch("perplexity_cli.api.endpoints.SSEClient")
    def test_init_constructs_stream_client_with_auth_and_timeout(self, mock_client: Mock) -> None:
        """Construction forwards every transport option to the stream client."""
        PerplexityAPI(token="t008-token", cookies={"session": "t008-cookie"}, timeout=77)

        mock_client.assert_called_once_with(
            auth=AuthContext(token="t008-token", cookies={"session": "t008-cookie"}),
            timeout=77,
        )

    @patch("perplexity_cli.api.endpoints.get_query_endpoint", return_value="https://example.test/q")
    def test_submit_query_rejects_blank_query(self, _mock_endpoint: Mock) -> None:
        """Blank queries are rejected with a stable validation error."""
        api = PerplexityAPI(token="t008-token")
        api.client = Mock()

        with pytest.raises(ValueError, match=r"^Query must not be empty$"):
            list(api.submit_query(QueryInput(query="   ")))

    @patch("perplexity_cli.api.endpoints.get_query_endpoint", return_value="https://example.test/q")
    def test_submit_query_builds_uuids_endpoint_and_default_mode(self, mock_endpoint: Mock) -> None:
        """Requests carry fresh UUIDs, the configured endpoint and standard mode."""
        api = PerplexityAPI(token="t008-token")
        api.client = Mock()
        api.client.stream_post.return_value = iter(())

        list(api.submit_query(QueryInput(query="hello")))

        endpoint_arg, payload = api.client.stream_post.call_args.args
        assert endpoint_arg == "https://example.test/q"
        params = payload["params"]
        uuid.UUID(params["frontend_uuid"])
        uuid.UUID(params["frontend_context_uuid"])
        assert params["search_implementation_mode"] == "standard"
        mock_endpoint.assert_called_once_with()

    @patch("perplexity_cli.api.endpoints.get_query_endpoint", return_value="https://example.test/q")
    def test_submit_query_forwards_query_and_explicit_mode(self, _mock_endpoint: Mock) -> None:
        """The public submit boundary preserves query data and explicit mode."""
        api = PerplexityAPI(token="t008-token")
        api.client = Mock()
        api.client.stream_post.return_value = iter(({},))

        messages = list(
            api.submit_query(
                QueryInput(query=" t008 query ", model_preference="t008-model"),
                search_implementation_mode="multi_step",
            )
        )

        assert len(messages) == 1
        _, payload = api.client.stream_post.call_args.args
        assert payload["query_str"] == " t008 query "
        assert payload["params"]["model_preference"] == "t008-model"
        assert payload["params"]["search_implementation_mode"] == "multi_step"

    @patch("perplexity_cli.api.endpoints.PerplexityAPI.submit_query")
    def test_collect_final_message_passes_mode_through(self, mock_submit: Mock) -> None:
        """The chosen search implementation mode reaches submit_query."""
        final_message = Mock(spec=SSEMessage)
        final_message.final_sse_message = True
        mock_submit.return_value = [final_message]

        api = PerplexityAPI(token="t008-token")
        result = api._collect_final_message(
            QueryInput(query="hello"),
            search_implementation_mode="multi_step",
        )

        assert result is final_message
        _, kwargs = mock_submit.call_args
        assert kwargs["search_implementation_mode"] == "multi_step"

    @patch("perplexity_cli.api.endpoints.PerplexityAPI.submit_query")
    def test_get_complete_answer_forwards_extra_params(self, mock_submit: Mock) -> None:
        """Attachments, model preference and overrides reach the query input."""
        final_message = Mock(spec=SSEMessage)
        final_message.final_sse_message = True
        final_message.extract_answer_text.return_value = "answer"
        final_message.web_results = []
        mock_submit.return_value = [final_message]

        api = PerplexityAPI(token="t008-token")
        result = api.get_complete_answer(
            "test query",
            extra_params=(["https://att.example.test/a"], "pplx_pro", {"k": "v"}),
        )

        query_input = mock_submit.call_args.args[0]
        assert query_input.query == "test query"
        assert query_input.attachment_urls == ["https://att.example.test/a"]
        assert query_input.model_preference == "pplx_pro"
        assert query_input.request_params == {"k": "v"}
        assert isinstance(result, Answer)
        assert result.text == "answer"

    @patch("perplexity_cli.api.endpoints.PerplexityAPI.submit_query")
    def test_get_complete_answer_defaults_to_standard_mode(self, mock_submit: Mock) -> None:
        """Without an explicit mode, standard search mode is submitted."""
        final_message = Mock(spec=SSEMessage)
        final_message.final_sse_message = True
        final_message.extract_answer_text.return_value = "answer"
        final_message.web_results = []
        mock_submit.return_value = [final_message]

        api = PerplexityAPI(token="t008-token")
        api.get_complete_answer("test query")

        assert mock_submit.call_args.kwargs["search_implementation_mode"] == "standard"

    @patch("perplexity_cli.api.endpoints.PerplexityAPI.submit_query")
    def test_get_complete_answer_empty_extra_params_use_query_defaults(
        self, mock_submit: Mock
    ) -> None:
        """An explicitly empty override tuple does not replace query defaults."""
        final_message = Mock(spec=SSEMessage)
        final_message.final_sse_message = True
        final_message.extract_answer_text.return_value = "answer"
        final_message.web_results = []
        mock_submit.return_value = [final_message]

        api = PerplexityAPI(token="t008-token")
        api.get_complete_answer("test query", extra_params=(None, None, None))

        query_input = mock_submit.call_args.args[0]
        assert query_input.attachment_urls == []
        assert query_input.model_preference is None
        assert query_input.request_params == {}
