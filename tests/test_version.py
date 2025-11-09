"""Tests for version utilities."""

import pytest

from perplexity_cli.utils.version import get_api_version, get_version, get_version_from_pyproject


class TestVersionUtilities:
    """Test version utility functions."""

    def test_get_version(self):
        """Test getting version."""
        version = get_version()
        assert isinstance(version, str)
        assert len(version) > 0

    def test_get_version_from_pyproject(self):
        """Test reading version from pyproject.toml."""
        version = get_version_from_pyproject()
        assert isinstance(version, str)
        # Should be in semver format
        assert "." in version

    def test_get_api_version(self):
        """Test getting API version."""
        api_version = get_api_version()
        assert isinstance(api_version, str)
        assert api_version == "2.18"

