"""Simple HTTP server to allow connection on port 8443

Responds to POST reqest with simple response."""

import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import logging
import os
from ssl import PROTOCOL_TLS_SERVER, SSLContext
import requests
import urllib3

from ..const import MESSAGE_LOG_LEVEL, PROXY_MODE, VISONIC_HOST

urllib3.disable_warnings()

_LOGGER = logging.getLogger(__name__)

initial_requests: int = 0

def log_message(message: str, *args, level: int = 5):
        """Log message to logger if level."""
        if MESSAGE_LOG_LEVEL >= level:
            _LOGGER.info(message, *args)

class RequestHandler(BaseHTTPRequestHandler):
    """HTTP handler"""
    def log_message(self, *args):
        """Override log messages."""

    def do_GET(self):  # pylint: disable=invalid-name
        """Handle GET request."""
        _LOGGER.info("GET Request: %s", self.request)
        _LOGGER.debug(
            "%s: %s\n%s\n%s",
            self.command,
            self.path,
            self.headers,
            self.request,
        )

    def do_POST(self):  # pylint: disable=invalid-name
        """Handle POST request"""
        global initial_requests

        content_len = int(self.headers.get('Content-Length'))
        try:
            post_body = self.rfile.read(content_len)
        except Exception:
            post_body = b""

        log_message("\x1b[1;36mAlarm HTTPS ->\x1b[0m %s", post_body.decode().replace("\n", ""), level=5)
        

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

                self.send_response(200)

                if initial_requests < 5:
                    resp = b'{"cmds":[{"name":"connect","params":{"port":5001}}],"ka_time":10,"version":3}\n'
                    initial_requests += 1
                else:
                    resp = res.content

                log_message("\x1b[1;36mVisonic HTTPS ->\x1b[0m %s", resp.decode().replace("\n", ""), level=5)

                if not self.wfile.closed:
                    for k, v in res.headers.items():
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
                    response = b'{"cmds":[{"name":"connect","params":{"port":5001}}],"ka_time":10,"version":3}\n'
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(response)
                    self.wfile.flush()
            except (TimeoutError, OSError) as ex:
                _LOGGER.warning("HTTP connection timed out sending to panel.  %s", ex)


class Webserver:
    """Threaded web server."""

    def __init__(self):
        self.host = "0.0.0.0"
        self.port = 8443
        self.server: HTTPServer = None
        self.running: bool = True

    def _webserver(self):
        """Start webserver."""
        dir_path = os.path.dirname(os.path.realpath(__file__))
        ssl_context = SSLContext(PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(
            dir_path + "/certs/cert.pem",
            dir_path + "/certs/private.key",
        )
        #self.host = get_ip()
        self.server = HTTPServer((self.host, self.port), RequestHandler)
        self.server.socket = ssl_context.wrap_socket(
            self.server.socket, server_side=True
        )

        _LOGGER.info("Webserver started on %s port %s", self.host, self.port)

        while self.running:
            self.server.handle_request()

    async def stop(self):
        """Stop webserver."""
        self.running = False
        try:
            requests.request(
                "QUIT", f"https://{self.host}:{self.port}", verify=False, timeout=10
            )
        except TimeoutError as ex:
            _LOGGER.warning("HTTP connection timed out sending to self.  %s", ex)

        self.server.socket.close()
        self.server.server_close()

    async def start(self):
        """Main."""
        # self.task = evloop.create_task(self.run_on_thread(evloop))
        evloop = asyncio.get_running_loop()
        await evloop.run_in_executor(None, self._webserver)
        _LOGGER.info("Webserver stopped")
