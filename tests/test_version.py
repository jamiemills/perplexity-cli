"""Tests for version utilities."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from perplexity_cli.utils.version import (
    _extract_version_from_data,
    _read_pyproject_version,
    get_api_version,
    get_version,
    get_version_from_pyproject,
)


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


class TestReadPyprojectVersion:
    """Test _read_pyproject_version edge cases."""

    def test_returns_none_when_pyproject_missing(self):
        """Return None when pyproject.toml does not exist."""
        with patch("perplexity_cli.utils.version._get_pyproject_path") as mock_path:
            mock_path.return_value.exists.return_value = False
            assert _read_pyproject_version() is None

    def test_returns_none_on_os_error(self, tmp_path):
        """Return None when an OSError occurs reading pyproject.toml."""
        fake = tmp_path / "pyproject.toml"
        fake.write_text("dummy")
        with (
            patch(
                "perplexity_cli.utils.version._get_pyproject_path",
                return_value=fake,
            ),
            patch("builtins.open", side_effect=OSError("disk error")),
        ):
            assert _read_pyproject_version() is None

    def test_returns_none_on_toml_decode_error(self, tmp_path):
        """Return None when pyproject.toml contains invalid TOML."""
        fake = tmp_path / "pyproject.toml"
        fake.write_bytes(b"[[[invalid toml")
        with patch(
            "perplexity_cli.utils.version._get_pyproject_path",
            return_value=fake,
        ):
            assert _read_pyproject_version() is None


class TestExtractVersionFromData:
    """Test _extract_version_from_data edge cases."""

    def test_returns_none_when_project_not_dict(self):
        """Return None when 'project' key is not a dict."""
        assert _extract_version_from_data({"project": "not-a-dict"}) is None

    def test_returns_none_when_version_not_string(self):
        """Return None when version value is not a string."""
        assert _extract_version_from_data({"project": {"version": 123}}) is None

    def test_returns_none_when_version_empty_string(self):
        """Return None when version is an empty string."""
        assert _extract_version_from_data({"project": {"version": ""}}) is None

    def test_returns_version_string(self):
        """Return the version when it is a valid string."""
        assert _extract_version_from_data({"project": {"version": "1.2.3"}}) == "1.2.3"


class TestGetVersionEdgeCases:
    """Test get_version fallback and error paths."""

    def test_raises_runtime_error_when_no_version_available(self):
        """Raise RuntimeError when both pyproject and metadata fail."""
        get_version.cache_clear()
        with (
            patch(
                "perplexity_cli.utils.version._read_pyproject_version",
                return_value=None,
            ),
            patch(
                "perplexity_cli.utils.version.version",
                side_effect=__import__(
                    "importlib.metadata", fromlist=["PackageNotFoundError"]
                ).PackageNotFoundError("pxcli"),
            ),
        ):
            with pytest.raises(RuntimeError, match="Unable to determine"):
                get_version()
        get_version.cache_clear()


class TestGetVersionFromPyprojectEdgeCases:
    """Test get_version_from_pyproject error path."""

    def test_raises_runtime_error_when_read_fails(self):
        """Raise RuntimeError when _read_pyproject_version returns None."""
        with patch(
            "perplexity_cli.utils.version._read_pyproject_version",
            return_value=None,
        ):
            with pytest.raises(RuntimeError, match=r"pyproject\.toml version"):
                get_version_from_pyproject()
