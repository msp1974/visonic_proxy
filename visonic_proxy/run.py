#!/usr/bin/env python

"""Run script."""

import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(SCRIPT_DIR))

from visonic_proxy.const import LOG_FILES_TO_KEEP, LOG_LEVEL, LOG_TO_FILE  # noqa: E402
from visonic_proxy.runner import VisonicProxy  # noqa: E402

handlers = [logging.StreamHandler(sys.stdout)]

if LOG_TO_FILE:
    f_handler = RotatingFileHandler(
        "../logs/message.log", backupCount=LOG_FILES_TO_KEEP
    )
    handlers.append(f_handler)

logging.basicConfig(
    # force=
    level=LOG_LEVEL,
    format="%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=handlers,
)


_LOGGER = logging.getLogger(__name__)


if __name__ == "__main__":
    # start a new log on each restart
    if LOG_TO_FILE:
        f_handler.doRollover()

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
