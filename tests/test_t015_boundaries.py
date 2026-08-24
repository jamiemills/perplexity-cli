"""Public-boundary regression tests for the T015 mutation scope."""

from __future__ import annotations

import asyncio
import base64
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import click
import pytest

from perplexity_cli.attachments.upload_manager import AttachmentUploader, _cancel_and_drain
from perplexity_cli.commands._ctx import as_int_or_none
from perplexity_cli.commands._schemas import build_command_schemas
from perplexity_cli.config.defaults import DEFAULT_UPLOAD_TIMEOUT
from perplexity_cli.utils.attachment_models import FileAttachment
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    SimpleResponse,
)
from perplexity_cli.utils.http_errors import (
    classify_http_error,
    classify_network_error,
    raise_http_status_error,
)
from perplexity_cli.utils.http_headers import build_perplexity_headers
from perplexity_cli.utils.rate_limiter import RateLimiter
from perplexity_cli.utils.session_factory import (
    IMPERSONATE_PROFILE,
    create_async_session,
    create_sync_session,
)
from tests.helpers.fake_transport import FakeHttpResponse, FakeHttpTransport
from tests.helpers.fake_uploader import FakeS3UploadClientFactory


def _attachment(filename: str = "note.txt") -> FileAttachment:
    """Create a valid attachment without touching the filesystem."""
    return FileAttachment(
        filename=filename,
        content_type="text/plain",
        data=base64.b64encode(b"content").decode("ascii"),
    )


class TestT015ContextAndSchemaBoundaries:
    """Check structured command helper outputs."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(0, 0), (-3, -3), (True, None), (False, None), ("3", None), (None, None)],
    )
    def test_as_int_or_none_distinguishes_ints_from_bools(
        self, value: object, expected: int | None
    ) -> None:
        assert as_int_or_none(value) == expected

    def test_command_schemas_have_object_outputs_and_known_properties(self) -> None:
        schemas = build_command_schemas()
        assert schemas
        assert all(entry["output"]["type"] == "object" for entry in schemas.values())
        assert schemas["query"]["output"]["properties"]["answer"]["type"] == "string"

    def test_rendered_schema_help_contains_both_envelope_shapes(self) -> None:
        from click import HelpFormatter

        from perplexity_cli.commands._help_sections import (
            HelpSectionConfig,
            add_help_sections,
        )

        def command() -> None:
            pass

        click_command = add_help_sections(
            click.command()(command), HelpSectionConfig(json_schema=True)
        )
        formatter = HelpFormatter()
        click_command.format_help(click.Context(click_command), formatter)
        rendered = formatter.getvalue()
        assert '"properties"' in rendered
        assert '"ok"' in rendered
        assert '"error"' in rendered


class TestT015HeaderAndSessionBoundaries:
    """Verify transport configuration reaches the concrete session boundary."""

    def test_header_builder_normalises_trailing_origin_slashes(self) -> None:
        headers = build_perplexity_headers(
            "token",
            {"csrftoken": "csrf"},
            header_extras=("application/json", "https://example.test///"),
        )
        assert headers == {
            "Content-Type": "application/json",
            "Origin": "https://example.test///",
            "Referer": "https://example.test/",
            "Accept": "application/json",
            "Authorization": "Bearer token",
            "X-CSRFToken": "csrf",
        }

    def test_session_defaults_and_explicit_timeout_reach_factories(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[dict[str, object]] = []

        class FakeSession:
            def __init__(self, **kwargs: object) -> None:
                calls.append(kwargs)

        monkeypatch.setattr("perplexity_cli.utils.session_factory._guard_curl_cffi", lambda: None)
        monkeypatch.setattr("perplexity_cli.utils.session_factory.Session", FakeSession)
        monkeypatch.setattr("perplexity_cli.utils.session_factory.AsyncSession", FakeSession)

        create_sync_session()
        create_sync_session(timeout=17)
        create_async_session()
        create_async_session(timeout=19)

        assert calls == [
            {"impersonate": IMPERSONATE_PROFILE, "timeout": 60},
            {"impersonate": IMPERSONATE_PROFILE, "timeout": 17},
            {"impersonate": IMPERSONATE_PROFILE, "timeout": 60},
            {"impersonate": IMPERSONATE_PROFILE, "timeout": 19},
        ]

    def test_explicit_uploader_base_url_is_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "perplexity_cli.attachments.upload_manager.get_perplexity_base_url",
            lambda: "https://configured.example",
        )
        uploader = AttachmentUploader("token", base_url="https://explicit.example")
        assert uploader.base_url == "https://explicit.example"


class TestT015RateLimiterBoundaries:
    """Exercise exact token and refill boundaries deterministically."""

    @pytest.mark.asyncio
    async def test_exactly_one_token_is_immediately_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now = 100.0
        sleeps: list[float] = []

        def monotonic() -> float:
            return now

        async def sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr("perplexity_cli.utils.rate_limiter.time.monotonic", monotonic)
        monkeypatch.setattr("perplexity_cli.utils.rate_limiter.asyncio.sleep", sleep)
        limiter = RateLimiter(requests_per_period=1, period_seconds=10.0)

        assert await limiter.acquire() == 0.0
        assert sleeps == []
        assert limiter.total_requests == 1
        assert limiter.get_stats()["current_tokens"] == 0.0

    @pytest.mark.asyncio
    async def test_wait_time_uses_remaining_tokens_divided_by_refill_rate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now = 100.0

        def monotonic() -> float:
            return now

        async def sleep(seconds: float) -> None:
            nonlocal now
            if seconds > 2.5:
                raise AssertionError("unexpected oversized refill wait")
            now += seconds

        monkeypatch.setattr("perplexity_cli.utils.rate_limiter.time.monotonic", monotonic)
        monkeypatch.setattr("perplexity_cli.utils.rate_limiter.asyncio.sleep", sleep)
        limiter = RateLimiter(requests_per_period=2, period_seconds=10.0)
        await limiter.acquire()
        now += 2.5
        await limiter.acquire()

        wait = await limiter.acquire()

        assert wait == pytest.approx(2.5)
        assert limiter.total_wait_time == pytest.approx(2.5)

    @pytest.mark.asyncio
    async def test_available_token_consumption_never_underflows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now = 100.0

        def monotonic() -> float:
            return now

        async def sleep(seconds: float) -> None:
            nonlocal now
            now += seconds

        monkeypatch.setattr("perplexity_cli.utils.rate_limiter.time.monotonic", monotonic)
        monkeypatch.setattr("perplexity_cli.utils.rate_limiter.asyncio.sleep", sleep)
        limiter = RateLimiter(requests_per_period=2, period_seconds=10.0)
        await limiter.acquire()
        now += 2.5

        assert await limiter.acquire() == 0.0
        assert limiter.get_stats()["current_tokens"] == pytest.approx(0.5)


class TestT015HttpBoundaries:
    """Check structured HTTP conversion and classification contracts."""

    def test_raise_http_status_error_preserves_request_and_response_metadata(self) -> None:
        response = SimpleNamespace(
            url="https://example.test/api",
            content="body",
            status_code=418,
            headers={"X-Test": "yes"},
        )

        with pytest.raises(PerplexityHTTPStatusError) as caught:
            raise_http_status_error(response, method="GET")

        error = caught.value
        assert error.request.method == "GET"
        assert error.request.url == "https://example.test/api"
        assert error.response.status_code == 418
        assert error.response.headers == {"X-Test": "yes"}
        assert error.response.text == "body"
        assert error.response.request is error.request

    @pytest.mark.parametrize(
        ("status", "code", "has_fix"),
        [
            (401, "authentication_required", True),
            (403, "permission_denied", False),
            (429, "rate_limited", True),
            (500, "network_error", True),
            (404, "network_error", False),
        ],
    )
    def test_http_classification_uses_status_taxonomy(
        self, status: int, code: str, has_fix: bool
    ) -> None:
        error = PerplexityHTTPStatusError("ignored", response=SimpleResponse(status_code=status))
        actual_code, _message, fix = classify_http_error(error)
        assert actual_code.value == code
        assert (fix is not None) is has_fix

    def test_network_classification_is_structured(self) -> None:
        code, _message, fix = classify_network_error(PerplexityRequestError("ignored"))
        assert code.value == "network_error"
        assert fix is not None


class TestT015UploadBoundary:
    """Verify the public upload workflow forwards and validates transport data."""

    @pytest.mark.asyncio
    async def test_upload_workflow_forwards_metadata_and_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        transport = FakeHttpTransport(
            FakeHttpResponse(
                json_data={
                    "results": {
                        "00000000-0000-0000-0000-000000000001": {
                            "fields": {"key": "uploads/note.txt"},
                            "s3_object_url": "https://s3.example/note.txt",
                        }
                    }
                }
            )
        )
        uploader = AttachmentUploader("token", base_url="https://api.example")
        file_uuid = uuid.UUID("00000000-0000-0000-0000-000000000001")
        monkeypatch.setattr(
            "perplexity_cli.attachments.upload_manager.uuid.uuid4", lambda: file_uuid
        )
        session_timeouts: list[object] = []

        def create_session(timeout: object = None) -> FakeHttpTransport:
            session_timeouts.append(timeout)
            return transport

        monkeypatch.setattr(uploader, "_create_async_session", create_session)
        monkeypatch.setattr(
            uploader,
            "_upload_batch",
            AsyncMock(return_value=["https://s3.example/note.txt"]),
        )

        urls = await uploader.upload_files([_attachment()])

        assert urls == ["https://s3.example/note.txt"]
        request_file = transport.last_post.kwargs["json"]["files"][
            "00000000-0000-0000-0000-000000000001"
        ]
        assert request_file["file_size"] == 7
        assert transport.last_post.kwargs["headers"]["Authorization"] == "Bearer token"
        assert session_timeouts == [DEFAULT_UPLOAD_TIMEOUT]

    @pytest.mark.asyncio
    async def test_upload_workflow_forwards_endpoint_and_decoded_multipart_bytes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        file_uuid = uuid.UUID("00000000-0000-0000-0000-000000000002")
        upload_endpoint = "https://api.example/upload-urls"
        transport = FakeHttpTransport(
            FakeHttpResponse(
                json_data={
                    "results": {
                        str(file_uuid): {
                            "fields": {"key": "uploads/note.txt"},
                            "s3_object_url": "https://s3.example/note.txt",
                        }
                    }
                }
            )
        )
        s3_factory = FakeS3UploadClientFactory(FakeHttpResponse(status_code=204))
        uploader = AttachmentUploader("token", base_url="https://api.example")
        monkeypatch.setattr(
            "perplexity_cli.attachments.upload_manager.uuid.uuid4", lambda: file_uuid
        )
        monkeypatch.setattr(
            "perplexity_cli.attachments.upload_manager.get_upload_url_endpoint",
            lambda: upload_endpoint,
        )
        session_timeouts: list[object] = []
        s3_timeouts: list[object] = []

        def create_session(timeout: object = None) -> FakeHttpTransport:
            session_timeouts.append(timeout)
            return transport

        def get_s3_factory() -> FakeS3UploadClientFactory:
            def create_client(**kwargs: object) -> object:
                s3_timeouts.append(kwargs.get("timeout"))
                return s3_factory()

            return create_client  # type: ignore[return-value]

        monkeypatch.setattr(uploader, "_create_async_session", create_session)
        monkeypatch.setattr(
            "perplexity_cli.attachments.upload_manager._get_httpx_async_client_factory",
            get_s3_factory,
        )

        urls = await uploader.upload_files([_attachment()])

        assert urls == ["https://s3.example/note.txt"]
        assert transport.last_post.url == upload_endpoint
        sent_file = s3_factory.last_client.posts[0].kwargs["files"]["file"]
        assert sent_file == ("note.txt", b"content", "text/plain")
        assert session_timeouts == [DEFAULT_UPLOAD_TIMEOUT]
        assert s3_timeouts == [DEFAULT_UPLOAD_TIMEOUT]

    @pytest.mark.asyncio
    async def test_cancel_and_drain_finishes_pending_siblings(self) -> None:
        pending = asyncio.Event()

        async def wait_forever() -> None:
            await pending.wait()

        tasks = [asyncio.create_task(wait_forever()) for _ in range(2)]
        try:
            await asyncio.wait_for(_cancel_and_drain(tasks), timeout=0.1)
            assert all(task.cancelled() for task in tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
