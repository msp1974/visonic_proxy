"""Helper functions."""

import inspect
import logging
import os

from .const import MESSAGE_LOG_LEVEL
from .enums import ConnectionName

_LOGGER = logging.getLogger(__name__)


def log_message(message: str, *args, level: int = 0, log_level=logging.INFO):
    """Log message to logger if level."""
    if level <= MESSAGE_LOG_LEVEL:
        if log_level == logging.WARNING:
            log = _LOGGER.warning
        elif log_level == logging.ERROR:
            log = _LOGGER.error
        elif log_level == logging.DEBUG:
            log = _LOGGER.debug
        else:
            log = _LOGGER.info

        if MESSAGE_LOG_LEVEL > 4:
            file = os.path.basename(inspect.stack()[1].filename).replace(".py", "")
            line_no = inspect.stack()[1].lineno
            pad = max(0, 22 - (len(file) + len(str(line_no))))
            log("[%s:%s]%s %s", file, line_no, " ".ljust(pad), message % args)
        else:
            log(message, *args)


def get_connection_id(name: ConnectionName, client_id: str) -> str:
    """Return connection id."""
    return f"{name}_{client_id}"
