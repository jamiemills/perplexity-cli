"""Type-introspection tests for ``utils/upstream_contracts``.

These tests pin down the public typing contract that Wave 1A established so
the pyright-strict ratchet keeps shrinking instead of regressing. The two
parse helpers and the ``require_*`` return annotations still reference
``Any`` because callers in ``attachments/upload_manager.py`` and
``threads/scraper.py`` perform untyped nested-mapping access on their
results; widening those to ``object`` is queued for the agent that owns
those consumer files.
"""

from __future__ import annotations

import typing
from collections.abc import Callable
from typing import Any

from perplexity_cli.utils import upstream_contracts

INPUT_FUNCS: list[Callable[..., object]] = [
    upstream_contracts.describe_payload_shape,
    upstream_contracts.schema_error,
    upstream_contracts.require_mapping,
    upstream_contracts.require_list,
]


def _iter_type_parts(hint: object) -> typing.Iterator[object]:
    """Yield ``hint`` and every nested type-argument recursively."""
    yield hint
    for arg in typing.get_args(hint):
        yield from _iter_type_parts(arg)


def test_input_funcs_accept_object_not_any() -> None:
    """The ``value`` parameter must be ``object`` (no ``Any`` escape hatch)."""
    for func in INPUT_FUNCS:
        hints = typing.get_type_hints(func)
        assert hints["value"] is object, f"{func.__name__}.value is not object"


def test_describe_payload_shape_returns_str() -> None:
    """``describe_payload_shape`` must promise a ``str`` return."""
    hints = typing.get_type_hints(upstream_contracts.describe_payload_shape)
    assert hints["return"] is str


def test_schema_error_returns_upstream_error() -> None:
    """``schema_error`` must promise the schema-error exception type."""
    from perplexity_cli.utils.exceptions import UpstreamSchemaError

    hints = typing.get_type_hints(upstream_contracts.schema_error)
    assert hints["return"] is UpstreamSchemaError


def test_shape_describers_are_typed_callables() -> None:
    """Each shape describer must be a real, annotated callable."""
    describers = upstream_contracts._SHAPE_DESCRIBERS
    for describer in describers.values():
        hints = typing.get_type_hints(describer)
        assert hints["return"] is str, "describer must return str"
        assert hints["value"] is object, "describer must accept object"


def test_type_guards_narrow_to_typed_containers() -> None:
    """The TypeGuard helpers must narrow to fully-typed containers."""
    mapping_hint = typing.get_type_hints(upstream_contracts._is_mapping)["return"]
    sequence_hint = typing.get_type_hints(upstream_contracts._is_sequence)["return"]
    assert typing.get_args(mapping_hint) == (dict[str, object],)
    assert typing.get_args(sequence_hint) == (list[object],)


def test_describers_dispatch_dict_and_list_and_str() -> None:
    """The dispatch table covers the three JSON container kinds."""
    keys = set(upstream_contracts._SHAPE_DESCRIBERS)
    assert keys == {dict, list, str}


def test_any_usage_does_not_grow_beyond_known_set() -> None:
    """Only the four documented public-API sites may reference ``Any``."""
    allowed: set[str] = {
        "require_mapping.return",
        "require_list.return",
        "parse_upload_url_response.payload",
        "parse_upload_url_response.return",
        "parse_thread_list_payload.payload",
        "parse_thread_list_payload.return",
    }
    public_funcs = [
        upstream_contracts.describe_payload_shape,
        upstream_contracts.schema_error,
        upstream_contracts.require_mapping,
        upstream_contracts.require_list,
        upstream_contracts.parse_upload_url_response,
        upstream_contracts.parse_thread_list_payload,
    ]
    offenders: set[str] = set()
    for func in public_funcs:
        hints = typing.get_type_hints(func)
        for name, hint in hints.items():
            if Any in set(_iter_type_parts(hint)):
                offenders.add(f"{func.__name__}.{name}")
    assert offenders <= allowed, "unexpected Any sites: " + ", ".join(offenders - allowed)
