"""Websocket server."""

import asyncio
from collections.abc import Callable
import datetime as dt
import hmac
import http
import json
import logging
import os
import ssl
import traceback
from typing import Any

from websockets import ConnectionClosed
from websockets.asyncio.server import ServerConnection, serve
from websockets.http11 import Request

from ..const import LOGGER_NAME, VIS_ACK, ConnectionName, MsgLogLevel
from ..events import Event, EventType
from ..helpers.ssl import get_ssl_certs_path
from ..message import QueuedMessage
from ..proxy import Proxy
from ..transcoders.helpers import get_lookup_value
from ..transcoders.refs import B0CommandName, Command35Settings
from .visonic_client import (
    INIT_SETTINGS,
    INIT_STATUSES,
    QID,
    SEND_WEBSOCKET_STATUS_EVENT,
    CMStatus,
    VisonicClient,
)

__all__ = [
    "CMStatus",
    "INIT_SETTINGS",
    "INIT_STATUSES",
    "QID",
    "SEND_WEBSOCKET_STATUS_EVENT",
    "VisonicClient",
    "WebsocketServer",
]

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
        self.websockets: dict[str, ServerConnection] = {}

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

            _LOGGER.info(
                "Started Websocket server on port %s (%s, %s)",
                self.port,
                "SSL enabled" if self.proxy.config.WEBSOCKET_SSL else "SSL disabled",
                "AUTH token required"
                if self.proxy.config.WEBSOCKET_AUTH_KEY
                else "AUTH token not required",
            )

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
            self.proxy.events.subscribe(
                ConnectionName.ALARM_MONITOR,
                EventType.SUBSCRIBED_MESSAGE,
                self.send_subscribed_message,
            ),
            self.proxy.events.subscribe(
                ConnectionName.ALARM_MONITOR,
                EventType.NEW_CAMERA_IMAGE,
                self.send_image_message,
            ),
        ]

        self.server_stop = self.proxy.loop.create_future()

        if self.proxy.config.WEBSOCKET_SSL:
            base_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
            certs_path = get_ssl_certs_path(
                self.proxy.config.SSL_CERT_PATH,
                is_addon=self.proxy.is_addon,
                base_dir=base_dir,
            )
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_context.load_cert_chain(
                f"{certs_path}/cert.pem",
                f"{certs_path}/private.key",
            )
        else:
            ssl_context = None

        async with serve(
            self.client_handler,
            self.host,
            self.port,
            process_request=self.verify_authorisation,
            ssl=ssl_context,
        ):
            await self.server_stop

    def verify_authorisation(
        self, websocket: ServerConnection, request: Request
    ) -> bool:
        """Verify auth token is set in config."""
        if not self.proxy.config.WEBSOCKET_AUTH_KEY:
            return None

        if auth_header := request.headers.get("Authorization"):
            expected = f"Bearer {self.proxy.config.WEBSOCKET_AUTH_KEY}"
            if hmac.compare_digest(auth_header, expected):
                return None

        _LOGGER.warning(
            "Unauthorised websocket connection attempt from %s",
            websocket.remote_address[0],
        )
        return websocket.respond(
            http.HTTPStatus.UNAUTHORIZED, "Invalid or missing authorisation token\n"
        )

    async def shutdown(self):
        """Stop websocket server."""
        ## Unsubscribe to events.
        for unsub in self._unsubscribe_listeners:
            unsub()

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

    async def client_handler(self, websocket: ServerConnection):
        """Websocket handler."""

        client_ip = websocket.remote_address[0]
        _LOGGER.info(
            "Websocket client connected from %s",
            client_ip,
        )
        self.websockets[websocket.id] = websocket

        try:
            while True:
                try:
                    message = await websocket.recv()
                    msg = json.loads(message)
                    _LOGGER.info(
                        "Received websocket message: %s", msg, extra=MsgLogLevel.L5
                    )
                    response, send_status = await self.websocket_receive_message(
                        websocket.id, msg
                    )
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
                    _LOGGER.info(
                        "Websocket client disconnected from %s",
                        client_ip,
                    )
                    break
        finally:
            self.websockets.pop(websocket.id, None)
            self.visonic_client.subscribed_messages.pop(websocket.id, None)

    async def send_image_message(self, event: Event):
        """Send broadcast message with image info and raw image data."""
        if event.event_data:
            image_info = event.event_data.get("image_info")
            image_data: bytes = event.event_data.get("data")

            msg = {"new_image": {"image_info": image_info, "image": image_data.hex()}}
            await self.broadcast(json.dumps(msg))

    async def send_subscribed_message(self, event: Event):
        """Send subscribed message to websocket connections."""

        if event.event_data:
            if clients := event.event_data.get("client_ids"):
                if cmd := event.event_data.get("command"):
                    _LOGGER.info(
                        "Sending subscribed message - %s", cmd, extra=MsgLogLevel.L5
                    )
                    msg = {
                        "subscribed_message": {
                            "command": cmd,
                            "datetime": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "message": event.event_data.get("message"),
                            "data": event.event_data.get("data"),
                        }
                    }
                    await self.send_ws_message(clients, json.dumps(msg))

    async def send_ws_message(
        self, clients: str | list[str], message: str | dict[str, Any]
    ):
        """Send message over websocket(s)."""
        if isinstance(clients, str):
            clients = [clients]

        if isinstance(message, dict):
            message = json.dumps(message)

        for client in clients:
            if websocket := self.websockets.get(client):
                await websocket.send(message)

    async def broadcast(self, message):
        """Send message to all websocket clients."""
        for websocket in list(self.websockets.values()):
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
            extra=MsgLogLevel.L4,
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

    def add_subscription(self, client_id: str, commands: str | list[str]) -> list[str]:
        """Add to subscribed messages for websocket client."""
        if not isinstance(commands, list):
            commands = [commands]

        if subs := self.visonic_client.subscribed_messages.get(client_id) or []:
            subs.extend(commands)

            # Remove duplicates
            subs = list(set(subs))

            self.visonic_client.subscribed_messages[client_id] = subs
            return subs

        self.visonic_client.subscribed_messages[client_id] = commands
        return commands

    def remove_subscription(
        self, client_id: str, commands: str | list[str]
    ) -> list[str]:
        """Remove a subscription for a message for a websocket client."""
        if not isinstance(commands, list):
            commands = [commands]

        if subs := self.visonic_client.subscribed_messages.get(client_id) or []:
            for cmd in commands:
                if cmd == "all":
                    del self.visonic_client.subscribed_messages[client_id]
                    return []
                if cmd in subs:
                    subs.remove(cmd)

            self.visonic_client.subscribed_messages[client_id] = subs
            return subs
        return []

    async def websocket_receive_message(self, client_id: str, msg: dict | str):  # noqa: C901
        """Receive message from websocket."""
        result = None
        send_status = False
        if not isinstance(msg, dict) or not (request := msg.get("request")):
            return (
                {
                    "error": "invalid request",
                    "message": "Request must be a JSON object with a 'request' field",
                },
                False,
            )

        if request == "status":
            result = await self.visonic_client.get_panel_status(refresh_key_data=True)
        elif request == "subscribe":
            if cmds := msg.get("commands"):
                subs = self.add_subscription(client_id, cmds)
                result = {
                    "result": "success",
                    "subscriptions": subs,
                }
        elif request == "unsubscribe":
            if cmds := msg.get("commands"):
                subs = self.remove_subscription(client_id, cmds)
                result = {
                    "result": "success",
                    "subscriptions": subs,
                }

        elif self.visonic_client.is_init:
            if request in ["turn_on", "turn_off"]:
                dev_item = msg.get("type")
                if dev_item == "bypass":
                    try:
                        zone = int(msg.get("zone", 0))
                    except (TypeError, ValueError):
                        return (
                            {"error": "invalid request", "message": "Invalid zone"},
                            False,
                        )
                    if zone:
                        response = await self.visonic_client.set_bypass(
                            zone, request == "turn_on"
                        )
                        if response:
                            msg["result"] = "success"
                            result = msg
                            send_status = True

                if dev_item == "pgm":
                    try:
                        pgm_id = int(msg.get("pgm_id", 0))
                    except (TypeError, ValueError):
                        return (
                            {"error": "invalid request", "message": "Invalid pgm_id"},
                            False,
                        )
                    if pgm_id:
                        response = await self.visonic_client.set_pgm(
                            pgm_id, request == "turn_on"
                        )
                        if response:
                            msg["result"] = "success"
                            result = msg
                            send_status = False
            elif request == "siren":
                if action := msg.get("action"):
                    if (
                        user_code
                        := await self.visonic_client.get_master_user_code()
                    ):
                        if action == "sound":
                            await self.visonic_client.sound_siren(user_code)
                        elif action == "mute":
                            await self.visonic_client.mute_siren(user_code)

            elif request == "image":
                if zone := msg.get("zone"):
                    try:
                        zone_id = int(zone)
                    except (TypeError, ValueError):
                        return (
                            {"error": "invalid request", "message": "Invalid zone"},
                            False,
                        )
                    await self.visonic_client.request_image(zone_id)
                    result = {
                        "request": "image",
                        "result": "success",
                    }

            elif request == "command":
                cmd = str(msg.get("id")) if msg.get("id") is not None else None
                if (
                    cmd is not None
                    and self.is_hex(cmd)
                    and cmd
                    not in [
                        "06",
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
                raw_setting = msg.get("id")
                try:
                    setting = int(raw_setting) if raw_setting is not None else None
                except (TypeError, ValueError):
                    setting = None
                use_42 = msg.get("use_42", False)
                if setting is not None and setting not in [83, 413]:
                    setting_name = get_lookup_value(Command35Settings, setting)
                    response = await self.visonic_client.get_setting(
                        setting, refresh=True, use_42=use_42
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
                use_42 = msg.get("use_42", False)
                result = await self.visonic_client.download_all_settings(
                    known_only=known_only, use_42=use_42
                )

            elif request == "send_raw_command":
                cmd = msg.get("cmd")
                if cmd and isinstance(cmd, str) and self.is_hex(cmd):
                    result = await self.visonic_client.send_raw_command(cmd)
                else:
                    result = {
                        "error": "invalid request",
                        "message": "No valid hex command supplied",
                    }

            elif request == "arm":
                state = msg.get("state")
                try:
                    partition = int(msg.get("partition", 7))
                except (TypeError, ValueError):
                    return (
                        {"error": "invalid request", "message": "Invalid partition"},
                        False,
                    )
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
            try:
                await self.visonic_client.receive_message(data)
            except asyncio.CancelledError:
                raise
            except Exception as ex:  # noqa: BLE001
                _LOGGER.error(
                    "Error processing websocket receive queue item: %s\n%s",
                    ex,
                    traceback.format_exc(),
                )
            finally:
                self.send_queue.task_done()
