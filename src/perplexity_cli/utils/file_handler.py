"""File handling utilities for attachment support."""

import logging
import re
from pathlib import Path

from perplexity_cli.api.models import FileAttachment

logger = logging.getLogger(__name__)


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
                    logger.debug(f"Extracted file path from query: {path}")
                elif path.is_dir():
                    _add_directory_files(path, files)
                    logger.debug(f"Extracted directory path from query: {path}")
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

    return sorted(files)


def _add_directory_files(directory: Path, files: set[Path]) -> None:
    """Recursively add all files from a directory.

    Args:
        directory: Directory path to search.
        files: Set to add discovered files to.
    """
    for item in directory.rglob("*"):
        if item.is_file():
            files.add(item.resolve())


def load_attachments(file_paths: list[Path]) -> list[FileAttachment]:
    """Load and create FileAttachment objects from file paths.

    Args:
        file_paths: List of Path objects to files.

    Returns:
        List of FileAttachment objects with content base64-encoded.

    Raises:
        FileNotFoundError: If a file does not exist.
        ValueError: If a path is not a file.
        OSError: If a file cannot be read.
    """
    attachments: list[FileAttachment] = []

    for path in file_paths:
        try:
            attachment = FileAttachment.from_file(path)
            attachments.append(attachment)
            logger.debug(f"Loaded attachment: {path.name} ({attachment.content_type})")
        except (FileNotFoundError, ValueError) as e:
            logger.error(f"Failed to load attachment: {path}: {e}")
            raise
        except OSError as e:
            logger.error(f"Error reading file: {path}: {e}")
            raise

    return attachments
