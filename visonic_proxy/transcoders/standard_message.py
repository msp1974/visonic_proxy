"""Decode stanard message."""

from dataclasses import dataclass, field
from enum import StrEnum
import logging

from .helpers import b2i, calculate_message_checksum

_LOGGER = logging.getLogger(__name__)


class StandardCommand(StrEnum):
    """Standard message command."""

    ACK = "02"
    HELLO = "06"
    ACCESS_DENIED = "08"
    EPROM_RW_MODE = "09"
    EXIT_RW_MODE = "0f"
    ARM_ALARM = "a1"
    REQ_STATUS = "a2"
    STATUS_UPDATE = "a5"
    ZONE_TYPE = "a6"
    SET_DATETIME = "ab"
    EPROM_INFO = "3c"
    WRITE_CONFIG = "3d"
    READ_CONFIG = "3e"
    CONFIG_VALUE = "3f"


@dataclass
class STDMessage:
    """Class to hold standard message structure."""

    cmd: str
    start: int = 0
    data: dict = field(default_factory={})
    raw_data: bytes | None = None
    verified: bool = False


class STDMessageDecoder:
    """Standard message decoder."""

    def decode(self, msg: bytes) -> STDMessage:
        """Get standard message."""
        command = msg[1:2].hex()
        # command_str = get_lookup_value(StandardCommand, command)
        data = msg[2:-2]
        checksum = msg[-2:-1].hex()
        verified = checksum == calculate_message_checksum(msg[1:-2]).hex()

        # decode data if known structure
        func = f"format_{command}"
        if hasattr(self, func):
            start, decoded = getattr(self, func)(data)
            return STDMessage(
                cmd=command,
                start=start,
                data=decoded,
                raw_data=decoded,
                verified=verified,
            )
        decoded = data.hex(" ")

        return STDMessage(
            cmd=command, start=0, data=decoded, raw_data=decoded, verified=verified
        )

    def format_3f(self, data: bytes) -> STDMessage:
        """Handle 3f EPROM download data."""
        position = b2i(data[0:2])
        length = data[2]
        mdata = data[3 : 3 + length]

        # _FILELOGGER.info("EPROM: \nPAGE: %s\nSTART: %s\nLENGTH: %s\nDATA:%s", start, page, length, mdata)

        return position, mdata.hex(" ")
