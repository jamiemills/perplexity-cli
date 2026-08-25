"""Tests for the typed dependency container module."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from perplexity_cli import query_deps
from perplexity_cli.query_deps import (
    bind_query_deps,
    make_query_deps,
    override_query_deps,
    require_query_deps,
)


class TestQueryDeps:
    """Container defaults and override behaviour (no global mutation)."""

    def test_make_query_deps_rejects_placeholder_calls(self) -> None:
        container = make_query_deps()
        with pytest.raises(AssertionError, match="placeholder"):
            container.handle_error()

    def test_override_returns_previous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        original = require_query_deps()
        replacement = override_query_deps(monkeypatch, PerplexityAPI=Mock())
        assert replacement is original
        # monkeypatch teardown restores the original container.

    def test_override_fields_are_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_api = Mock()
        original = require_query_deps()
        override_query_deps(monkeypatch, PerplexityAPI=fake_api)
        current = require_query_deps()
        assert current.PerplexityAPI is fake_api
        assert current is not original

    def test_bind_and_require_share_the_installed_container(self, monkeypatch):
        """The composition seam returns exactly the container that was bound."""
        container = make_query_deps()
        monkeypatch.setattr(query_deps, "_deps", None)

        bind_query_deps(container)

        assert require_query_deps() is container

    def test_require_fails_when_the_composition_seam_is_unbound(self, monkeypatch):
        """Consumers receive an actionable error before using missing dependencies."""
        monkeypatch.setattr(query_deps, "_deps", None)

        with pytest.raises(RuntimeError, match="dependencies are not bound"):
            require_query_deps()

    def test_make_query_deps_installs_one_placeholder_for_every_field(self) -> None:
        """Every unconfigured collaborator fails with the placeholder contract."""
        container = make_query_deps()
        for field in query_deps.fields(query_deps.QueryDeps):
            with pytest.raises(AssertionError, match="placeholder"):
                getattr(container, field.name)()

    def test_placeholder_and_unbound_errors_keep_actionable_details(self) -> None:
        """Dependency seam failures retain their diagnostic messages."""
        with pytest.raises(AssertionError) as placeholder:
            make_query_deps().handle_error()
        assert str(placeholder.value) == "placeholder collaborator must not be invoked"

    def test_unbound_error_names_the_composition_root(self, monkeypatch) -> None:
        """Unbound consumers receive the complete composition guidance."""
        monkeypatch.setattr(query_deps, "_deps", None)

        with pytest.raises(RuntimeError) as unbound:
            require_query_deps()

        assert str(unbound.value) == (
            "query dependencies are not bound; the composition root "
            "(perplexity_cli.cli) must call bind_query_deps()"
        )

    def test_set_query_deps_syncs_all_legacy_runner_attributes(self, monkeypatch) -> None:
        """Binding mirrors each collaborator for legacy patch/read compatibility."""
        previous = require_query_deps()
        values = {
            field.name: Mock(name=field.name) for field in query_deps.fields(query_deps.QueryDeps)
        }
        container = make_query_deps(**values)
        monkeypatch.setattr(query_deps, "_deps", None)

        try:
            query_deps.set_query_deps(container)

            from perplexity_cli import query_runner

            for field in query_deps.fields(query_deps.QueryDeps):
                assert getattr(query_runner, field.name) is values[field.name]
        finally:
            query_deps.set_query_deps(previous)

    def test_override_without_monkeypatch_rebinds_and_returns_previous(self, monkeypatch) -> None:
        """The explicit non-fixture path installs a replacement and returns its base."""
        original = make_query_deps()
        monkeypatch.setattr(query_deps, "_deps", original)
        replacement_value = Mock()

        previous = override_query_deps(None, PerplexityAPI=replacement_value)

        assert previous is original
        assert require_query_deps().PerplexityAPI is replacement_value
