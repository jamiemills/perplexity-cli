"""Direct unit tests for the ``_versioned`` helper in ``_examples.py``.

These tests live in a file that is NOT excluded from mutmut, so mutations
to the version-substitution logic are caught.  The drift-integration test
in ``test_help_doc_drift.py`` verifies the end-to-end help rendering but
is excluded from mutmut (it reads repo files)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from perplexity_cli.commands._examples import _versioned


class TestVersioned:
    """Tests for :func:`_versioned` in the context of actual module-level state."""

    def test_replaces_placeholder_with_runtime_version(self) -> None:
        """When _VERSION != _PLACEHOLDER_VERSION, the placeholder is replaced."""
        result = _versioned('{"version": "0.7.0"}')
        # The actual _VERSION from get_version() is injected at import time.
        assert "0.7.0" not in result
        assert "version" in result

    def test_applies_replace_across_multiple_occurrences(self) -> None:
        """Every occurrence of the placeholder version is replaced."""
        example = '{"a": {"version": "0.7.0"}, "b": {"version": "0.7.0"}}'
        result = _versioned(example)
        assert "0.7.0" not in result

    def test_no_effect_when_no_placeholder_present(self) -> None:
        """When the placeholder is absent, the string is returned unchanged."""
        result = _versioned('{"version": "9.9.9"}')
        assert "9.9.9" in result
        assert "0.7.0" not in result

    @patch("perplexity_cli.utils.version.get_version", return_value="0.7.0")
    def test_early_return_when_versions_match(
        self, _mock_version: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the runtime version matches the placeholder, the string is returned unchanged.

        We must reload the module so that ``_VERSION`` picks up the mocked
        ``get_version()`` return value.  ``_examples.py`` sets ``_VERSION`` at
        module scope, so we patch and re-import to get the early-return branch.
        """
        from perplexity_cli.commands import _examples

        monkeypatch.setattr(_examples, "_VERSION", "0.7.0")
        # The _PLACEHOLDER_VERSION is "0.7.0" — they now match.
        result = _examples._versioned('{"version": "0.7.0"}')
        assert result == '{"version": "0.7.0"}'
        assert "0.7.0" in result
