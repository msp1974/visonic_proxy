"""Regression tests for P2 event-driven waits and transcoder cleanup."""

import asyncio
import time
import unittest
from unittest.mock import AsyncMock

try:
    from tests._stubs import install_missing_stubs
except ImportError:
    from _stubs import install_missing_stubs

install_missing_stubs()

from visonic_proxy.connections.visonic_client import VisonicClient
from visonic_proxy.const import ACK
from visonic_proxy.proxy import Proxy
from visonic_proxy.transcoders.b0_decoder import B0Decoder
from visonic_proxy.transcoders.builder import MessageBuilder
from visonic_proxy.transcoders.helpers import calculate_message_checksum


class TestP2EventDrivenWaitsAndCleanup(unittest.IsolatedAsyncioTestCase):
    """Tests for P2 asyncio.Event waits and transcoder deduplication."""

    async def test_wait_for_responses_wakes_immediately_on_event(self):
        """wait_for_responses must wake via asyncio.Event without sleep polling."""
        loop = asyncio.get_running_loop()
        proxy = Proxy(loop, None)
        sent: list[bytes] = []
        client = VisonicClient(proxy, cb_send_message=sent.append, cb_send_websocket_message=AsyncMock())
        client.stop()
        await asyncio.sleep(0)

        client.waiting_for = [ACK, "24"]
        client.last_sent_message = b"\x0d\xb0\x01\x24\x01\x05\x43\x00\x0a"

        async def deliver_responses():
            await asyncio.sleep(0.02)
            client.register_received_message(ACK)
            client.register_received_message("24")

        t0 = time.monotonic()
        wait_task = asyncio.create_task(client.wait_for_responses(timeout=2.0, retries=1))
        deliver_task = asyncio.create_task(deliver_responses())
        ok, _ = await asyncio.gather(wait_task, deliver_task)
        elapsed = time.monotonic() - t0

        self.assertTrue(ok)
        self.assertTrue(client.rts.is_set())
        self.assertLess(elapsed, 0.5)

    async def test_wait_for_responses_retries_and_fails_cleanly_on_timeout(self):
        """wait_for_responses must resend on timeout and return False once retries exhaust."""
        loop = asyncio.get_running_loop()
        proxy = Proxy(loop, None)
        sent: list[bytes] = []
        client = VisonicClient(proxy, cb_send_message=sent.append, cb_send_websocket_message=AsyncMock())
        client.stop()
        await asyncio.sleep(0)

        client.waiting_for = ["24"]
        client.last_sent_message = b"\x0d\xb0\x01\x24\x01\x05\x43\x00\x0a"

        ok = await client.wait_for_responses(timeout=0.03, retries=2)
        self.assertFalse(ok)
        self.assertEqual(len(sent), 2)
        self.assertEqual(client.waiting_for, [])
        self.assertTrue(client.rts.is_set())

    async def test_wait_for_empty_queue_uses_queue_join(self):
        """wait_for_empty_queue must return once queued items are marked task_done."""
        loop = asyncio.get_running_loop()
        proxy = Proxy(loop, None)
        client = VisonicClient(proxy, cb_send_message=lambda _: None, cb_send_websocket_message=AsyncMock())
        client.stop()
        await asyncio.sleep(0)

        client.send_message_no_wait(b"\x0d\x02\xfd\x0a")

        async def drain():
            await asyncio.sleep(0.01)
            await client.send_queue.get()
            client.send_queue.task_done()

        await asyncio.gather(client.wait_for_empty_queue(), drain())
        self.assertEqual(client.send_queue.qsize(), 0)

    def test_builder_checksum_and_b0_decoder_reuses_formatters(self):
        """MessageBuilder checksum must match helper and B0Decoder must cache B0Formatters."""
        loop = asyncio.new_event_loop()
        try:
            proxy = Proxy(loop, None)
            builder = MessageBuilder(proxy)
            payload = bytes.fromhex("b0 01 6a 00 43")
            self.assertEqual(
                builder._calculate_message_checksum(payload),
                calculate_message_checksum(payload),
            )
            decoder = B0Decoder()
            self.assertIs(decoder._formatters, decoder._formatters)
        finally:
            loop.close()


if __name__ == "__main__":
    unittest.main()
