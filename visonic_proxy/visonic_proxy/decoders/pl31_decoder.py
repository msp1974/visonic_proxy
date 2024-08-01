"""Decode Powerlink31 message wrapper."""

from dataclasses import dataclass
import logging
import re

from ..const import NAK

_LOGGER = logging.getLogger(__name__)


@dataclass
class PowerLink31Message:
    """Message class."""

    crc16: str
    length: str
    msg_type: str
    msg_id: int
    account_id: str
    panel_id: str
    message_class: str
    data: bytes
    raw_data: bytes


class PowerLink31MessageDecoder:
    """Class to handle messages received."""

    def get_powerlink_31_wrapper(self, message: bytes) -> bytes:
        """Get first part of message."""
        i = message.find(b"\x5b")
        return message[1:i]

    def decode_powerlink31_message(self, message: bytes) -> PowerLink31Message:
        """Decode powerlink 3.1 message wrapper."""

        msg_decode = self.get_powerlink_31_wrapper(message).decode("ascii")
        l_index = msg_decode.find("L")
        hash_index = msg_decode.find("#")
        msg_start = message.find(b"\x5b")

        crc16 = msg_decode[0:4]
        length = msg_decode[4:8]
        msg_type = re.findall('"([^"]*)"', msg_decode)[0]

        if msg_type == NAK:
            # A NAK does not have any msgid, panel or account info
            # Data is empty and followed by a time/date
            # NAK: b'\nE5630025"NAK"0000R0L0A0[]_10:10:18,07-30-2024\r'

            # Set message to be time/date
            msg_start = message.find(b"\x5d")
            msg = message[msg_start + 2 : -1]

            return PowerLink31Message(
                crc16=crc16,
                length=length,
                msg_type=msg_type,
                msg_id=0,
                account_id="0",
                panel_id="0",
                message_class="",
                data=msg,
                raw_data=message,
            )

        msg_id = msg_decode[l_index - 4 : l_index]
        account_id = msg_decode[l_index + 1 : hash_index]
        panel_id = msg_decode[hash_index + 1 : hash_index + 7]
        msg = message[msg_start + 1 : -2]
        message_class = msg[1:2].hex()

        return PowerLink31Message(
            crc16=crc16,
            length=length,
            msg_type=msg_type,
            msg_id=int(msg_id),
            account_id=account_id,
            panel_id=panel_id,
            message_class=message_class,
            data=msg,
            raw_data=message,
        )
