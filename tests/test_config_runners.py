"""Tests for configuration and style command runners."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from perplexity_cli.runners.config import (
    _collect_env_overrides,
    _execute_clear_style,
    _get_ctx_obj_dict,
    _get_include_schema,
    _get_json_mode_from_ctx,
    _output_config_change,
    _output_config_text,
    _output_view_style,
    _read_ctx_bool,
    run_clear_style_command,
    run_configure_command,
    run_show_config_command,
    run_view_style_command,
)


class TestRunConfigureCommand:
    """Tests for run_configure_command()."""

    @patch("perplexity_cli.runners.config.StyleManager")
    def test_happy_path_saves_and_echoes(self, mock_sm_class, capsys):
        """Test successful style configuration."""
        mock_sm = Mock()
        mock_sm_class.return_value = mock_sm

        run_configure_command("Be concise and technical")

        mock_sm.save_style.assert_called_once_with("Be concise and technical")
        captured = capsys.readouterr()
        assert "Style configured successfully" in captured.out
        assert "Be concise and technical" in captured.out

    @patch("perplexity_cli.runners.config.StyleManager")
    def test_value_error_exits(self, mock_sm_class, capsys):
        """Test that ValueError from save_style causes exit code 1."""
        mock_sm = Mock()
        mock_sm.save_style.side_effect = ValueError("style too long")
        mock_sm_class.return_value = mock_sm

        with pytest.raises(SystemExit) as exc_info:
            run_configure_command("x" * 10000)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Invalid style: style too long" in captured.err

    @patch("perplexity_cli.runners.config.StyleManager")
    def test_os_error_exits(self, mock_sm_class, capsys):
        """Test that OSError from save_style causes exit code 1."""
        mock_sm = Mock()
        mock_sm.save_style.side_effect = OSError("disk full")
        mock_sm_class.return_value = mock_sm

        with pytest.raises(SystemExit) as exc_info:
            run_configure_command("some style")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Failed to save style: disk full" in captured.err


class TestRunViewStyleCommand:
    """Tests for run_view_style_command()."""

    @patch("perplexity_cli.runners.config.StyleManager")
    def test_displays_configured_style(self, mock_sm_class, capsys):
        """Test that a configured style is displayed."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = "Be formal and precise"
        mock_sm_class.return_value = mock_sm

        run_view_style_command()

        captured = capsys.readouterr()
        assert "Current style:" in captured.out
        assert "Be formal and precise" in captured.out

    @patch("perplexity_cli.runners.config.StyleManager")
    def test_displays_no_style_message(self, mock_sm_class, capsys):
        """Test output when no style is configured."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        run_view_style_command()

        captured = capsys.readouterr()
        assert "No style configured" in captured.out

    @patch("perplexity_cli.runners.config.StyleManager")
    def test_os_error_exits(self, mock_sm_class, capsys):
        """Test that OSError from load_style causes exit code 1."""
        mock_sm = Mock()
        mock_sm.load_style.side_effect = OSError("permission denied")
        mock_sm_class.return_value = mock_sm

        with pytest.raises(SystemExit) as exc_info:
            run_view_style_command()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error reading style: permission denied" in captured.err


class TestRunClearStyleCommand:
    """Tests for run_clear_style_command()."""

    @patch("perplexity_cli.runners.config.StyleManager")
    def test_clears_existing_style(self, mock_sm_class, capsys):
        """Test successful style clearing."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = "some style"
        mock_sm_class.return_value = mock_sm

        run_clear_style_command()

        mock_sm.clear_style.assert_called_once()
        captured = capsys.readouterr()
        assert "Style cleared successfully" in captured.out

    @patch("perplexity_cli.runners.config.StyleManager")
    def test_no_style_to_clear(self, mock_sm_class, capsys):
        """Test output when no style exists to clear."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        run_clear_style_command()

        mock_sm.clear_style.assert_not_called()
        captured = capsys.readouterr()
        assert "No style is currently configured" in captured.out

    @patch("perplexity_cli.runners.config.StyleManager")
    def test_os_error_exits(self, mock_sm_class, capsys):
        """Test that OSError causes exit code 1."""
        mock_sm = Mock()
        mock_sm.load_style.side_effect = OSError("read error")
        mock_sm_class.return_value = mock_sm

        with pytest.raises(SystemExit) as exc_info:
            run_clear_style_command()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error clearing style: read error" in captured.err


class TestRunShowConfigCommand:
    """Tests for run_show_config_command()."""

    @patch("perplexity_cli.runners.config.get_feature_config_path")
    @patch("perplexity_cli.runners.config.get_feature_config")
    def test_displays_configuration(self, mock_get_config, mock_get_path, capsys, monkeypatch):
        """Test that configuration is displayed correctly."""
        monkeypatch.delenv("PERPLEXITY_SAVE_COOKIES", raising=False)
        monkeypatch.delenv("PERPLEXITY_DEBUG_MODE", raising=False)

        mock_config = Mock()
        mock_config.save_cookies = False
        mock_config.debug_mode = True
        mock_get_config.return_value = mock_config
        mock_get_path.return_value = Path("/home/user/.config/perplexity-cli/config.json")

        run_show_config_command()

        captured = capsys.readouterr()
        assert "Perplexity CLI Configuration" in captured.out
        assert "save_cookies: False" in captured.out
        assert "debug_mode:   True" in captured.out


class TestConfigRunnerMutationKillers:
    """Mutation-killing tests for config runner edge cases."""

    @patch("perplexity_cli.runners.config.get_feature_config_path")
    @patch("perplexity_cli.runners.config.get_feature_config")
    def test_show_config_env_overrides_displayed(
        self, mock_get_config, mock_get_path, capsys, monkeypatch
    ):
        monkeypatch.setenv("PERPLEXITY_SAVE_COOKIES", "true")
        monkeypatch.setenv("PERPLEXITY_DEBUG_MODE", "false")

        mock_config = Mock()
        mock_config.save_cookies = True
        mock_config.debug_mode = False
        mock_get_config.return_value = mock_config
        mock_get_path.return_value = Path("/tmp/config.json")

        run_show_config_command()

        captured = capsys.readouterr()
        assert "Environment Overrides:" in captured.out
        assert "PERPLEXITY_SAVE_COOKIES=true" in captured.out
        assert "PERPLEXITY_DEBUG_MODE=false" in captured.out

    @patch("perplexity_cli.runners.config.get_feature_config_path")
    @patch("perplexity_cli.runners.config.get_feature_config")
    def test_show_config_no_env_overrides_section(
        self, mock_get_config, mock_get_path, capsys, monkeypatch
    ):
        monkeypatch.delenv("PERPLEXITY_SAVE_COOKIES", raising=False)
        monkeypatch.delenv("PERPLEXITY_DEBUG_MODE", raising=False)

        mock_config = Mock()
        mock_config.save_cookies = False
        mock_config.debug_mode = False
        mock_get_config.return_value = mock_config
        mock_get_path.return_value = Path("/tmp/config.json")

        run_show_config_command()

        captured = capsys.readouterr()
        assert "Environment Overrides:" not in captured.out

    @patch("perplexity_cli.runners.config.get_feature_config_path")
    @patch("perplexity_cli.runners.config.get_feature_config")
    def test_show_config_error_exits(self, mock_get_config, mock_get_path, capsys):
        from perplexity_cli.utils.exceptions import ConfigurationError

        mock_get_config.side_effect = ConfigurationError("bad config")

        with pytest.raises(SystemExit) as exc_info:
            run_show_config_command()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "[ERROR] Failed to load configuration: bad config" in captured.err

    @patch("perplexity_cli.runners.config.set_feature")
    @patch("perplexity_cli.runners.config.clear_feature_config_cache")
    def test_set_config_save_cookies_enabled_message(self, mock_clear, mock_set, capsys):
        from perplexity_cli.runners.config import run_set_config_command

        run_set_config_command("save_cookies", "true")

        captured = capsys.readouterr()
        assert "[OK] Configuration updated: save_cookies = True" in captured.out
        assert "[INFO] Cookie storage enabled." in captured.out
        assert "Re-authenticate to save cookies: pxcli auth login" in captured.out

    @patch("perplexity_cli.runners.config.set_feature")
    @patch("perplexity_cli.runners.config.clear_feature_config_cache")
    def test_set_config_save_cookies_disabled_message(self, mock_clear, mock_set, capsys):
        from perplexity_cli.runners.config import run_set_config_command

        run_set_config_command("save_cookies", "false")

        captured = capsys.readouterr()
        assert "[OK] Configuration updated: save_cookies = False" in captured.out
        assert "[INFO] Cookie storage disabled." in captured.out
        assert "Only JWT token will be saved on next authentication." in captured.out

    @patch("perplexity_cli.runners.config.set_feature")
    @patch("perplexity_cli.runners.config.clear_feature_config_cache")
    def test_set_config_debug_mode_enabled_message(self, mock_clear, mock_set, capsys):
        from perplexity_cli.runners.config import run_set_config_command

        run_set_config_command("debug_mode", "true")

        captured = capsys.readouterr()
        assert "[OK] Configuration updated: debug_mode = True" in captured.out
        assert "[INFO] Debug mode enabled." in captured.out
        assert "All commands will now log at DEBUG level." in captured.out

    @patch("perplexity_cli.runners.config.set_feature")
    @patch("perplexity_cli.runners.config.clear_feature_config_cache")
    def test_set_config_debug_mode_disabled_message(self, mock_clear, mock_set, capsys):
        from perplexity_cli.runners.config import run_set_config_command

        run_set_config_command("debug_mode", "false")

        captured = capsys.readouterr()
        assert "[OK] Configuration updated: debug_mode = False" in captured.out
        assert "[INFO] Debug mode disabled." in captured.out
        assert "Use --debug flag for one-time debug output." in captured.out

    @patch("perplexity_cli.runners.config.set_feature")
    @patch("perplexity_cli.runners.config.clear_feature_config_cache")
    def test_set_config_error_exits(self, mock_clear, mock_set, capsys):
        from perplexity_cli.runners.config import run_set_config_command
        from perplexity_cli.utils.exceptions import ConfigurationError

        mock_set.side_effect = ConfigurationError("invalid key")

        with pytest.raises(SystemExit) as exc_info:
            run_set_config_command("bad_key", "true")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "[ERROR] Failed to update configuration: invalid key" in captured.err

    @patch("perplexity_cli.runners.config.StyleManager")
    def test_configure_json_output(self, mock_sm_class, capsys):
        import json

        mock_sm = Mock()
        mock_sm_class.return_value = mock_sm

        run_configure_command("Be concise", output_format="json")

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is True
        assert envelope["command"] == "pxcli style set"
        assert envelope["result"]["style"] == "Be concise"

    @patch("perplexity_cli.runners.config.StyleManager")
    def test_view_style_json_output(self, mock_sm_class, capsys):
        import json

        mock_sm = Mock()
        mock_sm.load_style.return_value = "Formal tone"
        mock_sm_class.return_value = mock_sm

        run_view_style_command(output_format="json")

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is True
        assert envelope["command"] == "pxcli style show"
        assert envelope["result"]["style"] == "Formal tone"

    @patch("perplexity_cli.runners.config.StyleManager")
    def test_clear_style_json_had_style_true(self, mock_sm_class, capsys):
        import json

        mock_sm = Mock()
        mock_sm.load_style.return_value = "existing"
        mock_sm_class.return_value = mock_sm

        run_clear_style_command(output_format="json")

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["result"]["had_style"] is True

    @patch("perplexity_cli.runners.config.StyleManager")
    def test_clear_style_json_had_style_false(self, mock_sm_class, capsys):
        import json

        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        run_clear_style_command(output_format="json")

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["result"]["had_style"] is False

    @patch("perplexity_cli.runners.config.StyleManager")
    def test_view_style_no_style_shows_set_hint(self, mock_sm_class, capsys):
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        run_view_style_command()

        captured = capsys.readouterr()
        assert "No style configured." in captured.out
        assert "perplexity-cli configure <STYLE>" in captured.out

    @patch("perplexity_cli.runners.config.StyleManager")
    def test_view_style_shows_separator_lines(self, mock_sm_class, capsys):
        mock_sm = Mock()
        mock_sm.load_style.return_value = "My style"
        mock_sm_class.return_value = mock_sm

        run_view_style_command()

        captured = capsys.readouterr()
        assert "-" * 50 in captured.out

    @patch("perplexity_cli.runners.config.set_feature")
    @patch("perplexity_cli.runners.config.clear_feature_config_cache")
    def test_set_config_json_output(self, mock_clear, mock_set, capsys):
        import json

        from perplexity_cli.runners.config import run_set_config_command

        run_set_config_command("save_cookies", "true", output_format="json")

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is True
        assert envelope["command"] == "pxcli config set"
        assert envelope["result"]["key"] == "save_cookies"
        assert envelope["result"]["value"] is True

    @patch("perplexity_cli.runners.config.get_feature_config_path")
    @patch("perplexity_cli.runners.config.get_feature_config")
    def test_show_config_json_output(self, mock_get_config, mock_get_path, capsys, monkeypatch):
        import json

        monkeypatch.delenv("PERPLEXITY_SAVE_COOKIES", raising=False)
        monkeypatch.delenv("PERPLEXITY_DEBUG_MODE", raising=False)

        mock_config = Mock()
        mock_config.save_cookies = True
        mock_config.debug_mode = False
        mock_get_config.return_value = mock_config
        mock_get_path.return_value = Path("/tmp/config.json")

        run_show_config_command(output_format="json")

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is True
        assert envelope["command"] == "pxcli config show"
        assert envelope["result"]["save_cookies"] is True
        assert envelope["result"]["debug_mode"] is False
        assert envelope["result"]["config_path"] == "/tmp/config.json"

    @patch("perplexity_cli.runners.config.get_feature_config_path")
    @patch("perplexity_cli.runners.config.get_feature_config")
    def test_show_config_json_preserves_override_key(
        self, mock_get_config, mock_get_path, monkeypatch
    ):
        """JSON configuration output keeps environment overrides under its contract key."""
        monkeypatch.setenv("PERPLEXITY_DEBUG_MODE", "sentinel")
        mock_get_config.return_value = Mock(save_cookies=True, debug_mode=False)
        mock_get_path.return_value = Path("/tmp/config.json")
        with patch("perplexity_cli.runners.config.write_envelope") as write:
            run_show_config_command(output_format="json")

        result = write.call_args.args[0].result
        assert result["env_overrides"] == ["PERPLEXITY_DEBUG_MODE=sentinel"]

    @patch("perplexity_cli.runners.config.get_feature_config_path")
    @patch("perplexity_cli.runners.config.get_feature_config")
    def test_show_config_human_uses_indented_overrides_and_logs(
        self, mock_get_config, mock_get_path, capsys, monkeypatch
    ):
        """Human configuration output indents overrides and records successful display."""
        monkeypatch.setenv("PERPLEXITY_DEBUG_MODE", "sentinel")
        mock_get_config.return_value = Mock(save_cookies=True, debug_mode=False)
        mock_get_path.return_value = Path("/tmp/config.json")
        logger = Mock()
        with patch("perplexity_cli.runners.config.get_logger", return_value=logger):
            run_show_config_command(output_format="human")

        assert "  PERPLEXITY_DEBUG_MODE=sentinel" in capsys.readouterr().out
        logger.debug.assert_called_once_with("Configuration displayed successfully")

    @patch("perplexity_cli.runners.config.get_feature_config")
    def test_show_config_json_error_forwards_exception_and_contract(self, mock_get_config):
        """JSON configuration failures preserve the error envelope arguments."""
        from perplexity_cli.utils.exceptions import ConfigurationError

        error = ConfigurationError("sentinel failure")
        mock_get_config.side_effect = error
        with (
            patch("perplexity_cli.runners.config.handle_error") as handle,
            patch("perplexity_cli.runners.config.sys.exit", side_effect=SystemExit(1)),
            pytest.raises(SystemExit),
        ):
            run_show_config_command(output_format="json")

        handle.assert_called_once_with(error, "pxcli config show", output_format="json")

    @patch("perplexity_cli.runners.config.get_feature_config")
    def test_show_config_human_error_logs_with_traceback(self, mock_get_config, capsys):
        """Human configuration failures log the message with exception information."""
        from perplexity_cli.utils.exceptions import ConfigurationError

        error = ConfigurationError("sentinel failure")
        mock_get_config.side_effect = error
        logger = Mock()
        with (
            patch("perplexity_cli.runners.config.get_logger", return_value=logger),
            patch("perplexity_cli.runners.config.sys.exit", side_effect=SystemExit(1)),
            pytest.raises(SystemExit),
        ):
            run_show_config_command(output_format="human")

        assert "sentinel failure" in capsys.readouterr().err
        logger.error.assert_called_once_with(
            "Configuration display failed: %s", error, exc_info=True
        )

    def test_read_ctx_bool_supports_dict_and_object_contexts(self):
        """Context booleans work for both Click dictionaries and objects."""
        assert _read_ctx_bool({"schema": True}, "schema") is True
        assert _read_ctx_bool({}, "schema") is False
        context = SimpleNamespace(schema=True)
        assert _read_ctx_bool(context, "schema") is True
        assert _read_ctx_bool(context, "missing") is False

    def test_context_output_modes_read_click_context(self, monkeypatch):
        """JSON and schema output modes are resolved from context flags."""
        monkeypatch.setattr(
            "perplexity_cli.runners.config._get_ctx_obj_dict",
            lambda: {"json": True, "schema": True},
        )
        assert _get_json_mode_from_ctx() == "json"
        assert _get_include_schema() == "with_schema"

    def test_context_output_modes_have_human_defaults(self, monkeypatch):
        """Absent or false context flags select the human output contract."""
        monkeypatch.setattr(
            "perplexity_cli.runners.config._get_ctx_obj_dict",
            lambda: {"json": False, "schema": False},
        )

        assert _get_json_mode_from_ctx() == "human"
        assert _get_include_schema() == "no_schema"

    def test_collect_env_overrides_preserves_configured_order(self, monkeypatch):
        """Environment overrides are returned in the stable key order."""
        monkeypatch.setenv("PERPLEXITY_DEBUG_MODE", "false")
        monkeypatch.setenv("PERPLEXITY_SAVE_COOKIES", "true")

        assert _collect_env_overrides() == [
            "PERPLEXITY_SAVE_COOKIES=true",
            "PERPLEXITY_DEBUG_MODE=false",
        ]
        assert _collect_env_overrides(prefix="  ") == [
            "  PERPLEXITY_SAVE_COOKIES=true",
            "  PERPLEXITY_DEBUG_MODE=false",
        ]

    def test_output_config_text_includes_toggles_overrides_and_guidance(self, capsys):
        """Human config output contains values and actionable commands."""
        config = Mock(save_cookies=True, debug_mode=False)
        _output_config_text(config, "/tmp/config.json", ["  PERPLEXITY_SAVE_COOKIES=true"])

        output = capsys.readouterr().out
        semantic_fragments = (
            "/tmp/config.json",
            "save_cookies",
            "debug_mode",
            "PERPLEXITY_SAVE_COOKIES=true",
            "pxcli config set save_cookies",
            "pxcli config set debug_mode",
        )
        assert all(fragment in output for fragment in semantic_fragments)

    def test_output_config_text_has_exact_layout_with_override(self, capsys):
        """Human configuration output retains its headings, spacing, and commands."""
        config = Mock(save_cookies=True, debug_mode=False)

        _output_config_text(config, "/tmp/config.json", ["  OVERRIDE=sentinel"])

        assert capsys.readouterr().out.splitlines() == [
            "Perplexity CLI Configuration",
            "=" * 40,
            "Config file: /tmp/config.json",
            "",
            "Feature Toggles:",
            "  save_cookies: True",
            "  debug_mode:   False",
            "",
            "Environment Overrides:",
            "  OVERRIDE=sentinel",
            "",
            "To change settings:",
            "  pxcli config set save_cookies true|false",
            "  pxcli config set debug_mode true|false",
        ]

    def test_output_config_change_json_forwards_schema(self):
        """JSON configuration changes forward the schema inclusion flag."""
        logger = Mock()
        with (
            patch("perplexity_cli.runners.config._get_include_schema", return_value="with_schema"),
            patch("perplexity_cli.runners.config.write_envelope") as write,
        ):
            _output_config_change("debug_mode", "enabled", "json", logger)

        write.assert_called_once()
        assert write.call_args.kwargs["include_schema"] == "with_schema"
        logger.info.assert_not_called()

    def test_output_config_change_human_logs_and_prints_exact_state(self, capsys):
        """Human configuration changes log the key and boolean state lazily."""
        logger = Mock()

        _output_config_change("debug_mode", "disabled", "human", logger)

        assert capsys.readouterr().out.splitlines() == [
            "[OK] Configuration updated: debug_mode = False",
            "",
            "[INFO] Debug mode disabled.",
            "  Use --debug flag for one-time debug output.",
        ]
        logger.info.assert_called_once_with("Configuration updated: %s = %s", "debug_mode", False)

    def test_configure_json_error_preserves_exception_and_command(self):
        """Style validation failures retain their JSON error contract."""
        error = ValueError("invalid style")
        manager = Mock()
        manager.save_style.side_effect = error
        with (
            patch("perplexity_cli.runners.config.StyleManager", return_value=manager),
            patch(
                "perplexity_cli.runners.config.handle_error", side_effect=SystemExit(1)
            ) as handle,
            pytest.raises(SystemExit),
        ):
            run_configure_command("bad", output_format="json")

        handle.assert_called_once_with(error, "pxcli style set", output_format="json")

    def test_set_config_context_json_error_preserves_output_mode(self):
        """Context-derived JSON mode reaches configuration error handling."""
        from perplexity_cli.runners.config import run_set_config_command
        from perplexity_cli.utils.exceptions import ConfigurationError

        error = ConfigurationError("invalid key")
        with (
            patch("perplexity_cli.runners.config._get_json_mode_from_ctx", return_value="json"),
            patch("perplexity_cli.runners.config.set_feature", side_effect=error),
            patch(
                "perplexity_cli.runners.config.handle_error", side_effect=SystemExit(1)
            ) as handle,
            pytest.raises(SystemExit),
        ):
            run_set_config_command("unknown", "true")

        handle.assert_called_once_with(error, "pxcli config set", output_format="json")

    def test_set_config_error_logs_original_exception(self):
        """Configuration failures log the original error before exiting."""
        from perplexity_cli.runners.config import _handle_set_config_error
        from perplexity_cli.utils.exceptions import ConfigurationError

        error = ConfigurationError("invalid key")
        logger = Mock()
        with (
            patch("perplexity_cli.runners.config.handle_error"),
            patch("perplexity_cli.runners.config.sys.exit", side_effect=SystemExit(1)),
            pytest.raises(SystemExit),
        ):
            _handle_set_config_error(error, "human", logger)

        logger.error.assert_called_once_with("Configuration update failed: %s", error)

    def test_context_object_lookup_is_silent_and_returns_context_object(self, monkeypatch):
        """Context lookup must not raise outside Click and must preserve the object."""
        context = Mock(obj={"json": True})
        lookup = Mock(return_value=context)
        monkeypatch.setattr("perplexity_cli.runners.config.click.get_current_context", lookup)

        assert _get_ctx_obj_dict() == {"json": True}
        lookup.assert_called_once_with(silent=True)

    def test_context_object_lookup_returns_empty_dict_without_context(self, monkeypatch):
        """Commands have empty context flags when invoked outside Click."""
        monkeypatch.setattr(
            "perplexity_cli.runners.config.click.get_current_context", lambda silent: None
        )

        assert _get_ctx_obj_dict() == {}

    def test_configure_human_output_has_stable_lines(self, capsys):
        """Human style configuration output keeps all contract lines."""
        with patch("perplexity_cli.runners.config.StyleManager") as manager_class:
            run_configure_command("unique-style", output_format="human")

        assert capsys.readouterr().out.splitlines() == [
            "[OK] Style configured successfully.",
            "[OK] Style will be applied to all future queries.",
            "",
            "Style preview:",
            "  unique-style",
        ]
        manager_class.return_value.save_style.assert_called_once_with("unique-style")

    def test_configure_json_output_forwards_schema_mode(self):
        """JSON style configuration forwards the Click schema mode."""
        with (
            patch("perplexity_cli.runners.config.StyleManager"),
            patch("perplexity_cli.runners.config._get_include_schema", return_value="with_schema"),
            patch("perplexity_cli.runners.config.write_envelope") as write,
        ):
            run_configure_command("unique-style", output_format="json")

        assert write.call_args.kwargs["include_schema"] == "with_schema"

    def test_configure_context_selects_json_mode(self):
        """A context-derived JSON mode reaches the envelope boundary."""
        with (
            patch("perplexity_cli.runners.config._get_json_mode_from_ctx", return_value="json"),
            patch("perplexity_cli.runners.config.StyleManager"),
            patch("perplexity_cli.runners.config.write_envelope") as write,
        ):
            run_configure_command("unique-style")

        write.assert_called_once()

    def test_view_style_json_output_forwards_schema_mode(self):
        """JSON style display forwards the Click schema mode."""
        manager = Mock(load_style=Mock(return_value="unique-style"))
        with (
            patch("perplexity_cli.runners.config.StyleManager", return_value=manager),
            patch("perplexity_cli.runners.config._get_include_schema", return_value="with_schema"),
            patch("perplexity_cli.runners.config.write_envelope") as write,
        ):
            run_view_style_command(output_format="json")

        assert write.call_args.kwargs["include_schema"] == "with_schema"

    def test_view_style_context_selects_json_mode(self):
        """A context-derived JSON mode reaches the style envelope boundary."""
        manager = Mock(load_style=Mock(return_value="unique-style"))
        with (
            patch("perplexity_cli.runners.config._get_json_mode_from_ctx", return_value="json"),
            patch("perplexity_cli.runners.config.StyleManager", return_value=manager),
            patch("perplexity_cli.runners.config.write_envelope") as write,
        ):
            run_view_style_command()

        write.assert_called_once()

    def test_view_style_error_forwards_command_and_format(self):
        """Style read failures preserve the public error-handler arguments."""
        manager = Mock()
        manager.load_style.side_effect = OSError("read failure")
        with (
            patch("perplexity_cli.runners.config.StyleManager", return_value=manager),
            patch("perplexity_cli.runners.config._handle_style_error") as handle,
        ):
            run_view_style_command(output_format="json")

        handle.assert_called_once_with(
            manager.load_style.side_effect,
            "json",
            "pxcli style show",
            "Error reading style",
        )

    def test_view_style_human_output_has_exact_separators(self, capsys):
        """Configured style output has exactly two fixed-width separators."""
        _output_view_style("unique-style")

        assert capsys.readouterr().out.splitlines() == [
            "Current style:",
            "-" * 50,
            "unique-style",
            "-" * 50,
        ]

    def test_view_style_missing_output_has_complete_hint(self, capsys):
        """Missing styles include the complete configuration hint."""
        _output_view_style(None)

        assert capsys.readouterr().out.splitlines() == [
            "No style configured.",
            "",
            "Set a style with:",
            "  perplexity-cli configure <STYLE>",
        ]

    def test_clear_style_json_forwards_schema_mode(self):
        """JSON style clearing forwards schema inclusion and does not clear twice."""
        manager = Mock()
        manager.load_style.return_value = "unique-style"
        with (
            patch("perplexity_cli.runners.config._get_include_schema", return_value="with_schema"),
            patch("perplexity_cli.runners.config.write_envelope") as write,
        ):
            _execute_clear_style(manager, "json")

        manager.clear_style.assert_called_once_with()
        assert write.call_args.kwargs["include_schema"] == "with_schema"

    def test_clear_style_context_selects_json_mode(self):
        """A context-derived JSON mode reaches the clear envelope boundary."""
        manager = Mock()
        manager.load_style.return_value = None
        with (
            patch("perplexity_cli.runners.config._get_json_mode_from_ctx", return_value="json"),
            patch("perplexity_cli.runners.config.StyleManager", return_value=manager),
            patch("perplexity_cli.runners.config.write_envelope") as write,
        ):
            run_clear_style_command()

        write.assert_called_once()

    def test_clear_style_error_forwards_command_and_format(self):
        """Style clear failures preserve the public error-handler arguments."""
        manager = Mock()
        manager.load_style.side_effect = OSError("clear failure")
        with (
            patch("perplexity_cli.runners.config.StyleManager", return_value=manager),
            patch("perplexity_cli.runners.config._handle_style_error") as handle,
        ):
            run_clear_style_command(output_format="json")

        handle.assert_called_once_with(
            manager.load_style.side_effect,
            "json",
            "pxcli style clear",
            "Error clearing style",
        )

    def test_clear_style_human_output_has_complete_messages(self, capsys):
        """Human style clearing reports both the action and its effect."""
        manager = Mock()
        manager.load_style.return_value = "unique-style"

        _execute_clear_style(manager, "human")

        assert capsys.readouterr().out.splitlines() == [
            "[OK] Style cleared successfully.",
            "[OK] Queries will no longer include a style prompt.",
        ]

    def test_clear_style_without_style_has_single_message(self, capsys):
        """Clearing an absent style does not call the mutating operation."""
        manager = Mock()
        manager.load_style.return_value = None

        _execute_clear_style(manager, "human")

        manager.clear_style.assert_not_called()
        assert capsys.readouterr().out.splitlines() == ["No style is currently configured."]
