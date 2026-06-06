"""File handling utilities for attachment support."""

import re
from pathlib import Path

from perplexity_cli.utils.attachment_models import FileAttachment
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


def _resolve_path(path: Path, files: set[Path]) -> None:
    """Resolve a single path, adding it to the file set.

    Args:
        path: Path to resolve (must exist).
        files: Set to add discovered files to.

    Raises:
        ValueError: If the path is neither a file nor a directory.
    """
    if path.is_file():
        files.add(path.resolve())
    elif path.is_dir():
        _add_directory_files(path, files)
    else:
        raise ValueError(f"Not a file or directory: {path}")


def _process_query_paths(query_args: list[str], files: set[Path]) -> None:
    """Extract and resolve file paths mentioned in query text.

    Args:
        query_args: List of query argument strings.
        files: Set to add discovered files to.

    Raises:
        FileNotFoundError: If an extracted path does not exist.
        ValueError: If a path is neither a file nor a directory.
    """
    for arg in query_args:
        for path in _extract_file_paths_from_text(arg):
            if not path.exists():
                raise FileNotFoundError(f"File or directory not found: {path}")
            _resolve_path(path, files)
            logger.debug("Extracted path from query: %s", redact_path(path))


def _resolve_attach_path(path_str: str, files: set[Path]) -> None:
    """Resolve a single --attach path string.

    Args:
        path_str: A single path string (already stripped).
        files: Set to add discovered files to.

    Raises:
        FileNotFoundError: If the path does not exist.
        ValueError: If the path is neither a file nor a directory.
    """
    path = Path(path_str).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"File or directory not found: {path}")
    _resolve_path(path, files)


def _process_attach_args(attach_args: list[str] | None, files: set[Path]) -> None:
    """Resolve file paths from --attach flag values.

    Args:
        attach_args: List of comma-separated path strings, or None.
        files: Set to add discovered files to.

    Raises:
        FileNotFoundError: If a specified path does not exist.
        ValueError: If a path is neither a file nor a directory.
    """
    if not attach_args:
        return
    for attach_str in attach_args:
        for path_str in attach_str.split(","):
            path_str = path_str.strip()
            if path_str:
                _resolve_attach_path(path_str, files)


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
    _process_query_paths(query_args, files)
    _process_attach_args(attach_args, files)

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


def _should_include_file(file_path: Path) -> bool:
    """Determine whether a file should be included as an attachment.

    Args:
        file_path: Path to the file to check.

    Returns:
        True if the file should be included, False otherwise.
    """
    if _should_skip_directory_entry(file_path):
        return False
    if file_path.is_symlink():
        logger.debug("Skipping symlink during directory attachment: %s", redact_path(file_path))
        return False
    return file_path.is_file()


def _add_directory_files(directory: Path, files: set[Path]) -> None:
    """Recursively add all files from a directory.

    Args:
        directory: Directory path to search.
        files: Set to add discovered files to.
    """
    for current_dir, dirnames, filenames in directory.walk():
        dirnames[:] = _filter_subdirectories(current_dir, dirnames)
        for filename in filenames:
            file_path = current_dir / filename
            if _should_include_file(file_path):
                files.add(file_path.resolve())


def _filter_subdirectories(current_dir: Path, dirnames: list[str]) -> list[str]:
    """Filter subdirectories, removing those that should be skipped.

    Args:
        current_dir: The current directory being walked.
        dirnames: List of subdirectory names.

    Returns:
        Filtered list of subdirectory names to descend into.
    """
    return [
        d
        for d in dirnames
        if not _should_skip_directory_entry(current_dir / d) and not (current_dir / d).is_symlink()
    ]


def _load_single_attachment(path: Path, total_size: int) -> tuple[FileAttachment, int]:
    """Load a single file as a FileAttachment and update the running total size.

    Args:
        path: Path to the file to load.
        total_size: Current cumulative size of all attachments so far.

    Returns:
        Tuple of (FileAttachment, updated total size in bytes).

    Raises:
        AttachmentError: If size limits are exceeded.
        FileNotFoundError: If the file does not exist.
        ValueError: If the path is not a file.
        OSError: If the file cannot be read.
    """
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
    logger.debug("Loaded attachment: %s (%s)", redact_path(path.name), attachment.content_type)
    return attachment, total_size


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
            attachment, total_size = _load_single_attachment(path, total_size)
            attachments.append(attachment)
        except (FileNotFoundError, ValueError) as e:
            logger.error("Failed to load attachment: %s: %s", path, e)
            raise
        except OSError as e:
            logger.error("Error reading file: %s: %s", path, e)
            raise

    return attachments
