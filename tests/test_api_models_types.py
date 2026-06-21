"""Type-level regression tests for ``perplexity_cli.api.models``.

These tests assert that the public dataclass / pydantic field annotations
and helper signatures remain fully typed (no ``typing.Any``) so that
``pyright --strict`` keeps reporting zero diagnostics on this module.
"""

from __future__ import annotations

import typing

import pytest

from perplexity_cli.api import models as models_module
from perplexity_cli.api.models import (
    Answer,
    Block,
    HttpRequestContext,
    QueryInput,
    QueryParams,
    SSEMessage,
)


@pytest.mark.parametrize(
    ("cls", "field_name"),
    [
        (QueryInput, "attachment_urls"),
        (QueryInput, "request_params"),
        (QueryInput, "query"),
        (QueryInput, "model_preference"),
        (HttpRequestContext, "json_data"),
        (QueryParams, "mentions"),
        (QueryParams, "client_coordinates"),
        (Block, "content"),
        (SSEMessage, "blocks"),
        (Answer, "references"),
    ],
)
def test_field_annotation_has_no_any(cls: object, field_name: str) -> None:
    """No field annotation should mention ``Any`` after the refactor."""
    hints = typing.get_type_hints(cls)
    source = repr(hints[field_name])
    assert "Any" not in source, f"{cls}.{field_name} still mentions Any: {source}"


@pytest.mark.parametrize(
    ("func_name",),
    [
        ("_as_object_dict",),
        ("_as_object_list",),
    ],
)
def test_narrowing_helpers_exist_and_are_typed(func_name: str) -> None:
    """Module-level narrowing helpers must be present and callable."""
    func = getattr(models_module, func_name)
    hints = typing.get_type_hints(func)
    assert "return" in hints, f"{func_name} missing return annotation"
    source = repr(hints)
    assert "Any" not in source, f"{func_name} mentions Any: {source}"


def test_extract_methods_return_optional_str_or_typed() -> None:
    """Public extractor methods must keep their declared return types."""
    text_hints = typing.get_type_hints(Block.extract_text)
    assert text_hints["return"] == str | None

    plan_hints = typing.get_type_hints(Block.extract_plan_info)
    plan_return = repr(plan_hints["return"])
    assert "dict[str, object]" in plan_return
    assert "Any" not in plan_return

    web_hints = typing.get_type_hints(Block.extract_web_results)
    assert "Any" not in repr(web_hints["return"])


def test_query_params_to_dict_returns_object_value_dict() -> None:
    """``to_dict`` should not leak ``Any`` into its declared return type."""
    hints = typing.get_type_hints(QueryParams.to_dict)
    source = repr(hints["return"])
    assert "Any" not in source


def test_query_input_defaults_produce_typed_containers() -> None:
    """The ``field(default_factory=...)`` defaults must yield typed containers."""
    instance = QueryInput(query="hello")
    assert instance.attachment_urls == []
    assert instance.request_params == {}
    assert isinstance(instance.attachment_urls, list)
    assert isinstance(instance.request_params, dict)
