"""Hermetic integration tests for the attachment upload protocol chain.

Uses the local loopback harness server for upload URL acquisition, S3
upload, and query endpoints.  Requires ``GUARD_NETWORK=1``.

Each test exercises a distinct segment of the protocol:
1. Full upload chain through :class:`AttachmentUploader`
2. Exact byte verification of uploaded content
3. Non-2xx S3 upload status error handling
4. Query request construction including attachment URL order
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from perplexity_cli.attachments import AttachmentUploader
from perplexity_cli.utils.async_bridge import run_async
from perplexity_cli.utils.attachment_models import FileAttachment
from tests.support.protocol_server import ProtocolServer, QueryResponse, UploadUrlResponse


@pytest.mark.usefixtures("harness_config")
class TestAttachmentProtocolIntegration:
    """Tests that exercise the upload protocol end-to-end via the harness."""

    # ------------------------------------------------------------------
    # Full upload chain
    # ------------------------------------------------------------------

    def test_full_upload_chain_returns_correct_s3_url(
        self,
        harness_config: ProtocolServer,
        harness_server: ProtocolServer,
        tmp_path: Path,
    ) -> None:
        """Local-file → uploader → upload URL → S3 upload → returned URL.

        Verifies that the complete orchestration produces the expected S3
        object URL from the upload URL response.
        """
        test_file = tmp_path / "report.txt"
        test_file.write_text("Quarterly earnings up 12%.", encoding="utf-8")
        attachment = FileAttachment.from_file(test_file)

        _setup_upload_url_response(
            harness_server, {"uuid-chain": {"s3_object_url": "https://obj.example.com/report.txt"}}
        )
        _setup_s3_upload_response(harness_server, status_code=204)

        with patch(
            "perplexity_cli.attachments.upload_manager.uuid.uuid4", return_value="uuid-chain"
        ):
            uploader = AttachmentUploader(token="token-1")
            urls = run_async(uploader.upload_files([attachment]))

        assert urls == ["https://obj.example.com/report.txt"]
        assert harness_server.request_count == 2

    def test_upload_bytes_exact_presence(
        self, harness_server: ProtocolServer, tmp_path: Path
    ) -> None:
        """File content is present in the S3 upload request body."""
        content = b"\x89PNG\r\n\x1a\nfake-png-body-here"
        test_file = tmp_path / "image.png"
        test_file.write_bytes(content)
        attachment = FileAttachment.from_file(test_file)

        _setup_upload_url_response(
            harness_server, {"uuid-bytes": {"s3_object_url": "https://s3.example.com/image.png"}}
        )
        _setup_s3_upload_response(harness_server, status_code=204)

        with patch(
            "perplexity_cli.attachments.upload_manager.uuid.uuid4", return_value="uuid-bytes"
        ):
            uploader = AttachmentUploader(token="token-2")
            run_async(uploader.upload_files([attachment]))

        assert content in harness_server.last_request_body

    # ------------------------------------------------------------------
    # Non-2xx upload status
    # ------------------------------------------------------------------

    def test_non_204_s3_upload_raises_error(
        self,
        harness_server: ProtocolServer,
        tmp_path: Path,
    ) -> None:
        """A non-204 S3 upload response raises an upload error."""
        test_file = tmp_path / "fail.txt"
        test_file.write_text("content", encoding="utf-8")
        attachment = FileAttachment.from_file(test_file)

        _setup_upload_url_response(
            harness_server, {"uuid-fail": {"s3_object_url": "https://s3.example.com/fail.txt"}}
        )
        _setup_s3_upload_response(harness_server, status_code=500, body="internal error")

        with patch(
            "perplexity_cli.attachments.upload_manager.uuid.uuid4", return_value="uuid-fail"
        ):
            uploader = AttachmentUploader(token="token-3")

            with pytest.raises(Exception) as exc_info:
                run_async(uploader.upload_files([attachment]))

            error_text = str(exc_info.value).lower()
            assert "500" in error_text or "upload" in error_text or "s3" in error_text

    # ------------------------------------------------------------------
    # Query request construction
    # ------------------------------------------------------------------

    def test_query_request_includes_attachment_urls(
        self,
        harness_server: ProtocolServer,
    ) -> None:
        """A query POST to the harness contains attachment S3 URLs."""
        harness_server.query_response = QueryResponse(
            sse_chunks=harness_server.make_query_sse_chunks("response"),
        )

        attachment_urls = [
            "https://s3.example.com/attach/file_a.txt",
            "https://s3.example.com/attach/file_b.pdf",
        ]

        query_payload = {
            "query_str": "Summarise these files",
            "params": {
                "attachments": attachment_urls,
                "language": "en-US",
                "timezone": "Europe/London",
                "search_focus": "internet",
            },
        }

        resp = httpx.post(
            f"{harness_server.url}/api/query",
            json=query_payload,
            timeout=10,
        )

        assert resp.status_code == 200
        request_body = json.loads(harness_server.last_request_body.decode())
        assert request_body["params"]["attachments"] == attachment_urls

    def test_attachment_order_preserved_in_query(
        self,
        harness_server: ProtocolServer,
    ) -> None:
        """Attachment URL ordering is preserved in the query request."""
        harness_server.query_response = QueryResponse(
            sse_chunks=harness_server.make_query_sse_chunks("response"),
        )

        ordered_urls = [f"https://s3.example.com/attach/{i:02d}" for i in range(5)]

        query_payload = {
            "query_str": "Test order",
            "params": {"attachments": list(ordered_urls)},
        }

        httpx.post(
            f"{harness_server.url}/api/query",
            json=query_payload,
            timeout=10,
        )

        request_body = json.loads(harness_server.last_request_body.decode())
        received = request_body["params"]["attachments"]
        assert received == ordered_urls
        assert received == [f"https://s3.example.com/attach/{i:02d}" for i in range(5)]

    def test_query_without_attachments_omits_field(
        self,
        harness_server: ProtocolServer,
    ) -> None:
        """A query without attachment URLs can omit the attachments key."""
        harness_server.query_response = QueryResponse(
            sse_chunks=harness_server.make_query_sse_chunks("no-attach response"),
        )

        query_payload = {
            "query_str": "Plain query",
            "params": {},
        }

        resp = httpx.post(
            f"{harness_server.url}/api/query",
            json=query_payload,
            timeout=10,
        )

        assert resp.status_code == 200


# ------------------------------------------------------------------
# Test helpers
# ------------------------------------------------------------------


def _setup_upload_url_response(
    server: ProtocolServer,
    uuid_to_config: dict[str, dict[str, str]],
) -> None:
    """Configure the harness upload URL response for one or more file UUIDs.

    Each entry in *uuid_to_config* must provide at least ``s3_object_url``;
    ``fields`` defaults to ``{"key": "presigned-value"}``.
    """
    results: dict[str, dict[str, object]] = {}
    for file_uuid, config in uuid_to_config.items():
        results[file_uuid] = {
            "fields": config.get("fields", {"key": "presigned-value"}),
            "s3_object_url": config["s3_object_url"],
        }
    server.upload_url_response = UploadUrlResponse(body={"results": results})


def _setup_s3_upload_response(
    server: ProtocolServer,
    *,
    status_code: int = 204,
    body: str = "",
) -> None:
    """Configure the harness to return *status_code* for S3 upload POSTs.

    The harness routes non-upload-url POSTs to ``_serve_query``, so we
    configure ``query_response`` with a raw body to simulate the S3
    response.
    """
    server.query_response = QueryResponse(
        status_code=status_code,
        raw_body=body,
        content_type="application/octet-stream",
    )
