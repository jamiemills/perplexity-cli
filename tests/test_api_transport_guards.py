"""Transport-guard behaviour tests for ``perplexity_cli.api.client`` helpers.

Each test pins the observable contract of the untyped-transport shims:
either the guarded operation succeeds with forwarded arguments, or it
fails closed with a stable ``RuntimeError`` describing the offending
boundary. Message assertions are anchored so that wrapped, re-cased or
``None``-message mutations fail.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from types import MappingProxyType
from typing import Any
from unittest.mock import Mock

import pytest

from perplexity_cli.api import client as api_client
from perplexity_cli.api.client import (
    HttpRequestContext,
    RetryHandler,
    SSEClient,
    _close_transport_session,
    _coerce_header_mapping,
    _coerce_header_pair,
    _create_transport_session,
    _iter_object_values,
    _open_stream_context,
    _read_transport_value,
    _StreamContextAdapter,
)
from perplexity_cli.auth.models import AuthContext

CTX = "t008-ctx"


class _ExplodingNext:
    """Iterable whose iterator raises ``TypeError`` on ``next``."""

    def __iter__(self) -> Iterator[object]:
        return self

    def __next__(self) -> object:
        raise TypeError("iterator broke")


class _BadStr:
    """Object whose string conversion fails with a caught exception."""

    def __str__(self) -> str:
        raise KeyError("unstringable")


class _NoStreamSession:
    """Session stand-in without a usable ``stream`` method."""

    def __getattr__(self, name: str) -> Any:
        if name == "stream":
            raise AttributeError("no stream here")
        raise AttributeError(name)


def _request_context(json_data: object = None) -> HttpRequestContext:
    return HttpRequestContext(
        url="https://api.example.test/query",
        headers={"Content-Type": "application/json"},
        json_data=json_data,  # type: ignore[arg-type]  # owner: test-infrastructure; reason: exercise the transport boundary with arbitrary decoded JSON
        effective_timeout=30,
    )


def test_read_transport_value_wraps_attribute_failures() -> None:
    """Attribute failures surface as anchored RuntimeErrors."""

    def _boom() -> object:
        raise AttributeError("missing")

    with pytest.raises(RuntimeError, match=r"^Expected transport attribute for t008-ctx$"):
        _read_transport_value(_boom, CTX)


def test_iter_object_values_rejects_non_iterable() -> None:
    """Non-iterable transport values fail with an anchored message."""
    with pytest.raises(RuntimeError, match=r"^Expected iterable transport value for t008-ctx$"):
        list(_iter_object_values(object(), CTX))


def test_iter_object_values_rejects_failing_iterator() -> None:
    """Mid-iteration TypeErrors fail with an anchored message."""
    with pytest.raises(RuntimeError, match=r"^Expected iterator transport value for t008-ctx$"):
        list(_iter_object_values(_ExplodingNext(), CTX))


def test_coerce_header_pair_rejects_unsized_entry() -> None:
    """Header entries without a size fail closed."""
    with pytest.raises(RuntimeError, match=r"^Expected header pair items for t008-ctx$"):
        _coerce_header_pair(object(), CTX)


def test_coerce_header_pair_rejects_wrong_arity() -> None:
    """Header entries that are not pairs fail closed."""
    with pytest.raises(RuntimeError, match=r"^Expected header pair items for t008-ctx$"):
        _coerce_header_pair(("single",), CTX)


def test_coerce_header_pair_rejects_unstringable_item() -> None:
    """Items whose string conversion raises fail closed."""
    with pytest.raises(RuntimeError, match=r"^Expected header pair items for t008-ctx$"):
        _coerce_header_pair((_BadStr(), "value"), CTX)


def test_coerce_header_pair_stringifies_values() -> None:
    """Valid pairs are coerced to a string tuple."""
    assert _coerce_header_pair(("k", 42), CTX) == ("k", "42")


def test_coerce_header_mapping_rejects_non_mapping() -> None:
    """Values without ``items`` fail closed."""
    with pytest.raises(
        RuntimeError, match=r"^Expected mapping-like transport attribute for t008-ctx$"
    ):
        _coerce_header_mapping(object(), CTX)


def test_coerce_header_mapping_context_flows_to_iteration_errors() -> None:
    """Iteration failures report the caller-supplied context label."""

    class _BrokenItems:
        def items(self) -> int:
            return 42

    with pytest.raises(RuntimeError, match=f"for {CTX}$"):
        _coerce_header_mapping(_BrokenItems(), CTX)


def test_coerce_header_mapping_context_flows_to_pair_errors() -> None:
    """Pair-coercion failures report the caller-supplied context label."""

    class _OddItems:
        def items(self) -> list[tuple[object, ...]]:
            return [("lonely",)]

    with pytest.raises(RuntimeError, match=f"for {CTX}$"):
        _coerce_header_mapping(_OddItems(), CTX)


def test_coerce_header_mapping_stringifies_pairs() -> None:
    """A mapping-like value coerces into a plain string dictionary."""
    headers = MappingProxyType({"cf-ray": 7})

    assert _coerce_header_mapping(headers, CTX) == {"cf-ray": "7"}


def test_create_transport_session_passes_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The configured timeout reaches the session factory unchanged."""
    recorded: dict[str, object] = {}

    def _factory(**kwargs: object) -> object:
        recorded.update(kwargs)
        return Mock()

    monkeypatch.setattr("perplexity_cli.utils.session_factory.create_sync_session", _factory)

    _create_transport_session(29)

    assert recorded == {"timeout": 29}


def test_create_transport_session_wraps_factory_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Factory failures fail closed with an anchored message."""

    def _boom(**kwargs: object) -> object:
        raise AttributeError("gone")

    monkeypatch.setattr("perplexity_cli.utils.session_factory.create_sync_session", _boom)

    with pytest.raises(
        RuntimeError, match=r"^Expected callable create_sync_session transport factory$"
    ):
        _create_transport_session(29)


def test_close_transport_session_calls_close_once() -> None:
    """A healthy session is closed exactly once."""

    class _RecordingSession:
        def __init__(self) -> None:
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1

    session = _RecordingSession()

    _close_transport_session(session)

    assert session.close_calls == 1


def test_sse_client_close_closes_and_forgets_transport() -> None:
    """The public client close boundary closes its session exactly once."""
    client = SSEClient(auth=AuthContext(token="t008-token"))
    session = Mock()
    client._client = session

    client.close()

    session.close.assert_called_once_with()
    assert client._client is None


def test_close_transport_session_wraps_close_failure() -> None:
    """Broken session.close implementations fail closed."""

    class _BrokenClose:
        def close(self) -> None:
            raise TypeError("cannot close")

    with pytest.raises(RuntimeError, match=r"^Expected callable session\.close transport method$"):
        _close_transport_session(_BrokenClose())


def test_open_stream_context_forwards_request_details() -> None:
    """The transport receives method, URL, body, cookies and timeout."""
    session = Mock()
    ctx = _request_context({"query": "t008"})
    cookies = {"cf_clearance": "t008-cookie"}

    _open_stream_context(session, ctx, cookies)

    session.stream.assert_called_once_with(
        "POST",
        ctx.url,
        headers=ctx.headers,
        json={"query": "t008"},
        cookies=cookies,
        timeout=30,
    )


def test_sse_client_stream_post_enters_and_exits_transport_context() -> None:
    """The public streaming boundary uses and exits the transport context."""
    client = SSEClient(auth=AuthContext(token="t008-token"), max_retries=1)
    response = Mock(ok=True, status_code=200, reason="OK", headers={})
    response.iter_lines.return_value = []
    context = Mock()
    context.__enter__ = Mock(return_value=response)
    context.__exit__ = Mock(return_value=None)
    session = Mock()
    session.stream.return_value = context
    client._client = session

    assert list(client.stream_post("https://api.example.test/q", {})) == []

    context.__enter__.assert_called_once_with()
    context.__exit__.assert_called_once_with(None, None, None)


def test_open_stream_context_requires_object_body() -> None:
    """Non-object bodies fail before reaching the transport."""

    class _RecordingSession:
        def __init__(self) -> None:
            self.stream_called = False

        def stream(self, *args: object, **kwargs: object) -> object:
            self.stream_called = True
            return Mock()

    session = _RecordingSession()

    with pytest.raises(
        RuntimeError, match=r"^Expected JSON object transport attribute for stream\.json$"
    ):
        _open_stream_context(session, _request_context(["bad"]), {})

    assert session.stream_called is False


def test_open_stream_context_wraps_missing_stream() -> None:
    """Sessions without ``stream`` fail closed."""
    with pytest.raises(RuntimeError, match=r"^Expected callable session\.stream transport method$"):
        _open_stream_context(_NoStreamSession(), _request_context(), {})


def test_response_adapter_iter_lines_requires_callable() -> None:
    """Responses lacking ``iter_lines`` fail closed."""
    adapter = api_client._ResponseAdapter(object())

    with pytest.raises(
        RuntimeError, match=r"^Expected callable response\.iter_lines transport method$"
    ):
        list(adapter.iter_lines())


def test_response_adapter_iter_lines_rejects_non_sequence() -> None:
    """Non-iterable line sources fail closed."""
    response = Mock()
    response.iter_lines.return_value = 42
    adapter = api_client._ResponseAdapter(response)

    with pytest.raises(
        RuntimeError, match=r"^Expected iterable transport value for response\.iter_lines$"
    ):
        list(adapter.iter_lines())


def test_response_adapter_iter_lines_rejects_non_string_items() -> None:
    """Lines that are neither bytes nor strings fail closed."""
    response = Mock()
    response.iter_lines.return_value = [123]
    adapter = api_client._ResponseAdapter(response)

    with pytest.raises(
        RuntimeError, match=r"^Expected bytes or string lines from response\.iter_lines$"
    ):
        list(adapter.iter_lines())


def test_response_adapter_iter_lines_yields_lines() -> None:
    """Bytes and string lines pass through untouched."""
    response = Mock()
    response.iter_lines.return_value = [b"a", "b"]
    adapter = api_client._ResponseAdapter(response)

    assert list(adapter.iter_lines()) == [b"a", "b"]


def test_stream_context_enter_wraps_failure() -> None:
    """Broken context-manager entry fails closed."""

    class _NoEnter:
        def __getattr__(self, name: str) -> Any:
            raise AttributeError(name)

    with pytest.raises(RuntimeError, match=r"^Expected __enter__ on stream context manager$"):
        with _StreamContextAdapter(_NoEnter()):
            pass


def test_stream_context_exit_forwards_exc_info() -> None:
    """__exit__ receives the original exception triple verbatim."""
    recorded: dict[str, object] = {}
    exc_type = RuntimeError
    exc_value = ValueError("t008-boom")
    traceback = object()

    class _RecordingContext:
        def __enter__(self) -> object:
            return Mock()

        def __exit__(
            self,
            entered_type: type[BaseException] | None,
            entered_value: BaseException | None,
            entered_traceback: object,
        ) -> bool:
            recorded["args"] = (entered_type, entered_value, entered_traceback)
            return False

    adapter = _StreamContextAdapter(_RecordingContext())
    adapter.__enter__()
    result = adapter.__exit__(exc_type, exc_value, traceback)

    assert result is False
    assert recorded["args"] == (exc_type, exc_value, traceback)


def test_stream_context_exit_wraps_failure() -> None:
    """Broken context-manager exit fails closed."""

    class _NoExit:
        def __enter__(self) -> object:
            return Mock()

        def __getattr__(self, name: str) -> Any:
            if name == "__exit__":
                raise AttributeError("no exit")
            raise AttributeError(name)

    adapter = _StreamContextAdapter(_NoExit())
    adapter.__enter__()

    with pytest.raises(RuntimeError, match=r"^Expected __exit__ on stream context manager$"):
        adapter.__exit__(None, None, None)


def test_stream_context_exit_validates_result_type() -> None:
    """Non-bool, non-None exit results fail closed."""

    class _StringyExit:
        def __enter__(self) -> object:
            return Mock()

        def __exit__(
            self,
            entered_type: type[BaseException] | None,
            entered_value: BaseException | None,
            entered_traceback: object,
        ) -> object:
            return "invalid"

    adapter = _StreamContextAdapter(_StringyExit())
    adapter.__enter__()

    with pytest.raises(
        RuntimeError, match=r"^Expected bool-or-None return from stream context manager$"
    ):
        adapter.__exit__(None, None, None)


def test_standard_search_mode_is_not_deep_research() -> None:
    """Plain string values do not trigger the deep-research timeout."""
    resolved = SSEClient(auth=AuthContext(token="t008-token"), timeout=45)

    is_deep, effective_timeout = resolved._resolve_effective_timeout(
        {"params": {"search_mode": "standard"}}
    )

    assert (is_deep, effective_timeout) == (False, 45)


def _wired_stream_client() -> tuple[SSEClient, Mock]:
    """Build a client whose transport returns one empty successful stream."""
    response = Mock()
    response.ok = True
    response.status_code = 200
    response.reason = "OK"
    response.headers = {}
    response.iter_lines.return_value = []
    context = Mock()
    context.__enter__ = Mock(return_value=response)
    context.__exit__ = Mock(return_value=False)
    session = Mock()
    session.stream.return_value = context
    client = SSEClient(auth=AuthContext(token="t008-token"))
    client._client = session
    return client, session


def test_unhashable_mode_values_do_not_select_deep_research() -> None:
    """Non-string mode values are ignored, never probed for set membership."""
    client, session = _wired_stream_client()

    events = list(
        client.stream_post(
            "https://api.example.test/s",
            {"params": {"searchModeOverride": ["t008-not-a-string"]}},
        )
    )

    assert events == []
    assert session.stream.call_count == 1


class TestRequestExceptionGuard:
    """Availability gating of the transport-exception classifier."""

    @staticmethod
    def _exhausted_handler() -> RetryHandler:
        return RetryHandler(logging.getLogger("t008-guard"), max_retries=1)

    def test_unavailable_transport_exceptions_are_not_classified(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without curl_cffi the classifier must answer False for lookalikes."""
        monkeypatch.setattr(api_client, "_curl_cffi_available", False)
        monkeypatch.setattr(api_client, "_CurlRequestException", ValueError)
        error = ValueError("t008-not-a-transport-error")

        with pytest.raises(ValueError) as exc_info:
            self._exhausted_handler().handle_network_error(error, 0)

        assert exc_info.value is error

    def test_guard_short_circuits_when_flag_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A missing availability flag disables classification outright."""
        monkeypatch.setattr(api_client, "_curl_cffi_available", False)
        monkeypatch.setattr(api_client, "_CurlRequestException", None)

        assert api_client._is_request_exception(RuntimeError("t008-generic")) is False


def test_get_client_forwards_configured_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The configured timeout reaches the session factory unchanged."""
    recorded: dict[str, object] = {}

    def _factory(**kwargs: object) -> object:
        recorded.update(kwargs)
        return object()

    monkeypatch.setattr("perplexity_cli.utils.session_factory.create_sync_session", _factory)
    client = SSEClient(auth=AuthContext(token="t008-token"), timeout=64)

    client._get_client()

    assert recorded == {"timeout": 64}
