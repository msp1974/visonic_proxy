#!/usr/bin/env python

"""Run script."""

import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(SCRIPT_DIR))

from visonic_proxy.const import (  # noqa: E402
    LOG_FILES_TO_KEEP,
    LOG_LEVEL,
    LOG_TO_FILE,
    MESSAGE_LOG_LEVEL,
)
from visonic_proxy.runner import VisonicProxy  # noqa: E402


class MessageLevelFilter(logging.Filter):
    """Filter messages by message level."""

    def filter(self, record):
        """Apply filter."""

        if record.__dict__.get("msglevel", 0) <= MESSAGE_LOG_LEVEL:
            return True
        return False


class CustomFormatter(logging.Formatter):
    """Custom formatter."""

    def format(self, record):
        """Format record."""
        fileline = f"[{record.filename.replace(".py", "")}:{record.lineno}]"
        record.fileline = fileline
        return super().format(record)


messagelevelfilter = MessageLevelFilter()

# Set logging format output
if LOG_LEVEL == logging.DEBUG:
    formatter = CustomFormatter(
        "%(asctime)s %(levelname)-8s %(fileline)-20s %(message)s"
    )
else:
    formatter = CustomFormatter("%(asctime)s %(levelname)-8s %(message)10s")

# Add logging handlers
handlers = []

# Stream handler to stdout
s_handler = logging.StreamHandler(sys.stdout)
s_handler.setFormatter(formatter)
s_handler.addFilter(messagelevelfilter)
handlers.append(s_handler)

# File handler
if LOG_TO_FILE:
    f_handler = RotatingFileHandler(
        "../logs/message.log", backupCount=LOG_FILES_TO_KEEP
    )
    f_handler.setFormatter(formatter)
    f_handler.addFilter(messagelevelfilter)
    handlers.append(f_handler)


# Initiate logger
_LOGGER = logging.getLogger("visonic_proxy")
logging.basicConfig(
    level=LOG_LEVEL,
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=handlers,
)


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
