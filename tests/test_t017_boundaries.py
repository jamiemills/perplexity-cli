"""Behavioural boundary tests for the authentication command runner."""

import json
from unittest.mock import Mock, patch

import click
import pytest

from perplexity_cli.runners.auth import (
    _ctx_to_dict,
    _execute_auth,
    _handle_auth_os_config_error,
    _handle_auth_success,
    _handle_auth_timeout_error,
    _logout_emit,
    _print_auth_troubleshooting,
    _resolve_ctx_flags,
    _resolve_logout_ctx,
    run_auth_command,
    run_logout_command,
)


class _DefaultSensitiveDict(dict[str, object]):
    """Test mapping that exposes the default supplied to ``dict.get``."""

    def get(self, key: str, default: object = None) -> object:
        """Return a truthy value only when the caller supplies ``None``."""
        if key in {"json", "schema", "debug"} and default is None:
            return True
        return super().get(key, default)


def test_context_conversion_preserves_click_mapping() -> None:
    """Context dictionaries reach flag resolution and invalid objects do not."""
    assert _ctx_to_dict() == {}
    with click.Context(click.Command("auth"), obj={"json": True}) as context:
        assert _ctx_to_dict() == context.obj
    with click.Context(click.Command("auth"), obj=["not", "a", "mapping"]):
        assert _ctx_to_dict() == {}


def test_context_conversion_requests_silent_click_context() -> None:
    """Context lookup suppresses the no-active-context Click failure."""
    with patch(
        "perplexity_cli.runners.auth.click.get_current_context", return_value=None
    ) as get_context:
        assert _ctx_to_dict() == {}
    get_context.assert_called_once_with(silent=True)


def test_context_flags_use_each_context_value() -> None:
    """JSON, schema and debug flags are independently resolved."""
    assert _resolve_ctx_flags({}) == (False, False, False)
    assert _resolve_ctx_flags({"json": True, "schema": False, "debug": True}) == (
        True,
        False,
        True,
    )
    assert _resolve_ctx_flags({"json": False, "schema": True, "debug": False}) == (
        False,
        True,
        False,
    )


def test_context_flag_defaults_are_explicitly_false() -> None:
    """Flag resolution supplies false defaults to dictionary-like contexts."""
    assert _resolve_ctx_flags(_DefaultSensitiveDict()) == (False, False, False)


def test_auth_command_emits_human_setup_and_forwards_base_url(capsys) -> None:
    """Human login output includes the port and configured site before execution."""
    logger = Mock()
    with (
        patch("perplexity_cli.runners.auth.get_logger", return_value=logger),
        patch(
            "perplexity_cli.runners.auth.get_perplexity_base_url",
            return_value="https://site.example",
        ),
        patch("perplexity_cli.runners.auth._execute_auth") as execute,
    ):
        run_auth_command({"json": False, "schema": True, "debug": True}, port=9333)

    output = capsys.readouterr().out
    assert output == (
        "Authenticating with Perplexity.ai...\n"
        "\nMake sure Chrome is running with --remote-debugging-port=9333\n"
        "Navigate to https://site.example and log in if needed.\n\n"
    )
    execute.assert_called_once_with(9333, (False, True, True), "https://site.example")
    logger.info.assert_called_once_with("Starting authentication on port %s", 9333)


def test_auth_command_json_suppresses_human_setup(capsys) -> None:
    """JSON login emits no human setup text while preserving execution flags."""
    with (
        patch("perplexity_cli.runners.auth.get_logger", return_value=Mock()),
        patch(
            "perplexity_cli.runners.auth.get_perplexity_base_url",
            return_value="https://site.example",
        ),
        patch("perplexity_cli.runners.auth._execute_auth") as execute,
    ):
        run_auth_command({"json": True, "schema": False, "debug": False}, port=9333)

    assert capsys.readouterr().out == ""
    execute.assert_called_once_with(9333, (True, False, False), "https://site.example")


def test_auth_command_logs_keyboard_interrupt() -> None:
    """Interactive cancellation is logged and does not escape the command."""
    logger = Mock()
    with (
        patch("perplexity_cli.runners.auth.get_logger", return_value=logger),
        patch(
            "perplexity_cli.runners.auth.get_perplexity_base_url",
            return_value="https://site.example",
        ),
        patch("perplexity_cli.runners.auth._execute_auth", side_effect=KeyboardInterrupt),
    ):
        run_auth_command({}, port=9333)

    logger.info.assert_any_call("Authentication interrupted by user")


def test_execute_auth_forwards_success_and_cookie_count() -> None:
    """Successful authentication forwards all typed output options and logs only a count."""
    logger = Mock()
    with (
        patch("perplexity_cli.runners.auth.get_logger", return_value=logger),
        patch(
            "perplexity_cli.runners.auth.authenticate_sync",
            return_value=("token-sentinel", {"cookie-sentinel": "value-sentinel"}),
        ) as authenticate,
        patch("perplexity_cli.runners.auth._handle_auth_success") as success,
    ):
        _execute_auth(9333, (True, True, True), "https://site.example")

    authenticate.assert_called_once_with(port=9333)
    success.assert_called_once_with(
        "token-sentinel", {"cookie-sentinel": "value-sentinel"}, "json", "with_schema"
    )
    logger.debug.assert_called_once_with("Calling authenticate_sync")
    logger.info.assert_called_once_with("Token and %s cookies extracted successfully", 1)


def test_execute_auth_routes_timeout_and_os_errors() -> None:
    """Domain errors retain the selected format and configured troubleshooting URL."""
    with (
        patch("perplexity_cli.runners.auth.get_logger", return_value=Mock()),
        patch(
            "perplexity_cli.runners.auth.authenticate_sync",
            side_effect=TimeoutError("timeout-sentinel"),
        ),
        patch("perplexity_cli.runners.auth._handle_auth_timeout_error") as timeout,
    ):
        _execute_auth(9333, (False, False, True), "https://site.example")
    timeout.assert_called_once_with(
        timeout.call_args.args[0], "human", 9333, "https://site.example"
    )

    with (
        patch("perplexity_cli.runners.auth.get_logger", return_value=Mock()),
        patch("perplexity_cli.runners.auth.authenticate_sync", side_effect=OSError("os-sentinel")),
        patch("perplexity_cli.runners.auth._handle_auth_os_config_error") as os_error,
    ):
        _execute_auth(9333, (False, False, True), "https://site.example")
    os_error.assert_called_once()
    assert os_error.call_args.args[0].args == ("os-sentinel",)
    assert os_error.call_args.args[1:] == ("human", "debug")


def test_auth_success_human_output_contains_contract_lines(capsys) -> None:
    """Human success output distinguishes persistence, cookie state and next command."""
    manager = Mock(token_path="/tmp/token-sentinel.json")
    with (
        patch("perplexity_cli.runners.auth.TokenManager", return_value=manager),
        patch("perplexity_cli.runners.auth.get_logger", return_value=Mock()),
        patch("perplexity_cli.runners.auth.redact_path", return_value="<redacted>"),
        patch("perplexity_cli.runners.auth.get_save_cookies_enabled", return_value=False),
    ):
        _handle_auth_success(
            "token-sentinel", {"cookie-sentinel": "value-sentinel"}, "human", "no_schema"
        )

    output = capsys.readouterr().out
    assert output == (
        "[OK] Authentication successful!\n"
        "[OK] Token saved to: /tmp/token-sentinel.json\n"
        "[INFO] Cookies not saved (disabled in config)\n"
        "  To enable cookie storage: pxcli config set save_cookies true\n"
        '\nYou can now use: pxcli query "<your question>"\n'
    )
    manager.save_token.assert_called_once_with(
        "token-sentinel", cookies={"cookie-sentinel": "value-sentinel"}
    )
    logger = Mock()
    with (
        patch("perplexity_cli.runners.auth.TokenManager", return_value=manager),
        patch("perplexity_cli.runners.auth.get_logger", return_value=logger),
        patch("perplexity_cli.runners.auth.redact_path", return_value="<redacted>") as redact,
        patch("perplexity_cli.runners.auth.get_save_cookies_enabled", return_value=False),
    ):
        _handle_auth_success("token-sentinel", {}, "human", "no_schema")
    redact.assert_called_once_with("/tmp/token-sentinel.json")


def test_auth_success_json_forwards_schema_and_cookie_count(capsys) -> None:
    """JSON success returns the persisted path and exact cookie count."""
    manager = Mock(token_path="/tmp/token-sentinel.json")
    with (
        patch("perplexity_cli.runners.auth.TokenManager", return_value=manager),
        patch("perplexity_cli.runners.auth.get_logger", return_value=Mock()),
        patch("perplexity_cli.runners.auth.redact_path", return_value="<redacted>"),
    ):
        _handle_auth_success("token-sentinel", {"a": "1", "b": "2"}, "json", "with_schema")

    payload = json.loads(capsys.readouterr().out)
    assert payload["result"] == {"token_path": "/tmp/token-sentinel.json", "cookies_stored": 2}


def test_timeout_error_redacts_debug_and_preserves_troubleshooting(capsys) -> None:
    """Human timeout handling logs redacted text and passes the URL to help output."""
    logger = Mock()
    error = TimeoutError("secret-timeout-sentinel")
    with (
        patch("perplexity_cli.runners.auth.get_logger", return_value=logger),
        patch("perplexity_cli.runners.auth.redact_text", return_value="<redacted>") as redact,
        patch("perplexity_cli.runners.auth._print_auth_troubleshooting") as troubleshooting,
        patch("perplexity_cli.runners.auth.sys.exit", side_effect=SystemExit(1)),
        pytest.raises(SystemExit),
    ):
        _handle_auth_timeout_error(error, "human", 9333, "https://site.example")

    redact.assert_called_once_with("secret-timeout-sentinel", max_length=0)
    logger.debug.assert_called_once_with("Authentication failed: %s", "<redacted>")
    troubleshooting.assert_called_once_with(9333, "https://site.example")
    assert "[ERROR] Authentication failed: secret-timeout-sentinel" in capsys.readouterr().err


def test_os_config_error_forwards_error_logger_and_message() -> None:
    """Human OS/configuration errors preserve logger, debug mode and message tuple."""
    logger = Mock()
    error = OSError("os-sentinel")
    with (
        patch("perplexity_cli.runners.auth.get_logger", return_value=logger),
        patch("perplexity_cli.runners.auth.handle_unexpected_cli_error") as handler,
    ):
        _handle_auth_os_config_error(error, "human", "debug")

    handler.assert_called_once_with(
        error,
        logger,
        debug_mode="debug",
        message_tuple=(
            "[ERROR] Unexpected error: os-sentinel",
            "Unexpected error during authentication",
            False,
        ),
    )


def test_troubleshooting_writes_all_steps_to_stderr(capsys) -> None:
    """Troubleshooting remains actionable and is kept off standard output."""
    _print_auth_troubleshooting(9333, "https://site.example")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "\nTroubleshooting:\n"
        "  1. Start Chrome with: --remote-debugging-port=9333\n"
        "  2. Ensure Chrome is running and accessible\n"
        "  3. Navigate to https://site.example in Chrome\n"
        "  4. Log in with your Google account\n"
        "  5. Run this command again\n"
    )


def test_logout_context_defaults_and_explicit_modes() -> None:
    """Logout uses Click context schema when JSON mode is omitted."""
    with patch("perplexity_cli.runners.auth._ctx_to_dict", return_value={"schema": True}):
        assert _resolve_logout_ctx(False) == ("human", "with_schema")
    with patch(
        "perplexity_cli.runners.auth._ctx_to_dict", return_value={"json": True, "schema": False}
    ):
        assert _resolve_logout_ctx(None) == ("json", "no_schema")


def test_logout_emit_distinguishes_human_states(capsys) -> None:
    """Human logout distinguishes absent credentials from removed credentials."""
    _logout_emit("human", "no_schema", credential_state="absent")
    assert capsys.readouterr().out == "No stored credentials found.\n"
    _logout_emit("human", "no_schema", credential_state="present")
    assert (
        capsys.readouterr().out
        == "[OK] Logged out successfully.\n[OK] Stored credentials removed.\n"
    )


def test_logout_emit_forwards_json_schema(capsys) -> None:
    """JSON logout passes schema mode to the shared envelope writer."""
    with patch("perplexity_cli.runners.auth.write_envelope") as write:
        _logout_emit("json", "with_schema", credential_state="present")
    write.assert_called_once()
    assert write.call_args.kwargs == {"include_schema": "with_schema"}


def test_logout_os_error_preserves_human_handler_arguments() -> None:
    """Human logout failures preserve the exception, logger and user message."""
    manager = Mock()
    manager.token_exists.return_value = True
    error = OSError("logout-sentinel")
    manager.clear_token.side_effect = error
    logger = Mock()
    with (
        patch("perplexity_cli.runners.auth.TokenManager", return_value=manager),
        patch("perplexity_cli.runners.auth.get_logger", return_value=logger),
        patch("perplexity_cli.runners.auth.handle_unexpected_cli_error") as handler,
    ):
        run_logout_command(json_mode=False)

    handler.assert_called_once_with(
        error,
        logger,
        message_tuple=(
            "[ERROR] Error during logout: logout-sentinel",
            "Error during logout",
            False,
        ),
    )


def test_logout_command_forwards_schema_for_absent_and_present_json(capsys) -> None:
    """The command boundary preserves JSON schema mode for both credential states."""
    manager = Mock()
    manager.token_exists.return_value = False
    with (
        patch("perplexity_cli.runners.auth.TokenManager", return_value=manager),
        patch("perplexity_cli.runners.auth._ctx_to_dict", return_value={"schema": True}),
        patch("perplexity_cli.runners.auth.write_envelope") as write,
    ):
        run_logout_command(json_mode=True)
    assert capsys.readouterr().out == ""
    write.assert_called_once()
    assert write.call_args.kwargs["include_schema"] == "with_schema"

    manager.token_exists.return_value = True
    with (
        patch("perplexity_cli.runners.auth.TokenManager", return_value=manager),
        patch("perplexity_cli.runners.auth._ctx_to_dict", return_value={"schema": True}),
        patch("perplexity_cli.runners.auth.write_envelope") as write,
    ):
        run_logout_command(json_mode=True)
    write.assert_called_once()
    assert write.call_args.kwargs["include_schema"] == "with_schema"


def test_logout_context_defaults_schema_to_disabled() -> None:
    """Missing schema context does not opt logout into schema output."""
    with patch("perplexity_cli.runners.auth._ctx_to_dict", return_value={}):
        assert _resolve_logout_ctx(False) == ("human", "no_schema")


def test_logout_context_supplies_false_schema_default() -> None:
    """Logout context resolution supplies a false schema default."""
    with patch("perplexity_cli.runners.auth._ctx_to_dict", return_value=_DefaultSensitiveDict()):
        assert _resolve_logout_ctx(False) == ("human", "no_schema")
