"""Decode Powerlink31 message wrapper."""

import logging
import re
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)


@dataclass
class PowerLink31Message:
    """Message class."""

    crc16: str
    length: str
    type: str
    msg_id: str
    account_id: str
    panel_id: str
    message_class: str
    message: bytes


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
        msg_id = msg_decode[l_index - 4 : l_index]
        account_id = msg_decode[l_index + 1 : hash_index]
        panel_id = msg_decode[hash_index + 1 : hash_index + 7]
        msg = message[msg_start + 1 : -2]
        message_class = msg[1:2].hex()

        return PowerLink31Message(
            crc16=crc16,
            length=length,
            type=msg_type,
            msg_id=msg_id,
            account_id=account_id,
            panel_id=panel_id,
            message_class=message_class,
            message=msg,
        )
