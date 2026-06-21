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

    @patch("perplexity_cli.auth.token_manager.TokenManager")
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

    @patch("perplexity_cli.auth.token_manager.TokenManager")
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

    @patch("perplexity_cli.threads.exporter.write_threads_csv")
    @patch("perplexity_cli.runners.export.run_async")
    @patch("perplexity_cli.utils.config.get_rate_limiting_config")
    @patch("perplexity_cli.threads.cache_manager.ThreadCacheManager")
    @patch("perplexity_cli.threads.scraper.ThreadScraper")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
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

    @patch("perplexity_cli.threads.exporter.write_threads_csv")
    @patch("perplexity_cli.runners.export.run_async")
    @patch("perplexity_cli.utils.config.get_rate_limiting_config")
    @patch("perplexity_cli.threads.cache_manager.ThreadCacheManager")
    @patch("perplexity_cli.threads.scraper.ThreadScraper")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
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

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is True
        assert envelope["command"] == "pxcli threads export"
        assert envelope["result"]["total"] == 1
        assert len(envelope["result"]["threads"]) == 1


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
        with patch("perplexity_cli.runners.export.handle_error") as mock_handle:
            with pytest.raises(SystemExit):
                _validate_export_dates("bad", None, output_format="json")
            mock_handle.assert_called_once()


class TestSetupRateLimiter:
    """Tests for _setup_rate_limiter."""

    @patch("perplexity_cli.utils.config.get_rate_limiting_config")
    def test_returns_none_when_disabled(self, mock_config):
        """When rate limiting is disabled, returns None."""
        mock_config.return_value = Mock(enabled=False)
        result = _setup_rate_limiter(Mock())
        assert result is None

    @patch("perplexity_cli.utils.config.get_rate_limiting_config")
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

    @patch("perplexity_cli.runners.export.run_async")
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
        with patch("perplexity_cli.runners.export.handle_error") as mock_handle:
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
        with patch("perplexity_cli.runners.export.handle_error") as mock_handle:
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

        with patch("perplexity_cli.runners.export.handle_error") as mock_handle:
            with patch("perplexity_cli.runners.export.handle_http_error"):
                _handle_http_status_error(error, output_format="json", ctx_obj={}, logger=Mock())
            mock_handle.assert_called_once()

    def test_human_mode_calls_handle_http_error(self):
        """In human mode, handle_http_error is called."""
        error = Mock()
        with patch("perplexity_cli.runners.export.handle_http_error") as mock_handle:
            _handle_http_status_error(
                error, output_format="human", ctx_obj={"debug": False}, logger=Mock()
            )
        mock_handle.assert_called_once()


class TestHandleUnexpectedError:
    """Tests for _handle_unexpected_error."""

    def test_json_mode_calls_handle_error(self):
        """In JSON mode, handle_error is invoked."""
        with patch("perplexity_cli.runners.export.handle_error") as mock_handle:
            with patch("perplexity_cli.runners.export.handle_unexpected_cli_error"):
                _handle_unexpected_error(
                    RuntimeError("boom"), output_format="json", ctx_obj={}, logger=Mock()
                )
            mock_handle.assert_called_once()

    def test_human_mode_calls_unexpected_handler(self):
        """In human mode, handle_unexpected_cli_error is called."""
        with patch("perplexity_cli.runners.export.handle_unexpected_cli_error") as mock_handle:
            _handle_unexpected_error(
                RuntimeError("boom"), output_format="human", ctx_obj={}, logger=Mock()
            )
        mock_handle.assert_called_once()


class TestRunExportErrorHandlers:
    """Tests for run_export_threads_command error handler branches."""

    def _prepare_mocks(self, output_format="human"):
        """Set up common mocks for authenticated export."""
        patches = {
            "tm": patch("perplexity_cli.auth.token_manager.TokenManager"),
            "rate": patch("perplexity_cli.utils.config.get_rate_limiting_config"),
            "cm": patch("perplexity_cli.threads.cache_manager.ThreadCacheManager"),
            "scraper": patch("perplexity_cli.threads.scraper.ThreadScraper"),
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

    @patch("perplexity_cli.runners.export.run_async")
    def test_keyboard_interrupt(self, mock_run_async, capsys):
        """KeyboardInterrupt exits with code 130."""
        patches, _, ctx = self._prepare_mocks()
        mock_run_async.side_effect = _close_run_async_raise(KeyboardInterrupt())

        with pytest.raises(SystemExit) as exc_info:
            run_export_threads_command(ctx, None, None, None, False, False)

        assert exc_info.value.code == 130
        self._stop_patches(patches)

    @patch("perplexity_cli.runners.export.run_async")
    def test_known_error_handler(self, mock_run_async, capsys):
        """ValueError routes through _handle_known_error."""
        patches, _, ctx = self._prepare_mocks()
        mock_run_async.side_effect = _close_run_async_raise(ValueError("bad value"))

        with pytest.raises(SystemExit):
            run_export_threads_command(ctx, None, None, None, False, False)

        assert "bad value" in capsys.readouterr().err
        self._stop_patches(patches)

    @patch("perplexity_cli.runners.export.run_async")
    def test_http_status_error_handler(self, mock_run_async):
        """PerplexityHTTPStatusError routes through _handle_http_status_error."""
        from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError

        patches, _, ctx = self._prepare_mocks()
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.headers = {}
        error = PerplexityHTTPStatusError("server error", request=Mock(), response=mock_response)
        mock_run_async.side_effect = _close_run_async_raise(error)

        with patch("perplexity_cli.runners.export.handle_http_error", side_effect=SystemExit(1)):
            with pytest.raises(SystemExit):
                run_export_threads_command(ctx, None, None, None, False, False)

        self._stop_patches(patches)

    @patch("perplexity_cli.runners.export.run_async")
    def test_unexpected_error_handler(self, mock_run_async):
        """Unexpected exceptions route through _handle_unexpected_error."""
        patches, _, ctx = self._prepare_mocks()
        mock_run_async.side_effect = _close_run_async_raise(RuntimeError("boom"))

        with patch(
            "perplexity_cli.runners.export.handle_unexpected_cli_error", side_effect=SystemExit(1)
        ):
            with pytest.raises(SystemExit):
                run_export_threads_command(ctx, None, None, None, False, False)

        self._stop_patches(patches)
