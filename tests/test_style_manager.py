"""Tests for style configuration manager."""

from __future__ import annotations

import builtins
import json
import locale
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from perplexity_cli.utils.style_manager import MAX_STYLE_LENGTH, StyleManager

_POSIX = sys.platform != "win32"


@contextmanager
def _non_utf8_locale() -> Iterator[None]:
    """Force a non-UTF-8 preferred encoding so explicit encodings are distinguished."""
    previous = locale.setlocale(locale.LC_CTYPE)
    locale.setlocale(locale.LC_CTYPE, "C")
    try:
        yield
    finally:
        locale.setlocale(locale.LC_CTYPE, previous)


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
        assert sm.validate_style(None) is False  # type: ignore  # owner: test-infrastructure; reason: deliberately passes non-string values to exercise validation
        assert sm.validate_style(123) is False  # type: ignore  # owner: test-infrastructure; reason: deliberately passes non-string values to exercise validation
        assert sm.validate_style([]) is False  # type: ignore  # owner: test-infrastructure; reason: deliberately passes non-string values to exercise validation

    def test_validate_style_rejects_string_subclasses(self):
        """Validation accepts only the concrete string type at its boundary."""

        class CustomString(str):
            __slots__ = ()

        assert StyleManager().validate_style(CustomString("brief")) is False

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
            sm.save_style(None)  # type: ignore  # owner: test-infrastructure; reason: deliberately passes non-string style to exercise validation

        with pytest.raises(ValueError):
            sm.save_style(123)  # type: ignore  # owner: test-infrastructure; reason: deliberately passes non-string style to exercise validation


class TestStyleManagerFilePermissions:
    """Test style file security."""

    def test_save_style_sets_secure_permissions(self, mocked_style_path: Path):
        """Test save_style sets 0600 file permissions."""
        sm = StyleManager()
        sm.save_style("test style")

        # Check file permissions
        mode = mocked_style_path.stat().st_mode & 0o777
        assert mode == 0o600


class TestStyleManagerAtomicWrites:
    """Test atomic-write failure preservation for style saves."""

    def test_save_style_preserves_old_file_on_write_failure(self, mocked_style_path: Path):
        """An injected write failure leaves the old style file byte-for-byte."""
        sm = StyleManager()
        sm.save_style("old style")
        original = mocked_style_path.read_bytes()
        with patch(
            "perplexity_cli.utils.atomic_write._write_content",
            side_effect=OSError("injected write"),
        ):
            with pytest.raises(OSError):
                sm.save_style("new style")
        assert mocked_style_path.read_bytes() == original

    def test_save_style_preserves_old_file_on_replace_failure(self, mocked_style_path: Path):
        """An injected replace failure leaves the old style file byte-for-byte."""
        sm = StyleManager()
        sm.save_style("old style")
        original = mocked_style_path.read_bytes()
        with patch(
            "perplexity_cli.utils.atomic_write._replace_temp",
            side_effect=OSError("injected replace"),
        ):
            with pytest.raises(OSError):
                sm.save_style("new style")
        assert mocked_style_path.read_bytes() == original

    def test_save_style_leaves_no_temp_residue_after_failure(self, mocked_style_path: Path):
        """A failed style save leaves no temporary siblings behind."""
        sm = StyleManager()
        sm.save_style("old style")
        with patch(
            "perplexity_cli.utils.atomic_write._replace_temp",
            side_effect=OSError("injected replace"),
        ):
            with pytest.raises(OSError):
                sm.save_style("new style")
        residue = [p for p in mocked_style_path.parent.iterdir() if p.name.endswith(".tmp")]
        assert residue == []

    @pytest.mark.skipif(not _POSIX, reason="POSIX mode bits are not asserted on Windows")
    def test_save_style_failure_preserves_secure_permissions(self, mocked_style_path: Path):
        """The preserved old style file keeps 0600 mode after a failed save."""
        sm = StyleManager()
        sm.save_style("old style")
        with patch(
            "perplexity_cli.utils.atomic_write._replace_temp",
            side_effect=OSError("injected replace"),
        ):
            with pytest.raises(OSError):
                sm.save_style("new style")
        assert stat.S_IMODE(mocked_style_path.stat().st_mode) == 0o600


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

    def test_load_style_wraps_decode_failure_with_exact_message(self, mocked_style_path: Path):
        """Corrupted style files raise an OSError carrying the path and cause."""
        mocked_style_path.write_text("{invalid json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError) as decode_info:
            json.loads("{invalid json")
        expected = f"Failed to load style from {mocked_style_path}: {decode_info.value}"

        sm = StyleManager()
        with pytest.raises(OSError) as excinfo:
            sm.load_style()

        assert str(excinfo.value) == expected


class TestStyleManagerEncoding:
    """Test that style files are always decoded as UTF-8."""

    def test_load_style_decodes_utf8_regardless_of_locale(self, mocked_style_path: Path):
        """Non-ASCII styles load correctly even under a non-UTF-8 locale."""
        mocked_style_path.write_bytes(b'{"style": "caf\xc3\xa9"}')
        with _non_utf8_locale():
            assert StyleManager().load_style() == "café"


class TestStyleManagerValidationMessages:
    """Test exact validation error messages raised through save_style."""

    def test_save_style_empty_string_message_is_exact(self, mocked_style_path: Path):
        """Empty styles raise the precise non-empty-string message."""
        with pytest.raises(ValueError) as excinfo:
            StyleManager().save_style("")
        assert str(excinfo.value) == "Style must be a non-empty string"

    def test_save_style_blank_string_message_is_exact(self, mocked_style_path: Path):
        """Whitespace-only styles raise the precise blank-style message."""
        with pytest.raises(ValueError) as excinfo:
            StyleManager().save_style("   ")
        assert str(excinfo.value) == "Style cannot be blank or whitespace only"

    def test_save_style_too_long_message_is_exact(self, mocked_style_path: Path):
        """Over-long styles raise the precise maximum-length message."""
        oversized = "x" * (MAX_STYLE_LENGTH + 1)
        expected = (
            f"Style exceeds maximum length of {MAX_STYLE_LENGTH} characters "
            f"(current length: {len(oversized)} characters)"
        )
        with pytest.raises(ValueError) as excinfo:
            StyleManager().save_style(oversized)
        assert str(excinfo.value) == expected


class TestStyleManagerBoundaries:
    """Test boundary behaviour of style length limits."""

    def test_save_style_accepts_exactly_maximum_length(self, mocked_style_path: Path):
        """A style of exactly MAX_STYLE_LENGTH characters saves successfully."""
        StyleManager().save_style("x" * MAX_STYLE_LENGTH)
        assert mocked_style_path.exists()

    def test_validate_style_accepts_exactly_maximum_length(self):
        """A style of exactly MAX_STYLE_LENGTH characters validates as True."""
        assert StyleManager().validate_style("x" * MAX_STYLE_LENGTH) is True

    def test_validate_style_rejects_one_character_over_maximum(self):
        """One character beyond the limit is rejected without writing a file."""
        assert StyleManager().validate_style("x" * (MAX_STYLE_LENGTH + 1)) is False


class TestStyleManagerParentDirectories:
    """Test parent-directory creation when saving styles."""

    def test_save_style_creates_missing_parent_directories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """save_style creates every missing ancestor of the style file."""
        nested_style_path = tmp_path / "settings" / "deep" / "style.json"
        config_paths = MockConfigPaths(style_path=nested_style_path)
        monkeypatch.setattr(
            "perplexity_cli.utils.style_manager.get_config_paths",
            lambda: config_paths,
        )

        StyleManager().save_style("nested style")

        assert nested_style_path.exists()


class TestStyleManagerSerialisationFormat:
    """Test the on-disk JSON rendering produced by save_style."""

    def test_save_style_writes_two_space_indented_json(self, mocked_style_path: Path):
        """Saved style JSON is indented with exactly two spaces per level."""
        StyleManager().save_style("indented")

        lines = mocked_style_path.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "{"
        assert lines[1].startswith('  "')
        assert not lines[1].startswith('   "')
        assert lines[-1] == "}"


class TestStyleManagerSaveFailure:
    """Test exact error reporting when saving fails."""

    def test_save_style_write_failure_message_is_exact(self, mocked_style_path: Path):
        """Write failures are re-raised with the precise save-failure message."""
        sm = StyleManager()
        with patch(
            "perplexity_cli.utils.atomic_write._write_content",
            side_effect=OSError("injected write"),
        ):
            with pytest.raises(OSError) as excinfo:
                sm.save_style("new style")

        assert str(excinfo.value) == (
            f"Failed to save style to {mocked_style_path}: injected write"
        )


class TestStyleManagerIoCallContracts:
    """Explicit I/O parameters pinned at the module interaction boundary."""

    def test_load_style_opens_file_with_utf8_encoding(
        self, mocked_style_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """load_style passes the exact lowercase utf-8 encoding to open."""
        mocked_style_path.write_text('{"style": "spyon-load-style"}', encoding="utf-8")
        real_open = builtins.open
        captured: dict[str, Any] = {}

        def spying_open(file: str | Path, mode: str = "r", **kwargs: Any) -> Any:
            if Path(file) == mocked_style_path:
                captured["encoding"] = kwargs.get("encoding")
            return real_open(file, mode, **kwargs)

        monkeypatch.setattr(builtins, "open", spying_open)

        assert StyleManager().load_style() == "spyon-load-style"
        assert captured["encoding"] == "utf-8"

    def test_save_style_passes_explicit_owner_only_mode(
        self, mocked_style_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """save_style requests 0o600 permissions explicitly from the writer."""
        captured: dict[str, Any] = {}

        def spying_write(path: Path, content: str, mode: int = -1) -> None:
            """Record the writer invocation without touching the filesystem."""
            captured["mode"] = mode

        monkeypatch.setattr(
            "perplexity_cli.utils.style_manager.atomic_write_text",
            spying_write,
        )

        StyleManager().save_style("spyon-save-style")

        assert captured["mode"] == 0o600


class TestStyleManagerClearFailure:
    """Test exact error reporting when clearing fails."""

    def test_clear_style_unlink_failure_message_is_exact(self, mocked_style_path: Path):
        """Unlink failures are re-raised with the precise delete-failure message."""
        sm = StyleManager()
        sm.save_style("doomed")
        with patch.object(Path, "unlink", side_effect=OSError("injected delete")):
            with pytest.raises(OSError) as excinfo:
                sm.clear_style()

        assert str(excinfo.value) == (
            f"Failed to delete style file {mocked_style_path}: injected delete"
        )
