"""Tests for the export threads command runner."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from contextlib import contextmanager, redirect_stderr
from inspect import signature
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from perplexity_cli.config.models import RateLimitConfig
from perplexity_cli.runners.export import (
    CacheAction,
    ExportDateRange,
    ExportResult,
    OutputMode,
    _echo_date_range,
    _emit_json_error,
    _handle_cache_action,
    _handle_cache_clear,
    _handle_http_status_error,
    _handle_known_error,
    _handle_no_threads,
    _handle_unexpected_error,
    _output_export_results,
    _output_json,
    _resolve_ctx_flags,
    _scrape_threads,
    _validate_export_dates,
    run_export_threads_command,
)
from perplexity_cli.threads.exporter import ThreadRecord
from perplexity_cli.utils.exceptions import (
    AuthenticationError,
    PerplexityHTTPStatusError,
    SimpleRequest,
    SimpleResponse,
)
from tests.helpers.fake_services import FakeCacheManager, FakeThreadScraper, FakeTokenManager

_LOGGER = logging.getLogger("test-export-runner")

_THREAD_1 = ThreadRecord(title="Thread 1", created_at="2025-01-01", url="https://perplexity.ai/t/1")


@contextmanager
def _export_dependencies(token_manager, cache_manager, scraper, rate_config):
    """Patch the export runner's dependency boundaries with typed fakes."""
    with (
        patch("perplexity_cli.runners.export._create_token_manager", new=lambda: token_manager),
        patch("perplexity_cli.runners.export._create_cache_manager", new=lambda: cache_manager),
        patch("perplexity_cli.runners.export.ThreadScraper", new=lambda *args, **kwargs: scraper),
        patch("perplexity_cli.runners.export.get_rate_limiting_config", new=lambda: rate_config),
    ):
        yield


class TestRunExportThreadsCommand:
    """Tests for run_export_threads_command()."""

    def test_not_authenticated_human(self, capsys) -> None:
        """Human output shows not authenticated error."""
        tm = FakeTokenManager(load_token_result=(None, None))
        with _export_dependencies(
            tm, FakeCacheManager(), FakeThreadScraper(), RateLimitConfig(enabled=False)
        ):
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

    def test_not_authenticated_json(self, capsys) -> None:
        """JSON output shows error envelope when not authenticated."""
        tm = FakeTokenManager(load_token_result=(None, None))
        with _export_dependencies(
            tm, FakeCacheManager(), FakeThreadScraper(), RateLimitConfig(enabled=False)
        ):
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

    def test_success_human(self, tmp_path, monkeypatch, capsys) -> None:
        """Human output shows export complete."""
        monkeypatch.chdir(tmp_path)
        scraper = FakeThreadScraper(threads=[_THREAD_1])
        with _export_dependencies(
            FakeTokenManager(load_token_result=("token", {})),
            FakeCacheManager(),
            scraper,
            RateLimitConfig(enabled=False),
        ):
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
        assert list(tmp_path.glob("threads-*.csv"))

    def test_success_json(self, tmp_path, monkeypatch, capsys) -> None:
        """JSON output shows success envelope with thread data."""
        monkeypatch.chdir(tmp_path)
        scraper = FakeThreadScraper(threads=[_THREAD_1])
        with _export_dependencies(
            FakeTokenManager(load_token_result=("token", {})),
            FakeCacheManager(),
            scraper,
            RateLimitConfig(enabled=False),
        ):
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
        assert envelope["result"]["output_path"] is None
        assert "ERROR" not in captured.err
        assert not list(tmp_path.glob("threads-*.csv"))


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


class TestScrapeThreads:
    """Tests for _scrape_threads progress callback."""

    def test_progress_callback_echoes(self, capsys):
        """Progress callback is invoked and prints extraction progress."""
        scraper = FakeThreadScraper(
            threads=[ThreadRecord(title="T1", url="https://x.ai", created_at="2025-01-01")]
        )
        result = _scrape_threads(scraper, None, None, output_format="human")
        assert result == [ThreadRecord(title="T1", url="https://x.ai", created_at="2025-01-01")]
        assert scraper.progress_calls == [(1, 1)]
        assert "Extracting 1/1 threads" in capsys.readouterr().out


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
                _handle_known_error(ValueError("fail"), output_format="json", logger=_LOGGER)
            mock_handle.assert_called_once()

    def test_auth_error_shows_reauth_hint(self, capsys):
        """AuthenticationError shows re-authentication hint."""
        with pytest.raises(SystemExit):
            _handle_known_error(
                AuthenticationError("expired"), output_format="human", logger=_LOGGER
            )
        err = capsys.readouterr().err
        assert "re-authenticate" in err


class TestHandleHttpStatusError:
    """Tests for _handle_http_status_error."""

    def test_json_mode_calls_handle_error(self):
        """In JSON mode, handle_error is invoked."""
        error = PerplexityHTTPStatusError(
            "server error",
            response=SimpleResponse(status_code=500, headers={}),
        )
        with patch("perplexity_cli.runners.export.handle_error", autospec=True) as mock_handle:
            with patch("perplexity_cli.runners.export.handle_http_error", autospec=True):
                _handle_http_status_error(error, output_format="json", ctx_obj={}, logger=_LOGGER)
            mock_handle.assert_called_once()

    def test_human_mode_calls_handle_http_error(self):
        """In human mode, handle_http_error is called."""
        error = PerplexityHTTPStatusError("server error")
        with patch("perplexity_cli.runners.export.handle_http_error", autospec=True) as mock_handle:
            _handle_http_status_error(
                error, output_format="human", ctx_obj={"debug": False}, logger=_LOGGER
            )
        mock_handle.assert_called_once()


class TestHandleUnexpectedError:
    """Tests for _handle_unexpected_error."""

    def test_json_mode_calls_handle_error(self):
        """In JSON mode, handle_error is invoked."""
        with patch("perplexity_cli.runners.export.handle_error", autospec=True) as mock_handle:
            with patch("perplexity_cli.runners.export.handle_unexpected_cli_error", autospec=True):
                _handle_unexpected_error(
                    RuntimeError("boom"), output_format="json", ctx_obj={}, logger=_LOGGER
                )
            mock_handle.assert_called_once()

    def test_human_mode_calls_unexpected_handler(self):
        """In human mode, handle_unexpected_cli_error is called."""
        with patch(
            "perplexity_cli.runners.export.handle_unexpected_cli_error", autospec=True
        ) as mock_handle:
            _handle_unexpected_error(
                RuntimeError("boom"), output_format="human", ctx_obj={}, logger=_LOGGER
            )
        mock_handle.assert_called_once()


class TestRunExportErrorHandlers:
    """Tests for run_export_threads_command error handler branches."""

    @staticmethod
    def _auth_dependencies(scraper):
        """Patch dependencies for an authenticated export run."""
        return (
            FakeTokenManager(load_token_result=("token", {})),
            FakeCacheManager(),
            scraper,
            RateLimitConfig(enabled=False),
        )

    def test_keyboard_interrupt(self, capsys):
        """KeyboardInterrupt exits with code 130."""
        scraper = FakeThreadScraper(scrape_error=KeyboardInterrupt())
        with _export_dependencies(*self._auth_dependencies(scraper)):
            with pytest.raises(SystemExit) as exc_info:
                run_export_threads_command({}, None, None, None, False, False)

        assert exc_info.value.code == 130

    def test_known_error_handler(self, capsys):
        """ValueError routes through _handle_known_error."""
        scraper = FakeThreadScraper(scrape_error=ValueError("bad value"))
        with _export_dependencies(*self._auth_dependencies(scraper)):
            with pytest.raises(SystemExit):
                run_export_threads_command({}, None, None, None, False, False)

        assert "bad value" in capsys.readouterr().err

    def test_http_status_error_handler(self):
        """PerplexityHTTPStatusError routes through _handle_http_status_error."""
        error = PerplexityHTTPStatusError(
            "server error",
            request=SimpleRequest(method="POST", url="https://perplexity.ai/t"),
            response=SimpleResponse(status_code=500, headers={}),
        )
        scraper = FakeThreadScraper(scrape_error=error)
        with (
            _export_dependencies(*self._auth_dependencies(scraper)),
            patch(
                "perplexity_cli.runners.export.handle_http_error",
                side_effect=SystemExit(1),
                autospec=True,
            ),
        ):
            with pytest.raises(SystemExit):
                run_export_threads_command({}, None, None, None, False, False)

    def test_unexpected_error_handler(self):
        """Unexpected exceptions route through _handle_unexpected_error."""
        scraper = FakeThreadScraper(scrape_error=RuntimeError("boom"))
        with (
            _export_dependencies(*self._auth_dependencies(scraper)),
            patch(
                "perplexity_cli.runners.export.handle_unexpected_cli_error",
                side_effect=SystemExit(1),
                autospec=True,
            ),
        ):
            with pytest.raises(SystemExit):
                run_export_threads_command({}, None, None, None, False, False)


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

        record = ThreadRecord(title="Obj Title", url="https://obj.ai", created_at="2025-06-01")
        payload = _thread_payload(record)
        assert payload == {
            "title": "Obj Title",
            "created_at": "2025-06-01",
            "url": "https://obj.ai",
        }

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
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from perplexity_cli.runners.export import _echo_date_range; "
                "_echo_date_range('2025-01-01', '2025-12-31')",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        assert result.stderr == "[OK] Filtered by date range: 2025-01-01 to 2025-12-31\n"

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

    def test_echo_date_range_default_prefix_is_exact(self, capsys):
        assert _echo_date_range.__kwdefaults__ == {"prefix": "[OK] Filtered by date range"}
        _echo_date_range("2025-01-01", None)
        assert capsys.readouterr().err == ("[OK] Filtered by date range: 2025-01-01 to end\n")

    @pytest.mark.parametrize(
        ("from_date", "to_date", "expected"),
        (
            (
                "2025-01-01",
                None,
                "[OK] Filtered by date range: 2025-01-01 to end\n",
            ),
            (
                None,
                "2025-12-31",
                "[OK] Filtered by date range: beginning to 2025-12-31\n",
            ),
        ),
    )
    def test_echo_date_range_default_prefix_exact_for_open_bounds(
        self, from_date, to_date, expected
    ):
        with redirect_stderr(StringIO()):
            _echo_date_range(from_date, to_date)
        code = (
            "from perplexity_cli.runners.export import _echo_date_range; "
            f"_echo_date_range({from_date!r}, {to_date!r})"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            check=True,
            capture_output=True,
            text=True,
        )
        assert result.stderr == expected

    def test_handle_no_threads_shows_date_range(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            _handle_no_threads("2025-01-01", "2025-06-30", output_format="human")
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "No threads found matching criteria." in captured.err
        assert "2025-01-01 to 2025-06-30" in captured.err

    def test_handle_known_error_non_auth_no_reauth_hint(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            _handle_known_error(ValueError("oops"), output_format="human", logger=_LOGGER)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "[ERROR] Export failed: oops" in captured.err
        assert "re-authenticate" not in captured.err

    def test_handle_auth_missing_human(self, capsys):
        from perplexity_cli.runners.export import _handle_auth_missing

        with pytest.raises(SystemExit) as exc_info:
            _handle_auth_missing("human", _LOGGER)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "[ERROR] Not authenticated." in captured.err
        assert "pxcli auth login" in captured.err

    def test_success_human_with_date_range(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        scraper = FakeThreadScraper(
            threads=[ThreadRecord(title="T1", url="https://x.ai", created_at="2025-03-01")]
        )
        with _export_dependencies(
            FakeTokenManager(load_token_result=("token", {})),
            FakeCacheManager(),
            scraper,
            RateLimitConfig(enabled=False),
        ):
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

    def test_success_json_with_explicit_output(self, tmp_path, capsys):
        out_path = tmp_path / "out.csv"
        scraper = FakeThreadScraper(
            threads=[ThreadRecord(title="T1", url="https://x.ai", created_at="2025-01-01")]
        )
        with _export_dependencies(
            FakeTokenManager(load_token_result=("token", {})),
            FakeCacheManager(),
            scraper,
            RateLimitConfig(enabled=False),
        ):
            run_export_threads_command(
                ctx_obj={"json": True},
                from_date=None,
                to_date=None,
                output=out_path,
                force_refresh=False,
                clear_cache=False,
            )

        assert out_path.exists()
        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["result"]["output_path"] == str(out_path.resolve())

    def test_validate_export_dates_invalid_shows_format_hint(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            _validate_export_dates("garbage", None, output_format="human")
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Please use YYYY-MM-DD format" in captured.err

    def test_handle_cache_clear_preserve_does_nothing(self, tmp_path, capsys):
        cm = FakeCacheManager(cache_path=tmp_path / "cache.json")
        _handle_cache_clear(cm, clear_cache=False, output_format="human", logger=_LOGGER)
        assert cm.cache_exists_calls == 0
        assert cm.clear_calls == 0
        json_cache = FakeCacheManager(cache_path=tmp_path / "missing-cache.json")
        _handle_cache_action(json_cache, CacheAction.CLEAR, output_format="json", logger=_LOGGER)
        assert capsys.readouterr().out == ""

    def test_resolve_ctx_flags_maps_json_and_schema(self):
        """Export output mode reflects both context flags independently."""
        assert [
            _resolve_ctx_flags(context)
            for context in (
                None,
                {},
                {"json": True},
                {"schema": True},
                {"json": True, "schema": True},
            )
        ] == [
            OutputMode("human", "no_schema"),
            OutputMode("human", "no_schema"),
            OutputMode("json", "no_schema"),
            OutputMode("human", "with_schema"),
            OutputMode("json", "with_schema"),
        ]

    def test_output_json_serialises_threads_and_date_range(self, monkeypatch):
        """JSON output contains the complete thread and date-range payload."""
        result = ExportResult(
            threads=[_THREAD_1],
            output_path=Path("exports/threads.csv"),
            date_range=ExportDateRange(from_date="2025-01-01", to_date="2025-12-31"),
        )
        captured: list[dict[str, object]] = []
        monkeypatch.setattr(
            "perplexity_cli.runners.export.write_envelope",
            lambda envelope, include_schema: captured.append(envelope),
        )

        _output_json(result, include_schema="with_schema")

        assert captured[0].model_dump() == {
            "ok": True,
            "command": "pxcli threads export",
            "result": {
                "total": 1,
                "threads": [
                    {
                        "title": "Thread 1",
                        "created_at": "2025-01-01",
                        "url": "https://perplexity.ai/t/1",
                    }
                ],
                "output_path": str(Path("exports/threads.csv").resolve()),
                "date_range": {"from": "2025-01-01", "to": "2025-12-31"},
            },
            "meta": None,
            "next_actions": [],
        }

    def test_output_export_results_json_without_path_skips_csv(self, monkeypatch):
        """JSON-only mode emits JSON without invoking the CSV writer."""
        result = ExportResult(
            threads=[_THREAD_1],
            output_path=None,
            date_range=ExportDateRange(from_date=None, to_date=None),
        )
        output_json = Mock()
        write_csv = Mock()
        monkeypatch.setattr("perplexity_cli.runners.export._output_json", output_json)
        monkeypatch.setattr("perplexity_cli.runners.export.write_threads_csv", write_csv)

        _output_export_results(result, OutputMode("json", "no_schema"), _LOGGER)

        output_json.assert_called_once_with(result, "no_schema")
        write_csv.assert_not_called()

    def test_output_export_results_json_with_path_writes_csv_then_json(self, tmp_path, monkeypatch):
        """JSON mode with an explicit path writes CSV and reports its resolved path."""
        requested_path = tmp_path / "threads.csv"
        written_path = tmp_path / "written.csv"
        result = ExportResult(
            threads=[_THREAD_1],
            output_path=requested_path,
            date_range=ExportDateRange(from_date=None, to_date=None),
        )
        output_json = Mock()
        write_csv = Mock(return_value=written_path)
        monkeypatch.setattr("perplexity_cli.runners.export._output_json", output_json)
        monkeypatch.setattr("perplexity_cli.runners.export.write_threads_csv", write_csv)

        _output_export_results(result, OutputMode("json", "with_schema"), _LOGGER)

        write_csv.assert_called_once_with(result.threads, requested_path)
        output_json.assert_called_once()
        written_result = output_json.call_args.args[0]
        assert written_result.output_path == written_path
        assert output_json.call_args.args[1] == "with_schema"

    def test_http_status_error_passes_debug_mode_to_handler(self):
        """HTTP error handling preserves the debug flag and context label."""
        error = PerplexityHTTPStatusError("server error")
        with patch("perplexity_cli.runners.export.handle_http_error") as handle:
            _handle_http_status_error(error, "human", {"debug": True}, _LOGGER)

        handle.assert_called_once_with(
            error,
            _LOGGER,
            debug_mode="debug",
            context="during thread export",
        )

    def test_unexpected_error_passes_normal_mode_to_handler(self):
        """Unexpected error handling defaults to normal mode without debug."""
        error = RuntimeError("boom")
        with patch("perplexity_cli.runners.export.handle_unexpected_cli_error") as handle:
            _handle_unexpected_error(error, "human", None, _LOGGER)

        handle.assert_called_once()
        assert handle.call_args.args == (error, _LOGGER)
        assert handle.call_args.kwargs["debug_mode"] == "normal"
        assert handle.call_args.kwargs["message_tuple"][2] is False

    def test_emit_json_error_preserves_original_exception(self):
        """JSON export errors pass the original exception to the envelope handler."""
        error = ValueError("invalid export")
        with patch(
            "perplexity_cli.runners.export.handle_error", side_effect=SystemExit(1)
        ) as handle:
            with pytest.raises(SystemExit):
                _emit_json_error(error, "json")

        handle.assert_called_once_with(error, "pxcli threads export", output_format="json")

    def test_output_json_forwards_schema_inclusion(self):
        """Export JSON forwards the requested schema inclusion unchanged."""
        result = ExportResult(
            threads=[_THREAD_1],
            output_path=None,
            date_range=ExportDateRange(from_date=None, to_date=None),
        )
        with patch("perplexity_cli.runners.export.write_envelope") as write:
            _output_json(result, include_schema="with_schema")

        write.assert_called_once()
        assert write.call_args.kwargs["include_schema"] == "with_schema"

    def test_export_preparation_validates_to_date(self):
        """The command passes the upper date bound into preparation validation."""
        scraper = FakeThreadScraper(threads=[_THREAD_1])
        with (
            _export_dependencies(
                FakeTokenManager(load_token_result=("token", {})),
                FakeCacheManager(),
                scraper,
                RateLimitConfig(enabled=False),
            ),
            patch("perplexity_cli.runners.export._validate_export_dates") as validate,
            patch("perplexity_cli.runners.export._output_export_results"),
        ):
            run_export_threads_command({}, None, "2025-12-31", None, False, False)

        validate.assert_called_once_with(None, "2025-12-31", "human")

    def test_export_json_known_error_preserves_output_mode(self):
        """Known scrape failures retain JSON mode through top-level routing."""
        error = ValueError("bad thread data")
        scraper = FakeThreadScraper(scrape_error=error)
        with (
            _export_dependencies(
                FakeTokenManager(load_token_result=("token", {})),
                FakeCacheManager(),
                scraper,
                RateLimitConfig(enabled=False),
            ),
            patch(
                "perplexity_cli.runners.export._handle_known_error",
                side_effect=SystemExit(1),
            ) as handle,
            pytest.raises(SystemExit),
        ):
            run_export_threads_command({"json": True}, None, None, None, False, False)

        assert handle.call_args.args[:2] == (error, "json")


class TestExportPublicBoundaryCoverage:
    """Cover export request, output, and error distinctions at the public boundary."""

    @staticmethod
    def _run(scraper, cache=None, config=None):
        return _export_dependencies(
            FakeTokenManager(load_token_result=("token", {})),
            cache or FakeCacheManager(),
            scraper,
            config or RateLimitConfig(enabled=False),
        )

    def test_request_validation_is_exact(self):
        with pytest.raises(TypeError) as positional:
            run_export_threads_command({}, None, None, None, False)
        assert str(positional.value) == (
            "run_export_threads_command expected output, force_refresh, and clear_cache"
        )
        with pytest.raises(TypeError) as keyword:
            run_export_threads_command(
                {}, None, None, output=None, force_refresh=False, wrong=False
            )
        assert (
            str(keyword.value)
            == "run_export_threads_command requires output, force_refresh, clear_cache"
        )
        with pytest.raises(TypeError) as output:
            run_export_threads_command({}, None, None, "out.csv", False, False)
        assert str(output.value) == "output must be a Path or None"

    def test_json_payload_uses_empty_string_defaults_at_boundary(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)

        class Defaults(dict):
            def __init__(self):
                super().__init__()
                self.defaults = []

            def get(self, key, default=None):
                self.defaults.append((key, default))
                return default

        record = Defaults()
        with self._run(FakeThreadScraper(threads=[record])):
            run_export_threads_command({"json": True}, None, None, None, False, False)
        payload = json.loads(capsys.readouterr().out)["result"]["threads"][0]
        assert payload == {"title": "", "created_at": "", "url": ""}
        assert record.defaults == [("title", ""), ("created_at", ""), ("url", "")]

    @pytest.mark.parametrize("bad", ("not-a-date", "2025-99-99"))
    def test_invalid_date_is_structured_and_stops_scrape(self, bad, capsys):
        scraper = FakeThreadScraper(threads=[_THREAD_1])
        with self._run(scraper), pytest.raises(SystemExit):
            run_export_threads_command({"json": True}, bad, None, None, False, False)
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["ok"] is False
        assert envelope["error"]["message"] in {
            "Unknown string format: not-a-date",
            "month must be in 1..12: 2025-99-99",
            "month must be in 1..12, not 99: 2025-99-99",
        }
        assert scraper.scrape_calls == []

    def test_human_output_and_logs_are_exact(self, tmp_path, monkeypatch, capsys, caplog):
        monkeypatch.chdir(tmp_path)
        with self._run(FakeThreadScraper(threads=[_THREAD_1])), caplog.at_level(logging.INFO):
            run_export_threads_command({}, None, None, None, False, False)
        output = capsys.readouterr().out
        assert "Exporting threads from Perplexity.ai library...\n" in output
        assert "\n[OK] Export complete\n[OK] Exported 1 threads\n" in output
        assert "Exported 1 threads to " in caplog.text
        assert "Starting thread export" in caplog.text

    def test_progress_callback_uses_non_newline_human_output(self, monkeypatch):
        scraper = FakeThreadScraper(threads=[_THREAD_1])
        echoes = []
        monkeypatch.setattr(
            "perplexity_cli.runners.export.click.echo", lambda *a, **kw: echoes.append((a, kw))
        )
        with self._run(scraper):
            run_export_threads_command({}, None, None, None, False, False)
        progress = next(args for args, kwargs in echoes if args and "Extracting" in args[0])
        assert next(kwargs for args, kwargs in echoes if args == progress)["nl"] is False

    @pytest.mark.parametrize("error", (AuthenticationError("expired"), ValueError("sentinel")))
    def test_known_errors_preserve_exact_public_diagnostics(self, error, capsys, caplog):
        with (
            self._run(FakeThreadScraper(scrape_error=error)),
            caplog.at_level(logging.ERROR),
            pytest.raises(SystemExit),
        ):
            run_export_threads_command({}, None, None, None, False, False)
        text = capsys.readouterr().err
        assert f"[ERROR] Export failed: {error}" in text
        assert "Export failed: " + str(error) in caplog.text
        if isinstance(error, AuthenticationError):
            assert (
                "Your token may have expired. Please re-authenticate:\n  perplexity-cli auth\n"
                in text
            )

    @pytest.mark.parametrize(
        "error,handler",
        (
            (PerplexityHTTPStatusError("http"), "handle_http_error"),
            (RuntimeError("unexpected"), "handle_unexpected_cli_error"),
        ),
    )
    def test_public_error_handlers_receive_mode_context_and_logger(self, error, handler):
        with (
            self._run(FakeThreadScraper(scrape_error=error)),
            patch(f"perplexity_cli.runners.export.{handler}", side_effect=SystemExit(1)) as mock,
            pytest.raises(SystemExit),
        ):
            run_export_threads_command({}, None, None, None, False, False)
        assert mock.call_args.args[0] is error
        assert mock.call_args.args[1] is not None
        assert mock.call_args.kwargs.get("debug_mode") == "normal"

    def test_interrupt_keeps_exit_code_and_exact_log(self, capsys, caplog):
        with (
            self._run(FakeThreadScraper(scrape_error=KeyboardInterrupt())),
            caplog.at_level(logging.INFO),
        ):
            with pytest.raises(SystemExit) as exc_info:
                run_export_threads_command({}, None, None, None, False, False)
        assert exc_info.value.code == 130
        assert capsys.readouterr().err == "\n[ERROR] Export interrupted.\n"
        assert "Export interrupted by user" in caplog.text

    @pytest.mark.parametrize(
        ("from_date", "to_date", "message"),
        (
            (123, None, "from_date must be a string or None"),
            (None, 123, "to_date must be a string or None"),
        ),
    )
    def test_public_request_names_invalid_dates(self, from_date, to_date, message):
        with pytest.raises(TypeError, match=message):
            run_export_threads_command({}, from_date, to_date, None, False, False)

    def test_public_human_date_output_is_exact(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        with self._run(FakeThreadScraper(threads=[_THREAD_1])):
            run_export_threads_command({}, "2025-01-01", "2025-12-31", None, False, False)
        assert "[OK] Filtered by date range: 2025-01-01 to 2025-12-31\n" in capsys.readouterr().err

    def test_public_scraper_constructor_receives_prepared_dependencies(self):
        scraper = FakeThreadScraper(threads=[_THREAD_1])
        received = {}

        def construct(**kwargs):
            received.update(kwargs)
            return scraper

        with (
            self._run(scraper),
            patch("perplexity_cli.runners.export.ThreadScraper", new=construct),
        ):
            run_export_threads_command({}, None, None, None, True, False)
        assert received == {
            "token": "token",
            "cookies": {},
            "rate_limiter": None,
            "cache_manager": received["cache_manager"],
            "force_refresh": True,
        }

    @pytest.mark.parametrize(
        "ctx,expected", (({}, "[ERROR] Not authenticated.\n"), ({"json": True}, None))
    )
    def test_public_missing_authentication_has_mode_specific_boundary(
        self, ctx, expected, capsys, caplog
    ):
        with self._run(FakeThreadScraper()), pytest.raises(SystemExit):
            with patch(
                "perplexity_cli.runners.export._create_token_manager",
                new=lambda: FakeTokenManager(load_token_result=(None, None)),
            ):
                run_export_threads_command(ctx, None, None, None, False, False)
        if expected is not None:
            assert expected in capsys.readouterr().err
        else:
            assert json.loads(capsys.readouterr().out)["error"]["message"] == "Not authenticated"

    @pytest.mark.parametrize("ctx", ({}, {"json": True}))
    def test_public_empty_result_has_mode_specific_boundary(self, ctx, capsys):
        with self._run(FakeThreadScraper()), pytest.raises(SystemExit):
            run_export_threads_command(ctx, None, None, None, False, False)
        output = capsys.readouterr()
        if ctx.get("json"):
            assert (
                json.loads(output.out)["error"]["message"] == "No threads found matching criteria"
            )
        else:
            assert output.err.startswith("\n[ERROR] No threads found matching criteria.\n")

    def test_public_explicit_json_output_writes_and_reports_csv(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        output = tmp_path / "export.csv"
        with self._run(FakeThreadScraper(threads=[_THREAD_1])):
            run_export_threads_command({"json": True}, None, None, output, False, False)
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["result"]["output_path"] == str(output.resolve())
        assert output.exists()

    def test_public_cache_clear_distinguishes_missing_and_present(self, tmp_path, capsys, caplog):
        cache = FakeCacheManager(cache_path=tmp_path / "cache.json")
        with (
            self._run(FakeThreadScraper(threads=[_THREAD_1]), cache),
            caplog.at_level(logging.INFO),
        ):
            run_export_threads_command({}, None, None, None, False, True)
        assert "[INFO] No cache file to clear\n" in capsys.readouterr().out
        assert "Cache cleared by user" not in caplog.text
        cache.cache_path.write_text("{}")
        with (
            self._run(FakeThreadScraper(threads=[_THREAD_1]), cache),
            caplog.at_level(logging.INFO),
        ):
            run_export_threads_command({}, None, None, None, False, True)
        assert "[OK] Cache cleared\n" in capsys.readouterr().out
        assert "Cache cleared by user" in caplog.text

    def test_public_enabled_rate_limiter_is_constructed_and_logged(self, caplog):
        config = RateLimitConfig(enabled=True, requests_per_period=2, period_seconds=10)
        with (
            self._run(FakeThreadScraper(threads=[_THREAD_1]), config=config),
            caplog.at_level(logging.INFO),
        ):
            run_export_threads_command({}, None, None, None, False, False)
        assert "Rate limiting enabled: 2 requests per 10.0 seconds" in caplog.text

    @pytest.mark.parametrize(
        ("error", "handler"),
        (
            (RuntimeError("unexpected"), "handle_unexpected_cli_error"),
            (PerplexityHTTPStatusError("http"), "handle_http_error"),
        ),
    )
    def test_public_json_errors_preserve_exception_and_debug_mode(self, error, handler):
        with (
            self._run(FakeThreadScraper(scrape_error=error)),
            patch("perplexity_cli.runners.export.handle_error") as json_error,
            patch(f"perplexity_cli.runners.export.{handler}", side_effect=SystemExit(1)) as mock,
            pytest.raises(SystemExit),
        ):
            run_export_threads_command(
                {"json": True, "debug": True}, None, None, None, False, False
            )
        json_error.assert_called_once_with(error, "pxcli threads export", output_format="json")
        assert mock.call_args.args[0] is error
        assert mock.call_args.kwargs["debug_mode"] == "debug"

    @pytest.mark.parametrize("ctx", ({"schema": "yes"}, {"debug": "yes"}))
    def test_public_context_rejects_non_bool_flags(self, ctx):
        with pytest.raises(TypeError, match="must be a bool"):
            run_export_threads_command(ctx, None, None, None, False, False)

    @pytest.mark.parametrize("args", ((None, "yes", False), (None, False, "no")))
    def test_public_request_rejects_non_bool_tail_values(self, args):
        with pytest.raises(TypeError, match="must be a bool"):
            run_export_threads_command({}, None, None, *args)

    def test_public_json_only_log_is_exact(self, caplog):
        with self._run(FakeThreadScraper(threads=[_THREAD_1])), caplog.at_level(logging.INFO):
            run_export_threads_command({"json": True}, None, None, None, False, False)
        assert "Exported 1 threads (JSON only, no CSV written)" in caplog.text

    def test_public_human_output_includes_resolved_path(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        with self._run(FakeThreadScraper(threads=[_THREAD_1])):
            run_export_threads_command({}, None, None, None, False, False)
        assert (
            f"[OK] Saved to: {next(tmp_path.glob('threads-*.csv')).resolve()}"
            in capsys.readouterr().out
        )

    def test_public_json_progress_is_silent(self, capsys):
        with self._run(FakeThreadScraper(threads=[_THREAD_1])):
            run_export_threads_command({"json": True}, None, None, None, False, False)
        assert "Extracting" not in capsys.readouterr().out

    def test_public_enabled_rate_limiter_reaches_scraper(self):
        config = RateLimitConfig(enabled=True, requests_per_period=2, period_seconds=10)
        received = {}

        def construct(**kwargs):
            received.update(kwargs)
            return FakeThreadScraper(threads=[_THREAD_1])

        with (
            self._run(FakeThreadScraper(), config=config),
            patch("perplexity_cli.runners.export.ThreadScraper", new=construct),
        ):
            run_export_threads_command({}, None, None, None, False, False)
        assert received["rate_limiter"] is not None

    def test_public_context_preserves_schema_flag(self):
        captured = {}

        def output(result, mode, logger):
            captured["mode"] = mode

        with (
            self._run(FakeThreadScraper(threads=[_THREAD_1])),
            patch("perplexity_cli.runners.export._output_export_results", new=output),
        ):
            run_export_threads_command(
                {"json": True, "schema": True}, None, None, None, False, False
            )
        assert captured["mode"] == OutputMode("json", "with_schema")

    @pytest.mark.parametrize(
        ("args", "message"),
        (
            ((None, "yes", False), "force_refresh must be a bool"),
            ((None, False, "no"), "clear_cache must be a bool"),
        ),
    )
    def test_public_request_validation_names_tail_fields(self, args, message):
        with pytest.raises(TypeError) as error:
            run_export_threads_command({}, None, None, *args)
        assert str(error.value) == message

    def test_public_invalid_date_hint_is_exact(self, capsys):
        with self._run(FakeThreadScraper()), pytest.raises(SystemExit):
            run_export_threads_command({}, "bad", None, None, False, False)
        assert "Please use YYYY-MM-DD format (e.g., 2025-12-23)\n" in capsys.readouterr().err

    def test_public_rate_limit_log_is_exact(self, caplog):
        config = RateLimitConfig(enabled=True, requests_per_period=2, period_seconds=10)
        with (
            self._run(FakeThreadScraper(threads=[_THREAD_1]), config=config),
            caplog.at_level(logging.INFO),
        ):
            run_export_threads_command({}, None, None, None, False, False)
        assert "Rate limiting enabled: 2 requests per 10.0 seconds" in [
            record.message for record in caplog.records
        ]

    def test_public_cache_clear_log_is_exact(self, tmp_path, capsys, caplog):
        cache = FakeCacheManager(cache_path=tmp_path / "cache.json")
        cache.cache_path.write_text("{}")
        with (
            self._run(FakeThreadScraper(threads=[_THREAD_1]), cache),
            caplog.at_level(logging.INFO),
        ):
            run_export_threads_command({}, None, None, None, False, True)
        assert "Cache cleared by user" in [record.message for record in caplog.records]

    def test_public_empty_result_preserves_both_date_bounds(self, capsys):
        with self._run(FakeThreadScraper()), pytest.raises(SystemExit):
            run_export_threads_command({}, "2025-01-01", "2025-12-31", None, False, False)
        assert capsys.readouterr().err == (
            "\n[ERROR] No threads found matching criteria.\nDate range: 2025-01-01 to 2025-12-31\n"
        )

    def test_public_default_date_output_is_exact(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        with self._run(FakeThreadScraper(threads=[_THREAD_1])):
            run_export_threads_command({}, "2025-01-01", None, None, False, False)
        assert "[OK] Filtered by date range: 2025-01-01 to end\n" in capsys.readouterr().err

    def test_public_json_output_log_message_is_exact(self, caplog):
        with self._run(FakeThreadScraper(threads=[_THREAD_1])), caplog.at_level(logging.INFO):
            run_export_threads_command({"json": True}, None, None, None, False, False)
        assert "Exported 1 threads (JSON only, no CSV written)" in [
            record.message for record in caplog.records
        ]

    def test_public_explicit_output_log_contains_written_path(self, tmp_path, caplog):
        output = tmp_path / "export.csv"
        with self._run(FakeThreadScraper(threads=[_THREAD_1])), caplog.at_level(logging.INFO):
            run_export_threads_command({}, None, None, output, False, False)
        assert f"Exported 1 threads to {output}" in [record.message for record in caplog.records]

    def test_public_known_json_error_preserves_exception_and_log(self, caplog):
        error = ValueError("bad thread data")
        with (
            self._run(FakeThreadScraper(scrape_error=error)),
            patch("perplexity_cli.runners.export.handle_error") as json_error,
            caplog.at_level(logging.ERROR),
            pytest.raises(SystemExit),
        ):
            run_export_threads_command({"json": True}, None, None, None, False, False)
        json_error.assert_called_once_with(error, "pxcli threads export", output_format="json")
        assert "Export failed: bad thread data" in [record.message for record in caplog.records]

    @pytest.mark.parametrize("handler", ("handle_http_error", "handle_unexpected_cli_error"))
    def test_public_json_error_false_debug_is_normal(self, handler):
        error = (
            PerplexityHTTPStatusError("http")
            if handler == "handle_http_error"
            else RuntimeError("unexpected")
        )
        with (
            self._run(FakeThreadScraper(scrape_error=error)),
            patch("perplexity_cli.runners.export.handle_error"),
            patch(f"perplexity_cli.runners.export.{handler}", side_effect=SystemExit(1)) as mock,
            pytest.raises(SystemExit),
        ):
            run_export_threads_command(
                {"json": True, "debug": False}, None, None, None, False, False
            )
        assert mock.call_args.kwargs["debug_mode"] == "normal"

    def test_public_missing_authentication_diagnostics_and_warning_are_exact(self, capsys, caplog):
        with self._run(FakeThreadScraper()), pytest.raises(SystemExit):
            with patch(
                "perplexity_cli.runners.export._create_token_manager",
                new=lambda: FakeTokenManager(load_token_result=(None, None)),
            ):
                with caplog.at_level(logging.WARNING):
                    run_export_threads_command({}, None, None, None, False, False)
        assert "Please authenticate first with: pxcli auth login\n" in capsys.readouterr().err
        assert "Export attempted without authentication" in [
            record.message for record in caplog.records
        ]

    def test_public_auth_guard_preserves_unreachable_assertion(self):
        with (
            self._run(FakeThreadScraper()),
            patch(
                "perplexity_cli.runners.export._create_token_manager",
                new=lambda: FakeTokenManager(load_token_result=(None, None)),
            ),
            patch("perplexity_cli.runners.export._handle_auth_missing"),
            pytest.raises(AssertionError, match="unreachable after auth-missing handler exits"),
        ):
            run_export_threads_command({}, None, None, None, False, False)

    def test_public_interrupt_log_is_exact(self, caplog):
        with (
            self._run(FakeThreadScraper(scrape_error=KeyboardInterrupt())),
            caplog.at_level(logging.INFO),
        ):
            with pytest.raises(SystemExit):
                run_export_threads_command({}, None, None, None, False, False)
        assert "Export interrupted by user" in [record.message for record in caplog.records]

    def test_public_json_progress_has_no_leading_newline(self, capsys):
        with self._run(FakeThreadScraper(threads=[_THREAD_1])):
            run_export_threads_command({"json": True}, None, None, None, False, False)
        assert not capsys.readouterr().out.startswith("\n")

    def test_public_default_date_prefix_is_exact(self, capsys):
        from perplexity_cli.runners.export import _echo_date_range

        _echo_date_range("2025-01-01", None)
        assert capsys.readouterr().err == "[OK] Filtered by date range: 2025-01-01 to end\n"

    @pytest.mark.parametrize("handler", ("handle_http_error", "handle_unexpected_cli_error"))
    def test_public_json_errors_without_debug_use_normal_mode(self, handler):
        error = (
            PerplexityHTTPStatusError("http")
            if handler == "handle_http_error"
            else RuntimeError("unexpected")
        )
        with (
            self._run(FakeThreadScraper(scrape_error=error)),
            patch("perplexity_cli.runners.export.handle_error"),
            patch(f"perplexity_cli.runners.export.{handler}", side_effect=SystemExit(1)) as mock,
            pytest.raises(SystemExit),
        ):
            run_export_threads_command({"json": True}, None, None, None, False, False)
        assert mock.call_args.kwargs["debug_mode"] == "normal"

    def test_public_preparation_start_log_is_exact(self, caplog):
        with self._run(FakeThreadScraper(threads=[_THREAD_1])), caplog.at_level(logging.INFO):
            run_export_threads_command({}, None, None, None, False, False)
        assert "Starting thread export" in [record.message for record in caplog.records]

    def test_public_json_cache_clear_keeps_json_output(self, tmp_path, capsys):
        cache = FakeCacheManager(cache_path=tmp_path / "cache.json")
        cache.cache_path.write_text("{}")
        with self._run(FakeThreadScraper(threads=[_THREAD_1]), cache):
            run_export_threads_command({"json": True}, None, None, None, False, True)
        assert json.loads(capsys.readouterr().out)["ok"] is True

    def test_public_auth_guard_assertion_message_is_exact(self):
        with (
            self._run(FakeThreadScraper()),
            patch(
                "perplexity_cli.runners.export._create_token_manager",
                new=lambda: FakeTokenManager(load_token_result=(None, None)),
            ),
            patch("perplexity_cli.runners.export._handle_auth_missing"),
        ):
            with pytest.raises(AssertionError) as error:
                run_export_threads_command({}, None, None, None, False, False)
        assert str(error.value) == "unreachable after auth-missing handler exits"

    def test_public_thread_serialisation_uses_runtime_cast_contract(self, monkeypatch, capsys):
        import perplexity_cli.runners.export as export_runner

        original_cast = export_runner.cast
        annotations = []

        def checked_cast(annotation, value):
            annotations.append(annotation)
            return original_cast(annotation, value)

        monkeypatch.setattr(export_runner, "cast", checked_cast)
        with self._run(FakeThreadScraper(threads=[_THREAD_1])):
            run_export_threads_command({"json": True}, None, None, None, False, False)
        assert annotations and all(annotation is not None for annotation in annotations)

    @pytest.mark.parametrize("handler", ("handle_http_error", "handle_unexpected_cli_error"))
    def test_public_error_handlers_request_false_debug_default(self, handler):
        error = (
            PerplexityHTTPStatusError("http")
            if handler == "handle_http_error"
            else RuntimeError("unexpected")
        )
        defaults = []

        class Context(dict):
            def get(self, key, default=None):
                if key == "debug":
                    defaults.append(default)
                return super().get(key, default)

        with (
            self._run(FakeThreadScraper(scrape_error=error)),
            patch(
                "perplexity_cli.runners.export._normalise_context",
                return_value=Context(json=True),
            ),
            patch("perplexity_cli.runners.export.handle_error"),
            patch(f"perplexity_cli.runners.export.{handler}", side_effect=SystemExit(1)),
            pytest.raises(SystemExit),
        ):
            run_export_threads_command({"json": True}, None, None, None, False, False)
        assert defaults == [False]

    def test_public_default_date_prefix_survives_full_pipeline(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        with self._run(FakeThreadScraper(threads=[_THREAD_1])):
            run_export_threads_command({}, "2025-01-01", None, None, False, False)
        assert capsys.readouterr().err.endswith("[OK] Filtered by date range: 2025-01-01 to end\n")

    def test_public_date_range_helper_declares_canonical_default(self):
        assert signature(_echo_date_range).parameters["prefix"].default == (
            "[OK] Filtered by date range"
        )

    @pytest.mark.parametrize("handler", ("handle_http_error", "handle_unexpected_cli_error"))
    def test_public_empty_context_uses_normal_error_mode(self, handler):
        error = (
            PerplexityHTTPStatusError("http")
            if handler == "handle_http_error"
            else RuntimeError("unexpected")
        )
        with (
            self._run(FakeThreadScraper(scrape_error=error)),
            patch("perplexity_cli.runners.export._normalise_context", return_value=None),
            patch("perplexity_cli.runners.export.handle_error"),
            patch(f"perplexity_cli.runners.export.{handler}", side_effect=SystemExit(1)) as mock,
            pytest.raises(SystemExit),
        ):
            run_export_threads_command({"json": True}, None, None, None, False, False)
        assert mock.call_args.kwargs["debug_mode"] == "normal"

    def test_public_unexpected_error_message_tuple_is_exact(self):
        error = RuntimeError("unexpected")
        with (
            self._run(FakeThreadScraper(scrape_error=error)),
            patch(
                "perplexity_cli.runners.export.handle_unexpected_cli_error",
                side_effect=SystemExit(1),
            ) as mock,
            pytest.raises(SystemExit),
        ):
            run_export_threads_command({}, None, None, None, False, False)
        assert mock.call_args.kwargs["message_tuple"] == (
            "\n[ERROR] Unexpected error: unexpected",
            "Unexpected error during export",
            False,
        )
