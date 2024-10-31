"""Helper functions."""

from dataclasses import dataclass
import datetime as dt
from enum import Enum, StrEnum
from functools import reduce
from itertools import batched
import logging
from textwrap import wrap
from typing import Any

TEXT_UNKNOWN = "UNKNOWN"

_LOGGER = logging.getLogger(__name__)


@dataclass
class VPCommand:
    """Class to hold command to send message queue."""

    cmd: str
    state: bool


def ibit(integer: int | list[int], bit: int, lsb_is_0: bool = False) -> bool:
    """Return value of bit signified by passed in bit position."""
    # Could be passed list with single int (from 42 commands).  In which case
    # use first byte of list
    if isinstance(integer, list):
        integer = integer[0]
    bit = min(bit, 7)
    if lsb_is_0:
        return (integer >> bit) & 1 == 1
    return (integer >> (7 - bit)) & 1 == 1


def b2i(byte: bytes, big_endian: bool = False) -> int:
    """Convert hex to byte."""
    if big_endian:
        return int.from_bytes(byte, "big")
    return int.from_bytes(byte, "little")


def chunk_array(data, size) -> list:
    """Split array into chunk of size."""
    return list(batched(data, size))


def chunk_bytearray(data: bytearray, size: int) -> list[bytes]:
    """Split bytearray into sized chunks."""
    if data:
        return [data[i : i + size] for i in range(0, len(data), size)]


def bits_to_le_bytes(bits: int | list[int], bit_length: int) -> bytes:
    """Convert a list of ints representing bit index to bytes."""
    if not isinstance(bits, list):
        bits = [bits]

    base_data = ["0"] * bit_length
    for d in bits:
        if d > 0 and d <= bit_length:
            base_data[d - 1] = "1"
    data_chunks = chunk_array(base_data[::-1], 8)  # reverse to bit 0 is lsb
    data_bytes = ["".join(bit for bit in data_chunk) for data_chunk in data_chunks]
    int_list = [bytes([int(bits_string, 2)]) for bits_string in data_bytes]
    return b"".join(int_list[::-1])  # reverse to make little endian


def get_lookup_value(lookup_enum: Enum | StrEnum, value: Any) -> str | int:
    """Get key from value for Enum."""
    try:
        return lookup_enum(value).name.lower()
    except ValueError:
        # if isinstance(lookup_enum, Enum):
        #    return None
        pass
    return TEXT_UNKNOWN


def calculate_message_checksum(msg: bytearray) -> bytes:
    """Calculate CRC Checksum."""
    checksum = 0
    for char in msg[0 : len(msg)]:
        checksum += char
    checksum = 0xFF - (checksum % 0xFF)
    if checksum == 0xFF:
        checksum = 0x00
    return checksum.to_bytes(1, "big")


def ip_formatter(data: bytes) -> int:
    """Decode dhcp info.

    string just needs seperating into 3 lots of 4 x 3 chars
    """

    def make_ip(data: str):
        return ".".join([str(int(i)) for i in wrap(data, 3)])

    items = wrap(data, 12)

    if len(items) > 1:
        # This has ip, subnet and gateway
        ip = make_ip(items[0])
        subnet = make_ip(items[1])
        gateway = make_ip(items[2])
        return {"IP": ip, "Subnet": subnet, "Gateway": gateway}
    return make_ip(items[0])


def ints_to_datetime(data: list[int]) -> dt.datetime:
    """Assumes dt is in below format.

    s, m, h, d, mn, y, c
    """
    secs = data[0]
    mins = data[1]
    hour = data[2]
    day = data[3]
    month = data[4]
    year = data[5] + (data[6] * 100)

    return dt.datetime.strptime(
        f"{year}-{month}-{day}T{hour}:{mins}:{secs}", "%Y-%m-%dT%H:%M:%S"
    )


def decode_timestamp(data: bytes) -> dt.datetime:
    """Convert hex timestamp to datetime."""
    ts = data[::-1]
    timestamp = reduce(lambda s, x: s * 256 + x, bytearray(ts))
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc)


def str_to_datetime(dtstring: str) -> dt.datetime:
    """Convert string to datetime."""
    return dt.datetime.strptime(dtstring, "%Y-%m-%d %H:%M:%S")


def str_datetime_diff(dtstring1: str, dtstring2: str) -> int:
    """Return absolute total seconds between 2 timestamps."""
    try:
        dt1 = str_to_datetime(dtstring1)
        dt2 = str_to_datetime(dtstring2)
        response = abs((dt1 - dt2).total_seconds())
    except TypeError:
        response = 0
    return response


def partition_int_to_list_ids(partitions: int) -> list[int]:
    """Convert int representing partitions ids to list of ids."""
    binary = f"{partitions:08b}"
    return [idx + 1 for idx, ones in enumerate(binary[::-1]) if ones == "1"]
