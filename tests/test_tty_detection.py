"""Tests for TTY detection and NO_COLOR support."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import patch

import pytest

from perplexity_cli.formatting.base import should_use_plain_default
from perplexity_cli.formatting.registry import resolve_format


@pytest.fixture
def set_no_color(monkeypatch: pytest.MonkeyPatch) -> Callable[[str | None], None]:
    """Force an explicit NO_COLOR state so results never depend on the shell env.

    Args:
        state: Value to set NO_COLOR to, or None to unset it entirely.
    """

    def _apply(state: str | None) -> None:
        if state is None:
            monkeypatch.delenv("NO_COLOR", raising=False)
        else:
            monkeypatch.setenv("NO_COLOR", state)

    return _apply


class TestTTYDetection:
    """Test TTY-based format resolution."""

    def test_non_tty_defaults_to_plain(self, set_no_color: Callable[[str | None], None]):
        """When stdout is not a TTY and no format specified, resolve to 'plain'."""
        set_no_color(None)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = False
            assert resolve_format(None) == "plain"

    def test_tty_defaults_to_rich(self, set_no_color: Callable[[str | None], None]):
        """When stdout is a TTY and NO_COLOR unset, resolve to 'rich'."""
        set_no_color(None)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert resolve_format(None) == "rich"

    def test_explicit_format_honoured_non_tty(self, set_no_color: Callable[[str | None], None]):
        """When --format rich is explicit, use it even if not TTY."""
        set_no_color(None)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = False
            assert resolve_format("rich") == "rich"

    def test_explicit_format_honoured_tty(self, set_no_color: Callable[[str | None], None]):
        """When --format plain is explicit, use it even if TTY."""
        set_no_color(None)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert resolve_format("plain") == "plain"


class TestNoColorSupport:
    """Test NO_COLOR environment variable support."""

    def test_no_color_env_disables_colours(self, set_no_color: Callable[[str | None], None]):
        """NO_COLOR=1 causes default to plain."""
        set_no_color("1")
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert resolve_format(None) == "plain"

    def test_no_color_empty_string_disables(self, set_no_color: Callable[[str | None], None]):
        """NO_COLOR='' (empty) still disables colours per spec."""
        set_no_color("")
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert resolve_format(None) == "plain"

    def test_no_color_flag_overrides(self, set_no_color: Callable[[str | None], None]):
        """--no-color flag causes default to plain."""
        set_no_color(None)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert resolve_format(None, no_color=True) == "plain"

    def test_no_color_unset_allows_colours(self, set_no_color: Callable[[str | None], None]):
        """Without NO_COLOR, colours are allowed."""
        set_no_color(None)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert resolve_format(None) == "rich"


class TestShouldUsePlainDefault:
    """Test the should_use_plain_default helper."""

    def test_non_tty_returns_true(self, set_no_color: Callable[[str | None], None]):
        """Non-TTY stdout returns True."""
        set_no_color(None)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = False
            assert should_use_plain_default() is True

    def test_tty_without_no_color_returns_false(self, set_no_color: Callable[[str | None], None]):
        """TTY without NO_COLOR returns False."""
        set_no_color(None)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert should_use_plain_default() is False

    def test_tty_with_no_color_returns_true(self, set_no_color: Callable[[str | None], None]):
        """TTY with NO_COLOR set returns True."""
        set_no_color("")
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert should_use_plain_default() is True


class TestShouldUseColors:
    """Test the Formatter.should_use_colors method."""

    def test_no_color_env_disables(self, set_no_color: Callable[[str | None], None]):
        """NO_COLOR env var disables colours."""
        from perplexity_cli.formatting.plain import PlainTextFormatter

        set_no_color("1")
        formatter = PlainTextFormatter()
        assert formatter.should_use_colors() is False

    def test_no_color_unset_tty_enables(self, set_no_color: Callable[[str | None], None]):
        """Without NO_COLOR on a TTY, colours are enabled."""
        from perplexity_cli.formatting.plain import PlainTextFormatter

        set_no_color(None)
        formatter = PlainTextFormatter()
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert formatter.should_use_colors() is True
