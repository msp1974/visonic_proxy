"""Logging."""

import logging
from logging.handlers import RotatingFileHandler
import sys

from .const import (
    KEYWORD_COLORS,
    LOG_FILES_TO_KEEP,
    LOG_LEVEL,
    LOG_TO_FILE,
    MESSAGE_LOG_LEVEL,
)
from .enums import Colour

DEBUG_FORMAT = "%(asctime)s %(levelname)-8s %(fileline)-20s %(message)s"
STD_FORMAT = "%(asctime)s %(levelname)-8s %(message)10s"


class MessageLevelFilter(logging.Filter):
    """Filter messages by message level."""

    def filter(self, record):
        """Apply filter."""
        if (
            record.__dict__.get("msglevel", 0) <= MESSAGE_LOG_LEVEL
            or record.levelno == logging.DEBUG
        ):
            return True
        return False


class CustomFileFormatter(logging.Formatter):
    """Custom formatter for log file output."""

    def format(self, record):
        """Format record."""
        # Add filename and lineno formatting attribute
        fileline = f"[{record.filename.replace(".py", "")}:{record.lineno}]"
        record.fileline = fileline

        message = super().format(record)

        if hasattr(self, "colour_keywords"):
            message = getattr(self, "colour_keywords")(message)
        return message


class CustomStreamFormatter(CustomFileFormatter):
    """Custom formatter."""

    def colour_keywords(self, message: str) -> str:
        """Colour format keywords."""
        for keywordcolour in KEYWORD_COLORS:
            for prefix in keywordcolour.prefix_filter:
                if f"{prefix}{keywordcolour.keyword}" in message:
                    message = message.replace(
                        keywordcolour.keyword,
                        f"{keywordcolour.colour}{keywordcolour.keyword}{Colour.reset}",
                    )
            for suffix in keywordcolour.suffix_filter:
                if f"{keywordcolour.keyword}{suffix}" in message:
                    message = message.replace(
                        keywordcolour.keyword,
                        f"{keywordcolour.colour}{keywordcolour.keyword}{Colour.reset}",
                    )

        return message


def get_format_string() -> str:
    """Get format string."""
    if LOG_LEVEL == logging.DEBUG:
        return DEBUG_FORMAT
    return STD_FORMAT


# Add logging handlers
handlers = []

message_filter = MessageLevelFilter()


# File handler
if LOG_TO_FILE:
    f_handler = RotatingFileHandler(
        "../logs/message.log", backupCount=LOG_FILES_TO_KEEP
    )
    f_fmt = CustomFileFormatter(DEBUG_FORMAT)
    f_handler.setFormatter(f_fmt)
    f_handler.addFilter(message_filter)
    handlers.append(f_handler)

# Stream handler to stdout
s_handler = logging.StreamHandler(sys.stdout)
s_fmt = CustomStreamFormatter(get_format_string())
s_handler.setFormatter(s_fmt)
s_handler.addFilter(message_filter)
handlers.append(s_handler)

# Initiate logger
_LOGGER = logging.getLogger("visonic_proxy")
_LOGGER.setLevel(LOG_LEVEL)
for handler in handlers:
    _LOGGER.addHandler(handler)
# _LOGGER.handlers = handlers


def rollover():
    """Rollover log file."""
    f_handler.doRollover()
