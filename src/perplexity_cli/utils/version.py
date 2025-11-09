"""Version management utilities."""

import re
from pathlib import Path

from perplexity_cli import __version__


def get_version_from_pyproject() -> str:
    """Read version from pyproject.toml.

    Returns:
        Version string from pyproject.toml.

    Raises:
        RuntimeError: If pyproject.toml cannot be read or parsed.
    """
    # Try to find pyproject.toml relative to this file
    current_file = Path(__file__)
    # Go up from utils/ -> perplexity_cli/ -> src/ -> project root
    project_root = current_file.parent.parent.parent.parent

    pyproject_path = project_root / "pyproject.toml"

    if not pyproject_path.exists():
        # Fallback to __version__ if pyproject.toml not found
        return __version__

    try:
        # Read pyproject.toml as text and extract version
        # This avoids needing tomllib which may not be available in all Python versions
        with open(pyproject_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Look for version = "x.y.z" pattern
            match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                return match.group(1)
    except Exception:
        pass
    
    # Fallback to __version__ if parsing fails
    return __version__


def get_version() -> str:
    """Get the current version of the package.

    Returns:
        Version string.
    """
    return get_version_from_pyproject()


def get_api_version() -> str:
    """Get the API version to use in requests.

    Returns:
        API version string (default: "2.18").
    """
    # This could be made configurable in the future
    return "2.18"

