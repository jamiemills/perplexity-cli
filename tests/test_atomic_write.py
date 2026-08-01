"""Tests for the atomic file writer with fault injection at every stage."""

from __future__ import annotations

import json
import logging
import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from perplexity_cli.utils.atomic_write import (
    _create_temp_sibling,
    _fsync_directory,
    atomic_write_text,
)

_POSIX = sys.platform != "win32"


def _temp_files(directory: Path) -> list[Path]:
    """Return any temporary siblings left behind in a directory."""
    return [p for p in directory.iterdir() if p.name.endswith(".tmp")]


class TestAtomicWriteRoundTrip:
    """Tests for the happy-path atomic write contract."""

    def test_writes_json_content(self, tmp_path):
        """JSON-serialisable content is persisted to the destination."""
        dest = tmp_path / "data.json"
        payload = {"token": "encrypted-value", "version": 2}
        atomic_write_text(dest, payload)
        with open(dest, encoding="utf-8") as f:
            assert json.load(f) == payload

    def test_no_temp_residue_after_success(self, tmp_path):
        """A successful write leaves no temporary siblings behind."""
        dest = tmp_path / "data.json"
        atomic_write_text(dest, {"a": 1})
        assert _temp_files(tmp_path) == []
        assert dest.read_text() == json.dumps({"a": 1})

    @pytest.mark.skipif(not _POSIX, reason="POSIX mode bits are not asserted on Windows")
    def test_new_file_has_mode_0600(self, tmp_path):
        """A newly created destination gets the default 0600 mode."""
        dest = tmp_path / "data.json"
        atomic_write_text(dest, {"a": 1})
        assert stat.S_IMODE(dest.stat().st_mode) == 0o600

    @pytest.mark.skipif(not _POSIX, reason="POSIX mode bits are not asserted on Windows")
    def test_replaced_file_has_mode_0600(self, tmp_path):
        """An overwritten destination keeps the 0600 mode after replacement."""
        dest = tmp_path / "data.json"
        dest.write_text("old")
        os.chmod(dest, 0o644)
        atomic_write_text(dest, {"a": 1})
        assert stat.S_IMODE(dest.stat().st_mode) == 0o600

    @pytest.mark.skipif(not _POSIX, reason="POSIX mode bits are not asserted on Windows")
    def test_custom_mode_is_applied(self, tmp_path):
        """A requested mode other than the default is honoured."""
        dest = tmp_path / "data.json"
        atomic_write_text(dest, {"a": 1}, mode=0o700)
        assert stat.S_IMODE(dest.stat().st_mode) == 0o700

    def test_parent_directory_required(self, tmp_path):
        """A missing parent directory raises OSError without side effects."""
        dest = tmp_path / "missing" / "data.json"
        with pytest.raises(OSError):
            atomic_write_text(dest, {"a": 1})
        assert not dest.exists()


class TestTempNaming:
    """Tests for unique same-directory temporary sibling naming."""

    def test_temp_names_unique_and_same_directory(self, tmp_path):
        """Temporary siblings have unique names in the destination directory."""
        dest = tmp_path / "data.json"
        first = _create_temp_sibling(dest)
        second = _create_temp_sibling(dest)
        try:
            assert first.parent == tmp_path
            assert second.parent == tmp_path
            assert first.name != second.name
            assert first.name.endswith(".tmp")
            assert first.is_file()
            assert second.is_file()
        finally:
            first.unlink(missing_ok=True)
            second.unlink(missing_ok=True)


class TestSymlinkDestination:
    """Tests for rejecting symlink destinations before replacement."""

    def test_symlink_destination_rejected(self, tmp_path):
        """A destination that is a symlink is rejected and left untouched."""
        target = tmp_path / "target.json"
        target.write_text("ORIGINAL")
        dest = tmp_path / "data.json"
        try:
            dest.symlink_to(target)
        except (OSError, NotImplementedError, PermissionError):
            pytest.skip("symlink creation is not supported on this platform")
        with pytest.raises(OSError, match="symlink"):
            atomic_write_text(dest, {"new": 1})
        assert dest.is_symlink()
        assert target.read_text() == "ORIGINAL"
        assert _temp_files(tmp_path) == []


class TestFaultInjection:
    """Fault injection proving old destinations are preserved byte-for-byte."""

    @pytest.mark.parametrize(
        "stage",
        [
            "_serialise_content",
            "_create_temp_sibling",
            "_set_permissions",
            "_write_content",
            "_flush_file",
            "_fsync_file",
            "_replace_temp",
        ],
    )
    def test_stage_failure_preserves_existing_destination(self, tmp_path, stage):
        """A failure at each stage leaves the existing destination untouched."""
        dest = tmp_path / "data.json"
        dest.write_text("ORIGINAL")
        with patch(f"perplexity_cli.utils.atomic_write.{stage}", side_effect=OSError("injected")):
            with pytest.raises(OSError, match="injected"):
                atomic_write_text(dest, {"new": 1})
        assert dest.read_text() == "ORIGINAL"
        assert _temp_files(tmp_path) == []

    def test_open_failure_preserves_existing_destination(self, tmp_path):
        """A failure while opening the temporary file preserves the destination."""
        dest = tmp_path / "data.json"
        dest.write_text("ORIGINAL")
        with patch("builtins.open", side_effect=OSError("injected open")):
            with pytest.raises(OSError, match="injected open"):
                atomic_write_text(dest, {"new": 1})
        assert dest.read_text() == "ORIGINAL"
        assert _temp_files(tmp_path) == []

    def test_stage_failure_creates_no_partial_destination(self, tmp_path):
        """A replace failure leaves no destination file behind at all."""
        dest = tmp_path / "data.json"
        with patch(
            "perplexity_cli.utils.atomic_write._replace_temp", side_effect=OSError("injected")
        ):
            with pytest.raises(OSError, match="injected"):
                atomic_write_text(dest, {"new": 1})
        assert not dest.exists()
        assert _temp_files(tmp_path) == []

    def test_cleanup_failure_does_not_mask_primary_error(self, tmp_path, caplog):
        """A failing cleanup neither masks the primary error nor corrupts the file."""
        dest = tmp_path / "data.json"
        dest.write_text("ORIGINAL")
        with caplog.at_level(logging.WARNING):
            with (
                patch(
                    "perplexity_cli.utils.atomic_write._replace_temp",
                    side_effect=OSError("replace failed"),
                ),
                patch(
                    "perplexity_cli.utils.atomic_write._cleanup_temp",
                    side_effect=OSError("cleanup failed"),
                ) as mock_cleanup,
            ):
                with pytest.raises(OSError, match="replace failed"):
                    atomic_write_text(dest, {"new": 1})
        assert dest.read_text() == "ORIGINAL"
        mock_cleanup.assert_called_once()
        assert len(_temp_files(tmp_path)) == 1
        assert "Could not remove temporary file" in caplog.text


class TestDirectoryFsync:
    """Tests for best-effort directory fsync after replacement."""

    def test_directory_fsync_called_after_replace(self, tmp_path):
        """The parent directory is fsynced after a successful replacement."""
        dest = tmp_path / "data.json"
        with patch("perplexity_cli.utils.atomic_write._fsync_directory") as mock_fsync:
            atomic_write_text(dest, {"a": 1})
            mock_fsync.assert_called_once_with(tmp_path)

    def test_directory_fsync_swallows_oserror(self, tmp_path):
        """A failed directory fsync is silently ignored."""
        with patch("os.open", side_effect=OSError("cannot open dir")):
            _fsync_directory(tmp_path)
