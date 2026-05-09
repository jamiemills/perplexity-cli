"""Tests for perplexity_cli.utils.async_bridge."""

import asyncio

from perplexity_cli.utils.async_bridge import run_async


async def async_add(a: int, b: int) -> int:
    return a + b


async def async_raise() -> None:
    raise ValueError("test error")


async def async_return_list() -> list[int]:
    return [1, 2, 3]


async def async_return_none() -> None:
    return None


class TestRunAsync:
    """Tests for run_async function."""

    def test_simple_coroutine(self):
        result = run_async(async_add(3, 4))
        assert result == 7

    def test_exception_propagation(self):
        import pytest

        with pytest.raises(ValueError, match="test error"):
            run_async(async_raise())

    def test_return_type_preserved(self):
        result = run_async(async_return_list())
        assert isinstance(result, list)
        assert result == [1, 2, 3]

    def test_nested_loop_handling(self):
        """run_async works when called from within a running event loop."""

        async def outer():
            return run_async(async_add(10, 20))

        result = asyncio.run(outer())
        assert result == 30

    def test_none_return(self):
        result = run_async(async_return_none())
        assert result is None
