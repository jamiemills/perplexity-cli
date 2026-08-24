"""Behavioural boundaries for thread cache, date, model, and export paths."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from perplexity_cli.threads.cache_manager import ThreadCacheManager
from perplexity_cli.threads.date_parser import (
    _check_after_start,
    _check_before_end,
    _parse_day_end,
    _parse_day_start,
    is_in_date_range,
    parse_absolute_date_string,
    to_iso8601,
)
from perplexity_cli.threads.exporter import (
    ThreadRecord,
    _neutralise_cell,
    write_threads_csv,
)
from perplexity_cli.threads.models import (
    CacheContent,
    CacheFormat,
    CacheMetadata,
    _validate_thread_dict,
    parse_iso8601_timestamp,
    parse_strict_date,
    validate_date_args,
)
from perplexity_cli.threads.utils import convert_cache_dicts_to_thread_records
from perplexity_cli.utils.exceptions import ConfigurationError, UpstreamSchemaError


def _record(
    title: str = "title",
    url: str = "https://example.test/1",
    created_at: str = "2025-12-23T13:51:50Z",
) -> ThreadRecord:
    return ThreadRecord(title=title, url=url, created_at=created_at)


def test_date_parser_preserves_timezone_and_exact_day_boundaries() -> None:
    """Date helpers preserve UTC and include both ends of a day."""
    value = datetime(2025, 12, 23, 13, 51, 50, tzinfo=UTC)

    assert (
        parse_absolute_date_string("Tuesday, December 23, 2025 at 1:51:50 PM Greenwich Mean Time")
        == value
    )
    assert _parse_day_start("2025-12-23", UTC) == datetime(2025, 12, 23, tzinfo=UTC)
    assert _parse_day_start("2025-12-23 15:14:13", UTC) == datetime(2025, 12, 23, tzinfo=UTC)
    offset = timezone(timedelta(hours=2))
    assert _parse_day_start("2025-12-23 15:14:13", offset).tzinfo == offset
    assert _parse_day_end("2025-12-23", UTC) == datetime(
        2025, 12, 23, 23, 59, 59, 999999, tzinfo=UTC
    )
    assert _check_after_start(value, "2025-12-23")
    assert _check_before_end(value, "2025-12-23")
    assert is_in_date_range(value, "2025-12-23", "2025-12-23")
    assert _check_before_end(datetime(2025, 12, 23, 23, 59, 59, 999999, tzinfo=UTC), "2025-12-23")


def test_date_parser_rejects_missing_timezone_and_malformed_ranges() -> None:
    """Date parsing reports invalid input at the public range boundary."""
    with pytest.raises(ValueError, match="Failed to parse date string"):
        parse_absolute_date_string("not a date")
    with pytest.raises(ValueError, match="Parsed datetime has no timezone info"):
        parse_absolute_date_string("2025-12-23 13:51:50")
    with pytest.raises(ValueError, match="Invalid date format"):
        is_in_date_range(datetime.now(UTC), "not-a-date", None)
    assert _check_after_start(datetime.now(UTC), None)
    assert _check_before_end(datetime.now(UTC), None)


def test_to_iso8601_normalises_naive_and_offset_datetimes() -> None:
    """ISO output assumes UTC for naive values and converts offsets."""
    assert to_iso8601(datetime(2025, 12, 23, 13, 51, 50)) == "2025-12-23T13:51:50Z"
    assert to_iso8601(datetime(2025, 12, 23, 15, 51, 50, tzinfo=UTC)) == ("2025-12-23T15:51:50Z")
    assert to_iso8601(datetime(2025, 12, 23, 15, 51, 50, tzinfo=UTC)) == ("2025-12-23T15:51:50Z")
    assert to_iso8601(datetime(2025, 12, 23, 15, 51, 50, tzinfo=UTC)).endswith("Z")
    aware = Mock()
    aware.tzinfo = object()
    converted = Mock()
    converted.isoformat.return_value = "2025-12-23T15:51:50+00:00"
    aware.astimezone.return_value = converted
    assert to_iso8601(aware) == "2025-12-23T15:51:50Z"
    aware.astimezone.assert_called_once_with(UTC)


def test_models_parse_dates_and_validate_cache_shapes() -> None:
    """Thread cache models enforce strict dates, versions, and required fields."""
    assert parse_strict_date("2025-12-23") == date(2025, 12, 23)
    assert parse_iso8601_timestamp("2025-12-23T13:51:50Z").tzinfo is not None
    assert validate_date_args(None, "2025-12-23") == (None, date(2025, 12, 23))
    with pytest.raises(ValueError, match="expected YYYY-MM-DD"):
        parse_strict_date("2025-12-3")
    with pytest.raises(ValueError, match="Invalid date '2025-02-30'"):
        parse_strict_date("2025-02-30")
    with pytest.raises(ValueError, match="Invalid date range"):
        validate_date_args("2025-12-24", "2025-12-23")
    with pytest.raises(ValueError, match="Invalid ISO-8601"):
        parse_iso8601_timestamp("not-a-timestamp")

    now = datetime.now(UTC)
    metadata = CacheMetadata(last_sync_time=now, total_threads=0)
    assert metadata.total_threads == 0
    content = CacheContent(metadata=metadata, threads=[])
    assert content.threads == []
    outer = CacheFormat(cache="encrypted", created_at=now)
    assert outer.encrypted is True
    with pytest.raises(ValueError, match="cannot be in the future"):
        CacheMetadata(last_sync_time=datetime.max.replace(tzinfo=UTC))
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        CacheMetadata(last_sync_time=now, total_threads=-1)
    with pytest.raises(ValueError, match="Encrypted cache cannot be empty"):
        CacheFormat(cache=" ")


def test_models_reject_malformed_thread_entries() -> None:
    """Cache content rejects non-dictionaries and missing URL/title fields."""
    metadata = CacheMetadata(last_sync_time=datetime.now(UTC))
    with pytest.raises(ValueError, match="valid dictionary"):
        CacheContent(metadata=metadata, threads=["bad"])
    with pytest.raises(ValueError, match="must have a 'url'"):
        CacheContent(metadata=metadata, threads=[{"title": "title"}])
    with pytest.raises(ValueError, match="must have a 'title'"):
        CacheContent(metadata=metadata, threads=[{"url": "url"}])


def test_thread_shape_validation_preserves_distinct_errors() -> None:
    """Thread shape failures identify the rejected shape and valid items pass."""
    with pytest.raises(ValueError, match="Each thread must be a dictionary"):
        _validate_thread_dict("bad")
    with pytest.raises(ValueError) as invalid_shape:
        _validate_thread_dict("bad")
    assert str(invalid_shape.value) == "Each thread must be a dictionary"
    with pytest.raises(ValueError, match="Each thread must have a 'url' field"):
        _validate_thread_dict({"title": "title"})
    with pytest.raises(ValueError, match="Each thread must have a 'title' field"):
        _validate_thread_dict({"url": "url"})
    assert _validate_thread_dict({"title": "title", "url": "url"}) is True
    with pytest.raises(ValueError) as missing_url:
        _validate_thread_dict({"title": "title"})
    assert str(missing_url.value) == "Each thread must have a 'url' field"
    with pytest.raises(ValueError) as missing_title:
        _validate_thread_dict({"url": "url"})
    assert str(missing_title.value) == "Each thread must have a 'title' field"


def test_timestamp_parser_requires_uppercase_z() -> None:
    """Timestamp parsing accepts the cache spelling but not lowercase z."""
    assert parse_iso8601_timestamp("2025-12-23T13:51:50Z").tzinfo is not None
    with pytest.raises(ValueError, match="Invalid ISO-8601 timestamp"):
        parse_iso8601_timestamp("2025-12-23T13:51:50z")
    assert to_iso8601(datetime(2025, 12, 23, 15, 51, 50, tzinfo=UTC)) == ("2025-12-23T15:51:50Z")
    with patch("perplexity_cli.threads.models.datetime") as clock:
        parse_iso8601_timestamp("2025-12-23T13:51:50Z")
    clock.fromisoformat.assert_called_once_with("2025-12-23T13:51:50+00:00")


def test_export_neutralises_formula_prefixes_after_whitespace() -> None:
    """CSV cells beginning with spreadsheet formulas receive an apostrophe."""
    assert _neutralise_cell(" =SUM(A1)") == "' =SUM(A1)"
    assert _neutralise_cell("\t+formula") == "'\t+formula"
    assert _neutralise_cell("safe-value") == "safe-value"
    assert _neutralise_cell("\r\n@formula") == "'\r\n@formula"
    assert _neutralise_cell("\v=formula") == "\v=formula"
    assert _neutralise_cell("X=formula") == "X=formula"


def test_export_writes_exact_header_and_cells(tmp_path: Path) -> None:
    """CSV output preserves column order and neutralises every record field."""
    target = tmp_path / "threads.csv"
    result = write_threads_csv([_record("=title", "@url", "-date")], target)

    assert result == target
    assert target.read_text(encoding="utf-8") == ("created_at,title,url\n'-date,'=title,'@url\n")
    with pytest.raises(ValueError, match="empty records"):
        write_threads_csv([], target)
    with pytest.raises(ValueError) as empty:
        write_threads_csv([], target)
    assert str(empty.value) == "Cannot write CSV with empty records list"


def test_export_wraps_atomic_write_errors(tmp_path: Path) -> None:
    """CSV write failures retain the destination path and original cause."""
    target = tmp_path / "threads.csv"
    with patch("perplexity_cli.threads.exporter.atomic_write_text", side_effect=OSError("disk")):
        with pytest.raises(OSError, match="Failed to write CSV file to") as raised:
            write_threads_csv([_record()], target)
    assert isinstance(raised.value.__cause__, OSError)


def test_export_default_path_uses_timestamp_format() -> None:
    """Default CSV names include the current timestamp format."""
    with patch("perplexity_cli.threads.exporter.datetime") as clock:
        clock.now.return_value = datetime(2025, 12, 23, 13, 51, 50)
        result = write_threads_csv([_record()])
    assert result == Path("threads-2025-12-23-135150.csv")
    result.unlink()


def test_utils_converts_records_and_identifies_missing_fields() -> None:
    """Cache dictionaries convert to records without accepting malformed shapes."""
    records = convert_cache_dicts_to_thread_records(
        [{"title": "title", "url": "url", "created_at": "date"}]
    )
    assert records == [_record("title", "url", "date")]
    with pytest.raises(UpstreamSchemaError, match="Malformed cached thread record"):
        convert_cache_dicts_to_thread_records(["bad"])
    with pytest.raises(UpstreamSchemaError, match="missing url"):
        convert_cache_dicts_to_thread_records([{"title": "title", "created_at": "date"}])
    with pytest.raises(UpstreamSchemaError, match="missing created_at"):
        convert_cache_dicts_to_thread_records([{"title": "title", "url": "url"}])
    with pytest.raises(UpstreamSchemaError) as malformed:
        convert_cache_dicts_to_thread_records(["bad"])
    assert str(malformed.value) == "Malformed cached thread record"


def test_cache_metadata_uses_empty_and_min_max_paths(tmp_path: Path) -> None:
    """Cache metadata reports empty coverage and timestamp extrema."""
    manager = ThreadCacheManager(tmp_path / "cache.json")
    empty = manager._build_cache_metadata([])
    assert empty["oldest_thread_date"] is None
    assert empty["newest_thread_date"] is None
    assert empty["total_threads"] == 0
    assert set(empty) == {
        "last_sync_time",
        "oldest_thread_date",
        "newest_thread_date",
        "total_threads",
    }
    metadata = manager._build_cache_metadata(
        [_record(created_at="2025-12-22T00:00:00Z"), _record(created_at="2025-12-23T00:00:00Z")]
    )
    assert metadata["oldest_thread_date"] == "2025-12-22T00:00:00Z"
    assert metadata["newest_thread_date"] == "2025-12-23T00:00:00Z"
    assert metadata["total_threads"] == 2


def test_cache_save_builds_encrypted_outer_and_secure_mode(tmp_path: Path) -> None:
    """Cache save sends the complete encrypted wrapper to atomic storage."""
    manager = ThreadCacheManager(tmp_path / "cache.json")
    threads = [_record()]
    with (
        patch(
            "perplexity_cli.threads.cache_manager.encrypt_token", return_value="cipher"
        ) as encrypt,
        patch("perplexity_cli.threads.cache_manager.atomic_write_json") as write,
        patch.object(manager, "_build_cache_metadata", return_value={"sentinel": True}),
    ):
        manager.save_cache(threads)

    payload = write.call_args.args[1]
    assert json.loads(encrypt.call_args.args[0])["threads"] == [threads[0].model_dump()]
    assert payload["version"] == 1
    assert payload["encrypted"] is True
    assert payload["cache"] == "cipher"
    assert write.call_args.kwargs["mode"] == 0o600


def test_cache_load_validates_permissions_and_returns_json_model(tmp_path: Path) -> None:
    """Cache load verifies permissions, decrypts, validates, and logs success."""
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({"raw": True}), encoding="utf-8")
    manager = ThreadCacheManager(path)
    manager.logger = Mock()
    outer = Mock()
    content = Mock()
    content.model_dump.return_value = {"threads": []}
    with (
        patch.object(manager, "_verify_permissions") as verify,
        patch.object(manager, "_validate_outer_format", return_value=outer) as validate,
        patch.object(manager, "_decrypt_and_validate_cache", return_value=content) as decrypt,
    ):
        assert manager.load_cache() == {"threads": []}
    verify.assert_called_once_with()
    validate.assert_called_once_with({"raw": True})
    decrypt.assert_called_once_with(outer)
    content.model_dump.assert_called_once_with(mode="json")
    manager.logger.info.assert_called_once_with("Cache loaded from %s", "<redacted>/cache.json")


def test_cache_load_logs_and_wraps_os_errors(tmp_path: Path) -> None:
    """Cache read errors retain the original exception and traceback logging."""
    path = tmp_path / "cache.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o600)
    path.chmod(0o600)
    manager = ThreadCacheManager(path)
    manager.logger = Mock()
    with patch("builtins.open", side_effect=OSError("read failure")):
        with pytest.raises(OSError, match="Failed to load cache from") as raised:
            manager.load_cache()
    assert isinstance(raised.value.__cause__, OSError)
    assert manager.logger.error.call_args.kwargs["exc_info"] is True
    assert manager.logger.error.call_args.args[:2] == (
        "Failed to load cache: %s",
        raised.value.__cause__,
    )


def test_cache_load_missing_and_invalid_json_paths(tmp_path: Path) -> None:
    """Missing cache returns None while malformed JSON becomes an OSError."""
    manager = ThreadCacheManager(tmp_path / "missing.json")
    assert manager.load_cache() is None
    manager.cache_path.write_text("not-json", encoding="utf-8")
    manager.cache_path.chmod(0o600)
    with pytest.raises(OSError, match="Failed to load cache"):
        manager.load_cache()


def test_cache_save_includes_complete_outer_wrapper(tmp_path: Path) -> None:
    """Cache save includes all outer fields and the configured schema version."""
    manager = ThreadCacheManager(tmp_path / "cache.json")
    manager.logger = Mock()
    with (
        patch(
            "perplexity_cli.threads.cache_manager.encrypt_token", return_value="cipher"
        ) as encrypt,
        patch("perplexity_cli.threads.cache_manager.atomic_write_json") as write,
        patch.object(manager, "_build_cache_metadata", return_value={"sentinel": True}),
    ):
        manager.save_cache([_record()])
    inner = json.loads(encrypt.call_args.args[0])
    outer = write.call_args.args[1]
    assert inner == {
        "version": 1,
        "metadata": {"sentinel": True},
        "threads": [_record().model_dump()],
    }
    assert set(outer) == {"version", "encrypted", "cache", "created_at"}
    assert outer["created_at"].endswith("+00:00")


def test_cache_save_logs_redacted_path_and_thread_count(tmp_path: Path) -> None:
    """Successful cache saves log the redacted destination and count."""
    manager = ThreadCacheManager(tmp_path / "cache.json")
    manager.logger = Mock()
    with (
        patch("perplexity_cli.threads.cache_manager.encrypt_token", return_value="cipher"),
        patch("perplexity_cli.threads.cache_manager.atomic_write_json"),
    ):
        manager.save_cache([_record(), _record(url="fresh")])
    manager.logger.info.assert_called_once_with(
        "Cache saved to %s (%s threads)", "<redacted>/cache.json", 2
    )


def test_cache_save_wraps_atomic_write_errors(tmp_path: Path) -> None:
    """Cache save errors preserve the source error and traceback logging."""
    manager = ThreadCacheManager(tmp_path / "cache.json")
    manager.logger = Mock()
    with patch(
        "perplexity_cli.threads.cache_manager.atomic_write_json", side_effect=OSError("disk")
    ):
        with pytest.raises(OSError, match="Failed to save or set permissions") as raised:
            manager.save_cache([_record()])
    assert isinstance(raised.value.__cause__, OSError)
    manager.logger.error.assert_called_once_with(
        "Failed to save cache: %s", raised.value.__cause__, exc_info=True
    )


def test_cache_outer_and_inner_validation_preserve_configuration_errors(tmp_path: Path) -> None:
    """Outer encryption and decrypted content failures become configuration errors."""
    manager = ThreadCacheManager(tmp_path / "cache.json")
    with pytest.raises(ConfigurationError, match="not encrypted"):
        manager._validate_outer_format({"version": 1, "encrypted": False, "cache": "cipher"})
    with patch("perplexity_cli.threads.cache_manager.decrypt_token", return_value="{}"):
        with pytest.raises(ConfigurationError, match="Cache content has invalid format"):
            manager._decrypt_and_validate_cache(CacheFormat(cache="cipher"))


def test_cache_outer_validation_rejects_schema_and_payload_errors(tmp_path: Path) -> None:
    """Outer validation rejects unsupported versions and empty encrypted payloads."""
    manager = ThreadCacheManager(tmp_path / "cache.json")
    with pytest.raises(ConfigurationError) as invalid_version:
        manager._validate_outer_format({"version": 2, "encrypted": True, "cache": "cipher"})
    assert str(invalid_version.value) == "Cache file has invalid format"
    with pytest.raises(ConfigurationError) as empty_cache:
        manager._validate_outer_format({"version": 1, "encrypted": True, "cache": ""})
    assert str(empty_cache.value) == "Cache file has invalid format"


def test_cache_validation_logs_original_validation_errors(tmp_path: Path) -> None:
    """Cache validation logs retain the validation exception as an argument."""
    manager = ThreadCacheManager(tmp_path / "cache.json")
    manager.logger = Mock()
    with pytest.raises(ConfigurationError):
        manager._validate_outer_format({"version": 2, "encrypted": True, "cache": "cipher"})
    logged_error = manager.logger.exception.call_args.args[1]
    assert logged_error.__class__.__name__ == "ValidationError"
    assert manager.logger.exception.call_args.args[0] == ("Cache file has invalid outer format: %s")

    manager.logger.reset_mock()
    with pytest.raises(ConfigurationError) as not_encrypted:
        manager._validate_outer_format({"version": 1, "encrypted": False, "cache": "cipher"})
    assert str(not_encrypted.value) == (
        "Cache file is not encrypted. Cache may be corrupted. Consider deleting and rebuilding."
    )
    manager.logger.warning.assert_called_once_with("Cache file is not encrypted")

    manager.logger.reset_mock()
    with patch("perplexity_cli.threads.cache_manager.decrypt_token", return_value="{}"):
        with pytest.raises(ConfigurationError) as invalid_content:
            manager._decrypt_and_validate_cache(CacheFormat(cache="cipher"))
    assert str(invalid_content.value) == "Cache content has invalid format"
    logged_error = manager.logger.exception.call_args.args[1]
    assert logged_error.__class__.__name__ == "ValidationError"
    assert manager.logger.exception.call_args.args[0] == ("Cache content has invalid format: %s")


def test_cache_coverage_and_freshness_use_public_date_contract(tmp_path: Path) -> None:
    """Coverage and freshness distinguish missing, complete, and extended ranges."""
    manager = ThreadCacheManager(tmp_path / "cache.json")
    manager.load_cache = Mock(return_value=None)
    assert manager.get_cache_coverage() == (None, None)
    assert manager._parse_cache_coverage() is None
    assert manager.requires_fresh_data("2025-12-22", "2025-12-23") == (
        True,
        "2025-12-22",
        "2025-12-23",
    )

    manager.load_cache.return_value = {
        "metadata": {
            "oldest_thread_date": "2025-12-21T00:00:00Z",
            "newest_thread_date": "2025-12-23T00:00:00Z",
        }
    }
    assert manager._parse_cache_coverage() == (date(2025, 12, 21), date(2025, 12, 23))
    assert manager.requires_fresh_data("2025-12-21", "2025-12-22") == (False, None, None)
    assert manager.requires_fresh_data("2025-12-20", "2025-12-22") == (
        True,
        "2025-12-20",
        "2025-12-22",
    )

    manager.load_cache.return_value = {"metadata": {"oldest_thread_date": "old"}}
    assert manager._parse_cache_coverage() is None
    manager.load_cache.return_value = {"metadata": {"newest_thread_date": "new"}}
    assert manager._parse_cache_coverage() is None
    manager.load_cache.return_value = {}
    assert manager.get_cache_coverage() == (None, None)
    manager.load_cache.return_value = {"other": True}
    assert manager.get_cache_coverage() == (None, None)
    assert manager._parse_cache_coverage() is None


def test_cache_freshness_uses_utc_for_open_ended_requests(tmp_path: Path) -> None:
    """Open-ended cache requests use the current UTC calendar date."""
    manager = ThreadCacheManager(tmp_path / "cache.json")
    manager._parse_cache_coverage = Mock(return_value=(date(2025, 12, 20), date(2025, 12, 22)))
    with patch("perplexity_cli.threads.cache_manager.datetime") as clock:
        clock.now.return_value.date.return_value = date(2025, 12, 23)
        with patch.object(
            manager, "_calculate_fetch_range", return_value=(False, None, None)
        ) as calculate:
            manager.requires_fresh_data(None, None)
    assert calculate.call_args.args[1] == date(2025, 12, 23)
    clock.now.assert_called_once_with(UTC)


def test_cache_load_uses_utf8_and_logs_original_read_error(tmp_path: Path) -> None:
    """Cache reads use UTF-8 and error logs preserve the source exception."""
    path = tmp_path / "cache.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o600)
    manager = ThreadCacheManager(path)
    manager.logger = Mock()
    with patch("builtins.open", side_effect=OSError("read failure")) as open_file:
        with pytest.raises(OSError):
            manager.load_cache()
    open_file.assert_called_once_with(path, encoding="utf-8")
    assert manager.logger.error.call_args.args[1].args == ("read failure",)


def test_cache_merge_clear_and_permission_boundaries(tmp_path: Path) -> None:
    """Cache merge keeps cached duplicates, clear is idempotent, and permissions forward."""
    manager = ThreadCacheManager(tmp_path / "cache.json")
    manager.logger = Mock()
    cached = [_record("old", "same", "2025-12-22T00:00:00Z")]
    fetched = [
        _record("new", "same", "2025-12-23T00:00:00Z"),
        _record("fresh", "fresh", "2025-12-24T00:00:00Z"),
    ]
    merged = manager.merge_threads(cached, fetched)
    assert [(item.title, item.url) for item in merged] == [("fresh", "fresh"), ("old", "same")]

    manager.clear_cache()
    manager.cache_path.write_text("cache", encoding="utf-8")
    with patch("pathlib.Path.unlink") as unlink:
        manager.clear_cache()
    unlink.assert_called_once_with()
    manager.logger.info.assert_called_once_with("Cache cleared from %s", manager.cache_path)
    with patch("perplexity_cli.threads.cache_manager.verify_secure_permissions") as verify:
        manager._verify_permissions()
    verify.assert_called_once_with(
        manager.cache_path, expected_permissions=0o600, file_type="cache", logger=manager.logger
    )


def test_cache_clear_wraps_delete_errors(tmp_path: Path) -> None:
    """Cache deletion errors preserve the cause and traceback logging."""
    path = tmp_path / "cache.json"
    path.write_text("cache", encoding="utf-8")
    manager = ThreadCacheManager(path)
    manager.logger = Mock()
    with patch("pathlib.Path.unlink", side_effect=OSError("delete failure")):
        with pytest.raises(OSError, match="Failed to delete cache file") as raised:
            manager.clear_cache()
    assert isinstance(raised.value.__cause__, OSError)
    assert manager.logger.error.call_args.args[1].args == ("delete failure",)
    assert manager.logger.error.call_args.kwargs["exc_info"] is True
    assert manager.logger.error.call_args.args[0] == "Failed to delete cache file: %s"


def test_cache_merge_logs_actual_duplicate_count(tmp_path: Path) -> None:
    """Duplicate reporting uses the number of omitted fetched records."""
    manager = ThreadCacheManager(tmp_path / "cache.json")
    manager.logger = Mock()
    cached = [_record("old", "same", "2025-12-22T00:00:00Z")]
    fetched = [_record("new", "same", "2025-12-23T00:00:00Z")]

    manager.merge_threads(cached, fetched)

    manager.logger.debug.assert_called_once_with("Deduplicated %s duplicate threads", 1)


def test_cache_merge_deduplicates_repeated_fetched_urls(tmp_path: Path) -> None:
    """Repeated fetched URLs are omitted and unique fetched records are retained."""
    manager = ThreadCacheManager(tmp_path / "cache.json")
    manager.logger = Mock()
    fetched = [_record(url="same"), _record(title="duplicate", url="same")]
    assert manager.merge_threads([], fetched) == [fetched[0]]
    manager.logger.debug.assert_called_once_with("Deduplicated %s duplicate threads", 1)


def test_cache_merge_does_not_log_when_no_records_are_deduplicated(tmp_path: Path) -> None:
    """A merge with no duplicates does not emit a misleading debug event."""
    manager = ThreadCacheManager(tmp_path / "cache.json")
    manager.logger = Mock()
    manager.merge_threads([], [_record(url="one"), _record(url="two")])
    manager.logger.debug.assert_not_called()


def test_cache_metadata_timestamps_are_utc(tmp_path: Path) -> None:
    """Both empty and populated metadata use an explicit UTC clock."""
    manager = ThreadCacheManager(tmp_path / "cache.json")
    with patch("perplexity_cli.threads.cache_manager.datetime") as clock:
        clock.now.return_value.isoformat.return_value = "now"
        manager._build_cache_metadata([])
        manager._build_cache_metadata([_record()])
    assert clock.now.call_args_list == [((UTC,), {}), ((UTC,), {})]
