"""Specific additional formatters."""

from itertools import batched
import logging
from textwrap import wrap
from typing import Any

from .helpers import (
    b2i,
    chunk_array,
    decode_timestamp,
    get_lookup_value,
    ibit,
    ints_to_datetime,
    ip_formatter,
)
from .refs import (
    EVENTS,
    SYSTEM_STATUS,
    ZONE_TYPES,
    IndexName,
    ZoneBrightness,
    ZoneStatus,
)

_LOGGER = logging.getLogger(__name__)


class B0Formatters:
    """B0 formatters class."""

    # ----------------------------------------------------------------------------------------------
    # B0 command formatters
    # ----------------------------------------------------------------------------------------------

    def format_24(self, data: list[int]) -> dict[str, Any]:
        """Format into dict."""
        dte = ints_to_datetime(data[8:15]).strftime("%Y-%m-%d %H:%M:%S")
        partition_count = data[16]
        partition_data = chunk_array(data[17:], 4)

        sys_status = {}
        for idx, partition in enumerate(partition_data):
            state = partition[0]  # byte 0 is armed status
            sys = partition[1]  # byte 1 of each chunk is sys status

            sys_status.update(
                {
                    idx + 1: {
                        "State": SYSTEM_STATUS[state],
                        "Ready": bool(sys & (0b1 << 0)),
                        "Alarm in Memory": bool(sys & (0b1 << 1)),
                        "Trouble": bool(sys & (0b1 << 2)),
                        "Bypass": bool(sys & (0b1 << 3)),
                        "Last 10 Secs": bool(sys & (0b1 << 4)),
                        "Zone Event": bool(sys & (0b1 << 5)),
                        "Status Changed": bool(sys & (0b1 << 6)),
                        "Partition Active": bool(sys & (0b1 << 7)),
                    }
                }
            )
        return {
            "datetime": dte,
            "partitions": partition_count,
            "states": sys_status,
        }

    def format_2a(self, data: list) -> list[dict[str, Any]]:
        """Decode a 2a standard event log message.

        73 f2 97 66 0c 00 00 32 00 75
        0-3 - datetime
        4 - device type - per IndexName 0c - panel, 09 - plink, 03 - zones
        5 - if device type is zone, zero based zone id
        6 - 0
        7 - event type
        8 - 0
        9 - some sort of sorting id

        Data should be 1 chunk of array with each element as a log entry
        """
        events = []
        try:
            for hex_event in data:
                event = bytearray.fromhex(hex_event)
                date = decode_timestamp(event[:4])
                device_type = event[4]
                zone_id = event[5]
                event_type = event[7]

                device_name = get_lookup_value(IndexName, device_type)
                if device_type == 3:
                    zone_id = zone_id + 1
                event_name = EVENTS[event_type]

                events.append(
                    {
                        "dt": date.strftime("%Y-%m-%d %H:%M:%S"),
                        "device": device_name,
                        "zone": zone_id,
                        "event": event_name,
                    }
                )

            return events
        except IndexError:
            return "Invalid Data"

    def format_2d(self, data: list[int]) -> list[str]:
        """Zone types lookup to ref ZoneTypes."""
        return [ZONE_TYPES[d] for d in data]

    def format_3d(self, data: list[int]) -> list[float]:
        """Format zone temps.

        Each byte is a zone temp based on temp = (value/2) - 40.5 to give 0.5C increments
        A value of FF means no temp available.
        """
        return [(temp / 2) - 40.5 if temp != 255 else 255 for temp in data]

    def format_4b(self, data: list[str]) -> list[float]:
        """Format last zone event.

        Each 5 byte entry is zone with a 4 bytes datetime (reverse timestamp) followed by a 1 byte code
        Codes are
        0 - Not a zone, 1 - Open, 2 - Closed, 3 - Motion, 4 - CheckedIn
        """

        events = []
        for hex_event in data:
            event = bytearray.fromhex(hex_event)
            date = decode_timestamp(event[:4])
            code = get_lookup_value(ZoneStatus, event[4])
            events.append(
                {
                    "datetime": date.strftime("%Y-%m-%d %H:%M:%S"),
                    "code": code,
                }
            )
        return events

    def format_51(self, data: list[int]):
        """Format 51 ask me message into list of hex."""
        return [d.to_bytes(1).hex() for d in data]

    def format_58(self, data: list[str]):
        """Format 58 device info.

        Data is list of hex string.  Each entry is device.

        0 is type ref index
        1 is device type
        2 is zone id
        3 is ?
        4 is if wireless?
        5 is ?
        6 - name
        7 is ?
        8, 9 - first part of enroll id
        10, 11 - second part of enroll id
        12 is ?
        """
        result = {}
        for dev_data in data:
            device = bytes.fromhex(dev_data)
            dev_type = get_lookup_value(IndexName, device[0])
            if not result.get(dev_type):
                result[dev_type] = {}

            dev_id = f"{b2i(device[8:10]):03d}-{b2i(device[10:12]):04d}"
            id_no = device[2]
            wireless = device[4] == 1
            name = device[6]
            result[dev_type][id_no] = {
                "device_id": dev_id,
                "assigned_name_id": name,
                "wireless": wireless,
            }
        return result

    def format_64(self, data: str) -> str:
        """Format panel SW version."""
        return bytearray.fromhex(data).decode("ascii", errors="ignore")

    def format_75(self, data: str) -> str:
        """Format event log.

        Not sure of type of events
        0-3 - datetime
        4 - 7 - not sure
        """
        events = {}
        for zone_id, hex_event in enumerate(data):
            event = bytearray.fromhex(hex_event)
            date = decode_timestamp(event[:4])
            code = event[4:8].hex(" ")
            events[zone_id + 1] = {
                "datetime": date.strftime("%Y-%m-%d %H:%M:%S"),
                "code": code,
            }

        return events

    def format_77(self, data: list[int]) -> list[float]:
        """Format zone brightness.

        Each byte is a zone lux based on 00 = 2 lux, 01 = 7 lux, 02 = 15 lux
        A value of FF means no lux available.
        """
        return [get_lookup_value(ZoneBrightness, lux) for lux in data]

    # ----------------------------------------------------------------------------------------------
    # Command 35 formatters
    # ----------------------------------------------------------------------------------------------

    def format_35_03(self, data: str) -> str:
        """Format IP address."""
        return ip_formatter(data)

    def format_35_04(self, data: str) -> str:
        """Format IP port."""
        return int(int(data) / 10)

    def format_35_05(self, data: str) -> str:
        """Format IP address."""
        return ip_formatter(data)

    def format_35_06(self, data: str) -> str:
        """Format IP port."""
        return int(int(data) / 10)

    def format_35_07(self, data: list[int]) -> list[str]:
        """Is decoded as 1 byte int but is actually 2 byte int.

        Match to IndexName for what each value is.
        """
        _LOGGER.info("35_07DATA: %s", data)
        result = {}
        for i in range(0, len(data), 2):
            result[IndexName(i / 2).name.lower()] = data[i]

        return result

    def format_35_08(self, data: str | list[str]) -> list[str]:
        """Usercodes are 4 bytes each."""
        if isinstance(data, list):
            return data
        return wrap(data, 4)

    def format_35_17(self, data: str) -> str:
        """Format phone number.

        need to strp trailing f's
        """
        return data.rstrip("f")

    def format_35_18(self, data: str) -> str:
        """Format phone number.

        need to strp trailing f's
        """
        return data.rstrip("f")

    def format_35_19(self, data: str) -> str:
        """Format phone number.

        need to strp trailing f's
        """
        return data.rstrip("f")

    def format_35_20(self, data: str) -> str:
        """Format phone number.

        need to strp trailing f's
        """
        return data.rstrip("f")

    def format_35_36(self, data: list[int]) -> float:
        """Format eprom version."""

        return data[1] + (data[0] / 1000)

    def format_35_40(self, data: list[int]) -> list[str]:
        """Is decoded as 1 byte int.

        Match to IndexName for what each value is.
        """
        _LOGGER.info("DATA: %s", data)
        result = {}
        for i in range(0, len(data), 1):
            result[IndexName(i).name.lower()] = data[i]

        return result

    def format_35_49(self, data: str) -> list[str]:
        """Zone types lookup to ref ZoneTypes."""
        return [ZONE_TYPES[d] for d in data]

    def format_35_77(self, data: str | list[str]) -> list[str]:
        """Private reporting tel nos.

        f terminated, need to remove
        """
        if isinstance(data, list):
            return [d.rstrip("f") for d in data]
        return [d.rstrip("f") for d in wrap(data, 16)]

    def format_35_81(self, data: str | list[str]) -> list[str]:
        """SMS Reporting phone numbers.

        F filled strings of 8 bytes each.
        """
        if isinstance(data, list):
            return [n.rstrip("f") for n in data]
        return [n.rstrip("f") for n in wrap(data, 16)]

    def format_35_89(self, data: int | list[int]) -> str:
        """Panic alarm setting.
        bits 2 & 3
        00 - disabled
        01 - silent
        10 - audible
        """
        if ibit(data, 2):
            return "silent"
        if ibit(data, 3):
            return "audible"
        return "disabled"

    def format_35_90(self, data: int) -> str:
        """Quick arm setting."""
        return ibit(data, 4)

    def format_35_91(self, data: int) -> str:
        """Bypass setting   Trouble Beeps
        bits 0 & 1          bits 5 & 6
        00 - no bypass      00 - off
        01 - force arm      01 - off @ night
        10 - manual bypass  11 - on
        """
        result = {}
        # Bypass
        value = "no bypass"
        if ibit(data, 0):
            value = "manual bypass"
        elif ibit(data, 1):
            value = "force arm"
        result["bypass"] = value

        # Trouble beeps
        value = "off"
        if ibit(data, 5):
            value = "on"
        elif ibit(data, 6):
            value = "off at night"
        result["trouble beeps"] = value
        return result

    def format_35_92(self, data: int) -> str:
        """Latch alarm, backlight, quick arm, missing/jamming alarm."""
        return {
            "latch arm": ibit(data, 0),
            "backlight always on": ibit(data, 2),
            "quick arm": ibit(data, 4),
            "miss jam alarm": ibit(data, 7),
        }

    def format_35_93(self, data: int) -> str:
        """Not ready type, keyfob low back ack, memory prompt."""
        return {
            "not ready if missing dev": ibit(data, 3),
            "keyfob low batt ack": ibit(data, 4),
            "memory prompt": ibit(data, 7),
        }

    def format_35_95(self, data: int) -> str:
        """Arming key arm away."""
        return ibit(data, 2)

    def format_35_106(self, data: int) -> str:
        """Trouble beeps and zone pairing."""
        trouble_beeps = "off"
        if ibit(data, 5) and ibit(data, 6):
            trouble_beeps = "on"
        elif ibit(data, 6):
            trouble_beeps = "off at night"

        return {"trouble beeps": trouble_beeps, "zone pairing": ibit(data, 7)}

    def format_35_97(self, data: list[int]) -> str:
        """Duress code. Decodes as list of int but should be direct string"""
        return f"{data[0]:0>2x}{data[1]:0>2x}"

    def format_35_128(self, data: list[int]) -> str:
        """GPRS APN. Decodes as list of int but should be decoded ascii string"""
        return bytearray(data).decode("ascii", errors="ignore")

    def format_35_129(self, data: list[int]) -> str:
        """GPRS User. Decodes as list of int but should be decoded ascii string"""
        return bytearray(data).decode("ascii", errors="ignore")

    def format_35_130(self, data: list[int]) -> str:
        """GPRS Password. Decodes as list of int but should be decoded ascii string"""
        return bytearray(data).decode("ascii", errors="ignore")

    def format_35_138(self, data: list[int]) -> str:
        """CS reporting methods."""
        methods = ["disable", "cellular", "broadband", "PSTN"]
        return [methods[i] for i in data]

    def format_35_139(self, data: int | list[int]) -> str:
        """CS dual reporting."""
        options = [
            "disable",
            "PSTN & broadband",
            "PSTN & cellular",
            "broadband & cellular",
        ]
        return options[data[0] if isinstance(data, list) else data]

    def format_35_164(self, data: list[int]) -> list[str]:
        """Email addresses - presented as 0 temrinated int list.  4 x 40 bytes"""
        return [
            bytearray(d).decode("ascii", errors="ignore").rstrip("\x00")
            for d in batched(data, 40)
        ]

    def format_35_165(self, data: list[int]) -> list[str]:
        """SMS/MMS phone numbers - presented as ff terminated int list.  4 x 8 bytes"""
        return [bytearray(d).hex().rstrip("f") for d in batched(data, 8)]

    def format_35_170(self, data: list[int]) -> str:
        """Alt download code - 2 bytes of int."""
        return bytearray(data).hex()

    def format_35_173(self, data: list[int]) -> list[str]:
        """GPRS Caller IDs - presented as ff terminated int list.  2 x 8 bytes"""
        return [bytearray(d).hex().rstrip("f") for d in batched(data, 8)]

    def format_35_229(self, data: str) -> list[str]:
        """Usercodes are 4 bytes each."""
        return wrap(data, 4)

    def format_35_340(self, data: str) -> dict[str, str] | str:
        """IP, subnet, gateway."""
        return ip_formatter(data)

    # ----------------------------------------------------------------------------------------------
    # Command 42 formatters
    # ----------------------------------------------------------------------------------------------

    def format_42_07(self, data: list[int]) -> list[str]:
        """Match to IndexName for what each value is."""
        result = {}
        for idx, dta in enumerate(data):
            result[IndexName(idx).name.lower()] = dta

        return result

    def format_42_36(self, data: list[int]) -> int:
        """EPROM version to major.minor format"""
        byte_int = int.to_bytes(data[0], 2)
        return byte_int[0] + byte_int[1] / 1000

    def format_42_71(self, data: list[int]) -> bool:
        """Format h24 time setting.  Bit 0 is status."""
        return (data[0] >> 0) & 1 == 1

    def format_42_72(self, data: list[int]) -> bool:
        """US date format setting.  Bit 0 is status."""
        return (data[0] >> 0) & 1 == 0
