#!/usr/bin/env python

"""Run script."""

import asyncio
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(SCRIPT_DIR))

from visonic_proxy.connections.httpserver.make_certs import cert_gen  # noqa: E402
from visonic_proxy.const import LOG_TO_FILE  # noqa: E402
from visonic_proxy.logger import _LOGGER, rollover  # noqa: E402
from visonic_proxy.runner import VisonicProxy  # noqa: E402


def validate_certs():
    """Validate certificate files."""
    if os.path.isfile("./connections/httpserver/certs/cert.pem") and os.path.isfile(
        "./connections/httpserver/certs/private.key"
    ):
        return True

    # Generate certs
    _LOGGER.info("Generating webserver certificates")
    try:
        cert_gen(path="./connections/httpserver/certs/")
        return True  # noqa: TRY300
    except Exception as ex:  # noqa: BLE001
        _LOGGER.error("Error generating certificates - %s", ex)
        return False


if __name__ == "__main__":
    if validate_certs():
        # start a new log on each restart
        if LOG_TO_FILE:
            rollover()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        proxy_server = VisonicProxy(loop)
        task = loop.create_task(proxy_server.start(), name="ProxyRunner")
        try:
            loop.run_until_complete(task)
        except KeyboardInterrupt:
            _LOGGER.info("Keyboard interrupted. Exit.")
            task.cancel()
            loop.run_until_complete(proxy_server.stop())
        loop.close()
    else:
        _LOGGER.error(
            "Unable to find certificate files.  Please generate these with create_certs.sh"
        )
