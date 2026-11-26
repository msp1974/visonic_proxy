"""Fallback stubs for optional third-party packages when running tests outside Docker/venv."""

import importlib.util
import sys
import types


def install_missing_stubs():
    """Install lightweight module stubs only if third-party packages are not installed."""
    if "websockets" not in sys.modules and importlib.util.find_spec("websockets") is None:
        ws = types.ModuleType("websockets")
        ws.ConnectionClosed = type("ConnectionClosed", (Exception,), {})

        ws_asyncio = types.ModuleType("websockets.asyncio")
        ws_server = types.ModuleType("websockets.asyncio.server")
        ws_server.ServerConnection = object
        ws_server.serve = lambda *args, **kwargs: None

        ws_http11 = types.ModuleType("websockets.http11")
        ws_http11.Request = object

        sys.modules["websockets"] = ws
        sys.modules["websockets.asyncio"] = ws_asyncio
        sys.modules["websockets.asyncio.server"] = ws_server
        sys.modules["websockets.http11"] = ws_http11

    if "PIL" not in sys.modules and importlib.util.find_spec("PIL") is None:
        pil = types.ModuleType("PIL")
        pil_image = types.ModuleType("PIL.Image")
        pil.Image = pil_image
        sys.modules["PIL"] = pil
        sys.modules["PIL.Image"] = pil_image

    if "requests" not in sys.modules and importlib.util.find_spec("requests") is None:
        req = types.ModuleType("requests")
        req_exc = types.ModuleType("requests.exceptions")
        req_exc.ReadTimeout = type("ReadTimeout", (TimeoutError,), {})
        req_exc.JSONDecodeError = ValueError
        req.exceptions = req_exc
        req.Response = object
        req.Session = object
        sys.modules["requests"] = req
        sys.modules["requests.exceptions"] = req_exc

    if "urllib3" not in sys.modules and importlib.util.find_spec("urllib3") is None:
        u3 = types.ModuleType("urllib3")
        u3.disable_warnings = lambda *args, **kwargs: None
        u3_exc = types.ModuleType("urllib3.exceptions")
        u3_exc.ConnectTimeoutError = type("ConnectTimeoutError", (TimeoutError,), {})
        u3.exceptions = u3_exc
        sys.modules["urllib3"] = u3
        sys.modules["urllib3.exceptions"] = u3_exc
