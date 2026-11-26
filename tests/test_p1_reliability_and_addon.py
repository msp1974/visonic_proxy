"""Regression tests for P1 reliability, lifecycle, persistence, and modularization."""

import asyncio
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock

try:
    from tests._stubs import install_missing_stubs
except ImportError:
    from _stubs import install_missing_stubs

install_missing_stubs()

from visonic_proxy.connections.manager import ConnectionManager
from visonic_proxy.connections.server import ServerConnection
from visonic_proxy.connections.visonic_client import VisonicClient as DirectVisonicClient
from visonic_proxy.connections.watchdog import Watchdog
from visonic_proxy.connections.websocket import CMStatus, VisonicClient, WebsocketServer
from visonic_proxy.const import (
    ConnectionName,
    ConnectionPriority,
    ConnectionStatus,
)
from visonic_proxy.events import Event, EventType
from visonic_proxy.helpers.ssl import (
    ADDON_CERTS_PATH,
    get_ssl_certs_path,
)
from visonic_proxy.managers.storage_manager import STATUS, DataStore
from visonic_proxy.proxy import Proxy
from visonic_proxy.transcoders.refs import MessageType


class TestAddOnPersistenceAndModularizationP1(unittest.TestCase):
    """Tests for HA-01 and ARC-01."""

    def test_get_ssl_certs_path_uses_persistent_data_dir_in_addon_mode(self):
        """Add-on mode must persist TLS certs under /data/certs."""
        self.assertEqual(
            get_ssl_certs_path("certs", is_addon=True),
            ADDON_CERTS_PATH,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            standalone = get_ssl_certs_path("certs", is_addon=False, base_dir=tmpdir)
            self.assertEqual(Path(standalone), Path(tmpdir) / "certs")

    def test_websocket_reexports_visonic_client_for_backwards_compatibility(self):
        """Splitting visonic_client.py must preserve imports from websocket.py."""
        self.assertIs(VisonicClient, DirectVisonicClient)
        self.assertIsNotNone(CMStatus)
        self.assertIsNotNone(WebsocketServer)


class TestEventsAndDataStoreP1(unittest.IsolatedAsyncioTestCase):
    """Tests for BUG-12 and BUG-14."""

    async def test_event_dispatch_isolates_listener_failure_and_unsubscribe_safe(self):
        """A failing listener must not prevent subsequent listeners from receiving the event."""
        loop = asyncio.get_running_loop()
        proxy = Proxy(loop, None)
        received: list[str] = []

        async def bad_listener(_event: Event):
            raise RuntimeError("listener boom")

        def good_listener(event: Event):
            received.append(str(event.event_data))

        unsub_bad = proxy.events.subscribe(
            ConnectionName.ALARM, EventType.DATA_RECEIVED, bad_listener
        )
        unsub_good = proxy.events.subscribe(
            ConnectionName.ALARM, EventType.DATA_RECEIVED, good_listener
        )

        ok = await proxy.events._async_fire_event(
            Event(ConnectionName.ALARM, EventType.DATA_RECEIVED, event_data="hello")
        )
        self.assertFalse(ok)
        self.assertEqual(received, ["hello"])

        # Unsubscribe must cleanly remove without mutation bugs
        unsub_bad()
        unsub_good()
        self.assertEqual(proxy.events.listeners, {})

    def test_datastore_combine_dict_handles_primitives_and_non_dict_transition(self):
        """DataStore must safely merge primitive values and transition to paged responses."""
        store = DataStore()
        merged = store._combine_dict({"a": 1, "b": [1], "c": {"x": 1}}, {"a": 2, "b": [2], "c": {"y": 2}})
        self.assertEqual(merged, {"a": 2, "b": [1, 2], "c": {"x": 1, "y": 2}})

        # Prior non-dict value (e.g. list) followed by PAGED_RESPONSE page != 1 must not raise AttributeError
        store.store(STATUS, MessageType.RESPONSE, "24", 0, 0, ["initial"], "00")
        store.store(STATUS, MessageType.PAGED_RESPONSE, "24", 0, 2, ["p2"], "02")
        store.store(STATUS, MessageType.RESPONSE, "24", 0, 3, ["p3"], "03")
        self.assertEqual(store.get_status("24_panel_status"), ["p2", "p3"])

        # Out-of-bounds EPROM write must not raise IndexError
        store.store_eprom(65534, "01 02 03 04 05")
        self.assertEqual(store.get_eprom()[65534], "01")
        self.assertEqual(store.get_eprom()[65535], "02")


class TestManagerServerWatchdogP1(unittest.IsolatedAsyncioTestCase):
    """Tests for BUG-15 and monotonic watchdog/server timers."""

    async def test_server_get_client_id_distinguishes_same_port_different_ip(self):
        """ServerConnection.get_client_id must match both IP and port."""
        loop = asyncio.get_running_loop()
        proxy = Proxy(loop, None)
        server = ServerConnection(proxy, ConnectionName.ALARM, "127.0.0.1", 5001)

        t1 = MagicMock()
        t1.get_extra_info.return_value = ("192.168.1.10", 40000)
        t2 = MagicMock()
        t2.get_extra_info.return_value = ("192.168.1.20", 40000)

        server.client_connected(t1)
        server.client_connected(t2)

        self.assertEqual(server.get_client_id(t1), 1)
        self.assertEqual(server.get_client_id(t2), 2)

    async def test_manager_disconnection_checks_alarm_monitor_count_and_stops_safely(self):
        """disconnection_event should send status when ALARM_MONITOR is connected, even with 0 alarms."""
        loop = asyncio.get_running_loop()
        proxy = Proxy(loop, None)
        cm = ConnectionManager(proxy)
        cm.webserver = MagicMock()
        cm.webserver.stop = AsyncMock()
        cm.flow_manager.message_router.command_manager.send_status_message = AsyncMock()

        proxy.clients.add(
            ConnectionName.ALARM_MONITOR,
            1,
            MagicMock(),
            ConnectionStatus.CONNECTED,
            ConnectionPriority.ALARM_MONITOR,
        )

        await cm.disconnection_event(
            Event(ConnectionName.ALARM, EventType.DISCONNECTION, client_id=1)
        )
        cm.flow_manager.message_router.command_manager.send_status_message.assert_awaited_once()

        # stop() must succeed even if webserver is None
        cm.webserver = None
        cm.flow_manager.stop = AsyncMock()
        await cm.stop()

    async def test_watchdog_uses_monotonic_clock_and_fires_disconnect(self):
        """Watchdog must trigger REQUEST_DISCONNECT after inactive_period using monotonic time."""
        loop = asyncio.get_running_loop()
        proxy = Proxy(loop, None)
        events: list[Event] = []
        unsub = proxy.events.subscribe(
            ConnectionName.ALARM, EventType.REQUEST_DISCONNECT, events.append
        )

        wd = Watchdog(proxy, ConnectionName.ALARM, inactive_period=10)
        wd._run_watchdog = False  # Don't reschedule timer during direct _runner test
        wd._last_activity_tracker[1] = time.monotonic() - 20

        try:
            wd._runner()
            await asyncio.sleep(0.02)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].client_id, 1)
        finally:
            wd.stop_sync()
            unsub()


if __name__ == "__main__":
    unittest.main()
