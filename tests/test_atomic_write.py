"""Tests for the atomic file writer with fault injection at every stage."""

from __future__ import annotations

import inspect
import json
import locale
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
    atomic_write_json,
    atomic_write_text,
)

_POSIX = sys.platform != "win32"


def _temp_files(directory: Path) -> list[Path]:
    """Return any temporary siblings left behind in a directory."""
    return [p for p in directory.iterdir() if p.name.endswith(".tmp")]


def _force_c_locale() -> str | None:
    """Switch the process LC_CTYPE to the C locale and return the saved value.

    Returns ``None`` when the platform refuses the switch so callers can skip.
    """
    try:
        saved = locale.setlocale(locale.LC_CTYPE)
        locale.setlocale(locale.LC_CTYPE, "C")
    except locale.Error:
        return None
    return saved


class TestAtomicWriteRoundTrip:
    """Tests for the happy-path atomic write contract."""

    def test_writes_json_content(self, tmp_path):
        """JSON-serialisable content is persisted to the destination."""
        dest = tmp_path / "data.json"
        payload = {"token": "encrypted-value", "version": 2}
        atomic_write_json(dest, payload)
        with open(dest, encoding="utf-8") as f:
            assert json.load(f) == payload

    def test_no_temp_residue_after_success(self, tmp_path):
        """A successful write leaves no temporary siblings behind."""
        dest = tmp_path / "data.json"
        atomic_write_json(dest, {"a": 1})
        assert _temp_files(tmp_path) == []
        assert dest.read_text() == json.dumps({"a": 1})

    def test_writes_raw_text_verbatim(self, tmp_path):
        """Raw text is written byte-for-byte without JSON serialisation."""
        dest = tmp_path / "style.json"
        raw = '{"style": "concise", "note": "not-quoted"}'
        atomic_write_text(dest, raw)
        assert dest.read_text() == raw

    def test_raw_text_public_default_mode_is_0600(self):
        """The raw-text API declares the same restrictive default mode as JSON."""
        assert inspect.signature(atomic_write_text).parameters["mode"].default == 0o600

    def test_raw_text_bypasses_serialisation(self, tmp_path):
        """The raw-text variant never calls the JSON serialisation stage."""
        dest = tmp_path / "style.txt"
        with patch(
            "perplexity_cli.utils.atomic_write._serialise_content",
            side_effect=AssertionError("serialisation must not run for raw text"),
        ):
            atomic_write_text(dest, '{"a": 1}')
        assert dest.read_text() == '{"a": 1}'

    def test_no_temp_residue_after_raw_text_success(self, tmp_path):
        """A successful raw-text write leaves no temporary siblings behind."""
        dest = tmp_path / "style.txt"
        atomic_write_text(dest, "plain text")
        assert _temp_files(tmp_path) == []
        assert dest.read_text() == "plain text"

    @pytest.mark.skipif(not _POSIX, reason="POSIX mode bits are not asserted on Windows")
    def test_new_file_has_mode_0600(self, tmp_path):
        """A newly created destination gets the default 0600 mode."""
        dest = tmp_path / "data.json"
        atomic_write_json(dest, {"a": 1})
        assert stat.S_IMODE(dest.stat().st_mode) == 0o600

    @pytest.mark.skipif(not _POSIX, reason="POSIX mode bits are not asserted on Windows")
    def test_replaced_file_has_mode_0600(self, tmp_path):
        """An overwritten destination keeps the 0600 mode after replacement."""
        dest = tmp_path / "data.json"
        dest.write_text("old")
        os.chmod(dest, 0o644)
        atomic_write_json(dest, {"a": 1})
        assert stat.S_IMODE(dest.stat().st_mode) == 0o600

    @pytest.mark.skipif(not _POSIX, reason="POSIX mode bits are not asserted on Windows")
    def test_custom_mode_is_applied(self, tmp_path):
        """A requested mode other than the default is honoured."""
        dest = tmp_path / "data.json"
        atomic_write_json(dest, {"a": 1}, mode=0o700)
        assert stat.S_IMODE(dest.stat().st_mode) == 0o700

    @pytest.mark.skipif(not _POSIX, reason="POSIX mode bits are not asserted on Windows")
    def test_raw_text_new_file_has_mode_0600(self, tmp_path):
        """A raw-text destination gets the default 0600 mode."""
        dest = tmp_path / "style.txt"
        atomic_write_text(dest, "plain")
        assert stat.S_IMODE(dest.stat().st_mode) == 0o600

    def test_parent_directory_required(self, tmp_path):
        """A missing parent directory raises OSError without side effects."""
        dest = tmp_path / "missing" / "data.json"
        with pytest.raises(OSError):
            atomic_write_json(dest, {"a": 1})
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
            atomic_write_json(dest, {"new": 1})
        assert dest.is_symlink()
        assert target.read_text() == "ORIGINAL"
        assert _temp_files(tmp_path) == []

    def test_symlink_destination_rejected_for_raw_text(self, tmp_path):
        """A symlink destination is rejected for raw-text writes."""
        target = tmp_path / "target.txt"
        target.write_text("ORIGINAL")
        dest = tmp_path / "style.txt"
        try:
            dest.symlink_to(target)
        except (OSError, NotImplementedError, PermissionError):
            pytest.skip("symlink creation is not supported on this platform")
        with pytest.raises(OSError, match="symlink"):
            atomic_write_text(dest, "new")
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
                atomic_write_json(dest, {"new": 1})
        assert dest.read_text() == "ORIGINAL"
        assert _temp_files(tmp_path) == []

    def test_open_failure_preserves_existing_destination(self, tmp_path):
        """A failure while opening the temporary file preserves the destination."""
        dest = tmp_path / "data.json"
        dest.write_text("ORIGINAL")
        with patch("builtins.open", side_effect=OSError("injected open")):
            with pytest.raises(OSError, match="injected open"):
                atomic_write_json(dest, {"new": 1})
        assert dest.read_text() == "ORIGINAL"
        assert _temp_files(tmp_path) == []

    def test_stage_failure_creates_no_partial_destination(self, tmp_path):
        """A replace failure leaves no destination file behind at all."""
        dest = tmp_path / "data.json"
        with patch(
            "perplexity_cli.utils.atomic_write._replace_temp", side_effect=OSError("injected")
        ):
            with pytest.raises(OSError, match="injected"):
                atomic_write_json(dest, {"new": 1})
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
                    atomic_write_json(dest, {"new": 1})
        assert dest.read_text() == "ORIGINAL"
        mock_cleanup.assert_called_once()
        assert len(_temp_files(tmp_path)) == 1
        assert "Could not remove temporary file" in caplog.text


class TestRawTextFaultInjection:
    """Fault injection for the raw-text variant."""

    @pytest.mark.parametrize(
        "stage",
        [
            "_create_temp_sibling",
            "_set_permissions",
            "_write_content",
            "_flush_file",
            "_fsync_file",
            "_replace_temp",
        ],
    )
    def test_stage_failure_preserves_existing_destination(self, tmp_path, stage):
        """A failure at each raw-text stage leaves the destination untouched."""
        dest = tmp_path / "style.txt"
        dest.write_text("ORIGINAL")
        with patch(f"perplexity_cli.utils.atomic_write.{stage}", side_effect=OSError("injected")):
            with pytest.raises(OSError, match="injected"):
                atomic_write_text(dest, "new content")
        assert dest.read_text() == "ORIGINAL"
        assert _temp_files(tmp_path) == []

    def test_open_failure_preserves_existing_destination(self, tmp_path):
        """A failure while opening the raw-text temp file preserves the destination."""
        dest = tmp_path / "style.txt"
        dest.write_text("ORIGINAL")
        with patch("builtins.open", side_effect=OSError("injected open")):
            with pytest.raises(OSError, match="injected open"):
                atomic_write_text(dest, "new content")
        assert dest.read_text() == "ORIGINAL"
        assert _temp_files(tmp_path) == []

    def test_replace_failure_creates_no_partial_destination(self, tmp_path):
        """A raw-text replace failure leaves no destination file behind."""
        dest = tmp_path / "style.txt"
        with patch(
            "perplexity_cli.utils.atomic_write._replace_temp", side_effect=OSError("injected")
        ):
            with pytest.raises(OSError, match="injected"):
                atomic_write_text(dest, "new content")
        assert not dest.exists()
        assert _temp_files(tmp_path) == []

    def test_cleanup_failure_does_not_mask_primary_error(self, tmp_path, caplog):
        """A failing cleanup neither masks the primary error nor corrupts the file."""
        dest = tmp_path / "style.txt"
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
                    atomic_write_text(dest, "new content")
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
            atomic_write_json(dest, {"a": 1})
            mock_fsync.assert_called_once_with(tmp_path)

    def test_directory_fsync_called_after_raw_text_replace(self, tmp_path):
        """The parent directory is fsynced after a raw-text replacement."""
        dest = tmp_path / "style.txt"
        with patch("perplexity_cli.utils.atomic_write._fsync_directory") as mock_fsync:
            atomic_write_text(dest, "plain")
            mock_fsync.assert_called_once_with(tmp_path)

    def test_directory_fsync_swallows_oserror(self, tmp_path):
        """A failed directory fsync is silently ignored."""
        with patch("os.open", side_effect=OSError("cannot open dir")):
            _fsync_directory(tmp_path)


class TestTempSiblingNamingContract:
    """Temporary siblings are hidden same-directory files."""

    def test_temp_sibling_uses_hidden_dot_prefix(self, tmp_path):
        """The temp file name hides behind a dot prefix derived from the target."""
        import perplexity_cli.utils.atomic_write as aw

        dest = tmp_path / "data.json"
        temp = aw._create_temp_sibling(dest)
        try:
            assert temp.parent == tmp_path
            assert temp.name.startswith(f".{dest.name}.")
            assert temp.name.endswith(".tmp")
        finally:
            temp.unlink(missing_ok=True)


class TestReplacementSameDirectory:
    """Replacement sources must live in the destination directory."""

    def test_replacement_source_lives_in_destination_directory(self, tmp_path, monkeypatch):
        """The rename source is the temp sibling created beside the destination."""
        import perplexity_cli.utils.atomic_write as aw

        dest = tmp_path / "data.json"
        seen = {}
        real_replace = aw._replace_temp

        def spy(temp_path, target):
            seen["temp_parent"] = temp_path.parent
            return real_replace(temp_path, target)

        monkeypatch.setattr(aw, "_replace_temp", spy)
        atomic_write_text(dest, "payload")
        assert seen["temp_parent"] == tmp_path
        assert dest.read_text() == "payload"


class TestSilentCleanupOfVanishedTemp:
    """Cleanup of an already-removed temporary is silent."""

    def test_cleanup_of_already_removed_temp_logs_no_warning(self, tmp_path, monkeypatch, caplog):
        """A vanished temp does not trigger the removal-failure warning."""
        import perplexity_cli.utils.atomic_write as aw

        dest = tmp_path / "data.json"

        def replace_then_vanish(_temp_path, _target):
            raise OSError("injected replace failure")

        def vanished_temp(_temp_path):
            return None

        monkeypatch.setattr(aw, "_replace_temp", replace_then_vanish)
        monkeypatch.setattr(aw, "_cleanup_temp", vanished_temp)
        with caplog.at_level(logging.WARNING):
            with pytest.raises(OSError, match="injected replace failure"):
                atomic_write_json(dest, {"a": 1})
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert not any("Could not remove temporary file" in r.getMessage() for r in warnings)


class TestCleanupFailureWarningContent:
    """The cleanup warning names the redacted temporary path."""

    def test_warning_names_the_redacted_temp_file(self, tmp_path, monkeypatch, caplog):
        """The warning message carries the prefix and the redacted temp name."""
        import logging as logging_module

        import perplexity_cli.utils.atomic_write as aw

        dest = tmp_path / "data.json"

        def unremovable_temp(_temp_path):
            raise OSError("locked")

        def failing_replace(_temp_path, _target):
            raise OSError("injected replace failure")

        monkeypatch.setattr(aw, "_cleanup_temp", unremovable_temp)
        monkeypatch.setattr(aw, "_replace_temp", failing_replace)
        with caplog.at_level(logging_module.WARNING):
            with pytest.raises(OSError, match="replace"):
                atomic_write_json(dest, {"a": 1})
        warning_records = [r for r in caplog.records if r.levelno == logging_module.WARNING]
        message = warning_records[0].getMessage()
        assert message.startswith("Could not remove temporary file ")
        assert "%s" not in message


class TestDirectoryFsyncImplementation:
    """Directory fsync opens the parent with the platform directory flag."""

    def test_opens_directory_with_o_directory_flag(self, tmp_path, monkeypatch):
        """The directory handle is opened read-only with O_DIRECTORY set."""
        calls: list[int] = []
        real_open = os.open

        def spy(path, flags, *args, **kwargs):
            calls.append(flags)
            return real_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", spy)
        _fsync_directory(tmp_path)
        dir_flag = getattr(os, "O_DIRECTORY", 0)
        assert calls, "expected the directory to be opened for fsync"
        assert calls[0] & dir_flag

    def test_missing_o_directory_constant_is_tolerated(self, tmp_path, monkeypatch):
        """Platforms without O_DIRECTORY skip the fsync without error."""
        monkeypatch.delattr(os, "O_DIRECTORY")
        _fsync_directory(tmp_path)


class TestUtf8EncodingContract:
    """Non-ASCII payloads are persisted as UTF-8 regardless of process locale."""

    @pytest.mark.skipif(not _POSIX, reason="the C locale switch is POSIX-only")
    def test_non_ascii_text_is_utf8_even_under_c_locale(self, tmp_path: Path) -> None:
        """Raw text with non-ASCII characters survives an ASCII process locale."""
        dest = tmp_path / "style.txt"
        content = "h\u00e9llo w\u00f6rld"
        saved = _force_c_locale()
        if saved is None:
            pytest.skip("the C locale is unavailable on this platform")
        try:
            atomic_write_text(dest, content)
        finally:
            locale.setlocale(locale.LC_CTYPE, saved)
        assert dest.read_bytes() == content.encode("utf-8")


class TestOpenEncodingContract:
    """The temporary file is opened with explicit portable text parameters."""

    def test_temp_file_open_arguments_are_explicit(self, tmp_path: Path, monkeypatch) -> None:
        """Writes preserve explicit UTF-8 encoding and disabled newline translation."""
        real_open = open
        calls = []

        def spy(*args, **kwargs):
            calls.append((args, kwargs))
            return real_open(*args, **kwargs)

        monkeypatch.setattr("builtins.open", spy)
        atomic_write_text(tmp_path / "style.txt", "line one\nline two")

        assert calls[0][1]["encoding"] == "utf-8"
        assert calls[0][1]["newline"] == ""


class TestVanishedTempCleanup:
    """Cleanup of an already-deleted temp file stays silent through the real path."""

    def test_vanished_temp_cleanup_logs_no_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """No removal warning is logged when the temp vanished before cleanup."""
        import perplexity_cli.utils.atomic_write as aw

        dest = tmp_path / "data.json"

        def replace_after_vanish(temp_path: Path, _target: Path) -> None:
            temp_path.unlink()
            raise OSError("injected replace failure")

        monkeypatch.setattr(aw, "_replace_temp", replace_after_vanish)
        with caplog.at_level(logging.WARNING):
            with pytest.raises(OSError, match="injected replace failure"):
                atomic_write_json(dest, {"a": 1})
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert not any("Could not remove temporary file" in r.getMessage() for r in warnings)
        assert _temp_files(tmp_path) == []


class TestCleanupWarningNamesTempFile:
    """The removal warning identifies the exact temporary sibling by name."""

    def test_cleanup_warning_contains_temp_file_name(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The removal warning carries the temp file's basename."""
        import perplexity_cli.utils.atomic_write as aw

        dest = tmp_path / "data.json"
        seen: dict[str, Path] = {}

        def failing_replace(temp_path: Path, _target: Path) -> None:
            seen["temp"] = temp_path
            raise OSError("injected replace failure")

        def unremovable_temp(_temp_path: Path) -> None:
            raise OSError("locked")

        monkeypatch.setattr(aw, "_replace_temp", failing_replace)
        monkeypatch.setattr(aw, "_cleanup_temp", unremovable_temp)
        with caplog.at_level(logging.WARNING):
            with pytest.raises(OSError, match="injected replace failure"):
                atomic_write_json(dest, {"a": 1})
        warning = next(r for r in caplog.records if r.levelno == logging.WARNING)
        assert seen["temp"].name in warning.getMessage()
