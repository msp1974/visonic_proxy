"""Websocket server."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import datetime as dt
import itertools
import json
import logging

from websockets import ConnectionClosed, WebSocketServerProtocol
from websockets.server import serve

from visonic_proxy import __VERSION__

from ..const import ACK, LOGGER_NAME, VIS_ACK, ConnectionName, MsgLogLevel
from ..events import Event, EventType
from ..managers.storage_manager import DataStore
from ..message import QueuedMessage
from ..proxy import Proxy
from ..transcoders.b0_decoder import B0Decoder, B0Message
from ..transcoders.builder import MessageBuilder
from ..transcoders.helpers import (
    VPCommand,
    b2i,
    bits_to_le_bytes,
    chunk_bytearray,
    get_lookup_value,
    ibit,
    str_datetime_diff,
)
from ..transcoders.refs import (
    SENSOR_TYPES,
    B0CommandName,
    Command35Settings,
    EPROMSetting,
    EPROMSettingLookup,
    ManagedMessages,
    MessageClass,
    MessageType,
    SensorType,
)
from ..transcoders.standard_message import STDMessage, STDMessageDecoder

SEND_WEBSOCKET_STATUS_EVENT = "send_websocket_status"

INIT_STATUSES = [
    B0CommandName.PANEL_STATUS,
    B0CommandName.TRIGGERED_ZONE,
    B0CommandName.BYPASSES,
    B0CommandName.DEVICE_TYPES,
    B0CommandName.TAMPER_ACTIVES,
    B0CommandName.TAMPER_ALERTS,
    B0CommandName.ASSIGNED_NAMES,
    B0CommandName.WIRED_DEVICES_STATUS,
    B0CommandName.ASSIGNED_ZONE_TYPES,
    B0CommandName.ZONE_LAST_EVENT,
    B0CommandName.TROUBLES,
    B0CommandName.DEVICE_INFO,
    B0CommandName.ZONE_TEMPS,
    B0CommandName.ZONE_BRIGHTNESS,
]
INIT_SETTINGS = [
    Command35Settings.PANEL_SERIAL_NO,
    Command35Settings.USER_CODES,
    Command35Settings.ZONE_NAMES,
    Command35Settings.DOWNLOAD_CODE,
    Command35Settings.PANEL_EPROM_VERSION,
    Command35Settings.CAPABILITIES,
    Command35Settings.PANEL_SOFTWARE_VERSION,
    Command35Settings.PARTITIONS_ENABLED,
    Command35Settings.ZONE_CHIME,
    Command35Settings.PANEL_HARDWARE_VERSION,
    Command35Settings.POWERLINK_SW_VERSION,
]

RESPOND_MESSAGES = [B0CommandName.ASK_ME]

STATUS = "status"
SETTINGS = "settings"
EPROM = "eprom"

_LOGGER = logging.getLogger(LOGGER_NAME)


class WebsocketServer:
    """Class to manage a websocket server."""

    def __init__(
        self,
        proxy: Proxy,
        name: str,
        host: str,
        port: int | None,
        data_received_callback: Callable | None = None,
    ):
        """Init."""
        self.proxy = proxy
        self.name = name
        self.host = host
        self.port = port if port else self.proxy.config.WEBSOCKET_PORT
        self.cb_received_data = data_received_callback

        self.server_stop: asyncio.Future = None
        self.server_task: asyncio.Task = None
        self.send_processor_task: asyncio.Task | None = None
        self.websockets: dict[str, WebSocketServerProtocol] = {}

        self.send_queue = asyncio.Queue()

        self.client_id = 1
        self.visonic_client: VisonicClient

        self._unsubscribe_listeners: list[Callable] = []

    async def start_listening(self):
        """Start websocket server."""
        if not self.server_task or self.server_task.done():
            self.server_task = self.proxy.loop.create_task(
                self.run_server(), name="Websocket Server"
            )

            self.send_processor_task = self.proxy.loop.create_task(
                self._send_queue_processor(), name="Websocket Send Queue Processor"
            )

            self.visonic_client: VisonicClient = VisonicClient(
                self.proxy, self.receive_message, self.broadcast
            )

            self.client_connected()

            _LOGGER.info("Started Websocket server on port %s", self.port)

    async def run_server(self):
        """Run websocket server.

        Meant to be ruun as a task.
        """
        ## Subscribe to websocket status update events
        self._unsubscribe_listeners = [
            self.proxy.events.subscribe(
                ConnectionName.ALARM_MONITOR,
                SEND_WEBSOCKET_STATUS_EVENT,
                self.send_status,
            ),
        ]

        self.server_stop = self.proxy.loop.create_future()

        server = await serve(self.client_handler, self.host, self.port)
        await self.server_stop
        server.close()
        await server.wait_closed()

    async def shutdown(self):
        """Stop websocket server."""
        ## Unsubscribe to events.
        for unsub in self._unsubscribe_listeners:
            unsub()

        # for websocket in self.websockets.values():
        #    await websocket.close_transport()
        if self.send_processor_task and not self.send_processor_task.done():
            self.send_processor_task.cancel()

        self.visonic_client.stop()

        self.server_stop.set_result("End")
        await asyncio.sleep(0.1)
        if self.server_task and not self.server_task.done():
            self.server_task.cancel()

        _LOGGER.info("Stopped Websocket server")

    def client_connected(self):
        """Handle client connection."""

        # Fire connection event
        # Fire connection event to register client
        self.proxy.events.fire_event(
            Event(
                name=self.name,
                event_type=EventType.CONNECTION,
                client_id=self.client_id,
                event_data={
                    "connection": self,
                    "send_non_pl31_messages": True,
                },
            )
        )

    def disconnect_client(self, client_id: str):
        """Disconnect client."""

    async def client_handler(self, websocket: WebSocketServerProtocol):
        """Websocket handler."""
        self.websockets[websocket.id] = websocket

        await websocket.send(json.dumps({"connection": "success"}))

        while True:
            try:
                message = await websocket.recv()
                msg = json.loads(message)
                _LOGGER.info(
                    "Received websocket message: %s", msg, extra=MsgLogLevel.L5
                )
                response, send_status = await self.websocket_receive_message(msg)
                if response:
                    if isinstance(response, dict):
                        await websocket.send(json.dumps(response))
                    else:
                        await websocket.send(response)

                    if send_status:
                        status = await self.visonic_client.get_panel_status()
                        await self.broadcast(status)
            except json.decoder.JSONDecodeError as ex:  # noqa: PERF203
                _LOGGER.error("JSON decode error: %s", ex)
                await websocket.send(
                    json.dumps({"error": "invalid request", "message": ex.msg})
                )
                continue
            except ConnectionClosed:
                del self.websockets[websocket.id]
                break

    async def broadcast(self, message):
        """Send message to all websocket clients."""
        for websocket in self.websockets.values():
            try:
                await websocket.send(message)
            except ConnectionClosed:  # noqa: PERF203
                continue

    def receive_message(self, data: bytes):
        """Receive message from visonic client to forward to flow manager."""
        _LOGGER.info("".rjust(60, "-"), extra=MsgLogLevel.L4)
        _LOGGER.debug(
            "Received Data: %s %s - %s",
            self.name,
            self.client_id,
            data,
            exc_info=MsgLogLevel.L4,
        )

        if self.cb_received_data:
            self.cb_received_data(self.name, self.client_id, data)

    def is_hex(self, s):
        """Return if value is hex."""
        try:
            bytes.fromhex(s)
        except ValueError:
            return False
        return True

    async def websocket_receive_message(self, msg: dict | str):
        """Receive message from websocket."""
        result = None
        send_status = False
        if request := msg.get("request"):
            if request == "status":
                result = await self.visonic_client.get_panel_status(
                    refresh_key_data=True
                )
            elif self.visonic_client.is_init:
                if request in ["turn_on", "turn_off"]:
                    dev_item = msg.get("type")
                    if dev_item == "bypass":
                        if zone := int(msg.get("zone", 0)):
                            response = await self.visonic_client.set_bypass(
                                zone, request == "turn_on"
                            )
                            if response:
                                msg["result"] = "success"
                                result = msg
                                send_status = True

                    if dev_item == "pgm":
                        if pgm_id := int(msg.get("pgm_id", 0)):
                            response = await self.visonic_client.set_pgm(
                                pgm_id, request == "turn_on"
                            )
                            if response:
                                msg["result"] = "success"
                                result = msg
                                send_status = False

                elif request == "command":
                    cmd = str(msg.get("id"))
                    if (
                        cmd is not None
                        and self.is_hex(cmd)
                        and cmd
                        not in [
                            "06",
                            "0f",
                            "17",
                            "35",
                            "42",
                            "51",
                            "6a",
                        ]
                    ):
                        cmd_name = get_lookup_value(B0CommandName, cmd)
                        response = await self.visonic_client.get_status(
                            cmd, refresh=True
                        )
                        result = {
                            "command": cmd,
                            "name": cmd_name,
                            "result": response,
                        }
                    else:
                        result = {
                            "error": "invalid request",
                            "message": "Either command not supplied or an invalid command provided",
                        }
                elif request == "setting":
                    setting = int(msg.get("id"))
                    if setting is not None and setting not in [83, 413]:
                        setting_name = get_lookup_value(Command35Settings, setting)
                        response = await self.visonic_client.get_setting(
                            setting, refresh=True
                        )
                        result = {
                            "setting": setting,
                            "name": setting_name,
                            "result": response,
                        }
                    else:
                        result = {
                            "error": "invalid request",
                            "message": "Either setting not supplied or an invalid setting provided",
                        }

                elif request == "all_commands":
                    known_only = msg.get("known_only", True)
                    result = await self.visonic_client.download_all_statuses(
                        known_only=known_only
                    )

                elif request == "all_settings":
                    known_only = msg.get("known_only", True)
                    result = await self.visonic_client.download_all_settings(
                        known_only=known_only
                    )

                elif request == "send_raw_command":
                    cmd = msg.get("cmd")
                    if cmd:
                        result = await self.visonic_client.send_raw_command(cmd)
                    else:
                        result = {
                            "error": "invalid request",
                            "message": "No command supplied",
                        }

                elif request == "arm":
                    state = msg.get("state")
                    partition = int(msg.get("partition", 7))
                    if state is not None:
                        response = await self.visonic_client.arming(
                            partition, state, msg.get("code")
                        )
                        if response:
                            result = {"request": "arm", "result": "success"}
                        else:
                            result = {"request": "arm", "result": "failed"}
                else:
                    result = json.dumps(
                        {
                            "error": "invalid request",
                            "message": f"{request} is not a valid request",
                        }
                    )
            else:
                result = json.dumps(
                    {
                        "error": "unable to service request",
                        "message": "server not initialised",
                    }
                )

            return result, send_status

    async def send_status(self, event: Event):
        """Send status message."""
        refresh_key_data = True

        if event.event_data:
            refresh_key_data = event.event_data.get("refresh", True)

        status = await self.visonic_client.get_panel_status(
            refresh_key_data=refresh_key_data
        )
        await self.broadcast(status)

    async def send_message(self, queued_message: QueuedMessage):
        """Send message to Visonic client."""
        self.send_queue.put_nowait(queued_message.message.data)
        _LOGGER.info(
            "%s->%s %s - %s %s %s",
            queued_message.source,
            self.name,
            self.client_id,
            f"{queued_message.message.msg_id:0>4}",
            queued_message.message.msg_type,
            queued_message.message.data.hex(" "),
            extra=MsgLogLevel.L3
            if queued_message.message.msg_type == VIS_ACK
            else MsgLogLevel.L2,
        )

    async def _send_queue_processor(self):
        """Process send queue."""
        while True:
            data: bytes = await self.send_queue.get()
            await self.visonic_client.receive_message(data)


class QID:
    """Hold queue id."""

    id_iter = itertools.count()

    @staticmethod
    def get_next():
        """Get next queue_id."""
        return next(QID.id_iter)


@dataclass
class CMStatus:
    """Hold status from e0 message."""

    alarm_connections: int = 0
    visonic_connections: int = 0
    monitor_connections: int = 0
    proxy_mode: bool = False
    stealth_mode: bool = False
    download_mode: bool = False

    @property
    def disconnected_mode(self):
        """Return if disconnected mode."""
        return self.visonic_connections == 0

    @property
    def alarm_connected(self):
        """Return if alarm connected."""
        return self.alarm_connections > 0


class VisonicClient:
    """Class to emulate a Visonic client to manage data and messages."""

    def __init__(
        self,
        proxy: Proxy,
        cb_send_message: Callable,
        cb_send_websocket_message: Callable,
    ):
        """Initialise."""
        self.proxy = proxy
        self.cb_send_message = cb_send_message
        self.cb_send_ws_message = cb_send_websocket_message

        self.cm_status = CMStatus()

        self.datastore = DataStore()

        self.send_lock = asyncio.Lock()
        self.rts = asyncio.Event()
        self.download_mode = asyncio.Event()
        self.stealth_mode = asyncio.Event()
        self.send_queue = asyncio.PriorityQueue()
        self.waiting_for: list[str] = []
        self.last_sent_message: bytes

        self.message_builder = MessageBuilder(self.proxy)
        self.message_decoder = B0Decoder()

        self.is_init: bool = False
        self.request_in_progress: bool = False

        self.send_processor_task = self.proxy.loop.create_task(
            self.send_queue_processor(), name="Visonic Client Send Queue Processor"
        )

        self.last_received: dt.datetime = dt.datetime.now()

        self.init_task = self.proxy.loop.create_task(
            self.initialise_data(), name="Init Waiter"
        )

    def stop(self):
        """Stop queue."""
        if self.send_processor_task and not self.send_processor_task.done():
            self.send_processor_task.cancel()

        if self.init_task and not self.init_task.done():
            self.init_task.cancel()

    async def initialise_data(self):
        """Init client data.

        Waits for alarm to connect and a period of message quiet before running.
        Should have run within 10s of Alarem connecting.

        Meant to be run as a task.
        """
        while True:
            if (
                self.cm_status.alarm_connections > 0
                and not self.cm_status.download_mode
                and not self.is_init
                and not self.request_in_progress
                and (self.is_quiet or self.cm_status.disconnected_mode)
            ):
                start = dt.datetime.now()
                _LOGGER.info("Starting Visonic Client Initialisation")
                self.request_in_progress = True
                await self.send_message_and_wait(VPCommand("stealth", True))
                await self.download_statuses(INIT_STATUSES)
                await self.download_settings(INIT_SETTINGS)

                await self.wait_for_empty_queue()
                await self.download_eprom_settings(list(EPROMSetting))
                await self.send_message_and_wait(VPCommand("stealth", False))
                self.request_in_progress = False
                self.is_init = True
                _LOGGER.info(
                    "Completed Visonic Client Initialisation in %ss",
                    (dt.datetime.now() - start).total_seconds(),
                )
                await self.schedule_status_update(1, False)
                break

            await asyncio.sleep(1)

    @property
    def is_quiet(self) -> bool:
        """Return if more than 5 secs since last message."""
        return (dt.datetime.now() - self.last_received).total_seconds() > 3

    def register_received_message(self, cmd: str, setting: int | None = None):
        """Register received message and remove from wait list."""
        try:
            if setting:
                self.waiting_for.remove(f"{cmd}_{setting}")
            else:
                # If command in invalid list, remove as has been successfully received now
                if self.proxy.invalid_commands.get(cmd):
                    self.proxy.invalid_commands[cmd] = 0

                self.waiting_for.remove(cmd)
        except ValueError:
            pass

    async def receive_message(self, data: bytes):
        """Process received message."""
        self.last_received = dt.datetime.now()
        # Requires ACK
        if data.hex(" ") in [ManagedMessages.ACK, ManagedMessages.PL_ACK]:
            self.register_received_message(ACK)
        else:
            self.cb_send_message(bytes.fromhex(ManagedMessages.PL_ACK))

            message_class = data[1:2].hex()
            if message_class == MessageClass.B0:
                try:
                    dec = self.message_decoder.decode(data)

                    if dec.cmd == B0CommandName.INVALID_COMMAND:
                        # If waiting multiple - do not know which is invalid.
                        # Therefore only register invalid if sure which is invalid
                        # ie list only has 1 entry
                        if len(self.waiting_for) == 1:
                            self.registered_invalid_command(self.waiting_for[0])

                        # clear wiating for.
                        self.waiting_for = []

                    else:
                        self.proxy.loop.create_task(
                            self.process_message(message_class, dec)
                        )
                except Exception as ex:  # noqa: BLE001
                    _LOGGER.error(ex)

            elif message_class == MessageClass.E0:
                # Process E0 message from CM.
                # 0a e0 <alarm connections> <visonic connections> <monitor connections> <stealth mode> <download mode> <crc> 0d

                self.register_received_message(message_class)
                stealth = data[6] == 1
                download = data[7] == 1

                cm_status = CMStatus(
                    alarm_connections=data[2],
                    visonic_connections=data[3],
                    monitor_connections=data[4],
                    proxy_mode=data[5] == 1,
                    stealth_mode=stealth,
                    download_mode=download,
                )

                _LOGGER.debug("STATUS: %s", cm_status)
                # Set stealth mode event for anything waiting on it
                if stealth:
                    self.stealth_mode.set()
                elif self.stealth_mode.is_set():
                    self.stealth_mode.clear()

                self.proxy.loop.create_task(
                    self.process_message(message_class, cm_status)
                )

            else:
                # Process std message and store data.
                dec = STDMessageDecoder().decode(data)
                self.register_received_message(dec.cmd)
                self.proxy.loop.create_task(self.process_message(MessageClass.STD, dec))

    def registered_invalid_command(self, command: str):
        """Register a command as invalid after receiving a 06 reponse to a B0 message."""
        if not self.proxy.invalid_commands.get(command):
            self.proxy.invalid_commands[command] = 1
        else:
            self.proxy.invalid_commands[command] = (
                self.proxy.invalid_commands[command] + 1
            )

    def is_invalid_command(self, command: str) -> bool:
        """If command has been registered invalid due to 06 reponse."""
        if count := self.proxy.invalid_commands.get(command):
            if count >= self.proxy.config.INVALID_MESSAGE_THRESHOLD:
                return True
        return False

    async def process_message(
        self, message_class: str, dec: B0Message | STDMessage | CMStatus
    ):
        """Process received message from socket client."""
        data_changed = False
        if message_class == MessageClass.STD and dec.cmd == "3f":
            self.datastore.store_eprom(dec.start, dec.data)
            self.register_received_message(dec.cmd)
        elif message_class == MessageClass.B0:
            if dec.cmd in [B0CommandName.SETTINGS_35, B0CommandName.SETTINGS_42]:
                data_changed = self.datastore.store(
                    SETTINGS,
                    dec.msg_type,
                    dec.cmd,
                    dec.setting,
                    dec.page,
                    dec.data,
                    dec.raw_data,
                )
                if dec.msg_type == 3 and dec.page in (0, 255):
                    self.register_received_message(f"{dec.cmd}_{dec.setting}")
            elif dec.cmd not in [B0CommandName.INVALID_COMMAND]:
                data_changed = self.datastore.store(
                    STATUS,
                    dec.msg_type,
                    dec.cmd,
                    dec.setting,
                    dec.page,
                    dec.data,
                    dec.raw_data,
                )
                if dec.msg_type == 3 and dec.page in (0, 255):
                    self.register_received_message(dec.cmd)

            if dec.msg_type == MessageType.RESPONSE:
                if dec.cmd in [B0CommandName.SETTINGS_35, B0CommandName.SETTINGS_42]:
                    setting_name = get_lookup_value(Command35Settings, dec.setting)
                    _LOGGER.info(
                        "SETTING: %s: %s",
                        f"{setting_name} ({dec.setting})",
                        self.datastore.get_setting(
                            f"{dec.setting}_{setting_name}",
                            dec.cmd == B0CommandName.SETTINGS_42,
                        ),
                        extra=MsgLogLevel.L4,
                    )
                else:
                    command_name = get_lookup_value(B0CommandName, dec.cmd)
                    _LOGGER.info(
                        "STATUS: %s: %s",
                        f"{command_name} ({dec.cmd})",
                        self.datastore.get_status(f"{dec.cmd}_{command_name}"),
                        extra=MsgLogLevel.L4,
                    )

            # Response to a 51 message
            if dec.cmd in [B0CommandName.ASK_ME, B0CommandName.ASK_ME2] and dec.data:
                await asyncio.sleep(0.2)
                for cmd in dec.data:
                    msg = self.message_builder.message_preprocessor(
                        bytes.fromhex(f"{MessageClass.B0} {cmd}")
                    )
                    self.send_message_no_wait(msg.data, [cmd])

        elif message_class == MessageClass.E0:
            # Connection change message.
            # Send status update if alarm changes

            prev_alarm_connections = self.cm_status.alarm_connections
            self.cm_status = dec
            if self.cm_status.alarm_connections != prev_alarm_connections:
                result = await self.get_panel_status(refresh_key_data=False)
                await self.cb_send_ws_message(result)

        # if data has changed, send status message to websocket clients.
        if (
            (
                message_class == MessageClass.B0
                and dec.msg_type != MessageType.PAGED_RESPONSE
                or message_class != MessageClass.B0
            )
            and data_changed
            and self.is_init
            and not self.request_in_progress
            and (dec.setting in INIT_SETTINGS or dec.cmd in INIT_STATUSES)
        ):
            result = await self.get_panel_status(refresh_key_data=False)
            await self.cb_send_ws_message(result)

    async def wait_for_responses(self) -> bool:
        """Wait for responses before setting rts.

        If timeout, then resend request.
        """
        timeout = 5
        retries = 3

        i = 0
        retry = 0
        success = True
        self.rts.clear()
        while len(self.waiting_for) > 0:
            await asyncio.sleep(0.05)
            i += 1

            if i >= timeout * 20:
                i = 0
                _LOGGER.warning("TIMEOUT WAITING FOR: %s", self.waiting_for)
                # If only waiting for ACK, move on.
                if self.waiting_for == [ACK]:
                    self.waiting_for = []
                    continue
                if retry < retries:
                    _LOGGER.info("RESENDING: %s", self.last_sent_message.hex(" "))
                    self.cb_send_message(self.last_sent_message)
                    retry += 1
                else:
                    _LOGGER.error(
                        "NO RESPONSE RECEIVED: %s", self.last_sent_message.hex(" ")
                    )
                    success = False
                    self.waiting_for = []

        self.rts.set()
        return success

    async def wait_for_empty_queue(self):
        """Wait for empty queue."""
        while self.send_queue.qsize() > 0:
            await asyncio.sleep(0.1)

    def send_message_no_wait(
        self,
        data: bytes | VPCommand,
        wait_for: list[str] | None = None,
        priority: int = 10,
    ):
        """Add message to send queue."""
        if isinstance(data, bytes):
            _LOGGER.debug("SENDING: %s", data.hex(" "))
        self.send_queue.put_nowait((priority, QID().get_next(), data, wait_for))

    async def send_message_and_wait(
        self, data: bytes | VPCommand, wait_for: list[str] | None = None
    ):
        """Send message and wait for responses."""
        await self.send_lock.acquire()
        await self._send_message_and_wait(data, wait_for)
        self.send_lock.release()

    async def send_queue_processor(self):
        """Process receive queue."""
        while True:
            # Wait for rts
            await self.rts.wait()
            _, _, msg, wait_for = await self.send_queue.get()
            await self.send_lock.acquire()

            await self._send_message_and_wait(msg, wait_for)

            self.send_lock.release()

    async def _send_message_and_wait(
        self, msg: bytes | VPCommand, wait_for: list[str] | None = None
    ) -> bool:
        """Send a message and wait for response to be received."""
        send_msg = None
        if isinstance(msg, VPCommand):
            wait_for = []
            if msg.cmd == "download":
                if msg.state:
                    send_msg = bytes.fromhex(ManagedMessages.DOWNLOAD)
                    wait_for = [ACK, "3c"]
                else:
                    send_msg = bytes.fromhex(ManagedMessages.EXIT_DOWNLOAD_MODE)
                    wait_for = []  # ["02", "e0"]
            elif msg.cmd == "stealth":
                if msg.state:
                    send_msg = bytes.fromhex(ManagedMessages.ENABLE_STEALTH)
                    wait_for = [ACK, "e0"]
                else:
                    send_msg = bytes.fromhex(ManagedMessages.DISABLE_STEALTH)
                    wait_for = [ACK, "e0"]
        else:
            send_msg = msg

        _LOGGER.info("SENDING: %s", send_msg.hex(" "), extra=MsgLogLevel.L5)
        self.cb_send_message(send_msg)
        self.last_sent_message = send_msg
        if wait_for:
            self.waiting_for.extend(wait_for)
            _LOGGER.info("WAITING FOR: %s", self.waiting_for, extra=MsgLogLevel.L5)
        return await self.wait_for_responses()

    async def can_download(self):
        """Return if can download from panel.

        Panel needs to be disarmed.
        """
        return not await self.is_armed()

    async def is_armed(self, refresh: bool = True):
        """Return if can download from panel.

        Panel needs to be disarmed.
        """
        is_armed = False
        status = await self.get_status("24", refresh=refresh)

        for partition in status.get("states").values():
            if partition.get("State") not in ["Disarmed", "Downloading"]:
                is_armed = True

        return is_armed

    async def send_raw_command(self, command: str):
        """Get A5 message by sending an A2."""
        msg = bytes.fromhex(command)
        await self.send_message_and_wait(msg)

    async def get_status(
        self, status_id: str, key: str | None = None, refresh: bool = False
    ) -> dict | list | str:
        """Get status value from datastore.  Refresh first if requested."""
        status_name = f"{status_id}_{get_lookup_value(B0CommandName, status_id)}"

        if refresh or self.datastore.get_status(status_name) is None:
            if not self.is_invalid_command(status_id):
                msg = self.message_builder.message_preprocessor(
                    bytes.fromhex(f"b0 {status_id}")
                )
                await self.send_message_and_wait(msg.data, [ACK, str(status_id)])
            else:
                _LOGGER.debug(
                    "Command %s requested which has been marked as invalid for this panel",
                    status_id,
                    extra=MsgLogLevel.L2,
                )

        if key:
            return (
                self.datastore.get_status(status_name).get(key)
                if self.datastore.get_status(status_name)
                else None
            )
        return self.datastore.get_status(status_name)

    async def get_setting(
        self, setting: int, refresh: bool = False
    ) -> dict | list | str:
        """Get settings value from datastore.  Refresh if requested or does not exist in store."""
        setting_name = f"{setting}_{get_lookup_value(Command35Settings, setting)}"
        if refresh or self.datastore.get_setting(setting_name) is None:
            setting_id = setting.to_bytes(2, byteorder="little")
            msg = self.message_builder.message_preprocessor(
                bytes.fromhex(f"b0 35 {setting_id.hex(" ")}")
            )
            await self.send_message_and_wait(msg.data, [ACK, f"35_{setting!s}"])

        return self.datastore.get_setting(setting_name)

    async def get_eprom_setting(
        self, setting: EPROMSetting, refresh: bool = False
    ) -> str | list[str]:
        """Get eprom value from datastore.  Refresh is requested or does not exist in store."""
        setting_info = EPROMSettingLookup.get(setting)
        if (
            refresh
            or self.datastore.get_eprom_setting(
                setting_info.position, setting_info.length
            )
            is None
        ) and await self.can_download():
            await self.send_message_and_wait(VPCommand("download", True))
            wait_for = ["3f"]
            msg = f"3e {int(setting_info.position).to_bytes(2, "little").hex(" ")} {setting_info.length:02x} 00 b0 00 00 00 00 00"
            await self.send_message_and_wait(bytes.fromhex(msg), wait_for)
            await self.send_message_and_wait(VPCommand("download", False))

        return self.datastore.get_eprom_setting(
            setting_info.position, setting_info.length
        )

    async def download_statuses(
        self, statuses: str | list[str], set_stealth: bool = False
    ):
        """Get status data."""
        if isinstance(statuses, str):
            statuses = [statuses]

        if set_stealth:
            await self.send_message_and_wait(VPCommand("stealth", True))

        per_request = 5
        for i in range(0, len(statuses), per_request):
            wait_for = [f"{status}" for status in statuses[i : i + per_request]]
            request_list = list(statuses[i : i + per_request])
            request = f"b0 17 {" ".join(request_list)}"
            msg = self.message_builder.message_preprocessor(bytes.fromhex(request))
            wait_for.append(ACK)
            await self.send_message_and_wait(msg.data, wait_for)

        if set_stealth:
            await self.wait_for_empty_queue()
            await self.send_message_and_wait(VPCommand("stealth", False))

    async def download_settings(
        self, settings: int | list[int], set_stealth: bool = False
    ):
        """Iterate settings and store in alarm data."""

        if isinstance(settings, int):
            settings = [settings]

        if set_stealth:
            await self.send_message_and_wait(VPCommand("stealth", True))

        settings_per_request = 6
        for i in range(0, len(settings), settings_per_request):
            wait_for = [
                f"35_{setting}" for setting in settings[i : i + settings_per_request]
            ]
            request_list = [
                i.to_bytes(2, byteorder="little").hex(" ")
                for i in settings[i : i + settings_per_request]
            ]
            request = f"b0 35 {" ".join(request_list)}"
            msg = self.message_builder.message_preprocessor(bytes.fromhex(request))
            wait_for.append(ACK)
            await self.send_message_and_wait(msg.data, wait_for)

        if set_stealth:
            await self.wait_for_empty_queue()
            await self.send_message_and_wait(VPCommand("stealth", False))

    async def download_eprom_settings(
        self, settings: list[EPROMSetting], force_refresh: bool = False
    ):
        """Check if eprom settings are in datastore and loads as a batch if not.

        If force refresh is true then loads the full list.
        """
        load_list: list[EPROMSetting] = []
        for setting in settings:
            setting_info = EPROMSettingLookup.get(setting)
            if (
                force_refresh
                or self.datastore.get_eprom_setting(
                    setting_info.position, setting_info.length
                )
                is None
            ):
                load_list.append(setting)

        if load_list and await self.can_download():
            await self.send_message_and_wait(VPCommand("download", True))
            eprom_settings = [setting.value for setting in load_list]
            for eprom_setting in eprom_settings:
                wait_for = ["3f"]
                eprom_setting_def = EPROMSettingLookup[eprom_setting]
                msg = f"3e {int(eprom_setting_def.position).to_bytes(2, "little").hex(" ")} {eprom_setting_def.length:02x} 00 b0 00 00 00 00 00"
                await self.send_message_and_wait(bytes.fromhex(msg), wait_for)
            await self.send_message_and_wait(VPCommand("download", False))

    async def download_all_statuses(self, known_only: bool = True):
        """Request all known statuses."""
        ignore_list = ["06", "0f", "17", "35", "39", "42", "51", "6a"]
        statuses = [
            status.value for status in B0CommandName if status.value not in ignore_list
        ]
        await self.download_statuses(statuses, set_stealth=True)

        return self.datastore.get_all_statuses()

    async def download_all_settings(self, known_only: bool = True):
        """Count to 441 and request all settings."""
        ignore_list = [83, 413]

        if known_only:  # noqa: SIM108
            settings = [
                setting.value
                for setting in Command35Settings
                if setting.value not in ignore_list
            ]
        else:
            settings = [setting for setting in range(441) if setting not in ignore_list]

        await self.download_settings(settings, set_stealth=True)

        return self.datastore.get_all_settings()

    async def download_all_eprom_settings(self):
        """Download all known eprom settings."""
        if await self.can_download():
            wait_for = ["3f"]
            start = dt.datetime.now()
            await self.send_message_and_wait(VPCommand("download", True))
            eprom_settings = [setting.value for setting in EPROMSetting]
            for eprom_setting in eprom_settings:
                eprom_setting_def = EPROMSettingLookup[eprom_setting]
                msg = f"3e {int(eprom_setting_def.position).to_bytes(2, "little").hex(" ")} {eprom_setting_def.length:02x} 00 b0 00 00 00 00 00"
                await self.send_message_and_wait(bytes.fromhex(msg), wait_for)
            await self.send_message_and_wait(VPCommand("download", False))

            taken = (dt.datetime.now() - start).total_seconds()
            return {"time_taken": taken, "eprom": self.datastore.get_eprom()}

        return "Panel is armed.  Cannot download eprom."

    async def schedule_status_update(
        self, time_period: int, refresh_key_data: bool = True
    ):
        """Schedule a status update in time_period seconds."""
        self.proxy.events.fire_event_later(
            time_period,
            Event(
                ConnectionName.ALARM_MONITOR,
                SEND_WEBSOCKET_STATUS_EVENT,
                event_data={"refresh": refresh_key_data},
            ),
        )

    async def get_panel_status(self, refresh_key_data: bool = False):
        """Get current panel status."""
        start = dt.datetime.now()

        output = {
            "version": __VERSION__,
            "time_taken": 0,
            "datetime": 0,
            "connections": {
                "alarm": self.cm_status.alarm_connections,
                "visonic": self.cm_status.visonic_connections,
            },
            "modes": {
                "proxy": self.cm_status.proxy_mode,
                "stealth": self.cm_status.stealth_mode,
                "download": self.cm_status.download_mode,
            },
        }

        if self.is_init:
            self.request_in_progress = True
            result = await self.get_panel_info(
                json_encode=False, refresh_key_data=refresh_key_data
            )
            self.request_in_progress = False
            output.update(result)
        end = dt.datetime.now()

        output["time_taken"] = round((end - start).total_seconds(), 3)
        output["datetime"] = end.strftime("%Y-%m-%d %H:%M:%S")

        try:
            return json.dumps(output, indent=2)
        except TypeError as ex:
            _LOGGER.error(
                "Error processing panel status.  Data: %s\nError: %s", output, ex
            )
            raise TypeError from ex

    async def get_panel_info(
        self, json_encode: bool = True, refresh_key_data: bool = False
    ):
        """Get current panel info."""
        try:
            panel_id = await self.get_setting(Command35Settings.PANEL_SERIAL_NO)
            panel_status = await self.get_status(
                B0CommandName.PANEL_STATUS, refresh=refresh_key_data
            )
            download_code = await self.get_setting(Command35Settings.DOWNLOAD_CODE)
            eprom = await self.get_setting(Command35Settings.PANEL_EPROM_VERSION)
            panel_capabilities = await self.get_setting(Command35Settings.CAPABILITIES)
            sw_version = await self.get_setting(
                Command35Settings.PANEL_SOFTWARE_VERSION
            )
            partitions_enabled = (
                await self.get_setting(
                    Command35Settings.PARTITIONS_ENABLED, refresh=refresh_key_data
                )
            ) == 1
            panel_hw_version = await self.get_setting(
                Command35Settings.PANEL_HARDWARE_VERSION
            )
            plink_sw_version = await self.get_setting(
                Command35Settings.POWERLINK_SW_VERSION
            )
            troubles = await self.get_status(
                B0CommandName.TROUBLES, refresh=refresh_key_data
            )
            master_user_code = (await self.get_setting(Command35Settings.USER_CODES))[0]

            result = {
                "panel": {
                    "id": panel_id,
                    "hw_version": panel_hw_version,
                    "sw_version": sw_version,
                    "eprom_version": eprom,
                    "plink_sw_version": plink_sw_version,
                    "capabilities": panel_capabilities,
                    "partitions_enabled": partitions_enabled,
                    "partitions": panel_status.get("partitions"),
                    "active_partitions": [
                        x
                        for x in panel_status["states"]
                        if panel_status["states"][x].get("Partition Active", False)
                    ],
                    "download_code": download_code,
                    "master_user_code": master_user_code,
                    "datetime": panel_status.get("datetime"),
                    "troubles": troubles,
                },
                "partitions": await self.get_partition_info(refresh_key_data),
                "devices": await self.get_device_info(
                    refresh_key_data=refresh_key_data
                ),
            }

            if json_encode:
                result = json.dumps(result, indent=2)

            return result  # noqa: TRY300

        except Exception as ex:  # noqa: BLE001
            _LOGGER.error("Error getting panel info. %s", ex)
            raise Exception from ex

    async def get_partition_info(self, refresh_key_data: bool = False):
        """Get partition info."""
        triggered_partitions = [0, 0, 0]
        partition_status = await self.get_status(
            B0CommandName.PANEL_STATUS, "states", refresh=refresh_key_data
        )
        device_partitions = await self.get_status(
            B0CommandName.ASSIGNED_PARTITION, "zones"
        )
        device_triggers = await self.get_status(B0CommandName.TRIGGERED_ZONE, "zones")

        # Get if partition has triggered zone device
        for idx, dev in enumerate(device_triggers):
            if dev == 1:
                dev_part = device_partitions[idx]
                if ibit(dev_part, 7) == 1:
                    triggered_partitions[0] = 1
                if ibit(dev_part, 6) == 1:
                    triggered_partitions[1] = 1
                if ibit(dev_part, 5) == 1:
                    triggered_partitions[2] = 1

        # update partition status
        for i in range(1, 4):
            if partition_status.get(i):
                partition_status[i]["Triggered"] = triggered_partitions[i - 1] == 1
                if triggered_partitions[i - 1] == 1 and partition_status[i][
                    "State"
                ] not in ["Disarmed", "EntryDelay"]:
                    partition_status[i]["State"] = "Triggered"

        return partition_status

    async def get_device_info(self, refresh_key_data: bool = False):
        """Get device info."""
        devices = {}
        enrolled_devices = await self.get_status(B0CommandName.DEVICE_INFO)
        zone_names = await self.get_setting(Command35Settings.ZONE_NAMES)
        pgm_status = await self.get_status(B0CommandName.WIRED_DEVICES_STATUS, "pgm")
        tamper_actives = await self.get_status(B0CommandName.TAMPER_ACTIVES)
        tamper_alerts = await self.get_status(B0CommandName.TAMPER_ALERTS)

        for dev_type, dev in sorted(enrolled_devices.items()):
            if dev_type == "zones":
                devices["zones"] = await self.get_zone_info(refresh_key_data)
            else:
                if not devices.get(dev_type):
                    devices[dev_type] = {}

                for d, i in sorted(dev.items()):
                    if i.get("assigned_name_id", 255) != 255:
                        i["name"] = zone_names[i.get("assigned_name_id")]
                    else:
                        i["name"] = f"{dev_type.title()} {d+1}"

                        if SENSOR_TYPES.get(dev_type):
                            try:
                                if device_type_info := SENSOR_TYPES[dev_type].get(
                                    i.get("sub_type")
                                ):
                                    i["device_type"] = device_type_info.func.name
                                    i["device_model"] = device_type_info.name
                                    i["active_tamper"] = (
                                        tamper_actives[dev_type][d] == 1
                                    )
                                    i["tamper_alert"] = tamper_alerts[dev_type][d] == 1
                                else:
                                    _LOGGER.warning(
                                        "Unrecognised device: %s - %s",
                                        dev_type,
                                        i.get("sub_type"),
                                    )
                                    i["device_type"] = dev_type.title()
                                    i["device_model"] = (
                                        f"{dev_type.title()}-{i["device_type_id"]}"
                                    )
                            except KeyError:
                                _LOGGER.error(
                                    "Error processing device: %s - %s",
                                    dev_type,
                                    i.get("sub_type"),
                                )
                                i = {}

                    if dev_type == "pgm":
                        i["on"] = pgm_status[d] == 1
                        i["device_model"] = dev_type.title()

                    devices[dev_type][d + 1] = i

        return devices

    async def get_zone_info(self, refresh_key_data: bool = False):
        """Show sensor info."""
        requested_delayed_status = False
        zones = {}
        panel_status = await self.get_status(B0CommandName.PANEL_STATUS)
        enrolled_zones = await self.get_status(B0CommandName.DEVICE_INFO, "zones")

        zones_name_ids = await self.get_status(B0CommandName.ASSIGNED_NAMES, "zones")
        zone_device_types = await self.get_status(B0CommandName.DEVICE_TYPES, "zones")
        zone_names = await self.get_setting(Command35Settings.ZONE_NAMES)
        zone_chimes = await self.get_setting(Command35Settings.ZONE_CHIME)
        zones_types = await self.get_status(B0CommandName.ASSIGNED_ZONE_TYPES, "zones")
        zones_bypasses = await self.get_status(
            B0CommandName.BYPASSES, "zones", refresh=refresh_key_data
        )
        zones_temps = await self.get_status(B0CommandName.ZONE_TEMPS, "zones")
        zones_brightnesses = await self.get_status(
            B0CommandName.ZONE_BRIGHTNESS, "zones"
        )
        zones_last_events = await self.get_status(
            B0CommandName.ZONE_LAST_EVENT, "zones", refresh=refresh_key_data
        )
        zones_trips = await self.get_status(B0CommandName.TRIGGERED_ZONE, "zones")
        device_ids = await self.get_status(B0CommandName.DEVICE_INFO, "zones")
        panel_hw_version = await self.get_setting(
            Command35Settings.PANEL_HARDWARE_VERSION
        )

        # Zone alarm leds
        if panel_hw_version == "PowerMaster-10":
            zl_data = await self.get_eprom_setting(EPROMSetting.ALARM_LED_PM10)
        elif panel_hw_version == "PowerMaster-30":
            zl_data = await self.get_eprom_setting(EPROMSetting.ALARM_LED_PM30)
        else:
            zl_data = None
        zones_alarm_leds = zl_data.split(" ") if zl_data else None

        # zone disarm activity
        zda_data = await self.get_eprom_setting(EPROMSetting.DISARM_ACTIVITY)
        zones_disarm_activity = (
            chunk_bytearray(bytes.fromhex(zda_data), 2) if zda_data else None
        )

        tamper_actives = await self.get_status(B0CommandName.TAMPER_ACTIVES, "zones")
        tamper_alerts = await self.get_status(B0CommandName.TAMPER_ALERTS, "zones")

        for idx, info in sorted(enrolled_zones.items()):
            zone_id = idx + 1
            zones[zone_id] = {}

            zones[zone_id]["name"] = zone_names[zones_name_ids[idx]]
            zones[zone_id]["type"] = zones_types[idx]
            if zone_device_info := SENSOR_TYPES["zones"].get(zone_device_types[idx]):
                zones[zone_id]["device_type"] = zone_device_info.func.name
                zones[zone_id]["device_model"] = zone_device_info.name
            else:
                zones[zone_id]["device_type"] = "Unknown"
                zones[zone_id]["device_model"] = f"Unknown-{zone_device_types[idx]}"
            zones[zone_id]["device_id"] = device_ids[idx].get("device_id", "Unknown")
            zones[zone_id]["partitions"] = info.get("partitions")
            zones[zone_id]["chime"] = zone_chimes[idx] == 1
            zones[zone_id]["bypass"] = zones_bypasses[idx] == 1
            zones[zone_id]["alarm_led"] = (
                zones_alarm_leds[idx] == "01" if zones_alarm_leds else "Unknown"
            )
            zones[zone_id]["disarm_active"] = (
                zones_disarm_activity[idx] != b"\xff\xff"
                if zones_disarm_activity
                else "Unknown"
            )
            zones[zone_id]["disarm_active_delay_mins"] = (
                int(b2i(zones_disarm_activity[idx]) / 60)
                if zones_disarm_activity and zones_disarm_activity[idx] != b"\xff\xff"
                else -1
            )
            zones[zone_id]["active_tamper"] = tamper_actives[idx] == 1
            zones[zone_id]["tamper_alert"] = tamper_alerts[idx] == 1
            zones[zone_id]["tripped"] = zones_trips[idx] == 1
            zones[zone_id]["last_event_datetime"] = zones_last_events[idx].get(
                "datetime"
            )
            zones[zone_id]["last_event"] = zones_last_events[idx].get("code")

            if zone_device_info and zone_device_info.func in [
                SensorType.MOTION,
                SensorType.CAMERA,
            ]:
                motion_detected = (
                    zones[zone_id]["last_event"] == "motion"
                    and str_datetime_diff(
                        panel_status.get("datetime"),
                        zones_last_events[idx].get("datetime"),
                    )
                    <= 10
                )
                zones[zone_id]["motion_detected"] = motion_detected
                if motion_detected and not requested_delayed_status:
                    requested_delayed_status = True
                    await self.schedule_status_update(15)

            if zones_temps and zones_temps[idx] != 255:
                zones[zone_id]["temperature"] = zones_temps[idx]
            if zones_brightnesses and zones_brightnesses[idx] != "na":
                zones[zone_id]["brightness"] = zones_brightnesses[idx]

        return zones

    async def arming(
        self, partitions: int | list[int], arm_type: int, user_code: str | None = None
    ):
        """Arm/disarm panel patitions."""
        _LOGGER.info("ARM: %s %s", partitions, arm_type, extra=MsgLogLevel.L5)
        if not user_code and (
            user_codes := await self.get_setting(Command35Settings.USER_CODES)
        ):
            user_code = user_codes[0]

        if user_code:
            partition = 0
            if isinstance(partitions, list):
                for p in partitions:
                    if p == "1":
                        partition = partition + 1
                    elif p == "2":
                        partition = partition + 2
                    elif p == "3":
                        partition = partition + 4
            else:
                partition = int(partitions)

            if CMStatus.download_mode:
                msg = self.message_builder.message_preprocessor(
                    bytes.fromhex(ManagedMessages.EXIT_DOWNLOAD_MODE)
                )
                self.send_message_no_wait(msg.data, [])

            arm_msg = f"a1 00 00 {arm_type:02d} {user_code[0:2]} {user_code[2:4]} {partition:02d} 00 00 00 00 43"
            msg = self.message_builder.message_preprocessor(bytes.fromhex(arm_msg))
            self.send_message_no_wait(msg.data, [])
            return True
        return False

    async def set_bypass(self, zones: int | list[int], enable: bool) -> str:
        """Set bypasses."""

        self.request_in_progress = True
        success = False
        zone_data = bits_to_le_bytes(zones, 64)
        download_code = await self.get_setting(Command35Settings.DOWNLOAD_CODE)

        data = bytes.fromhex(f"00 ff 01 03 08 {zone_data.hex(" ")}")
        message = self.message_builder.build_b0_add_remove_message(
            MessageType.ADD if enable else MessageType.REMOVE, "19", download_code, data
        )

        if message:
            await self.send_message_and_wait(message.data, [ACK])
            msg = self.message_builder.message_preprocessor(
                bytes.fromhex("b0 17 19 24")
            )
            await self.send_message_and_wait(msg.data, ["19", "24"])
            success = True

        self.request_in_progress = False
        return success

    async def set_pgm(
        self, pgm_ids: int | list[int], enable: bool, duration: int | None = None
    ):
        """Set a PGM output.  Can be timed with duration in seconds."""
        # 0d b0 00 27 09 aa aa 11 ff 08 0b 02 01 00 43 5f 0a
        pgm_data = bits_to_le_bytes(pgm_ids, 16)
        download_code = (
            (await self.get_setting(Command35Settings.USER_CODES)[0])
            if duration
            else (await self.get_setting(Command35Settings.DOWNLOAD_CODE))
        )

        if duration is not None:
            # Use a 7a message to enable for duration
            data = bytes.fromhex(
                f"01 ff 20 0b 04 {pgm_data.hex(" ")} {(duration.to_bytes(2, "little")).hex(" ")}"
            )
            message = self.message_builder.build_b0_add_remove_message(
                MessageType.ADD, "7a", download_code, data
            )

        else:
            data = bytes.fromhex(
                f"{"01" if enable else "00"} ff 08 0b 02 {pgm_data.hex(" ")}"
            )
            message = self.message_builder.build_b0_add_remove_message(
                MessageType.ADD, "27", download_code, data
            )

        if message:
            await self.send_message_and_wait(message.data, [ACK])
            return True
