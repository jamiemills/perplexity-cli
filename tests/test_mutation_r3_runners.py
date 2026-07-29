"""Round 3 mutation-killing tests for runner modules.

Targets survivors missed by rounds 1-2: exact character-level output,
boundary arithmetic, dict structure, log message formats, and branch
coverage for rarely-exercised paths.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

# ---------------------------------------------------------------------------
# export.py — deep branch coverage
# ---------------------------------------------------------------------------


class TestExportR3:
    """Round 3 mutation killers for runners/export.py."""

    def test_emit_json_error_suppressed_in_human_mode(self) -> None:
        from perplexity_cli.runners.export import _emit_json_error

        with patch("perplexity_cli.runners.export.handle_error") as mock_handle:
            _emit_json_error(ValueError("x"), "human")
        mock_handle.assert_not_called()

    def test_emit_json_error_fires_in_json_mode(self) -> None:
        from perplexity_cli.runners.export import _emit_json_error

        with patch("perplexity_cli.runners.export.handle_error") as mock_handle:
            _emit_json_error(ValueError("x"), "json")
        mock_handle.assert_called_once()

    def test_is_dict_str_obj_true_for_dict(self) -> None:
        from perplexity_cli.runners.export import _is_dict_str_obj

        assert _is_dict_str_obj({"a": 1}) is True

    def test_is_dict_str_obj_false_for_list(self) -> None:
        from perplexity_cli.runners.export import _is_dict_str_obj

        assert _is_dict_str_obj([1, 2]) is False

    def test_is_dict_str_obj_false_for_string(self) -> None:
        from perplexity_cli.runners.export import _is_dict_str_obj

        assert _is_dict_str_obj("hello") is False

    def test_normalise_context_partial_json_only(self) -> None:
        from perplexity_cli.runners.export import _normalise_context

        result = _normalise_context({"json": True})
        assert result == {"json": True, "schema": False, "debug": False}

    def test_normalise_context_partial_schema_only(self) -> None:
        from perplexity_cli.runners.export import _normalise_context

        result = _normalise_context({"schema": True})
        assert result == {"json": False, "schema": True, "debug": False}

    def test_normalise_context_rejects_int_for_debug(self) -> None:
        from perplexity_cli.runners.export import _normalise_context

        with pytest.raises(TypeError, match="ctx_obj\\['debug'\\] must be a bool"):
            _normalise_context({"debug": 1})

    def test_try_parse_dates_valid_both(self) -> None:
        from perplexity_cli.runners.export import _try_parse_dates

        _try_parse_dates("2025-01-15", "2025-06-30")

    def test_try_parse_dates_skips_none(self) -> None:
        from perplexity_cli.runners.export import _try_parse_dates

        _try_parse_dates(None, None)

    def test_try_parse_dates_invalid_raises_value_error(self) -> None:
        from perplexity_cli.runners.export import _try_parse_dates

        with pytest.raises(ValueError):
            _try_parse_dates("not-a-date", None)

    def test_handle_cache_action_preserve_noop(self) -> None:
        from perplexity_cli.runners.export import CacheAction, _handle_cache_action

        cm = Mock()
        _handle_cache_action(cm, CacheAction.PRESERVE, "human", Mock())
        cm.cache_exists.assert_not_called()
        cm.clear_cache.assert_not_called()

    def test_handle_cache_action_clear_json_silent(self, capsys) -> None:
        from perplexity_cli.runners.export import CacheAction, _handle_cache_action

        cm = Mock()
        cm.cache_exists.return_value = True
        logger = Mock()
        _handle_cache_action(cm, CacheAction.CLEAR, "json", logger)
        cm.clear_cache.assert_called_once()
        logger.info.assert_called_once_with("Cache cleared by user")
        assert capsys.readouterr().out == ""

    def test_handle_cache_action_clear_no_cache_human(self, capsys) -> None:
        from perplexity_cli.runners.export import CacheAction, _handle_cache_action

        cm = Mock()
        cm.cache_exists.return_value = False
        _handle_cache_action(cm, CacheAction.CLEAR, "human", Mock())
        assert "[INFO] No cache file to clear" in capsys.readouterr().out

    def test_scrape_threads_json_mode_no_progress(self, capsys) -> None:
        from perplexity_cli.runners.export import _scrape_threads

        def fake_run(coro):
            coro.close()
            return [{"title": "T"}]

        with patch("perplexity_cli.runners.export.run_async", side_effect=fake_run):
            result = _scrape_threads(Mock(), None, None, "json")
        assert result == [{"title": "T"}]
        assert capsys.readouterr().out == ""

    def test_scrape_threads_human_prints_newline_after(self, capsys) -> None:
        from perplexity_cli.runners.export import _scrape_threads

        def fake_run(coro):
            coro.close()
            return []

        with patch("perplexity_cli.runners.export.run_async", side_effect=fake_run):
            _scrape_threads(Mock(), None, None, "human")
        assert capsys.readouterr().out == "\n"

    def test_output_json_with_resolved_path(self, capsys, tmp_path) -> None:
        from perplexity_cli.runners.export import ExportDateRange, ExportResult, _output_json

        csv_file = tmp_path / "out.csv"
        csv_file.write_text("data")
        result = ExportResult(
            threads=[{"title": "A", "created_at": "2025-01-01", "url": "https://x.ai"}],
            output_path=csv_file,
            date_range=ExportDateRange(from_date=None, to_date=None),
        )
        _output_json(result, "no_schema")
        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["result"]["output_path"] == str(csv_file.resolve())
        assert envelope["result"]["date_range"] == {"from": None, "to": None}

    def test_output_export_results_json_only_no_csv(self, capsys) -> None:
        from perplexity_cli.runners.export import (
            ExportDateRange,
            ExportResult,
            OutputMode,
            _output_export_results,
        )

        result = ExportResult(
            threads=[{"title": "T", "created_at": "C", "url": "U"}],
            output_path=None,
            date_range=ExportDateRange(from_date=None, to_date=None),
        )
        mode = OutputMode(json_mode="json", include_schema="no_schema")
        logger = Mock()
        with patch("perplexity_cli.runners.export.write_threads_csv") as mock_csv:
            _output_export_results(result, mode, logger)
        mock_csv.assert_not_called()
        logger.info.assert_called_once_with("Exported %s threads (JSON only, no CSV written)", 1)
        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["result"]["output_path"] is None

    def test_output_export_results_json_with_explicit_output(self, capsys) -> None:
        from perplexity_cli.runners.export import (
            ExportDateRange,
            ExportResult,
            OutputMode,
            _output_export_results,
        )

        result = ExportResult(
            threads=[{"title": "T", "created_at": "C", "url": "U"}],
            output_path=Path("/tmp/out.csv"),
            date_range=ExportDateRange(from_date="2025-01-01", to_date=None),
        )
        mode = OutputMode(json_mode="json", include_schema="no_schema")
        with patch(
            "perplexity_cli.runners.export.write_threads_csv", return_value=Path("/tmp/out.csv")
        ) as mock_csv:
            _output_export_results(result, mode, Mock())
        mock_csv.assert_called_once()
        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is True

    def test_output_export_results_human_exact_saved_to(self, capsys) -> None:
        from perplexity_cli.runners.export import (
            ExportDateRange,
            ExportResult,
            OutputMode,
            _output_export_results,
        )

        result = ExportResult(
            threads=[{"title": "A", "created_at": "B", "url": "C"}] * 3,
            output_path=None,
            date_range=ExportDateRange(from_date="2025-01-01", to_date="2025-12-31"),
        )
        mode = OutputMode(json_mode="human", include_schema="no_schema")
        csv_path = Path("/tmp/threads.csv")
        with patch("perplexity_cli.runners.export.write_threads_csv", return_value=csv_path):
            _output_export_results(result, mode, Mock())
        out = capsys.readouterr()
        assert "[OK] Exported 3 threads" in out.out
        assert f"[OK] Saved to: {csv_path.resolve()}" in out.out
        assert "2025-01-01 to 2025-12-31" in out.err

    def test_build_export_request_full(self) -> None:
        from perplexity_cli.runners.export import _build_export_request

        req = _build_export_request(
            "2025-01-01",
            "2025-06-30",
            (),
            {"output": None, "force_refresh": True, "clear_cache": False},
        )
        assert req.date_range.from_date == "2025-01-01"
        assert req.date_range.to_date == "2025-06-30"
        assert req.output is None
        assert req.force_refresh is True
        assert req.clear_cache is False

    def test_build_export_request_positional_args(self) -> None:
        from perplexity_cli.runners.export import _build_export_request

        req = _build_export_request(None, None, (Path("/x.csv"), False, True), {})
        assert req.output == Path("/x.csv")
        assert req.force_refresh is False
        assert req.clear_cache is True

    def test_resolve_ctx_flags_schema_true(self) -> None:
        from perplexity_cli.runners.export import _resolve_ctx_flags

        mode = _resolve_ctx_flags({"json": False, "schema": True})
        assert mode.json_mode == "human"
        assert mode.include_schema == "with_schema"

    def test_thread_payload_dict_non_string_values(self) -> None:
        from perplexity_cli.runners.export import _thread_payload

        payload = _thread_payload({"title": 123, "created_at": None, "url": []})
        assert payload == {"title": "", "created_at": "", "url": ""}

    def test_thread_payload_object_non_string_attrs(self) -> None:
        from perplexity_cli.runners.export import _thread_payload

        record = SimpleNamespace(title=42, created_at=None, url=[])
        payload = _thread_payload(record)
        assert payload == {"title": "", "created_at": "", "url": ""}

    def test_handle_known_error_logs_before_exit(self) -> None:
        from perplexity_cli.runners.export import _handle_known_error

        logger = Mock()
        exc = ValueError("msg")
        with pytest.raises(SystemExit):
            _handle_known_error(exc, "human", logger)
        logger.error.assert_called_once_with("Export failed: %s", exc)

    def test_handle_auth_missing_json_calls_handle_error(self) -> None:
        from perplexity_cli.runners.export import _handle_auth_missing

        with patch("perplexity_cli.runners.export.handle_error") as mock_handle:
            with pytest.raises(SystemExit):
                _handle_auth_missing("json", Mock())
        mock_handle.assert_called_once()

    def test_handle_http_status_error_debug_true(self) -> None:
        from perplexity_cli.runners.export import _handle_http_status_error

        error = Mock()
        logger = Mock()
        with patch("perplexity_cli.runners.export.handle_http_error") as mock_http:
            _handle_http_status_error(error, "human", {"debug": True}, logger)
        mock_http.assert_called_once_with(
            error, logger, debug_mode="debug", context="during thread export"
        )

    def test_handle_http_status_error_debug_false(self) -> None:
        from perplexity_cli.runners.export import _handle_http_status_error

        error = Mock()
        logger = Mock()
        with patch("perplexity_cli.runners.export.handle_http_error") as mock_http:
            _handle_http_status_error(error, "human", {"debug": False}, logger)
        mock_http.assert_called_once_with(
            error, logger, debug_mode="normal", context="during thread export"
        )

    def test_handle_http_status_error_none_ctx(self) -> None:
        from perplexity_cli.runners.export import _handle_http_status_error

        error = Mock()
        logger = Mock()
        with patch("perplexity_cli.runners.export.handle_http_error") as mock_http:
            _handle_http_status_error(error, "human", None, logger)
        mock_http.assert_called_once_with(
            error, logger, debug_mode="normal", context="during thread export"
        )

    def test_handle_unexpected_error_message_tuple(self) -> None:
        from perplexity_cli.runners.export import _handle_unexpected_error

        with patch("perplexity_cli.runners.export.handle_unexpected_cli_error") as mock_handler:
            _handle_unexpected_error(RuntimeError("boom"), "human", {"debug": True}, Mock())
        args = mock_handler.call_args
        assert args.kwargs["debug_mode"] == "debug"
        msg_tuple = args.kwargs["message_tuple"]
        assert msg_tuple[0] == "\n[ERROR] Unexpected error: boom"
        assert msg_tuple[1] == "Unexpected error during export"
        assert msg_tuple[2] is False


# ---------------------------------------------------------------------------
# auth.py — deep branch coverage
# ---------------------------------------------------------------------------


class TestAuthR3:
    """Round 3 mutation killers for runners/auth.py."""

    def test_is_str_dict_false_for_list(self) -> None:
        from perplexity_cli.runners.auth import _is_str_dict

        assert _is_str_dict([1, 2]) is False

    def test_is_str_dict_true_for_empty_dict(self) -> None:
        from perplexity_cli.runners.auth import _is_str_dict

        assert _is_str_dict({}) is True

    def test_ctx_to_dict_non_dict_obj(self) -> None:
        from perplexity_cli.runners.auth import _ctx_to_dict

        mock_ctx = Mock()
        mock_ctx.obj = "not-a-dict"
        with patch("perplexity_cli.runners.auth.click.get_current_context", return_value=mock_ctx):
            assert _ctx_to_dict() == {}

    def test_ctx_to_dict_none_context(self) -> None:
        from perplexity_cli.runners.auth import _ctx_to_dict

        with patch("perplexity_cli.runners.auth.click.get_current_context", return_value=None):
            assert _ctx_to_dict() == {}

    def test_resolve_ctx_flags_non_dict_non_none_falls_back(self) -> None:
        from perplexity_cli.runners.auth import _resolve_ctx_flags

        with patch("perplexity_cli.runners.auth.click.get_current_context", return_value=None):
            assert _resolve_ctx_flags("garbage") == (False, False, False)

    def test_resolve_auth_output_options_mixed(self) -> None:
        from perplexity_cli.runners.auth import _resolve_auth_output_options

        opts = _resolve_auth_output_options((True, False, True))
        assert opts.output_format == "json"
        assert opts.schema_inclusion == "no_schema"
        assert opts.debug_level == "debug"

    def test_handle_auth_timeout_json_calls_handle_error(self, capsys) -> None:
        from perplexity_cli.runners.auth import _handle_auth_timeout_error

        with patch("perplexity_cli.runners.auth.handle_error") as mock_handle:
            with pytest.raises(SystemExit) as exc_info:
                _handle_auth_timeout_error(TimeoutError("t"), "json", 9222, "https://x.ai")
        assert exc_info.value.code == 1
        mock_handle.assert_called_once()

    def test_handle_auth_timeout_human_no_handle_error(self) -> None:
        from perplexity_cli.runners.auth import _handle_auth_timeout_error

        with patch("perplexity_cli.runners.auth.handle_error") as mock_handle:
            with pytest.raises(SystemExit):
                _handle_auth_timeout_error(TimeoutError("t"), "human", 9222, "https://x.ai")
        mock_handle.assert_not_called()

    def test_handle_auth_os_config_error_json_calls_handle_error(self) -> None:
        from perplexity_cli.runners.auth import _handle_auth_os_config_error

        with patch("perplexity_cli.runners.auth.handle_error") as mock_handle:
            with patch("perplexity_cli.runners.auth.handle_unexpected_cli_error"):
                _handle_auth_os_config_error(OSError("e"), "json", "normal")
        mock_handle.assert_called_once()

    def test_handle_auth_os_config_error_human_no_handle_error(self) -> None:
        from perplexity_cli.runners.auth import _handle_auth_os_config_error

        with patch("perplexity_cli.runners.auth.handle_error") as mock_handle:
            with patch("perplexity_cli.runners.auth.handle_unexpected_cli_error"):
                _handle_auth_os_config_error(OSError("e"), "human", "debug")
        mock_handle.assert_not_called()

    def test_logout_emit_human_present_exact(self, capsys) -> None:
        from perplexity_cli.runners.auth import _logout_emit

        _logout_emit("human", "no_schema", "present")
        out = capsys.readouterr().out
        assert "[OK] Logged out successfully.\n" in out
        assert "[OK] Stored credentials removed.\n" in out

    def test_logout_emit_human_absent_exact(self, capsys) -> None:
        from perplexity_cli.runners.auth import _logout_emit

        _logout_emit("human", "no_schema", "absent")
        assert capsys.readouterr().out == "No stored credentials found.\n"

    def test_logout_emit_json_present(self, capsys) -> None:
        from perplexity_cli.runners.auth import _logout_emit

        _logout_emit("json", "no_schema", "present")
        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["command"] == "pxcli auth logout"
        assert envelope["result"]["credentials_existed"] is True

    def test_logout_emit_json_absent(self, capsys) -> None:
        from perplexity_cli.runners.auth import _logout_emit

        _logout_emit("json", "no_schema", "absent")
        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["result"]["credentials_existed"] is False

    def test_resolve_logout_ctx_explicit_true(self) -> None:
        from perplexity_cli.runners.auth import _resolve_logout_ctx

        with patch("perplexity_cli.runners.auth.click.get_current_context", return_value=None):
            fmt, schema = _resolve_logout_ctx(True)
        assert fmt == "json"
        assert schema == "no_schema"

    def test_resolve_logout_ctx_explicit_false(self) -> None:
        from perplexity_cli.runners.auth import _resolve_logout_ctx

        with patch("perplexity_cli.runners.auth.click.get_current_context", return_value=None):
            fmt, schema = _resolve_logout_ctx(False)
        assert fmt == "human"

    def test_resolve_logout_ctx_none_reads_ctx(self) -> None:
        from perplexity_cli.runners.auth import _resolve_logout_ctx

        mock_ctx = Mock()
        mock_ctx.obj = {"json": True, "schema": True}
        with patch("perplexity_cli.runners.auth.click.get_current_context", return_value=mock_ctx):
            fmt, schema = _resolve_logout_ctx(None)
        assert fmt == "json"
        assert schema == "with_schema"

    @patch("perplexity_cli.runners.auth.get_save_cookies_enabled", return_value=True)
    @patch("perplexity_cli.runners.auth.TokenManager")
    def test_handle_auth_success_json_exact_keys(self, mock_tm_class, _mock, capsys) -> None:
        from perplexity_cli.runners.auth import _handle_auth_success

        mock_tm = Mock()
        mock_tm.token_path = "/home/user/.config/pxcli/token.json"
        mock_tm_class.return_value = mock_tm

        _handle_auth_success("tok", {"a": "1"}, "json", "no_schema")
        envelope = json.loads(capsys.readouterr().out.strip())
        assert set(envelope["result"].keys()) == {"token_path", "cookies_stored"}
        assert envelope["result"]["token_path"] == "/home/user/.config/pxcli/token.json"
        assert envelope["result"]["cookies_stored"] == 1

    @patch("perplexity_cli.runners.auth.TokenManager")
    @patch("perplexity_cli.runners.auth.authenticate_sync")
    def test_run_auth_command_configuration_error(self, mock_auth, mock_tm_class) -> None:
        from perplexity_cli.runners.auth import run_auth_command
        from perplexity_cli.utils.exceptions import ConfigurationError

        mock_auth.side_effect = ConfigurationError("bad config")
        mock_tm_class.return_value = Mock()

        with patch("perplexity_cli.runners.auth.handle_unexpected_cli_error") as mock_handler:
            run_auth_command({"json": False, "schema": False, "debug": False}, port=9222)
        mock_handler.assert_called_once()

    @patch("perplexity_cli.runners.auth.TokenManager")
    def test_logout_os_error_json_calls_handle_error(self, mock_tm_class) -> None:
        from perplexity_cli.runners.auth import run_logout_command

        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.clear_token.side_effect = OSError("disk")
        mock_tm_class.return_value = mock_tm

        with patch("perplexity_cli.runners.auth.handle_error") as mock_handle:
            with patch("perplexity_cli.runners.auth.handle_unexpected_cli_error"):
                run_logout_command(json_mode=True)
        mock_handle.assert_called_once()


# ---------------------------------------------------------------------------
# config.py — deep branch coverage
# ---------------------------------------------------------------------------


class TestConfigR3:
    """Round 3 mutation killers for runners/config.py."""

    def test_get_ctx_obj_dict_none_context(self) -> None:
        from perplexity_cli.runners.config import _get_ctx_obj_dict

        with patch("perplexity_cli.runners.config.click.get_current_context", return_value=None):
            assert _get_ctx_obj_dict() == {}

    def test_get_ctx_obj_dict_none_obj(self) -> None:
        from perplexity_cli.runners.config import _get_ctx_obj_dict

        mock_ctx = Mock()
        mock_ctx.obj = None
        with patch(
            "perplexity_cli.runners.config.click.get_current_context", return_value=mock_ctx
        ):
            assert _get_ctx_obj_dict() == {}

    def test_get_ctx_obj_dict_returns_obj(self) -> None:
        from perplexity_cli.runners.config import _get_ctx_obj_dict

        mock_ctx = Mock()
        mock_ctx.obj = {"json": True}
        with patch(
            "perplexity_cli.runners.config.click.get_current_context", return_value=mock_ctx
        ):
            assert _get_ctx_obj_dict() == {"json": True}

    def test_get_include_schema_true(self) -> None:
        from perplexity_cli.runners.config import _get_include_schema

        mock_ctx = Mock()
        mock_ctx.obj = {"schema": True}
        with patch(
            "perplexity_cli.runners.config.click.get_current_context", return_value=mock_ctx
        ):
            assert _get_include_schema() == "with_schema"

    def test_get_include_schema_false(self) -> None:
        from perplexity_cli.runners.config import _get_include_schema

        with patch("perplexity_cli.runners.config.click.get_current_context", return_value=None):
            assert _get_include_schema() == "no_schema"

    def test_get_json_mode_from_ctx_true(self) -> None:
        from perplexity_cli.runners.config import _get_json_mode_from_ctx

        mock_ctx = Mock()
        mock_ctx.obj = {"json": True}
        with patch(
            "perplexity_cli.runners.config.click.get_current_context", return_value=mock_ctx
        ):
            assert _get_json_mode_from_ctx() == "json"

    def test_handle_style_error_json_calls_handle_error(self) -> None:
        from perplexity_cli.runners.config import _handle_style_error

        with patch("perplexity_cli.runners.config.handle_error") as mock_handle:
            with pytest.raises(SystemExit) as exc_info:
                _handle_style_error(ValueError("v"), "json", "pxcli style set", "Invalid style")
        assert exc_info.value.code == 1
        mock_handle.assert_called_once()

    def test_handle_style_error_human_no_handle_error(self, capsys) -> None:
        from perplexity_cli.runners.config import _handle_style_error

        with patch("perplexity_cli.runners.config.handle_error") as mock_handle:
            with pytest.raises(SystemExit):
                _handle_style_error(ValueError("v"), "human", "pxcli style set", "Invalid style")
        mock_handle.assert_not_called()
        assert "[ERROR] Invalid style: v" in capsys.readouterr().err

    @patch("perplexity_cli.runners.config.set_feature")
    @patch("perplexity_cli.runners.config.clear_feature_config_cache")
    def test_set_config_value_case_insensitive_true(self, mock_clear, mock_set, capsys) -> None:
        from perplexity_cli.runners.config import run_set_config_command

        run_set_config_command("save_cookies", "TRUE")
        mock_set.assert_called_once_with("save_cookies", True)
        assert "save_cookies = True" in capsys.readouterr().out

    @patch("perplexity_cli.runners.config.set_feature")
    @patch("perplexity_cli.runners.config.clear_feature_config_cache")
    def test_set_config_value_case_insensitive_false(self, mock_clear, mock_set, capsys) -> None:
        from perplexity_cli.runners.config import run_set_config_command

        run_set_config_command("debug_mode", "FALSE")
        mock_set.assert_called_once_with("debug_mode", False)
        assert "debug_mode = False" in capsys.readouterr().out

    @patch("perplexity_cli.runners.config.set_feature")
    @patch("perplexity_cli.runners.config.clear_feature_config_cache")
    def test_set_config_non_true_string_is_false(self, mock_clear, mock_set, capsys) -> None:
        from perplexity_cli.runners.config import run_set_config_command

        run_set_config_command("save_cookies", "yes")
        mock_set.assert_called_once_with("save_cookies", False)

    @patch("perplexity_cli.runners.config.set_feature")
    @patch("perplexity_cli.runners.config.clear_feature_config_cache")
    def test_set_config_clears_cache(self, mock_clear, mock_set) -> None:
        from perplexity_cli.runners.config import run_set_config_command

        run_set_config_command("save_cookies", "true")
        mock_clear.assert_called_once()

    @patch("perplexity_cli.runners.config.set_feature")
    @patch("perplexity_cli.runners.config.clear_feature_config_cache")
    def test_output_config_change_json_exact(self, mock_clear, mock_set, capsys) -> None:
        from perplexity_cli.runners.config import run_set_config_command

        run_set_config_command("debug_mode", "false", output_format="json")
        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["command"] == "pxcli config set"
        assert envelope["result"]["key"] == "debug_mode"
        assert envelope["result"]["value"] is False

    @patch("perplexity_cli.runners.config.set_feature")
    @patch("perplexity_cli.runners.config.clear_feature_config_cache")
    def test_set_config_error_json_calls_handle_error(self, mock_clear, mock_set) -> None:
        from perplexity_cli.runners.config import run_set_config_command
        from perplexity_cli.utils.exceptions import ConfigurationError

        mock_set.side_effect = ConfigurationError("bad")
        with patch("perplexity_cli.runners.config.handle_error") as mock_handle:
            with pytest.raises(SystemExit):
                run_set_config_command("x", "true", output_format="json")
        mock_handle.assert_called_once()

    @patch("perplexity_cli.runners.config.get_feature_config_path")
    @patch("perplexity_cli.runners.config.get_feature_config")
    def test_show_config_json_env_overrides_empty(
        self, mock_get_config, mock_get_path, capsys, monkeypatch
    ) -> None:
        from perplexity_cli.runners.config import run_show_config_command

        monkeypatch.delenv("PERPLEXITY_SAVE_COOKIES", raising=False)
        monkeypatch.delenv("PERPLEXITY_DEBUG_MODE", raising=False)
        mock_get_config.return_value = SimpleNamespace(save_cookies=False, debug_mode=True)
        mock_get_path.return_value = Path("/tmp/cfg.json")

        run_show_config_command(output_format="json")
        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["result"]["env_overrides"] == []
        assert envelope["result"]["debug_mode"] is True

    @patch("perplexity_cli.runners.config.get_feature_config_path")
    @patch("perplexity_cli.runners.config.get_feature_config")
    def test_show_config_error_json_calls_handle_error(
        self, mock_get_config, mock_get_path
    ) -> None:
        from perplexity_cli.runners.config import run_show_config_command
        from perplexity_cli.utils.exceptions import ConfigurationError

        mock_get_config.side_effect = ConfigurationError("bad")
        with patch("perplexity_cli.runners.config.handle_error") as mock_handle:
            with pytest.raises(SystemExit):
                run_show_config_command(output_format="json")
        mock_handle.assert_called_once()

    @patch("perplexity_cli.runners.config.StyleManager")
    def test_configure_json_value_error_calls_handle_error(self, mock_sm_class) -> None:
        from perplexity_cli.runners.config import run_configure_command

        mock_sm_class.return_value.save_style.side_effect = ValueError("bad")
        with patch("perplexity_cli.runners.config.handle_error") as mock_handle:
            with pytest.raises(SystemExit):
                run_configure_command("x", output_format="json")
        mock_handle.assert_called_once()

    @patch("perplexity_cli.runners.config.StyleManager")
    def test_clear_style_json_os_error_calls_handle_error(self, mock_sm_class) -> None:
        from perplexity_cli.runners.config import run_clear_style_command

        mock_sm_class.return_value.load_style.side_effect = OSError("io")
        with patch("perplexity_cli.runners.config.handle_error") as mock_handle:
            with pytest.raises(SystemExit):
                run_clear_style_command(output_format="json")
        mock_handle.assert_called_once()

    def test_print_config_change_message_debug_enabled_exact(self, capsys) -> None:
        from perplexity_cli.runners.config import _print_config_change_message

        _print_config_change_message("debug_mode", "enabled")
        out = capsys.readouterr().out
        assert "\n[INFO] Debug mode enabled.\n" in out
        assert "  All commands will now log at DEBUG level.\n" in out

    def test_output_config_text_no_env_overrides_no_section(self, capsys) -> None:
        from perplexity_cli.runners.config import _output_config_text

        config = SimpleNamespace(save_cookies=True, debug_mode=True)
        _output_config_text(config, "/p", [])
        out = capsys.readouterr().out
        assert "Environment Overrides:" not in out
        assert "  save_cookies: True" in out
        assert "  debug_mode:   True" in out


# ---------------------------------------------------------------------------
# status.py — deep branch coverage
# ---------------------------------------------------------------------------


class TestStatusR3:
    """Round 3 mutation killers for runners/status.py."""

    def test_ctx_to_dict_non_dict_obj(self) -> None:
        from perplexity_cli.runners.status import _ctx_to_dict

        mock_ctx = Mock()
        mock_ctx.obj = [1, 2, 3]
        with patch(
            "perplexity_cli.runners.status.click.get_current_context", return_value=mock_ctx
        ):
            assert _ctx_to_dict() == {}

    def test_ctx_to_dict_none_ctx(self) -> None:
        from perplexity_cli.runners.status import _ctx_to_dict

        with patch("perplexity_cli.runners.status.click.get_current_context", return_value=None):
            assert _ctx_to_dict() == {}

    def test_get_include_schema_true(self) -> None:
        from perplexity_cli.runners.status import _get_include_schema

        mock_ctx = Mock()
        mock_ctx.obj = {"schema": True}
        with patch(
            "perplexity_cli.runners.status.click.get_current_context", return_value=mock_ctx
        ):
            assert _get_include_schema() == "with_schema"

    def test_get_include_schema_default(self) -> None:
        from perplexity_cli.runners.status import _get_include_schema

        with patch("perplexity_cli.runners.status.click.get_current_context", return_value=None):
            assert _get_include_schema() == "no_schema"

    def test_describe_file_permissions_secure_0o755(self, tmp_path) -> None:
        from perplexity_cli.runners.status import _describe_file_permissions

        f = tmp_path / "f.json"
        f.write_text("{}")
        os.chmod(f, 0o755)
        assert _describe_file_permissions(f, 0o755) == "secure (0o755)"

    def test_describe_file_permissions_insecure_0o777(self, tmp_path) -> None:
        from perplexity_cli.runners.status import _describe_file_permissions

        f = tmp_path / "f.json"
        f.write_text("{}")
        os.chmod(f, 0o777)
        result = _describe_file_permissions(f, 0o600)
        assert result == "insecure (0o777; expected 0o600)"

    def test_get_token_age_days_value_error(self) -> None:
        from perplexity_cli.runners.status import _get_token_age_days

        path = Mock()
        path.stat.side_effect = ValueError
        assert _get_token_age_days(path) is None

    def test_get_token_age_days_large_age(self) -> None:
        from perplexity_cli.runners.status import _get_token_age_days

        path = Mock()
        old = datetime.now() - timedelta(days=365)
        path.stat.return_value = Mock(st_mtime=old.timestamp())
        assert _get_token_age_days(path) == 365

    def test_verify_token_http_status_error(self) -> None:
        from perplexity_cli.runners.status import _verify_token
        from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError

        with patch("perplexity_cli.runners.status.PerplexityAPI") as mock_api:
            mock_api.return_value.__enter__ = Mock(side_effect=PerplexityHTTPStatusError("err"))
            mock_api.return_value.__exit__ = Mock(return_value=False)
            assert _verify_token("t", {}, Mock()) is False

    def test_verify_token_upstream_schema_error(self) -> None:
        from perplexity_cli.runners.status import _verify_token
        from perplexity_cli.utils.exceptions import UpstreamSchemaError

        with patch("perplexity_cli.runners.status.PerplexityAPI") as mock_api:
            mock_api.return_value.__enter__ = Mock(side_effect=UpstreamSchemaError("bad"))
            mock_api.return_value.__exit__ = Mock(return_value=False)
            assert _verify_token("t", None, Mock()) is False

    def test_verify_token_authentication_error(self) -> None:
        from perplexity_cli.runners.status import _verify_token
        from perplexity_cli.utils.exceptions import AuthenticationError

        with patch("perplexity_cli.runners.status.PerplexityAPI") as mock_api:
            mock_api.return_value.__enter__ = Mock(side_effect=AuthenticationError("no"))
            mock_api.return_value.__exit__ = Mock(return_value=False)
            assert _verify_token("t", {}, Mock()) is False

    def test_output_status_text_verify_true_verified_none(self, capsys) -> None:
        from perplexity_cli.runners.status import _output_status_text

        tm = Mock()
        tm.token_path = Mock()
        tm.token_path.stat.return_value = Mock(st_mtime=1700000000.0)
        _output_status_text("tok", {}, (5, None, True), tm=tm)
        out = capsys.readouterr().out
        assert "[INFO] Token verification returned empty response" in out

    def test_output_token_modified_time_attribute_error(self, capsys) -> None:
        from perplexity_cli.runners.status import _output_token_modified_time

        path = Mock()
        path.stat.side_effect = AttributeError
        _output_token_modified_time(path, 5)
        assert "unavailable" in capsys.readouterr().out

    @patch("perplexity_cli.runners.status.PerplexityAPI")
    @patch("perplexity_cli.runners.status.TokenManager")
    def test_run_status_verify_human_verified_false(
        self, mock_tm_class, mock_api_class, capsys
    ) -> None:
        from perplexity_cli.runners.status import run_status_command
        from perplexity_cli.utils.exceptions import PerplexityRequestError

        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.load_token.return_value = ("tok", {"c": "v"})
        mock_token_path = Mock()
        mock_token_path.__str__ = Mock(return_value="/tmp/t.json")
        mock_token_path.stat.return_value = Mock(st_mtime=1700000000.0)
        mock_tm.token_path = mock_token_path
        mock_tm_class.return_value = mock_tm

        mock_api_class.return_value.__enter__ = Mock(side_effect=PerplexityRequestError("down"))
        mock_api_class.return_value.__exit__ = Mock(return_value=False)

        run_status_command(verify="verify")
        out = capsys.readouterr().out
        assert "[ERROR] Token verification failed" in out

    @patch("perplexity_cli.runners.status.PerplexityAPI")
    @patch("perplexity_cli.runners.status.TokenManager")
    def test_run_status_verify_json_verified_false(
        self, mock_tm_class, mock_api_class, capsys
    ) -> None:
        from perplexity_cli.runners.status import run_status_command
        from perplexity_cli.utils.exceptions import PerplexityRequestError

        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.load_token.return_value = ("tok", None)
        mock_token_path = Mock()
        mock_token_path.__str__ = Mock(return_value="/tmp/t.json")
        mock_token_path.stat.return_value = Mock(st_mtime=1700000000.0)
        mock_tm.token_path = mock_token_path
        mock_tm_class.return_value = mock_tm

        mock_api_class.return_value.__enter__ = Mock(side_effect=PerplexityRequestError("down"))
        mock_api_class.return_value.__exit__ = Mock(return_value=False)

        run_status_command(verify="verify", output_format="json")
        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["result"]["verified"] is False
        assert envelope["result"]["cookies_stored"] == 0

    @patch("perplexity_cli.runners.status.get_feature_config")
    @patch("perplexity_cli.runners.status.ThreadCacheManager")
    @patch("perplexity_cli.runners.status.TokenManager")
    def test_doctor_security_text_threat_model_line(
        self, mock_tm_class, mock_cm_class, mock_feature_config, capsys
    ) -> None:
        from perplexity_cli.runners.status import run_doctor_security_command

        mock_tm = Mock()
        mock_tm.token_path = Mock(__str__=Mock(return_value="/t"))
        mock_tm.token_path.exists.return_value = False
        mock_tm.SECURE_PERMISSIONS = 0o600
        mock_tm_class.return_value = mock_tm

        mock_cm = Mock()
        mock_cm.cache_path = Mock(__str__=Mock(return_value="/c"))
        mock_cm.cache_path.exists.return_value = False
        mock_cm.SECURE_PERMISSIONS = 0o600
        mock_cm_class.return_value = mock_cm

        mock_feature_config.return_value = Mock(save_cookies=True)

        run_doctor_security_command(output_format="human")
        out = capsys.readouterr().out
        assert (
            "Threat model: protects against casual file copying between machines, not against "
            "other local processes or users that can already read these files"
        ) in out
        assert "Cookie storage warning: browser cookies are sensitive" in out

    @patch("perplexity_cli.runners.status.get_feature_config")
    @patch("perplexity_cli.runners.status.ThreadCacheManager")
    @patch("perplexity_cli.runners.status.TokenManager")
    def test_doctor_security_json_exact_keys(
        self, mock_tm_class, mock_cm_class, mock_feature_config, capsys
    ) -> None:
        from perplexity_cli.runners.status import run_doctor_security_command

        mock_tm = Mock()
        mock_tm.token_path = Mock(__str__=Mock(return_value="/t"))
        mock_tm.token_path.exists.return_value = False
        mock_tm.SECURE_PERMISSIONS = 0o600
        mock_tm_class.return_value = mock_tm

        mock_cm = Mock()
        mock_cm.cache_path = Mock(__str__=Mock(return_value="/c"))
        mock_cm.cache_path.exists.return_value = False
        mock_cm.SECURE_PERMISSIONS = 0o600
        mock_cm_class.return_value = mock_cm

        mock_feature_config.return_value = Mock(save_cookies=False)

        run_doctor_security_command(output_format="json")
        envelope = json.loads(capsys.readouterr().out.strip())
        result = envelope["result"]
        assert set(result.keys()) == {
            "storage_backend",
            "token_path",
            "token_permissions",
            "cache_path",
            "cache_permissions",
            "cookies_enabled",
        }
        assert result["cookies_enabled"] is False

    def test_build_status_envelope_command_name(self) -> None:
        from perplexity_cli.runners.status import _build_status_envelope

        tm = Mock()
        tm.token_path = Mock(__str__=Mock(return_value="/t"))
        env = _build_status_envelope(True, tm, (10, 5, False))
        assert env.command == "pxcli auth status"
        assert env.result["token_age_days"] == 10
        assert env.result["cookies_stored"] == 5
        assert env.result["verified"] is False

    @patch("perplexity_cli.runners.status.TokenManager")
    def test_run_status_no_token_json_exact_envelope(self, mock_tm_class, capsys) -> None:
        from perplexity_cli.runners.status import run_status_command

        mock_tm = Mock()
        mock_tm.token_exists.return_value = False
        mock_tm.token_path = Mock(__str__=Mock(return_value="/tmp/tok.json"))
        mock_tm_class.return_value = mock_tm

        run_status_command(verify="skip", output_format="json")
        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["command"] == "pxcli auth status"
        assert envelope["result"]["token_path"] == "/tmp/tok.json"
        assert envelope["result"]["token_age_days"] is None
        assert envelope["result"]["cookies_stored"] == 0
        assert envelope["result"]["verified"] is None


# ---------------------------------------------------------------------------
# models.py — deep branch coverage
# ---------------------------------------------------------------------------


class TestModelsR3:
    """Round 3 mutation killers for runners/models.py."""

    def test_format_row_single_char_cells(self) -> None:
        from perplexity_cli.runners.models import _format_row

        result = _format_row(("a", "b", "c", "d"), [1, 1, 1, 1])
        assert result == "a  b  c  d"

    def test_format_row_uneven_widths(self) -> None:
        from perplexity_cli.runners.models import _format_row

        result = _format_row(("short", "x", "y", "z"), [10, 2, 2, 2])
        assert result == "short       x   y   z "

    def test_format_separator_single_column(self) -> None:
        from perplexity_cli.runners.models import _format_separator

        assert _format_separator([5]) == "-----"

    def test_calculate_column_widths_empty_rows(self) -> None:
        from perplexity_cli.runners.models import _calculate_column_widths

        headers = ("MODEL ID", "LABEL", "TIER", "DESCRIPTION")
        assert _calculate_column_widths(headers, []) == [8, 5, 4, 11]

    def test_render_table_two_rows(self) -> None:
        from perplexity_cli.runners.models import _render_table

        rows = [("m1", "A", "Pro", "D1"), ("m22", "BB", "Max", "D2")]
        output = _render_table(rows)
        lines = output.split("\n")
        assert len(lines) == 4
        assert lines[0].startswith("MODEL ID")
        assert all(c in "-  " for c in lines[1])

    def test_build_table_rows_empty_description(self) -> None:
        from perplexity_cli.models.model_config import ModelConfigEntry
        from perplexity_cli.runners.models import _build_table_rows

        entry = ModelConfigEntry(
            label="X",
            description="",
            subscription_tier="pro",
            non_reasoning_model="m1",
        )
        rows = _build_table_rows([entry])
        assert rows[0][3] == ""

    def test_build_table_rows_none_model_id(self) -> None:
        from perplexity_cli.models.model_config import ModelConfigEntry
        from perplexity_cli.runners.models import _build_table_rows

        entry = ModelConfigEntry(
            label="X",
            description="D",
            subscription_tier="free",
            non_reasoning_model=None,
        )
        rows = _build_table_rows([entry])
        assert rows[0][0] == "(none)"
        assert rows[0][2] == "Free"

    def test_entry_to_dict_none_reasoning(self) -> None:
        from perplexity_cli.models.model_config import ModelConfigEntry
        from perplexity_cli.runners.models import _entry_to_dict

        entry = ModelConfigEntry(
            label="L",
            description="D",
            subscription_tier="pro",
            non_reasoning_model="m1",
            reasoning_model=None,
        )
        result = _entry_to_dict(entry)
        assert result["reasoning_model"] is None
        assert result["is_default"] is False

    def test_handle_list_error_json_calls_handle_error(self) -> None:
        from perplexity_cli.runners.models import _handle_list_error
        from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError

        with patch("perplexity_cli.runners.models.handle_error") as mock_handle:
            with pytest.raises(SystemExit):
                _handle_list_error(PerplexityHTTPStatusError("err"), "json", Mock())
        mock_handle.assert_called_once()

    def test_handle_list_error_human_no_handle_error(self) -> None:
        from perplexity_cli.runners.models import _handle_list_error

        with patch("perplexity_cli.runners.models.handle_error") as mock_handle:
            with pytest.raises(SystemExit):
                _handle_list_error(RuntimeError("x"), "human", Mock())
        mock_handle.assert_not_called()

    def test_detect_subscription_level_logs_warning(self) -> None:
        from perplexity_cli.runners.models import _detect_subscription_level

        mock_client = MagicMock()
        mock_client.get_json.side_effect = RuntimeError("fail")
        with patch("perplexity_cli.runners.models.get_logger") as mock_get_logger:
            logger = Mock()
            mock_get_logger.return_value = logger
            level = _detect_subscription_level(mock_client)
        assert level.value == "pro"
        logger.warning.assert_called_once()

    def test_run_models_list_json_schema_flag(self, capsys) -> None:
        from perplexity_cli.models.model_config import ModelConfigEntry
        from perplexity_cli.runners.models import run_models_list_command

        entries = [
            ModelConfigEntry(
                label="M",
                description="D",
                subscription_tier="pro",
                non_reasoning_model="m1",
            ),
        ]
        mock_service = MagicMock()
        mock_service.list_available_models.return_value = entries

        with (
            patch("perplexity_cli.runners.models._resolve_auth", return_value=("t", {})),
            patch("perplexity_cli.runners.models._create_rest_client", return_value=MagicMock()),
            patch(
                "perplexity_cli.runners.models._detect_subscription_level",
                return_value=MagicMock(),
            ),
            patch("perplexity_cli.runners.models._create_model_service", return_value=mock_service),
        ):
            run_models_list_command(ctx_obj={"json": True, "schema": True})

        envelope = json.loads(capsys.readouterr().out.strip())
        assert "$schema" in envelope
        assert envelope["ok"] is True

    def test_run_models_list_human_no_schema(self, capsys) -> None:
        from perplexity_cli.models.model_config import ModelConfigEntry
        from perplexity_cli.runners.models import run_models_list_command

        entries = [
            ModelConfigEntry(
                label="TestModel",
                description="Desc",
                subscription_tier="pro",
                non_reasoning_model="tm1",
            ),
        ]
        mock_service = MagicMock()
        mock_service.list_available_models.return_value = entries

        with (
            patch("perplexity_cli.runners.models._resolve_auth", return_value=("t", None)),
            patch("perplexity_cli.runners.models._create_rest_client", return_value=MagicMock()),
            patch(
                "perplexity_cli.runners.models._detect_subscription_level",
                return_value=MagicMock(),
            ),
            patch("perplexity_cli.runners.models._create_model_service", return_value=mock_service),
        ):
            run_models_list_command(ctx_obj={"json": False, "schema": False})

        out = capsys.readouterr().out
        assert "TestModel" in out
        assert "tm1" in out

    def test_get_ctx_flag_schema_key(self) -> None:
        from perplexity_cli.runners.models import _get_ctx_flag

        assert _get_ctx_flag({"schema": True}, "schema") is True
        assert _get_ctx_flag({"json": True}, "schema") is False

    def test_build_models_json_result_multiple(self) -> None:
        from perplexity_cli.models.model_config import ModelConfigEntry
        from perplexity_cli.runners.models import build_models_json_result

        entries = [
            ModelConfigEntry(
                label="A", description="D1", subscription_tier="pro", non_reasoning_model="m1"
            ),
            ModelConfigEntry(
                label="B", description="D2", subscription_tier="max", non_reasoning_model="m2"
            ),
        ]
        result = build_models_json_result(entries)
        assert len(result["models"]) == 2
        assert result["models"][0]["model_id"] == "m1"
        assert result["models"][1]["model_id"] == "m2"
        assert result["models"][1]["tier"] == "max"
