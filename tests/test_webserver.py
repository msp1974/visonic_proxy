"""Unit tests for Webserver non-blocking forwarding and connect command filtering."""

import asyncio
import json
import time
import unittest
from unittest.mock import MagicMock

try:
    from tests._stubs import install_missing_stubs
except ImportError:
    from _stubs import install_missing_stubs

install_missing_stubs()

from visonic_proxy.connections.httpserver.utils import HttpHeaders, HttpRequest
from visonic_proxy.connections.webserver import Connect, MyHandler
from visonic_proxy.const import ConnectionName
from visonic_proxy.events import Event, EventType
from visonic_proxy.proxy import Proxy


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.content = bytes(f"{json.dumps(payload)}\n", "ascii")
        self.status_code = status_code
        self.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(self.content)),
        }

    def json(self):
        return dict(self._payload)


class TestWebserver(unittest.IsolatedAsyncioTestCase):
    """Tests for HTTPS /scripts/update.php proxy behavior."""

    async def asyncSetUp(self):
        self.loop = asyncio.get_running_loop()
        self.proxy = Proxy(self.loop, None)
        self.proxy.config.PROXY_MODE = True
        self.handler = MyHandler(self.proxy, request_connect=True)
        self.events: list[Event] = []
        self._unsub = self.proxy.events.subscribe(
            ConnectionName.VISONIC,
            EventType.REQUEST_CONNECT,
            self.events.append,
        )

    async def asyncTearDown(self):
        self._unsub()
        Connect.request_connect = True

    def _make_update_request(self) -> HttpRequest:
        headers = HttpHeaders()
        headers.add("Host", "52.58.105.181:8443")
        return HttpRequest(
            stamp=0.0,
            method="POST",
            path="/scripts/update.php",
            version="HTTP/1.1",
            query_params={},
            headers=headers,
            body=b"serial=123456",
        )

    async def test_strips_connect_command_when_alarm_already_connected(self):
        """When Connect.request_connect is False, strip 'connect' so panel does not open a 2nd TCP socket."""
        Connect.request_connect = False
        upstream = FakeResponse(
            {
                "cmds": [{"name": "connect", "params": {"port": 5001}}],
                "ka_time": 10,
                "version": 3,
            }
        )
        self.handler._sync_forward_request = MagicMock(return_value=upstream)

        resp = await self.handler.default(self._make_update_request())
        await asyncio.sleep(0.02)

        # Visonic connect event MUST still be fired for the proxy
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0].event_type, EventType.REQUEST_CONNECT)

        # Response to the alarm must NOT contain the 'connect' command
        body = json.loads(resp.body.decode("ascii"))
        self.assertNotIn("cmds", body)
        self.assertEqual(body["ka_time"], 10)
        self.assertEqual(int(resp.headers.get("Content-Length")), len(resp.body))

    async def test_keeps_connect_command_when_alarm_not_yet_connected(self):
        """When Connect.request_connect is True, instruct alarm to connect to proxy."""
        Connect.request_connect = True
        upstream = FakeResponse({"ka_time": 10, "version": 3})
        self.handler._sync_forward_request = MagicMock(return_value=upstream)

        resp = await self.handler.default(self._make_update_request())
        body = json.loads(resp.body.decode("ascii"))
        self.assertEqual(body["cmds"][0]["name"], "connect")
        self.assertEqual(body["cmds"][0]["params"]["port"], self.proxy.config.MESSAGE_PORT)

    async def test_timeout_returns_manual_response(self):
        """If PowerManage times out, default() must return a valid HttpResponse."""
        Connect.request_connect = False
        self.handler._sync_forward_request = MagicMock(side_effect=TimeoutError("timed out"))

        resp = await self.handler.default(self._make_update_request())
        self.assertIsNotNone(resp)
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.body.decode("ascii"))
        self.assertEqual(body["ka_time"], 10)

    async def test_forward_request_does_not_block_event_loop(self):
        """Blocking HTTP call must run in worker thread so asyncio tasks keep progressing."""
        ticks = 0

        def slow_post(_request):
            time.sleep(0.15)
            return FakeResponse({"ka_time": 10, "version": 3})

        async def ticker():
            nonlocal ticks
            for _ in range(5):
                await asyncio.sleep(0.02)
                ticks += 1

        self.handler._sync_forward_request = slow_post
        Connect.request_connect = False

        res, _ = await asyncio.gather(
            self.handler.default(self._make_update_request()),
            ticker(),
        )
        self.assertIsNotNone(res)
        self.assertGreaterEqual(ticks, 3)


if __name__ == "__main__":
    unittest.main()
