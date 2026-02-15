"""Test file attachment JSON serialization in HTTP requests."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from perplexity_cli.api.client import SSEClient
from perplexity_cli.api.models import FileAttachment


class TestFileAttachmentRequestSerialization:
    """Test file attachment serialization in HTTP requests."""

    def test_stream_post_with_attachments_json_serializable(self):
        """Test that requests with file attachments are JSON serializable."""
        # Create test file attachment
        test_file = Path("/tmp/test_attachment_req.txt")
        test_file.write_text("Test content for attachment", encoding="utf-8")
        attachment = FileAttachment.from_file(test_file)

        # Prepare request data with attachment (as endpoints.py would do)
        json_data = {
            "query_str": "Test query",
            "params": {
                "language": "en-US",
                "timezone": "Europe/London",
                "attachments": [attachment.model_dump(mode="json")],
                # ... other params
            },
        }

        # Verify JSON serialization works
        try:
            json_str = json.dumps(json_data)
            assert len(json_str) > 0
            # Verify we can deserialize it
            deserialized = json.loads(json_str)
            assert deserialized["params"]["attachments"][0]["filename"] == "test_attachment_req.txt"
        except TypeError as e:
            pytest.fail(f"JSON serialization failed: {e}")

    def test_stream_post_with_attachments_sent_correctly(self):
        """Test that file attachments are sent correctly in stream_post."""
        client = SSEClient(token="test-token")

        # Create test file attachment
        test_file = Path("/tmp/test_attachment2_req.txt")
        test_file.write_text("Another test", encoding="utf-8")
        attachment = FileAttachment.from_file(test_file)

        # Prepare request data with attachment
        json_data = {
            "query_str": "Test query",
            "params": {
                "language": "en-US",
                "attachments": [attachment.model_dump(mode="json")],
            },
        }

        # Mock curl_cffi response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.reason = "OK"
        mock_response.headers = {}
        mock_response.iter_lines.return_value = [
            b'data: {"test": "message"}',
            b'data: {"final": true}',
        ]

        captured_json_data = []

        def mock_stream(method, url, **kwargs):
            # Capture the json parameter
            if "json" in kwargs:
                captured_json_data.append(kwargs["json"])
            return mock_response.__enter__()

        mock_response.__enter__ = lambda self: mock_response
        mock_response.__exit__ = lambda self, *args: None

        with patch.object(client, "_get_client") as mock_get_client:
            mock_session = Mock()
            mock_session.stream = Mock(side_effect=mock_stream)
            mock_get_client.return_value = mock_session

            # Call stream_post
            list(client.stream_post("https://example.com/api", json_data))

            # Verify json data was captured
            assert len(captured_json_data) > 0
            captured = captured_json_data[0]

            # Verify attachment is present and correct
            assert "params" in captured
            assert "attachments" in captured["params"]
            assert len(captured["params"]["attachments"]) == 1
            assert captured["params"]["attachments"][0]["filename"] == "test_attachment2_req.txt"
            assert captured["params"]["attachments"][0]["content_type"] == "text/plain"

            # Verify it would be JSON serializable
            json_str = json.dumps(captured)
            assert len(json_str) > 0
