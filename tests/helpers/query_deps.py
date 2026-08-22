"""Helpers for patching :class:`QueryDeps` collaborators in tests."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from perplexity_cli import query_deps as qd


def patch_query_deps(monkeypatch: Any, **overrides: Any) -> None:
    """Replace selected collaborators for one test, auto-restored."""
    base = qd._deps if qd._deps is not None else qd.make_query_deps()
    replacement = qd.replace(base, **overrides)
    monkeypatch.setattr(qd, "_deps", replacement)


def patched_dep(name: str, dep: Any):
    """Context manager yielding ``dep`` installed under ``name``."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        base = qd._deps if qd._deps is not None else qd.make_query_deps()
        previous = qd._deps
        set = qd.replace(base, **{name: dep})
        qd.set_query_deps(set)
        try:
            yield dep
        finally:
            qd.set_query_deps(previous)

    return _ctx()


def patched_dep_decorator(name: str, dep: Any = None, **kwargs: Any):
    """Decorator mirroring ``unittest.mock.patch`` stacking semantics.

    Inner applications only record metadata; the outermost builds one active
    wrapper that installs every recorded collaborator and passes the mocks
    positionally, exactly like stacked ``@patch`` decorators.
    """
    import functools
    from unittest import mock as _ut_mock
    from unittest.mock import Mock

    resolved = dep if dep is not None else Mock(**kwargs)

    def decorator(func):
        pending = getattr(func, "_pd_pending", [])
        new_pending = [(name, resolved), *pending]
        if getattr(func, "_pd_is_wrapper", False):
            func._pd_pending = new_pending  # type: ignore[attr-defined]  # owner: quality-infrastructure; reason: dynamic attribute on function object for decorator stacking
            return func

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs2: Any) -> Any:
            base = qd._deps if qd._deps is not None else qd.make_query_deps()
            previous = qd._deps
            overrides = dict(reversed(new_pending))
            qd.set_query_deps(replace(base, **overrides))
            try:
                call_args = list(args)
                first_param = next(iter(func.__code__.co_varnames), "")
                if call_args and first_param == "self":
                    call_args = (
                        call_args[:1]
                        + [value for _, value in reversed(new_pending)]
                        + call_args[1:]
                    )
                else:
                    call_args = [value for _, value in reversed(new_pending)] + call_args
                return func(*call_args, **kwargs2)
            finally:
                qd.set_query_deps(previous)

        class _Patching:
            new = _ut_mock.DEFAULT
            attribute_name = None

        wrapper._pd_pending = new_pending  # type: ignore[attr-defined]  # owner: quality-infrastructure; reason: dynamic attribute on function object for decorator stacking
        wrapper._pd_is_wrapper = True  # type: ignore[attr-defined]  # owner: quality-infrastructure; reason: dynamic attribute on function object for decorator stacking
        wrapper.patchings = [_Patching() for _ in range(len(new_pending))]  # type: ignore[attr-defined]  # owner: quality-infrastructure; reason: pytest mock-patch bookkeeping requires dynamic attribute
        return wrapper

    return decorator
