"""Unit tests for upload manager helper functions."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from perplexity_cli.attachments.upload_manager import (
    _diagnose_upload_entry_error,
    _extract_error_response_text,
    _normalise_upload_fields,
    _validate_s3_object_url,
)
from perplexity_cli.utils.exceptions import UpstreamSchemaError


class TestExtractErrorResponseText:
    """Tests for _extract_error_response_text()."""

    def test_extracts_text_from_response(self) -> None:
        response = Mock()
        response.text = "Error occurred"
        result = _extract_error_response_text(response)
        assert result == "Error occurred"

    def test_truncates_to_500_chars(self) -> None:
        response = Mock()
        response.text = "x" * 600
        result = _extract_error_response_text(response)
        assert len(result) == 500

    def test_falls_back_to_content_when_text_empty(self) -> None:
        response = Mock()
        response.text = ""
        response.content = b"binary error"
        result = _extract_error_response_text(response)
        assert "binary error" in result

    def test_handles_text_none(self) -> None:
        response = Mock()
        response.text = None
        response.content = b"fallback"
        result = _extract_error_response_text(response)
        assert "fallback" in result
        assert len(result) <= 500

    def test_handles_attribute_error(self) -> None:
        response = Mock(spec=[])
        result = _extract_error_response_text(response)
        assert result == ""


class TestDiagnoseUploadEntryError:
    """Tests for _diagnose_upload_entry_error()."""

    def test_rate_limited_message(self) -> None:
        result = _diagnose_upload_entry_error({"rate_limited": True})
        assert "quota exhausted" in result
        assert "settings" in result.lower()

    def test_api_error_message(self) -> None:
        result = _diagnose_upload_entry_error({"error": "Invalid file type"})
        assert "Invalid file type" in result
        assert "failed to generate upload URL" in result

    def test_empty_response_message(self) -> None:
        result = _diagnose_upload_entry_error({})
        assert "empty presigned URL" in result

    def test_no_rate_limited_or_error_key(self) -> None:
        result = _diagnose_upload_entry_error({"other": "value"})
        assert "empty presigned URL" in result


class TestNormaliseUploadFields:
    """Tests for _normalise_upload_fields()."""

    def test_extracts_fields_dict(self) -> None:
        result = _normalise_upload_fields({"fields": {"key": "val"}})
        assert result == {"key": "val"}

    def test_returns_empty_dict_when_fields_missing(self) -> None:
        result = _normalise_upload_fields({})
        assert result == {}

    def test_returns_empty_dict_when_fields_is_none(self) -> None:
        result = _normalise_upload_fields({"fields": None})
        assert result == {}

    def test_returns_empty_dict_when_fields_not_a_dict(self) -> None:
        result = _normalise_upload_fields({"fields": "not a dict"})
        assert result == {}


class TestValidateS3ObjectUrl:
    """Tests for _validate_s3_object_url()."""

    def test_passes_when_url_is_valid_string(self) -> None:
        _validate_s3_object_url({"s3_object_url": "https://s3.amazonaws.com/bucket/key"})

    def test_passes_when_url_is_none(self) -> None:
        _validate_s3_object_url({"s3_object_url": None})

    def test_passes_when_url_is_missing(self) -> None:
        _validate_s3_object_url({})

    def test_raises_when_url_is_not_string(self) -> None:
        with pytest.raises(UpstreamSchemaError):
            _validate_s3_object_url({"s3_object_url": 123})
