"""Handles creating messages to send to Alarm."""

from dataclasses import dataclass
import logging

from .crc16 import Crc16Arc

_LOGGER = logging.getLogger(__name__)


@dataclass
class MessageItem:
    """Class for message ite to add to queue."""

    msg_id: int
    msg_type: str
    message: str
    msg_data: bytearray


@dataclass
class CommandRequest:
    """Class for command request."""

    command: str
    params: list


class MessageBuilder:
    """Class to build commands to send to alarm."""

    alarm_serial: str = None
    account: str = None

    def _calculate_message_checksum(self, msg: bytearray) -> bytes:
        """Calculate CRC Checksum."""
        checksum = 0
        for char in msg[0 : len(msg)]:
            checksum += char
        checksum = 0xFF - (checksum % 0xFF)
        if checksum == 0xFF:
            checksum = 0x00
        return checksum.to_bytes(1, "big")

    def build_ack_message(self, msg_id: int) -> MessageItem:
        """Build ACK message."""
        ack = "0d 02 43 ba 0a"
        return self.build_powerlink31_message(msg_id, ack, is_ack=True)

    def build_keep_alive_message(self, msg_id: int) -> MessageItem:
        """Build keep alive message."""
        ka = "0d b0 01 6a 00 43 a0 0a"
        return self.build_powerlink31_message(msg_id, ka)

    def build_eprom_rw_mode_message(self, msg_id: int) -> MessageItem:
        """Build eprom rw mode message."""
        return self.build_std_request(msg_id, "09")

    def build_exit_eprom_rw_mode(self, msg_id: int) -> MessageItem:
        """Build exit eprom mode message."""
        return self.build_std_request(msg_id, "0f")

    def message_preprocessor(self, msg_id: int, msg: bytes) -> MessageItem:
        r"""Preprocessor for using injector to send message to alarm.

        Messages can be injected in:
        Full format - 0d b0 01 6a 00 43 a0 0a \ 0d a2 00 00 08 00 00 00 00 00 00 00 43 12 0a
        Partial format - b0 01 6a 43 \ a2 00 00 08 00 00 00 00 00 00 00 43
        Short format (for B0 messages only) - b0 6a / b0 17 18 24
        """
        if msg[:1] == b"\x0d" and msg[-1:] == b"\x0a":
            if msg[1:2] == b"\x02":
                # Received ack message.  Use build_ack_message to ensure correct ACK type
                message = self.build_ack_message(msg_id)
            else:
                message = self.build_powerlink31_message(msg_id, msg.hex(" "))
            return message

        # Else deal with shortcut commands
        if msg[:1] == b"\xb0":
            if msg[-1:] != b"\x43":
                command = msg[1:2].hex()
                params = msg[2:].hex(" ")
                message = self.build_b0_request(msg_id, command, params)
            else:
                message = self.build_b0_partial_request(msg_id, msg.hex(" "))
        else:
            message = self.build_std_request(msg_id, msg)
        return message

    def build_powerlink31_message(
        self, msg_id: int, message: str, is_ack: bool = False
    ) -> MessageItem:
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

        msg_initiator = "\n"
        msg_type = "VIS-ACK" if is_ack else "VIS-BBA"

        msg_start = f'"{msg_type}"{msg_id:04}L{self.account}#{self.alarm_serial}['
        msg_end = "]"
        msg_terminator = "\r"

        base_msg = bytearray()
        base_msg.extend(map(ord, msg_start))
        base_msg.extend(bytearray.fromhex(message))
        base_msg.extend(map(ord, msg_end))

        # generate message prefix
        # crc
        crc16 = Crc16Arc.calchex(base_msg)
        msg_length = len(base_msg).to_bytes(2, byteorder="big").hex()

        msg = bytearray()
        msg.extend(map(ord, msg_initiator))
        msg.extend(map(ord, crc16.upper()))
        msg.extend(map(ord, msg_length))
        msg.extend(base_msg)
        msg.extend(map(ord, msg_terminator))

        return MessageItem(msg_id, msg_type, message, msg)

    def build_std_request(self, msg_id: int, command: bytes) -> MessageItem:
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
        message = f"0d {msg} 0a"

        # Now build this command into a powerlink31 message
        return self.build_powerlink31_message(msg_id, message)

    def build_b0_request(
        self, msg_id: int, command: str, params: str = ""
    ) -> MessageItem:
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
        message = f"0d {msg} 0a"

        # Now build this command into a powerlink31 message
        return self.build_powerlink31_message(msg_id, message)

    def build_b0_partial_request(self, msg_id: int, msg: str) -> MessageItem:
        """Wrap b0 full command.

        input message should start b0 and end 43
        """
        checksum = self._calculate_message_checksum(bytes.fromhex(msg))
        msg += f" {checksum.hex()}"
        message = f"0d {msg} 0a"
        # Now build this command into a powerlink31 message
        return self.build_powerlink31_message(msg_id, message)

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
            return f"{cmd} {length:02x} 01 FF 08 FF {no_requests:02x} {params} 00"

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

        if no_configs < 3:
            # Need to have min 3 here and be filled up with 00 00
            bparams = bytearray.fromhex(params)
            bparams.extend([0 for i in range((2 - no_configs) * 2)])
            bparams.extend(bytearray.fromhex("ff ff"))
            params = bparams.hex(" ")
            no_configs = 3

        length = 5 + (no_configs * 2)
        msg = f"{cmd}"
        msg += f" {length:02x}"
        msg += " 02 ff 08 0c"
        msg += f" {no_configs * 2:02x}"  # 2 bytes per config entry
        msg += f" {params}"

        return msg
