"""Tests for TTY detection and NO_COLOR support."""

from unittest.mock import patch

from perplexity_cli.formatting.base import should_use_plain_default
from perplexity_cli.formatting.registry import resolve_format


class TestTTYDetection:
    """Test TTY-based format resolution."""

    def test_non_tty_defaults_to_plain(self):
        """When stdout is not a TTY and no format specified, resolve to 'plain'."""
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = False
            assert resolve_format(None) == "plain"

    def test_tty_defaults_to_rich(self, monkeypatch):
        """When stdout is a TTY, resolve to 'rich'."""
        monkeypatch.delenv("NO_COLOR", raising=False)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert resolve_format(None) == "rich"

    def test_explicit_format_honoured_non_tty(self):
        """When --format rich is explicit, use it even if not TTY."""
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = False
            assert resolve_format("rich") == "rich"

    def test_explicit_format_honoured_tty(self):
        """When --format plain is explicit, use it even if TTY."""
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert resolve_format("plain") == "plain"


class TestNoColorSupport:
    """Test NO_COLOR environment variable support."""

    def test_no_color_env_disables_colours(self, monkeypatch):
        """NO_COLOR=1 causes default to plain."""
        monkeypatch.setenv("NO_COLOR", "1")
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert resolve_format(None) == "plain"

    def test_no_color_empty_string_disables(self, monkeypatch):
        """NO_COLOR='' (empty) still disables colours per spec."""
        monkeypatch.setenv("NO_COLOR", "")
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert resolve_format(None) == "plain"

    def test_no_color_flag_overrides(self, monkeypatch):
        """--no-color flag causes default to plain."""
        monkeypatch.delenv("NO_COLOR", raising=False)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert resolve_format(None, no_color=True) == "plain"

    def test_no_color_unset_allows_colours(self, monkeypatch):
        """Without NO_COLOR, colours are allowed."""
        monkeypatch.delenv("NO_COLOR", raising=False)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert resolve_format(None) == "rich"


class TestShouldUsePlainDefault:
    """Test the should_use_plain_default helper."""

    def test_non_tty_returns_true(self):
        """Non-TTY stdout returns True."""
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = False
            assert should_use_plain_default() is True

    def test_tty_without_no_color_returns_false(self, monkeypatch):
        """TTY without NO_COLOR returns False."""
        monkeypatch.delenv("NO_COLOR", raising=False)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert should_use_plain_default() is False

    def test_tty_with_no_color_returns_true(self, monkeypatch):
        """TTY with NO_COLOR set returns True."""
        monkeypatch.setenv("NO_COLOR", "")
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert should_use_plain_default() is True


class TestShouldUseColors:
    """Test the Formatter.should_use_colors method."""

    def test_no_color_env_disables(self, monkeypatch):
        """NO_COLOR env var disables colours."""
        from perplexity_cli.formatting.plain import PlainTextFormatter

        monkeypatch.setenv("NO_COLOR", "1")
        formatter = PlainTextFormatter()
        assert formatter.should_use_colors() is False

    def test_no_color_unset_tty_enables(self, monkeypatch):
        """Without NO_COLOR on a TTY, colours are enabled."""
        from perplexity_cli.formatting.plain import PlainTextFormatter

        monkeypatch.delenv("NO_COLOR", raising=False)
        formatter = PlainTextFormatter()
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert formatter.should_use_colors() is True
