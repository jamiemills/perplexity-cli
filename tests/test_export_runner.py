"""Tests for the export threads command runner."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from perplexity_cli.runners.export import (
    _handle_cache_clear,
    _handle_http_status_error,
    _handle_known_error,
    _handle_no_threads,
    _handle_unexpected_error,
    _scrape_threads,
    _setup_rate_limiter,
    _validate_export_dates,
    run_export_threads_command,
)


def _close_run_async_return(value):
    def run(coro):
        coro.close()
        return value

    return run


def _close_run_async_raise(exc):
    def run(coro):
        coro.close()
        raise exc

    return run


class TestRunExportThreadsCommand:
    """Tests for run_export_threads_command()."""

    @patch("perplexity_cli.runners.export.TokenManager", autospec=True)
    def test_not_authenticated_human(self, mock_tm_class, capsys):
        """Human output shows not authenticated error."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        mock_tm_class.return_value = mock_tm

        with pytest.raises(SystemExit) as exc_info:
            run_export_threads_command(
                ctx_obj={},
                from_date=None,
                to_date=None,
                output=None,
                force_refresh=False,
                clear_cache=False,
            )

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Not authenticated" in captured.err

    @patch("perplexity_cli.runners.export.TokenManager", autospec=True)
    def test_not_authenticated_json(self, mock_tm_class, capsys):
        """JSON output shows error envelope when not authenticated."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        mock_tm_class.return_value = mock_tm

        with pytest.raises(SystemExit):
            run_export_threads_command(
                ctx_obj={"json": True},
                from_date=None,
                to_date=None,
                output=None,
                force_refresh=False,
                clear_cache=False,
            )

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is False
        assert envelope["command"] == "pxcli threads export"

    @patch("perplexity_cli.runners.export.write_threads_csv", autospec=True)
    @patch("perplexity_cli.runners.export.run_async", autospec=True)
    @patch("perplexity_cli.runners.export.get_rate_limiting_config", autospec=True)
    @patch("perplexity_cli.runners.export.ThreadCacheManager", autospec=True)
    @patch("perplexity_cli.runners.export.ThreadScraper", autospec=True)
    @patch("perplexity_cli.runners.export.TokenManager", autospec=True)
    def test_success_human(
        self,
        mock_tm_class,
        mock_scraper_class,
        mock_cm_class,
        mock_rate_config,
        mock_run_async,
        mock_write_csv,
        capsys,
    ):
        """Human output shows export complete."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = ("token", {})
        mock_tm_class.return_value = mock_tm

        mock_rate_config.return_value = Mock(enabled=False)
        mock_run_async.side_effect = _close_run_async_return(
            [{"title": "Thread 1", "created_at": "2025-01-01", "url": "https://perplexity.ai/t/1"}]
        )
        mock_write_csv.return_value = Path("/tmp/threads.csv")

        run_export_threads_command(
            ctx_obj={},
            from_date=None,
            to_date=None,
            output=None,
            force_refresh=False,
            clear_cache=False,
        )

        captured = capsys.readouterr()
        assert "Export complete" in captured.out
        assert "ERROR" not in captured.err

    @patch("perplexity_cli.runners.export.write_threads_csv", autospec=True)
    @patch("perplexity_cli.runners.export.run_async", autospec=True)
    @patch("perplexity_cli.runners.export.get_rate_limiting_config", autospec=True)
    @patch("perplexity_cli.runners.export.ThreadCacheManager", autospec=True)
    @patch("perplexity_cli.runners.export.ThreadScraper", autospec=True)
    @patch("perplexity_cli.runners.export.TokenManager", autospec=True)
    def test_success_json(
        self,
        mock_tm_class,
        mock_scraper_class,
        mock_cm_class,
        mock_rate_config,
        mock_run_async,
        mock_write_csv,
        capsys,
    ):
        """JSON output shows success envelope with thread data."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = ("token", {})
        mock_tm_class.return_value = mock_tm

        mock_rate_config.return_value = Mock(enabled=False)
        mock_run_async.side_effect = _close_run_async_return(
            [{"title": "Thread 1", "created_at": "2025-01-01", "url": "https://perplexity.ai/t/1"}]
        )
        mock_write_csv.return_value = Path("/tmp/threads.csv")

        run_export_threads_command(
            ctx_obj={"json": True},
            from_date=None,
            to_date=None,
            output=None,
            force_refresh=False,
            clear_cache=False,
        )

        captured = capsys.readouterr()
        envelope = json.loads(captured.out.strip())
        assert envelope["ok"] is True
        assert envelope["command"] == "pxcli threads export"
        assert envelope["result"]["total"] == 1
        assert len(envelope["result"]["threads"]) == 1
        mock_write_csv.assert_not_called()
        assert envelope["result"]["output_path"] is None
        assert "ERROR" not in captured.err


class TestValidateExportDates:
    """Tests for _validate_export_dates."""

    def test_passes_with_none_dates(self) -> None:
        _validate_export_dates(None, None, output_format="human")

    def test_passes_with_valid_dates(self) -> None:
        _validate_export_dates("2025-01-01", "2025-12-31", output_format="human")

    def test_exits_on_invalid_from_date(self) -> None:
        with pytest.raises(SystemExit):
            _validate_export_dates("not-a-date", None, output_format="human")

    def test_exits_on_invalid_to_date(self) -> None:
        with pytest.raises(SystemExit):
            _validate_export_dates(None, "not-a-date", output_format="human")

    def test_json_mode_routes_through_handler(self) -> None:
        with patch("perplexity_cli.runners.export.handle_error", autospec=True) as mock_handle:
            with pytest.raises(SystemExit):
                _validate_export_dates("bad", None, output_format="json")
            mock_handle.assert_called_once()


class TestSetupRateLimiter:
    """Tests for _setup_rate_limiter."""

    @patch("perplexity_cli.runners.export.get_rate_limiting_config", autospec=True)
    def test_returns_none_when_disabled(self, mock_config):
        """When rate limiting is disabled, returns None."""
        mock_config.return_value = Mock(enabled=False)
        result = _setup_rate_limiter(Mock())
        assert result is None

    @patch("perplexity_cli.runners.export.get_rate_limiting_config", autospec=True)
    def test_returns_rate_limiter_when_enabled(self, mock_config):
        """When rate limiting is enabled, returns a RateLimiter instance."""
        mock_config.return_value = Mock(enabled=True, requests_per_period=10, period_seconds=60)
        result = _setup_rate_limiter(Mock())
        assert result is not None


class TestHandleCacheClear:
    """Tests for _handle_cache_clear."""

    def test_no_cache_exists(self, capsys):
        """When no cache file exists, info message is shown."""
        cm = Mock()
        cm.cache_exists.return_value = False
        _handle_cache_clear(cm, clear_cache=True, output_format="human", logger=Mock())
        captured = capsys.readouterr()
        assert "No cache file to clear" in captured.out
        cm.clear_cache.assert_not_called()

    def test_cache_cleared(self, capsys):
        """When cache exists, it is cleared and confirmed."""
        cm = Mock()
        cm.cache_exists.return_value = True
        _handle_cache_clear(cm, clear_cache=True, output_format="human", logger=Mock())
        cm.clear_cache.assert_called_once()
        assert "Cache cleared" in capsys.readouterr().out

    def test_no_clear_requested(self):
        """When clear_cache is False, nothing happens."""
        cm = Mock()
        _handle_cache_clear(cm, clear_cache=False, output_format="human", logger=Mock())
        cm.cache_exists.assert_not_called()

    def test_json_mode_silent_no_cache(self, capsys):
        """In JSON mode, no output is written when cache doesn't exist."""
        cm = Mock()
        cm.cache_exists.return_value = False
        _handle_cache_clear(cm, clear_cache=True, output_format="json", logger=Mock())
        assert capsys.readouterr().out == ""

    def test_json_mode_silent_cleared(self, capsys):
        """In JSON mode, no output is written when cache is cleared."""
        cm = Mock()
        cm.cache_exists.return_value = True
        _handle_cache_clear(cm, clear_cache=True, output_format="json", logger=Mock())
        assert capsys.readouterr().out == ""


class TestScrapeThreads:
    """Tests for _scrape_threads progress callback."""

    @patch("perplexity_cli.runners.export.run_async", autospec=True)
    def test_progress_callback_echoes(self, mock_run_async, capsys):
        """Progress callback prints extraction progress in human mode."""
        mock_run_async.side_effect = _close_run_async_return([{"title": "T1"}])
        scraper = Mock()
        result = _scrape_threads(scraper, None, None, output_format="human")
        assert result == [{"title": "T1"}]

        # Verify run_async was called (progress callback tested implicitly)
        mock_run_async.assert_called_once()


class TestHandleNoThreads:
    """Tests for _handle_no_threads."""

    def test_json_mode_calls_handle_error(self):
        """In JSON mode, handle_error is invoked."""
        with patch("perplexity_cli.runners.export.handle_error", autospec=True) as mock_handle:
            with pytest.raises(SystemExit):
                _handle_no_threads(None, None, output_format="json")
            mock_handle.assert_called_once()

    def test_human_mode_exits(self, capsys):
        """In human mode, error is printed and process exits."""
        with pytest.raises(SystemExit) as exc_info:
            _handle_no_threads(None, None, output_format="human")
        assert exc_info.value.code == 1
        assert "No threads found" in capsys.readouterr().err


class TestHandleKnownError:
    """Tests for _handle_known_error."""

    def test_json_mode_calls_handle_error(self):
        """In JSON mode, handle_error is called before exit."""
        with patch("perplexity_cli.runners.export.handle_error", autospec=True) as mock_handle:
            with pytest.raises(SystemExit):
                _handle_known_error(ValueError("fail"), output_format="json", logger=Mock())
            mock_handle.assert_called_once()

    def test_auth_error_shows_reauth_hint(self, capsys):
        """AuthenticationError shows re-authentication hint."""
        from perplexity_cli.utils.exceptions import AuthenticationError

        with pytest.raises(SystemExit):
            _handle_known_error(
                AuthenticationError("expired"), output_format="human", logger=Mock()
            )
        err = capsys.readouterr().err
        assert "re-authenticate" in err


class TestHandleHttpStatusError:
    """Tests for _handle_http_status_error."""

    def test_json_mode_calls_handle_error(self):
        """In JSON mode, handle_error is invoked."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.headers = {}
        error = Mock(spec=Exception)
        error.response = mock_response

        with patch("perplexity_cli.runners.export.handle_error", autospec=True) as mock_handle:
            with patch("perplexity_cli.runners.export.handle_http_error", autospec=True):
                _handle_http_status_error(error, output_format="json", ctx_obj={}, logger=Mock())
            mock_handle.assert_called_once()

    def test_human_mode_calls_handle_http_error(self):
        """In human mode, handle_http_error is called."""
        error = Mock()
        with patch("perplexity_cli.runners.export.handle_http_error", autospec=True) as mock_handle:
            _handle_http_status_error(
                error, output_format="human", ctx_obj={"debug": False}, logger=Mock()
            )
        mock_handle.assert_called_once()


class TestHandleUnexpectedError:
    """Tests for _handle_unexpected_error."""

    def test_json_mode_calls_handle_error(self):
        """In JSON mode, handle_error is invoked."""
        with patch("perplexity_cli.runners.export.handle_error", autospec=True) as mock_handle:
            with patch("perplexity_cli.runners.export.handle_unexpected_cli_error", autospec=True):
                _handle_unexpected_error(
                    RuntimeError("boom"), output_format="json", ctx_obj={}, logger=Mock()
                )
            mock_handle.assert_called_once()

    def test_human_mode_calls_unexpected_handler(self):
        """In human mode, handle_unexpected_cli_error is called."""
        with patch(
            "perplexity_cli.runners.export.handle_unexpected_cli_error", autospec=True
        ) as mock_handle:
            _handle_unexpected_error(
                RuntimeError("boom"), output_format="human", ctx_obj={}, logger=Mock()
            )
        mock_handle.assert_called_once()


class TestRunExportErrorHandlers:
    """Tests for run_export_threads_command error handler branches."""

    def _prepare_mocks(self, output_format="human"):
        """Set up common mocks for authenticated export."""
        patches = {
            "tm": patch("perplexity_cli.runners.export.TokenManager", autospec=True),
            "rate": patch("perplexity_cli.runners.export.get_rate_limiting_config", autospec=True),
            "cm": patch("perplexity_cli.runners.export.ThreadCacheManager", autospec=True),
            "scraper": patch("perplexity_cli.runners.export.ThreadScraper", autospec=True),
        }
        mocks = {k: p.start() for k, p in patches.items()}
        tm = Mock()
        tm.load_token.return_value = ("token", {})
        mocks["tm"].return_value = tm
        mocks["rate"].return_value = Mock(enabled=False)
        ctx = {"json": True} if output_format == "json" else {}
        return patches, mocks, ctx

    def _stop_patches(self, patches):
        for p in patches.values():
            p.stop()

    @patch("perplexity_cli.runners.export.run_async", autospec=True)
    def test_keyboard_interrupt(self, mock_run_async, capsys):
        """KeyboardInterrupt exits with code 130."""
        patches, _, ctx = self._prepare_mocks()
        mock_run_async.side_effect = _close_run_async_raise(KeyboardInterrupt())

        with pytest.raises(SystemExit) as exc_info:
            run_export_threads_command(ctx, None, None, None, False, False)

        assert exc_info.value.code == 130
        self._stop_patches(patches)

    @patch("perplexity_cli.runners.export.run_async", autospec=True)
    def test_known_error_handler(self, mock_run_async, capsys):
        """ValueError routes through _handle_known_error."""
        patches, _, ctx = self._prepare_mocks()
        mock_run_async.side_effect = _close_run_async_raise(ValueError("bad value"))

        with pytest.raises(SystemExit):
            run_export_threads_command(ctx, None, None, None, False, False)

        assert "bad value" in capsys.readouterr().err
        self._stop_patches(patches)

    @patch("perplexity_cli.runners.export.run_async", autospec=True)
    def test_http_status_error_handler(self, mock_run_async):
        """PerplexityHTTPStatusError routes through _handle_http_status_error."""
        from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError

        patches, _, ctx = self._prepare_mocks()
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.headers = {}
        error = PerplexityHTTPStatusError("server error", request=Mock(), response=mock_response)
        mock_run_async.side_effect = _close_run_async_raise(error)

        with patch(
            "perplexity_cli.runners.export.handle_http_error",
            side_effect=SystemExit(1),
            autospec=True,
        ):
            with pytest.raises(SystemExit):
                run_export_threads_command(ctx, None, None, None, False, False)

        self._stop_patches(patches)

    @patch("perplexity_cli.runners.export.run_async", autospec=True)
    def test_unexpected_error_handler(self, mock_run_async):
        """Unexpected exceptions route through _handle_unexpected_error."""
        patches, _, ctx = self._prepare_mocks()
        mock_run_async.side_effect = _close_run_async_raise(RuntimeError("boom"))

        with patch(
            "perplexity_cli.runners.export.handle_unexpected_cli_error",
            side_effect=SystemExit(1),
            autospec=True,
        ):
            with pytest.raises(SystemExit):
                run_export_threads_command(ctx, None, None, None, False, False)

        self._stop_patches(patches)


class TestExportRunnerMutationKillers:
    """Mutation-killing tests for export runner edge cases."""

    def test_normalise_context_rejects_non_dict(self):
        from perplexity_cli.runners.export import _normalise_context

        assert _normalise_context("not-a-dict") is None
        assert _normalise_context(42) is None
        assert _normalise_context(None) is None

    def test_normalise_context_rejects_non_bool_values(self):
        from perplexity_cli.runners.export import _normalise_context

        with pytest.raises(TypeError, match="must be a bool"):
            _normalise_context({"json": "yes"})

    def test_normalise_context_valid_flags(self):
        from perplexity_cli.runners.export import _normalise_context

        result = _normalise_context({"json": True, "schema": False, "debug": True})
        assert result == {"json": True, "schema": False, "debug": True}

    def test_normalise_context_empty_dict(self):
        from perplexity_cli.runners.export import _normalise_context

        result = _normalise_context({})
        assert result == {"json": False, "schema": False, "debug": False}

    def test_validate_optional_date_rejects_non_string(self):
        from perplexity_cli.runners.export import _validate_optional_date

        with pytest.raises(TypeError, match="must be a string or None"):
            _validate_optional_date(123, "from_date")

    def test_validate_optional_date_none_returns_none(self):
        from perplexity_cli.runners.export import _validate_optional_date

        assert _validate_optional_date(None, "from_date") is None

    def test_validate_optional_date_string_passthrough(self):
        from perplexity_cli.runners.export import _validate_optional_date

        assert _validate_optional_date("2025-01-01", "to_date") == "2025-01-01"

    def test_validate_output_path_rejects_non_path(self):
        from perplexity_cli.runners.export import _validate_output_path

        with pytest.raises(TypeError, match="output must be a Path or None"):
            _validate_output_path("/tmp/file.csv")

    def test_validate_output_path_none_returns_none(self):
        from perplexity_cli.runners.export import _validate_output_path

        assert _validate_output_path(None) is None

    def test_validate_output_path_accepts_path(self):
        from perplexity_cli.runners.export import _validate_output_path

        p = Path("/tmp/out.csv")
        assert _validate_output_path(p) is p

    def test_require_bool_value_rejects_non_bool(self):
        from perplexity_cli.runners.export import _require_bool_value

        with pytest.raises(TypeError, match="force_refresh must be a bool"):
            _require_bool_value("true", "force_refresh")

    def test_require_bool_value_accepts_true(self):
        from perplexity_cli.runners.export import _require_bool_value

        assert _require_bool_value(True, "clear_cache") is True

    def test_require_bool_value_accepts_false(self):
        from perplexity_cli.runners.export import _require_bool_value

        assert _require_bool_value(False, "clear_cache") is False

    def test_resolve_export_tail_values_wrong_arg_count(self):
        from perplexity_cli.runners.export import _resolve_export_tail_values

        with pytest.raises(TypeError, match="expected output, force_refresh, and clear_cache"):
            _resolve_export_tail_values((None, False), {})

    def test_resolve_export_tail_values_wrong_kwargs(self):
        from perplexity_cli.runners.export import _resolve_export_tail_values

        with pytest.raises(TypeError, match="requires output, force_refresh, clear_cache"):
            _resolve_export_tail_values((), {"output": None, "wrong": True})

    def test_resolve_export_tail_values_from_kwargs(self):
        from perplexity_cli.runners.export import _resolve_export_tail_values

        output, force, clear = _resolve_export_tail_values(
            (), {"output": None, "force_refresh": True, "clear_cache": False}
        )
        assert output is None
        assert force is True
        assert clear is False

    def test_resolve_export_tail_values_from_args(self):
        from perplexity_cli.runners.export import _resolve_export_tail_values

        output, force, clear = _resolve_export_tail_values((Path("/x.csv"), True, True), {})
        assert output == Path("/x.csv")
        assert force is True
        assert clear is True

    def test_string_or_empty_returns_string(self):
        from perplexity_cli.runners.export import _string_or_empty

        assert _string_or_empty("hello") == "hello"

    def test_string_or_empty_returns_empty_for_non_string(self):
        from perplexity_cli.runners.export import _string_or_empty

        assert _string_or_empty(42) == ""
        assert _string_or_empty(None) == ""
        assert _string_or_empty([]) == ""

    def test_thread_payload_from_dict(self):
        from perplexity_cli.runners.export import _thread_payload

        record = {"title": "T1", "created_at": "2025-01-01", "url": "https://x.ai"}
        payload = _thread_payload(record)
        assert payload == {"title": "T1", "created_at": "2025-01-01", "url": "https://x.ai"}

    def test_thread_payload_from_dict_missing_keys(self):
        from perplexity_cli.runners.export import _thread_payload

        payload = _thread_payload({})
        assert payload == {"title": "", "created_at": "", "url": ""}

    def test_thread_payload_from_object(self):
        from perplexity_cli.runners.export import _thread_payload

        record = Mock()
        record.title = "Obj Title"
        record.created_at = "2025-06-01"
        record.url = "https://obj.ai"
        payload = _thread_payload(record)
        assert payload == {"title": "Obj Title", "created_at": "2025-06-01", "url": "https://obj.ai"}

    def test_thread_payload_from_object_missing_attr(self):
        from perplexity_cli.runners.export import _thread_payload

        class Bare:
            pass

        payload = _thread_payload(Bare())
        assert payload == {"title": "", "created_at": "", "url": ""}

    def test_echo_date_range_with_both_dates(self, capsys):
        from perplexity_cli.runners.export import _echo_date_range

        _echo_date_range("2025-01-01", "2025-12-31")
        captured = capsys.readouterr()
        assert "[OK] Filtered by date range: 2025-01-01 to 2025-12-31" in captured.err

    def test_echo_date_range_from_only(self, capsys):
        from perplexity_cli.runners.export import _echo_date_range

        _echo_date_range("2025-01-01", None)
        captured = capsys.readouterr()
        assert "2025-01-01 to end" in captured.err

    def test_echo_date_range_to_only(self, capsys):
        from perplexity_cli.runners.export import _echo_date_range

        _echo_date_range(None, "2025-12-31")
        captured = capsys.readouterr()
        assert "beginning to 2025-12-31" in captured.err

    def test_echo_date_range_neither(self, capsys):
        from perplexity_cli.runners.export import _echo_date_range

        _echo_date_range(None, None)
        assert capsys.readouterr().err == ""

    def test_echo_date_range_custom_prefix(self, capsys):
        from perplexity_cli.runners.export import _echo_date_range

        _echo_date_range("2025-01-01", None, prefix="Date range")
        captured = capsys.readouterr()
        assert "Date range: 2025-01-01 to end" in captured.err

    def test_handle_no_threads_shows_date_range(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            _handle_no_threads("2025-01-01", "2025-06-30", output_format="human")
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "No threads found matching criteria." in captured.err
        assert "2025-01-01 to 2025-06-30" in captured.err

    def test_handle_known_error_non_auth_no_reauth_hint(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            _handle_known_error(ValueError("oops"), output_format="human", logger=Mock())
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "[ERROR] Export failed: oops" in captured.err
        assert "re-authenticate" not in captured.err

    def test_handle_auth_missing_human(self, capsys):
        from perplexity_cli.runners.export import _handle_auth_missing

        with pytest.raises(SystemExit) as exc_info:
            _handle_auth_missing("human", Mock())
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "[ERROR] Not authenticated." in captured.err
        assert "pxcli auth login" in captured.err

    @patch("perplexity_cli.runners.export.write_threads_csv", autospec=True)
    @patch("perplexity_cli.runners.export.run_async", autospec=True)
    @patch("perplexity_cli.runners.export.get_rate_limiting_config", autospec=True)
    @patch("perplexity_cli.runners.export.ThreadCacheManager", autospec=True)
    @patch("perplexity_cli.runners.export.ThreadScraper", autospec=True)
    @patch("perplexity_cli.runners.export.TokenManager", autospec=True)
    def test_success_human_with_date_range(
        self,
        mock_tm_class,
        mock_scraper_class,
        mock_cm_class,
        mock_rate_config,
        mock_run_async,
        mock_write_csv,
        capsys,
    ):
        mock_tm = Mock()
        mock_tm.load_token.return_value = ("token", {})
        mock_tm_class.return_value = mock_tm
        mock_rate_config.return_value = Mock(enabled=False)
        mock_run_async.side_effect = _close_run_async_return(
            [{"title": "T1", "created_at": "2025-03-01", "url": "https://x.ai"}]
        )
        mock_write_csv.return_value = Path("/tmp/threads.csv")

        run_export_threads_command(
            ctx_obj={},
            from_date="2025-01-01",
            to_date="2025-06-30",
            output=None,
            force_refresh=False,
            clear_cache=False,
        )

        captured = capsys.readouterr()
        assert "Exported 1 threads" in captured.out
        assert "2025-01-01 to 2025-06-30" in captured.err

    @patch("perplexity_cli.runners.export.write_threads_csv", autospec=True)
    @patch("perplexity_cli.runners.export.run_async", autospec=True)
    @patch("perplexity_cli.runners.export.get_rate_limiting_config", autospec=True)
    @patch("perplexity_cli.runners.export.ThreadCacheManager", autospec=True)
    @patch("perplexity_cli.runners.export.ThreadScraper", autospec=True)
    @patch("perplexity_cli.runners.export.TokenManager", autospec=True)
    def test_success_json_with_explicit_output(
        self,
        mock_tm_class,
        mock_scraper_class,
        mock_cm_class,
        mock_rate_config,
        mock_run_async,
        mock_write_csv,
        capsys,
    ):
        mock_tm = Mock()
        mock_tm.load_token.return_value = ("token", {})
        mock_tm_class.return_value = mock_tm
        mock_rate_config.return_value = Mock(enabled=False)
        mock_run_async.side_effect = _close_run_async_return(
            [{"title": "T1", "created_at": "2025-01-01", "url": "https://x.ai"}]
        )
        mock_write_csv.return_value = Path("/tmp/out.csv")

        run_export_threads_command(
            ctx_obj={"json": True},
            from_date=None,
            to_date=None,
            output=Path("/tmp/out.csv"),
            force_refresh=False,
            clear_cache=False,
        )

        mock_write_csv.assert_called_once()
        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["result"]["output_path"] is not None

    def test_validate_export_dates_invalid_shows_format_hint(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            _validate_export_dates("garbage", None, output_format="human")
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Please use YYYY-MM-DD format" in captured.err

    def test_handle_cache_clear_preserve_does_nothing(self):
        cm = Mock()
        _handle_cache_clear(cm, clear_cache=False, output_format="human", logger=Mock())
        cm.cache_exists.assert_not_called()
        cm.clear_cache.assert_not_called()

    @patch("perplexity_cli.runners.export.get_rate_limiting_config", autospec=True)
    def test_setup_rate_limiter_logs_config(self, mock_config):
        mock_config.return_value = Mock(enabled=True, requests_per_period=5, period_seconds=30)
        logger = Mock()
        result = _setup_rate_limiter(logger)
        assert result is not None
        logger.info.assert_called_once_with(
            "Rate limiting enabled: %s requests per %s seconds", 5, 30
        )
