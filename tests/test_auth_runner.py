"""Tests for auth command routing."""

from unittest.mock import Mock, patch

import pytest

from perplexity_cli.cli import auth_login, auth_logout, auth_status
from perplexity_cli.runners.auth import (
    _AuthOutputOptions,
    _handle_auth_os_config_error,
    _handle_auth_success,
    _handle_auth_timeout_error,
    _print_auth_troubleshooting,
    _resolve_auth_output_options,
    _resolve_ctx_flags,
    _resolve_logout_ctx,
)


class TestAuthLogin:
    """Test auth login command routing."""

    @patch("perplexity_cli.runners.auth.TokenManager")
    @patch("perplexity_cli.runners.auth.authenticate_sync")
    def test_auth_login_invokes_run_auth_command(self, mock_auth, mock_tm_class, runner):
        mock_cookies = {"__cf_bm": "test"}
        mock_auth.return_value = ("token-abc", mock_cookies)
        mock_tm = Mock()
        mock_tm.token_path = "/path/to/token.json"
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(auth_login)

        assert result.exit_code == 0
        assert "Authentication successful" in result.output

    @patch("perplexity_cli.runners.auth.TokenManager")
    @patch("perplexity_cli.runners.auth.authenticate_sync")
    def test_auth_login_custom_port(self, mock_auth, mock_tm_class, runner):
        mock_auth.return_value = ("token-abc", {})
        mock_tm = Mock()
        mock_tm.token_path = "/path/to/token.json"
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(auth_login, ["--port", "9223"])

        assert result.exit_code == 0
        mock_auth.assert_called_once_with(port=9223)

    @patch("perplexity_cli.runners.auth.TokenManager")
    @patch("perplexity_cli.runners.auth.authenticate_sync")
    def test_auth_login_default_port(self, mock_auth, mock_tm_class, runner):
        from perplexity_cli.config.defaults import DEFAULT_CHROME_DEBUG_PORT

        mock_auth.return_value = ("token-abc", {})
        mock_tm = Mock()
        mock_tm.token_path = "/path/to/token.json"
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(auth_login)

        assert result.exit_code == 0
        mock_auth.assert_called_once_with(port=DEFAULT_CHROME_DEBUG_PORT)


class TestAuthLogout:
    """Test auth logout command routing."""

    @patch("perplexity_cli.runners.auth.TokenManager")
    def test_auth_logout_invokes_run_logout_command(self, mock_tm_class, runner):
        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.clear_token.return_value = None
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(auth_logout)

        assert result.exit_code == 0
        assert "Logged out successfully" in result.output
        mock_tm.clear_token.assert_called_once()


class TestAuthStatus:
    """Test auth status command routing."""

    @patch("perplexity_cli.runners.status.TokenManager")
    def test_auth_status_invokes_run_status_command(self, mock_tm_class, runner):
        mock_tm = Mock()
        mock_tm.token_exists.return_value = False
        mock_tm_class.return_value = mock_tm

        result = runner.invoke(auth_status)

        assert result.exit_code == 0
        assert "Not authenticated" in result.output

    @patch("perplexity_cli.runners.status.TokenManager")
    @patch("perplexity_cli.runners.status.PerplexityAPI")
    def test_auth_status_verify(self, mock_api_class, mock_tm_class, runner):
        from pathlib import Path
        from unittest.mock import MagicMock

        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.load_token.return_value = ("test-token", {"csrftoken": "abc"})
        mock_tm.token_path = Path("/path/to/token.json")
        mock_tm_class.return_value = mock_tm

        mock_api = MagicMock()
        mock_api.__enter__ = Mock(return_value=mock_api)
        mock_api.__exit__ = Mock(return_value=False)
        mock_answer = Mock()
        mock_answer.text = "test"
        mock_answer.references = []
        mock_api.get_complete_answer.return_value = mock_answer
        mock_api_class.return_value = mock_api

        result = runner.invoke(auth_status, ["--verify"])

        assert result.exit_code == 0
        assert "Token is valid and working" in result.output


class TestAuthRunnerMutationKillers:
    """Mutation-killing tests for auth runner edge cases."""

    @patch("perplexity_cli.runners.auth.get_save_cookies_enabled", return_value=False)
    @patch("perplexity_cli.runners.auth.TokenManager")
    @patch("perplexity_cli.runners.auth.authenticate_sync")
    def test_auth_success_cookies_disabled_message(
        self, mock_auth, mock_tm_class, mock_cookies_enabled, capsys
    ):
        from perplexity_cli.runners.auth import run_auth_command

        mock_auth.return_value = ("tok-123", {"cf": "val"})
        mock_tm = Mock()
        mock_tm.token_path = "/tmp/token.json"
        mock_tm_class.return_value = mock_tm

        run_auth_command({"json": False, "schema": False, "debug": False}, port=9222)

        captured = capsys.readouterr()
        assert "[INFO] Cookies not saved (disabled in config)" in captured.out
        assert "pxcli config set save_cookies true" in captured.out

    @patch("perplexity_cli.runners.auth.get_save_cookies_enabled", return_value=True)
    @patch("perplexity_cli.runners.auth.TokenManager")
    @patch("perplexity_cli.runners.auth.authenticate_sync")
    def test_auth_success_cookies_enabled_message(
        self, mock_auth, mock_tm_class, mock_cookies_enabled, capsys
    ):
        from perplexity_cli.runners.auth import run_auth_command

        mock_auth.return_value = ("tok-123", {"a": "1", "b": "2"})
        mock_tm = Mock()
        mock_tm.token_path = "/tmp/token.json"
        mock_tm_class.return_value = mock_tm

        run_auth_command({"json": False, "schema": False, "debug": False}, port=9222)

        captured = capsys.readouterr()
        assert "2 cookies saved (including Cloudflare cookies)" in captured.out

    @patch("perplexity_cli.runners.auth.TokenManager")
    @patch("perplexity_cli.runners.auth.authenticate_sync")
    def test_auth_timeout_error_shows_troubleshooting(self, mock_auth, mock_tm_class, capsys):
        from perplexity_cli.runners.auth import run_auth_command

        mock_auth.side_effect = TimeoutError("connection timed out")
        mock_tm_class.return_value = Mock()

        with pytest.raises(SystemExit) as exc_info:
            run_auth_command({"json": False, "schema": False, "debug": False}, port=9222)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "[ERROR] Authentication failed: connection timed out" in captured.err
        assert "Troubleshooting:" in captured.err
        assert "--remote-debugging-port=9222" in captured.err

    @patch("perplexity_cli.runners.auth.TokenManager")
    @patch("perplexity_cli.runners.auth.authenticate_sync")
    def test_auth_os_error_shows_unexpected(self, mock_auth, mock_tm_class, capsys):
        from perplexity_cli.runners.auth import run_auth_command

        mock_auth.side_effect = OSError("permission denied")
        mock_tm_class.return_value = Mock()

        with patch("perplexity_cli.runners.auth.handle_unexpected_cli_error") as mock_handler:
            run_auth_command({"json": False, "schema": False, "debug": False}, port=9222)

        mock_handler.assert_called_once()

    @patch("perplexity_cli.runners.auth.TokenManager")
    @patch("perplexity_cli.runners.auth.authenticate_sync")
    def test_auth_json_mode_no_human_output(self, mock_auth, mock_tm_class, capsys):
        from perplexity_cli.runners.auth import run_auth_command

        mock_auth.return_value = ("tok", {})
        mock_tm = Mock()
        mock_tm.token_path = "/tmp/token.json"
        mock_tm_class.return_value = mock_tm

        run_auth_command({"json": True, "schema": False, "debug": False}, port=9222)

        captured = capsys.readouterr()
        assert "Authenticating with Perplexity.ai" not in captured.out
        assert "Make sure Chrome is running" not in captured.out

    @patch("perplexity_cli.runners.auth.TokenManager")
    def test_logout_no_credentials_message(self, mock_tm_class, capsys):
        from perplexity_cli.runners.auth import run_logout_command

        mock_tm = Mock()
        mock_tm.token_exists.return_value = False
        mock_tm_class.return_value = mock_tm

        run_logout_command(json_mode=False)

        captured = capsys.readouterr()
        assert "No stored credentials found." in captured.out

    @patch("perplexity_cli.runners.auth.TokenManager")
    def test_logout_os_error_handled(self, mock_tm_class, capsys):
        from perplexity_cli.runners.auth import run_logout_command

        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.clear_token.side_effect = OSError("disk error")
        mock_tm_class.return_value = mock_tm

        with patch("perplexity_cli.runners.auth.handle_unexpected_cli_error") as mock_handler:
            run_logout_command(json_mode=False)

        mock_handler.assert_called_once()

    @patch("perplexity_cli.runners.auth.TokenManager")
    def test_logout_json_mode_credentials_existed_true(self, mock_tm_class, capsys):
        import json

        from perplexity_cli.runners.auth import run_logout_command

        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.clear_token.return_value = None
        mock_tm_class.return_value = mock_tm

        run_logout_command(json_mode=True)

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["result"]["credentials_existed"] is True

    @patch("perplexity_cli.runners.auth.TokenManager")
    def test_logout_json_mode_credentials_existed_false(self, mock_tm_class, capsys):
        import json

        from perplexity_cli.runners.auth import run_logout_command

        mock_tm = Mock()
        mock_tm.token_exists.return_value = False
        mock_tm_class.return_value = mock_tm

        run_logout_command(json_mode=True)

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["result"]["credentials_existed"] is False

    @patch("perplexity_cli.runners.auth.TokenManager")
    @patch("perplexity_cli.runners.auth.authenticate_sync")
    def test_auth_success_json_envelope_cookies_count(self, mock_auth, mock_tm_class, capsys):
        import json

        from perplexity_cli.runners.auth import run_auth_command

        mock_auth.return_value = ("tok", {"a": "1", "b": "2", "c": "3"})
        mock_tm = Mock()
        mock_tm.token_path = "/tmp/token.json"
        mock_tm_class.return_value = mock_tm

        run_auth_command({"json": True, "schema": False, "debug": False}, port=9222)

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["result"]["cookies_stored"] == 3

    @patch("perplexity_cli.runners.auth.TokenManager")
    @patch("perplexity_cli.runners.auth.authenticate_sync")
    def test_auth_keyboard_interrupt_no_exit(self, mock_auth, mock_tm_class, capsys):
        from perplexity_cli.runners.auth import run_auth_command

        mock_auth.side_effect = KeyboardInterrupt()
        mock_tm_class.return_value = Mock()

        run_auth_command({"json": False, "schema": False, "debug": False}, port=9222)

        captured = capsys.readouterr()
        assert "ERROR" not in captured.err

    def test_resolve_ctx_flags_maps_all_output_flags(self):
        """Authentication flags map independently to JSON, schema and debug."""
        assert _resolve_ctx_flags(None) == (False, False, False)
        assert _resolve_ctx_flags({}) == (False, False, False)
        assert _resolve_ctx_flags({"json": True, "schema": True, "debug": True}) == (
            True,
            True,
            True,
        )
        assert _resolve_ctx_flags("invalid") == (False, False, False)

    def test_resolve_auth_output_options_maps_typed_values(self):
        """Typed authentication output options preserve all boolean flags."""
        assert _resolve_auth_output_options((False, False, False)) == _AuthOutputOptions(
            "human", "no_schema", "normal"
        )
        assert _resolve_auth_output_options((True, True, True)) == _AuthOutputOptions(
            "json", "with_schema", "debug"
        )

    def test_print_auth_troubleshooting_includes_all_steps(self, capsys):
        """Troubleshooting output includes actionable connection values."""
        _print_auth_troubleshooting(9222, "https://www.perplexity.ai")

        output = capsys.readouterr().err
        assert (
            "--remote-debugging-port=9222" in output,
            "https://www.perplexity.ai" in output,
        ) == (
            True,
            True,
        )

    def test_auth_timeout_json_routes_to_error_handler(self):
        """JSON timeout errors use the shared JSON error handler."""
        error = TimeoutError("timed out")
        with patch("perplexity_cli.runners.auth.handle_error", side_effect=SystemExit(1)) as handle:
            with pytest.raises(SystemExit):
                _handle_auth_timeout_error(error, "json", 9222, "https://perplexity.ai")

        handle.assert_called_once_with(error, "pxcli auth login", output_format="json")

    def test_auth_os_config_json_routes_to_error_handler(self):
        """JSON OS/configuration errors use the shared JSON error handler."""
        error = OSError("permission denied")
        with patch("perplexity_cli.runners.auth.handle_error", side_effect=SystemExit(1)) as handle:
            with pytest.raises(SystemExit):
                _handle_auth_os_config_error(error, "json", "debug")

        handle.assert_called_once_with(error, "pxcli auth login", output_format="json")

    def test_auth_os_config_human_passes_debug_mode(self):
        """Human OS/configuration errors preserve the requested debug mode."""
        error = OSError("permission denied")
        with patch("perplexity_cli.runners.auth.handle_unexpected_cli_error") as handle:
            _handle_auth_os_config_error(error, "human", "debug")

        handle.assert_called_once()
        assert handle.call_args.kwargs["debug_mode"] == "debug"
        assert handle.call_args.kwargs["message_tuple"][2] is False

    def test_handle_auth_success_saves_token_and_emits_json_schema(self):
        """Successful JSON authentication saves credentials and forwards schema mode."""
        mock_manager = Mock()
        mock_manager.token_path = "/tmp/token.json"
        with (
            patch("perplexity_cli.runners.auth.TokenManager", return_value=mock_manager),
            patch("perplexity_cli.runners.auth.write_envelope") as write,
        ):
            _handle_auth_success("token", {"cookie": "value"}, "json", "with_schema")

        mock_manager.save_token.assert_called_once_with("token", cookies={"cookie": "value"})
        write.assert_called_once()
        assert write.call_args.kwargs["include_schema"] == "with_schema"

    def test_resolve_logout_ctx_uses_context_schema_and_json(self):
        """Logout resolves omitted flags from the current Click context."""
        with patch(
            "perplexity_cli.runners.auth._ctx_to_dict",
            return_value={"json": True, "schema": True},
        ):
            assert _resolve_logout_ctx(None) == ("json", "with_schema")

    def test_auth_success_logs_only_redacted_token_path(self):
        """Credential persistence logs the redacted path, never credential values."""
        manager = Mock(token_path="/secret/token.json")
        logger = Mock()
        with (
            patch("perplexity_cli.runners.auth.TokenManager", return_value=manager),
            patch("perplexity_cli.runners.auth.get_logger", return_value=logger),
            patch("perplexity_cli.runners.auth.redact_path", return_value="<redacted>"),
            patch("perplexity_cli.runners.auth.get_save_cookies_enabled", return_value=True),
        ):
            _handle_auth_success("sensitive-token", {"session": "secret"}, "human", "no_schema")

        manager.save_token.assert_called_once_with("sensitive-token", cookies={"session": "secret"})
        logger.info.assert_called_once_with("Token and cookies saved to %s", "<redacted>")

    def test_auth_json_timeout_preserves_json_error_routing(self):
        """Authentication timeouts retain JSON mode through the execution layer."""
        error = TimeoutError("timed out")
        with (
            patch("perplexity_cli.runners.auth.authenticate_sync", side_effect=error),
            patch("perplexity_cli.runners.auth.handle_error", side_effect=SystemExit(1)) as handle,
            pytest.raises(SystemExit),
        ):
            from perplexity_cli.runners.auth import run_auth_command

            run_auth_command({"json": True}, port=9222)

        handle.assert_called_once_with(error, "pxcli auth login", output_format="json")

    def test_logout_json_os_error_uses_json_error_handler(self):
        """Credential deletion failures are emitted as JSON in JSON mode."""
        manager = Mock()
        manager.token_exists.return_value = True
        error = OSError("disk failure")
        manager.clear_token.side_effect = error
        with (
            patch("perplexity_cli.runners.auth.TokenManager", return_value=manager),
            patch("perplexity_cli.runners.auth.handle_error", side_effect=SystemExit(1)) as handle,
            pytest.raises(SystemExit),
        ):
            from perplexity_cli.runners.auth import run_logout_command

            run_logout_command(json_mode=True)

        handle.assert_called_once_with(error, "pxcli auth logout", output_format="json")
