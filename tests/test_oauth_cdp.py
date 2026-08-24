"""Tests for OAuth CDP transaction hardening."""

from __future__ import annotations

import asyncio
import json
from types import TracebackType
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from websockets.exceptions import ConnectionClosed

from perplexity_cli.auth.oauth_handler import (
    ChromeDevToolsClient,
    _check_page_loaded,
    _extract_token,
    _fetch_local_storage,
    _navigate_and_wait,
    _poll_for_auth_data,
    _wait_for_page_load,
    authenticate_sync,
    authenticate_with_browser,
)
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
        assert (results, client.message_id, max_active) == ([{"cmd": 1}, {"cmd": 2}], 2, 1)
        sent_ids = [json.loads(item.args[0])["id"] for item in mock_ws.send.call_args_list]
        assert sent_ids == [1, 2]

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
            if recv_calls > 2:
                raise ConnectionClosed(None, None)
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
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1, "result": "not-a-dict"}),
            ConnectionClosed(None, None),
        ]
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws
        with pytest.raises(AuthenticationError):
            await client.send_command("Page.enable")

    @pytest.mark.asyncio
    async def test_malformed_error_object_raises(self) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1, "error": "oops"}),
            ConnectionClosed(None, None),
        ]
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws
        with pytest.raises(AuthenticationError):
            await client.send_command("Page.enable")

    @pytest.mark.asyncio
    async def test_error_missing_message_raises(self) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1, "error": {"code": -32601}}),
            ConnectionClosed(None, None),
        ]
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
    async def test_matching_uses_the_protocol_id_field(self) -> None:
        """A response is selected by its CDP ``id`` field, not another key."""
        mock_ws = AsyncMock()
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1, "result": {"ok": True}}),
            AuthenticationError("unexpected second receive"),
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
        assert client.ws is None

    @pytest.mark.asyncio
    async def test_close_swallows_close_errors(self) -> None:
        mock_ws = AsyncMock()
        mock_ws.close.side_effect = ConnectionClosed(None, None)
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws
        await client.close()
        await client.close()
        assert mock_ws.close.call_count == 1

    @pytest.mark.asyncio
    async def test_closed_flag_never_touches_later_sockets(self) -> None:
        """A socket assigned after close() is left untouched by repeat closes."""
        first_ws = AsyncMock()
        second_ws = AsyncMock()
        client = ChromeDevToolsClient(9222)
        client.ws = first_ws
        await client.close()
        assert client.ws is None
        client.ws = second_ws
        await client.close()
        first_ws.close.assert_called_once()
        second_ws.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_failure_logs_exact_debug_message(self) -> None:
        mock_ws = AsyncMock()
        mock_ws.close.side_effect = ConnectionClosed(None, None)
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws
        mock_logger = MagicMock()

        with patch("perplexity_cli.auth.oauth_handler.get_logger", return_value=mock_logger):
            await client.close()

        mock_logger.debug.assert_called_once_with("Error while closing CDP WebSocket")


class TestNotConnectedGuard:
    """Both connection guards reject with the documented message."""

    @pytest.mark.asyncio
    async def test_send_command_before_connect_raises_exactly(self) -> None:
        client = ChromeDevToolsClient(9222)
        with pytest.raises(AuthenticationError, match=r"^Not connected to Chrome$"):
            await client.send_command("Page.enable")

    @pytest.mark.asyncio
    async def test_await_response_before_connect_raises_exactly(self) -> None:
        client = ChromeDevToolsClient(9222)
        with pytest.raises(AuthenticationError, match=r"^Not connected to Chrome$"):
            await client._await_response(1, "Page.enable")

    @pytest.mark.asyncio
    async def test_in_lock_guard_rejects_socket_lost_while_queued(self) -> None:
        """The post-lock guard fires when the socket disappears during contention."""
        lock = _EnteringBlockLock()
        client = ChromeDevToolsClient(9222)
        client._command_lock = lock
        client.ws = AsyncMock()
        task = asyncio.create_task(client.send_command("Page.enable"))
        await asyncio.wait_for(lock.entered.wait(), timeout=1)
        client.ws = None
        lock.release_event.set()
        with pytest.raises(AuthenticationError, match=r"^Not connected to Chrome$"):
            await asyncio.wait_for(task, timeout=1)


class _EnteringBlockLock:
    """Command-lock stand-in that blocks holders until released by the test."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release_event = asyncio.Event()

    async def __aenter__(self) -> _EnteringBlockLock:
        self.entered.set()
        await self.release_event.wait()
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class TestSendCommandWireFormat:
    """Commands on the wire carry correlated IDs, methods and params."""

    @pytest.mark.asyncio
    async def test_payload_id_method_and_params_are_correlated(self) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1, "result": {"ok": True}}),
            ConnectionClosed(None, None),
        ]
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws

        with patch("perplexity_cli.auth.oauth_handler._CDP_RESPONSE_TIMEOUT", 0.05):
            result = await asyncio.wait_for(
                client.send_command("Page.navigate", {"url": "https://nav-sentinel.invalid"}),
                timeout=0.1,
            )

        assert result == {"ok": True}
        assert client.message_id == 1
        sent = mock_ws.send.call_args.args[0]
        assert json.loads(sent) == {
            "id": 1,
            "method": "Page.navigate",
            "params": {"url": "https://nav-sentinel.invalid"},
        }

    @pytest.mark.asyncio
    async def test_matching_requires_exact_id_field_value(self) -> None:
        """A response whose id differs is skipped, never consumed."""
        mock_ws = AsyncMock()
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1, "result": {"which": "first"}}),
            json.dumps({"id": 99, "result": {"which": "second"}}),
            AuthenticationError("unexpected third receive"),
        ]
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws

        with patch("perplexity_cli.auth.oauth_handler._CDP_RESPONSE_TIMEOUT", 0.05):
            result = await asyncio.wait_for(client.send_command("Page.enable"), timeout=0.1)

        assert result == {"which": "first"}

    @pytest.mark.asyncio
    async def test_unsolicited_events_do_not_satisfy_a_command(self) -> None:
        """Events without an id cannot stand in for the awaited response."""
        mock_ws = AsyncMock()
        mock_ws.recv.side_effect = [
            json.dumps({"method": "Network.requestWillBeSent", "result": {"spoof": True}}),
            json.dumps({"id": 1, "result": {"real": True}}),
        ]
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws

        with patch("perplexity_cli.auth.oauth_handler._CDP_RESPONSE_TIMEOUT", 0.05):
            result = await asyncio.wait_for(client.send_command("Page.enable"), timeout=0.1)

        assert result == {"real": True}

    @pytest.mark.asyncio
    async def test_send_command_passes_allocated_id_to_waiter(self) -> None:
        """The public command boundary preserves the allocated response ID."""
        mock_ws = AsyncMock()
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws
        client._await_response = AsyncMock(return_value={"ok": True})

        result = await client.send_command("Page.enable")

        assert result == {"ok": True}
        client._await_response.assert_awaited_once_with(1, "Page.enable")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("initial_id", [0, 4])
    async def test_send_command_allocates_the_next_id(self, initial_id: int) -> None:
        """Every command increments the wire and waiter correlation ID by one."""
        mock_ws = AsyncMock()
        client = ChromeDevToolsClient(9222)
        client.message_id = initial_id
        client.ws = mock_ws
        client._await_response = AsyncMock(return_value={"ok": True})

        assert await client.send_command("Page.enable") == {"ok": True}

        assert client.message_id == initial_id + 1
        assert json.loads(mock_ws.send.call_args.args[0])["id"] == initial_id + 1
        client._await_response.assert_awaited_once_with(initial_id + 1, "Page.enable")


class TestCdpWaitDeadline:
    """The CDP response deadline is enforced even while recv blocks."""

    @pytest.mark.asyncio
    async def test_inner_deadline_raises_the_named_timeout(self) -> None:
        mock_ws = AsyncMock()
        stalled = asyncio.Event()

        async def blocked_recv() -> str:
            await stalled.wait()
            return json.dumps({"id": 1, "result": {}})

        mock_ws.recv.side_effect = blocked_recv
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws

        with patch("perplexity_cli.auth.oauth_handler._CDP_RESPONSE_TIMEOUT", 0.05):
            with pytest.raises(
                TimeoutError, match=r"^Timed out waiting for CDP response to Page\.enable$"
            ):
                await asyncio.wait_for(client.send_command("Page.enable"), timeout=0.1)
        stalled.set()

    @pytest.mark.asyncio
    async def test_matching_waiter_preserves_id_and_deadline(self) -> None:
        """The waiter accepts the requested ID and does not poll forever."""
        mock_ws = AsyncMock()
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1, "result": {"ok": True}}),
            ConnectionClosed(None, None),
        ]
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws

        result = await asyncio.wait_for(client._await_response(1, "Page.enable"), timeout=0.1)

        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_correlated_command_returns_first_matching_payload(self) -> None:
        """A sent command returns its correlated payload promptly.

        Any mis-correlation of the response id (dropped or mismatched key)
        makes this call never return, which the self-owned bound converts
        into a fast deterministic failure.
        """
        mock_ws = AsyncMock()
        mock_ws.recv.side_effect = [
            json.dumps({"id": 9, "result": {"token": "wrong-response"}}),
            json.dumps({"id": 1, "result": {"token": "t011-cdp"}}),
        ]
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws

        result = await asyncio.wait_for(client.send_command("Page.enable"), timeout=0.3)

        assert result == {"token": "t011-cdp"}
        assert mock_ws.recv.await_count >= 1

    @pytest.mark.asyncio
    async def test_await_response_applies_configured_deadline(self) -> None:
        """The response waiter receives the configured CDP deadline."""
        client = ChromeDevToolsClient(9222)
        client.ws = AsyncMock()
        client._wait_for_matching = AsyncMock(return_value={"ok": True})
        timeout_context = MagicMock()
        timeout_context.__aenter__ = AsyncMock()
        timeout_context.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "perplexity_cli.auth.oauth_handler.asyncio.timeout", return_value=timeout_context
        ) as timeout:
            result = await client._await_response(1, "Page.enable")

        assert result == {"ok": True}
        timeout.assert_called_once_with(30.0)
        client._wait_for_matching.assert_awaited_once_with(1, "Page.enable")

    @pytest.mark.asyncio
    async def test_waiter_matches_protocol_id_not_null_key(self) -> None:
        client = ChromeDevToolsClient(9222)
        client.ws = AsyncMock()
        stalled = asyncio.Event()

        receives = 0

        async def receive_wrong_key() -> dict[str | None, object]:
            nonlocal receives
            receives += 1
            if receives > 1:
                await stalled.wait()
            return {None: 1, "result": {"wrong": True}}

        client._recv_from_ws = AsyncMock(side_effect=receive_wrong_key)
        client._parse_cdp_message = MagicMock(side_effect=lambda value: value)

        with patch("perplexity_cli.auth.oauth_handler._CDP_RESPONSE_TIMEOUT", 0.05):
            with pytest.raises(TimeoutError):
                await client._await_response(1, "Page.enable")

    @pytest.mark.asyncio
    async def test_send_command_uses_incremented_id_for_wire_response(self) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1, "result": {"ok": True}}),
            ConnectionClosed(None, None),
        ]
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws

        assert await asyncio.wait_for(client.send_command("Page.enable"), timeout=0.3) == {
            "ok": True
        }


class TestErrorResponseMethodNaming:
    """Malformed-error rejections name the originating protocol method."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error_payload",
        ["oops", {"code": -32601}],
        ids=["non-dict-error", "message-less-error"],
    )
    async def test_malformed_error_names_the_method(self, error_payload: object) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1, "error": error_payload}),
            ConnectionClosed(None, None),
        ]
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws

        with pytest.raises(
            AuthenticationError, match=r"^Chrome returned a malformed error for Page\.enable$"
        ):
            await client.send_command("Page.enable")

    @pytest.mark.asyncio
    async def test_missing_result_names_the_method(self) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1}),
            ConnectionClosed(None, None),
        ]
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws

        with pytest.raises(
            AuthenticationError, match=r"^Chrome returned a malformed result for Page\.enable$"
        ):
            await client.send_command("Page.enable")


class TestMessageFramingRejections:
    """Malformed frames are rejected with their documented messages."""

    @pytest.mark.asyncio
    async def test_non_object_frame_rejected_exactly(self) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv.return_value = "[1, 2, 3]"
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws

        with patch("perplexity_cli.auth.oauth_handler._CDP_RESPONSE_TIMEOUT", 0.05):
            with pytest.raises(
                AuthenticationError, match=r"^Chrome returned a malformed CDP message$"
            ):
                await client.send_command("Page.enable")

    def test_malformed_json_rejected_exactly(self) -> None:
        client = ChromeDevToolsClient(9222)
        with pytest.raises(AuthenticationError, match=r"^Chrome returned malformed CDP JSON$"):
            client._parse_cdp_message("{{{ not json")

    @pytest.mark.asyncio
    async def test_recv_without_socket_rejected_exactly(self) -> None:
        client = ChromeDevToolsClient(9222)
        with pytest.raises(AuthenticationError, match=r"^CDP connection to Chrome is closed$"):
            await client._recv_from_ws()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "transport_error",
        [OSError("boom"), ConnectionClosed(None, None)],
        ids=["oserror", "closed"],
    )
    async def test_recv_transport_failure_wraps_cause_exactly(
        self, transport_error: Exception
    ) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv.side_effect = transport_error
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws

        with pytest.raises(
            AuthenticationError, match=r"^CDP connection to Chrome closed unexpectedly$"
        ) as exc_info:
            await client._recv_from_ws()

        assert isinstance(exc_info.value.__cause__, (OSError, ConnectionClosed))


class TestTargetsEndpointRequest:
    """Target discovery hits the documented HTTP endpoint shape."""

    def test_requests_port_specific_json_endpoint_with_timeout(self) -> None:
        targets = [{"type": "page", "webSocketDebuggerUrl": "ws://localhost:94711/x"}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = targets
        mock_resp.raise_for_status = MagicMock()

        client = ChromeDevToolsClient(94711)
        with patch("httpx.get", return_value=mock_resp) as get_mock:
            client._fetch_targets()

        get_mock.assert_called_once_with("http://localhost:94711/json", timeout=5)

    def test_invalid_payload_rejected_exactly(self) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"unexpected": "shape"}
        mock_resp.raise_for_status = MagicMock()

        client = ChromeDevToolsClient(94711)
        with patch("httpx.get", return_value=mock_resp):
            with pytest.raises(
                AuthenticationError, match=r"^Chrome returned an invalid targets payload$"
            ):
                client._fetch_targets()

    def test_missing_debugger_url_rejected_exactly(self) -> None:
        """A page target without a debugger URL is rejected verbatim."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"type": "page", "title": "no-ws"}]
        mock_resp.raise_for_status = MagicMock()

        client = ChromeDevToolsClient(94711)
        with patch("httpx.get", return_value=mock_resp):
            with pytest.raises(
                AuthenticationError, match=r"^Could not get WebSocket debugger URL$"
            ):
                asyncio.run(client.connect())


class TestCookieEntryValidation:
    """Malformed cookie entries are rejected with the documented message."""

    def test_non_dict_entry_rejected_exactly(self) -> None:
        with pytest.raises(
            AuthenticationError, match=r"^Chrome returned a malformed cookie entry$"
        ):
            _extract_token(["cookie-entry-sentinel"], {})

    def test_non_string_value_rejected_exactly(self) -> None:
        with pytest.raises(
            AuthenticationError, match=r"^Chrome returned a malformed cookie entry$"
        ):
            _extract_token([{"name": "cookie-name-sentinel", "value": 12345}], {})


class TestCheckPageLoadedProtocol:
    """Page-load probing uses the documented CDP query and diagnostics."""

    @pytest.mark.asyncio
    async def test_queries_navigation_history_by_exact_method(self) -> None:
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        mock_client.send_command.return_value = {"currentIndex": 0, "entries": ["page-sentinel"]}
        mock_logger = MagicMock()

        result = await _check_page_loaded(mock_client, mock_logger)

        assert result is True
        assert mock_client.send_command.await_args_list == [call("Page.getNavigationHistory")]

    @pytest.mark.asyncio
    async def test_success_logs_loaded_diagnostics_exactly(self) -> None:
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        mock_client.send_command.return_value = {"currentIndex": 0}
        mock_logger = MagicMock()

        result = await _check_page_loaded(mock_client, mock_logger)

        assert result is True
        assert mock_logger.debug.call_args_list == [call("Page loaded successfully")]

    @pytest.mark.asyncio
    async def test_failure_logs_not_ready_with_the_error(self) -> None:
        error = AuthenticationError("nav-not-ready-sentinel")
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        mock_client.send_command.side_effect = error
        mock_logger = MagicMock()

        result = await _check_page_loaded(mock_client, mock_logger)

        assert result is False
        assert mock_logger.debug.call_args_list == [call("Page not ready yet: %s", error)]


class TestNavigateAndWaitDiagnostics:
    """Navigation emits the documented command sequence and diagnostics."""

    @pytest.mark.asyncio
    async def test_navigates_with_diagnostics_and_page_deadline(self) -> None:
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        nav_result = {"frameId": "nav-frame-sentinel"}
        mock_client.send_command.side_effect = [{}, {}, nav_result]
        mock_logger = MagicMock()
        url = "https://nav-target-sentinel.invalid"

        with patch(
            "perplexity_cli.auth.oauth_handler._wait_for_page_load", new_callable=AsyncMock
        ) as wait_mock:
            await _navigate_and_wait(mock_client, url, mock_logger)

        assert mock_client.send_command.await_args_list == [
            call("Page.enable"),
            call("Network.enable"),
            call("Page.navigate", {"url": url}),
        ]
        assert mock_logger.info.call_args_list == [call("Navigating to %s...", url)]
        assert call("Navigation result: %s", nav_result) in mock_logger.debug.call_args_list
        assert call("Waiting for page to load...") in mock_logger.debug.call_args_list
        wait_mock.assert_awaited_once_with(mock_client, timeout=30)


class TestFetchLocalStorageProtocol:
    """localStorage harvesting sends the documented evaluation and guards shapes."""

    @pytest.mark.asyncio
    async def test_evaluates_the_local_storage_expression(self) -> None:
        storage = {"ls-sentinel-key": "ls-sentinel-value"}
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        mock_client.send_command.return_value = {"result": {"value": storage}}

        result = await _fetch_local_storage(mock_client)
        await_args = mock_client.send_command.await_args
        params = await_args.args[1]
        assert (
            result,
            mock_client.send_command.await_count,
            len(await_args.args),
            await_args.args[0],
            set(params.keys()),
            "localStorage.length" in params["expression"],
            "localStorage.getItem" in params["expression"],
        ) == (storage, 1, 2, "Runtime.evaluate", {"expression"}, True, True)

    @pytest.mark.asyncio
    async def test_non_dict_inner_result_rejected_exactly(self) -> None:
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        mock_client.send_command.return_value = {"result": ["not-a-dict"]}

        with pytest.raises(
            AuthenticationError, match=r"^Chrome returned a malformed localStorage payload$"
        ):
            await _fetch_local_storage(mock_client)

    @pytest.mark.asyncio
    async def test_non_dict_value_rejected_exactly(self) -> None:
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        mock_client.send_command.return_value = {"result": {"value": "scalar-sentinel"}}

        with pytest.raises(
            AuthenticationError, match=r"^Chrome returned a malformed localStorage payload$"
        ):
            await _fetch_local_storage(mock_client)


class TestPollForAuthDataProtocol:
    """Polling queries all cookies, logs redacted diagnostics, and paces itself."""

    @pytest.mark.asyncio
    async def test_success_queries_all_cookies_and_logs_cookie_count(self) -> None:
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        mock_client.send_command.return_value = {
            "cookies": [{"name": "__Secure-next-auth.session-token", "value": "poll-token"}]
        }
        mock_logger = MagicMock()
        loop = MagicMock()
        loop.time.side_effect = [0.0, 0.0]

        with (
            patch("perplexity_cli.auth.oauth_handler.asyncio.get_event_loop", return_value=loop),
            patch(
                "perplexity_cli.auth.oauth_handler._fetch_local_storage",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            token, cookie_dict = await _poll_for_auth_data(mock_client, 5, 0.25, mock_logger)

        assert token == "poll-token"
        assert cookie_dict == {"__Secure-next-auth.session-token": "poll-token"}
        assert mock_client.send_command.await_args_list == [call("Network.getAllCookies")]
        assert mock_logger.info.call_args_list == [
            call("Successfully extracted authentication token and %s cookies", 1)
        ]

    @pytest.mark.asyncio
    async def test_waiting_poll_logs_pace_then_sleeps(self) -> None:
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        mock_client.send_command.side_effect = [
            {"cookies": []},
            {"cookies": [{"name": "__Secure-next-auth.session-token", "value": "later-token"}]},
        ]
        mock_logger = MagicMock()
        loop = MagicMock()
        loop.time.side_effect = [0.0, 0.0, 0.0]

        with (
            patch("perplexity_cli.auth.oauth_handler.asyncio.get_event_loop", return_value=loop),
            patch(
                "perplexity_cli.auth.oauth_handler.asyncio.sleep", new_callable=AsyncMock
            ) as sleep_mock,
            patch(
                "perplexity_cli.auth.oauth_handler._fetch_local_storage",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            token, _ = await _poll_for_auth_data(mock_client, 5, 0.25, mock_logger)

        assert token == "later-token"
        assert mock_logger.debug.call_args_list == [
            call("No token found yet, waiting %ss... (elapsed: %ss)", 0.25, "0.0")
        ]
        assert sleep_mock.await_args_list == [call(0.25)]

    @pytest.mark.asyncio
    async def test_timeout_message_names_the_login_remedy(self) -> None:
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        mock_client.send_command.return_value = {"cookies": []}
        mock_logger = MagicMock()
        loop = MagicMock()
        loop.time.side_effect = [0.0, 0.0, 999.0]

        with (
            patch("perplexity_cli.auth.oauth_handler.asyncio.get_event_loop", return_value=loop),
            patch("perplexity_cli.auth.oauth_handler.asyncio.sleep", new_callable=AsyncMock),
            patch(
                "perplexity_cli.auth.oauth_handler._fetch_local_storage",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            with pytest.raises(TimeoutError) as exc_info:
                await _poll_for_auth_data(mock_client, 5, 0.25, mock_logger)

        message = str(exc_info.value)
        assert "Authentication timeout after 5 seconds" in message
        assert "Please ensure you have logged in to Perplexity.ai in Chrome." in message


class TestWaitForPageLoadPacing:
    """Page-load waiting re-probes on the documented cadence and deadline."""

    @pytest.mark.asyncio
    async def test_reprobes_every_half_second_until_loaded(self) -> None:
        mock_client = AsyncMock(spec=ChromeDevToolsClient)

        with (
            patch(
                "perplexity_cli.auth.oauth_handler._check_page_loaded",
                new_callable=AsyncMock,
                side_effect=[False, True],
            ) as probe_mock,
            patch(
                "perplexity_cli.auth.oauth_handler.asyncio.sleep", new_callable=AsyncMock
            ) as sleep_mock,
        ):
            await _wait_for_page_load(mock_client, timeout=30)

        assert sleep_mock.await_args_list == [call(0.5)]
        assert probe_mock.await_count == 2

    @pytest.mark.asyncio
    async def test_probe_at_exact_deadline_still_runs(self) -> None:
        """An elapsed equal to the deadline still gets its final probe."""
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        loop = MagicMock()
        loop.time.side_effect = [100.0, 104.0, 105.0]

        with (
            patch("perplexity_cli.auth.oauth_handler.asyncio.get_event_loop", return_value=loop),
            patch(
                "perplexity_cli.auth.oauth_handler._check_page_loaded",
                new_callable=AsyncMock,
                side_effect=[False, True],
            ) as probe_mock,
            patch("perplexity_cli.auth.oauth_handler.asyncio.sleep", new_callable=AsyncMock),
        ):
            await _wait_for_page_load(mock_client, timeout=5)

        assert probe_mock.await_count == 2


class TestAuthenticateSyncForwarding:
    """authenticate_sync forwards every setting to the browser flow."""

    def test_forwards_all_settings_to_browser_flow(self) -> None:
        with (
            patch("perplexity_cli.auth.oauth_handler.authenticate_with_browser") as flow_mock,
            patch(
                "perplexity_cli.auth.oauth_handler.run_async", return_value=("sync-token", {})
            ) as bridge_mock,
        ):
            result = authenticate_sync(
                url="https://sync-sentinel.invalid", port=94711, timeout=42, poll_interval=1.5
            )

        flow_mock.assert_called_once_with("https://sync-sentinel.invalid", 94711, 42, 1.5)
        bridge_mock.assert_called_once()
        forwarded = bridge_mock.call_args.args[0]
        assert asyncio.iscoroutine(forwarded)
        forwarded.close()
        assert result == ("sync-token", {})


class TestAuthenticateWithBrowserWiring:
    """The browser flow wires resolved defaults, logging and guaranteed close."""

    @pytest.mark.asyncio
    async def test_wires_resolved_defaults_through_flow_logging(self) -> None:
        client = MagicMock(spec=ChromeDevToolsClient)
        client.connect = AsyncMock()
        client.close = AsyncMock()
        mock_logger = MagicMock()

        with (
            patch("perplexity_cli.auth.oauth_handler.get_logger", return_value=mock_logger),
            patch(
                "perplexity_cli.auth.oauth_handler.ChromeDevToolsClient", return_value=client
            ) as ctor,
            patch(
                "perplexity_cli.auth.oauth_handler._navigate_and_wait", new_callable=AsyncMock
            ) as navigate_mock,
            patch(
                "perplexity_cli.auth.oauth_handler._poll_for_auth_data",
                new_callable=AsyncMock,
                return_value=("wired-token", {}),
            ) as poll_mock,
        ):
            token, _ = await authenticate_with_browser(
                url="https://flow-sentinel.invalid", port=94711, timeout=11, poll_interval=0.75
            )

        assert token == "wired-token"
        ctor.assert_called_once_with(94711)
        assert call("Connecting to Chrome on port %s...", 94711) in mock_logger.info.call_args_list
        assert call("Connected to Chrome") in mock_logger.info.call_args_list
        assert call("Waiting for authentication...") in mock_logger.info.call_args_list
        navigate_mock.assert_awaited_once_with(client, "https://flow-sentinel.invalid", mock_logger)
        poll_mock.assert_awaited_once_with(client, 11, 0.75, mock_logger)
        client.close.assert_awaited_once_with()
