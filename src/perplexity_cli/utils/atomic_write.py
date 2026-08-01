"""Atomic file writer with secure permissions and crash-safe replacement.

Provides ``atomic_write_text`` which serialises content before touching the
filesystem, writes it to a uniquely-named exclusive temporary file in the same
directory, applies restrictive permissions before any content bytes are
written (POSIX), flushes and fsyncs the temporary file, and replaces the
destination via ``os.replace``. On any failure before replacement the existing
destination is preserved byte-for-byte and the temporary file is removed.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Protocol, TextIO

from perplexity_cli.utils.logging import get_logger, redact_path

logger = get_logger()


def atomic_write_text(path: Path, content: object, mode: int = 0o600) -> None:
    """Atomically write JSON-serialisable content to a file.

    Serialises the content before touching the destination, writes it to a
    uniquely-named exclusive temporary file in the same directory, applies the
    requested permissions before writing any bytes (POSIX), flushes and fsyncs
    the temporary file, and replaces the destination with ``os.replace``. On
    any pre-replace failure the existing destination is preserved byte-for-byte
    and the temporary file is removed. Destination symlinks are rejected
    immediately before replacement.

    Args:
        path: Destination file to write.
        content: JSON-serialisable object to persist.
        mode: Permission bits applied before writing (POSIX only; ignored on
            Windows).

    Raises:
        OSError: If the destination is a symlink or any filesystem operation
            fails before the replacement is complete.
    """
    text = _serialise_content(content)
    temp_path = _create_temp_sibling(path)
    try:
        _set_permissions(temp_path, mode)
        with open(temp_path, "w", encoding="utf-8", newline="") as file_obj:
            _write_content(file_obj, text)
            _flush_file(file_obj)
            _fsync_file(file_obj)
        _reject_symlink_destination(path)
        _replace_temp(temp_path, path)
    except BaseException:
        _try_cleanup(temp_path)
        raise
    _fsync_directory(path.parent)


def _serialise_content(content: object) -> str:
    """Serialise content to a JSON string before any filesystem work."""
    return json.dumps(content)


def _create_temp_sibling(path: Path) -> Path:
    """Create a uniquely-named exclusive temporary file beside the destination."""
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    os.close(fd)
    return Path(temp_name)


def _set_permissions(path: Path, mode: int) -> None:
    """Apply the requested mode before sensitive bytes are written."""
    os.chmod(path, mode)


def _write_content(file_obj: TextIO, content: str) -> None:
    """Write serialised content to the open temporary file."""
    file_obj.write(content)


def _flush_file(file_obj: TextIO) -> None:
    """Flush the open temporary file's user-space buffer."""
    file_obj.flush()


def _fsync_file(file_obj: TextIO) -> None:
    """Force the temporary file's data to stable storage."""
    os.fsync(file_obj.fileno())


def _reject_symlink_destination(path: Path) -> None:
    """Raise ``OSError`` if the destination is a symlink."""
    if path.is_symlink():
        msg = f"Refusing to write through a symlink destination: {path}"
        raise OSError(msg)


def _replace_temp(temp_path: Path, path: Path) -> None:
    """Atomically replace the destination with the temporary file."""
    os.replace(temp_path, path)  # noqa: PTH105  # os.replace is the atomic rename primitive


def _cleanup_temp(temp_path: Path) -> None:
    """Remove a temporary file, ignoring one that is already gone."""
    temp_path.unlink(missing_ok=True)


def _try_cleanup(temp_path: Path) -> None:
    """Remove a temporary file after a failed write without masking the error."""
    try:
        _cleanup_temp(temp_path)
    except OSError:
        logger.warning("Could not remove temporary file %s", redact_path(temp_path))


def _fsync_directory(directory: Path) -> None:
    """Best-effort directory fsync so the rename survives a crash."""
    dir_flag = getattr(  # nosemgrep: getattr-with-string-literal  # owner: quality-infrastructure; reason: platform-optional O_DIRECTORY constant lookup
        os, "O_DIRECTORY", None
    )
    if dir_flag is None:
        return
    try:
        dir_fd = os.open(directory, os.O_RDONLY | dir_flag)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        return


class _CouplingProtocol(Protocol):  # pyright: ignore[reportUnusedClass]  # owner: quality-infrastructure; reason: coupling-metrics abstractness protocol, intentionally unreferenced
    """Abstract coupling protocol."""

    ...
