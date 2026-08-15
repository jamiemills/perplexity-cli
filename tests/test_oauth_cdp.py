"""Tests for OAuth CDP transaction hardening."""

from __future__ import annotations

import asyncio
import json
from types import TracebackType
from unittest.mock import AsyncMock, patch

import pytest
from websockets.exceptions import ConnectionClosed

from perplexity_cli.auth.oauth_handler import ChromeDevToolsClient
from perplexity_cli.utils.exceptions import AuthenticationError


class _ObservedLock:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.waiter_queued = asyncio.Event()

    async def __aenter__(self) -> _ObservedLock:
        if self._lock.locked():
            self.waiter_queued.set()
        await self._lock.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._lock.release()

    def locked(self) -> bool:
        return self._lock.locked()


class TestConcurrentCommands:
    """Concurrency and cancellation guarantees for send_command."""

    @pytest.mark.asyncio
    async def test_concurrent_commands_are_serialised_with_correlated_ids(self) -> None:
        responses = [
            json.dumps({"id": 1, "result": {"cmd": 1}}),
            json.dumps({"id": 2, "result": {"cmd": 2}}),
        ]
        active_recv = 0
        max_active = 0
        index = 0
        first_recv_started = asyncio.Event()
        release_first_recv = asyncio.Event()

        async def recv() -> str:
            nonlocal active_recv, max_active, index
            active_recv += 1
            max_active = max(max_active, active_recv)
            if index == 0:
                first_recv_started.set()
                await release_first_recv.wait()
            active_recv -= 1
            response = responses[index]
            index += 1
            return response

        mock_ws = AsyncMock()
        mock_ws.recv.side_effect = recv
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws

        first = asyncio.create_task(client.send_command("Page.enable"))
        await first_recv_started.wait()
        second = asyncio.create_task(client.send_command("Network.enable"))
        assert client._command_lock.locked()
        release_first_recv.set()
        results = await asyncio.gather(first, second)
        assert results == [{"cmd": 1}, {"cmd": 2}]
        assert client.message_id == 2
        assert max_active == 1

    @pytest.mark.asyncio
    async def test_cancelled_waiter_sends_nothing(self) -> None:
        mock_ws = AsyncMock()
        gate = asyncio.Event()
        recv_started = asyncio.Event()

        async def blocking_recv() -> str:
            recv_started.set()
            await gate.wait()
            return json.dumps({"id": 1, "result": {}})

        mock_ws.recv.side_effect = blocking_recv
        client = ChromeDevToolsClient(9222)
        observed_lock = _ObservedLock()
        client._command_lock = observed_lock
        client.ws = mock_ws

        first = asyncio.create_task(client.send_command("Page.enable"))
        await asyncio.wait_for(recv_started.wait(), timeout=1)
        assert client.message_id == 1

        waiter = asyncio.create_task(client.send_command("Network.enable"))
        await asyncio.wait_for(observed_lock.waiter_queued.wait(), timeout=1)
        assert observed_lock.locked()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert mock_ws.send.call_count == 1
        assert client.message_id == 1

        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

    @pytest.mark.asyncio
    async def test_cancelled_active_caller_releases_lock(self) -> None:
        mock_ws = AsyncMock()
        gate = asyncio.Event()
        recv_started = asyncio.Event()
        recv_calls = 0

        async def recv() -> str:
            nonlocal recv_calls
            recv_calls += 1
            if recv_calls == 1:
                recv_started.set()
                await gate.wait()
            return json.dumps({"id": 2, "result": {"ok": True}})

        mock_ws.recv.side_effect = recv
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws

        first = asyncio.create_task(client.send_command("Page.enable"))
        await recv_started.wait()
        assert client.message_id == 1
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

        result = await asyncio.wait_for(client.send_command("Network.enable"), timeout=1)
        assert result == {"ok": True}


class TestCdpResponseHardening:
    """Timeout and malformed-response handling for CDP transactions."""

    @pytest.mark.asyncio
    async def test_timeout_names_method_not_params(self) -> None:
        mock_ws = AsyncMock()
        gate = asyncio.Event()

        async def blocking_recv() -> str:
            await gate.wait()
            return json.dumps({"id": 1, "result": {}})

        mock_ws.recv.side_effect = blocking_recv
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws

        with patch("perplexity_cli.auth.oauth_handler._CDP_RESPONSE_TIMEOUT", 0.05):
            with pytest.raises(TimeoutError) as exc_info:
                await client.send_command("Page.navigate", {"url": "https://secret.invalid"})
        assert "Page.navigate" in str(exc_info.value)
        assert "secret.invalid" not in str(exc_info.value)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("raw", ["not json{{{", "[1, 2, 3]", "42", '"just a string"'])
    async def test_malformed_or_non_object_message_raises(self, raw: str) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv.return_value = raw
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws
        with pytest.raises(AuthenticationError):
            await client.send_command("Page.enable")

    @pytest.mark.asyncio
    async def test_malformed_result_raises(self) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv.return_value = json.dumps({"id": 1, "result": "not-a-dict"})
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws
        with pytest.raises(AuthenticationError):
            await client.send_command("Page.enable")

    @pytest.mark.asyncio
    async def test_malformed_error_object_raises(self) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv.return_value = json.dumps({"id": 1, "error": "oops"})
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws
        with pytest.raises(AuthenticationError):
            await client.send_command("Page.enable")

    @pytest.mark.asyncio
    async def test_error_missing_message_raises(self) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv.return_value = json.dumps({"id": 1, "error": {"code": -32601}})
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws
        with pytest.raises(AuthenticationError):
            await client.send_command("Page.enable")

    @pytest.mark.asyncio
    async def test_unsolicited_events_ignored(self) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv.side_effect = [
            json.dumps({"method": "Network.requestWillBeSent", "params": {"requestId": "1"}}),
            json.dumps({"id": 1, "result": {"ok": True}}),
        ]
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws
        assert await client.send_command("Page.enable") == {"ok": True}

    @pytest.mark.asyncio
    async def test_closed_socket_raises_with_cause(self) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv.side_effect = ConnectionClosed(None, None)
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws
        with pytest.raises(AuthenticationError) as exc_info:
            await client.send_command("Page.enable")
        assert isinstance(exc_info.value.__cause__, ConnectionClosed)


class TestCloseSemantics:
    """close() idempotence and failure handling."""

    @pytest.mark.asyncio
    async def test_close_at_most_once(self) -> None:
        mock_ws = AsyncMock()
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws
        await client.close()
        await client.close()
        mock_ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_swallows_close_errors(self) -> None:
        mock_ws = AsyncMock()
        mock_ws.close.side_effect = ConnectionClosed(None, None)
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws
        await client.close()
        await client.close()
        assert mock_ws.close.call_count == 1
