"""Handles creating messages to send to Alarm."""

from dataclasses import dataclass
import logging

from ..helpers.crc16 import Crc16Arc
from ..proxy import Proxy
from .pl31_decoder import PowerLink31Message
from .refs import VIS_ACK, VIS_BBA, ManagedMessages, MessageType

_LOGGER = logging.getLogger(__name__)


@dataclass
class NonPowerLink31Message:
    """Non Powerlink Message."""

    msg_type: str
    msg_id: int
    message_class: str
    data: bytes


@dataclass
class CommandRequest:
    """Class for command request."""

    command: str
    params: list


class MessageBuilder:
    """Class to build commands to send to alarm."""

    def __init__(self, proxy: Proxy):
        """Initialise."""
        self.proxy = proxy

    def _calculate_message_checksum(self, msg: bytearray) -> bytes:
        """Calculate CRC Checksum."""
        checksum = 0
        for char in msg[0 : len(msg)]:
            checksum += char
        checksum = 0xFF - (checksum % 0xFF)
        if checksum == 0xFF:
            checksum = 0x00
        return checksum.to_bytes(1, "big")

    def build_ack_message(
        self, msg_id: int = 0, pl_ack: bool = True
    ) -> NonPowerLink31Message:
        """Build ACK message.

        ACK - 0d 02 fd 0a
        PL_ACK - 0d 02 43 ba 0a
        """
        return NonPowerLink31Message(
            msg_type=VIS_ACK,
            msg_id=msg_id,
            message_class="02",
            data=bytes.fromhex(
                ManagedMessages.PL_ACK if pl_ack else ManagedMessages.ACK
            ),
        )

    def build_keep_alive_message(self) -> NonPowerLink31Message:
        """Build keep alive message.

        0d b0 01 6a 00 43 a0 0a
        """
        return NonPowerLink31Message(
            msg_type=VIS_BBA,
            msg_id=0,
            message_class="b0",
            data=bytes.fromhex(ManagedMessages.KEEPALIVE),
        )

    def build_eprom_rw_mode_message(self) -> str:
        """Build eprom rw mode message."""
        return self.build_std_request("09")

    def build_exit_eprom_rw_mode(self) -> str:
        """Build exit eprom mode message."""
        return self.build_std_request("0f")

    def message_preprocessor(self, msg: bytes) -> NonPowerLink31Message:
        r"""Preprocessor for using injector to send message to alarm.

        Messages can be injected in:
        Full format - 0d b0 01 6a 00 43 a0 0a \ 0d a2 00 00 08 00 00 00 00 00 00 00 43 12 0a
        Partial format - b0 01 6a 43 \ a2 00 00 08 00 00 00 00 00 00 00 43
        Short format (for B0 messages only) - b0 6a / b0 17 18 24
        """
        msg_type = VIS_BBA

        _LOGGER.debug("Message Builder Received - %s", msg.hex(" "))

        if msg[:1] == b"\x0d" and msg[-1:] == b"\x0a":
            if msg[1:2] == b"\x02":
                # Received ack message.  Use build_ack_message to ensure correct ACK type
                # message = self.build_ack_message().data.hex(" ")
                message = (
                    ManagedMessages.PL_ACK
                    if msg == bytes.fromhex(ManagedMessages.ACK)
                    else msg.hex(" ")
                )
                msg_type = VIS_ACK
            else:
                message = msg.hex(" ")

        # Else deal with shortcut commands
        elif msg[:1] == b"\xb0":
            if msg[-1:] != b"\x43":
                command = msg[1:2].hex()
                params = msg[2:].hex(" ")
                message = self.build_b0_request(command, params)
            else:
                message = self.build_b0_partial_request(msg.hex(" "))
        else:
            message = self.build_std_request(msg)

        _LOGGER.debug("Message Builder Returned: %s", message)

        data = bytes.fromhex(message)
        message_class = data[1:2].hex()
        return NonPowerLink31Message(
            msg_type=msg_type, msg_id=0, message_class=message_class, data=data
        )

    def build_std_request(self, command: bytes) -> str:
        r"""Build standard message to alarm.

        Input is
        A6 00 00 00 00 00 00 00 00 00 00 43
        Output should be (wrapped in a powerlink message)
        0d A6 00 00 00 00 00 00 00 00 00 00 43 ea 0a
        0d a2 00 00 08 00 00 00 00 00 00 00 43 12 0a

        0 is always 0d as message start
        1 is std command
        2 - 11 are 00
        12 is always 43 (C)
        13 is checksum (claculated without start and end of message)
        14 is always 0a (\n) as message end
        """
        msg = command.hex(" ")
        checksum = self._calculate_message_checksum(bytes.fromhex(msg))
        msg += f" {checksum.hex()}"

        return f"0d {msg} 0a"

    def build_b0_add_remove_message(
        self, message_type: MessageType, cmd: str, code: str, data: bytes
    ) -> NonPowerLink31Message:
        """Build a b0 00 or b0 04 message.

        data should be bytes and include all data after ff ie 01 03 02 00 01 for bits datatype, zone index, length 4, zones
        """
        msg_type = VIS_BBA
        msg = "b0 04"
        if message_type == MessageType.ADD:
            msg = "b0 00"

        length = len(data) + 2

        code = bytes.fromhex(code).hex(" ")
        # msg_data = f"{download_code} ff 01 03 08 {zone_data.hex(" ")}"
        msg = f"b0 {'00' if message_type == MessageType.ADD else '04'} {cmd} {length:02x} {code} {data.hex(' ')} 43"

        checksum = self._calculate_message_checksum(bytes.fromhex(msg))
        msg += f" {checksum.hex()}"

        message = f"0d {msg} 0a"
        data = bytes.fromhex(message)
        message_class = data[1:2].hex()
        return NonPowerLink31Message(
            msg_type=msg_type, msg_id=0, message_class=message_class, data=data
        )

    def build_b0_request(self, command: str, params: str = "") -> str:
        """Build b0 message to alarm.

        0d b0 01 [command and params] 43 [checksum] 0a
        """
        msg = "b0 01"

        func = f"_build_b0_{command}_request"
        if hasattr(self, func):
            msg += f" {getattr(self, func)(params)}"
        else:
            msg += f" {self._build_b0_generic_request(command, params)}"

        msg += " 43"

        checksum = self._calculate_message_checksum(bytes.fromhex(msg))
        msg += f" {checksum.hex()}"

        return f"0d {msg} 0a"

    def build_b0_partial_request(self, msg: str) -> str:
        """Wrap b0 full command.

        input message should start b0 or e0 and end 43
        """
        checksum = self._calculate_message_checksum(bytes.fromhex(msg))
        msg += f" {checksum.hex()}"
        return f"0d {msg} 0a"

    def _build_b0_generic_request(self, cmd: int, params: str = "") -> str:
        """Build generic request.

        format is
        [cmd] [length of params] [params]
        ie 24 01 05
        """
        length = 0
        msg = ""
        if params:
            length = len(bytearray.fromhex(params))
            msg += f"{cmd} {length:02} {params}"
        else:
            msg += f"{cmd} 01 05"  # Some commands need 05 as param, others not but adding to all seems to work

        return msg

    def _build_b0_17_request(self, params: str) -> str:
        """Build 17 request.

        TESTING
        """
        cmd = "17"
        if params:
            no_requests = len(params.split(" "))
            length = 6 + no_requests
            return f"{cmd} {length:02x} 01 ff 08 ff {no_requests:02x} {params} 00"

        return self._build_b0_generic_request(cmd, params)

    def _build_b0_35_request(self, params: str) -> str:
        """Build command message for a 35 config command.

        format is
        35 [length] 02 ff 08 ff [length of configs] [configs]
        ie 35 07 02 ff 08 ff 02 03 00

        can be multi configs
        ie 35 09 02 ff 08 ff 04 03 00 07 00

        """
        cmd = "35"
        no_configs = int(len(params.split(" ")) / 2)
        length = 5 + (no_configs * 2)
        msg = f"{cmd}"
        msg += f" {length:02x}"
        msg += " 02 ff 08 ff"
        msg += f" {no_configs * 2:02x}"  # 2 bytes per config entry
        msg += f" {params}"

        return msg

    def _build_b0_42_request(self, params: str) -> str:
        """Build command message for a 42 config command.

        format is
        42 [length] 02 ff 08 0c [length of configs] [configs]
        ie 42 0b 02 ff 08 0c 06 42 00 00 00 ff ff

        can be multi configs
        ie 42 0d 06 ff 08 0c 08 a4 00 a5 00 18 01 19 01 43 1c 0a

        """
        cmd = "42"
        no_configs = int(len(params.split(" ")) / 2)

        if no_configs == 1:
            params = f"{params} 00 00 ff ff"
        elif no_configs == 2:
            params = f"{params} ff ff"

        length = 5 + (max(6, no_configs * 2))
        msg = f"{cmd}"
        msg += f" {length:02x}"
        msg += f" {(6 if no_configs > 1 else 2):02d}"
        msg += " ff 08 0c"
        msg += f" {(length - 5):02x}"  # 2 bytes per config entry
        msg += f" {params}"
        return msg

    def build_powerlink31_message(
        self, msg_id: int, message: bytes, is_ack: bool = False
    ) -> PowerLink31Message:
        r"""Build initial part of B0 message.

        format is
        0a [CRC16][Length][MSG TYPE][MSG ID]L[ACCT NO]#[ALARM SERIAL][COMMAND]\r

        0a 6BAF   001D    "VIS-BBA" 5564    L 001234  # 2A4CC3       [See standard or b0 below]0d
        ie
        0a 36 42 41 46 30 30 31 44 22 56 49 53 2d 41 43 4b 22 35 35 36 34 4c 30 23 32 41 34 43 43 33 5b 0d 02 43 ba 0a 5d 0d
        b'\n6BAF001D"VIS-ACK"5564L0#2A4CC3[\r\x02C\xba\n]\r'

        Notes
        CRC16 is CRC16ARC of message from first " to last ]
        Length is from first " to last ]
        "VIS-ACK"/"VIS-BBA" - ACK for msg acknowldge, BBA for command/response message - have seen some *ADM-CID and *ACK
        MSG_ID increases with each BBA message.  ACK should be same as BBA it is ACK'ing
        ACCT_NO - message to Alarm is 0, from alarm is account no.

        """
        message = message.hex(" ")

        msg_initiator = "\n"
        msg_type = "VIS-ACK" if is_ack else "VIS-BBA"

        msg_start = (
            f'"{msg_type}"{msg_id:04}L{self.proxy.account_id}#{self.proxy.panel_id}['
        )
        msg_end = "]"
        msg_terminator = "\r"

        base_msg = bytearray()
        base_msg.extend(map(ord, msg_start))
        base_msg.extend(bytearray.fromhex(message))
        base_msg.extend(map(ord, msg_end))

        # generate message prefix
        # crc
        crc16 = Crc16Arc.calchex(base_msg)
        msg_length = len(base_msg).to_bytes(2, byteorder="big")

        msg = bytearray()
        msg.extend(map(ord, msg_initiator))
        msg.extend(map(ord, crc16.upper()))
        msg.extend(map(ord, msg_length.hex()))
        msg.extend(base_msg)
        msg.extend(map(ord, msg_terminator))

        return PowerLink31Message(
            crc16=crc16,
            length=msg_length,
            msg_type=msg_type,
            msg_id=msg_id,
            account_id=self.proxy.account_id,
            panel_id=self.proxy.panel_id,
            message_class="",
            data=bytearray.fromhex(message),
            raw_data=msg,
        )
