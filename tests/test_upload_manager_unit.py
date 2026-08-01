"""Unit tests for upload manager helper functions."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from perplexity_cli.attachments.upload_manager import (
    _diagnose_upload_entry_error,
    _extract_error_response_text,
    _has_usable_fields,
    _has_usable_object_url,
    _is_valid_presigned_entry,
    _require_upload_fields,
    _validate_s3_object_url,
    _validate_upload_uuid_bijection,
)
from perplexity_cli.utils.exceptions import UpstreamSchemaError
from tests.helpers.fake_transport import FakeHttpResponse


class TestExtractErrorResponseText:
    """Tests for _extract_error_response_text()."""

    def test_extracts_text_from_response(self) -> None:
        response = FakeHttpResponse(text="Error occurred")
        result = _extract_error_response_text(response)
        assert result == "Error occurred"

    def test_truncates_to_500_chars(self) -> None:
        response = FakeHttpResponse(text="x" * 600)
        result = _extract_error_response_text(response)
        assert len(result) == 500

    def test_falls_back_to_content_when_text_empty(self) -> None:
        response = FakeHttpResponse(text="", content=b"binary error")
        result = _extract_error_response_text(response)
        assert "binary error" in result

    def test_handles_text_none(self) -> None:
        response = FakeHttpResponse(text=None, content=b"fallback")
        result = _extract_error_response_text(response)
        assert "fallback" in result
        assert len(result) <= 500

    def test_handles_attribute_error(self) -> None:
        # A spec-restricted Mock with no attributes exercises the
        # AttributeError fallback path that FakeHttpResponse cannot model.
        response = Mock(spec_set=[])
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


class TestRequireUploadFields:
    """Tests for the fail-closed _require_upload_fields()."""

    def test_extracts_fields_dict(self) -> None:
        result = _require_upload_fields({"fields": {"key": "val"}})
        assert result == {"key": "val"}

    def test_raises_when_fields_missing(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="fields"):
            _require_upload_fields({})

    def test_raises_when_fields_is_none(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="fields"):
            _require_upload_fields({"fields": None})

    def test_raises_when_fields_is_empty_dict(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="fields"):
            _require_upload_fields({"fields": {}})

    def test_raises_when_fields_not_a_dict(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="fields"):
            _require_upload_fields({"fields": "not a dict"})


class TestValidateS3ObjectUrl:
    """Tests for the fail-closed _validate_s3_object_url()."""

    def test_passes_when_url_is_valid_string(self) -> None:
        _validate_s3_object_url({"s3_object_url": "https://s3.amazonaws.com/bucket/key"})

    def test_raises_when_url_is_none(self) -> None:
        with pytest.raises(UpstreamSchemaError):
            _validate_s3_object_url({"s3_object_url": None})

    def test_raises_when_url_is_missing(self) -> None:
        with pytest.raises(UpstreamSchemaError):
            _validate_s3_object_url({})

    def test_raises_when_url_is_empty(self) -> None:
        with pytest.raises(UpstreamSchemaError):
            _validate_s3_object_url({"s3_object_url": ""})

    def test_raises_when_url_is_not_string(self) -> None:
        with pytest.raises(UpstreamSchemaError):
            _validate_s3_object_url({"s3_object_url": 123})


class TestHasUsableFields:
    """Tests for _has_usable_fields()."""

    def test_non_empty_mapping(self) -> None:
        assert _has_usable_fields({"fields": {"key": "x"}}) is True

    def test_empty_mapping(self) -> None:
        assert _has_usable_fields({"fields": {}}) is False

    def test_non_mapping(self) -> None:
        assert _has_usable_fields({"fields": []}) is False

    def test_missing(self) -> None:
        assert _has_usable_fields({}) is False


class TestHasUsableObjectUrl:
    """Tests for _has_usable_object_url()."""

    def test_non_empty_string(self) -> None:
        assert _has_usable_object_url({"s3_object_url": "https://s3.example.com/x"}) is True

    def test_empty_string(self) -> None:
        assert _has_usable_object_url({"s3_object_url": ""}) is False

    def test_whitespace_string(self) -> None:
        assert _has_usable_object_url({"s3_object_url": "   "}) is False

    def test_non_string(self) -> None:
        assert _has_usable_object_url({"s3_object_url": 123}) is False


class TestIsValidPresignedEntry:
    """Fail-closed shape checks on a single upload result entry."""

    def test_valid_entry(self) -> None:
        assert (
            _is_valid_presigned_entry(
                {
                    "fields": {"key": "x"},
                    "s3_object_url": "https://s3.example.com/x.txt",
                }
            )
            is True
        )

    def test_rate_limited_entry_is_invalid(self) -> None:
        assert (
            _is_valid_presigned_entry(
                {
                    "fields": {"key": "x"},
                    "s3_object_url": "https://s3.example.com/x.txt",
                    "rate_limited": True,
                }
            )
            is False
        )

    def test_error_entry_is_invalid(self) -> None:
        assert (
            _is_valid_presigned_entry(
                {
                    "fields": {"key": "x"},
                    "s3_object_url": "https://s3.example.com/x.txt",
                    "error": "boom",
                }
            )
            is False
        )

    def test_missing_fields_is_invalid(self) -> None:
        assert _is_valid_presigned_entry({"s3_object_url": "https://s3.example.com/x.txt"}) is False

    def test_empty_fields_is_invalid(self) -> None:
        assert (
            _is_valid_presigned_entry(
                {"fields": {}, "s3_object_url": "https://s3.example.com/x.txt"}
            )
            is False
        )

    def test_missing_object_url_is_invalid(self) -> None:
        assert _is_valid_presigned_entry({"fields": {"key": "x"}}) is False

    def test_empty_object_url_is_invalid(self) -> None:
        assert _is_valid_presigned_entry({"fields": {"key": "x"}, "s3_object_url": ""}) is False


class TestValidateUploadUuidBijection:
    """Tests for the exact requested/result UUID bijection check."""

    def test_exact_match_passes(self) -> None:
        _validate_upload_uuid_bijection({"a", "b"}, {"b", "a"})

    def test_empty_sets_pass(self) -> None:
        _validate_upload_uuid_bijection(set(), set())

    def test_missing_result_rejected(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="missing"):
            _validate_upload_uuid_bijection({"a", "b"}, {"a"})

    def test_extra_result_rejected(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="extra"):
            _validate_upload_uuid_bijection({"a"}, {"a", "b"})

    def test_missing_and_extra_rejected(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="missing"):
            _validate_upload_uuid_bijection({"a", "b"}, {"c", "d"})
