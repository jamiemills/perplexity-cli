"""File handling utilities for attachment support."""

import re
from pathlib import Path

from perplexity_cli.api.models import FileAttachment
from perplexity_cli.utils.exceptions import AttachmentError
from perplexity_cli.utils.logging import get_logger, redact_path

logger = get_logger()

MAX_ATTACHMENT_COUNT = 25
MAX_ATTACHMENT_FILE_SIZE = 10 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_SIZE = 25 * 1024 * 1024
SKIPPED_DIRECTORY_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}
SKIPPED_FILENAME_PREFIXES = (".env",)
SKIPPED_FILENAME_SUFFIXES = (
    ".key",
    ".pem",
    ".p12",
    ".pfx",
    ".crt",
    ".cer",
    ".der",
    ".jks",
    ".p8",
)


def _extract_file_paths_from_text(text: str) -> list[Path]:
    """Extract file paths mentioned in text.

    Looks for absolute paths (starting with / or drive letters for Windows).
    Patterns matched:
    - Unix absolute paths: /path/to/file
    - Windows absolute paths: C:\\path\\to\\file
    - Tilde paths: ~/path/to/file

    Args:
        text: Text that may contain file paths.

    Returns:
        List of Path objects for any paths found.
    """
    paths: set[Path] = set()

    # Pattern for Unix absolute paths with file extensions (/path/to/file.ext)
    # Requires at least one dot (file extension)
    unix_pattern = r"/[a-zA-Z0-9._\-/]+\.[a-zA-Z0-9]+"

    # Pattern for tilde paths (~/path/to/file.ext)
    tilde_pattern = r"~[a-zA-Z0-9._\-/]*\.[a-zA-Z0-9]+"

    # Find all potential paths
    for match in re.finditer(unix_pattern, text):
        candidate = match.group()
        # Remove trailing punctuation that's likely from the sentence
        candidate = candidate.rstrip(".,;:!?'\"")
        path = Path(candidate)
        paths.add(path)

    for match in re.finditer(tilde_pattern, text):
        candidate = match.group()
        candidate = candidate.rstrip(".,;:!?'\"")
        path = Path(candidate).expanduser()
        paths.add(path)

    return sorted(paths)


def resolve_file_arguments(
    query_args: list[str],
    attach_args: list[str] | None = None,
) -> list[Path]:
    """Resolve file paths from query arguments and --attach flags.

    Handles three input methods:
    1. Inline file paths mentioned in query text (e.g., "/tmp/file.md")
    2. --attach flag with comma-separated paths
    3. --attach flag with directory paths (recursive)

    Args:
        query_args: List of query argument strings (may contain file paths).
        attach_args: List of --attach flag values (comma-separated or single paths).

    Returns:
        Sorted list of unique Path objects for files to attach.

    Raises:
        FileNotFoundError: If a specified file/directory does not exist.
        ValueError: If an argument is not a file or directory.
        AttachmentError: If attachment safety limits are exceeded.
    """
    files: set[Path] = set()

    # Extract file paths from query text
    for arg in query_args:
        # Extract any mentioned file paths from the query text
        extracted_paths = _extract_file_paths_from_text(arg)
        for path in extracted_paths:
            if path.exists():
                if path.is_file():
                    files.add(path.resolve())
                    logger.debug(f"Extracted file path from query: {redact_path(path)}")
                elif path.is_dir():
                    _add_directory_files(path, files)
                    logger.debug(f"Extracted directory path from query: {redact_path(path)}")
                else:
                    raise ValueError(f"Not a file or directory: {path}")
            else:
                # Path was mentioned but doesn't exist
                raise FileNotFoundError(f"File or directory not found: {path}")

    # Process --attach flag values
    if attach_args:
        for attach_str in attach_args:
            # Split by comma to support multiple files per flag
            for path_str in attach_str.split(","):
                path_str = path_str.strip()
                if not path_str:
                    continue
                path = Path(path_str).expanduser()
                if not path.exists():
                    raise FileNotFoundError(f"File or directory not found: {path}")
                if path.is_file():
                    files.add(path.resolve())
                elif path.is_dir():
                    _add_directory_files(path, files)
                else:
                    raise ValueError(f"Not a file or directory: {path}")

    resolved_files = sorted(files)

    if len(resolved_files) > MAX_ATTACHMENT_COUNT:
        raise AttachmentError(
            f"Too many attachments: {len(resolved_files)} files exceeds the limit of "
            f"{MAX_ATTACHMENT_COUNT}"
        )

    return resolved_files


def _should_skip_directory_entry(path: Path) -> bool:
    """Return True when a directory entry should be skipped by default."""
    name = path.name

    if name in SKIPPED_DIRECTORY_NAMES:
        return True
    if name.startswith("."):
        return True
    if name.startswith(SKIPPED_FILENAME_PREFIXES):
        return True
    if path.suffix.lower() in SKIPPED_FILENAME_SUFFIXES:
        return True

    return False


def _add_directory_files(directory: Path, files: set[Path]) -> None:
    """Recursively add all files from a directory.

    Args:
        directory: Directory path to search.
        files: Set to add discovered files to.
    """
    for item in directory.walk():
        current_dir, dirnames, filenames = item

        dirnames[:] = [
            dirname
            for dirname in dirnames
            if not _should_skip_directory_entry(current_dir / dirname)
            and not (current_dir / dirname).is_symlink()
        ]

        for filename in filenames:
            file_path = current_dir / filename
            if _should_skip_directory_entry(file_path):
                continue
            if file_path.is_symlink():
                logger.debug(
                    f"Skipping symlink during directory attachment: {redact_path(file_path)}"
                )
                continue
            if file_path.is_file():
                files.add(file_path.resolve())


def load_attachments(file_paths: list[Path]) -> list[FileAttachment]:
    """Load and create FileAttachment objects from file paths.

    Args:
        file_paths: List of Path objects to files.

    Returns:
        List of FileAttachment objects with content base64-encoded.

    Raises:
        FileNotFoundError: If a file does not exist.
        ValueError: If a path is not a file.
        AttachmentError: If attachment safety limits are exceeded.
        OSError: If a file cannot be read.
    """
    if len(file_paths) > MAX_ATTACHMENT_COUNT:
        raise AttachmentError(
            f"Too many attachments: {len(file_paths)} files exceeds the limit of "
            f"{MAX_ATTACHMENT_COUNT}"
        )

    attachments: list[FileAttachment] = []
    total_size = 0

    for path in file_paths:
        try:
            file_size = path.stat().st_size
            if file_size > MAX_ATTACHMENT_FILE_SIZE:
                raise AttachmentError(
                    f"Attachment too large: {path.name} exceeds the per-file limit of "
                    f"{MAX_ATTACHMENT_FILE_SIZE} bytes"
                )

            total_size += file_size
            if total_size > MAX_TOTAL_ATTACHMENT_SIZE:
                raise AttachmentError(
                    f"Total attachment size exceeds the limit of {MAX_TOTAL_ATTACHMENT_SIZE} bytes"
                )

            attachment = FileAttachment.from_file(path)
            attachments.append(attachment)
            logger.debug(f"Loaded attachment: {redact_path(path.name)} ({attachment.content_type})")
        except (FileNotFoundError, ValueError) as e:
            logger.error(f"Failed to load attachment: {path}: {e}")
            raise
        except OSError as e:
            logger.error(f"Error reading file: {path}: {e}")
            raise

    return attachments
