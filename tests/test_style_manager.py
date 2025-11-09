"""Tests for style configuration manager."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from perplexity_cli.utils.style_manager import StyleManager


class TestStyleManagerBasic:
    """Test basic StyleManager functionality."""

    def test_load_style_returns_none_when_not_set(self):
        """Test load_style returns None when style file doesn't exist."""
        with patch("perplexity_cli.utils.style_manager.get_style_path") as mock_path:
            mock_path.return_value = Path("/nonexistent/path/style.json")
            sm = StyleManager()
            result = sm.load_style()
            assert result is None

    def test_save_style_creates_file(self):
        """Test save_style creates style file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            style_path = Path(tmpdir) / "style.json"

            with patch("perplexity_cli.utils.style_manager.get_style_path") as mock_path:
                mock_path.return_value = style_path
                sm = StyleManager()
                sm.save_style("be concise")

                assert style_path.exists()
                with open(style_path) as f:
                    data = json.load(f)
                    assert data["style"] == "be concise"
                    assert "created_at" in data

    def test_save_and_load_style(self):
        """Test save_style and load_style roundtrip."""
        with tempfile.TemporaryDirectory() as tmpdir:
            style_path = Path(tmpdir) / "style.json"

            with patch("perplexity_cli.utils.style_manager.get_style_path") as mock_path:
                mock_path.return_value = style_path
                sm = StyleManager()

                test_style = "provide brief answers"
                sm.save_style(test_style)
                loaded_style = sm.load_style()

                assert loaded_style == test_style

    def test_clear_style_removes_file(self):
        """Test clear_style removes style file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            style_path = Path(tmpdir) / "style.json"

            with patch("perplexity_cli.utils.style_manager.get_style_path") as mock_path:
                mock_path.return_value = style_path
                sm = StyleManager()

                # Create a style file
                sm.save_style("test style")
                assert style_path.exists()

                # Clear it
                sm.clear_style()
                assert not style_path.exists()

    def test_clear_style_is_idempotent(self):
        """Test clear_style doesn't error when file doesn't exist."""
        with patch("perplexity_cli.utils.style_manager.get_style_path") as mock_path:
            mock_path.return_value = Path("/nonexistent/path/style.json")
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

    def test_save_style_rejects_empty_string(self):
        """Test save_style raises ValueError for empty string."""
        with tempfile.TemporaryDirectory() as tmpdir:
            style_path = Path(tmpdir) / "style.json"

            with patch("perplexity_cli.utils.style_manager.get_style_path") as mock_path:
                mock_path.return_value = style_path
                sm = StyleManager()

                with pytest.raises(ValueError):
                    sm.save_style("")

                with pytest.raises(ValueError):
                    sm.save_style("   ")

    def test_save_style_rejects_non_string(self):
        """Test save_style raises ValueError for non-string."""
        with tempfile.TemporaryDirectory() as tmpdir:
            style_path = Path(tmpdir) / "style.json"

            with patch("perplexity_cli.utils.style_manager.get_style_path") as mock_path:
                mock_path.return_value = style_path
                sm = StyleManager()

                with pytest.raises(ValueError):
                    sm.save_style(None)  # type: ignore

                with pytest.raises(ValueError):
                    sm.save_style(123)  # type: ignore


class TestStyleManagerFilePermissions:
    """Test style file security."""

    def test_save_style_sets_secure_permissions(self):
        """Test save_style sets 0600 file permissions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            style_path = Path(tmpdir) / "style.json"

            with patch("perplexity_cli.utils.style_manager.get_style_path") as mock_path:
                mock_path.return_value = style_path
                sm = StyleManager()
                sm.save_style("test style")

                # Check file permissions
                mode = style_path.stat().st_mode & 0o777
                assert mode == 0o600


class TestStyleManagerErrorHandling:
    """Test error handling."""

    def test_load_style_handles_corrupted_json(self):
        """Test load_style raises OSError for corrupted JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            style_path = Path(tmpdir) / "style.json"

            # Write corrupted JSON
            with open(style_path, "w") as f:
                f.write("{invalid json")

            with patch("perplexity_cli.utils.style_manager.get_style_path") as mock_path:
                mock_path.return_value = style_path
                sm = StyleManager()

                with pytest.raises(OSError):
                    sm.load_style()

    def test_load_style_handles_missing_style_key(self):
        """Test load_style raises OSError when style key missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            style_path = Path(tmpdir) / "style.json"

            with open(style_path, "w") as f:
                json.dump({"created_at": "2025-01-01"}, f)

            with patch("perplexity_cli.utils.style_manager.get_style_path") as mock_path:
                mock_path.return_value = style_path
                sm = StyleManager()
                result = sm.load_style()
                # Returns None for missing style key (via .get)
                assert result is None
