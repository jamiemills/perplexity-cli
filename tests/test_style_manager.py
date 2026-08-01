"""Tests for style configuration manager."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from perplexity_cli.utils.style_manager import StyleManager


@dataclass(frozen=True, slots=True)
class MockConfigPaths:
    """Minimal stand-in for resolved config paths."""

    style_path: Path


@pytest.fixture
def mocked_style_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point StyleManager at an isolated temporary style file.

    Returns the style file path, patched into
    ``perplexity_cli.utils.style_manager.get_config_paths``.
    """
    style_path = tmp_path / "style.json"
    config_paths = MockConfigPaths(style_path=style_path)
    monkeypatch.setattr(
        "perplexity_cli.utils.style_manager.get_config_paths",
        lambda: config_paths,
    )
    return style_path


class TestStyleManagerBasic:
    """Test basic StyleManager functionality."""

    def test_load_style_returns_none_when_not_set(self, mocked_style_path: Path):
        """Test load_style returns None when style file doesn't exist."""
        sm = StyleManager()
        result = sm.load_style()
        assert result is None

    def test_save_style_creates_file(self, mocked_style_path: Path):
        """Test save_style creates style file."""
        sm = StyleManager()
        sm.save_style("be concise")

        assert mocked_style_path.exists()
        with open(mocked_style_path, encoding="utf-8") as f:
            data = json.load(f)
            assert data["style"] == "be concise"
            assert "created_at" in data

    def test_save_and_load_style(self, mocked_style_path: Path):
        """Test save_style and load_style roundtrip."""
        sm = StyleManager()

        test_style = "provide brief answers"
        sm.save_style(test_style)
        loaded_style = sm.load_style()

        assert loaded_style == test_style

    def test_clear_style_removes_file(self, mocked_style_path: Path):
        """Test clear_style removes style file."""
        sm = StyleManager()

        # Create a style file
        sm.save_style("test style")
        assert mocked_style_path.exists()

        # Clear it
        sm.clear_style()
        assert not mocked_style_path.exists()

    def test_clear_style_is_idempotent(self, mocked_style_path: Path):
        """Test clear_style doesn't error when file doesn't exist."""
        sm = StyleManager()
        # Should not raise
        sm.clear_style()


class TestStyleManagerValidation:
    """Test style validation."""

    def test_validate_style_accepts_valid_string(self):
        """Test validate_style accepts valid strings."""
        sm = StyleManager()
        assert sm.validate_style("be brief") is True
        assert sm.validate_style("provide answers in under 50 words") is True

    def test_validate_style_rejects_empty_string(self):
        """Test validate_style rejects empty strings."""
        sm = StyleManager()
        assert sm.validate_style("") is False
        assert sm.validate_style("   ") is False

    def test_validate_style_rejects_non_string(self):
        """Test validate_style rejects non-string types."""
        sm = StyleManager()
        assert sm.validate_style(None) is False  # type: ignore
        assert sm.validate_style(123) is False  # type: ignore
        assert sm.validate_style([]) is False  # type: ignore

    def test_validate_style_rejects_too_long(self):
        """Test validate_style rejects excessively long strings."""
        sm = StyleManager()
        long_string = "x" * 10001
        assert sm.validate_style(long_string) is False

    def test_save_style_rejects_empty_string(self, mocked_style_path: Path):
        """Test save_style raises ValueError for empty string."""
        sm = StyleManager()

        with pytest.raises(ValueError):
            sm.save_style("")

        with pytest.raises(ValueError):
            sm.save_style("   ")

    def test_save_style_rejects_non_string(self, mocked_style_path: Path):
        """Test save_style raises ValueError for non-string."""
        sm = StyleManager()

        with pytest.raises(ValueError):
            sm.save_style(None)  # type: ignore

        with pytest.raises(ValueError):
            sm.save_style(123)  # type: ignore


class TestStyleManagerFilePermissions:
    """Test style file security."""

    def test_save_style_sets_secure_permissions(self, mocked_style_path: Path):
        """Test save_style sets 0600 file permissions."""
        sm = StyleManager()
        sm.save_style("test style")

        # Check file permissions
        mode = mocked_style_path.stat().st_mode & 0o777
        assert mode == 0o600


class TestStyleManagerErrorHandling:
    """Test error handling."""

    def test_load_style_handles_corrupted_json(self, mocked_style_path: Path):
        """Test load_style raises OSError for corrupted JSON."""
        # Write corrupted JSON
        with open(mocked_style_path, "w", encoding="utf-8") as f:
            f.write("{invalid json")

        sm = StyleManager()

        with pytest.raises(OSError):
            sm.load_style()

    def test_load_style_handles_missing_style_key(self, mocked_style_path: Path):
        """Test load_style raises OSError when style key missing."""
        with open(mocked_style_path, "w", encoding="utf-8") as f:
            json.dump({"created_at": "2025-01-01"}, f)

        sm = StyleManager()
        result = sm.load_style()
        # Returns None for missing style key (via .get)
        assert result is None
