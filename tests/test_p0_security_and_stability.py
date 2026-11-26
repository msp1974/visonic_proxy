"""Regression tests for P0 security, configuration, transcoder, and asyncio stability fixes."""

import asyncio
import json
import logging
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

try:
    from tests._stubs import install_missing_stubs
except ImportError:
    from _stubs import install_missing_stubs

install_missing_stubs()

from visonic_proxy.connections.client import ClientConnection
from visonic_proxy.connections.httpserver.utils import (
    HttpBadRequestError,
    HttpPayloadTooLargeError,
    http_parser,
)
from visonic_proxy.connections.manager import ConnectionManager
from visonic_proxy.connections.webserver import MyHandler
from visonic_proxy.connections.websocket import VisonicClient, WebsocketServer
from visonic_proxy.const import (
    Config,
    ConnectionName,
    ConnectionPriority,
    ConnectionStatus,
    ManagedMessages,
)
from visonic_proxy.events import Event, EventType
from visonic_proxy.helpers.env import process_env_vars, redact_config_value
from visonic_proxy.logger import VPLogger
from visonic_proxy.managers.flow_manager import FlowManager
from visonic_proxy.proxy import Proxy
from visonic_proxy.transcoders.b0_decoder import (
    B0Decoder,
    B0Message,
    InvalidMessageException,
)
from visonic_proxy.transcoders.builder import MessageBuilder
from visonic_proxy.transcoders.standard_message import STDMessage


class TestConfigAndStartupP0(unittest.TestCase):
    """Tests for CFG-01 and BUG-06."""

    def test_process_env_vars_reads_addon_options_and_coerces_types(self):
        """Addon options.json and env vars should coerce types without mutating Config class."""
        orig_host = Config.VISONIC_HOST
        orig_port = Config.MESSAGE_PORT
        orig_ws_mode = Config.WEBSOCKET_MODE

        with tempfile.TemporaryDirectory() as tmpdir:
            options_file = Path(tmpdir) / "options.json"
            options_file.write_text(
                json.dumps(
                    {
                        "visonic_host": "10.0.0.5",
                        "websocket_mode": True,
                        "websocket_ssl": False,
                        "websocket_auth_key": "super-secret-token",
                        "message_log_level": 4,
                        "log_level": "debug",
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"MESSAGE_PORT": "5099", "TRANSACTION_WINDOW_SECONDS": "3.5"},
                clear=False,
            ):
                cfg = process_env_vars(options_path=str(options_file))

        self.assertEqual(cfg.VISONIC_HOST, "10.0.0.5")
        self.assertTrue(cfg.WEBSOCKET_MODE)
        self.assertFalse(cfg.WEBSOCKET_SSL)
        self.assertEqual(cfg.WEBSOCKET_AUTH_KEY, "super-secret-token")
        self.assertEqual(cfg.MESSAGE_LOG_LEVEL, 4)
        self.assertEqual(cfg.LOG_LEVEL, logging.DEBUG)
        self.assertEqual(cfg.MESSAGE_PORT, 5099)
        self.assertIsInstance(cfg.MESSAGE_PORT, int)
        self.assertEqual(cfg.TRANSACTION_WINDOW_SECONDS, 3.5)
        self.assertIsInstance(cfg.TRANSACTION_WINDOW_SECONDS, float)

        # Global Config class defaults must remain untouched
        self.assertEqual(Config.VISONIC_HOST, orig_host)
        self.assertEqual(Config.MESSAGE_PORT, orig_port)
        self.assertEqual(Config.WEBSOCKET_MODE, orig_ws_mode)

    def test_redact_config_value_masks_secret(self):
        """Sensitive config values must be redacted for logging."""
        self.assertEqual(
            redact_config_value("WEBSOCKET_AUTH_KEY", "my-secret"), "***REDACTED***"
        )
        self.assertEqual(redact_config_value("VISONIC_HOST", "1.2.3.4"), "1.2.3.4")

    def test_logger_rollover_safe_without_file_handler(self):
        """VPLogger.rollover() must not raise AttributeError when LOG_FILE is empty."""
        vp_logger = VPLogger(log_file="")
        vp_logger.rollover()  # Should not raise


class TestSecurityAndHttpParserP0(unittest.IsolatedAsyncioTestCase):
    """Tests for SEC-01, SEC-03, and BUG-07."""

    async def test_decode_image_sanitizes_path_traversal_and_preserves_crlf_bytes(self):
        """decode_image must prevent path traversal and not truncate JPEG bytes on CRLF."""
        loop = asyncio.get_running_loop()
        proxy = Proxy(loop, None)
        handler = MyHandler(proxy, request_connect=False)
        events: list[Event] = []
        unsub = proxy.events.subscribe(
            ConnectionName.ALARM_MONITOR, EventType.NEW_CAMERA_IMAGE, events.append
        )

        # Binary payload containing \r\n that previously got truncated
        jpeg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\r\nMIDDLE\r\nEND\xff\xd9"
        body = (
            b"serial: ../../evil/panel\r\n"
            b"camera: ../2\r\n"
            b"frameNum: 0\r\n"
            b"filesCount: 1\r\n"
            b"data: 999\r\n"
            + jpeg_bytes
        )

        saved_calls: list[tuple[bytes, Path]] = []

        def fake_save(data_bytes: bytes, target_path: Path):
            saved_calls.append((data_bytes, target_path))

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                with patch.object(MyHandler, "_save_image_sync", side_effect=fake_save):
                    await handler.decode_image(body, images_dir=tmpdir)
                await asyncio.sleep(0.02)

                self.assertEqual(len(saved_calls), 1)
                saved_bytes, saved_path = saved_calls[0]
                self.assertEqual(saved_bytes, jpeg_bytes)
                self.assertTrue(saved_path.is_relative_to(Path(tmpdir).resolve()))
                self.assertNotIn("..", saved_path.name)
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0].event_data["data"], jpeg_bytes)
        finally:
            unsub()

    async def test_http_parser_rejects_oversized_content_length(self):
        """http_parser must raise HttpPayloadTooLargeError above max_content_length."""
        reader = asyncio.StreamReader()
        reader.feed_data(
            b"POST /scripts/update.php HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Content-Length: 999999999\r\n\r\n"
        )
        reader.feed_eof()

        with self.assertRaises(HttpPayloadTooLargeError):
            await http_parser(reader, timeout=1.0, http_trace=False, max_content_length=1024)

    async def test_http_parser_rejects_malformed_request_line_and_bad_length(self):
        """http_parser must raise HttpBadRequestError on malformed HTTP input."""
        bad_req = asyncio.StreamReader()
        bad_req.feed_data(b"INVALID\r\n\r\n")
        bad_req.feed_eof()
        with self.assertRaises(HttpBadRequestError):
            await http_parser(bad_req, timeout=1.0, http_trace=False)

        bad_len = asyncio.StreamReader()
        bad_len.feed_data(
            b"POST /test HTTP/1.1\r\nContent-Length: notanint\r\n\r\n"
        )
        bad_len.feed_eof()
        with self.assertRaises(HttpBadRequestError):
            await http_parser(bad_len, timeout=1.0, http_trace=False)


class TestTranscodersAndWebsocketP0(unittest.IsolatedAsyncioTestCase):
    """Tests for BUG-01, BUG-04, BUG-05, BUG-09, BUG-10, BUG-11, and SEC-02."""

    def test_dataclass_default_factories_work(self):
        """B0Message and STDMessage default data fields must be independent dicts."""
        m1 = B0Message(msg_type=1, cmd="24")
        m2 = B0Message(msg_type=1, cmd="24")
        m1.data["k"] = 1
        self.assertEqual(m2.data, {})

        s1 = STDMessage(cmd="02")
        s2 = STDMessage(cmd="02")
        s1.data["x"] = 2
        self.assertEqual(s2.data, {})

    def test_b0_decoder_raises_invalid_message_exception(self):
        """B0Decoder.decode() must raise InvalidMessageException on invalid frame."""
        decoder = B0Decoder()
        with self.assertRaises(InvalidMessageException):
            decoder.decode(b"\x00\x00\x00\x00\x00\x00")

    def test_builder_generic_request_uses_hex_length(self):
        """_build_b0_generic_request must encode parameter length in hex."""
        loop = asyncio.new_event_loop()
        try:
            proxy = Proxy(loop, None)
            builder = MessageBuilder(proxy)
            params = " ".join(["01"] * 12)  # 12 bytes = 0x0c
            result = builder._build_b0_generic_request("24", params)
            self.assertTrue(result.startswith("24 0c "))
        finally:
            loop.close()

    async def test_set_pgm_with_duration_awaits_user_codes(self):
        """set_pgm with duration must await get_setting(USER_CODES) before indexing."""
        loop = asyncio.get_running_loop()
        proxy = Proxy(loop, None)
        client = VisonicClient(proxy, cb_send_message=lambda _: None, cb_send_websocket_message=AsyncMock())
        client.stop()
        await asyncio.sleep(0)

        client.get_setting = AsyncMock(return_value=["1234"])
        client.send_message_and_wait = AsyncMock(return_value=True)

        ok = await client.set_pgm(1, True, duration=30)
        self.assertTrue(ok)
        client.send_message_and_wait.assert_awaited_once()

    async def test_websocket_receive_message_handles_missing_or_invalid_fields(self):
        """websocket_receive_message must always return a (response, send_status) tuple."""
        loop = asyncio.get_running_loop()
        proxy = Proxy(loop, None)
        ws_server = WebsocketServer(proxy, ConnectionName.ALARM_MONITOR, "0.0.0.0", 8082)
        ws_server.visonic_client = VisonicClient(
            proxy, cb_send_message=lambda _: None, cb_send_websocket_message=AsyncMock()
        )
        ws_server.visonic_client.stop()
        ws_server.visonic_client.is_init = True
        await asyncio.sleep(0)

        resp, send_status = await ws_server.websocket_receive_message("c1", {})
        self.assertIn("error", resp)
        self.assertFalse(send_status)

        resp2, send_status2 = await ws_server.websocket_receive_message(
            "c1", {"request": "setting", "id": "not-an-int"}
        )
        self.assertIn("error", resp2)
        self.assertFalse(send_status2)

    async def test_websocket_verify_authorisation_uses_constant_time_check(self):
        """verify_authorisation must allow matching Bearer token and reject invalid ones."""
        loop = asyncio.get_running_loop()
        proxy = Proxy(loop, None)
        proxy.config.WEBSOCKET_AUTH_KEY = "topsecret"
        ws_server = WebsocketServer(proxy, ConnectionName.ALARM_MONITOR, "0.0.0.0", 8082)

        fake_ws = MagicMock()
        fake_ws.remote_address = ("127.0.0.1", 12345)
        fake_ws.respond.return_value = "UNAUTHORIZED"

        ok_req = SimpleNamespace(headers={"Authorization": "Bearer topsecret"})
        bad_req = SimpleNamespace(headers={"Authorization": "Bearer wrong"})

        self.assertIsNone(ws_server.verify_authorisation(fake_ws, ok_req))
        self.assertEqual(ws_server.verify_authorisation(fake_ws, bad_req), "UNAUTHORIZED")

    async def test_get_device_info_populates_sensor_types_when_named(self):
        """Named non-zone devices must still get device_type and device_model."""
        loop = asyncio.get_running_loop()
        proxy = Proxy(loop, None)
        client = VisonicClient(proxy, cb_send_message=lambda _: None, cb_send_websocket_message=AsyncMock())
        client.stop()
        await asyncio.sleep(0)

        async def fake_get_status(cmd, key=None, refresh=False):
            if cmd == "58":  # DEVICE_INFO
                return {
                    "keypads": {
                        0: {
                            "assigned_name_id": 0,
                            "sub_type": 5,
                            "device_type_id": 7,
                        }
                    }
                }
            if cmd == "27":
                return [0]
            if cmd in ("0a", "0b"):
                return {"keypads": [0]}
            return {}

        client.get_status = AsyncMock(side_effect=fake_get_status)
        client.get_setting = AsyncMock(return_value=["Hallway Keypad"])

        devices = await client.get_device_info()
        keypad = devices["keypads"][1]
        self.assertEqual(keypad["name"], "Hallway Keypad")
        self.assertIn("device_type", keypad)
        self.assertIn("device_model", keypad)


class TestAsyncPipelineAndConnectionsP0(unittest.IsolatedAsyncioTestCase):
    """Tests for BUG-02, BUG-03, and BUG-08."""

    async def test_flow_manager_reassembles_fragmented_tcp_and_survives_garbage(self):
        """Fragmented TCP PL31 frames must reassemble and garbage must not kill the processor."""
        loop = asyncio.get_running_loop()
        proxy = Proxy(loop, None)
        proxy.account_id = "001234"
        proxy.panel_id = "2A4CC3"
        proxy.status.disconnected_mode = True
        builder = MessageBuilder(proxy)

        flow = FlowManager(proxy)
        sent = []

        async def fake_send(msg):
            sent.append(msg)

        proxy.clients.add(
            ConnectionName.ALARM,
            1,
            object(),
            ConnectionStatus.CONNECTED,
            ConnectionPriority.ALARM,
            send_non_pl31_messages=False,
        )
        await flow.start(fake_send)
        try:
            frame = bytes(
                builder.build_powerlink31_message(
                    10,
                    bytes.fromhex("0d b0 03 24 01 00 43 e2 0a"),
                    is_ack=False,
                    account_id="001234",
                    panel_id="2A4CC3",
                ).raw_data
            )
            # Send garbage prefix + first half, then second half
            flow.data_received(ConnectionName.ALARM, 1, b"GARBAGE" + frame[:12])
            await asyncio.sleep(0.03)
            self.assertFalse(flow.message_receiver_task.done())

            flow.data_received(ConnectionName.ALARM, 1, frame[12:])
            await asyncio.sleep(0.05)

            self.assertFalse(flow.message_receiver_task.done())
            # In disconnected_mode, Proxy (CM) must have sent VIS-ACK(10) back to Alarm
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0].message.msg_id, 10)
        finally:
            await flow.stop()

    async def test_disconnection_releases_pending_has_connected_and_clears_rx_buffer(self):
        """Failed CONNECTING client disconnection must release pending_has_connected."""
        loop = asyncio.get_running_loop()
        proxy = Proxy(loop, None)
        cm = ConnectionManager(proxy)
        cm.webserver = MagicMock()
        cm.flow_manager.pending_has_connected.clear()
        cm.flow_manager._rx_buffers[(ConnectionName.VISONIC, 1)] = bytearray(b"partial")

        await cm.disconnection_event(
            Event(ConnectionName.VISONIC, EventType.DISCONNECTION, client_id=1)
        )

        self.assertTrue(cm.flow_manager.pending_has_connected.is_set())
        self.assertNotIn((ConnectionName.VISONIC, 1), cm.flow_manager._rx_buffers)

    async def test_client_connection_timeout_and_resource_cleanup(self):
        """ClientConnection.connect() must time out cleanly and disconnected() must stop watchdog."""
        loop = asyncio.get_running_loop()
        proxy = Proxy(loop, None)
        events: list[Event] = []
        unsub = proxy.events.subscribe(
            ConnectionName.VISONIC, EventType.DISCONNECTION, events.append
        )

        client = ClientConnection(
            proxy, ConnectionName.VISONIC, "127.0.0.1", 5001, parent_connection_id=1, run_watchdog=True
        )
        try:
            with patch.object(
                loop, "create_connection", new=AsyncMock(side_effect=TimeoutError("timeout"))
            ):
                connected = await client.connect()
            await asyncio.sleep(0.02)

            self.assertFalse(connected)
            self.assertFalse(client.connection_in_progress)
            self.assertEqual(len(events), 1)

            # Simulate connected with watchdog, then disconnected()
            mock_transport = MagicMock()
            client.connection_made(mock_transport)
            self.assertIsNotNone(client.watchdog)
            self.assertTrue(len(client.unsubscribe_listeners) > 0)

            # Event for another client_id must NOT shut down this client
            await client.handle_disconnect_event(
                Event(ConnectionName.VISONIC, EventType.REQUEST_DISCONNECT, client_id=99)
            )
            self.assertTrue(client.connected)

            client.disconnected(mock_transport)
            self.assertFalse(client.connected)
            self.assertIsNone(client.watchdog)
            self.assertEqual(len(client.unsubscribe_listeners), 0)
        finally:
            unsub()


if __name__ == "__main__":
    unittest.main()
