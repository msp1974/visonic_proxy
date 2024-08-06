"""Constants."""

import logging

PROXY_MODE = True
LOG_LEVEL = logging.INFO
LOG_TO_FILE = True
LOG_FILES_TO_KEEP = 10

# 1 connection/disconnection info only
# 2 same as 1 plus sent messages
# 3 same as 2 plus sent ACKs
# 4 same as 3 plus received messages
# 5 same as 4 plus ack waiting messages and builder messages
MESSAGE_LOG_LEVEL = 5


VISONIC_HOST = "52.58.105.181"
MESSAGE_PORT = 5001
ALARM_MONITOR_PORT = 5002
VISONIC_MONITOR_PORT = 5003
VISONIC_RECONNECT_INTERVAL = 10
KEEPALIVE_TIMER = 30  # Send Keepalive if no messages in 30 seconds
WATHCHDOG_TIMEOUT = 120  # If no received message on connection for 120s, kill it.
ACK_TIMEOUT = 5  # How long to wait for ACK before continuing


ALARM_MONITOR_SENDS_ACKS = True
ALARM_MONITOR_NEEDS_ACKS = True
MATCH_ACK_MSG_ID = False
ALARM_MONITOR_SENDS_KEEPALIVES = False
ACK_B0_03_MESSAGES = False
SEND_E0_MESSAGES = True

FILTER_STD_COMMANDS = ["0b"]
FILTER_B0_COMMANDS = []


TEXT_UNKNOWN = "UNKNOWN"

VIS_ACK = "VIS-ACK"
VIS_BBA = "VIS-BBA"
ADM_CID = "*ADM-CID"
ADM_ACK = "*ACK"
DUH = "DUH"
NAK = "NAK"

STATUS_COMMAND = "e0"
ACTION_COMMAND = "e1"


NO_WAIT_FOR_ACK_MESSAGES = []
