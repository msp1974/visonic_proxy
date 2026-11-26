"""Unit tests for DataStore and VisonicClient stability & concurrency fixes."""

import asyncio
import unittest
from unittest.mock import AsyncMock

try:
    from tests._stubs import install_missing_stubs
except ImportError:
    from _stubs import install_missing_stubs

install_missing_stubs()

from visonic_proxy.connections.websocket import CMStatus, VisonicClient
from visonic_proxy.managers.storage_manager import SETTINGS, STATUS, DataStore
from visonic_proxy.proxy import Proxy
from visonic_proxy.transcoders.b0_decoder import B0Message
from visonic_proxy.transcoders.helpers import get_lookup_value
from visonic_proxy.transcoders.refs import (
    B0CommandName,
    Command35Settings,
    MessageClass,
    MessageType,
)


class TestDataStore(unittest.TestCase):
    """Tests for DataStore page handling and ordering."""

    def test_store_status_page_255_does_not_raise_and_orders_pages(self):
        """page=255 should compute next page safely and rebuild pages in order."""
        store = DataStore()
        store.store(STATUS, MessageType.PAGED_RESPONSE, "24", 0, 1, ["a"], "01")
        store.store(STATUS, MessageType.PAGED_RESPONSE, "24", 0, 255, ["b"], "02")
        store.store(STATUS, MessageType.RESPONSE, "24", 0, 3, ["c"], "03")

        key = f"24_{get_lookup_value(B0CommandName, '24')}"
        result = store.get_status(key)
        self.assertEqual(result, ["a", "b", "c"])

    def test_store_settings_page_255_does_not_raise(self):
        """Settings paged response with page=255 should not raise TypeError."""
        store = DataStore()
        store.store(SETTINGS, MessageType.PAGED_RESPONSE, "35", 1, 1, {"k1": 1}, "01")
        store.store(SETTINGS, MessageType.PAGED_RESPONSE, "35", 1, 255, {"k2": 2}, "02")
        store.store(SETTINGS, MessageType.RESPONSE, "35", 1, 3, {"k3": 3}, "03")

        key = f"1_{get_lookup_value(Command35Settings, 1)}"
        result = store.get_setting(key)
        self.assertEqual(result, {"k1": 1, "k2": 2, "k3": 3})


class TestVisonicClientConcurrency(unittest.IsolatedAsyncioTestCase):
    """Tests for VisonicClient lock safety, flags, and ASK_ME deduplication."""

    async def asyncSetUp(self):
        """Set up a VisonicClient with mocked callbacks."""
        self.loop = asyncio.get_running_loop()
        self.proxy = Proxy(self.loop, None)
        self.sent_messages: list[bytes] = []
        self.ws_messages: list[str] = []

        async def ws_cb(msg):
            self.ws_messages.append(msg)

        self.client = VisonicClient(
            self.proxy,
            cb_send_message=self.sent_messages.append,
            cb_send_websocket_message=ws_cb,
        )
        # Cancel background tasks so tests remain deterministic
        self.client.stop()
        await asyncio.sleep(0)

    async def test_request_in_progress_resets_on_exception(self):
        """get_panel_status must reset request_in_progress even if get_panel_info fails."""
        self.client.is_init = True
        self.client.get_panel_info = AsyncMock(side_effect=RuntimeError("boom"))

        with self.assertRaises(RuntimeError):
            await self.client.get_panel_status(refresh_key_data=True)

        self.assertFalse(self.client.request_in_progress)

    async def test_send_lock_released_on_exception(self):
        """send_message_and_wait must release send_lock on failure."""
        self.client._send_message_and_wait = AsyncMock(
            side_effect=RuntimeError("send error")
        )

        with self.assertRaises(RuntimeError):
            await self.client.send_message_and_wait(b"\x0d\x02\xfd\x0a")

        self.assertFalse(self.client.send_lock.locked())

    async def test_ask_me_ignored_when_visonic_connected(self):
        """When PowerManage (VISONIC) is connected, VisonicClient must not duplicate ASK_ME queries."""
        self.client.cm_status = CMStatus(alarm_connections=1, visonic_connections=1)
        dec = B0Message(
            msg_type=MessageType.RESPONSE,
            cmd=B0CommandName.ASK_ME,
            setting=0,
            page=0,
            data=["24", "0f"],
            raw_data=b"",
        )

        await self.client.process_message(MessageClass.B0, dec)
        self.assertEqual(self.client.send_queue.qsize(), 0)

    async def test_ask_me_handled_when_visonic_disconnected(self):
        """When PowerManage is disconnected, VisonicClient should still answer ASK_ME."""
        self.client.cm_status = CMStatus(alarm_connections=1, visonic_connections=0)
        dec = B0Message(
            msg_type=MessageType.RESPONSE,
            cmd=B0CommandName.ASK_ME,
            setting=0,
            page=0,
            data=["24"],
            raw_data=b"",
        )

        await self.client.process_message(MessageClass.B0, dec)
        self.assertEqual(self.client.send_queue.qsize(), 1)


if __name__ == "__main__":
    unittest.main()
