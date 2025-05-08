#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from inspect import getfullargspec
import json
import logging
import os
import re
from ssl import PROTOCOL_TLS_SERVER, SSLContext
import types
from typing import TYPE_CHECKING

from visonic_proxy.proxy import Proxy

from .utils import (
    HttpHeaders,
    HttpRequest,
    HttpResponse,
    http_parser,
    http_send_response,
)

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)


@dataclass
class UriRoute:
    """URI route."""

    path: str | re.Pattern
    http_method: str | list[str]
    uri_variables: list[str] | None
    call_args: list[str]

    def is_static(self) -> bool:
        """Get if static route."""
        return not isinstance(self.path, re.Pattern)

    def http_methods(self) -> Generator[str]:
        """Get methods."""
        if isinstance(self.http_method, str):
            yield self.http_method
        else:
            for m in self.http_method:
                yield m

    def match(self, http_method: str, path: str) -> bool:
        """Match method and path."""
        for m in self.http_methods():
            if m == http_method:
                break
        else:
            return False

        if self.is_static():
            return path == self.path
        return self.path.match(path) is not None


def _convert_params(request: HttpRequest, route: UriRoute, method):
    args_index = 0 if isinstance(method, types.FunctionType) else 1  # skip 'self'
    args = []
    for param_name in route.call_args[args_index:]:
        if param_name == "request":
            args.append(request)
        elif param_name == "raw_body":
            args.append(request.body)
        elif param_name == "body":
            args.append(json.loads(request.body))
        elif param_name == "query_params":
            args.append(request.query_params)
        elif param_name == "headers":
            args.append(request.headers)
        elif param_name == "uri_variables":
            uri_variables = (
                dict(zip(route.uri_variables, re.findall(route.path, request.path)))
                if len(route.uri_variables) == 1
                else dict(
                    zip(route.uri_variables, re.findall(route.path, request.path)[0])
                )
            )
            args.append(uri_variables)
        else:
            args.append(None)
    return args


def _uri_variable_to_pattern(uri):
    """Converts a URI like /foo/{name}/{id}/bar
    into a regex pattern like /foo/(?P<name>[^/]*)/(?P<id>[^/]*)/bar
    """
    uri_variables = []
    last_index = 0
    uri_parts = ["^"]
    for m in re.finditer(r"\{(.*?)\}", uri):
        group_name = m.group(1)
        uri_variables.append(group_name)
        start, end = m.span()
        uri_parts.append(uri[last_index:start])
        uri_parts.append("(?P<")
        uri_parts.append(group_name)
        uri_parts.append(">[^/]*)")
        last_index = end
    if last_index < len(uri):
        uri_parts.append(uri[last_index:])
    uri_parts.append("$")
    return uri_variables, re.compile("".join(uri_parts))


def _uri_route_decorator(
    f,
    path: str | re.Pattern,
    http_method: str | list[str],
    uri_variables: list[str] | None = None,
):
    args_specs = getfullargspec(f)
    route = UriRoute(path, http_method, uri_variables, args_specs.args)

    routes = getattr(f, "_http_routes", [])
    routes.append(route)
    f._http_routes = routes
    return f


def _scan_handler_for_uri_routes(handler: object) -> Generator[tuple[object, UriRoute]]:
    for attr in dir(handler):
        method = getattr(handler, attr)
        for route in getattr(method, "_http_routes", []):
            yield method, route


def uri_mapping(path: str, method: str | list[str] = "GET"):
    return lambda f: _uri_route_decorator(f, path, method)


def uri_pattern_mapping(path: str, method: str | list[str] = "GET"):
    return lambda f: _uri_route_decorator(f, re.compile(path), method)


def uri_variable_mapping(path: str, method: str | list[str] = "GET"):
    uri_variables, uri_regex = _uri_variable_to_pattern(path)
    return lambda f: _uri_route_decorator(f, uri_regex, method, uri_variables)


class HttpResponseException(Exception):
    response: HttpResponse

    def __init__(
        self,
        status_code: int,
        headers: HttpHeaders | None = None,
        body: bytes | None = None,
    ) -> None:
        super().__init__()
        self.response = HttpResponse(status_code, headers, body)


class HttpServer:
    def __init__(self, proxy: Proxy) -> None:
        self.proxy = proxy
        self.read_timeout = 2
        self._default_response_headers = HttpHeaders()
        self._static_routes = {}
        self._regex_routes = []
        self._server = None
        self._debug_http = True

    async def __aenter__(self):
        pass

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    def set_http_debug_enabled(self, enabled: bool):
        self._debug_http = enabled

    def add_default_response_headers(self, headers: HttpHeaders):
        self._default_response_headers.merge(headers)

    def add_handler(self, handler):
        logger.debug("Register handler %s", handler)
        for method, route in _scan_handler_for_uri_routes(handler):
            if route.is_static():
                for http_method in route.http_methods():
                    self._static_routes[f"{http_method}:{route.path}"] = (route, method)
                    logger.debug(
                        "Register static route %s %s to %s",
                        http_method,
                        route.path,
                        method,
                    )
            else:
                self._regex_routes.append((route, method))
                logger.debug(
                    "Register regex route %s %s to %s",
                    route.http_method,
                    route.path,
                    method,
                )

    async def start(self, host, port):
        if self._server is not None:
            raise RuntimeError("Server already started")

        dir_path = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        )
        ssl_context = SSLContext(PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(
            dir_path + f"/{self.proxy.config.SSL_CERT_PATH}/cert.pem",
            dir_path + f"/{self.proxy.config.SSL_CERT_PATH}/private.key",
        )

        self._server = await asyncio.start_server(
            self._handle_client, host, port, ssl=ssl_context
        )

    async def close(self):
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def serve_forever(self):
        if self._server is None:
            raise RuntimeError("Server not started yet")

        try:
            async with self._server:
                await self._server.serve_forever()
        finally:
            self._server = None

    def bind_address_description(self):
        return ", ".join(str(sock.getsockname()) for sock in self._server.sockets)

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            # while True:
            request = await http_parser(reader, self.read_timeout, self._debug_http)
            if request is None:
                return
            logger.debug("received request %s %s", request.method, request.path)

            route, method = self._find_route(request)
            if method:
                logger.debug("found matching route %s calling method %s", route, method)
                await self._process_request(writer, route, method, request)
            else:
                logger.warning(
                    "unable to find any matching route for %s %s",
                    request.method,
                    request.path,
                )
                response = self.build_http_404_response(request.method, request.path)
                await self._send_response(writer, request, response)
            return

        except (
            TimeoutError,
            asyncio.TimeoutError,
            asyncio.exceptions.IncompleteReadError,
        ) as e:
            logger.warning("got a failure %s. disconnecting the client", type(e))
        except Exception as e:
            logger.exception(
                "got a failure %s. disconnecting the client: %s", type(e), e
            )
        finally:
            writer.close()

    def build_http_404_response(self, _method: str, _path: str) -> HttpResponse:
        return HttpResponse(404)

    def build_http_500_response(self, _exception: Exception) -> HttpResponse:
        return HttpResponse(500)

    async def _process_request(self, writer, route, method, request: HttpRequest):
        try:
            args = _convert_params(request, route, method)
            response = method(*args)
            if asyncio.iscoroutine(response):
                response = await response

            if not isinstance(response, HttpResponse):
                if response is None:
                    response = HttpResponse(204)
                else:
                    # TODO: by default we convert to json
                    body = json.dumps(response).encode("utf-8")
                    response = HttpResponse(200, None, body)
            await self._send_response(writer, request, response)
        except HttpResponseException as e:
            await self._send_response(writer, request, e.response)
        except Exception as e:
            logger.exception(
                "got a %s failure during the execution of the request %s %s",
                type(e),
                request.method,
                request.path,
            )
            response = self.build_http_500_response(e)
            await self._send_response(writer, request, response)

    async def _send_response(
        self, writer, request: HttpRequest, response: HttpResponse
    ):
        if response.headers:
            response.headers.merge(self._default_response_headers)
        else:
            response.headers = self._default_response_headers
        await http_send_response(writer, request, response, self._debug_http)

    def _find_route(self, request: HttpRequest):
        mapping = self._static_routes.get(f"{request.method}:{request.path}")
        if mapping:
            return mapping

        for route, method in self._regex_routes:
            if route.match(request.method, request.path):
                return route, method
        return None, None
