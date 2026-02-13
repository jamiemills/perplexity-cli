"""File permission utilities for secure file handling."""

import logging
import stat
from pathlib import Path


def verify_secure_permissions(
    file_path: Path,
    expected_permissions: int = 0o600,
    file_type: str = "file",
    logger: logging.Logger | None = None,
) -> None:
    """Verify that a file has secure permissions (0600 by default).

    Args:
        file_path: Path to the file to verify.
        expected_permissions: Expected file permissions (default: 0o600).
        file_type: Descriptive name for error messages (e.g., "token", "cache").
        logger: Optional logger instance for logging errors.

    Raises:
        RuntimeError: If file permissions do not match expected value.
    """
    file_stat = file_path.stat()
    actual_permissions = stat.S_IMODE(file_stat.st_mode)

    if actual_permissions != expected_permissions:
        error_msg = (
            f"{file_type.title()} file has insecure permissions: "
            f"{oct(actual_permissions)}. Expected {oct(expected_permissions)}. "
            f"{file_type.title()} file may have been compromised."
        )

        if logger:
            logger.error(
                f"{file_type.capitalize()} file has insecure permissions: "
                f"{oct(actual_permissions)} (expected {oct(expected_permissions)})"
            )

        raise RuntimeError(error_msg)
