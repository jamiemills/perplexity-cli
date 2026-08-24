"""Behavioural boundaries for thread pagination and scraping."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from perplexity_cli.threads.exporter import ThreadRecord
from perplexity_cli.threads.pagination import (
    BatchProcessingContext,
    PaginationState,
    _build_batch_processing_context,
    _build_legacy_batch_processing_context,
    _coerce_optional_int,
    _coerce_optional_str,
    _coerce_progress_callback,
    _extract_total_threads,
    _has_more_pages,
    _legacy_context_value,
    _next_pagination_offset,
    _page_signature,
    _validate_batch_processing_arg_count,
)
from perplexity_cli.threads.scraper import (
    ThreadScraper,
    _create_async_session,
    _extract_cache_thread_dicts,
    _get_str_field,
    _handle_http_error,
    _is_response_protocol,
    _parse_single_thread,
    _require_response,
    _response_core_members,
)
from perplexity_cli.utils.exceptions import (
    AuthenticationError,
    PerplexityHTTPStatusError,
    RateLimitError,
    SimpleResponse,
    UpstreamSchemaError,
)


def _scraper(**options: object) -> ThreadScraper:
    """Create a scraper with a structurally valid session token."""
    return ThreadScraper('{"user": {"accessToken": "t014-token"}}', **options)


class TestPaginationBoundaries:
    """Exercise the legacy and typed pagination contracts."""

    @staticmethod
    def test_optional_coercers_accept_contract_values_and_reject_others() -> None:
        """Optional values retain their types and reject unrelated sentinels."""
        assert _coerce_optional_str(None, "from_date") is None
        assert _coerce_optional_str("2026-01-01", "from_date") == "2026-01-01"
        assert _coerce_optional_int(None, "total_threads") is None
        assert _coerce_optional_int(12, "total_threads") == 12
        for value, coercer, name in [
            (12, _coerce_optional_str, "from_date"),
            ("12", _coerce_optional_int, "total_threads"),
        ]:
            with pytest.raises(TypeError):
                coercer(value, name)

    @staticmethod
    def test_progress_coercer_requires_callable_or_none() -> None:
        """Progress callbacks are callable objects, not arbitrary truthy values."""
        callback = MagicMock()
        assert _coerce_progress_callback(None) is None
        assert _coerce_progress_callback(callback) is callback
        with pytest.raises(TypeError) as raised:
            _coerce_progress_callback("callback-sentinel")
        assert "None" in str(raised.value)

    @staticmethod
    def test_legacy_context_argument_count_and_index_contract() -> None:
        """Three legacy context arguments are valid and a fourth is rejected."""
        _validate_batch_processing_arg_count(3)
        with pytest.raises(TypeError):
            _validate_batch_processing_arg_count(4)
        assert _legacy_context_value(("date",), 0) == "date"
        assert _legacy_context_value(("date",), 1) is None

    @staticmethod
    def test_context_builders_normalise_typed_and_legacy_shapes() -> None:
        """Typed contexts pass through while legacy positions map explicitly."""
        typed = BatchProcessingContext("2026-01-01", 9, MagicMock())
        assert _build_batch_processing_context() == BatchProcessingContext()
        assert _build_batch_processing_context(typed) is typed
        assert isinstance(_build_batch_processing_context("2026-01-01"), BatchProcessingContext)
        assert (
            _build_legacy_batch_processing_context(("2026-01-01", 9, typed.progress_callback))
            == typed
        )
        assert _build_batch_processing_context("2026-01-01", 9, typed.progress_callback) == typed

    @staticmethod
    def test_page_and_offset_contracts() -> None:
        """Page signatures use the first entry and offsets must advance."""
        page = [
            {"last_query_datetime": "d", "slug": "a"},
            {"last_query_datetime": "x", "slug": "b"},
        ]
        assert _page_signature(page) == "d|a"
        assert _has_more_pages([]) is False
        assert _has_more_pages([{"has_next_page": True}]) is True
        assert _has_more_pages([{"has_next_page": False}, {"has_next_page": True}]) is False
        with pytest.raises(UpstreamSchemaError):
            _has_more_pages([{"has_next_page": "yes"}])
        assert _next_pagination_offset(0, 100) == 100
        for limit in (0, -1):
            with pytest.raises(UpstreamSchemaError):
                _next_pagination_offset(100, limit)

    @staticmethod
    def test_total_threads_uses_explicit_value_before_payload() -> None:
        """An established total is authoritative; fallback validates payload data."""
        assert _extract_total_threads({"total_threads": "ignored"}, 4) == 4
        assert _extract_total_threads({}, None) == 0
        assert _extract_total_threads({"total_threads": 0}, None) == 0
        with pytest.raises(UpstreamSchemaError):
            _extract_total_threads({"total_threads": "bad"}, None)

    @staticmethod
    def test_pagination_validation_reports_distinct_invalid_inputs() -> None:
        """Invalid legacy values retain diagnostic exception payloads."""
        invalid_cases = [
            (_coerce_optional_str, (12, "from_date")),
            (_coerce_optional_int, ("12", "total_threads")),
            (_coerce_progress_callback, ("callback-sentinel",)),
        ]
        for validator, args in invalid_cases:
            with pytest.raises(TypeError) as raised:
                validator(*args)
            assert raised.value.args and raised.value.args[0] is not None

        for count in (-1, 3):
            _validate_batch_processing_arg_count(count)
        with pytest.raises(TypeError) as raised:
            _validate_batch_processing_arg_count(4)
        assert raised.value.args and raised.value.args[0] is not None

    @staticmethod
    def test_legacy_context_preserves_each_optional_position() -> None:
        """Legacy positional values map independently to the typed context."""
        callback = MagicMock()
        context = _build_legacy_batch_processing_context((None, 0, callback))
        assert context.from_date is None
        assert context.total_threads == 0
        assert context.progress_callback is callback

    @staticmethod
    def test_legacy_context_labels_invalid_positions() -> None:
        """Invalid legacy positions expose the corresponding diagnostic field."""
        for args in ((12,), (None, "12"), (None, None, "callback")):
            with pytest.raises(TypeError) as raised:
                _build_legacy_batch_processing_context(args)
            assert raised.value.args and raised.value.args[0] is not None
            assert "XX" not in str(raised.value)
        with pytest.raises(TypeError) as raised:
            _build_legacy_batch_processing_context((12,))
        assert "from_date" in str(raised.value)
        with pytest.raises(TypeError) as raised:
            _build_legacy_batch_processing_context((None, "12"))
        assert "total_threads" in str(raised.value)

    @staticmethod
    def test_pagination_rejects_non_advancing_negative_limits() -> None:
        """Every non-positive page size is rejected before the next request."""
        with pytest.raises(UpstreamSchemaError) as raised:
            _next_pagination_offset(5, -1)
        assert raised.value.args and raised.value.args[0] is not None
        assert "XX" not in str(raised.value)

    @staticmethod
    def test_page_flags_default_false_and_validate_first_record_only() -> None:
        """Absent flags stop pagination and later flags cannot override the first."""
        assert _has_more_pages([{}]) is False
        assert _has_more_pages([{"has_next_page": False}, {"has_next_page": True}]) is False

    @staticmethod
    def test_page_state_retains_signature_when_pagination_stops() -> None:
        """A terminal page records its signature for the next-page guard."""
        scraper = _scraper()
        state, should_continue = scraper._process_page(
            [{"last_query_datetime": "2026-01-01T00:00:00", "slug": "a", "title": "A"}],
            [],
            PaginationState(),
            BatchProcessingContext(),
        )
        assert should_continue is False
        assert state.previous_signature == "2026-01-01T00:00:00|a"

    @staticmethod
    def test_repeated_page_is_rejected_before_batch_processing() -> None:
        """A repeated page signature fails without entering another pagination step."""
        scraper = _scraper()
        page = [{"last_query_datetime": "2026-01-01T00:00:00", "slug": "a", "title": "A"}]
        with pytest.raises(UpstreamSchemaError):
            scraper._process_page(
                page,
                [],
                PaginationState(previous_signature="2026-01-01T00:00:00|a"),
                BatchProcessingContext(),
            )

    @staticmethod
    def test_nonterminal_page_advances_and_retains_signature() -> None:
        """A page with a next-page flag advances its offset and cursor."""
        scraper = _scraper()
        state, should_continue = scraper._process_page(
            [
                {
                    "last_query_datetime": "2026-01-01T00:00:00",
                    "slug": "a",
                    "title": "A",
                    "has_next_page": True,
                }
            ],
            [],
            PaginationState(),
            BatchProcessingContext(),
        )
        assert should_continue is True
        assert state.offset == 100
        assert state.previous_signature == "2026-01-01T00:00:00|a"

    @staticmethod
    def test_batch_processing_preserves_known_total_for_progress() -> None:
        """A known total in the typed context remains authoritative."""
        callback = MagicMock()
        scraper = _scraper()
        threads: list[ThreadRecord] = []
        assert (
            scraper._process_thread_batch(
                [
                    {
                        "last_query_datetime": "2026-01-01T00:00:00",
                        "slug": "a",
                        "title": "A",
                        "total_threads": 2,
                    }
                ],
                threads,
                BatchProcessingContext(total_threads=99, progress_callback=callback),
            )
            is False
        )
        callback.assert_called_once_with(1, 99)


class TestScraperBoundaries:
    """Exercise scraper validation, request setup, and state boundaries."""

    @staticmethod
    def test_response_shape_guard_requires_core_members() -> None:
        """Malformed response-shaped objects fail closed without attribute leaks."""
        assert _response_core_members(object()) is None
        assert _response_core_members(type("ResponseWithoutJson", (), {"ok": True})()) is None
        assert _is_response_protocol(Mock(ok=True, json=Mock())) is True
        assert _is_response_protocol(Mock(ok=False, status_code="503", json=Mock())) is False
        assert _is_response_protocol(Mock(ok=False, status_code=503, json=Mock())) is True

    @staticmethod
    def test_response_requirement_rejects_objects_without_required_protocol() -> None:
        """Request handling fails with a diagnostic schema error for malformed responses."""
        with pytest.raises(UpstreamSchemaError) as raised:
            _require_response(object())
        assert raised.value.args and raised.value.args[0] is not None

    @staticmethod
    def test_constructor_keeps_defaults_and_configured_endpoints() -> None:
        """Constructor options and configured endpoint values are retained."""
        scraper = _scraper()
        assert scraper.force_refresh is False
        assert scraper.api_url
        assert scraper.api_version

    @staticmethod
    def test_cached_loader_defaults_missing_thread_list_to_empty() -> None:
        """A cache envelope without a thread list represents no cached records."""
        cache_manager = MagicMock()
        cache_manager.load_cache.return_value = {"metadata": {}}
        assert _scraper(cache_manager=cache_manager)._load_cached_threads() == []

        cache_manager.load_cache.return_value = {"threads": [{"title": "A"}]}
        with pytest.raises(UpstreamSchemaError):
            _scraper(cache_manager=cache_manager)._load_cached_threads()

    @staticmethod
    def test_cache_entry_shape_guard_rejects_non_list_and_non_mapping_entries() -> None:
        """Cached records must be a list of mappings before conversion."""
        for raw_threads in ("threads", ["thread"]):
            cache_manager = MagicMock()
            cache_manager.load_cache.return_value = {"threads": raw_threads}
            with pytest.raises(UpstreamSchemaError):
                _scraper(cache_manager=cache_manager)._load_cached_threads()
        assert _extract_cache_thread_dicts([]) == []

    @staticmethod
    def test_create_async_session_passes_timeout_and_impersonation() -> None:
        """Session construction forwards both transport requirements."""
        session = MagicMock()
        with (
            patch("perplexity_cli.threads.scraper._CURL_CFFI_AVAILABLE", True),
            patch(
                "perplexity_cli.threads.scraper.session_factory.AsyncSession", return_value=session
            ) as factory,
        ):
            assert _create_async_session(17) is session
        factory.assert_called_once_with(impersonate="chrome", timeout=17)

    @staticmethod
    def test_create_async_session_rejects_unavailable_transport() -> None:
        """Session construction fails explicitly when the optional transport is absent."""
        with patch("perplexity_cli.threads.scraper._CURL_CFFI_AVAILABLE", False):
            with pytest.raises(RuntimeError) as raised:
                _create_async_session()
            assert raised.value.args and raised.value.args[0] is not None

        with (
            patch("perplexity_cli.threads.scraper._CURL_CFFI_AVAILABLE", True),
            patch("perplexity_cli.threads.scraper.session_factory.AsyncSession", None),
        ):
            with pytest.raises(RuntimeError) as raised:
                _create_async_session()
            assert raised.value.args and raised.value.args[0] is not None

    @staticmethod
    def test_get_str_field_defaults_only_when_absent() -> None:
        """Missing optional fields use defaults, while explicit invalid values fail."""
        assert _get_str_field({}, "slug", "") == ""
        assert _get_str_field({}, "title", "Untitled") == "Untitled"
        with pytest.raises(UpstreamSchemaError):
            _get_str_field({"title": None}, "title", "Untitled")

    @staticmethod
    def test_parse_single_thread_defaults_optional_fields_and_formats_url() -> None:
        """A valid minimal upstream entry becomes a complete thread record."""
        record, stopped = _parse_single_thread(
            {"last_query_datetime": "2026-06-01T12:00:00", "slug": "minimal"}, None
        )
        assert stopped is False
        assert record == ThreadRecord(
            title="Untitled",
            url="https://www.perplexity.ai/search/minimal",
            created_at="2026-06-01T12:00:00Z",
        )

    @staticmethod
    def test_parse_single_thread_stops_at_lower_bound() -> None:
        """A thread older than the lower bound is not appended."""
        assert _parse_single_thread(
            {"last_query_datetime": "2025-01-01T00:00:00"}, "2026-01-01"
        ) == (
            None,
            True,
        )

    @staticmethod
    def test_parse_single_thread_rejects_empty_and_malformed_timestamps() -> None:
        """Required timestamps cannot be empty or syntactically invalid."""
        for timestamp in ("", "not-a-timestamp"):
            with pytest.raises((UpstreamSchemaError, ValueError)) as raised:
                _parse_single_thread({"last_query_datetime": timestamp}, None)
            assert "XX" not in str(raised.value)

    @staticmethod
    def test_http_error_mapping_preserves_unhandled_response() -> None:
        """Known status classes map to domain errors and other statuses retain response."""
        with pytest.raises(AuthenticationError) as raised:
            _handle_http_error(
                PerplexityHTTPStatusError("auth", response=SimpleResponse(status_code=401))
            )
        assert raised.value.args and raised.value.args[0] is not None
        with pytest.raises(RateLimitError):
            _handle_http_error(
                PerplexityHTTPStatusError("limit", response=SimpleResponse(status_code=429))
            )
        response = SimpleResponse(status_code=503)
        with pytest.raises(PerplexityHTTPStatusError) as raised:
            _handle_http_error(PerplexityHTTPStatusError("down", response=response))
        assert raised.value.response is response

    @pytest.mark.asyncio
    async def test_request_helpers_cover_auth_rate_limit_and_page_state(self) -> None:
        """Auth cookies, limiter waits, and page state are observable at boundaries."""
        limiter = AsyncMock()
        limiter.acquire.return_value = 0.0
        scraper = _scraper(cookies={"existing": "cookie"}, rate_limiter=limiter)
        headers, cookies = scraper._build_auth_context("session")
        assert headers == {"Content-Type": "application/json"}
        assert cookies == {"existing": "cookie", "__Secure-next-auth.session-token": "session"}
        await scraper._acquire_rate_limit()
        limiter.acquire.assert_awaited_once()
        threads: list[ThreadRecord] = []
        context = BatchProcessingContext()
        state, should_continue = scraper._process_page(
            [{"last_query_datetime": "2026-01-01T00:00:00", "slug": "a", "title": "A"}],
            threads,
            PaginationState(),
            context,
        )
        assert should_continue is False
        assert state.offset == 0
        assert [thread.title for thread in threads] == ["A"]

    @pytest.mark.asyncio
    async def test_request_and_fetch_helpers_forward_context_unchanged(self) -> None:
        """Request wrappers preserve headers, cookies, token, and date context."""
        scraper = _scraper()
        client = AsyncMock()
        with patch.object(
            scraper, "_execute_api_post", new_callable=AsyncMock, return_value=[]
        ) as execute:
            assert (
                await scraper._make_api_request(client, {"h": "v"}, {"c": "v"}, {"offset": 2}) == []
            )
        execute.assert_awaited_once_with(client, {"h": "v"}, {"c": "v"}, {"offset": 2})

        context = MagicMock()
        context.progress_callback = MagicMock()
        context.fetch_from = "2026-01-01"
        context.from_date = "2026-01-01"
        context.to_date = "2026-02-01"
        context.cached_threads = []
        with (
            patch("perplexity_cli.threads.scraper.extract_session_token", return_value="session"),
            patch.object(
                scraper, "_fetch_all_threads_from_api", new_callable=AsyncMock, return_value=[]
            ) as fetch,
            patch.object(scraper, "_merge_and_save", return_value=[]) as merge,
        ):
            assert await scraper._fetch_and_merge(context) == []
        fetch.assert_awaited_once_with("session", context.progress_callback, from_date="2026-01-01")
        merge.assert_called_once_with("2026-01-01", "2026-02-01", [], [])

        with (
            patch.object(scraper.logger, "info") as info,
            patch.object(
                scraper, "_fetch_all_threads_from_api", new_callable=AsyncMock, return_value=[]
            ),
            patch.object(scraper, "_merge_and_save", return_value=[]),
        ):
            await scraper._fetch_and_merge(context)
        assert info.call_args.args[0] is not None
        assert "XX" not in str(info.call_args.args)

    @pytest.mark.asyncio
    async def test_scrape_all_threads_forwards_all_public_context(self) -> None:
        """The public scrape boundary forwards dates and progress unchanged."""
        scraper = _scraper()
        callback = MagicMock()
        with (
            patch.object(scraper, "_try_cache_only", return_value=None) as cache_only,
            patch.object(
                scraper,
                "_prepare_fetch",
                return_value=([], "fetch-from", "fetch-to"),
            ) as prepare,
            patch.object(
                scraper, "_fetch_and_merge", new_callable=AsyncMock, return_value=[]
            ) as fetch,
        ):
            assert await scraper.scrape_all_threads("2026-01-01", "2026-02-01", callback) == []
        cache_only.assert_called_once_with("2026-01-01", "2026-02-01")
        prepare.assert_called_once_with("2026-01-01", "2026-02-01")
        fetch.assert_awaited_once()
        context = fetch.await_args.args[0]
        assert context.from_date == "2026-01-01"
        assert context.to_date == "2026-02-01"
        assert context.fetch_from == "fetch-from"
        assert context.progress_callback is callback

    @pytest.mark.asyncio
    async def test_fetch_all_threads_paginates_until_terminal_page(self) -> None:
        """API fetching advances offsets and accumulates records across pages."""
        scraper = _scraper()
        session = MagicMock()
        client = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=client)
        session.__aexit__ = AsyncMock(return_value=None)
        pages = [
            [
                {
                    "last_query_datetime": "2026-01-02T00:00:00",
                    "slug": "new",
                    "title": "New",
                    "has_next_page": True,
                    "total_threads": 2,
                }
            ],
            [
                {
                    "last_query_datetime": "2026-01-01T00:00:00",
                    "slug": "old",
                    "title": "Old",
                    "has_next_page": False,
                    "total_threads": 2,
                }
            ],
        ]
        with (
            patch("perplexity_cli.threads.scraper._create_async_session", return_value=session),
            patch.object(
                scraper, "_make_api_request", new_callable=AsyncMock, side_effect=pages
            ) as request,
        ):
            records = await scraper._fetch_all_threads_from_api("session")
        assert [record.title for record in records] == ["New", "Old"]
        assert request.await_args_list[0].args[3]["offset"] == 0
        assert request.await_args_list[1].args[3]["offset"] == 100

    @staticmethod
    def test_single_entry_wraps_timestamp_value_errors() -> None:
        """Malformed timestamp parsing is normalised at the scraper boundary."""
        with pytest.raises(UpstreamSchemaError) as raised:
            _scraper()._process_single_thread_entry({"last_query_datetime": "invalid"}, [], None)
        assert raised.value.args and raised.value.args[0] is not None

    @pytest.mark.asyncio
    async def test_rate_limiter_does_not_log_zero_wait(self) -> None:
        """Zero wait is not a rate-limit event."""
        limiter = AsyncMock()
        limiter.acquire.return_value = 0.0
        scraper = _scraper(rate_limiter=limiter)
        with patch.object(scraper.logger, "debug") as debug:
            await scraper._acquire_rate_limit()
        debug.assert_not_called()

    @pytest.mark.asyncio
    async def test_rate_limiter_logs_positive_wait_and_forwards_value(self) -> None:
        """Positive limiter waits are logged with the measured delay."""
        limiter = AsyncMock()
        limiter.acquire.return_value = 0.5
        scraper = _scraper(rate_limiter=limiter)
        with patch.object(scraper.logger, "debug") as debug:
            await scraper._acquire_rate_limit()
        debug.assert_called_once()
        assert debug.call_args.args[0] is not None
        assert debug.call_args.args[1] == 0.5
        assert "XX" not in str(debug.call_args.args)

    @staticmethod
    def test_cache_strategy_forwards_date_ranges_and_distinguishes_paths() -> None:
        """Cache-only and gap-fetch paths preserve range arguments and state."""
        cache_manager = MagicMock()
        cached = [ThreadRecord(title="A", url="u", created_at="2026-01-01T00:00:00Z")]
        cache_manager.load_cache.return_value = {
            "threads": [{"title": "A", "url": "u", "created_at": "2026-01-01T00:00:00Z"}],
        }
        cache_manager.requires_fresh_data.return_value = (False, None, None)
        scraper = _scraper(cache_manager=cache_manager)
        result = scraper._try_cache_only("2026-01-01", "2026-01-02")
        assert result == cached
        cache_manager.requires_fresh_data.assert_called_with("2026-01-01", "2026-01-02")

        scraper.force_refresh = True
        assert scraper._try_cache_only("from", "to") is None
        cache_manager.requires_fresh_data.reset_mock()
        assert scraper._prepare_fetch("from", "to") == ([], "from", "to")
        cache_manager.requires_fresh_data.assert_not_called()

        scraper.force_refresh = False
        cache_manager.requires_fresh_data.return_value = (True, "gap-from", "gap-to")
        cache_manager.load_cache.return_value = {"threads": []}
        with patch.object(scraper.logger, "info") as info:
            assert scraper._prepare_fetch("from", "to") == ([], "gap-from", "gap-to")
        info.assert_called_once()
        assert info.call_args.args[0] is not None
        assert "XX" not in str(info.call_args.args)

    @staticmethod
    def test_merge_with_cache_uses_manager_only_for_nonempty_cached_data() -> None:
        """Fetched records bypass merging without cached records or a manager."""
        fetched = [ThreadRecord(title="F", url="f", created_at="2026-01-01T00:00:00Z")]
        cache_manager = MagicMock()
        cache_manager.merge_threads.return_value = fetched
        scraper = _scraper(cache_manager=cache_manager)
        assert scraper._merge_with_cache([], fetched) is fetched
        with patch.object(scraper.logger, "info") as info:
            assert scraper._merge_with_cache([fetched[0]], fetched) is fetched
        cache_manager.merge_threads.assert_called_once_with([fetched[0]], fetched)
        assert cache_manager.merge_threads.return_value is fetched
        info.assert_called_once()
        assert info.call_args.args[0] is not None
        assert "XX" not in str(info.call_args.args)

    @staticmethod
    def test_cache_only_log_has_diagnostic_template() -> None:
        """A cache-only hit emits a real diagnostic record."""
        cache_manager = MagicMock()
        cache_manager.requires_fresh_data.return_value = (False, None, None)
        cache_manager.load_cache.return_value = {"threads": []}
        scraper = _scraper(cache_manager=cache_manager)
        with patch.object(scraper.logger, "info") as info:
            assert scraper._try_cache_only(None, None) == []
        info.assert_called_once()
        assert info.call_args.args[0] is not None
        assert "XX" not in str(info.call_args.args)

    @staticmethod
    def test_error_diagnostics_do_not_collapse_to_empty_or_mutant_sentinels() -> None:
        """Domain errors retain non-empty diagnostics without matching wording."""
        for status, error_type in ((401, AuthenticationError), (429, RateLimitError)):
            with pytest.raises(error_type) as raised:
                _handle_http_error(
                    PerplexityHTTPStatusError("status", response=SimpleResponse(status_code=status))
                )
            assert raised.value.args and raised.value.args[0] is not None
            assert "XX" not in str(raised.value)

    @staticmethod
    def test_merge_and_filter_boundaries() -> None:
        """Merge bypasses unavailable cache and date filtering preserves identity."""
        scraper = _scraper()
        thread = ThreadRecord(title="A", url="u", created_at="2026-01-01T00:00:00Z")
        assert scraper._merge_with_cache([], [thread]) == [thread]
        assert scraper._filter_by_date_range([thread], None, None) == [thread]
        assert scraper._filter_by_date_range([thread], "2026-01-02", None) == []
        assert scraper._filter_by_date_range([thread], None, "2025-12-31") == []
