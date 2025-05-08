"""B0 Message Decoding."""

from dataclasses import dataclass, field
import logging
from textwrap import wrap
from typing import Any

from .b0_formatters import B0Formatters
from .helpers import b2i, calculate_message_checksum, chunk_bytearray
from .refs import DataType, IndexName, MessageType

_LOGGER = logging.getLogger(__name__)


class InvalidMessageException(Exception):
    """Invalid message exception."""


@dataclass
class B0DataChunk:
    """Data chunk."""

    data_type: int
    index: int
    length: int
    raw_data: bytes


@dataclass
class B0Structure:
    """Decoded message structure."""

    start: int
    msg_class: str
    msg_type: int
    cmd: str
    length: int
    page: int = 0
    data_type: int = 0
    index: int = 255
    param_size: int = 0
    has_params: bool = False
    data_length: int = 0
    raw_data: bytes | list[B0DataChunk] = b""
    decoded_data: str | int | list[str] | None = None


@dataclass
class B0Message:
    """Class to hold B0 message info."""

    msg_type: int
    cmd: str
    setting: int = 0
    page: int = 0
    data: dict = field(default_factory={})
    raw_data: bytes | None = None


class B0Decoder:
    """B0 Message Decoder."""

    def decode(self, data: bytes) -> B0Message:
        """Decode b0 message."""
        # Decode structure
        try:
            struct = self.decode_structure(data)
        except InvalidMessageException as ex:
            _LOGGER.info("INVALID MESSAGE: %s", data.hex(" "))
            return {"Invalid Message": ex}

        # Format resulting data
        if struct.msg_type in [MessageType.RESPONSE, MessageType.PAGED_RESPONSE]:
            if struct.cmd == "35":
                setting, decoded_format = self.format_35_data(struct.raw_data)
                formatted = self.call_specific_formatter("35", setting, decoded_format)
                result = B0Message(
                    struct.msg_type,
                    struct.cmd,
                    setting,
                    struct.page,
                    formatted,
                    decoded_format,
                )
            elif struct.cmd == "42":
                setting, decoded_format = self.format_42_data(struct.raw_data)

                formatted = []
                if formatter := self.get_specific_formatter(["42", "35"], setting):
                    # if list of lists, process each list through formatter
                    if isinstance(decoded_format, list) and any(
                        isinstance(le, list) for le in decoded_format
                    ):
                        for data_item in decoded_format:
                            format_result = getattr(B0Formatters(), formatter)(
                                data_item
                            )
                            if (
                                isinstance(format_result, list)
                                and len(format_result) == 1
                            ):
                                format_result = format_result[0]
                            formatted.append(format_result)
                    else:
                        format_result = getattr(B0Formatters(), formatter)(
                            decoded_format
                        )
                        if isinstance(format_result, list) and len(format_result) == 1:
                            format_result = format_result[0]
                        formatted.append(format_result)
                else:
                    formatted = decoded_format

                if isinstance(formatted, list) and len(formatted) == 1:
                    formatted = formatted[0]

                result = B0Message(
                    struct.msg_type,
                    struct.cmd,
                    setting,
                    struct.page,
                    formatted,
                    decoded_format,
                )
            elif isinstance(struct.raw_data, list):
                # This is a chunked message and we need to iterate each chunk
                decoded_format = {}
                for chunk in struct.raw_data:
                    decoded_format[IndexName(chunk.index).name.lower()] = (
                        self.format_data(struct.cmd, chunk.data_type, chunk.raw_data)
                    )

                # Now translate data
                specific_formatter_func = f"format_{struct.cmd}"
                if hasattr(B0Formatters(), specific_formatter_func):
                    formatted_data = {}
                    for idx, d in decoded_format.items():
                        formatted_data[idx] = getattr(
                            B0Formatters(), specific_formatter_func
                        )(d)
                else:
                    formatted_data = decoded_format

                result = B0Message(
                    struct.msg_type,
                    struct.cmd,
                    0,
                    struct.page,
                    formatted_data,
                    decoded_format,
                )
            else:
                # This is just straight data.  Decode as per data type.
                decoded_format = self.format_data(
                    struct.cmd, struct.data_type, struct.raw_data
                )
                specific_formatter_func = f"format_{struct.cmd}"
                formatted_data = (
                    getattr(B0Formatters(), specific_formatter_func)(decoded_format)
                    if hasattr(B0Formatters(), specific_formatter_func)
                    else decoded_format
                )
                result = B0Message(
                    struct.msg_type,
                    struct.cmd,
                    0,
                    struct.page,
                    formatted_data,
                    decoded_format,
                )
        else:
            decoded_format = self.format_data(
                struct.cmd, struct.data_type, struct.raw_data
            )
            result = B0Message(
                struct.msg_type,
                struct.cmd,
                0,
                struct.page,
                decoded_format,
                struct.raw_data,
            )

        return result

    def decode_structure(self, data: bytes) -> B0Structure:
        """Decode b0 structure."""
        # These are consistant across all b0 messages
        # _LOGGER.info("DEC: %s", data.hex(" "))
        msg_start = data[0]
        msg_class = data[1]
        msg_type = data[2]
        cmd = data[3]
        length = data[4]
        checksum = data[-2]
        msg_end = data[-1]

        # Validate message start, end and class
        if not (msg_start == 0x0D and msg_end == 0x0A and msg_class == 0xB0):
            raise InvalidMessageException("invalid start and end")

        # validate checksum
        if b2i(calculate_message_checksum(data[1:-2])) != checksum:
            raise InvalidMessageException("invalid checksum")

        msg_struct = B0Structure(
            start=msg_start,
            msg_class=msg_class.to_bytes().hex(),
            msg_type=msg_type,
            cmd=cmd.to_bytes().hex(),
            length=length,
        )

        msg_data = data[5 : 5 + length]

        if msg_type in [MessageType.ADD, MessageType.REMOVE]:
            # These 2 message types contain the download code in bytes 5 & 6
            # Only so far seen a b0 00/04 19/25 messages to set/unset bypass, enroll/unenroll sensor
            # 0d b0 00 19 0f aa aa 00 ff 01 03 08 02 00 00 00 00 00 00 00 43 80 0a
            # 0d b0 04 19 0f aa aa 00 ff 01 03 08 01 00 00 00 00 00 00 00 43 7d 0a
            # 0d b0 00 25 10 aa aa 01 ff 08 ff 09 31 34 30 35 30 31 39 07 00 43 03 0a
            # 0d b0 04 25 09 aa aa 01 ff 08 03 02 08 00 43 6e 0a
            # download_code = msg_data[0:2].hex()
            msg_struct.page = data[8]
            msg_struct.data_type = msg_data[9]
            msg_struct.index = msg_data[10]
            data_length = msg_data[11]
            msg_struct.data_length = data_length
            msg_struct.raw_data = msg_data[12 : 12 + data_length]

        if msg_type == MessageType.REQUEST:
            # This can have 2 forms.  A request with or without parameters.
            # If the request does have parameters (ie 35 or 42 message), it looks like this.
            # 0d b0 01 35 0d 02 ff 08 ff 08 0f 00 55 00 54 00 06 01 43 f6 0a
            # byte 6 is the size of each parameter, 7 page, 8 data type, 9 index,
            # 10 data size, 11 onward is data

            # If no parameters, it looks like this
            # 0d b0 01 07 01 05 43 fd 0a
            # byte 5 is data but this doesn't seem to mean anythying other than no data
            # _LOGGER.info("DATA: %s", data.hex(" "))
            if data[6] == 255:
                # This has parameters
                msg_struct.has_params = True
                msg_struct.param_size = data[5]
                msg_struct.page = data[6]
                msg_struct.data_type = data[7]
                msg_struct.index = data[8]
                data_length = data[9]
                msg_struct.data_length = data_length
                msg_struct.raw_data = data[10 : 10 + data_length]
            else:
                msg_struct.raw_data = data[5]

        if msg_type in [MessageType.PAGED_RESPONSE, MessageType.RESPONSE]:
            # These 2 message types are the same, except that a PAGED_RESPONSE(02) is only a
            # part message in that the rest of the data will come in a later RESPONSE(03) message.
            # There are 2 main formats, those with 1 data element and those with multiple
            # elements (chunked) data where the index relates to the category of that data.
            # See IndexName enum.

            # Non chunked example without params
            # 0d b0 03 22 2f ff 10 ff 2a 08 00 0f 00 08 00 40 00 20 00 ... 57 43 f9 0a
            # bytes 5 is page, 6 data type, 7 index, 8 data length, 9 to data length is data

            # Non chunked example with params
            # 0d b0 03 35 0a ff 08 ff 05 4b 00 04 0c 00 05 43 5c 0a
            # byte 5 is page, 6 data type, 7 index, 8 data length, 9 to data length is
            # data (first 2 bytes of data is param)

            # Chunked example without params (not seen a chunked example with params)
            # 0d b0 03 01 5e ff 08 00 04 07 07 07 07 ff 08 01 0f 06 06 ... 24 43 3a 0a
            # bytes 5 is page, 6 is data type, 7 index, 8 data length (for chunk), 9 to data
            # length is data.  As next bytes is ff, repeats as per byte 6 onward.

            # 03, 0F - Anomoloy
            # 0d b0 03 03 03 19 07 ce 43 14 0a
            # 0d b0 03 0f 0b 19 07 0f 00 00 01 00 01 00 81 97 43 a4 0a

            # 06 - Anomoly
            # 0d b0 03 06 02 02 05 43 f9 0a

            # Response and Paged Response messages have a counter in the last byte of the data
            # (defined by data length), so we subtract 1 from length for raw_data
            if msg_struct.msg_type == MessageType.RESPONSE and data[5] == 0x19:
                # Commands 03, 0f
                msg_struct.data_type = 8
                msg_struct.index = 255
                data_length = length - 1
                msg_struct.data_length = data_length
                msg_struct.raw_data = data[5 : 5 + data_length]
            elif cmd == 0x06:
                # Command 06 - invalid request response
                msg_struct.data_type = 8
                msg_struct.index = 255
                data_length = data[4]
                msg_struct.data_length = data_length
                msg_struct.raw_data = data[5 : 5 + data_length]
            else:
                msg_struct.page = data[5]
                data_type = data[6]

                if data_type == 0:
                    # actual data type is in 8 & 9 as little endian int - ie cmd 64
                    # 0d b0 03 64 18 ff 00 ff 13 00 ff 10 4a 53 37 30 33 36 ... 34 6c 43 96 0a
                    msg_struct.data_type = b2i(data[8:10], big_endian=False)
                    msg_struct.index = data[10]
                    data_length = data[11]
                    msg_struct.data_length = data_length
                    msg_struct.raw_data = data[12 : 12 + data_length]
                else:
                    msg_struct.data_type = data_type
                    index = data[7]
                    if index != 0xFF:
                        # This is chunked data
                        data_length = -1  # Denotes data is in chunks in raw data
                        msg_struct.raw_data = self.chunk_data(
                            data[6:-4]
                        )  # Take last 4 bytes off (counter, end data, checksum , end message)
                    else:
                        data_length = data[8]
                        msg_struct.data_length = data_length
                        if data_length == 0:
                            msg_struct.raw_data = b""
                        else:
                            msg_struct.raw_data = data[9 : 9 + data_length]

        if msg_type == MessageType.UNKNOWN:
            # I have only seen this 05 message type very rarely and do not have an example.
            # For now, we just ignore it.
            pass

        return msg_struct

    def chunk_data(self, data: bytes) -> list[B0DataChunk]:
        """Split chunked data in list of B0DataChunks."""
        result = []
        i = 0
        while i <= len(data) - 1:
            chunk_data_length = data[i + 2]
            result.append(
                B0DataChunk(
                    data_type=data[i],
                    index=data[i + 1],
                    length=chunk_data_length,
                    raw_data=data[i + 3 : i + 3 + chunk_data_length],
                )
            )
            i = i + 4 + chunk_data_length
        # _LOGGER.info(result)
        return result

    def format_data(
        self, command: str, data_type: int, data: bytes
    ) -> str | int | list[str | int]:
        """Format data."""

        if data_type == 1:
            # bits
            result = []
            for b in data:
                bits = list(f"{b:08b}")
                bits.reverse()
                result.extend(bits)
            result = [int(i) for i in result]
        elif data_type == 8:
            result = [b2i(data[i : i + 1]) for i in range(0, len(data), 1)]
        elif data_type == 16:
            result = [
                b2i(data[i : i + 2], big_endian=False) for i in range(0, len(data), 2)
            ]
        elif data_type > 16 and data_type != 19:
            size = int(data_type / 8)
            result = [data[i : i + size].hex(" ") for i in range(0, len(data), size)]
        else:
            result = data.hex(" ")

        return result

    def format_35_data(self, data: bytes) -> tuple[int, str | int | list[str | int]]:
        """Format a command 35 message.

        This has many parameter options to retrieve EPROM settings.
        bytes 0 & 1 are the parameter
        bytes 2 is the data type
        bytes 3 to length (-3) is data
        """
        setting = b2i(data[0:2], big_endian=False)
        decoded_format = self.settings_data_type_formatter(data[2], data[3:])
        return setting, decoded_format

    def format_42_data(self, data: bytes) -> tuple[int, str | int | list[str | int]]:
        """Format a command 42 message.

        This has many parameter options to retrieve EPROM settings.
        bytes 0 & 1 are the parameter
        bytes 2 & 3 is the max number of data items
        bytes 4 & 5 is the size of each data item
        bytes 6 & 7 - don't know
        bytes 8 & 9 is the data type
        bytes 10 & 11 is the start index of data item
        bytes 12 & 13 is the number of data items
        bytes 14 to end is data
        """
        setting = b2i(data[0:2], big_endian=False)
        # max_data_items = b2i(data[2:4], big_endian=False)
        data_item_size = max(1, int(b2i(data[4:6], big_endian=False) / 8))
        data_type = data[8]  # This is actually 2 bytes, what is second byte??
        byte_size = 2 if data[9] == 0 else 1
        # start_entry = b2i(data[10:12], big_endian=False)
        # entries = b2i(data[12:14], big_endian=False)

        # Split into entries
        data_items = chunk_bytearray(data[14:], data_item_size)
        decoded_format = []
        if data_items:
            for data_item in data_items:
                # Convert to correct data type
                decoded_format.append(  # noqa: PERF401
                    self.settings_42_data_type_formatter(
                        data_type, data_item, byte_size=byte_size
                    )
                )

        if len(decoded_format) == 1:
            return setting, decoded_format[0]
        return setting, decoded_format

    def get_specific_formatter(
        self, command: str | list[str], setting: int | None = None
    ) -> str:
        """Get function name of specific formatter."""
        for cmd in command:
            if setting:
                func = f"format_{cmd}_{setting:02d}"
            else:
                func = f"format_{cmd}"

            if hasattr(B0Formatters(), func):
                return func
        return None

    def call_specific_formatter(
        self, command: str | list[str], setting: int | None = None, data: Any = None
    ) -> Any:
        """Pass data through specific formatter and return result.

        Allows for a list of commands to look for a common formatter but
        will only call the first match in the list.
        If no match, it returns passed data
        """
        if not isinstance(command, list):
            command = [command]

        for cmd in command:
            if setting:
                func = f"format_{cmd}_{setting:02d}"
            else:
                func = f"format_{cmd}"
            try:
                if hasattr(B0Formatters(), func):
                    return getattr(B0Formatters(), func)(data)
            except (ValueError, TypeError):
                return None
        return data

    def settings_42_data_type_formatter(
        self, data_type: int, data: bytes, byte_size: int = 1
    ) -> int | str | bytearray:
        """Preformatter for settings 42."""
        if data_type == DataType.SPACE_PADDED_STRING_LIST:
            # Remove any \x00 also when decoding.
            # On 42 46 00 strings are \n terminated
            name = data.decode("ascii", errors="ignore")
            return name.replace("\x00", "").rstrip("\n").rstrip(" ")
        return self.settings_data_type_formatter(data_type, data, byte_size=byte_size)

    def settings_data_type_formatter(
        self, data_type: int, data: bytes, string_size: int = 16, byte_size: int = 1
    ) -> int | str | bytearray:
        """Format data for 35 and 42 data."""
        if data_type == DataType.ZERO_PADDED_STRING:  # \x00 padded string
            return data.decode("ascii", errors="ignore").rstrip("\x00")
        if data_type == DataType.DIRECT_MAP_STRING:  # Direct map to string
            return data.hex()
        if data_type == DataType.FF_PADDED_STRING:
            return data.hex().replace("ff", "")
        if data_type == DataType.DOUBLE_LE_INT:  # 2 byte int
            return (
                [b2i(data[i : i + 2], False) for i in range(0, len(data), 2)]
                if len(data) > 2
                else b2i(data[0:2], False)
            )
        if data_type == DataType.INTEGER:  # 1 byte int?
            if len(data) == byte_size:
                return b2i(data)
            # Assume 1 byte int list
            return [
                b2i(data[i : i + byte_size]) for i in range(0, len(data), byte_size)
            ]
        if data_type == DataType.STRING:
            return data.decode("ascii", errors="ignore")
        if data_type == DataType.SPACE_PADDED_STRING:  # Space padded string
            return data.decode("ascii", errors="ignore").rstrip(" ")
        if (
            data_type == DataType.SPACE_PADDED_STRING_LIST
        ):  # Space paddeded string list - seems all 16 chars
            # Cmd 35 0d 00 can include a \x00 instead of \x20 (space)
            # Remove any \x00 also when decoding.
            names = wrap(data.decode("ascii", errors="ignore"), string_size)
            if names and len(names) == 1:
                return names[0].replace("\x00", "").rstrip(" ")
            return [
                name.replace("\x00", "").rstrip(" ") for name in names if name != ""
            ]
        return data.hex(" ")
