"""Reference lookups."""

import collections
from enum import IntEnum, StrEnum

DEFAULT_DOWNLOAD_CODE = "aaaa"


class MessageClass(StrEnum):
    """Message classes."""

    B0 = "b0"
    E0 = "e0"
    STD = "std"


class MessageType(IntEnum):
    """Message type."""

    ADD = 0
    REQUEST = 1
    PAGED_RESPONSE = 2
    RESPONSE = 3
    REMOVE = 4
    UNKNOWN = 5


class DataType(IntEnum):
    """Command 35 Message data data types."""

    ZERO_PADDED_STRING = 0
    DIRECT_MAP_STRING = 1
    FF_PADDED_STRING = 2
    DOUBLE_LE_INT = 3
    INTEGER = 4
    STRING = 6
    SPACE_PADDED_STRING = 8
    SPACE_PADDED_STRING_LIST = 10


class ArmModes(IntEnum):
    """Arm mode command codes."""

    DISARM = 0x00
    EXIT_DELAY_ARM_HOME = 0x01
    EXIT_DELAY_ARM_AWAY = 0x02
    ENTRY_DELAY = 0x03
    ARM_HOME = 0x04
    ARM_AWAY = 0x05
    WALK_TEST = 0x06
    USER_TEST = 0x07
    ARM_INSTANT_HOME = 0x14
    ARM_INSTANT_AWAY = 0x15


class B0CommandName(StrEnum):
    """B0 Message command."""

    WIRELESS_DEVICES_00 = "00"  # bits relate to bit 7 of devices (58)
    WIRELESS_DEVICES_01 = "01"  # Investigate more
    WIRELESS_DEVICE_UPDATING = "02"  # Investigate more
    PANEL_TYPE = "03"  # Returns [25,7] on PM10, [25,8] on PM30
    WIRELESS_DEVICE_CHANNEL = "04"
    WIRELESS_DEVICES_05 = "05"  # Investigate more
    INVALID_COMMAND = "06"
    ZONES_07 = "07"  # Investigate more
    WIRELESS_DEVICES_08 = "08"
    WIRELESS_DEVICES_09 = "09"
    TAMPER_ACTIVES = "0a"
    TAMPER_ALERTS = "0b"
    WIRELESS_DEVICES_0C = "0c"
    WIRELESS_DEVICES_0D = "0d"
    WIRELESS_DEVICES_0E = "0e"
    STATUS = "0f"  # Investigate more
    # 10 is invalid command
    # 11 - 16 all return 64 bits of 0 - Zone related?
    ZONES_11 = "11"
    ZONES_12 = "12"
    TRIGGERED_ZONE = "13"
    ZONES_14 = "14"
    ZONES_15 = "15"
    ZONES_16 = "16"
    REQUEST_LIST = "17"  # with params, alarm sends list of responses.  Without params, sends list of 59, 0f, 11-16, 51-58, 5b, 62, 64, 66, 69, 6d, 6e, 71, 75-77, 7a-7c.
    SENSOR_DETECTION = (
        "18"  # shows for contact and moition - prob others bit = 1 if active, 0 if not
    )
    BYPASSES = "19"
    ZONES_1A = "1a"
    ZONES_1B = "1b"
    ZONES_1C = "1c"
    ENROLLED = "1d"  # Seems to have a 1 bit for each enrolled device
    ZONES_1E = "1e"
    DEVICE_TYPES = "1f"
    ASSIGNED_PARTITION = "20"  # Partition id is bit ie 7 = 0111
    ASSIGNED_NAMES = "21"
    SYSTEM_CAPABILITIES = "22"  # This gives wrong values.  Use 35 07 00
    UNKNOWN_23 = "23"  # PM10 returned 19 bytes all 0
    PANEL_STATUS = "24"
    UNKNOWN_25 = "25"  # PM 30 returned 1 byte - 0, PM 10 return 1 byte - 9
    # 26 invalid
    WIRED_DEVICES_STATUS = "27"  # Can send 00 and 04 to turn on/off with download code - on 0d b0 00 27 09 aa aa 11 ff 08 0b 02 01 00 43 5f 0a, off - 0d b0 00 27 09 aa aa 10 ff 08 0b 02 01 00 43 60 0a - see 7a for timed on
    WIRED_DEVICES_SOMETHING_28 = "28"
    UNKNOWN_29 = "29"  # PM10/30 returned [0, 0, 64, 96, 144, 176, 184, 188, 205, 206, 238, 188, 246]
    STANDARD_EVENT_LOG = "2a"  # Sends 58 pages of data! With 1000, 10 byte entries
    TYPE_OFFSETS = "2b"  # PM10 and PM30 returned same - [2097, 1617, 2049, 1, 1793, 1281, 1281, 2129, 2166, 2168, 1281, 2129, 0, 2169, 0, 0, 0, 0, 2176, 2177]
    # 2c is invalid command
    ASSIGNED_ZONE_TYPES = "2d"
    SENSORS_SOMETHING = "2e"
    ZONES_2F = "2f"
    ZONES_30 = "30"
    ZONES_31 = "31"
    ZONES_32 = "32"
    ZONES_33 = "33"
    ZONES_34 = "34"
    SETTINGS_35 = "35"  # Needs a parameter for the setting Command35Settings
    LEGACY_EVENT_LOG = "36"
    SOME_EVENT37 = "37"  # Seems to be 1 event - last/alarm/trouble??  0c 00 93 9e 7d 66 - as of 8/7/24 - still same - shows 27/06/2024 17:17:07
    SOMETHING_38 = "38"  # Investigate 3 x 4 bytes
    ASK_ME2 = "39"
    ZONES_3A = "3a"  # Some zone info in bits
    # 3b, 3c are invalid
    ZONE_TEMPS = "3d"
    SIREN_CONTROL = "3e"  # Only seems to be a 00 type message ie 0d b0 00 3e 0a 31 80 05 ff 08 02 03 00 00 01 43 fe 0a sounds siren 0.  Could also control other things as 02 is siren index
    # 3f - invalid
    WIRELESS_DEVICES_40 = "40"  # Some zone info - has data for each zone in use 04 (04 06 for 1&2 on PM10)
    # 41 gets no response
    SETTINGS_42 = "42"  # Need a parameter for the setting - see b0_42_command.py
    ZONES_43 = "43"  # Some zone info in 64 bits - all 0.  PM10 no response
    # 44 - 47 invalid
    UNKNOWN_48 = "48"  # PM10 returned [255, 0, 0, 0, 0, 0]
    ZONES_49 = "49"  # PM30 - 64 bytes all 00, PM10 - 30 bytes all 00
    # 4a invalid
    ZONE_LAST_EVENT = "4b"
    # 4c, 4d invalid
    SOAK_TEST_ZONES = "4e"
    ZONES_4F = "4f"  # some zone info in 64 bits - all 0
    ZONES_50 = "50"  # some zone info in 2 byte words - all 0
    ASK_ME = "51"
    PANEL_INFO = "52"  # Gives [25,7,0,2,0,1] on PM10, [25,8,0,2,0,1] on PM30
    WIRED_DEVICES_SOMETHING_53 = "53"
    TROUBLES = "54"
    REPEATERS_SOMETHING_55 = "55"
    UNKNOWN_56 = "56"  # PM10/30 returned [3, 0, 2, 2, 6, 0, 0]
    UNKNOWN_57 = "57"
    DEVICE_INFO = "58"
    GSM_STATUS = "59"
    # 5a invalid
    KEYPADS = "5b"
    # 5c, 5d, 5e, 5f, 60, 61 invalid
    UNKNOWN_62 = "62"  # PM10/30 returned [100]
    # 63 invalid
    PANEL_SOFTWARE_VERSION = "64"
    # 65 invalid
    SIRENS = "66"
    # 67, 68 invalid
    PANEL_EPROM_AND_SW_VERSION = "69"  # PM10 gave invalid
    KEEP_ALIVE = "6a"
    # 6b 6c 6d invalid
    UNKNOWN_6E = "6e"  # PM10/30 return ['01 00 00'] even with 2 active partitions
    # 6f, 70 invalid
    PANEL_SOMETHING_71 = "71"  # PM10/30 returned single byte - 02
    # 72, 73, 74 invalid
    SOME_LOG_75 = "75"
    IOVS = "76"
    ZONE_BRIGHTNESS = "77"
    # 78, 79 invalid
    TIMED_PGM_COMMAND = "7a"  # for sending PGM on for timed period (secs) - 0d b0 00 7a 0b 31 80 01 ff 20 0b 04 00 01 3c 00 43 67 0a
    ZONES_7B = "7b"
    ZONES_7C = "7c"
    # invalid above 7d
    # not tested above 9f


class Command35Settings(IntEnum):
    """Command 35 settings."""

    COMMS_CS_REC1_ACCT = 0  # 00 00
    COMMS_CS_REC2_ACCT = 1  # 01 00
    PANEL_SERIAL_NO = 2  # 02 00
    COMMS_CS_REC1_IP = 3  # 03 00"
    COMMS_CS_REC1_PORT = 4  # "04 00"
    COMMS_CS_REC2_IP = 5  # "05 00"
    COMMS_CS_REC2_PORT = 6  # "06 00"
    CAPABILITIES_DOUBLE = 7  # "07 00"
    USER_CODES = 8  # "08 00"
    ZONE_NAMES = 13  # "0d 00"
    MY_SIM_TELNO = 14  # 0e 00
    DOWNLOAD_CODE = 15  # "0f 00"
    UNKOWN16 = 16  # 10 00 - value 0
    SMS_MMS_BY_SERVER_TEL1 = 17  # 11 00
    SMS_MMS_BY_SERVER_TEL2 = 18  # 12 00
    SMS_MMS_BY_SERVER_TEL3 = 19  # 13 00
    SMS_MMS_BY_SERVER_TEL4 = 20  # 14 00
    EMAIL_BY_SERVER_EMAIL1 = 21  # 15 00
    EMAIL_BY_SERVER_EMAIL2 = 22  # 16 00
    EMAIL_BY_SERVER_EMAIL3 = 23  # 17 00
    EMAIL_BY_SERVER_EMAIL4 = 24  # 18 00
    SOME_SETTINGS25 = 25  # 19 00 - value 01 00 00 ff 0f 00 00 00 00 00 01 01 00 00 00
    PANEL_EPROM_VERSION = 36  # 24 00 - ae 08 = 8.174
    TYPE_OFFSETS = 39  # 27 00 - no idea what this means!
    CAPABILITIES = 40  # 28 00
    UNKNOWN_SOFTWARE_VERSION = 43  # 2b 00 - JS700421 v1.0.02
    PANEL_DEFAULT_VERSION = 44  # 2c 00
    PANEL_SOFTWARE_VERSION = 45  # 2d 00
    PARTITIONS_ENABLED = 48  # 30 00
    ASSIGNED_ZONE_TYPES = 49  # 31 00
    ASSIGNED_ZONE_NAMES = 50  # 32 00
    ZONE_CHIME = 51  # 33 00
    MAP_VALUE = 52  # 34 00 - Not sure what this is but returns MAP08
    MAP_VALUE_2 = 53  # 35 00 - Not sure what this is but returns MAP08
    ZONE_PARTITION_ASSIGNMENT = (
        54  # 36 00 - What partition, sensor/zone is assigned to - can be multiple.
    )
    TAG_PARTITION_ASSIGNMENT = 55  # 37 00 - Not sure. All 0x01's but 32 bytes. keypads/tags? 42 37 00 on PM10 shows 8
    KEYPAD_PARTITION_ASSIGNMENT = 56  # 38 00
    SIREN_PARTITION_ASSIGNMENT = 57  # 39 00 - Not sure as all 0x01's but 8 bytes - sirens? But I have a wireless one. 42 39 00 on PM10 shows 4
    PANEL_HARDWARE_VERSION = 60  # "3c 00"
    PANEL_RSU_VERSION = 61  # "3d 00"
    PANEL_BOOT_VERSION = 62  # "3e 00"
    CUSTOM_ZONE_NAMES = 66  # "42 00"
    ZONE_NAMES2 = 69  # "45 00"
    CUSTOM_ZONE_NAMES2 = 70  # "46 00"
    H24_TIME_FORMAT = 71  # "47 00"
    US_DATE_FORMAT = 72  # "48 00"
    PRIVATE_REPORTING_TELNOS = 77  # 4d 00
    MAX_PARTITIONS = 78  # 4e 00 - THINK- NEEDS CHECKING SHOWS 03
    SMS_REPORT_NUMBERS = 81  # 51 00
    INSTALLER_CODE = 84  # 54 00
    MASTER_CODE = 85  # 55 00
    GUARD_CODE = 86  # 56 00
    EN50131_EXIT_DELAYS = 87  # 57 00
    EXIT_DELAY = 88  # 58 00
    PANIC_ALARM = 89  # 59 00
    QUICK_ARM = 90  # 5a 00
    BYPASS_AND_TROUBLE_BEEPS = 91  # 5b 00
    LATCHARM_BLGHT_QUICKARM_JAMALARM = 92  # 5c 00
    NOTREADY_KEYFOBBATT_MEMPROMPT = 93  # 5d 00
    ZONE_REARM = 94  # 5e 00
    ARMINGKEY_ARMAWAY = 95  # 5f 00
    DURESS_CODE = 97  # 61 00
    INACTIVE_ALERT = 98  # 62 00
    AC_FAILURE_REPORT = 100  # 64 00
    EN50131_CONFIRM_ALARM_TIMER = 101  # 65 00
    RESET_OPTION = 104  # 68 00
    ABORT_FIRE_TIME = 105  # 69 00
    ZONE_PAIRING_AND_PANEL_SIREN = 106  # 6a 00
    SIREN_TIME = 107  # 6b 00
    STROBE_TIME = 108  # 6c 00
    EXIT_MODE = 109  # 6d 00
    PIEZO_BEEPS = 110  # 6e 00
    SCREEN_SAVER = 115  # 73 00
    JAMMING_DETECTION = 116  # 74 00
    MISSING_REPORT = 117  # 75 00
    USER_PERMIT = 120  # 78 00
    COMMS_GPRS_APN = 128  # 80 00
    COMMS_GPRS_USER = 129  # 81 00
    COMMS_GPRS_PWD = 130  # 82 00
    CS_REPORTING_METHODS = 138  # 8a 00
    CS_DUAL_REPORTING = 139  # 8b 00
    COMMS_CS_REC1_TELNO = 140  # 8c 00
    COMMS_CS_REC2_TELNO = 141  # 8d 00
    COMMS_CS_REC12_SMS = 142  # 8e 00
    TAMPER_ALARM = 152  # 98 00
    EMAIL_BY_SERVER_ADDRESSES = 164  # a4 00
    SMS_MMS_BY_SERVER_NUMBERS = 165  # a5 00
    VIEW_ON_DEMAND = 166  # a6 00
    VIEW_ON_DEMAND_TIME_WINDOW = 167  # a7 00
    ALT_DOWNLOAD_CODE = 170  # aa 00
    SIREN_ONLINE = 171  # ab 00
    GPRS_CALLER_IDS = 173  # ad 00
    DHCP_MODE = 174  # ae 00
    POWERLINK_IP = 175  # af 00
    POWERLINK_SUBNET = 176  # b0 00
    POWERLINK_GATEWAY = 177  # b1 00
    SECURITY_STD_MODE = 183  # b7 00
    BS8243_RPT_CONFIRM_ALARM = 190  # be 00
    EXIT_DELAYS = 191  # bf 00
    DD243_RPT_CONFIRM_ALARM = 198  # c6 00
    DD243_ENTRY_DELAYS = 199  # c7 00
    USER_PARTITION_ACCESS = 226  # e2 00 - byte per user, partition id is bit
    KEYPAD_PARTITION_ASSIGNMENT2 = 228  # e4 00
    USER_CODES2 = 229  # e5 00
    PANEL_LANGUAGE = 232  # e8 00
    ACCEPTED_CHARS_UPPER = 233  # e9 00
    ACCEPTED_CHARS_LOWER = 234  # ea 00
    INVESTIGATE_MORE = 235  # eb 00 - looks zone related but not sure
    SOAK_PERIOD = 255  # ff 00
    SMOKE_FAST_MISSING = 259  # 03 01
    DD243_CANCEL_ALARM = 273  # 11 01
    POWERLINK_SW_VERSION = 277  # "15 01"
    EMAIL_REPORTED_EVENTS = 280  # "18 01"  # alarm, alert, trouble, open/close - 4 bytes, 1 for each of 4 email addresses
    SMS_REPORTED_EVENTS = 281  # 19 01 - alarm, alert, trouble, open/close - 4 bytes, 1 for each of 4 tel nos.
    MMS_REPORTED_EVENTS = 282  # 1a 01 - alarm, alert, trouble, open/close - 4 bytes, 1 for each of 4 tel nos.
    TECHNIST_CODE_VERSION = 304  # 30 01
    UNKNOWN_SW_VERSION = 306  # 32 01
    PIEZO_BEEPS2 = 307  # 33 01
    TROUBLES = 336  # 50 01 - Seems to be trouble/alert texts for panel
    INDEX_NAMES = 337  # 51 01
    DHCP_IP = 340  # 54 01
    KIDS_COME_HOME = 347  # 5b 01
    ENABLE_API = 368  # 70 01
    PANEL_SERIAL = 369  # 71 01
    HOME_AUTOMATION_SERVICE = 371  # 73 01
    ENABLE_SSH = 372  # 74 01
    SSL_FOR_IPMP = 389  # 85 01
    LOG_EMAIL_SEND_NOW = 391  # 87 01
    UNKNOWN_EMAIL = 393  # 89 01 - msp5.2cpu.visonic@gmail.com
    UNKNOWN_PWD = 394  # 8a 01 - I think! Wer98Ce651dsa093
    DNS_NAME = 397  # 8d 01
    ABORT_TIME = 398  # 8e 01
    ENTRY_DELAY = 399  # 8f 01
    # DO_NOT_USE = 413  # 9d 01 - Alarm goes mad sending 255 pages and then repeats! Drops off and needs repower to reconnect.
    LOG_FTP_SITE = 424  # a8 01 - ftp://Pm360logger.visonic.com:990
    LOG_FTP_UID = 425  # a9 01 - plink360
    LOG_FTP_PWD = 426  # aa 01 - plink360visonic
    # b9 01 and above not valid


class EPROMSetting(StrEnum):
    """Enum for eprom settings."""

    ALARM_LED_PM10 = "alarm_led_pm10"
    ALARM_LED_PM30 = "alarm_led_pm30"
    DISARM_ACTIVITY = "disarm_activity"


EpromSettingInfo = collections.namedtuple("EpromSetting", "position length databits")
EPROMSettingLookup = {
    "alarm_led_pm10": EpromSettingInfo(49250, 64, 16),
    "alarm_led_pm30": EpromSettingInfo(49735, 64, 16),
    "disarm_activity": EpromSettingInfo(49542, 128, 16),
}  # alarm led - 49250 on PM10, 49735 on PM30

VIS_ACK = "VIS-ACK"
VIS_BBA = "VIS-BBA"
ADM_CID = "*ADM-CID"
ADM_ACK = "*ACK"


class ManagedMessages(StrEnum):
    """Messages that get handled in some way."""

    PL_ACK = "0d 02 43 ba 0a"
    ACK = "0d 02 fd 0a"
    DISCONNECT_MESSAGE = "0d ad 0a 00 00 00 00 00 00 00 00 00 43 05 0a"
    HELLO = "0d 06 f9 0a"
    KEEPALIVE = "0d b0 01 6a 00 43 a0 0a"
    DOWNLOAD = "0d 09 f6 0a"  # Alarm does ACK
    STOP = "0d 0b f4 0a"  # Alarm doesnt ACK
    EXIT_DOWNLOAD_MODE = "0d 0f f0 0a"  # Alarm does ACK
    # Don't really know what this is but alarm sends when HA send a STOP
    # message.
    DENIED = "0d 08 f7 0a"
    ENABLE_STEALTH = "e1 02 01"
    DISABLE_STEALTH = "e1 02 00"


class IndexName(IntEnum):
    """Index name.

    This came from b0 35 51 01 on Powermater-10
    """

    REPEATERS = 0
    PANIC_BUTTONS = 1
    SIRENS = 2
    ZONES = 3
    KEYPADS = 4
    KEYFOBS = 5
    USERS = 6
    X10_DEVICES = 7
    GSM_MODULES = 8
    POWERLINK = 9
    TAGS = 10
    PGM = 11
    PANEL = 12
    GUARDS = 13
    EVENTS = 14
    PARTITIONS = 15
    UNK16 = 16
    EXPANDER_33 = 17
    IOV = 18  # IOV is the IO expansion module
    UNK19 = 19
    UNK20 = 20
    NA = 255


class ZoneStatus(IntEnum):
    """Zone status enum."""

    NA = 0
    OPEN = 1
    CLOSED = 2
    MOTION = 3
    CHECKIN = 4


class ZoneBrightness(IntEnum):
    """Zone brightness enum."""

    DARKNESS = 0
    PARTIAL_LIGHT = 1
    DAYLIGHT = 2
    NA = 255


ZONE_TYPES = [
    "Non-Alarm",
    "Emergency",
    "Flood",
    "Gas",
    "Delay 1",
    "Delay 2",
    "Interior-Follow",
    "Perimeter",
    "Perimeter-Follow",
    "24 Hours Silent",
    "24 Hours Audible",
    "Fire",
    "Interior",
    "Home Delay",
    "Temperature",
    "Outdoor",
    "16",
]


class SensorType(IntEnum):
    """Sensor types enum."""

    IGNORED = -2
    UNKNOWN = -1
    MOTION = 0
    MAGNET = 1
    CAMERA = 2
    WIRED = 3
    SMOKE = 4
    FLOOD = 5
    GAS = 6
    VIBRATION = 7
    SHOCK = 8
    TEMPERATURE = 9
    SOUND = 10
    KEYFOB = 50
    KEYPAD = 60
    PANIC_BUTTON = 70


ZoneSensorType = collections.namedtuple("ZoneSensorType", "name func")
SENSOR_TYPES = {
    "zones": {
        0x01: ZoneSensorType("Next PG2", SensorType.MOTION),
        0x03: ZoneSensorType("Clip PG2", SensorType.MOTION),
        0x04: ZoneSensorType("Next CAM PG2", SensorType.CAMERA),
        0x05: ZoneSensorType("GB-502 PG2", SensorType.SOUND),
        0x06: ZoneSensorType("TOWER-32AM PG2", SensorType.MOTION),
        0x07: ZoneSensorType("TOWER-32AMK9", SensorType.MOTION),
        0x0A: ZoneSensorType("TOWER CAM PG2", SensorType.CAMERA),
        0x0C: ZoneSensorType("MP-802 PG2", SensorType.MOTION),
        0x0F: ZoneSensorType("MP-902 PG2", SensorType.MOTION),
        0x15: ZoneSensorType("SMD-426 PG2", SensorType.SMOKE),
        0x16: ZoneSensorType("SMD-429 PG2", SensorType.SMOKE),
        0x18: ZoneSensorType("GSD-442 PG2", SensorType.SMOKE),
        0x19: ZoneSensorType("FLD-550 PG2", SensorType.FLOOD),
        0x1A: ZoneSensorType("TMD-560 PG2", SensorType.TEMPERATURE),
        0x1E: ZoneSensorType("SMD-429 PG2", SensorType.SMOKE),
        0x29: ZoneSensorType("MC-302V PG2", SensorType.MAGNET),
        0x2A: ZoneSensorType("MC-302 PG2", SensorType.MAGNET),
        0x2C: ZoneSensorType("MC-303V PG2", SensorType.MAGNET),
        0x2D: ZoneSensorType("MC-302V PG2", SensorType.MAGNET),
        0x35: ZoneSensorType("SD-304 PG2", SensorType.SHOCK),
        0xFE: ZoneSensorType("Wired", SensorType.WIRED),
    },
    "keyfobs": {
        0x01: ZoneSensorType("Keyfob", SensorType.KEYFOB),
        0x02: ZoneSensorType("KF-235 PG2", SensorType.KEYFOB),
    },
    "sirens": {0x01: ZoneSensorType("SR-740 PG2", SensorType.SOUND)},
    "keypads": {0x05: ZoneSensorType("KP-160 PG2", SensorType.KEYPAD)},
    "pgm": {0x01: ZoneSensorType("PGM-1", SensorType.WIRED), 0x05: ZoneSensorType("PGM-5", SensorType.WIRED)},
    "panic_buttons": {0x01: ZoneSensorType("PB-101", SensorType.PANIC_BUTTON)},
    "panel": {0x00: ZoneSensorType("Powermaster", "Panel")},
    "powerlink": {0x00: ZoneSensorType("Powerlink", "Powerlink")},
}

SYSTEM_STATUS = [
    "Disarmed",
    "ExitDelay_ArmHome",
    "ExitDelay_ArmAway",
    "EntryDelay",
    "Armed Home",
    "Armed Away",
    "UserTest",
    "Downloading",
    "Programming",
    "Installer",
    "Home Bypass",
    "Away Bypass",
    "Ready",
    "NotReady",
    "??",
    "??",
    "Disarm",
    "ExitDelay",
    "ExitDelay",
    "EntryDelay",
    "StayInstant",
    "ArmedInstant",
    "??",
    "??",
    "??",
    "??",
    "??",
    "??",
    "??",
    "??",
    "??",
    "??",
]

TROUBLES = [
    "Unknown",
    # 1
    "Preenroll No Code",
    "Unknown",
    "Unknown",
    "Unknown",
    "Unknown",
    "Unknown",
    "Unknown",
    "Unknown",
    "1 Way",
    # 10
    "Unknown",
    "Unknown",
    "Unknown",
    "Unknown",
    "Unknown",
    "Unknown",
    "Burglary Alarm",
    "Unknown",
    "Unknown",
    "Tamper Memory",
    # 20
    "Opened",
    "Unknown",
    "Unknown",
    "Unknown",
    "Unknown",
    "Tamper",
    "Unknown",
    "Unknown",
    "Unknown",
    "Unknown",
    # 30
    "Unknown",
    "Unknown",
    "Unknown",
    "Unknown",
    "Unknown",
    "Unknown",
    "Unknown",
    "Unknown",
    "Unknown",
]

EVENTS = [
    "None",
    # 1
    "Interior Alarm",
    "Perimeter Alarm",
    "Delay Alarm",
    "24h Silent Alarm",
    "24h Audible Alarm",
    "Tamper",
    "Control Panel Tamper",
    "Tamper Alarm",
    "Tamper Alarm",
    "Communication Loss",
    "Panic From Keyfob",
    "Panic From Control Panel",
    "Duress",
    "Confirm Alarm",
    "General Trouble",
    "General Trouble Restore",
    "Interior Restore",
    "Perimeter Restore",
    "Delay Restore",
    "24h Silent Restore",
    # 21
    "24h Audible Restore",
    "Tamper Restore",
    "Control Panel Tamper Restore",
    "Tamper Restore",
    "Tamper Restore",
    "Communication Restore",
    "Cancel Alarm",
    "General Restore",
    "Trouble Restore",
    "Not used",
    "Recent Close",
    "Fire",
    "Fire Restore",
    "Not Active",
    "Emergency",
    "Remove User",
    "Disarm Latchkey",
    "Confirm Alarm Emergency",
    "Supervision (Inactive)",
    "Supervision Restore (Active)",
    "Low Battery",
    "Low Battery Restore",
    "AC Fail",
    "AC Restore",
    "Control Panel Low Battery",
    "Control Panel Low Battery Restore",
    "RF Jamming",
    "RF Jamming Restore",
    "Communications Failure",
    "Communications Restore",
    # 51
    "Telephone Line Failure",
    "Telephone Line Restore",
    "Auto Test",
    "Fuse Failure",
    "Fuse Restore",
    "Keyfob Low Battery",
    "Keyfob Low Battery Restore",
    "Engineer Reset",
    "Battery Disconnect",
    "1-Way Keypad Low Battery",
    "1-Way Keypad Low Battery Restore",
    "1-Way Keypad Inactive",
    "1-Way Keypad Restore Active",
    "Low Battery Ack",
    "Clean Me",
    "Fire Trouble",
    "Low Battery",
    "Battery Restore",
    "AC Fail",
    "AC Restore",
    "Supervision (Inactive)",
    "Supervision Restore (Active)",
    "Gas Alert",
    "Gas Alert Restore",
    "Gas Trouble",
    "Gas Trouble Restore",
    "Flood Alert",
    "Flood Alert Restore",
    "X-10 Trouble",
    "X-10 Trouble Restore",
    # 81
    "Arm Home",
    "Arm Away",
    "Quick Arm Home",
    "Quick Arm Away",
    "Disarm",
    "Fail To Auto-Arm",
    "Enter To Test Mode",
    "Exit From Test Mode",
    "Force Arm",
    "Auto Arm",
    "Instant Arm",
    "Bypass",
    "Fail To Arm",
    "Door Open",
    "Communication Established By Control Panel",
    "System Reset",
    "Installer Programming",
    "Wrong Password",
    "Not Sys Event",
    "Not Sys Event",
    # 101
    "Extreme Hot Alert",
    "Extreme Hot Alert Restore",
    "Freeze Alert",
    "Freeze Alert Restore",
    "Human Cold Alert",
    "Human Cold Alert Restore",
    "Human Hot Alert",
    "Human Hot Alert Restore",
    "Temperature Sensor Trouble",
    "Temperature Sensor Trouble Restore",
    # New values for PowerMaster and models with partitions
    "PIR Mask",
    "PIR Mask Restore",
    "Repeater low battery",
    "Repeater low battery restore",
    "Repeater inactive",
    "Repeater inactive restore",
    "Repeater tamper",
    "Repeater tamper restore",
    "Siren test end",
    "Devices test end",
    # 121
    "One way comm. trouble",
    "One way comm. trouble restore",
    "Sensor outdoor alarm",
    "Sensor outdoor restore",
    "Guard sensor alarmed",
    "Guard sensor alarmed restore",
    "Date time change",
    "System shutdown",
    "System power up",
    "Missed Reminder",
    "Pendant test fail",
    "Basic KP inactive",
    "Basic KP inactive restore",
    "Basic KP tamper",
    "Basic KP tamper Restore",
    "Heat",
    "Heat restore",
    "LE Heat Trouble",
    "CO alarm",
    "CO alarm restore",
    # 141
    "CO trouble",
    "CO trouble restore",
    "Exit Installer",
    "Enter Installer",
    "Self test trouble",
    "Self test restore",
    "Confirm panic event",
    "n/a",
    "Soak test fail",
    "Fire Soak test fail",
    "Gas Soak test fail",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
    "n/a",
]
