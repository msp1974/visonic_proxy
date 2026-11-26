"""Simple HTTP server to allow connection on port 8443.

Responds to POST reqest with simple response.
"""

import asyncio
import contextlib
import datetime as dt
import io
import json
import logging
from pathlib import Path
import re
import time

from PIL import Image
import requests
import urllib3

from ..const import LOGGER_NAME, ConnectionName, MsgLogLevel
from ..events import Event, EventType
from ..proxy import Proxy
from .httpserver.server import HttpServer, uri_pattern_mapping
from .httpserver.utils import HttpHeaders, HttpRequest, HttpResponse

urllib3.disable_warnings()

_LOGGER = logging.getLogger(LOGGER_NAME)


class Connect:
    """Class to hold request connect."""

    request_connect: bool = True


class MyHandler:
    """Webserver handler."""

    def __init__(self, proxy: Proxy, request_connect: bool):
        """Initialise."""
        self.proxy = proxy
        self.request_connect = request_connect

    def _sync_forward_request(self, request: HttpRequest) -> requests.Response:
        """Synchronously forward request (executed in worker thread)."""
        with requests.Session() as session:
            return session.post(
                f"https://{self.proxy.config.VISONIC_HOST}:{self.proxy.config.WEBSERVER_PORT}{request.path}",
                params=request.query_params,
                headers=request.headers,
                data=request.body,
                verify=False,
                timeout=2,
            )

    async def forward_request(self, request: HttpRequest) -> requests.Response:
        """Forward request without blocking the asyncio event loop."""
        try:
            return await asyncio.to_thread(self._sync_forward_request, request)
        except (TimeoutError, requests.exceptions.ReadTimeout, OSError) as ex:
            _LOGGER.warning(
                "HTTP connection timed out error sending to Visonic. %s", ex
            )
            return None

    @uri_pattern_mapping("(.*?)", "POST")
    async def default(self, request: HttpRequest):
        """Handle default post handler."""
        _LOGGER.info("WEB REQUEST: %s", request, extra=MsgLogLevel.L5)

        if request.path == "/scripts/update.php":
            if self.proxy.config.PROXY_MODE:
                if res := await self.forward_request(request):
                    has_connect_cmd = False
                    response: dict = {}
                    try:
                        response = res.json()
                        if cmds := response.get("cmds"):
                            for command in cmds:
                                if command.get("name") == "connect":
                                    has_connect_cmd = True
                                    # fire event
                                    _LOGGER.info(
                                        "Received web connection request",
                                        extra=MsgLogLevel.L1,
                                    )
                                    event = Event(
                                        ConnectionName.VISONIC,
                                        EventType.REQUEST_CONNECT,
                                    )
                                    self.proxy.events.fire_event(event)
                    except (requests.exceptions.JSONDecodeError, ValueError):
                        _LOGGER.info("cannot decode response")
                        response = {}

                    if Connect.request_connect:
                        resp_dict = {
                            "cmds": [
                                {
                                    "name": "connect",
                                    "params": {"port": self.proxy.config.MESSAGE_PORT},
                                }
                            ],
                            "ka_time": 10,
                            "version": 3,
                        }
                        resp = bytes(f"{json.dumps(resp_dict)}\n", "ascii")
                    elif has_connect_cmd and isinstance(response, dict):
                        # Alarm is already connected to proxy; strip 'connect' command so
                        # the panel does not open a duplicate TCP connection.
                        filtered_cmds = [
                            cmd
                            for cmd in response.get("cmds", [])
                            if cmd.get("name") != "connect"
                        ]
                        if filtered_cmds:
                            response["cmds"] = filtered_cmds
                        else:
                            response.pop("cmds", None)
                        resp = bytes(f"{json.dumps(response)}\n", "ascii")
                    else:
                        resp = res.content

                    _LOGGER.info(
                        "\x1b[1;36mVisonic HTTPS ->\x1b[0m %s",
                        resp.decode(errors="replace").replace("\n", ""),
                        extra=MsgLogLevel.L5,
                    )

                    headers = HttpHeaders()
                    has_content_length = False
                    for k, v in res.headers.items():
                        if k.lower() == "content-length":
                            # Adjust content length if we modified the payload
                            headers.add(k, len(resp))
                            has_content_length = True
                        else:
                            headers.add(k, v)
                    if not has_content_length:
                        headers.add("Content-Length", len(resp))
                    return HttpResponse(200, headers, resp)
                return await self.send_man_response()

            return await self.send_man_response()
        elif self.proxy.config.PROXY_MODE:
            if res := await self.forward_request(request):
                response = res.content
                _LOGGER.info("RESPONSE: %s", response, extra=MsgLogLevel.L5)

                if request.path == "/scripts/pir_film.php":
                    await self.decode_image(request.body)

                headers = HttpHeaders()
                for k, v in res.headers.items():
                    headers.add(k, v)
                return HttpResponse(res.status_code, headers, res.content)

    @staticmethod
    def _sanitize_filename_part(value: object, default: str = "unknown") -> str:
        """Restrict filename segments to safe characters to prevent path traversal."""
        cleaned = re.sub(r"[^A-Za-z0-9_-]", "", str(value or ""))
        return cleaned or default

    @staticmethod
    def _save_image_sync(data: bytes, target_path: Path) -> None:
        """Decode and persist image bytes in a worker thread."""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(io.BytesIO(data)) as im:
            im.save(target_path)

    async def decode_image(self, data: bytes, images_dir: str = "./images"):
        """Decode camera PIR image safely without blocking the event loop."""
        if not data:
            return

        image_json: dict[str, str | None] = {}
        keys = [
            "version",
            "serial",
            "camera",
            "cameraTrigger",
            "film",
            "file",
            "index",
            "frameNum",
            "frameRate",
            "fileType",
            "filmType",
            "filesCount",
        ]
        for key in keys:
            keystr = f"{key}: (.*?)\r\n"
            match = re.search(bytes(keystr, "ascii"), data)
            if match:
                image_json[key] = match.group(1).decode("utf-8", errors="replace")
            else:
                image_json[key] = None

        frame_display: int | str = "unknown"
        if image_json["frameNum"] is not None:
            with contextlib.suppress(ValueError):
                frame_display = int(image_json["frameNum"]) + 1

        _LOGGER.info(
            "RECEIVED CAMERA IMAGE %s of %s",
            frame_display,
            image_json["filesCount"],
            extra=MsgLogLevel.L3,
        )
        _LOGGER.info("IMAGE INFO: %s", image_json, extra=MsgLogLevel.L5)

        # Extract binary image payload after the data header without truncating on \r\n
        parts = data.split(b"\r\ndata: ", 1)
        if len(parts) < 2:
            _LOGGER.warning("Camera image payload missing data header")
            return
        payload_parts = parts[1].split(b"\r\n", 1)
        if len(payload_parts) < 2:
            _LOGGER.warning("Camera image payload missing body separator")
            return
        image_bytes = payload_parts[1]

        dt_now = dt.datetime.now().strftime("%Y%m%d%H%M%S")
        serial = self._sanitize_filename_part(image_json["serial"], "panel")
        camera = self._sanitize_filename_part(image_json["camera"], "0")
        frame_num = self._sanitize_filename_part(image_json["frameNum"], "0")
        filename = f"{serial}_zone{camera}_{frame_num}_{dt_now}.jpg"

        base_dir = Path(images_dir).resolve()
        target_path = (base_dir / filename).resolve()
        if not target_path.is_relative_to(base_dir):
            _LOGGER.warning("Rejected unsafe camera image path: %s", filename)
            return

        try:
            await asyncio.to_thread(self._save_image_sync, image_bytes, target_path)

            self.proxy.events.fire_event(
                Event(
                    name=ConnectionName.ALARM_MONITOR,
                    event_type=EventType.NEW_CAMERA_IMAGE,
                    client_id=0,
                    event_data={
                        "image_info": image_json,
                        "data": image_bytes,
                    },
                )
            )
        except Exception as ex:  # noqa: BLE001
            _LOGGER.error("Error saving image.  Error is %s", ex)

    async def send_man_response(self):
        """Send constgructed response."""
        try:
            resp = {}
            if Connect.request_connect:
                _LOGGER.info("Webserver sent request to connect", extra=MsgLogLevel.L1)
                resp["cmds"] = [
                    {
                        "name": "connect",
                        "params": {"port": self.proxy.config.MESSAGE_PORT},
                    }
                ]

            resp.update({"ka_time": 10, "version": 3})
            response = json.dumps(resp)
            _LOGGER.info("Response: %s", response, extra=MsgLogLevel.L1)
            bin_resp = bytes(f"{response}\n", "ascii")

            _LOGGER.info("\x1b[1;36mCM HTTPS ->\x1b[0m %s", resp, extra=MsgLogLevel.L5)

            headers = HttpHeaders()

            headers.add(
                "Date",
                time.strftime("%a, %d %b %Y %H:%M:%S %Z", time.gmtime()),
            )
            headers.add("Content-Type", "application/json")
            headers.add("Content-Length", len(bin_resp))
            headers.add("Connection", "keep-alive")
            headers.add(
                "Content-Security-Policy",
                "default-src 'self'; frame-src 'self' https://*.google.com; style-src 'self' 'unsafe-inline' https://*.googleapis.com; font-src 'self' data: https:; connect-src 'self' ws://52.58.105.181 wss://52.58.105.181 https://*.google.com https://*.googleapis.com; script-src 'self' https://*.google.com https://*.googleapis.com 'unsafe-inline' 'unsafe-eval'; img-src 'self' https://*.google.com https://*.googleapis.com data: https://*.gstatic.com https://*.google.com",
            )
            headers.add("Strict-Transport-Security", "max-age=31536000")
            headers.add("X-Content-Type-Options", "nosniff")
            headers.add("X-Frame-Options", "SAMEORIGIN")
            headers.add("X-XSS-Protection", "1; mode=block")
            return HttpResponse(200, headers, bin_resp)
        except (TimeoutError, OSError) as ex:
            _LOGGER.warning("HTTP connection timed out sending to panel.  %s", ex)


class Webserver:
    """Ayncio web server."""

    def __init__(self, proxy: Proxy):
        """Init."""
        self.proxy = proxy
        self.port = self.proxy.config.WEBSERVER_PORT
        self.http_server = HttpServer(proxy)
        self.running: bool = True
        self.server_task: asyncio.Task

        self.request_connect: bool = True

    def set_request_to_connect(self):
        """Set response to http request to connect."""
        Connect.request_connect = True

    def unset_request_to_connect(self):
        """Unset response to http request to connect."""
        Connect.request_connect = False

    async def _webserver(self):
        """Start webserver."""
        self.http_server.add_handler(MyHandler(self.proxy, self.request_connect))
        # start the server and serve/wait forever
        await self.http_server.start("0.0.0.0", self.port)
        with contextlib.suppress(RuntimeError):
            await self.http_server.serve_forever()

    async def start(self):
        """Start webserver."""
        self.server_task = self.proxy.loop.create_task(
            self._webserver(), name="WebServer"
        )
        self.running = True
        _LOGGER.info("Started HTTP server on port %s (SSL enabled)", self.port)

    async def stop(self):
        """Stop webserver."""
        with contextlib.suppress(RuntimeError):
            await self.http_server.close()

        if self.server_task and not self.server_task.done():
            self.server_task.cancel()
        self.running = False
        _LOGGER.info("Stopped HTTP server")
