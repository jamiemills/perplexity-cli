"""Version management utilities."""

import tomllib
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _get_pyproject_path() -> Path:
    """Return the repository pyproject path for source checkouts."""
    return Path(__file__).resolve().parents[3] / "pyproject.toml"


def _read_pyproject_version() -> str | None:
    """Read the project version directly from pyproject.toml if available."""
    pyproject_path = _get_pyproject_path()
    if not pyproject_path.exists():
        return None

    try:
        with pyproject_path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return None

    return _extract_version_from_data(data)


def _extract_version_from_data(data: dict) -> str | None:
    """Extract the version string from parsed pyproject data.

    Args:
        data: Parsed TOML data dictionary.

    Returns:
        Version string if found and valid, None otherwise.
    """
    project = data.get("project")
    if not isinstance(project, dict):
        return None
    package_version = project.get("version")
    if isinstance(package_version, str) and package_version:
        return package_version
    return None


@lru_cache(maxsize=1)
def get_version() -> str:
    """Get the runtime package version.

    Source checkouts prefer `pyproject.toml` so development version changes are
    visible immediately. Installed packages fall back to distribution metadata.

    Returns:
        Version string.
    """
    pyproject_version = _read_pyproject_version()
    if pyproject_version is not None:
        return pyproject_version

    try:
        return version("pxcli")
    except PackageNotFoundError:
        raise RuntimeError("Unable to determine pxcli version") from None


def get_version_from_pyproject() -> str:
    """Read version from pyproject.toml.

    Returns:
        Version string from pyproject.toml.

    Raises:
        RuntimeError: If pyproject.toml cannot be read or parsed.
    """
    package_version = _read_pyproject_version()
    if package_version is None:
        raise RuntimeError("pyproject.toml version could not be read")

    return package_version


def get_api_version() -> str:
    """Get the API version to use in requests.

    Returns:
        API version string (default: "2.18").
    """
    # This could be made configurable in the future
    return "2.18"
