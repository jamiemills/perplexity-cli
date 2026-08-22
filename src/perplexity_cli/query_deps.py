"""Typed dependency container for the query orchestration seam.

The application layer may not statically import adapter or presentation
modules, so :mod:`perplexity_cli.query_runner` receives its collaborators
through this frozen container.  The composition root (:mod:`perplexity_cli.cli`)
constructs it once at import time; tests install fakes by building another
container and monkeypatching the single ``_deps`` attribute.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class QueryDeps:
    """Collaborators required by :mod:`perplexity_cli.query_runner`.

    Field order mirrors the historical seam declarations so diffs stay
    reviewable.  Types are ``Callable`` contracts rather than concrete
    adapter classes precisely because those classes live in outer layers.
    """

    handle_error: Callable[..., Any]
    get_logger: Callable[..., Any]
    redact_path: Callable[[str], str]
    redact_text: Callable[[str], str]
    redact_url: Callable[[str], str]
    get_config_paths: Callable[[], Any]
    get_save_cookies_enabled: Callable[[], bool]
    get_formatter: Callable[[str], Any]
    list_formatters: Callable[[], list[str]]
    StyleManager: type
    TokenManager: type
    load_token_optional: Callable[[], tuple[str | None, dict[str, str] | None]]
    PerplexityAPI: type
    resolve_file_arguments: Callable[..., Any]
    load_attachments: Callable[..., Any]
    run_async: Callable[..., Any]
    AttachmentUploader: type


_deps: QueryDeps | None = None


def bind_query_deps(container: QueryDeps) -> None:
    """Install the composition-root container (idempotent per test setup)."""
    set_query_deps(container)


def set_query_deps(container: QueryDeps | None) -> None:
    """Replace the module-level container reference."""
    # Single deliberate mutable binding for the composition seam; enforced
    # frozen contents make this the only assignment site.
    globals()["_deps"] = container


def require_query_deps() -> QueryDeps:
    """Return the bound container, failing fast when unbound."""
    if _deps is None:
        msg = (
            "query dependencies are not bound; the composition root "
            "(perplexity_cli.cli) must call bind_query_deps()"
        )
        raise RuntimeError(msg)
    return _deps


def make_query_deps(**overrides: Any) -> QueryDeps:
    """Build a container with inert placeholders overridden per test."""

    def _unused(*_args: Any, **_kwargs: Any) -> Any:
        msg = "placeholder collaborator must not be invoked"
        raise AssertionError(msg)

    defaults: dict[str, Any] = {f.name: _unused for f in fields(QueryDeps)}
    defaults.update(overrides)
    return QueryDeps(**defaults)


def override_query_deps(monkeypatch: Any, **overrides: Any) -> QueryDeps:
    """Swap selected collaborators on the bound container for one test.

    The monkeypatch fixture is accepted so callers keep the standard test
    signature; restoration happens through :func:`set_query_deps` in the
    caller's teardown via ``monkeypatch.setattr`` on ``query_deps._deps``.
    """
    del monkeypatch
    base = _deps if _deps is not None else make_query_deps()
    replacement = replace(base, **overrides)
    set_query_deps(replacement)
    return base
