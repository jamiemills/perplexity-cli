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

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    def test_happy_path_saves_and_echoes(self, mock_sm_class, capsys):
        """Test successful style configuration."""
        mock_sm = Mock()
        mock_sm_class.return_value = mock_sm

        run_configure_command("Be concise and technical")

        mock_sm.save_style.assert_called_once_with("Be concise and technical")
        captured = capsys.readouterr()
        assert "Style configured successfully" in captured.out
        assert "Be concise and technical" in captured.out

    @patch("perplexity_cli.utils.style_manager.StyleManager")
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

    @patch("perplexity_cli.utils.style_manager.StyleManager")
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

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    def test_displays_configured_style(self, mock_sm_class, capsys):
        """Test that a configured style is displayed."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = "Be formal and precise"
        mock_sm_class.return_value = mock_sm

        run_view_style_command()

        captured = capsys.readouterr()
        assert "Current style:" in captured.out
        assert "Be formal and precise" in captured.out

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    def test_displays_no_style_message(self, mock_sm_class, capsys):
        """Test output when no style is configured."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        run_view_style_command()

        captured = capsys.readouterr()
        assert "No style configured" in captured.out

    @patch("perplexity_cli.utils.style_manager.StyleManager")
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

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    def test_clears_existing_style(self, mock_sm_class, capsys):
        """Test successful style clearing."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = "some style"
        mock_sm_class.return_value = mock_sm

        run_clear_style_command()

        mock_sm.clear_style.assert_called_once()
        captured = capsys.readouterr()
        assert "Style cleared successfully" in captured.out

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    def test_no_style_to_clear(self, mock_sm_class, capsys):
        """Test output when no style exists to clear."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = None
        mock_sm_class.return_value = mock_sm

        run_clear_style_command()

        mock_sm.clear_style.assert_not_called()
        captured = capsys.readouterr()
        assert "No style is currently configured" in captured.out

    @patch("perplexity_cli.utils.style_manager.StyleManager")
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

    @patch("perplexity_cli.utils.config.get_feature_config_path")
    @patch("perplexity_cli.utils.config.get_feature_config")
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
