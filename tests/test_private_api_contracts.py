"""Contract-style tests for private upstream payload parsing."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from perplexity_cli.api.contracts import describe_payload_shape
from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import FileAttachment, SSEMessage
from perplexity_cli.attachments.upload_manager import AttachmentUploader
from perplexity_cli.threads.scraper import ThreadScraper
from perplexity_cli.utils.exceptions import AttachmentUploadError, UpstreamSchemaError

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "private_api"


def load_payload(name: str) -> dict:
    """Load a sanitised upstream payload fixture."""

    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class TestPrivateAPIContracts:
    """Verify realistic private API payload contracts remain supported."""

    def test_submit_query_parses_plan_and_final_answer_payloads(self):
        """Test submit_query parses common progress and final payload shapes."""
        api = PerplexityAPI(token="test-token")
        api.client = Mock()
        api.client.stream_post.return_value = iter(
            [
                load_payload("plan_progress_message.json"),
                load_payload("final_answer_message.json"),
            ]
        )

        messages = list(api.submit_query("Where is Paris?"))

        assert len(messages) == 2

        plan_info = messages[0].blocks[0].extract_plan_info()
        assert plan_info == {
            "progress": "Comparing source quality",
            "eta_seconds": 87,
            "goals": [
                "Check encyclopaedia summary",
                "Cross-check government site",
            ],
            "pct_complete": 35,
        }

        assert messages[1].final_sse_message is True
        assert messages[1].extract_answer_text() == (
            "Paris is the capital of France.\n\nIt is the country's largest city."
        )
        assert messages[1].web_results is not None
        assert [result.url for result in messages[1].web_results] == [
            "https://example.invalid/encyclopaedia/paris",
            "https://gov.example.invalid/france/paris",
        ]

    def test_get_complete_answer_uses_sanitised_final_payload(self):
        """Test complete-answer extraction against a realistic final payload."""
        api = PerplexityAPI(token="test-token")
        api.client = Mock()
        api.client.stream_post.return_value = iter([load_payload("final_answer_message.json")])

        answer = api.get_complete_answer("Where is Paris?")

        assert answer.text == "Paris is the capital of France.\n\nIt is the country's largest city."
        assert len(answer.references) == 2
        assert answer.references[0].name == "Encyclopaedia Example"
        assert answer.references[1].url == "https://gov.example.invalid/france/paris"

    def test_sse_message_supports_diff_answer_fixture(self):
        """Test diff-style answer blocks remain parseable."""
        message = SSEMessage.from_dict(load_payload("diff_answer_message.json"))

        assert message.extract_answer_text() == "Updated summary from diff payload."
        assert message.web_results is None

    def test_submit_query_rejects_malformed_web_results_fixture(self):
        """Test malformed upstream references raise UpstreamSchemaError."""
        api = PerplexityAPI(token="test-token")
        api.client = Mock()
        api.client.stream_post.return_value = iter(
            [load_payload("malformed_web_results_message.json")]
        )

        with pytest.raises(UpstreamSchemaError, match="Malformed web result block"):
            list(api.submit_query("broken payload"))

    def test_get_complete_answer_reports_block_usages_when_answer_missing(self):
        """Test no-answer failures include actionable schema-drift diagnostics."""
        api = PerplexityAPI(token="test-token")
        api.client = Mock()
        api.client.stream_post.return_value = iter([load_payload("final_no_answer_message.json")])

        with pytest.raises(
            UpstreamSchemaError,
            match=r"No answer found in final upstream response: status=COMPLETED, block_usages=web_results",
        ):
            api.get_complete_answer("missing answer")


class TestUploadContracts:
    """Verify upload contract parsing against sanitised upstream payloads."""

    @pytest.mark.asyncio
    async def test_request_upload_urls_accepts_fixture_response(self):
        """Test presigned upload payload contract using a sanitised fixture."""
        uploader = AttachmentUploader(token="test-token")
        attachment = FileAttachment(
            filename="fixture-1.txt",
            content_type="text/plain",
            data="Zml4dHVyZS1jb250ZW50",
        )

        mock_session = AsyncMock()
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json = Mock(return_value=load_payload("upload_url_success_response.json"))
        mock_session.post.return_value = mock_response

        with patch("perplexity_cli.attachments.upload_manager.AsyncSession") as mock_session_class:
            mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)
            with patch("perplexity_cli.attachments.upload_manager.uuid.uuid4") as mock_uuid:
                mock_uuid.return_value = type("UUID", (), {"__str__": lambda s: "fixture-uuid-1"})()
                response_json, uuid_map = await uploader._request_upload_urls([attachment])

        assert response_json["results"]["fixture-uuid-1"]["s3_object_url"].endswith("fixture-1.txt")
        assert uuid_map["fixture-uuid-1"].filename == "fixture-1.txt"

    @pytest.mark.asyncio
    async def test_request_upload_urls_surfaces_rate_limited_fixture(self):
        """Test representative upstream upload quota payload gets a clear error."""
        uploader = AttachmentUploader(token="test-token")
        attachment = FileAttachment(
            filename="fixture-1.txt",
            content_type="text/plain",
            data="Zml4dHVyZS1jb250ZW50",
        )

        mock_session = AsyncMock()
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json = Mock(
            return_value=load_payload("upload_url_rate_limited_response.json")
        )
        mock_session.post.return_value = mock_response

        with patch("perplexity_cli.attachments.upload_manager.AsyncSession") as mock_session_class:
            mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)
            with patch("perplexity_cli.attachments.upload_manager.uuid.uuid4") as mock_uuid:
                mock_uuid.return_value = type("UUID", (), {"__str__": lambda s: "fixture-uuid-1"})()
                with pytest.raises(AttachmentUploadError, match="File upload quota exhausted"):
                    await uploader._request_upload_urls([attachment])


class TestThreadListContracts:
    """Verify thread-list contract parsing against sanitised upstream payloads."""

    @pytest.mark.asyncio
    async def test_fetch_threads_accepts_fixture_page(self):
        """Test thread-list payload contract using a sanitised fixture."""
        scraper = ThreadScraper(token='{"user": {"accessToken": "test-token"}}')

        mock_response_page = Mock()
        mock_response_page.ok = True
        mock_response_page.json.return_value = load_payload("thread_list_page.json")

        mock_response_done = Mock()
        mock_response_done.ok = True
        mock_response_done.json.return_value = []

        mock_session = AsyncMock()
        mock_session.post.side_effect = [mock_response_page, mock_response_done]

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_session
        mock_context.__aexit__.return_value = False

        with patch("perplexity_cli.threads.scraper.AsyncSession", return_value=mock_context):
            threads = await scraper._fetch_all_threads_from_api("test-token")

        assert [thread.title for thread in threads] == ["Example thread one", "Example thread two"]
        assert threads[0].url == "https://www.perplexity.ai/search/example-thread-one"

    @pytest.mark.asyncio
    async def test_fetch_threads_rejects_error_envelope_fixture(self):
        """Test schema-drift diagnostics include top-level payload shape details."""
        scraper = ThreadScraper(token='{"user": {"accessToken": "test-token"}}')

        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = load_payload("thread_list_error_payload.json")

        mock_session = AsyncMock()
        mock_session.post.return_value = mock_response

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_session
        mock_context.__aexit__.return_value = False

        with patch("perplexity_cli.threads.scraper.AsyncSession", return_value=mock_context):
            with pytest.raises(
                UpstreamSchemaError,
                match=r"Malformed thread list payload from upstream API: expected array, got object\(keys=\[error, message\]\)",
            ):
                await scraper._fetch_all_threads_from_api("test-token")


class TestContractDiagnostics:
    """Verify shared contract diagnostics are stable and informative."""

    def test_describe_payload_shape_reports_mapping_keys(self):
        """Test payload-shape summaries help diagnose schema drift."""

        assert describe_payload_shape({"error": "broken", "message": "changed"}) == (
            "object(keys=[error, message])"
        )
