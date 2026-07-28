"""Tests for configuration and style command runners."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from perplexity_cli.runners.config import (
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
