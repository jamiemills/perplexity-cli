"""Behavioural boundary tests for upstream payload contract helpers."""

from __future__ import annotations

import pytest

from perplexity_cli.utils.exceptions import UpstreamSchemaError
from perplexity_cli.utils.upstream_contracts import (
    parse_thread_list_payload,
    parse_upload_url_response,
    require_list,
    require_mapping,
)


class TestRequireMappingContract:
    """``require_mapping`` rejection diagnostics."""

    def test_non_mapping_message_is_exact(self) -> None:
        """A scalar payload yields the full context, kind, shape and detail text."""
        with pytest.raises(UpstreamSchemaError) as exc_info:
            require_mapping(42, "ctx", detail="extra")
        assert str(exc_info.value) == "ctx: expected object, got int (extra)"

    def test_mapping_payload_returns_identity(self) -> None:
        """A mapping passes through unchanged."""
        payload: dict[str, object] = {"a": 1}
        assert require_mapping(payload, "ctx") is payload


class TestRequireListContract:
    """``require_list`` rejection diagnostics."""

    def test_non_list_message_is_exact(self) -> None:
        """A scalar payload yields the full context, kind, shape and detail text."""
        with pytest.raises(UpstreamSchemaError) as exc_info:
            require_list(42, "ctx", detail="extra")
        assert str(exc_info.value) == "ctx: expected array, got int (extra)"

    def test_dict_payload_lists_first_five_sorted_keys(self) -> None:
        """Dict payloads are described by their first five sorted keys only."""
        payload = {f"k{i}": i for i in range(6)}
        with pytest.raises(UpstreamSchemaError) as exc_info:
            require_list(payload, "ctx")
        assert str(exc_info.value) == ("ctx: expected array, got object(keys=[k0, k1, k2, k3, k4])")


class TestParseUploadUrlResponseContract:
    """``parse_upload_url_response`` error diagnostics at each nesting level."""

    def test_top_level_non_mapping_message_is_exact(self) -> None:
        """A scalar response names the upload-URL context with no detail suffix."""
        with pytest.raises(UpstreamSchemaError) as exc_info:
            parse_upload_url_response(42)
        assert str(exc_info.value) == (
            "Malformed upload URL response from upstream API: expected object, got int"
        )

    def test_results_field_message_is_exact(self) -> None:
        """A non-mapping results field carries the documented detail text."""
        with pytest.raises(UpstreamSchemaError) as exc_info:
            parse_upload_url_response({"results": 42})
        assert str(exc_info.value) == (
            "Malformed upload results payload from upstream API: "
            "expected object, got int (missing or invalid 'results' field)"
        )

    def test_entry_message_includes_file_uuid(self) -> None:
        """A non-mapping entry carries the offending file_uuid detail."""
        with pytest.raises(UpstreamSchemaError) as exc_info:
            parse_upload_url_response({"results": {"uuid-1": 42}})
        assert str(exc_info.value) == (
            "Malformed upload result entry from upstream API: "
            "expected object, got int (file_uuid=uuid-1)"
        )


class TestParseThreadListPayloadContract:
    """``parse_thread_list_payload`` rejection diagnostics."""

    def test_entry_non_mapping_message_is_exact(self) -> None:
        """A scalar thread entry names the thread-entry context exactly."""
        with pytest.raises(UpstreamSchemaError) as exc_info:
            parse_thread_list_payload([42])
        assert str(exc_info.value) == (
            "Malformed thread entry in upstream API response: expected object, got int"
        )
