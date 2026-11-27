"""Unit and concurrency tests for MessageIdMapper, FlowManager, and MessageRouter (socket mode)."""

import asyncio
import unittest

from visonic_proxy.const import (
    VIS_ACK,
    VIS_BBA,
    ConnectionName,
    ConnectionPriority,
    ConnectionStatus,
    ManagedMessages,
)
from visonic_proxy.events import Event, EventType
from visonic_proxy.helpers.crc16 import Crc16Arc
from visonic_proxy.managers.flow_manager import FlowManager, WaitingAck
from visonic_proxy.managers.message_id_mapper import MessageIdMapper
from visonic_proxy.message import QueuedMessage
from visonic_proxy.proxy import Proxy
from visonic_proxy.transcoders.builder import MessageBuilder
from visonic_proxy.transcoders.pl31_decoder import PowerLink31MessageDecoder


def verify_pl31_crc(raw: bytes) -> bool:
    """Verify PowerLink 3.1 CRC16-ARC header matches payload from first quote to closing bracket."""
    header_crc = raw[1:5].decode("ascii").upper()
    body = raw[9:-1]
    return header_crc == Crc16Arc.calchex(body).upper()


class TestMessageIdMapper(unittest.TestCase):
    """Tests for independent Alarm <-> Visonic msg_id translation."""

    def test_independent_sequences_after_ha_injection(self):
        """HA injections advance Alarm msg_id without desyncing Visonic msg_id."""
        mapper = MessageIdMapper()
        # Initial traffic from Alarm
        vis_init = mapper.map_alarm_to_visonic(5564)
        self.assertEqual(vis_init, 5564)

        # Visonic sends 5565 -> Alarm gets 5565
        alarm_id_1 = mapper.map_visonic_to_alarm(5565)
        self.assertEqual(alarm_id_1, 5565)
        self.assertEqual(mapper.resolve_alarm_ack_for_visonic(5565), 5565)

        # HA injects two messages to Alarm: 5566 and 5567
        self.assertEqual(mapper.next_alarm_msg_id(), 5566)
        self.assertEqual(mapper.next_alarm_msg_id(), 5567)

        # Now Visonic sends its next message 5566 -> translated to Alarm 5568
        alarm_id_2 = mapper.map_visonic_to_alarm(5566)
        self.assertEqual(alarm_id_2, 5568)
        self.assertEqual(mapper.resolve_alarm_ack_for_visonic(5568), 5566)

        # Alarm replies with 5569 -> translated to Visonic 5567
        vis_reply_id = mapper.map_alarm_to_visonic(5569)
        self.assertEqual(vis_reply_id, 5567)
        self.assertEqual(mapper.resolve_visonic_ack_for_alarm(5567), 5569)

    def test_wraparound_and_bounded_eviction(self):
        """IDs wrap from 9999 to 1 and correlation tables respect max_entries."""
        mapper = MessageIdMapper(max_entries=3)
        mapper.observe_alarm_msg_id(9999)
        self.assertEqual(mapper.next_alarm_msg_id(), 1)

        for i in range(1, 6):
            mapper.map_visonic_to_alarm(i)
        self.assertEqual(len(mapper._alarm_to_visonic), 3)


class TestSocketModeConcurrency(unittest.IsolatedAsyncioTestCase):
    """End-to-end concurrency tests for socket mode (websocket_mode=False)."""

    async def asyncSetUp(self):
        self.loop = asyncio.get_running_loop()
        self.proxy = Proxy(self.loop, None)
        self.proxy.config.WEBSOCKET_MODE = False
        self.proxy.config.ENABLE_MSG_ID_TRANSLATION = True
        self.proxy.config.TRANSACTION_WINDOW_SECONDS = 0.5
        self.proxy.config.ACK_TIMEOUT = 0.2
        self.proxy.status.disconnected_mode = False
        self.proxy.account_id = "001234"
        self.proxy.panel_id = "2A4CC3"

        self.builder = MessageBuilder(self.proxy)
        self.decoder = PowerLink31MessageDecoder()
        self.flow = FlowManager(self.proxy)
        self.sent: list[QueuedMessage] = []

        async def fake_send(msg: QueuedMessage):
            self.sent.append(msg)

        # Register ALARM, VISONIC, and ALARM_MONITOR (socket mode -> send_non_pl31_messages=True)
        self.proxy.clients.add(
            ConnectionName.ALARM,
            1,
            object(),
            ConnectionStatus.CONNECTED,
            ConnectionPriority.ALARM,
            send_non_pl31_messages=False,
        )
        self.proxy.clients.add(
            ConnectionName.VISONIC,
            1,
            object(),
            ConnectionStatus.CONNECTED,
            ConnectionPriority.VISONIC,
            send_non_pl31_messages=False,
        )
        self.proxy.clients.add(
            ConnectionName.ALARM_MONITOR,
            1,
            object(),
            ConnectionStatus.CONNECTED,
            ConnectionPriority.ALARM_MONITOR,
            send_non_pl31_messages=True,
        )

        await self.flow.start(fake_send)

    async def asyncTearDown(self):
        await self.flow.stop()

    def _pl31_bytes(
        self, msg_id: int, payload_hex: str, is_ack: bool = False, account_id: str = "001234"
    ) -> bytes:
        msg = self.builder.build_powerlink31_message(
            msg_id,
            bytes.fromhex(payload_hex),
            is_ack=is_ack,
            account_id=account_id,
            panel_id="2A4CC3",
        )
        return bytes(msg.raw_data)

    async def test_ack_timeout_clears_ack_awaiter(self):
        """ack_timeout must clear ack_awaiter and release send queue."""
        self.flow.ack_awaiter = WaitingAck(
            ConnectionName.ALARM, 1, ConnectionName.ALARM_MONITOR, 1, 100
        )
        self.flow.hold_send_queue()

        await self.flow.ack_timeout(
            Event(ConnectionName.ALARM, EventType.ACK_TIMEOUT, 1, {"msg_id": 100})
        )
        self.assertIsNone(self.flow.ack_awaiter)
        self.assertTrue(self.flow.is_rts)

    async def test_ha_response_isolated_from_visonic_and_subsequent_visonic_msg_id_translated(
        self,
    ):
        """HA queries do not leak to Visonic, and Visonic keeps contiguous msg_ids."""
        # Seed Alarm & Visonic at msg_id 100
        self.flow.message_id_mapper.observe_alarm_msg_id(100)
        self.flow.message_id_mapper.observe_visonic_msg_id(100)

        # 1. HA (socket mode) sends a b0 status query (non-PL31 raw bytes)
        ha_query = self.builder.message_preprocessor(bytes.fromhex("b0 24")).data
        self.flow.data_received(ConnectionName.ALARM_MONITOR, 1, ha_query)
        await asyncio.sleep(0.05)

        # Alarm should receive VIS-BBA with alarm msg_id 101
        alarm_msgs = [m for m in self.sent if m.destination == ConnectionName.ALARM]
        self.assertEqual(len(alarm_msgs), 1)
        self.assertEqual(alarm_msgs[0].message.msg_id, 101)
        self.assertEqual(alarm_msgs[0].message.msg_type, VIS_BBA)

        # 2. Alarm sends VIS-ACK(101) and VIS-BBA(102) response
        self.flow.data_received(
            ConnectionName.ALARM,
            1,
            self._pl31_bytes(101, ManagedMessages.PL_ACK, is_ack=True),
        )
        await asyncio.sleep(0.05)

        panel_reply = "0d b0 03 24 01 00 43 e2 0a"
        self.flow.data_received(
            ConnectionName.ALARM,
            1,
            self._pl31_bytes(102, panel_reply, is_ack=False),
        )
        await asyncio.sleep(0.05)

        # Visonic MUST NOT have received HA's panel response
        visonic_msgs = [m for m in self.sent if m.destination == ConnectionName.VISONIC]
        self.assertEqual(len(visonic_msgs), 0)

        # HA MUST have received the ACK and the panel response
        ha_msgs = [m for m in self.sent if m.destination == ConnectionName.ALARM_MONITOR]
        self.assertGreaterEqual(len(ha_msgs), 2)

        # Proxy (CM) MUST have ACKed Alarm's VIS-BBA(102)
        cm_acks = [
            m
            for m in self.sent
            if m.destination == ConnectionName.ALARM
            and m.source == ConnectionName.CM
            and m.message.msg_type == VIS_ACK
            and m.message.msg_id == 102
        ]
        self.assertEqual(len(cm_acks), 1)

        # 3. Now mobile app (VISONIC) sends its next command with visonic msg_id=101
        vis_cmd = self._pl31_bytes(101, "0d b0 01 0f 01 05 43 f6 0a", is_ack=False, account_id="0")
        self.flow.data_received(ConnectionName.VISONIC, 1, vis_cmd)
        await asyncio.sleep(0.05)

        # Proxy must translate Visonic 101 -> Alarm 103 with valid CRC16
        vis_to_alarm = [
            m
            for m in self.sent
            if m.source == ConnectionName.VISONIC
            and m.destination == ConnectionName.ALARM
            and m.message.msg_type == VIS_BBA
        ]
        self.assertEqual(len(vis_to_alarm), 1)
        self.assertEqual(vis_to_alarm[0].message.msg_id, 103)
        self.assertTrue(verify_pl31_crc(bytes(vis_to_alarm[0].message.raw_data)))

        # 4. Alarm sends VIS-ACK(103) -> Proxy translates back to VIS-ACK(101) for Visonic
        self.flow.data_received(
            ConnectionName.ALARM,
            1,
            self._pl31_bytes(103, ManagedMessages.PL_ACK, is_ack=True),
        )
        await asyncio.sleep(0.05)

        ack_to_visonic = [
            m
            for m in self.sent
            if m.destination == ConnectionName.VISONIC and m.message.msg_type == VIS_ACK
        ]
        self.assertEqual(len(ack_to_visonic), 1)
        self.assertEqual(ack_to_visonic[0].message.msg_id, 101)
        self.assertTrue(verify_pl31_crc(bytes(ack_to_visonic[0].message.raw_data)))

        # 5. Alarm sends VIS-BBA(104) response to Visonic -> Visonic gets 102 AND HA gets passive copy
        ha_count_before = len(
            [m for m in self.sent if m.destination == ConnectionName.ALARM_MONITOR]
        )
        self.flow.data_received(
            ConnectionName.ALARM,
            1,
            self._pl31_bytes(104, panel_reply, is_ack=False),
        )
        await asyncio.sleep(0.05)

        bba_to_visonic = [
            m
            for m in self.sent
            if m.destination == ConnectionName.VISONIC and m.message.msg_type == VIS_BBA
        ]
        self.assertEqual(len(bba_to_visonic), 1)
        self.assertEqual(bba_to_visonic[0].message.msg_id, 102)
        self.assertTrue(verify_pl31_crc(bytes(bba_to_visonic[0].message.raw_data)))

        ha_count_after = len(
            [m for m in self.sent if m.destination == ConnectionName.ALARM_MONITOR]
        )
        self.assertEqual(ha_count_after, ha_count_before + 1)

    async def test_ha_waits_for_active_visonic_transaction_then_proceeds(self):
        """HA request to Alarm waits while Visonic owns the channel and proceeds once Visonic ACKs."""
        self.flow.message_id_mapper.observe_alarm_msg_id(200)
        self.flow.message_id_mapper.observe_visonic_msg_id(200)

        # Visonic sends a command to Alarm (claims transaction ownership)
        vis_cmd = self._pl31_bytes(
            201, "0d b0 01 0f 01 05 43 f6 0a", is_ack=False, account_id="0"
        )
        self.flow.data_received(ConnectionName.VISONIC, 1, vis_cmd)
        await asyncio.sleep(0.03)

        # Alarm ACKs Visonic's command (rts released, but Visonic still owns transaction until response ACK)
        self.flow.data_received(
            ConnectionName.ALARM,
            1,
            self._pl31_bytes(201, ManagedMessages.PL_ACK, is_ack=True),
        )
        await asyncio.sleep(0.03)

        # Now HA sends a concurrent query while Visonic transaction is still active
        ha_query = self.builder.message_preprocessor(bytes.fromhex("b0 24")).data
        self.flow.data_received(ConnectionName.ALARM_MONITOR, 1, ha_query)
        await asyncio.sleep(0.05)

        # HA's query must NOT have been sent to Alarm yet while Visonic owns the transaction
        ha_to_alarm_before = [
            m
            for m in self.sent
            if m.source == ConnectionName.ALARM_MONITOR
            and m.destination == ConnectionName.ALARM
        ]
        self.assertEqual(len(ha_to_alarm_before), 0)

        # Visonic ACKs the panel's reply -> releases transaction ownership immediately
        self.flow.data_received(
            ConnectionName.VISONIC,
            1,
            self._pl31_bytes(202, ManagedMessages.PL_ACK, is_ack=True, account_id="0"),
        )
        await asyncio.sleep(0.05)

        # Now HA's queued query MUST proceed to Alarm
        ha_to_alarm_after = [
            m
            for m in self.sent
            if m.source == ConnectionName.ALARM_MONITOR
            and m.destination == ConnectionName.ALARM
        ]
        self.assertEqual(len(ha_to_alarm_after), 1)

    async def test_clients_get_first_client_prefers_connected(self):
        """Clients.get_first_client should select CONNECTED over DISCONNECTING."""
        self.proxy.clients.update_status(
            ConnectionName.ALARM, 1, ConnectionStatus.DISCONNECTING
        )
        self.proxy.clients.add(
            ConnectionName.ALARM,
            2,
            object(),
            ConnectionStatus.CONNECTED,
            ConnectionPriority.ALARM,
        )
        first = self.proxy.clients.get_first_client(ConnectionName.ALARM)
        self.assertIsNotNone(first)
        self.assertEqual(first.id, 2)

    async def test_alarm_hello_forwarded_when_visonic_is_still_connecting(self):
        """Initial Alarm HELLO arriving while Visonic is CONNECTING must be queued and delivered."""
        self.proxy.status.disconnected_mode = True
        self.proxy.clients.update_status(
            ConnectionName.VISONIC, 1, ConnectionStatus.CONNECTING
        )

        # Alarm sends HELLO before Visonic TCP handshake completes
        hello = self._pl31_bytes(9906, ManagedMessages.HELLO, is_ack=False)
        self.flow.data_received(ConnectionName.ALARM, 1, hello)
        await asyncio.sleep(0.03)

        # Simulate Visonic completing TCP handshake 30ms later
        self.proxy.clients.update_status(
            ConnectionName.VISONIC, 1, ConnectionStatus.CONNECTED
        )
        self.proxy.status.disconnected_mode = False
        self.flow.pending_has_connected.set()
        await asyncio.sleep(0.05)

        visonic_msgs = [m for m in self.sent if m.destination == ConnectionName.VISONIC]
        self.assertEqual(len(visonic_msgs), 1)
        self.assertEqual(
            visonic_msgs[0].message.data, bytes.fromhex(ManagedMessages.HELLO)
        )
        # CM must NOT have spoofed a local VIS-ACK for HELLO while Visonic was connecting
        cm_acks = [
            m
            for m in self.sent
            if m.source == ConnectionName.CM and m.destination == ConnectionName.ALARM
        ]
        self.assertEqual(len(cm_acks), 0)


if __name__ == "__main__":
    unittest.main()
