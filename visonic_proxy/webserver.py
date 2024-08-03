"""Simple HTTP server to allow connection on port 8443.

Responds to POST reqest with simple response.
"""

import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
from ssl import PROTOCOL_TLS_SERVER, SSLContext
import time
import traceback

import requests
import urllib3

from .const import MESSAGE_LOG_LEVEL, PROXY_MODE, VISONIC_HOST, ConnectionName
from .events import Event, EventType, async_fire_event

urllib3.disable_warnings()

_LOGGER = logging.getLogger(__name__)


def log_message(message: str, *args, level: int = 5):
    """Log message to logger if level."""
    if level <= MESSAGE_LOG_LEVEL:
        _LOGGER.info(message, *args)


class WebResponseController:
    """Class for webresponse control."""

    loop: asyncio.AbstractEventLoop = None
    request_connect: bool = True  # Set to True for startup to make Alarm connect


class RequestHandler(BaseHTTPRequestHandler):
    """HTTP handler."""

    def log_message(self, *args):
        """Override log messages."""

    def do_GET(self):  # pylint: disable=invalid-name
        """Handle GET request."""
        _LOGGER.debug(
            "%s: %s\n%s\n%s",
            self.command,
            self.path,
            self.headers,
            self.request,
        )

    def do_POST(self):  # pylint: disable=invalid-name
        """Handle POST request."""

        content_len = int(self.headers.get("Content-Length"))
        try:
            post_body = self.rfile.read(content_len)
        except Exception:  # noqa: BLE001
            post_body = b""

        log_message(
            "\x1b[1;36mAlarm HTTPS ->\x1b[0m %s",
            post_body.decode().replace("\n", ""),
            level=5,
        )

        self.send_response(200)

        if PROXY_MODE:
            try:
                headers = {}
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                headers["Connection"] = "keep-alive"
                s = requests.Session()
                res = s.post(
                    f"https://{VISONIC_HOST}:8443{self.path}",
                    headers=headers,
                    data=post_body,
                    verify=False,
                    timeout=5,
                )

                # Check if Visonic asking for connection and fire request connection event
                try:
                    response: dict = res.json()
                    if cmds := response.get("cmds"):
                        for command in cmds:
                            if command.get("name") == "connect":
                                # fire event
                                log_message("Received web connection request", level=6)
                                event = Event(
                                    ConnectionName.VISONIC,
                                    EventType.WEB_REQUEST_CONNECT,
                                )
                                future = asyncio.run_coroutine_threadsafe(
                                    async_fire_event(event),
                                    WebResponseController.loop,
                                )
                                # Wait for the result with an optional timeout argument
                                try:
                                    assert future.result(5)
                                except (AssertionError, TimeoutError):
                                    _LOGGER.error(
                                        "Webserver failed to fire connect request event"
                                    )
                                    _LOGGER.error(traceback.format_exc())
                except requests.exceptions.JSONDecodeError:
                    _LOGGER.info("cannot decode response")
                    response = {}

                if WebResponseController.request_connect:
                    log_message("WEBSERVER: Request to connect is set", level=6)
                    resp = b'{"cmds":[{"name":"connect","params":{"port":5001}}],"ka_time":10,"version":3}\n'
                else:
                    resp = res.content

                log_message(
                    "\x1b[1;36mVisonic HTTPS ->\x1b[0m %s",
                    resp.decode().replace("\n", ""),
                    level=5,
                )

                if not self.wfile.closed:
                    for k, v in res.headers.items():
                        if k == "Content-Length":
                            # Ajust content length if we have added connect command
                            self.send_header(k, len(resp))
                        else:
                            self.send_header(k, v)
                    self.end_headers()
                    self.wfile.write(resp)
                    self.wfile.flush()
            except (TimeoutError, requests.exceptions.ReadTimeout, OSError) as ex:
                _LOGGER.warning(
                    "HTTP connection timed out error sending to Visonic. %s", ex
                )
        else:
            try:
                if not self.wfile.closed:
                    resp = {}
                    if WebResponseController.request_connect:
                        resp["cmds"] = [{"name": "connect", "params": {"port": 5001}}]

                    resp.update({"ka_time": 10, "version": 3})
                    response = json.dumps(resp)
                    bin_resp = bytes(f"{response}\n", "ascii")

                    log_message(
                        "\x1b[1;36mCM HTTPS ->\x1b[0m %s",
                        resp,
                        level=5,
                    )

                    self.send_header(
                        "Date",
                        time.strftime("%a, %d %b %Y %H:%M:%S %Z", time.gmtime()),
                    )
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", len(bin_resp))
                    self.send_header("Connection", "keep-alive")
                    self.send_header(
                        "Content-Security-Policy",
                        "default-src 'self'; frame-src 'self' https://*.google.com; style-src 'self' 'unsafe-inline' https://*.googleapis.com; font-src 'self' data: https:; connect-src 'self' ws://52.58.105.181 wss://52.58.105.181 https://*.google.com https://*.googleapis.com; script-src 'self' https://*.google.com https://*.googleapis.com 'unsafe-inline' 'unsafe-eval'; img-src 'self' https://*.google.com https://*.googleapis.com data: https://*.gstatic.com https://*.google.com",
                    )
                    self.send_header("Strict-Transport-Security", "max-age=31536000")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("X-Frame-Options", "SAMEORIGIN")
                    self.send_header("X-XSS-Protection", "1; mode=block")
                    self.end_headers()
                    self.wfile.write(bin_resp)
                    self.wfile.flush()
            except (TimeoutError, OSError) as ex:
                _LOGGER.warning("HTTP connection timed out sending to panel.  %s", ex)


class Webserver:
    """Threaded web server."""

    def __init__(self):
        """Init."""
        self.host = "0.0.0.0"
        self.port = 8443
        self.server: HTTPServer = None
        self.running: bool = True

    def set_request_to_connect(self):
        """Set response to http request to connect."""
        WebResponseController.request_connect = True

    def unset_request_to_connect(self):
        """Unset response to http request to connect."""
        WebResponseController.request_connect = False

    def _webserver(self, loop: asyncio.AbstractEventLoop):
        """Start webserver."""
        try:
            # Set loop
            WebResponseController.loop = loop
            dir_path = os.path.dirname(os.path.realpath(__file__))
            ssl_context = SSLContext(PROTOCOL_TLS_SERVER)
            ssl_context.load_cert_chain(
                dir_path + "/certs/cert.pem",
                dir_path + "/certs/private.key",
            )
            # self.host = get_ip()
            self.server = HTTPServer((self.host, self.port), RequestHandler)
            self.server.socket = ssl_context.wrap_socket(
                self.server.socket, server_side=True
            )

            _LOGGER.info("Webserver started on %s port %s", self.host, self.port)
        except (OSError, Exception) as ex:
            _LOGGER.error("Unable to start webserver. Error is %s", ex)
        else:
            while self.running:
                self.server.handle_request()

    async def stop(self):
        """Stop webserver."""
        self.running = False
        try:
            requests.request(
                "QUIT", f"https://{self.host}:{self.port}", verify=False, timeout=5
            )
        except TimeoutError as ex:
            _LOGGER.warning("HTTP connection timed out sending to self.  %s", ex)

        self.server.socket.close()
        self.server.server_close()

    async def start(self):
        """Start webserver."""
        evloop = asyncio.get_running_loop()
        await evloop.run_in_executor(None, self._webserver, evloop)
        _LOGGER.info("Webserver stopped")
