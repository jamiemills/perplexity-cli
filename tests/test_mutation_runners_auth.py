"""Round 2 mutation-killing tests for runners/ and auth/.

Targets survivors missed by round 1: exact string literals, arithmetic,
boundary comparisons, boolean short-circuits, return values, and constants.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from perplexity_cli.config.defaults import (
    DEFAULT_AUTH_POLL_INTERVAL,
    DEFAULT_AUTH_TIMEOUT,
    DEFAULT_CHROME_DEBUG_PORT,
    DEFAULT_STATUS_CHECK_TIMEOUT,
)

# ---------------------------------------------------------------------------
# runners/auth.py — exact strings and flag resolution
# ---------------------------------------------------------------------------


class TestAuthRunnerExactStrings:
    """Exact-output mutation killers for runners/auth.py."""

    def test_auth_login_command_constant(self) -> None:
        from perplexity_cli.runners.auth import _AUTH_LOGIN_COMMAND

        assert _AUTH_LOGIN_COMMAND == "pxcli auth login"

    def test_print_auth_troubleshooting_exact_steps(self, capsys) -> None:
        from perplexity_cli.runners.auth import _print_auth_troubleshooting

        _print_auth_troubleshooting(9222, "https://www.perplexity.ai")

        err = capsys.readouterr().err
        assert "\nTroubleshooting:" in err
        assert "  1. Start Chrome with: --remote-debugging-port=9222" in err
        assert "  2. Ensure Chrome is running and accessible" in err
        assert "  3. Navigate to https://www.perplexity.ai in Chrome" in err
        assert "  4. Log in with your Google account" in err
        assert "  5. Run this command again" in err

    def test_print_auth_troubleshooting_interpolates_port(self, capsys) -> None:
        from perplexity_cli.runners.auth import _print_auth_troubleshooting

        _print_auth_troubleshooting(1234, "https://example.com")

        err = capsys.readouterr().err
        assert "--remote-debugging-port=1234" in err
        assert "Navigate to https://example.com in Chrome" in err

    @patch("perplexity_cli.runners.auth.get_save_cookies_enabled", return_value=True)
    @patch("perplexity_cli.runners.auth.TokenManager")
    def test_handle_auth_success_human_exact_lines(
        self, mock_tm_class, _mock_cookies, capsys
    ) -> None:
        from perplexity_cli.runners.auth import _handle_auth_success

        mock_tm = Mock()
        mock_tm.token_path = "/tmp/tok.json"
        mock_tm_class.return_value = mock_tm

        _handle_auth_success("tok", {"a": "1", "b": "2"}, "human", "no_schema")

        out = capsys.readouterr().out
        assert "[OK] Authentication successful!" in out
        assert "[OK] Token saved to: /tmp/tok.json" in out
        assert "[OK] 2 cookies saved (including Cloudflare cookies)" in out
        assert '\nYou can now use: pxcli query "<your question>"' in out

    @patch("perplexity_cli.runners.auth.get_save_cookies_enabled", return_value=True)
    @patch("perplexity_cli.runners.auth.TokenManager")
    def test_handle_auth_success_saves_token_and_cookies(
        self, mock_tm_class, _mock_cookies
    ) -> None:
        from perplexity_cli.runners.auth import _handle_auth_success

        mock_tm = Mock()
        mock_tm.token_path = "/tmp/tok.json"
        mock_tm_class.return_value = mock_tm

        _handle_auth_success("tok", {"a": "1"}, "human", "no_schema")

        mock_tm.save_token.assert_called_once_with("tok", cookies={"a": "1"})

    @patch("perplexity_cli.runners.auth.get_save_cookies_enabled", return_value=True)
    @patch("perplexity_cli.runners.auth.TokenManager")
    def test_handle_auth_success_json_envelope(self, mock_tm_class, _mock_cookies, capsys) -> None:
        from perplexity_cli.runners.auth import _handle_auth_success

        mock_tm = Mock()
        mock_tm.token_path = "/tmp/tok.json"
        mock_tm_class.return_value = mock_tm

        _handle_auth_success("tok", {"a": "1", "b": "2", "c": "3"}, "json", "no_schema")

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["command"] == "pxcli auth login"
        assert envelope["result"]["token_path"] == "/tmp/tok.json"
        assert envelope["result"]["cookies_stored"] == 3

    def test_resolve_auth_output_options_all_true(self) -> None:
        from perplexity_cli.runners.auth import _resolve_auth_output_options

        opts = _resolve_auth_output_options((True, True, True))
        assert opts.output_format == "json"
        assert opts.schema_inclusion == "with_schema"
        assert opts.debug_level == "debug"

    def test_resolve_auth_output_options_all_false(self) -> None:
        from perplexity_cli.runners.auth import _resolve_auth_output_options

        opts = _resolve_auth_output_options((False, False, False))
        assert opts.output_format == "human"
        assert opts.schema_inclusion == "no_schema"
        assert opts.debug_level == "normal"

    def test_resolve_ctx_flags_none_ctx_defaults_false(self) -> None:
        from perplexity_cli.runners.auth import _resolve_ctx_flags

        with patch("perplexity_cli.runners.auth.click.get_current_context", return_value=None):
            assert _resolve_ctx_flags(None) == (False, False, False)

    def test_resolve_ctx_flags_explicit_dict(self) -> None:
        from perplexity_cli.runners.auth import _resolve_ctx_flags

        assert _resolve_ctx_flags({"json": True, "schema": True, "debug": False}) == (
            True,
            True,
            False,
        )

    @patch("perplexity_cli.runners.auth.TokenManager")
    @patch("perplexity_cli.runners.auth.authenticate_sync")
    def test_handle_auth_timeout_error_exact_message(
        self, mock_auth, mock_tm_class, capsys
    ) -> None:
        from perplexity_cli.runners.auth import run_auth_command

        mock_auth.side_effect = TimeoutError("timed out here")
        mock_tm_class.return_value = Mock()

        with pytest.raises(SystemExit) as exc_info:
            run_auth_command({"json": False, "schema": False, "debug": False}, port=9222)

        assert exc_info.value.code == 1
        assert "[ERROR] Authentication failed: timed out here" in capsys.readouterr().err

    @patch("perplexity_cli.runners.auth.get_save_cookies_enabled", return_value=False)
    @patch("perplexity_cli.runners.auth.TokenManager")
    @patch("perplexity_cli.runners.auth.authenticate_sync")
    def test_run_auth_command_human_banner_exact(
        self, mock_auth, mock_tm_class, _mock_cookies, capsys
    ) -> None:
        from perplexity_cli.runners.auth import run_auth_command

        mock_auth.return_value = ("tok", {})
        mock_tm = Mock()
        mock_tm.token_path = "/tmp/tok.json"
        mock_tm_class.return_value = mock_tm

        run_auth_command({"json": False, "schema": False, "debug": False}, port=9222)

        out = capsys.readouterr().out
        assert "Authenticating with Perplexity.ai..." in out
        assert "Make sure Chrome is running with --remote-debugging-port=9222" in out
        assert "and log in if needed." in out


# ---------------------------------------------------------------------------
# runners/config.py — env overrides, exact text, ctx bool reading
# ---------------------------------------------------------------------------


class TestConfigRunnerExactStrings:
    """Exact-output mutation killers for runners/config.py."""

    def test_collect_env_overrides_with_prefix(self, monkeypatch) -> None:
        from perplexity_cli.runners.config import _collect_env_overrides

        monkeypatch.setenv("PERPLEXITY_SAVE_COOKIES", "true")
        monkeypatch.setenv("PERPLEXITY_DEBUG_MODE", "false")

        assert _collect_env_overrides(prefix="  ") == [
            "  PERPLEXITY_SAVE_COOKIES=true",
            "  PERPLEXITY_DEBUG_MODE=false",
        ]

    def test_collect_env_overrides_no_prefix(self, monkeypatch) -> None:
        from perplexity_cli.runners.config import _collect_env_overrides

        monkeypatch.setenv("PERPLEXITY_SAVE_COOKIES", "1")
        monkeypatch.delenv("PERPLEXITY_DEBUG_MODE", raising=False)

        assert _collect_env_overrides() == ["PERPLEXITY_SAVE_COOKIES=1"]

    def test_collect_env_overrides_empty_when_unset(self, monkeypatch) -> None:
        from perplexity_cli.runners.config import _collect_env_overrides

        monkeypatch.delenv("PERPLEXITY_SAVE_COOKIES", raising=False)
        monkeypatch.delenv("PERPLEXITY_DEBUG_MODE", raising=False)

        assert _collect_env_overrides() == []

    def test_output_config_text_exact_header_and_toggles(self, capsys) -> None:
        from perplexity_cli.runners.config import _output_config_text

        config = SimpleNamespace(save_cookies=True, debug_mode=False)
        _output_config_text(config, "/tmp/config.json", [])

        out = capsys.readouterr().out
        assert "Perplexity CLI Configuration" in out
        assert "=" * 40 in out
        assert "Config file: /tmp/config.json" in out
        assert "Feature Toggles:" in out
        assert "  save_cookies: True" in out
        assert "  debug_mode:   False" in out

    def test_output_config_text_help_lines_exact(self, capsys) -> None:
        from perplexity_cli.runners.config import _output_config_text

        config = SimpleNamespace(save_cookies=False, debug_mode=False)
        _output_config_text(config, "/tmp/config.json", [])

        out = capsys.readouterr().out
        assert "To change settings:" in out
        assert "  pxcli config set save_cookies true|false" in out
        assert "  pxcli config set debug_mode true|false" in out

    def test_output_config_text_env_overrides_section(self, capsys) -> None:
        from perplexity_cli.runners.config import _output_config_text

        config = SimpleNamespace(save_cookies=False, debug_mode=False)
        _output_config_text(config, "/tmp/config.json", ["  PERPLEXITY_SAVE_COOKIES=true"])

        out = capsys.readouterr().out
        assert "Environment Overrides:" in out
        assert "  PERPLEXITY_SAVE_COOKIES=true" in out

    def test_read_ctx_bool_dict_branch_true(self) -> None:
        from perplexity_cli.runners.config import _read_ctx_bool

        assert _read_ctx_bool({"json": True}, "json") is True

    def test_read_ctx_bool_dict_branch_missing(self) -> None:
        from perplexity_cli.runners.config import _read_ctx_bool

        assert _read_ctx_bool({}, "json") is False

    def test_read_ctx_bool_object_branch(self) -> None:
        from perplexity_cli.runners.config import _read_ctx_bool

        assert _read_ctx_bool(SimpleNamespace(json=True), "json") is True
        assert _read_ctx_bool(SimpleNamespace(), "json") is False

    def test_output_view_style_none_exact(self, capsys) -> None:
        from perplexity_cli.runners.config import _output_view_style

        _output_view_style(None)

        out = capsys.readouterr().out
        assert "No style configured." in out
        assert "\nSet a style with:" in out
        assert "  perplexity-cli configure <STYLE>" in out

    def test_output_view_style_value_exact_separator(self, capsys) -> None:
        from perplexity_cli.runners.config import _output_view_style

        _output_view_style("My style")

        out = capsys.readouterr().out
        assert "Current style:" in out
        assert "-" * 50 in out
        assert "My style" in out

    def test_print_config_change_message_unknown_key_no_output(self, capsys) -> None:
        from perplexity_cli.runners.config import _print_config_change_message

        _print_config_change_message("unknown_key", "enabled")

        assert capsys.readouterr().out == ""

    def test_print_config_change_message_save_cookies_enabled_exact(self, capsys) -> None:
        from perplexity_cli.runners.config import _print_config_change_message

        _print_config_change_message("save_cookies", "enabled")

        out = capsys.readouterr().out
        assert "[INFO] Cookie storage enabled." in out
        assert "  Re-authenticate to save cookies: pxcli auth login" in out

    def test_config_change_messages_constant_contents(self) -> None:
        from perplexity_cli.runners.config import _CONFIG_CHANGE_MESSAGES

        assert _CONFIG_CHANGE_MESSAGES["debug_mode", "disabled"] == (
            "[INFO] Debug mode disabled.",
            "  Use --debug flag for one-time debug output.",
        )
        assert _CONFIG_CHANGE_MESSAGES["save_cookies", "disabled"] == (
            "[INFO] Cookie storage disabled.",
            "  Only JWT token will be saved on next authentication.",
        )

    @patch("perplexity_cli.runners.config.StyleManager")
    def test_configure_command_human_exact_preview_lines(self, mock_sm_class, capsys) -> None:
        from perplexity_cli.runners.config import run_configure_command

        mock_sm_class.return_value = Mock()

        run_configure_command("Be terse")

        out = capsys.readouterr().out
        assert "[OK] Style configured successfully." in out
        assert "[OK] Style will be applied to all future queries." in out
        assert "\nStyle preview:" in out
        assert "  Be terse" in out


# ---------------------------------------------------------------------------
# runners/export.py — constants, payload, exact error strings
# ---------------------------------------------------------------------------


class TestExportRunnerExactStrings:
    """Exact-output mutation killers for runners/export.py."""

    def test_command_constant(self) -> None:
        from perplexity_cli.runners.export import _COMMAND

        assert _COMMAND == "pxcli threads export"

    def test_export_tail_arg_count_constant(self) -> None:
        from perplexity_cli.runners.export import _EXPORT_TAIL_ARG_COUNT

        assert _EXPORT_TAIL_ARG_COUNT == 3

    def test_cache_action_enum_values(self) -> None:
        from perplexity_cli.runners.export import CacheAction

        assert CacheAction.CLEAR.value == "clear"
        assert CacheAction.PRESERVE.value == "preserve"

    def test_thread_attribute_attribute_error_returns_empty(self) -> None:
        from perplexity_cli.runners.export import _thread_attribute

        class Bare:
            pass

        assert _thread_attribute(Bare(), lambda thread: thread.title) == ""

    def test_thread_attribute_non_string_returns_empty(self) -> None:
        from perplexity_cli.runners.export import _thread_attribute

        record = SimpleNamespace(title=42)
        assert _thread_attribute(record, lambda thread: thread.title) == ""

    def test_thread_attribute_string_value(self) -> None:
        from perplexity_cli.runners.export import _thread_attribute

        record = SimpleNamespace(title="Hello")
        assert _thread_attribute(record, lambda thread: thread.title) == "Hello"

    def test_resolve_ctx_flags_export_json(self) -> None:
        from perplexity_cli.runners.export import _resolve_ctx_flags

        mode = _resolve_ctx_flags({"json": True, "schema": True, "debug": False})
        assert mode.json_mode == "json"
        assert mode.include_schema == "with_schema"

    def test_resolve_ctx_flags_export_human_defaults(self) -> None:
        from perplexity_cli.runners.export import _resolve_ctx_flags

        mode = _resolve_ctx_flags(None)
        assert mode.json_mode == "human"
        assert mode.include_schema == "no_schema"

    def test_resolve_ctx_flags_export_empty_dict(self) -> None:
        from perplexity_cli.runners.export import _resolve_ctx_flags

        mode = _resolve_ctx_flags({})
        assert mode.json_mode == "human"
        assert mode.include_schema == "no_schema"

    def test_handle_known_error_exact_export_failed_line(self, capsys) -> None:
        from perplexity_cli.runners.export import _handle_known_error

        with pytest.raises(SystemExit) as exc_info:
            _handle_known_error(ValueError("bad thing"), output_format="human", logger=Mock())

        assert exc_info.value.code == 1
        assert "\n[ERROR] Export failed: bad thing" in capsys.readouterr().err

    def test_handle_known_error_auth_reauth_exact_lines(self, capsys) -> None:
        from perplexity_cli.runners.export import _handle_known_error
        from perplexity_cli.utils.exceptions import AuthenticationError

        with pytest.raises(SystemExit):
            _handle_known_error(
                AuthenticationError("expired"), output_format="human", logger=Mock()
            )

        err = capsys.readouterr().err
        assert "\nYour token may have expired. Please re-authenticate:" in err
        assert "  perplexity-cli auth" in err

    def test_handle_auth_missing_exact_lines(self, capsys) -> None:
        from perplexity_cli.runners.export import _handle_auth_missing

        with pytest.raises(SystemExit) as exc_info:
            _handle_auth_missing("human", Mock())

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "[ERROR] Not authenticated." in err
        assert "\nPlease authenticate first with: pxcli auth login" in err

    def test_output_json_date_range_and_total(self, capsys) -> None:
        from perplexity_cli.runners.export import (
            ExportDateRange,
            ExportResult,
            _output_json,
        )

        result = ExportResult(
            threads=[{"title": "T1", "created_at": "2025-01-01", "url": "https://x.ai"}],
            output_path=None,
            date_range=ExportDateRange(from_date="2025-01-01", to_date="2025-06-30"),
        )
        _output_json(result, "no_schema")

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["result"]["total"] == 1
        assert envelope["result"]["output_path"] is None
        assert envelope["result"]["date_range"] == {"from": "2025-01-01", "to": "2025-06-30"}
        assert envelope["result"]["threads"][0] == {
            "title": "T1",
            "created_at": "2025-01-01",
            "url": "https://x.ai",
        }

    def test_validate_export_dates_exact_error_lines(self, capsys) -> None:
        from perplexity_cli.runners.export import _validate_export_dates

        with pytest.raises(SystemExit) as exc_info:
            _validate_export_dates("garbage-date", None, output_format="human")

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "[ERROR] Invalid date format:" in err
        assert "Please use YYYY-MM-DD format (e.g., 2025-12-23)" in err

    @patch("perplexity_cli.runners.export.write_threads_csv", autospec=True)
    def test_output_export_results_human_exact_lines(self, mock_write_csv, capsys) -> None:
        from perplexity_cli.runners.export import (
            ExportDateRange,
            ExportResult,
            OutputMode,
            _output_export_results,
        )

        mock_write_csv.return_value = Path("/tmp/threads.csv")
        result = ExportResult(
            threads=[{"title": "T1", "created_at": "2025-01-01", "url": "https://x.ai"}],
            output_path=None,
            date_range=ExportDateRange(from_date=None, to_date=None),
        )
        output_mode = OutputMode(json_mode="human", include_schema="no_schema")

        _output_export_results(result, output_mode, Mock())

        out = capsys.readouterr().out
        assert "\n[OK] Export complete" in out
        assert "[OK] Exported 1 threads" in out
        assert "[OK] Saved to:" in out

    def test_handle_no_threads_exact_error_line(self, capsys) -> None:
        from perplexity_cli.runners.export import _handle_no_threads

        with pytest.raises(SystemExit) as exc_info:
            _handle_no_threads(None, None, output_format="human")

        assert exc_info.value.code == 1
        assert "\n[ERROR] No threads found matching criteria." in capsys.readouterr().err


# ---------------------------------------------------------------------------
# runners/models.py — table rendering internals and exact error lines
# ---------------------------------------------------------------------------


class TestModelRunnerExactStrings:
    """Exact-output mutation killers for runners/models.py."""

    def test_calculate_column_widths_exact(self) -> None:
        from perplexity_cli.runners.models import _calculate_column_widths

        headers = ("MODEL ID", "LABEL", "TIER", "DESCRIPTION")
        rows = [("m1", "Lab", "Pro", "Desc")]
        assert _calculate_column_widths(headers, rows) == [8, 5, 4, 11]

    def test_calculate_column_widths_grows_with_row(self) -> None:
        from perplexity_cli.runners.models import _calculate_column_widths

        headers = ("MODEL ID", "LABEL", "TIER", "DESCRIPTION")
        rows = [("a-very-long-model-id", "Lab", "Pro", "Desc")]
        widths = _calculate_column_widths(headers, rows)
        assert widths[0] == len("a-very-long-model-id")

    def test_format_separator_exact(self) -> None:
        from perplexity_cli.runners.models import _format_separator

        assert _format_separator([8, 5, 4, 11]) == ("--------  -----  ----  -----------")

    def test_format_row_exact_padding(self) -> None:
        from perplexity_cli.runners.models import _format_row

        assert _format_row(("a", "b", "c", "d"), [3, 3, 3, 3]) == "a    b    c    d  "

    def test_build_table_rows_exact_tuple(self) -> None:
        from perplexity_cli.models.model_config import ModelConfigEntry
        from perplexity_cli.runners.models import _build_table_rows

        entry = ModelConfigEntry(
            label="Best",
            description="Auto",
            subscription_tier="pro",
            non_reasoning_model="pplx_pro",
            is_default=True,
        )
        assert _build_table_rows([entry]) == [("pplx_pro", "Best (default)", "Pro", "Auto")]

    def test_render_table_headers_exact_first_line(self) -> None:
        from perplexity_cli.runners.models import _render_table

        rows = [("m1", "Lab", "Pro", "Desc")]
        output = _render_table(rows)
        assert output.split("\n")[0] == "MODEL ID  LABEL  TIER  DESCRIPTION"

    def test_handle_list_error_http_exact_full_line(self, capsys) -> None:
        from perplexity_cli.runners.models import _handle_list_error
        from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError

        with pytest.raises(SystemExit):
            _handle_list_error(
                PerplexityHTTPStatusError("Forbidden"), output_format="human", logger=Mock()
            )
        assert "[ERROR] Failed to fetch models: Forbidden" in capsys.readouterr().err

    def test_handle_list_error_network_exact_full_line(self, capsys) -> None:
        from perplexity_cli.runners.models import _handle_list_error
        from perplexity_cli.utils.exceptions import PerplexityRequestError

        with pytest.raises(SystemExit):
            _handle_list_error(
                PerplexityRequestError("conn refused"), output_format="human", logger=Mock()
            )
        assert "[ERROR] Network error: conn refused" in capsys.readouterr().err

    def test_handle_list_error_unexpected_exact_full_line(self, capsys) -> None:
        from perplexity_cli.runners.models import _handle_list_error

        with pytest.raises(SystemExit):
            _handle_list_error(RuntimeError("kaboom"), output_format="human", logger=Mock())
        assert "[ERROR] Unexpected error: kaboom" in capsys.readouterr().err

    def test_entry_to_dict_exact_keys(self) -> None:
        from perplexity_cli.models.model_config import ModelConfigEntry
        from perplexity_cli.runners.models import _entry_to_dict

        entry = ModelConfigEntry(
            label="L",
            description="D",
            subscription_tier="max",
            non_reasoning_model="m1",
            reasoning_model="m1_think",
            is_default=True,
        )
        assert _entry_to_dict(entry) == {
            "model_id": "m1",
            "label": "L",
            "tier": "max",
            "description": "D",
            "reasoning_model": "m1_think",
            "is_default": True,
        }

    def test_entry_to_dict_none_description_becomes_empty(self) -> None:
        from perplexity_cli.models.model_config import ModelConfigEntry
        from perplexity_cli.runners.models import _entry_to_dict

        entry = ModelConfigEntry(
            label="L",
            description="",
            subscription_tier="pro",
            non_reasoning_model="m1",
        )
        assert _entry_to_dict(entry)["description"] == ""


# ---------------------------------------------------------------------------
# runners/status.py — permission strings, exact text, verification logic
# ---------------------------------------------------------------------------


class TestStatusRunnerExactStrings:
    """Exact-output mutation killers for runners/status.py."""

    def test_status_check_timeout_constant(self) -> None:
        assert DEFAULT_STATUS_CHECK_TIMEOUT == 10

    def test_describe_file_permissions_secure_exact(self, tmp_path) -> None:
        from perplexity_cli.runners.status import _describe_file_permissions

        f = tmp_path / "secure.json"
        f.write_text("{}")
        os.chmod(f, 0o600)
        assert _describe_file_permissions(f, 0o600) == "secure (0o600)"

    def test_describe_file_permissions_insecure_exact_full(self, tmp_path) -> None:
        from perplexity_cli.runners.status import _describe_file_permissions

        f = tmp_path / "insecure.json"
        f.write_text("{}")
        os.chmod(f, 0o644)
        assert _describe_file_permissions(f, 0o600) == "insecure (0o644; expected 0o600)"

    def test_output_status_text_exact_header_lines(self, capsys) -> None:
        from perplexity_cli.runners.status import _output_status_text

        tm = Mock()
        tm.token_path = Mock()
        tm.token_path.stat.return_value = Mock(st_mtime=1700000000.0)
        _output_status_text("abcdef", {"c": "v"}, (5, None, False), tm=tm)

        out = capsys.readouterr().out
        assert "Perplexity CLI Status" in out
        assert "=" * 40 in out
        assert "Status: [OK] Authenticated" in out
        assert "Token length: 6 characters" in out
        assert "Cookies: 1 stored" in out

    def test_output_status_text_live_verify_hint_exact(self, capsys) -> None:
        from perplexity_cli.runners.status import _output_status_text

        tm = Mock()
        tm.token_path = Mock()
        tm.token_path.stat.return_value = Mock(st_mtime=1700000000.0)
        _output_status_text("tok", {}, (5, None, False), tm=tm)

        out = capsys.readouterr().out
        assert "\n[INFO] Live verification not run" in out
        assert "Use 'pxcli auth status --verify' to test the current token against the API." in out

    def test_handle_no_token_exact_status_error_line(self, capsys) -> None:
        from perplexity_cli.runners.status import _handle_no_token

        tm = Mock()
        tm.token_path = Mock(__str__=Mock(return_value="/tmp/token.json"))
        _handle_no_token(output_format="human", tm=tm, show_auth_hint="show")

        out = capsys.readouterr().out
        assert "Status: [ERROR] Not authenticated" in out
        assert "\nAuthenticate with: pxcli auth login" in out

    @patch("perplexity_cli.runners.status.get_feature_config")
    @patch("perplexity_cli.runners.status.ThreadCacheManager")
    @patch("perplexity_cli.runners.status.TokenManager")
    def test_doctor_security_text_exact_storage_backend(
        self, mock_tm_class, mock_cm_class, mock_feature_config, capsys
    ) -> None:
        from perplexity_cli.runners.status import run_doctor_security_command

        mock_tm = Mock()
        mock_tm.token_path = Mock(__str__=Mock(return_value="/tmp/t.json"))
        mock_tm.token_path.exists.return_value = False
        mock_tm.SECURE_PERMISSIONS = 0o600
        mock_tm_class.return_value = mock_tm

        mock_cm = Mock()
        mock_cm.cache_path = Mock(__str__=Mock(return_value="/tmp/c.json"))
        mock_cm.cache_path.exists.return_value = False
        mock_cm.SECURE_PERMISSIONS = 0o600
        mock_cm_class.return_value = mock_cm

        mock_feature_config.return_value = Mock(save_cookies=False)

        run_doctor_security_command(output_format="human")

        out = capsys.readouterr().out
        assert "Perplexity CLI Security" in out
        assert "Storage backend: machine-bound encrypted file storage" in out
        assert "Cookie storage enabled: False" in out

    @patch("perplexity_cli.runners.status.get_feature_config")
    @patch("perplexity_cli.runners.status.ThreadCacheManager")
    @patch("perplexity_cli.runners.status.TokenManager")
    def test_doctor_security_json_storage_backend_constant(
        self, mock_tm_class, mock_cm_class, mock_feature_config, capsys
    ) -> None:
        from perplexity_cli.runners.status import run_doctor_security_command

        mock_tm = Mock()
        mock_tm.token_path = Mock(__str__=Mock(return_value="/tmp/t.json"))
        mock_tm.token_path.exists.return_value = False
        mock_tm.SECURE_PERMISSIONS = 0o600
        mock_tm_class.return_value = mock_tm

        mock_cm = Mock()
        mock_cm.cache_path = Mock(__str__=Mock(return_value="/tmp/c.json"))
        mock_cm.cache_path.exists.return_value = False
        mock_cm.SECURE_PERMISSIONS = 0o600
        mock_cm_class.return_value = mock_cm

        mock_feature_config.return_value = Mock(save_cookies=False)

        run_doctor_security_command(output_format="json")

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["result"]["storage_backend"] == "machine-bound encrypted file storage"

    @patch("perplexity_cli.runners.status.PerplexityAPI")
    def test_verify_token_none_answer_returns_false(self, mock_api_class) -> None:
        from perplexity_cli.runners.status import _verify_token

        mock_api = Mock()
        mock_api.get_complete_answer.return_value = None
        mock_api_class.return_value.__enter__ = Mock(return_value=mock_api)
        mock_api_class.return_value.__exit__ = Mock(return_value=False)

        assert _verify_token("tok", {}, Mock()) is False

    @patch("perplexity_cli.runners.status.PerplexityAPI")
    def test_verify_token_uses_status_check_timeout(self, mock_api_class) -> None:
        from perplexity_cli.runners.status import _verify_token

        mock_api = Mock()
        mock_api.get_complete_answer.return_value = Mock(text="ok")
        mock_api_class.return_value.__enter__ = Mock(return_value=mock_api)
        mock_api_class.return_value.__exit__ = Mock(return_value=False)

        _verify_token("tok", {"c": "v"}, Mock())

        mock_api_class.assert_called_once_with(token="tok", cookies={"c": "v"}, timeout=10)

    @patch("perplexity_cli.runners.status.TokenManager")
    def test_run_status_insecure_perms_exact_fix_line(self, mock_tm_class, capsys) -> None:
        from perplexity_cli.runners.status import run_status_command
        from perplexity_cli.utils.exceptions import AuthenticationError

        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.load_token.side_effect = AuthenticationError("insecure")
        mock_tm.token_path = Mock(__str__=Mock(return_value="/tmp/t.json"))
        mock_tm_class.return_value = mock_tm

        run_status_command(verify="skip")

        out = capsys.readouterr().out
        assert "Status: [INFO] Token file has insecure permissions" in out
        assert "Error: insecure" in out
        assert "\nFix with: chmod 0600 /tmp/t.json" in out


# ---------------------------------------------------------------------------
# auth/utils.py — exact messages and return tuples
# ---------------------------------------------------------------------------


class TestAuthUtilsExact:
    """Exact-output mutation killers for auth/utils.py."""

    def test_load_or_prompt_token_auth_error_exact_messages(self, capsys) -> None:
        from perplexity_cli.auth.utils import load_or_prompt_token
        from perplexity_cli.utils.exceptions import AuthenticationError

        tm = Mock()
        tm.load_token.side_effect = AuthenticationError("bad state")

        with pytest.raises(SystemExit) as exc_info:
            load_or_prompt_token(tm, Mock(), command_context="query")

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "[ERROR] Authentication error: bad state" in err
        assert "\nPlease authenticate again with: pxcli auth login" in err

    def test_load_or_prompt_token_empty_token_exact_messages(self, capsys) -> None:
        from perplexity_cli.auth.utils import load_or_prompt_token

        tm = Mock()
        tm.load_token.return_value = ("", None)

        with pytest.raises(SystemExit) as exc_info:
            load_or_prompt_token(tm, Mock(), command_context="query")

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "[ERROR] Not authenticated." in err
        assert "\nPlease authenticate first with: pxcli auth login" in err

    def test_load_or_prompt_token_success_returns_tuple(self) -> None:
        from perplexity_cli.auth.utils import load_or_prompt_token

        tm = Mock()
        tm.load_token.return_value = ("tok-1", {"cf": "v"})

        assert load_or_prompt_token(tm, Mock()) == ("tok-1", {"cf": "v"})

    def test_load_token_optional_auth_error_returns_none_tuple(self) -> None:
        from perplexity_cli.auth.utils import load_token_optional
        from perplexity_cli.utils.exceptions import AuthenticationError

        tm = Mock()
        tm.load_token.side_effect = AuthenticationError("unusable")

        assert load_token_optional(tm, Mock()) == (None, None)

    def test_load_token_optional_success_returns_values(self) -> None:
        from perplexity_cli.auth.utils import load_token_optional

        tm = Mock()
        tm.load_token.return_value = ("tok-2", {"a": "b"})

        assert load_token_optional(tm, Mock()) == ("tok-2", {"a": "b"})


# ---------------------------------------------------------------------------
# auth/models.py — validation boundaries and exact messages
# ---------------------------------------------------------------------------


class TestAuthModelsExact:
    """Boundary and exact-message mutation killers for auth/models.py."""

    def test_auth_context_default_cookies_none(self) -> None:
        from perplexity_cli.auth.models import AuthContext

        assert AuthContext(token="t").cookies is None

    def test_token_format_version_zero_rejected(self) -> None:
        from perplexity_cli.auth.models import TokenFormat

        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            TokenFormat(token="abc", version=0)

    def test_token_format_version_three_rejected(self) -> None:
        from perplexity_cli.auth.models import TokenFormat

        with pytest.raises(ValidationError, match="less than or equal to 2"):
            TokenFormat(token="abc", version=3)

    def test_token_format_whitespace_token_message(self) -> None:
        from perplexity_cli.auth.models import TokenFormat

        with pytest.raises(ValidationError, match="Token cannot be whitespace-only"):
            TokenFormat(token="   ")

    def test_token_format_future_created_at_message(self) -> None:
        from perplexity_cli.auth.models import TokenFormat

        future = datetime.now() + timedelta(days=1)
        with pytest.raises(ValidationError, match="created_at cannot be in the future"):
            TokenFormat(token="abc", created_at=future)

    def test_token_format_serializes_created_at_isoformat(self) -> None:
        from perplexity_cli.auth.models import TokenFormat

        created = datetime(2025, 1, 2, 3, 4, 5)
        record = TokenFormat(token="abc", created_at=created)
        assert record.model_dump(mode="json")["created_at"] == created.isoformat()

    def test_cookie_data_whitespace_name_message(self) -> None:
        from perplexity_cli.auth.models import CookieData

        with pytest.raises(ValidationError, match="Cookie name cannot be empty"):
            CookieData(name="   ")

    def test_cookie_data_default_value_empty(self) -> None:
        from perplexity_cli.auth.models import CookieData

        assert CookieData(name="cf").value == ""

    def test_token_metadata_negative_age_message(self) -> None:
        from perplexity_cli.auth.models import TokenMetadata

        with pytest.raises(ValidationError, match="age_days cannot be negative"):
            TokenMetadata(age_days=-1)

    def test_token_metadata_defaults_exact(self) -> None:
        from perplexity_cli.auth.models import TokenMetadata

        meta = TokenMetadata()
        assert meta.is_encrypted is True
        assert meta.has_cookies is False
        assert meta.age_days is None
        assert meta.version == 2
        assert meta.created_at is None


# ---------------------------------------------------------------------------
# auth/token_manager.py — constants, pure helpers, age boundary
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_token_file() -> Path:
    """Provide a temporary token file path."""
    import tempfile

    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir) / "token.json"


@pytest.fixture
def token_manager(temp_token_file: Path, monkeypatch) -> object:
    """Create a TokenManager routed at a temporary token path."""
    from perplexity_cli.auth.token_manager import TokenManager

    mock_paths = type("MockPaths", (), {"token_path": temp_token_file})()
    monkeypatch.setattr(
        "perplexity_cli.auth.token_manager.get_config_paths",
        lambda: mock_paths,
    )
    manager = TokenManager()
    manager.logger = Mock()
    return manager


class TestTokenManagerExact:
    """Constant and helper mutation killers for auth/token_manager.py."""

    def test_constants_values(self) -> None:
        from perplexity_cli.auth.token_manager import (
            _DEFAULT_TOKEN_VERSION,
            _MALFORMED_COOKIES_ERROR,
            _TOKEN_FORMAT_VERSION,
            TOKEN_AGE_WARNING_DAYS,
        )

        assert TOKEN_AGE_WARNING_DAYS == 30
        assert _TOKEN_FORMAT_VERSION == 2
        assert _DEFAULT_TOKEN_VERSION == 1
        assert _MALFORMED_COOKIES_ERROR == "Token file contains malformed cookies data"

    def test_secure_permissions_constant(self) -> None:
        from perplexity_cli.auth.token_manager import TokenManager

        assert TokenManager.SECURE_PERMISSIONS == 0o600

    def test_extract_created_at_string(self) -> None:
        from perplexity_cli.auth.token_manager import _extract_created_at

        assert _extract_created_at({"created_at": "2025-01-01T00:00:00"}) == "2025-01-01T00:00:00"

    def test_extract_created_at_non_string(self) -> None:
        from perplexity_cli.auth.token_manager import _extract_created_at

        assert _extract_created_at({"created_at": 123}) is None
        assert _extract_created_at({}) is None

    def test_extract_token_string_missing_message(self) -> None:
        from perplexity_cli.auth.token_manager import _extract_token_string
        from perplexity_cli.utils.exceptions import AuthenticationError

        with pytest.raises(AuthenticationError, match="Token file is missing encrypted token data"):
            _extract_token_string({})

    def test_extract_token_string_empty_message(self) -> None:
        from perplexity_cli.auth.token_manager import _extract_token_string
        from perplexity_cli.utils.exceptions import AuthenticationError

        with pytest.raises(AuthenticationError, match="Token file is missing encrypted token data"):
            _extract_token_string({"token": ""})

    def test_extract_token_string_returns_value(self) -> None:
        from perplexity_cli.auth.token_manager import _extract_token_string

        assert _extract_token_string({"token": "abc"}) == "abc"

    def test_extract_version_default_when_missing(self) -> None:
        from perplexity_cli.auth.token_manager import _extract_version

        assert _extract_version({}) == 2

    def test_extract_version_non_int_falls_back(self) -> None:
        from perplexity_cli.auth.token_manager import _extract_version

        assert _extract_version({"version": "two"}) == 1

    def test_extract_version_explicit_int(self) -> None:
        from perplexity_cli.auth.token_manager import _extract_version

        assert _extract_version({"version": 2}) == 2

    def test_validate_cookie_types_non_dict_message(self) -> None:
        from perplexity_cli.auth.token_manager import TokenManager
        from perplexity_cli.utils.exceptions import AuthenticationError

        with pytest.raises(AuthenticationError, match="malformed cookies data"):
            TokenManager._validate_cookie_types(["not", "a", "dict"])

    def test_validate_cookie_types_non_string_value_message(self) -> None:
        from perplexity_cli.auth.token_manager import TokenManager
        from perplexity_cli.utils.exceptions import AuthenticationError

        with pytest.raises(AuthenticationError, match="malformed cookies data"):
            TokenManager._validate_cookie_types({"key": 123})

    def test_check_token_age_boundary_30_no_warning(self, token_manager) -> None:
        created_at = (datetime.now() - timedelta(days=30, hours=1)).isoformat()
        token_manager._check_token_age(created_at)
        token_manager.logger.warning.assert_not_called()
        token_manager.logger.debug.assert_called_once()

    def test_check_token_age_boundary_31_warning(self, token_manager) -> None:
        created_at = (datetime.now() - timedelta(days=31, hours=1)).isoformat()
        token_manager._check_token_age(created_at)
        token_manager.logger.warning.assert_called_once()

    def test_log_version_without_cookies_v2_message(self, token_manager) -> None:
        token_manager._log_version_without_cookies(2)
        token_manager.logger.debug.assert_called_once_with(
            "Token is v2 format but no cookies stored"
        )

    def test_log_version_without_cookies_v1_message(self, token_manager) -> None:
        token_manager._log_version_without_cookies(1)
        token_manager.logger.debug.assert_called_once_with("Token is v%s format (no cookies)", 1)

    def test_extract_encrypted_cookies_v1_returns_none(self, token_manager) -> None:
        assert token_manager._extract_encrypted_cookies({"cookies": "x"}, version=1) is None

    def test_extract_encrypted_cookies_v2_missing_key_returns_none(self, token_manager) -> None:
        assert token_manager._extract_encrypted_cookies({}, version=2) is None

    def test_extract_encrypted_cookies_v2_returns_string(self, token_manager) -> None:
        assert token_manager._extract_encrypted_cookies({"cookies": "enc"}, version=2) == "enc"


# ---------------------------------------------------------------------------
# auth/oauth_handler.py — token extraction, command building, defaults
# ---------------------------------------------------------------------------


class TestOauthHandlerExact:
    """Exact-output mutation killers for auth/oauth_handler.py."""

    def test_chrome_debug_constants(self) -> None:
        assert DEFAULT_CHROME_DEBUG_PORT == 9222
        assert DEFAULT_AUTH_TIMEOUT == 120
        assert DEFAULT_AUTH_POLL_INTERVAL == 2.0

    def test_extract_token_from_local_storage_exact_key(self) -> None:
        from perplexity_cli.auth.oauth_handler import _extract_token_from_local_storage

        result = _extract_token_from_local_storage({"pplx-next-auth-session": '{"a":1}'})
        assert result == '{"a": 1}'

    def test_extract_token_from_local_storage_missing_key(self) -> None:
        from perplexity_cli.auth.oauth_handler import _extract_token_from_local_storage

        assert _extract_token_from_local_storage({}) is None

    def test_extract_token_from_local_storage_invalid_json(self) -> None:
        from perplexity_cli.auth.oauth_handler import _extract_token_from_local_storage

        assert _extract_token_from_local_storage({"pplx-next-auth-session": "not-json"}) is None

    def test_extract_token_from_cookies_secure_preferred(self) -> None:
        from perplexity_cli.auth.oauth_handler import _extract_token_from_cookies

        cookies = {
            "next-auth.session-token": "plain",
            "__Secure-next-auth.session-token": "secure",
        }
        assert _extract_token_from_cookies(cookies) == "secure"

    def test_extract_token_from_cookies_plain_fallback(self) -> None:
        from perplexity_cli.auth.oauth_handler import _extract_token_from_cookies

        assert _extract_token_from_cookies({"next-auth.session-token": "plain"}) == "plain"

    def test_extract_token_from_cookies_none_when_absent(self) -> None:
        from perplexity_cli.auth.oauth_handler import _extract_token_from_cookies

        assert _extract_token_from_cookies({"unrelated": "x"}) is None

    def test_extract_token_combines_cookie_dict(self) -> None:
        from perplexity_cli.auth.oauth_handler import _extract_token

        cookies = [{"name": "a", "value": "1"}, {"name": "b", "value": "2"}]
        token, cookie_dict = _extract_token(cookies, {})
        assert token is None
        assert cookie_dict == {"a": "1", "b": "2"}

    def test_find_page_target_exact_message(self) -> None:
        from perplexity_cli.auth.oauth_handler import ChromeDevToolsClient
        from perplexity_cli.utils.exceptions import AuthenticationError

        with pytest.raises(AuthenticationError, match="No page target found in Chrome"):
            ChromeDevToolsClient._find_page_target([{"type": "background"}])

    def test_find_page_target_returns_page(self) -> None:
        from perplexity_cli.auth.oauth_handler import ChromeDevToolsClient

        page = {"type": "page", "id": "1"}
        assert ChromeDevToolsClient._find_page_target([{"type": "background"}, page]) == page

    def test_build_command_without_params(self) -> None:
        from perplexity_cli.auth.oauth_handler import ChromeDevToolsClient

        client = ChromeDevToolsClient(9222)
        client.message_id = 5
        assert client._build_command("Page.enable", None) == {"id": 5, "method": "Page.enable"}

    def test_build_command_with_params(self) -> None:
        from perplexity_cli.auth.oauth_handler import ChromeDevToolsClient

        client = ChromeDevToolsClient(9222)
        client.message_id = 7
        assert client._build_command("Page.navigate", {"url": "http://x"}) == {
            "id": 7,
            "method": "Page.navigate",
            "params": {"url": "http://x"},
        }

    def test_resolve_auth_defaults_explicit_passthrough(self) -> None:
        from perplexity_cli.auth.oauth_handler import _resolve_auth_defaults

        assert _resolve_auth_defaults("http://x", 1234, 99, 5.0) == ("http://x", 1234, 99, 5.0)

    def test_resolve_auth_defaults_numeric_defaults(self) -> None:
        from perplexity_cli.auth.oauth_handler import _resolve_auth_defaults

        _url, port, timeout, poll = _resolve_auth_defaults("http://x", None, None, None)
        assert port == 9222
        assert timeout == 120
        assert poll == 2.0

    def test_message_id_starts_at_zero(self) -> None:
        from perplexity_cli.auth.oauth_handler import ChromeDevToolsClient

        assert ChromeDevToolsClient(9222).message_id == 0
