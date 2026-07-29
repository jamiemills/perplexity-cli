"""Round 3 mutation-killing tests for threads/, auth/, and attachments/.

Targets survivors missed by rounds 1 and 2: response protocol guards,
coercion helpers, token manager internals, cache corruption paths,
OAuth token extraction, and upload manager field validation.
"""

from __future__ import annotations

import base64
import json
import os
import stat
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from perplexity_cli.attachments.upload_manager import (
    _S3_UPLOAD_SUCCESS_STATUS,
    AttachmentUploader,
    _diagnose_upload_entry_error,
    _extract_error_response_text,
    _is_object_mapping,
    _normalise_upload_fields,
    _validate_s3_object_url,
)
from perplexity_cli.auth.oauth_handler import (
    ChromeDevToolsClient,
    _extract_token,
    _extract_token_from_cookies,
    _extract_token_from_local_storage,
    _is_str_dict,
    _resolve_auth_defaults,
)
from perplexity_cli.auth.token_manager import (
    _DEFAULT_TOKEN_VERSION,
    _MALFORMED_COOKIES_ERROR,
    _TOKEN_FORMAT_VERSION,
    TOKEN_AGE_WARNING_DAYS,
    TokenManager,
    _extract_created_at,
    _extract_token_string,
    _extract_version,
)
from perplexity_cli.config.defaults import (
    DEFAULT_AUTH_POLL_INTERVAL,
    DEFAULT_AUTH_TIMEOUT,
    DEFAULT_CHROME_DEBUG_PORT,
    DEFAULT_PAGE_LOAD_TIMEOUT,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_UPLOAD_TIMEOUT,
    PERPLEXITY_SETTINGS_URL,
)
from perplexity_cli.threads.cache_manager import ThreadCacheManager
from perplexity_cli.threads.exporter import ThreadRecord
from perplexity_cli.threads.scraper import (
    BatchProcessingContext,
    ThreadScraper,
    _build_batch_processing_context,
    _coerce_optional_int,
    _coerce_optional_str,
    _coerce_progress_callback,
    _extract_cache_thread_dicts,
    _has_integer_status_code,
    _is_response_protocol,
    _legacy_context_value,
    _require_response,
    _response_core_members,
)
from perplexity_cli.utils.exceptions import (
    AttachmentUploadError,
    AuthenticationError,
    ConfigurationError,
    UpstreamSchemaError,
)


def _rec(title: str, url: str, created_at: str) -> ThreadRecord:
    return ThreadRecord(title=title, url=url, created_at=created_at)


# ---------------------------------------------------------------------------
# scraper.py – _response_core_members
# ---------------------------------------------------------------------------


class TestResponseCoreMembers:
    """Kill mutations in response core member extraction."""

    def test_returns_tuple_for_valid_object(self):
        obj = SimpleNamespace(ok=True, json=lambda: {})
        result = _response_core_members(obj)
        assert result is not None
        assert result[0] is True
        assert callable(result[1])

    def test_returns_none_on_missing_ok(self):
        obj = SimpleNamespace(json=lambda: {})
        assert _response_core_members(obj) is None

    def test_returns_none_on_missing_json(self):
        obj = SimpleNamespace(ok=True)
        assert _response_core_members(obj) is None

    def test_ok_false_still_returns_tuple(self):
        obj = SimpleNamespace(ok=False, json=lambda: {})
        result = _response_core_members(obj)
        assert result is not None
        assert result[0] is False


# ---------------------------------------------------------------------------
# scraper.py – _has_integer_status_code
# ---------------------------------------------------------------------------


class TestHasIntegerStatusCode:
    """Kill mutations in status code type check."""

    def test_integer_returns_true(self):
        obj = SimpleNamespace(status_code=200)
        assert _has_integer_status_code(obj) is True

    def test_string_returns_false(self):
        obj = SimpleNamespace(status_code="200")
        assert _has_integer_status_code(obj) is False

    def test_missing_attribute_returns_false(self):
        obj = SimpleNamespace()
        assert _has_integer_status_code(obj) is False

    def test_none_returns_false(self):
        obj = SimpleNamespace(status_code=None)
        assert _has_integer_status_code(obj) is False

    def test_bool_is_int_subclass(self):
        obj = SimpleNamespace(status_code=True)
        assert _has_integer_status_code(obj) is True


# ---------------------------------------------------------------------------
# scraper.py – _is_response_protocol
# ---------------------------------------------------------------------------


class TestIsResponseProtocol:
    """Kill mutations in response protocol guard."""

    def test_ok_true_callable_json_passes(self):
        obj = SimpleNamespace(ok=True, json=lambda: {})
        assert _is_response_protocol(obj) is True

    def test_ok_false_with_int_status_passes(self):
        obj = SimpleNamespace(ok=False, json=lambda: {}, status_code=500)
        assert _is_response_protocol(obj) is True

    def test_ok_false_without_status_fails(self):
        obj = SimpleNamespace(ok=False, json=lambda: {})
        assert _is_response_protocol(obj) is False

    def test_ok_not_bool_fails(self):
        obj = SimpleNamespace(ok=1, json=lambda: {})
        assert _is_response_protocol(obj) is False

    def test_json_not_callable_fails(self):
        obj = SimpleNamespace(ok=True, json="not_callable")
        assert _is_response_protocol(obj) is False

    def test_missing_members_fails(self):
        assert _is_response_protocol(object()) is False


# ---------------------------------------------------------------------------
# scraper.py – _require_response
# ---------------------------------------------------------------------------


class TestRequireResponse:
    """Kill mutations in response validation."""

    def test_valid_response_passes(self):
        obj = SimpleNamespace(ok=True, json=lambda: {})
        assert _require_response(obj) is obj

    def test_invalid_raises_upstream_schema_error(self):
        with pytest.raises(UpstreamSchemaError, match="Malformed HTTP response object"):
            _require_response(object())

    def test_ok_false_with_status_passes(self):
        obj = SimpleNamespace(ok=False, json=lambda: {}, status_code=404)
        assert _require_response(obj) is obj


# ---------------------------------------------------------------------------
# scraper.py – _coerce_optional_str / _coerce_optional_int / _coerce_progress_callback
# ---------------------------------------------------------------------------


class TestCoercionHelpers:
    """Kill mutations in legacy argument coercion."""

    def test_coerce_str_none(self):
        assert _coerce_optional_str(None, "field") is None

    def test_coerce_str_string(self):
        assert _coerce_optional_str("hello", "field") == "hello"

    def test_coerce_str_int_raises(self):
        with pytest.raises(TypeError, match="field must be a string or None"):
            _coerce_optional_str(42, "field")

    def test_coerce_int_none(self):
        assert _coerce_optional_int(None, "count") is None

    def test_coerce_int_integer(self):
        assert _coerce_optional_int(7, "count") == 7

    def test_coerce_int_string_raises(self):
        with pytest.raises(TypeError, match="count must be an integer or None"):
            _coerce_optional_int("seven", "count")

    def test_coerce_callback_none(self):
        assert _coerce_progress_callback(None) is None

    def test_coerce_callback_callable(self):
        def cb(c, t):
            return None

        assert _coerce_progress_callback(cb) is cb

    def test_coerce_callback_non_callable_raises(self):
        with pytest.raises(TypeError, match="progress_callback must be callable or None"):
            _coerce_progress_callback("not_callable")


# ---------------------------------------------------------------------------
# scraper.py – _legacy_context_value
# ---------------------------------------------------------------------------


class TestLegacyContextValue:
    """Kill index-boundary mutations in legacy context access."""

    def test_index_within_bounds(self):
        assert _legacy_context_value(("a", "b", "c"), 1) == "b"

    def test_index_at_boundary(self):
        assert _legacy_context_value(("a",), 0) == "a"

    def test_index_beyond_length(self):
        assert _legacy_context_value(("a",), 1) is None

    def test_empty_tuple(self):
        assert _legacy_context_value((), 0) is None


# ---------------------------------------------------------------------------
# scraper.py – _build_batch_processing_context
# ---------------------------------------------------------------------------


class TestBuildBatchProcessingContext:
    """Kill mutations in context normalisation."""

    def test_no_args_returns_defaults(self):
        ctx = _build_batch_processing_context()
        assert ctx.from_date is None
        assert ctx.total_threads is None
        assert ctx.progress_callback is None

    def test_single_context_passthrough(self):
        original = BatchProcessingContext(from_date="2026-01-01", total_threads=5)
        ctx = _build_batch_processing_context(original)
        assert ctx is original

    def test_legacy_single_string(self):
        ctx = _build_batch_processing_context("2026-05-01")
        assert ctx.from_date == "2026-05-01"
        assert ctx.total_threads is None


# ---------------------------------------------------------------------------
# scraper.py – _extract_cache_thread_dicts
# ---------------------------------------------------------------------------


class TestExtractCacheThreadDicts:
    """Kill mutations in cache thread validation."""

    def test_valid_entries(self):
        raw = [{"title": "T", "url": "U"}]
        result = _extract_cache_thread_dicts(raw)
        assert result == [{"title": "T", "url": "U"}]

    def test_non_list_raises(self):
        with pytest.raises(UpstreamSchemaError, match="Malformed cached thread records"):
            _extract_cache_thread_dicts("not a list")

    def test_non_dict_entry_raises(self):
        with pytest.raises(UpstreamSchemaError, match="Malformed cached thread records"):
            _extract_cache_thread_dicts(["not a dict"])

    def test_empty_list(self):
        assert _extract_cache_thread_dicts([]) == []


# ---------------------------------------------------------------------------
# scraper.py – ThreadScraper._load_cached_threads
# ---------------------------------------------------------------------------


class TestLoadCachedThreads:
    """Kill mutations in cached thread loading."""

    def test_no_cache_manager_returns_empty(self):
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}', cache_manager=None)
        assert scraper._load_cached_threads() == []

    def test_cache_returns_none(self):
        cm = MagicMock()
        cm.load_cache.return_value = None
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}', cache_manager=cm)
        assert scraper._load_cached_threads() == []

    def test_cache_with_threads(self):
        cm = MagicMock()
        cm.load_cache.return_value = {"threads": [{"title": "T", "url": "U", "created_at": "C"}]}
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}', cache_manager=cm)
        result = scraper._load_cached_threads()
        assert len(result) == 1
        assert result[0].title == "T"


# ---------------------------------------------------------------------------
# scraper.py – ThreadScraper._try_cache_only
# ---------------------------------------------------------------------------


class TestTryCacheOnly:
    """Kill mutations in cache-only fast path."""

    def test_no_cache_manager_returns_none(self):
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}', cache_manager=None)
        assert scraper._try_cache_only(None, None) is None

    def test_force_refresh_returns_none(self):
        cm = MagicMock()
        scraper = ThreadScraper(
            token='{"user": {"accessToken": "t"}}', cache_manager=cm, force_refresh=True
        )
        assert scraper._try_cache_only(None, None) is None

    def test_needs_fresh_returns_none(self):
        cm = MagicMock()
        cm.requires_fresh_data.return_value = (True, None, None)
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}', cache_manager=cm)
        assert scraper._try_cache_only(None, None) is None

    def test_cache_covers_range_returns_threads(self):
        cm = MagicMock()
        cm.requires_fresh_data.return_value = (False, None, None)
        cm.load_cache.return_value = {
            "threads": [{"title": "T", "url": "U", "created_at": "2026-01-15T00:00:00Z"}]
        }
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}', cache_manager=cm)
        result = scraper._try_cache_only(None, None)
        assert result is not None
        assert len(result) == 1


# ---------------------------------------------------------------------------
# scraper.py – ThreadScraper._prepare_fetch
# ---------------------------------------------------------------------------


class TestPrepareFetch:
    """Kill mutations in fetch preparation."""

    def test_force_refresh_returns_empty_and_original_dates(self):
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}', force_refresh=True)
        threads, fetch_from, fetch_to = scraper._prepare_fetch("2026-01-01", "2026-06-01")
        assert threads == []
        assert fetch_from == "2026-01-01"
        assert fetch_to == "2026-06-01"

    def test_no_cache_manager_returns_empty(self):
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}', cache_manager=None)
        threads, fetch_from, fetch_to = scraper._prepare_fetch("2026-01-01", None)
        assert threads == []
        assert fetch_from == "2026-01-01"
        assert fetch_to is None

    def test_with_cache_manager_delegates(self):
        cm = MagicMock()
        cm.requires_fresh_data.return_value = (True, "2026-03-01", "2026-06-01")
        cm.load_cache.return_value = {
            "threads": [{"title": "T", "url": "U", "created_at": "2026-01-01T00:00:00Z"}]
        }
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}', cache_manager=cm)
        threads, fetch_from, fetch_to = scraper._prepare_fetch("2026-01-01", "2026-06-01")
        assert len(threads) == 1
        assert fetch_from == "2026-03-01"
        assert fetch_to == "2026-06-01"


# ---------------------------------------------------------------------------
# scraper.py – ThreadScraper._process_single_thread_entry
# ---------------------------------------------------------------------------


class TestProcessSingleThreadEntry:
    """Kill mutations in single thread entry processing."""

    def test_valid_entry_appends(self):
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}')
        threads: list[ThreadRecord] = []
        stopped = scraper._process_single_thread_entry(
            {"last_query_datetime": "2026-06-01T00:00:00+00:00", "slug": "s", "title": "T"},
            threads,
            None,
        )
        assert stopped is False
        assert len(threads) == 1

    def test_old_entry_stops(self):
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}')
        threads: list[ThreadRecord] = []
        stopped = scraper._process_single_thread_entry(
            {"last_query_datetime": "2025-01-01T00:00:00+00:00", "slug": "s", "title": "T"},
            threads,
            "2026-01-01",
        )
        assert stopped is True
        assert len(threads) == 0

    def test_invalid_timestamp_raises_upstream_schema(self):
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}')
        threads: list[ThreadRecord] = []
        with pytest.raises(UpstreamSchemaError, match="Malformed thread timestamp"):
            scraper._process_single_thread_entry(
                {"last_query_datetime": "not-a-date", "slug": "s", "title": "T"},
                threads,
                None,
            )


# ---------------------------------------------------------------------------
# scraper.py – _parse_single_thread empty timestamp
# ---------------------------------------------------------------------------


class TestParseSingleThreadEmptyTimestamp:
    """Kill mutations in empty timestamp handling."""

    def test_empty_string_raises(self):
        with pytest.raises(UpstreamSchemaError, match="Malformed thread timestamp"):
            from perplexity_cli.threads.scraper import _parse_single_thread

            _parse_single_thread({"last_query_datetime": "", "slug": "s", "title": "T"}, None)


# ---------------------------------------------------------------------------
# token_manager.py – constants
# ---------------------------------------------------------------------------


class TestTokenManagerConstants:
    """Pin token manager constants to kill constant mutations."""

    def test_token_age_warning_days(self):
        assert TOKEN_AGE_WARNING_DAYS == 30

    def test_token_format_version(self):
        assert _TOKEN_FORMAT_VERSION == 2

    def test_default_token_version(self):
        assert _DEFAULT_TOKEN_VERSION == 1

    def test_malformed_cookies_error(self):
        assert _MALFORMED_COOKIES_ERROR == "Token file contains malformed cookies data"

    def test_secure_permissions_value(self):
        assert TokenManager.SECURE_PERMISSIONS == 0o600


# ---------------------------------------------------------------------------
# token_manager.py – _extract_created_at
# ---------------------------------------------------------------------------


class TestExtractCreatedAt:
    """Kill mutations in created_at extraction."""

    def test_string_value_returned(self):
        assert _extract_created_at({"created_at": "2026-01-01T00:00:00"}) == "2026-01-01T00:00:00"

    def test_non_string_returns_none(self):
        assert _extract_created_at({"created_at": 12345}) is None

    def test_missing_key_returns_none(self):
        assert _extract_created_at({}) is None

    def test_none_value_returns_none(self):
        assert _extract_created_at({"created_at": None}) is None


# ---------------------------------------------------------------------------
# token_manager.py – _extract_token_string
# ---------------------------------------------------------------------------


class TestExtractTokenString:
    """Kill mutations in token string extraction."""

    def test_valid_string(self):
        assert _extract_token_string({"token": "abc123"}) == "abc123"

    def test_missing_raises(self):
        with pytest.raises(AuthenticationError, match="missing encrypted token data"):
            _extract_token_string({})

    def test_empty_string_raises(self):
        with pytest.raises(AuthenticationError, match="missing encrypted token data"):
            _extract_token_string({"token": ""})

    def test_non_string_raises(self):
        with pytest.raises(AuthenticationError, match="missing encrypted token data"):
            _extract_token_string({"token": 12345})


# ---------------------------------------------------------------------------
# token_manager.py – _extract_version
# ---------------------------------------------------------------------------


class TestExtractVersion:
    """Kill mutations in version extraction."""

    def test_explicit_int(self):
        assert _extract_version({"version": 2}) == 2

    def test_missing_defaults_to_format_version(self):
        assert _extract_version({}) == _TOKEN_FORMAT_VERSION

    def test_non_int_defaults_to_one(self):
        assert _extract_version({"version": "two"}) == _DEFAULT_TOKEN_VERSION

    def test_version_one(self):
        assert _extract_version({"version": 1}) == 1


# ---------------------------------------------------------------------------
# token_manager.py – _check_token_age
# ---------------------------------------------------------------------------


class TestCheckTokenAge:
    """Kill mutations in token age checking."""

    def test_none_created_at_no_error(self):
        tm = TokenManager.__new__(TokenManager)
        tm.logger = Mock()
        tm._check_token_age(None)
        tm.logger.warning.assert_not_called()

    def test_old_token_logs_warning(self):
        tm = TokenManager.__new__(TokenManager)
        tm.logger = Mock()
        old_date = (datetime.now() - timedelta(days=31)).isoformat()
        tm._check_token_age(old_date)
        tm.logger.warning.assert_called_once()
        call_args = tm.logger.warning.call_args[0]
        assert "days old" in call_args[0]

    def test_young_token_logs_debug(self):
        tm = TokenManager.__new__(TokenManager)
        tm.logger = Mock()
        young_date = (datetime.now() - timedelta(days=5)).isoformat()
        tm._check_token_age(young_date)
        tm.logger.debug.assert_called_once()
        call_args = tm.logger.debug.call_args[0]
        assert "Token age" in call_args[0]

    def test_exactly_30_days_no_warning(self):
        tm = TokenManager.__new__(TokenManager)
        tm.logger = Mock()
        boundary_date = (datetime.now() - timedelta(days=30)).isoformat()
        tm._check_token_age(boundary_date)
        tm.logger.warning.assert_not_called()

    def test_unparseable_date_logs_debug(self):
        tm = TokenManager.__new__(TokenManager)
        tm.logger = Mock()
        tm._check_token_age("not-a-date")
        tm.logger.debug.assert_called_once()


# ---------------------------------------------------------------------------
# token_manager.py – _extract_encrypted_cookies
# ---------------------------------------------------------------------------


class TestExtractEncryptedCookies:
    """Kill mutations in encrypted cookie extraction."""

    def test_version_mismatch_returns_none(self):
        tm = TokenManager.__new__(TokenManager)
        tm.logger = Mock()
        result = tm._extract_encrypted_cookies({"cookies": "data"}, version=1)
        assert result is None

    def test_no_cookies_key_returns_none(self):
        tm = TokenManager.__new__(TokenManager)
        tm.logger = Mock()
        result = tm._extract_encrypted_cookies({}, version=2)
        assert result is None

    def test_valid_cookies_returned(self):
        tm = TokenManager.__new__(TokenManager)
        tm.logger = Mock()
        result = tm._extract_encrypted_cookies({"cookies": "encrypted_data"}, version=2)
        assert result == "encrypted_data"

    def test_empty_string_returns_none(self):
        tm = TokenManager.__new__(TokenManager)
        tm.logger = Mock()
        result = tm._extract_encrypted_cookies({"cookies": ""}, version=2)
        assert result is None

    def test_non_string_returns_none(self):
        tm = TokenManager.__new__(TokenManager)
        tm.logger = Mock()
        result = tm._extract_encrypted_cookies({"cookies": 123}, version=2)
        assert result is None


# ---------------------------------------------------------------------------
# token_manager.py – _log_version_without_cookies
# ---------------------------------------------------------------------------


class TestLogVersionWithoutCookies:
    """Kill mutations in version logging."""

    def test_v2_message(self):
        tm = TokenManager.__new__(TokenManager)
        tm.logger = Mock()
        tm._log_version_without_cookies(2)
        call_args = tm.logger.debug.call_args[0]
        assert "v2 format but no cookies" in call_args[0]

    def test_v1_message(self):
        tm = TokenManager.__new__(TokenManager)
        tm.logger = Mock()
        tm._log_version_without_cookies(1)
        call_args = tm.logger.debug.call_args[0]
        assert "v%s format" in call_args[0]


# ---------------------------------------------------------------------------
# token_manager.py – _parse_and_validate_cookies
# ---------------------------------------------------------------------------


class TestParseAndValidateCookies:
    """Kill mutations in cookie parsing and validation."""

    def test_valid_json(self):
        tm = TokenManager.__new__(TokenManager)
        tm.logger = Mock()
        result = tm._parse_and_validate_cookies('{"a": "1"}')
        assert result == {"a": "1"}

    def test_invalid_json_raises(self):
        tm = TokenManager.__new__(TokenManager)
        tm.logger = Mock()
        with pytest.raises(AuthenticationError, match=_MALFORMED_COOKIES_ERROR):
            tm._parse_and_validate_cookies("not json")

    def test_non_dict_json_raises(self):
        tm = TokenManager.__new__(TokenManager)
        tm.logger = Mock()
        with pytest.raises(AuthenticationError, match=_MALFORMED_COOKIES_ERROR):
            tm._parse_and_validate_cookies('["a", "b"]')


# ---------------------------------------------------------------------------
# token_manager.py – _validate_cookie_types
# ---------------------------------------------------------------------------


class TestValidateCookieTypes:
    """Kill mutations in cookie type validation."""

    def test_valid_dict(self):
        TokenManager._validate_cookie_types({"a": "1", "b": "2"})

    def test_non_dict_raises(self):
        with pytest.raises(AuthenticationError, match=_MALFORMED_COOKIES_ERROR):
            TokenManager._validate_cookie_types(["a", "b"])

    def test_non_string_value_raises(self):
        with pytest.raises(AuthenticationError, match=_MALFORMED_COOKIES_ERROR):
            TokenManager._validate_cookie_types({"a": 123})

    def test_non_string_key_raises(self):
        with pytest.raises(AuthenticationError, match=_MALFORMED_COOKIES_ERROR):
            TokenManager._validate_cookie_types({123: "value"})


# ---------------------------------------------------------------------------
# token_manager.py – _log_cookie_details
# ---------------------------------------------------------------------------


class TestLogCookieDetails:
    """Kill mutations in cookie detail logging."""

    def test_cf_cookies_counted(self):
        tm = TokenManager.__new__(TokenManager)
        tm.logger = Mock()
        tm._log_cookie_details({"cf_clearance": "x", "__cf_bm": "y", "other": "z"})
        first_call = tm.logger.debug.call_args_list[0][0]
        assert "3 cookies" in first_call[0] % (3, 2)

    def test_no_cf_cookies(self):
        tm = TokenManager.__new__(TokenManager)
        tm.logger = Mock()
        tm._log_cookie_details({"session": "abc"})
        assert tm.logger.debug.call_count >= 1


# ---------------------------------------------------------------------------
# token_manager.py – clear_token
# ---------------------------------------------------------------------------


class TestClearToken:
    """Kill mutations in token clearing."""

    def test_nonexistent_file_no_error(self, tmp_path):
        tm = TokenManager.__new__(TokenManager)
        tm.token_path = tmp_path / "nonexistent.json"
        tm.logger = Mock()
        tm.clear_token()

    def test_existing_file_deleted(self, tmp_path):
        token_file = tmp_path / "token.json"
        token_file.write_text("{}")
        tm = TokenManager.__new__(TokenManager)
        tm.token_path = token_file
        tm.logger = Mock()
        tm.clear_token()
        assert not token_file.exists()

    def test_os_error_wrapped(self, tmp_path):
        token_file = tmp_path / "token.json"
        token_file.write_text("{}")
        tm = TokenManager.__new__(TokenManager)
        tm.token_path = token_file
        tm.logger = Mock()
        with patch.object(Path, "unlink", side_effect=OSError("perm denied")):
            with pytest.raises(OSError, match="Failed to delete token file"):
                tm.clear_token()


# ---------------------------------------------------------------------------
# token_manager.py – token_exists
# ---------------------------------------------------------------------------


class TestTokenExists:
    """Kill mutations in token existence check."""

    def test_exists_true(self, tmp_path):
        token_file = tmp_path / "token.json"
        token_file.write_text("{}")
        tm = TokenManager.__new__(TokenManager)
        tm.token_path = token_file
        assert tm.token_exists() is True

    def test_exists_false(self, tmp_path):
        tm = TokenManager.__new__(TokenManager)
        tm.token_path = tmp_path / "nonexistent.json"
        assert tm.token_exists() is False


# ---------------------------------------------------------------------------
# token_manager.py – load_token not encrypted
# ---------------------------------------------------------------------------


class TestLoadTokenValidation:
    """Kill mutations in token file validation."""

    def test_not_encrypted_raises(self, tmp_path):
        token_file = tmp_path / "token.json"
        token_file.write_text(json.dumps({"token": "abc", "encrypted": False}))
        os.chmod(token_file, 0o600)
        tm = TokenManager.__new__(TokenManager)
        tm.token_path = token_file
        tm.logger = Mock()
        with pytest.raises(AuthenticationError, match="not encrypted"):
            tm._read_and_validate_token_file()

    def test_missing_token_raises(self, tmp_path):
        token_file = tmp_path / "token.json"
        token_file.write_text(json.dumps({"encrypted": True}))
        os.chmod(token_file, 0o600)
        tm = TokenManager.__new__(TokenManager)
        tm.token_path = token_file
        tm.logger = Mock()
        with pytest.raises(AuthenticationError, match="missing encrypted token data"):
            tm._read_and_validate_token_file()

    def test_nonexistent_returns_none(self, tmp_path):
        tm = TokenManager.__new__(TokenManager)
        tm.token_path = tmp_path / "nonexistent.json"
        tm.logger = Mock()
        result = tm.load_token()
        assert result == (None, None)


# ---------------------------------------------------------------------------
# token_manager.py – _prepare_token_data
# ---------------------------------------------------------------------------


class TestPrepareTokenData:
    """Kill mutations in token data preparation."""

    @patch("perplexity_cli.auth.token_manager.get_save_cookies_enabled", return_value=True)
    def test_with_cookies_enabled(self, _mock):
        tm = TokenManager.__new__(TokenManager)
        tm.logger = Mock()
        result = tm._prepare_token_data("enc_tok", {"a": "1"})
        assert result["version"] == _TOKEN_FORMAT_VERSION
        assert result["encrypted"] is True
        assert result["token"] == "enc_tok"
        assert "cookies" in result
        assert "created_at" in result

    @patch("perplexity_cli.auth.token_manager.get_save_cookies_enabled", return_value=False)
    def test_with_cookies_disabled(self, _mock):
        tm = TokenManager.__new__(TokenManager)
        tm.logger = Mock()
        result = tm._prepare_token_data("enc_tok", {"a": "1"})
        assert "cookies" not in result

    def test_no_cookies(self):
        tm = TokenManager.__new__(TokenManager)
        tm.logger = Mock()
        result = tm._prepare_token_data("enc_tok", None)
        assert "cookies" not in result
        assert result["encrypted"] is True


# ---------------------------------------------------------------------------
# cache_manager.py – load_cache corruption paths
# ---------------------------------------------------------------------------


class TestLoadCacheCorruption:
    """Kill mutations in cache corruption handling."""

    def test_nonexistent_returns_none(self, cache_manager):
        assert cache_manager.load_cache() is None

    def test_invalid_json_raises_os_error(self, cache_manager):
        cache_manager.cache_path.write_text("not json{{{")
        os.chmod(cache_manager.cache_path, 0o600)
        with pytest.raises(OSError, match="Failed to load cache"):
            cache_manager.load_cache()

    def test_not_encrypted_raises_config_error(self, cache_manager):
        cache_manager.cache_path.write_text(
            json.dumps({"version": 1, "encrypted": False, "cache": "data"})
        )
        os.chmod(cache_manager.cache_path, 0o600)
        with pytest.raises(ConfigurationError, match="not encrypted"):
            cache_manager.load_cache()

    def test_missing_cache_field_raises_config_error(self, cache_manager):
        cache_manager.cache_path.write_text(
            json.dumps({"version": 1, "encrypted": True, "cache": ""})
        )
        os.chmod(cache_manager.cache_path, 0o600)
        with pytest.raises(ConfigurationError):
            cache_manager.load_cache()


# ---------------------------------------------------------------------------
# cache_manager.py – _validate_outer_format
# ---------------------------------------------------------------------------


class TestValidateOuterFormat:
    """Kill mutations in outer format validation."""

    def test_invalid_schema_raises(self, cache_manager):
        with pytest.raises(ConfigurationError, match="invalid format"):
            cache_manager._validate_outer_format({"bad": "data"})

    def test_not_encrypted_raises(self, cache_manager):
        with pytest.raises(ConfigurationError, match="not encrypted"):
            cache_manager._validate_outer_format({"version": 1, "encrypted": False, "cache": "x"})

    def test_empty_cache_raises(self, cache_manager):
        with pytest.raises((ConfigurationError, Exception)):
            cache_manager._validate_outer_format({"version": 1, "encrypted": True, "cache": ""})


# ---------------------------------------------------------------------------
# cache_manager.py – get_cache_coverage
# ---------------------------------------------------------------------------


class TestGetCacheCoverage:
    """Kill mutations in cache coverage retrieval."""

    def test_no_cache_returns_none_none(self, cache_manager):
        assert cache_manager.get_cache_coverage() == (None, None)

    def test_with_threads_returns_dates(self, cache_manager):
        threads = [
            _rec("New", "u1", "2026-03-01T00:00:00Z"),
            _rec("Old", "u2", "2026-01-01T00:00:00Z"),
        ]
        cache_manager.save_cache(threads)
        oldest, newest = cache_manager.get_cache_coverage()
        assert oldest == "2026-01-01T00:00:00Z"
        assert newest == "2026-03-01T00:00:00Z"

    def test_empty_cache_returns_none_none(self, cache_manager):
        cache_manager.save_cache([])
        oldest, newest = cache_manager.get_cache_coverage()
        assert oldest is None
        assert newest is None


# ---------------------------------------------------------------------------
# cache_manager.py – clear_cache
# ---------------------------------------------------------------------------


class TestClearCache:
    """Kill mutations in cache clearing."""

    def test_nonexistent_no_error(self, cache_manager):
        cache_manager.clear_cache()

    def test_existing_deleted(self, cache_manager):
        cache_manager.save_cache([_rec("T", "U", "2026-01-01T00:00:00Z")])
        assert cache_manager.cache_path.exists()
        cache_manager.clear_cache()
        assert not cache_manager.cache_path.exists()

    def test_os_error_wrapped(self, cache_manager):
        cache_manager.cache_path.write_text("{}")
        with patch.object(Path, "unlink", side_effect=OSError("locked")):
            with pytest.raises(OSError, match="Failed to delete cache file"):
                cache_manager.clear_cache()


# ---------------------------------------------------------------------------
# cache_manager.py – cache_exists
# ---------------------------------------------------------------------------


class TestCacheExists:
    """Kill mutations in cache existence check."""

    def test_false_when_missing(self, cache_manager):
        assert cache_manager.cache_exists() is False

    def test_true_when_present(self, cache_manager):
        cache_manager.save_cache([])
        assert cache_manager.cache_exists() is True


# ---------------------------------------------------------------------------
# cache_manager.py – save_cache permissions
# ---------------------------------------------------------------------------


class TestSaveCachePermissions:
    """Kill mutations in cache file permission setting."""

    def test_permissions_set_to_0600(self, cache_manager):
        cache_manager.save_cache([_rec("T", "U", "2026-01-01T00:00:00Z")])
        actual = stat.S_IMODE(cache_manager.cache_path.stat().st_mode)
        assert actual == 0o600


# ---------------------------------------------------------------------------
# cache_manager.py – merge_threads dedup count
# ---------------------------------------------------------------------------


class TestMergeThreadsDedupCount:
    """Kill mutations in dedup counting."""

    def test_dedup_count_logged(self, cache_manager):
        cached = [_rec("C", "u1", "2026-01-01T00:00:00Z")]
        fetched = [
            _rec("F1", "u1", "2026-01-02T00:00:00Z"),
            _rec("F2", "u2", "2026-01-03T00:00:00Z"),
        ]
        merged = cache_manager.merge_threads(cached, fetched)
        assert len(merged) == 2

    def test_no_dedup_when_all_new(self, cache_manager):
        cached = [_rec("C", "u0", "2026-01-01T00:00:00Z")]
        fetched = [_rec("F", "u1", "2026-01-02T00:00:00Z")]
        merged = cache_manager.merge_threads(cached, fetched)
        assert len(merged) == 2


# ---------------------------------------------------------------------------
# oauth_handler.py – _is_str_dict
# ---------------------------------------------------------------------------


class TestIsStrDict:
    """Kill mutations in type guard."""

    def test_dict_returns_true(self):
        assert _is_str_dict({"key": "value"}) is True

    def test_list_returns_false(self):
        assert _is_str_dict(["a"]) is False

    def test_none_returns_false(self):
        assert _is_str_dict(None) is False

    def test_empty_dict_returns_true(self):
        assert _is_str_dict({}) is True


# ---------------------------------------------------------------------------
# oauth_handler.py – ChromeDevToolsClient init
# ---------------------------------------------------------------------------


class TestChromeDevToolsClientInit:
    """Kill mutations in client initialisation."""

    def test_port_stored(self):
        client = ChromeDevToolsClient(port=9333)
        assert client.port == 9333

    def test_message_id_starts_at_zero(self):
        client = ChromeDevToolsClient(port=9222)
        assert client.message_id == 0

    def test_ws_starts_none(self):
        client = ChromeDevToolsClient(port=9222)
        assert client.ws is None


# ---------------------------------------------------------------------------
# oauth_handler.py – _resolve_auth_defaults
# ---------------------------------------------------------------------------


class TestResolveAuthDefaults:
    """Kill mutations in default resolution."""

    def test_all_none_uses_defaults(self):
        url, port, timeout, poll = _resolve_auth_defaults(None, None, None, None)
        assert port == DEFAULT_CHROME_DEBUG_PORT
        assert timeout == DEFAULT_AUTH_TIMEOUT
        assert poll == DEFAULT_AUTH_POLL_INTERVAL

    def test_all_provided_uses_given(self):
        url, port, timeout, poll = _resolve_auth_defaults("https://custom.ai", 1234, 60, 0.5)
        assert url == "https://custom.ai"
        assert port == 1234
        assert timeout == 60
        assert poll == 0.5

    def test_default_port_is_9222(self):
        _, port, _, _ = _resolve_auth_defaults(None, None, None, None)
        assert port == 9222

    def test_default_timeout_is_120(self):
        _, _, timeout, _ = _resolve_auth_defaults(None, None, None, None)
        assert timeout == 120

    def test_default_poll_interval_is_2(self):
        _, _, _, poll = _resolve_auth_defaults(None, None, None, None)
        assert poll == 2.0


# ---------------------------------------------------------------------------
# oauth_handler.py – _extract_token_from_local_storage
# ---------------------------------------------------------------------------


class TestExtractTokenFromLocalStorage:
    """Kill mutations in localStorage token extraction."""

    def test_missing_key_returns_none(self):
        assert _extract_token_from_local_storage({}) is None

    def test_valid_json_returns_dumped(self):
        storage = {"pplx-next-auth-session": '{"user": "test"}'}
        result = _extract_token_from_local_storage(storage)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["user"] == "test"

    def test_invalid_json_returns_none(self):
        storage = {"pplx-next-auth-session": "not-json{{{"}
        assert _extract_token_from_local_storage(storage) is None

    def test_non_string_value_returns_none(self):
        storage = {"pplx-next-auth-session": 12345}
        assert _extract_token_from_local_storage(storage) is None


# ---------------------------------------------------------------------------
# oauth_handler.py – _extract_token_from_cookies
# ---------------------------------------------------------------------------


class TestExtractTokenFromCookies:
    """Kill mutations in cookie token extraction."""

    def test_secure_cookie_preferred(self):
        cookies = {
            "__Secure-next-auth.session-token": "secure_tok",
            "next-auth.session-token": "plain_tok",
        }
        assert _extract_token_from_cookies(cookies) == "secure_tok"

    def test_fallback_to_non_secure(self):
        cookies = {"next-auth.session-token": "plain_tok"}
        assert _extract_token_from_cookies(cookies) == "plain_tok"

    def test_no_matching_cookies(self):
        cookies = {"other": "value"}
        assert _extract_token_from_cookies(cookies) is None

    def test_empty_dict(self):
        assert _extract_token_from_cookies({}) is None


# ---------------------------------------------------------------------------
# oauth_handler.py – _extract_token
# ---------------------------------------------------------------------------


class TestExtractToken:
    """Kill mutations in combined token extraction."""

    def test_local_storage_preferred_over_cookies(self):
        cookies = [{"name": "__Secure-next-auth.session-token", "value": "cookie_tok"}]
        storage = {"pplx-next-auth-session": '{"user": "ls_tok"}'}
        token, cookie_dict = _extract_token(cookies, storage)
        assert token is not None
        assert "user" in json.loads(token)

    def test_falls_back_to_cookies(self):
        cookies = [{"name": "__Secure-next-auth.session-token", "value": "cookie_tok"}]
        token, cookie_dict = _extract_token(cookies, {})
        assert token == "cookie_tok"

    def test_no_token_anywhere(self):
        token, cookie_dict = _extract_token([], {})
        assert token is None
        assert cookie_dict == {}

    def test_cookie_dict_built(self):
        cookies = [
            {"name": "a", "value": "1"},
            {"name": "b", "value": "2"},
        ]
        _, cookie_dict = _extract_token(cookies, {})
        assert cookie_dict == {"a": "1", "b": "2"}


# ---------------------------------------------------------------------------
# oauth_handler.py – _find_page_target
# ---------------------------------------------------------------------------


class TestFindPageTarget:
    """Kill mutations in page target discovery."""

    def test_finds_page_type(self):
        targets = [{"type": "background"}, {"type": "page", "id": "p1"}]
        result = ChromeDevToolsClient._find_page_target(targets)
        assert result["id"] == "p1"

    def test_no_page_raises(self):
        targets = [{"type": "background"}, {"type": "worker"}]
        with pytest.raises(AuthenticationError, match="No page target found"):
            ChromeDevToolsClient._find_page_target(targets)

    def test_empty_list_raises(self):
        with pytest.raises(AuthenticationError, match="No page target found"):
            ChromeDevToolsClient._find_page_target([])

    def test_non_dict_entries_skipped(self):
        targets = ["not_a_dict", {"type": "page", "id": "p2"}]
        result = ChromeDevToolsClient._find_page_target(targets)
        assert result["id"] == "p2"


# ---------------------------------------------------------------------------
# oauth_handler.py – _build_command
# ---------------------------------------------------------------------------


class TestBuildCommand:
    """Kill mutations in CDP command construction."""

    def test_without_params(self):
        client = ChromeDevToolsClient(port=9222)
        client.message_id = 5
        cmd = client._build_command("Page.enable", None)
        assert cmd == {"id": 5, "method": "Page.enable"}
        assert "params" not in cmd

    def test_with_params(self):
        client = ChromeDevToolsClient(port=9222)
        client.message_id = 3
        cmd = client._build_command("Page.navigate", {"url": "https://x.com"})
        assert cmd["id"] == 3
        assert cmd["method"] == "Page.navigate"
        assert cmd["params"] == {"url": "https://x.com"}

    def test_empty_params_not_included(self):
        client = ChromeDevToolsClient(port=9222)
        client.message_id = 1
        cmd = client._build_command("Network.enable", {})
        assert "params" not in cmd


# ---------------------------------------------------------------------------
# oauth_handler.py – send_command not connected
# ---------------------------------------------------------------------------


class TestSendCommandNotConnected:
    """Kill mutations in connection guard."""

    @pytest.mark.asyncio
    async def test_raises_when_not_connected(self):
        client = ChromeDevToolsClient(port=9222)
        with pytest.raises(AuthenticationError, match="Not connected to Chrome"):
            await client.send_command("Page.enable")


# ---------------------------------------------------------------------------
# oauth_handler.py – config defaults
# ---------------------------------------------------------------------------


class TestOAuthConfigDefaults:
    """Pin OAuth-related config defaults."""

    def test_chrome_debug_port(self):
        assert DEFAULT_CHROME_DEBUG_PORT == 9222

    def test_auth_timeout(self):
        assert DEFAULT_AUTH_TIMEOUT == 120

    def test_auth_poll_interval(self):
        assert DEFAULT_AUTH_POLL_INTERVAL == 2.0

    def test_page_load_timeout(self):
        assert DEFAULT_PAGE_LOAD_TIMEOUT == 30


# ---------------------------------------------------------------------------
# upload_manager.py – constants
# ---------------------------------------------------------------------------


class TestUploadManagerConstants:
    """Pin upload manager constants."""

    def test_s3_upload_success_status(self):
        assert _S3_UPLOAD_SUCCESS_STATUS == 204

    def test_default_upload_timeout(self):
        assert DEFAULT_UPLOAD_TIMEOUT == 300

    def test_default_request_timeout(self):
        assert DEFAULT_REQUEST_TIMEOUT == 60

    def test_perplexity_settings_url(self):
        assert PERPLEXITY_SETTINGS_URL == "https://www.perplexity.ai/settings/account"


# ---------------------------------------------------------------------------
# upload_manager.py – _is_object_mapping
# ---------------------------------------------------------------------------


class TestIsObjectMapping:
    """Kill mutations in mapping type guard."""

    def test_dict_returns_true(self):
        assert _is_object_mapping({"a": 1}) is True

    def test_list_returns_false(self):
        assert _is_object_mapping([1, 2]) is False

    def test_none_returns_false(self):
        assert _is_object_mapping(None) is False

    def test_empty_dict_returns_true(self):
        assert _is_object_mapping({}) is True


# ---------------------------------------------------------------------------
# upload_manager.py – _diagnose_upload_entry_error
# ---------------------------------------------------------------------------


class TestDiagnoseUploadEntryError:
    """Kill mutations in upload error diagnosis."""

    def test_rate_limited_message(self):
        msg = _diagnose_upload_entry_error({"rate_limited": True})
        assert "quota exhausted" in msg
        assert PERPLEXITY_SETTINGS_URL in msg

    def test_api_error_message(self):
        msg = _diagnose_upload_entry_error({"error": "bad request"})
        assert "API failed to generate upload URL" in msg
        assert "bad request" in msg

    def test_empty_response_message(self):
        msg = _diagnose_upload_entry_error({})
        assert "empty presigned URL response" in msg
        assert "authentication or account issue" in msg

    def test_rate_limited_takes_priority_over_error(self):
        msg = _diagnose_upload_entry_error({"rate_limited": True, "error": "other"})
        assert "quota exhausted" in msg


# ---------------------------------------------------------------------------
# upload_manager.py – _extract_error_response_text
# ---------------------------------------------------------------------------


class TestExtractErrorResponseText:
    """Kill mutations in error text extraction."""

    def test_normal_text(self):
        resp = Mock()
        resp.text = "error details"
        assert _extract_error_response_text(resp) == "error details"

    def test_truncated_at_500(self):
        resp = Mock()
        resp.text = "x" * 1000
        assert len(_extract_error_response_text(resp)) == 500

    def test_empty_text_falls_back_to_content(self):
        resp = Mock()
        resp.text = ""
        resp.content = b"binary"
        result = _extract_error_response_text(resp)
        assert "binary" in result

    def test_attribute_error_returns_empty(self):
        resp = Mock(spec=[])
        assert _extract_error_response_text(resp) == ""


# ---------------------------------------------------------------------------
# upload_manager.py – _normalise_upload_fields
# ---------------------------------------------------------------------------


class TestNormaliseUploadFields:
    """Kill mutations in field normalisation."""

    def test_missing_fields_returns_empty(self):
        assert _normalise_upload_fields({}) == {}

    def test_none_fields_returns_empty(self):
        assert _normalise_upload_fields({"fields": None}) == {}

    def test_non_dict_fields_returns_empty(self):
        assert _normalise_upload_fields({"fields": "not_dict"}) == {}

    def test_valid_fields_returned(self):
        result = _normalise_upload_fields({"fields": {"key": "val"}})
        assert result == {"key": "val"}


# ---------------------------------------------------------------------------
# upload_manager.py – _validate_s3_object_url
# ---------------------------------------------------------------------------


class TestValidateS3ObjectUrl:
    """Kill mutations in S3 URL validation."""

    def test_valid_string_passes(self):
        _validate_s3_object_url({"s3_object_url": "https://s3.example.com/file"})

    def test_missing_key_passes(self):
        _validate_s3_object_url({})

    def test_empty_string_passes(self):
        _validate_s3_object_url({"s3_object_url": ""})

    def test_non_string_raises(self):
        with pytest.raises(UpstreamSchemaError, match="Malformed S3 object URL"):
            _validate_s3_object_url({"s3_object_url": 12345})


# ---------------------------------------------------------------------------
# upload_manager.py – AttachmentUploader._build_upload_metadata
# ---------------------------------------------------------------------------


class TestBuildUploadMetadata:
    """Kill mutations in upload metadata construction."""

    def test_metadata_structure(self):
        from perplexity_cli.utils.attachment_models import FileAttachment

        data = base64.b64encode(b"hello world").decode()
        attachment = FileAttachment(filename="test.txt", content_type="text/plain", data=data)
        metadata, uuid_map = AttachmentUploader._build_upload_metadata([attachment])
        assert len(metadata) == 1
        file_uuid = next(iter(metadata))
        entry = metadata[file_uuid]
        assert entry["filename"] == "test.txt"
        assert entry["content_type"] == "text/plain"
        assert entry["source"] == "default"
        assert entry["file_size"] == 11
        assert entry["force_image"] is False
        assert entry["search_mode"] == "search"

    def test_uuid_mapping(self):
        from perplexity_cli.utils.attachment_models import FileAttachment

        data = base64.b64encode(b"x").decode()
        attachment = FileAttachment(
            filename="f.bin", content_type="application/octet-stream", data=data
        )
        _, uuid_map = AttachmentUploader._build_upload_metadata([attachment])
        assert len(uuid_map) == 1
        assert next(iter(uuid_map.values())) is attachment

    def test_file_size_decoded_correctly(self):
        from perplexity_cli.utils.attachment_models import FileAttachment

        content = b"12345"
        data = base64.b64encode(content).decode()
        attachment = FileAttachment(
            filename="f.bin", content_type="application/octet-stream", data=data
        )
        metadata, _ = AttachmentUploader._build_upload_metadata([attachment])
        entry = next(iter(metadata.values()))
        assert entry["file_size"] == 5


# ---------------------------------------------------------------------------
# upload_manager.py – AttachmentUploader._build_s3_form_data
# ---------------------------------------------------------------------------


class TestBuildS3FormData:
    """Kill mutations in S3 form data construction."""

    def test_excludes_file_key(self):
        upload_data = {"fields": {"key": "val", "file": "should_exclude"}}
        result = AttachmentUploader._build_s3_form_data(upload_data)
        assert "file" not in result
        assert result["key"] == "val"

    def test_empty_fields(self):
        result = AttachmentUploader._build_s3_form_data({})
        assert result == {}

    def test_values_converted_to_str(self):
        upload_data = {"fields": {"num": 42}}
        result = AttachmentUploader._build_s3_form_data(upload_data)
        assert result["num"] == "42"


# ---------------------------------------------------------------------------
# upload_manager.py – AttachmentUploader._handle_s3_response
# ---------------------------------------------------------------------------


class TestHandleS3Response:
    """Kill mutations in S3 response handling."""

    def test_204_returns_url(self):
        from perplexity_cli.utils.attachment_models import FileAttachment

        resp = Mock()
        resp.status_code = 204
        upload_data = {"s3_object_url": "https://s3.example.com/file.pdf"}
        attachment = FileAttachment(
            filename="f.pdf", content_type="application/pdf", data="aGVsbG8="
        )
        result = AttachmentUploader._handle_s3_response(resp, upload_data, attachment)
        assert result == "https://s3.example.com/file.pdf"

    def test_non_204_raises(self):
        from perplexity_cli.utils.attachment_models import FileAttachment

        resp = Mock()
        resp.status_code = 403
        resp.text = "Forbidden"
        upload_data = {"s3_object_url": "https://s3.example.com/file.pdf"}
        attachment = FileAttachment(
            filename="f.pdf", content_type="application/pdf", data="aGVsbG8="
        )
        with pytest.raises(AttachmentUploadError, match=r"S3 upload failed for f\.pdf"):
            AttachmentUploader._handle_s3_response(resp, upload_data, attachment)

    def test_204_non_string_url_raises(self):
        from perplexity_cli.utils.attachment_models import FileAttachment

        resp = Mock()
        resp.status_code = 204
        upload_data = {"s3_object_url": 12345}
        attachment = FileAttachment(
            filename="f.pdf", content_type="application/pdf", data="aGVsbG8="
        )
        with pytest.raises(UpstreamSchemaError, match="Malformed S3 object URL"):
            AttachmentUploader._handle_s3_response(resp, upload_data, attachment)

    def test_error_message_includes_status(self):
        from perplexity_cli.utils.attachment_models import FileAttachment

        resp = Mock()
        resp.status_code = 500
        resp.text = "Internal"
        upload_data = {}
        attachment = FileAttachment(filename="doc.txt", content_type="text/plain", data="aGVsbG8=")
        with pytest.raises(AttachmentUploadError, match="status 500"):
            AttachmentUploader._handle_s3_response(resp, upload_data, attachment)


# ---------------------------------------------------------------------------
# upload_manager.py – AttachmentUploader._validate_upload_response
# ---------------------------------------------------------------------------


class TestValidateUploadResponse:
    """Kill mutations in upload response validation."""

    def test_valid_response_passes(self):
        response = {
            "results": {"uuid1": {"fields": {"k": "v"}, "s3_object_url": "https://s3.com/f"}}
        }
        AttachmentUploader._validate_upload_response(response)

    def test_missing_fields_raises(self):
        response = {"results": {"uuid1": {"s3_object_url": "https://s3.com/f"}}}
        with pytest.raises(AttachmentUploadError):
            AttachmentUploader._validate_upload_response(response)

    def test_rate_limited_raises(self):
        response = {"results": {"uuid1": {"rate_limited": True}}}
        with pytest.raises(AttachmentUploadError, match="quota exhausted"):
            AttachmentUploader._validate_upload_response(response)

    def test_empty_results_passes(self):
        response = {"results": {}}
        AttachmentUploader._validate_upload_response(response)


# ---------------------------------------------------------------------------
# upload_manager.py – AttachmentUploader.__init__
# ---------------------------------------------------------------------------


class TestAttachmentUploaderInit:
    """Kill mutations in uploader initialisation."""

    def test_default_base_url(self):
        uploader = AttachmentUploader(token="tok")
        assert uploader.base_url is not None
        assert "perplexity" in uploader.base_url

    def test_custom_base_url(self):
        uploader = AttachmentUploader(token="tok", base_url="https://custom.ai")
        assert uploader.base_url == "https://custom.ai"

    def test_cookies_stored(self):
        uploader = AttachmentUploader(token="tok", cookies={"cf": "x"})
        assert uploader.cookies == {"cf": "x"}

    def test_none_cookies(self):
        uploader = AttachmentUploader(token="tok")
        assert uploader.cookies is None


# ---------------------------------------------------------------------------
# upload_manager.py – AttachmentUploader.upload_files empty
# ---------------------------------------------------------------------------


class TestUploadFilesEmpty:
    """Kill mutations in empty upload handling."""

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self):
        uploader = AttachmentUploader(token="tok")
        result = await uploader.upload_files([])
        assert result == []


# ---------------------------------------------------------------------------
# cache_manager.py – requires_fresh_data with to_date None
# ---------------------------------------------------------------------------


class TestRequiresFreshDataToDateNone:
    """Kill mutations when to_date is None (uses today)."""

    def test_to_date_none_uses_today(self, cache_manager):
        threads = [
            _rec("New", "u1", "2026-03-01T00:00:00Z"),
            _rec("Old", "u2", "2026-01-01T00:00:00Z"),
        ]
        cache_manager.save_cache(threads)
        needs, _, _ = cache_manager.requires_fresh_data("2026-01-01", None)
        assert needs is True


# ---------------------------------------------------------------------------
# cache_manager.py – _calculate_fetch_range both directions
# ---------------------------------------------------------------------------


class TestCalculateFetchRangeBothDirections:
    """Kill mutations when both older and newer data needed."""

    def test_both_older_and_newer(self):
        needs, fetch_from, fetch_to = ThreadCacheManager._calculate_fetch_range(
            date(2025, 12, 1), date(2026, 3, 1), date(2026, 1, 1), date(2026, 2, 1)
        )
        assert needs is True
        assert fetch_from == "2025-12-01"
        assert fetch_to == "2026-03-01"

    def test_exactly_contained_no_fetch(self):
        needs, _, _ = ThreadCacheManager._calculate_fetch_range(
            date(2026, 1, 2), date(2026, 1, 30), date(2026, 1, 1), date(2026, 1, 31)
        )
        assert needs is False
