"""Tests for Chrome DevTools Protocol automation in oauth_handler."""

from __future__ import annotations

import asyncio
import json
import urllib.error
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from perplexity_cli.auth.oauth_handler import (
    ChromeDevToolsClient,
    _check_page_loaded,
    _fetch_local_storage,
    _navigate_and_wait,
    _poll_for_auth_data,
    _resolve_auth_defaults,
    _wait_for_page_load,
    authenticate_sync,
    authenticate_with_browser,
)
from perplexity_cli.utils.exceptions import AuthenticationError

# ---------------------------------------------------------------------------
# ChromeDevToolsClient
# ---------------------------------------------------------------------------


class TestChromeDevToolsClientInit:
    """Tests for ChromeDevToolsClient.__init__."""

    def test_sets_port(self):
        """Port is stored on the instance."""
        client = ChromeDevToolsClient(9222)
        assert client.port == 9222

    def test_ws_initially_none(self):
        """WebSocket connection starts as None."""
        client = ChromeDevToolsClient(9222)
        assert client.ws is None

    def test_message_id_starts_at_zero(self):
        """Message ID counter starts at zero."""
        client = ChromeDevToolsClient(9222)
        assert client.message_id == 0


class TestFetchTargets:
    """Tests for ChromeDevToolsClient._fetch_targets."""

    def test_returns_target_list(self):
        """Returns parsed JSON list from Chrome endpoint."""
        targets = [{"type": "page", "webSocketDebuggerUrl": "ws://localhost:9222/x"}]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(targets).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        client = ChromeDevToolsClient(9222)
        with patch(
            "perplexity_cli.auth.oauth_handler.urllib.request.urlopen", return_value=mock_resp
        ):
            result = client._fetch_targets()
        assert result == targets

    def test_raises_on_url_error(self):
        """Raises AuthenticationError when Chrome is unreachable."""
        client = ChromeDevToolsClient(9222)
        with patch(
            "perplexity_cli.auth.oauth_handler.urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            with pytest.raises(AuthenticationError, match="Failed to connect"):
                client._fetch_targets()

    def test_raises_on_non_list_response(self):
        """Raises AuthenticationError when Chrome returns a non-list payload."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"not": "a list"}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        client = ChromeDevToolsClient(9222)
        with patch(
            "perplexity_cli.auth.oauth_handler.urllib.request.urlopen", return_value=mock_resp
        ):
            with pytest.raises(AuthenticationError, match="invalid targets payload"):
                client._fetch_targets()

    def test_raises_on_invalid_json(self):
        """Raises AuthenticationError when Chrome returns invalid JSON."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json at all"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        client = ChromeDevToolsClient(9222)
        with patch(
            "perplexity_cli.auth.oauth_handler.urllib.request.urlopen", return_value=mock_resp
        ):
            with pytest.raises(AuthenticationError, match="Failed to connect"):
                client._fetch_targets()

    def test_raises_on_timeout(self):
        """Raises AuthenticationError on timeout."""
        client = ChromeDevToolsClient(9222)
        with patch(
            "perplexity_cli.auth.oauth_handler.urllib.request.urlopen",
            side_effect=TimeoutError("timed out"),
        ):
            with pytest.raises(AuthenticationError, match="Failed to connect"):
                client._fetch_targets()


class TestFindPageTarget:
    """Tests for ChromeDevToolsClient._find_page_target."""

    def test_returns_page_target(self):
        """Returns the first page-type target."""
        targets = [
            {"type": "background_page", "title": "bg"},
            {"type": "page", "title": "main"},
        ]
        result = ChromeDevToolsClient._find_page_target(targets)
        assert result["title"] == "main"

    def test_raises_when_no_page(self):
        """Raises AuthenticationError when no page target exists."""
        targets = [{"type": "service_worker"}]
        with pytest.raises(AuthenticationError, match="No page target found"):
            ChromeDevToolsClient._find_page_target(targets)

    def test_raises_on_empty_list(self):
        """Raises AuthenticationError on empty targets list."""
        with pytest.raises(AuthenticationError, match="No page target found"):
            ChromeDevToolsClient._find_page_target([])


class TestConnect:
    """Tests for ChromeDevToolsClient.connect."""

    @pytest.mark.asyncio
    async def test_connects_to_websocket(self):
        """Connects via websocket to the page target's debugger URL."""
        targets = [{"type": "page", "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/1"}]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(targets).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        mock_ws = AsyncMock()

        async def fake_connect(url):
            return mock_ws

        client = ChromeDevToolsClient(9222)
        with (
            patch(
                "perplexity_cli.auth.oauth_handler.urllib.request.urlopen", return_value=mock_resp
            ),
            patch(
                "perplexity_cli.auth.oauth_handler.websockets.connect", side_effect=fake_connect
            ) as mock_connect,
        ):
            await client.connect()
            mock_connect.assert_called_once_with("ws://localhost:9222/devtools/page/1")
            assert client.ws is mock_ws

    @pytest.mark.asyncio
    async def test_raises_when_no_ws_url(self):
        """Raises AuthenticationError when target has no webSocketDebuggerUrl."""
        targets = [{"type": "page", "title": "no-ws"}]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(targets).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        client = ChromeDevToolsClient(9222)
        with patch(
            "perplexity_cli.auth.oauth_handler.urllib.request.urlopen", return_value=mock_resp
        ):
            with pytest.raises(AuthenticationError, match="WebSocket debugger URL"):
                await client.connect()


class TestBuildCommand:
    """Tests for ChromeDevToolsClient._build_command."""

    def test_builds_without_params(self):
        """Builds command dict without params when none given."""
        client = ChromeDevToolsClient(9222)
        client.message_id = 5
        cmd = client._build_command("Page.enable", None)
        assert cmd == {"id": 5, "method": "Page.enable"}
        assert "params" not in cmd

    def test_builds_with_params(self):
        """Builds command dict with params when provided."""
        client = ChromeDevToolsClient(9222)
        client.message_id = 3
        cmd = client._build_command("Page.navigate", {"url": "https://example.com"})
        assert cmd == {"id": 3, "method": "Page.navigate", "params": {"url": "https://example.com"}}


class TestSendCommand:
    """Tests for ChromeDevToolsClient.send_command."""

    @pytest.mark.asyncio
    async def test_raises_when_not_connected(self):
        """Raises AuthenticationError when ws is None."""
        client = ChromeDevToolsClient(9222)
        with pytest.raises(AuthenticationError, match="Not connected"):
            await client.send_command("Page.enable")

    @pytest.mark.asyncio
    async def test_sends_and_receives(self):
        """Sends command and returns result from matching response."""
        mock_ws = AsyncMock()
        mock_ws.recv.return_value = json.dumps({"id": 1, "result": {"frameId": "abc"}})

        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws
        result = await client.send_command("Page.enable")
        assert result == {"frameId": "abc"}
        assert client.message_id == 1
        mock_ws.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_increments_message_id(self):
        """Each call increments the message ID."""
        mock_ws = AsyncMock()
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1, "result": {}}),
            json.dumps({"id": 2, "result": {}}),
        ]

        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws
        await client.send_command("Page.enable")
        await client.send_command("Network.enable")
        assert client.message_id == 2


class TestAwaitResponse:
    """Tests for ChromeDevToolsClient._await_response."""

    @pytest.mark.asyncio
    async def test_raises_when_not_connected(self):
        """Raises AuthenticationError when ws is None."""
        client = ChromeDevToolsClient(9222)
        with pytest.raises(AuthenticationError, match="Not connected"):
            await client._await_response()

    @pytest.mark.asyncio
    async def test_skips_non_matching_ids(self):
        """Skips messages that do not match the current message ID."""
        mock_ws = AsyncMock()
        mock_ws.recv.side_effect = [
            json.dumps({"id": 99, "result": {}}),
            json.dumps({"id": 1, "result": {"ok": True}}),
        ]

        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws
        client.message_id = 1
        result = await client._await_response()
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_raises_on_chrome_error(self):
        """Raises AuthenticationError when Chrome returns an error."""
        mock_ws = AsyncMock()
        mock_ws.recv.return_value = json.dumps({"id": 1, "error": {"message": "fail"}})

        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws
        client.message_id = 1
        with pytest.raises(AuthenticationError, match="Chrome error"):
            await client._await_response()

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_no_result_key(self):
        """Returns empty dict when response has no 'result' key."""
        mock_ws = AsyncMock()
        mock_ws.recv.return_value = json.dumps({"id": 1})

        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws
        client.message_id = 1
        result = await client._await_response()
        assert result == {}


class TestClose:
    """Tests for ChromeDevToolsClient.close."""

    @pytest.mark.asyncio
    async def test_closes_websocket(self):
        """Closes the websocket connection."""
        mock_ws = AsyncMock()
        client = ChromeDevToolsClient(9222)
        client.ws = mock_ws
        await client.close()
        mock_ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_noop_when_no_ws(self):
        """Does nothing when ws is None."""
        client = ChromeDevToolsClient(9222)
        await client.close()  # should not raise


# ---------------------------------------------------------------------------
# Module-level functions
# ---------------------------------------------------------------------------


class TestResolveAuthDefaults:
    """Tests for _resolve_auth_defaults."""

    def test_returns_explicit_values(self):
        """Returns provided values when all are explicit."""
        url, port, timeout, poll = _resolve_auth_defaults("https://example.com", 1234, 60, 2.0)
        assert url == "https://example.com"
        assert port == 1234
        assert timeout == 60
        assert poll == 2.0

    def test_applies_defaults_for_none(self):
        """Applies config defaults when arguments are None."""
        url, port, timeout, poll = _resolve_auth_defaults(None, None, None, None)
        # Just verify they are not None and are the correct types
        assert isinstance(url, str)
        assert isinstance(port, int)
        assert isinstance(timeout, int)
        assert isinstance(poll, float)


class TestNavigateAndWait:
    """Tests for _navigate_and_wait."""

    @pytest.mark.asyncio
    async def test_sends_enable_and_navigate_commands(self):
        """Sends Page.enable, Network.enable and Page.navigate commands."""
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        mock_client.send_command.return_value = {}
        mock_logger = MagicMock()

        with patch(
            "perplexity_cli.auth.oauth_handler._wait_for_page_load",
            new_callable=AsyncMock,
        ):
            await _navigate_and_wait(mock_client, "https://perplexity.ai", mock_logger)

        calls = [c.args for c in mock_client.send_command.call_args_list]
        assert calls[0] == ("Page.enable",)
        assert calls[1] == ("Network.enable",)
        assert calls[2] == ("Page.navigate", {"url": "https://perplexity.ai"})


class TestFetchLocalStorage:
    """Tests for _fetch_local_storage."""

    @pytest.mark.asyncio
    async def test_returns_storage_data(self):
        """Returns localStorage value when present in result."""
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        mock_client.send_command.return_value = {
            "result": {"value": {"key1": "val1", "key2": "val2"}}
        }
        result = await _fetch_local_storage(mock_client)
        assert result == {"key1": "val1", "key2": "val2"}

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_no_result(self):
        """Returns empty dict when result is missing."""
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        mock_client.send_command.return_value = {}
        result = await _fetch_local_storage(mock_client)
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_no_value(self):
        """Returns empty dict when result has no 'value' key."""
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        mock_client.send_command.return_value = {"result": {"type": "undefined"}}
        result = await _fetch_local_storage(mock_client)
        assert result == {}


class TestPollForAuthData:
    """Tests for _poll_for_auth_data."""

    @pytest.mark.asyncio
    async def test_returns_token_on_first_poll(self):
        """Returns token immediately when found on first poll."""
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        cookies = [{"name": "__Secure-next-auth.session-token", "value": "tok123"}]
        mock_client.send_command.return_value = {"cookies": cookies}
        mock_logger = MagicMock()

        with patch(
            "perplexity_cli.auth.oauth_handler._fetch_local_storage",
            new_callable=AsyncMock,
            return_value={},
        ):
            token, cookie_dict = await _poll_for_auth_data(
                mock_client, timeout=10, poll_interval=0.1, logger=mock_logger
            )
        assert token == "tok123"
        assert cookie_dict["__Secure-next-auth.session-token"] == "tok123"

    @pytest.mark.asyncio
    async def test_raises_timeout(self):
        """Raises TimeoutError when timeout is exceeded."""
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        mock_client.send_command.return_value = {"cookies": []}
        mock_logger = MagicMock()

        loop = asyncio.get_event_loop()
        call_count = 0
        base_time = loop.time()

        def advancing_time():
            nonlocal call_count
            call_count += 1
            # After a few calls, exceed the timeout
            if call_count > 3:
                return base_time + 100
            return base_time

        with (
            patch(
                "perplexity_cli.auth.oauth_handler._fetch_local_storage",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("perplexity_cli.auth.oauth_handler.asyncio.sleep", new_callable=AsyncMock),
            patch.object(loop, "time", side_effect=advancing_time),
        ):
            with pytest.raises(TimeoutError, match="Authentication timeout"):
                await _poll_for_auth_data(
                    mock_client, timeout=5, poll_interval=0.1, logger=mock_logger
                )

    @pytest.mark.asyncio
    async def test_polls_until_token_found(self):
        """Polls multiple times until a token appears."""
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        # First two polls: no cookies. Third poll: has token.
        mock_client.send_command.side_effect = [
            {"cookies": []},
            {"cookies": []},
            {"cookies": [{"name": "__Secure-next-auth.session-token", "value": "found"}]},
        ]
        mock_logger = MagicMock()

        with (
            patch(
                "perplexity_cli.auth.oauth_handler._fetch_local_storage",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("perplexity_cli.auth.oauth_handler.asyncio.sleep", new_callable=AsyncMock),
        ):
            token, _ = await _poll_for_auth_data(
                mock_client, timeout=60, poll_interval=0.1, logger=mock_logger
            )
        assert token == "found"


class TestWaitForPageLoad:
    """Tests for _wait_for_page_load."""

    @pytest.mark.asyncio
    async def test_returns_when_page_loaded(self):
        """Returns immediately when page is already loaded."""
        mock_client = AsyncMock(spec=ChromeDevToolsClient)

        with patch(
            "perplexity_cli.auth.oauth_handler._check_page_loaded",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await _wait_for_page_load(mock_client, timeout=5)

    @pytest.mark.asyncio
    async def test_raises_timeout(self):
        """Raises TimeoutError when page does not load within timeout."""
        mock_client = AsyncMock(spec=ChromeDevToolsClient)

        loop = asyncio.get_event_loop()
        call_count = 0
        base_time = loop.time()

        def advancing_time():
            nonlocal call_count
            call_count += 1
            if call_count > 3:
                return base_time + 100
            return base_time

        with (
            patch(
                "perplexity_cli.auth.oauth_handler._check_page_loaded",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch("perplexity_cli.auth.oauth_handler.asyncio.sleep", new_callable=AsyncMock),
            patch.object(loop, "time", side_effect=advancing_time),
        ):
            with pytest.raises(TimeoutError, match="Page load timeout"):
                await _wait_for_page_load(mock_client, timeout=5)

    @pytest.mark.asyncio
    async def test_uses_default_timeout_when_none(self):
        """Uses DEFAULT_PAGE_LOAD_TIMEOUT when timeout is None."""
        mock_client = AsyncMock(spec=ChromeDevToolsClient)

        with patch(
            "perplexity_cli.auth.oauth_handler._check_page_loaded",
            new_callable=AsyncMock,
            return_value=True,
        ):
            # Should not raise -- just verifying it works with None
            await _wait_for_page_load(mock_client, timeout=None)


class TestCheckPageLoaded:
    """Tests for _check_page_loaded."""

    @pytest.mark.asyncio
    async def test_returns_true_when_loaded(self):
        """Returns True when getNavigationHistory succeeds."""
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        mock_client.send_command.return_value = {"currentIndex": 0, "entries": []}
        mock_logger = MagicMock()

        result = await _check_page_loaded(mock_client, mock_logger)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self):
        """Returns False when send_command raises AuthenticationError."""
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        mock_client.send_command.side_effect = AuthenticationError("not ready")
        mock_logger = MagicMock()

        result = await _check_page_loaded(mock_client, mock_logger)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_empty_dict_result(self):
        """Returns False when send_command returns empty dict (falsy)."""
        mock_client = AsyncMock()
        mock_client.send_command.return_value = {}
        mock_logger = MagicMock()

        result = await _check_page_loaded(mock_client, mock_logger)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_none_result(self):
        """Returns False when send_command returns None."""
        mock_client = AsyncMock(spec=ChromeDevToolsClient)
        mock_client.send_command.return_value = None
        mock_logger = MagicMock()

        result = await _check_page_loaded(mock_client, mock_logger)
        assert result is False


class TestAuthenticateWithBrowser:
    """Tests for authenticate_with_browser."""

    @pytest.mark.asyncio
    async def test_full_flow(self):
        """Exercises the complete authentication flow with mocks."""
        targets = [{"type": "page", "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/1"}]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(targets).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        mock_ws = AsyncMock()
        # connect sends no commands, but send_command calls will follow
        # Page.enable, Network.enable, Page.navigate, Page.getNavigationHistory, Network.getAllCookies
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1, "result": {}}),  # Page.enable
            json.dumps({"id": 2, "result": {}}),  # Network.enable
            json.dumps({"id": 3, "result": {"frameId": "f1"}}),  # Page.navigate
            json.dumps(
                {"id": 4, "result": {"currentIndex": 0, "entries": []}}
            ),  # getNavigationHistory
            json.dumps(
                {
                    "id": 5,
                    "result": {
                        "cookies": [{"name": "__Secure-next-auth.session-token", "value": "tok"}]
                    },
                }
            ),  # getAllCookies
            json.dumps(
                {"id": 6, "result": {"result": {"value": {}}}}
            ),  # Runtime.evaluate (localStorage)
        ]

        async def fake_connect(url):
            return mock_ws

        with (
            patch(
                "perplexity_cli.auth.oauth_handler.urllib.request.urlopen", return_value=mock_resp
            ),
            patch("perplexity_cli.auth.oauth_handler.websockets.connect", side_effect=fake_connect),
            patch("perplexity_cli.auth.oauth_handler.asyncio.sleep", new_callable=AsyncMock),
        ):
            token, cookies = await authenticate_with_browser(
                url="https://perplexity.ai", port=9222, timeout=10, poll_interval=0.1
            )

        assert token == "tok"
        assert cookies["__Secure-next-auth.session-token"] == "tok"
        mock_ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_closes_client_on_error(self):
        """Ensures client.close is called even when an error occurs."""
        targets = [{"type": "page", "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/1"}]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(targets).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        mock_ws = AsyncMock()
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1, "result": {}}),  # Page.enable
            json.dumps({"id": 2, "result": {}}),  # Network.enable
            json.dumps({"id": 3, "error": {"message": "nav failed"}}),  # Page.navigate error
        ]

        async def fake_connect(url):
            return mock_ws

        with (
            patch(
                "perplexity_cli.auth.oauth_handler.urllib.request.urlopen", return_value=mock_resp
            ),
            patch("perplexity_cli.auth.oauth_handler.websockets.connect", side_effect=fake_connect),
        ):
            with pytest.raises(AuthenticationError, match="Chrome error"):
                await authenticate_with_browser(
                    url="https://perplexity.ai", port=9222, timeout=10, poll_interval=0.1
                )

        mock_ws.close.assert_called_once()


class TestAuthenticateSync:
    """Tests for authenticate_sync."""

    def test_delegates_to_run_async(self):
        """Calls run_async with the coroutine from authenticate_with_browser."""
        with patch(
            "perplexity_cli.auth.oauth_handler.run_async",
            return_value=("token", {"c": "v"}),
        ) as mock_run:
            result = authenticate_sync(
                url="https://example.com", port=1234, timeout=30, poll_interval=1.0
            )
        assert result == ("token", {"c": "v"})
        mock_run.assert_called_once()
