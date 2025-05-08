"""Logging."""

import logging
from logging.handlers import RotatingFileHandler
import sys

from .const import KEYWORD_COLORS, Colour, Config

DEBUG_FORMAT = "%(asctime)s %(levelname)-8s %(fileline)-20s %(message)s"
STD_FORMAT = "%(asctime)s %(levelname)-8s %(message)10s"


class MessageLevelFilter(logging.Filter):
    """Filter messages by message level."""

    def __init__(self, message_log_level: int = Config.MESSAGE_LOG_LEVEL):
        """Initialise."""
        super().__init__()
        self.message_log_level = message_log_level

    def set_message_log_level(self, message_log_level: int):
        """Set log level."""
        self.message_log_level = message_log_level

    def filter(self, record):
        """Apply filter."""
        if (
            record.__dict__.get("msglevel", 0) <= self.message_log_level
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


class VPLogger:
    """Class to handle custom logger."""

    def __init__(
        self,
        log_file: str = Config.LOG_FILE,
        log_level: int = Config.LOG_LEVEL,
        message_log_level: int = Config.MESSAGE_LOG_LEVEL,
    ):
        """Initialise."""
        self.log_file = log_file
        self.log_level = log_level
        self.message_log_level = message_log_level

        # Setup message filter
        self.message_filter = MessageLevelFilter(self.message_log_level)

        # Init logger
        handlers = []

        # File handler
        if self.log_file:
            self.f_handler = RotatingFileHandler(
                self.log_file, backupCount=Config.LOG_FILES_TO_KEEP
            )
            f_fmt = CustomFileFormatter(DEBUG_FORMAT)
            self.f_handler.setFormatter(f_fmt)
            self.f_handler.addFilter(self.message_filter)
            handlers.append(self.f_handler)

        # Stream handler to stdout
        s_handler = logging.StreamHandler(sys.stdout)
        s_fmt = CustomStreamFormatter(self.get_format_string())
        s_handler.setFormatter(s_fmt)
        s_handler.addFilter(self.message_filter)
        handlers.append(s_handler)

        # Initiate logger
        self.logger = logging.getLogger("visonic_proxy")
        self.logger.setLevel(self.log_level)
        for handler in handlers:
            self.logger.addHandler(handler)

    def rollover(self):
        """Rollover log file."""
        self.f_handler.doRollover()

    def get_format_string(self) -> str:
        """Get format string."""
        if self.log_level == logging.DEBUG:
            return DEBUG_FORMAT
        return STD_FORMAT
