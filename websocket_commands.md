# Websocket Server Accepted Requests

The Websocket server accepts the following requests:

Requests are in json format as below.

```
{"request":"[COMMAND]", "[PARAM NAME]":[PARAM VALUE]}
```

## Status

The status command will return a standard status output of the panel.  If the Visonic Proxy has not yet completed the Websocket client initialisation, you will only receive a partial output.  This initialisation process takes about 5-10s after the alarm first connects.
```
{"request":"status"}
```

## Command

You can issue any status command by id to the websocket client and it will request from the alarm panel and return a json decoded version of the response.  Command ids are as per the list of B0 status commands and must be a hex string ie "0a", "00" etc.
```
{"request":"command", "id": "[COMMAND ID]"}
```

## Setting

Very similar to the command above, you can request any setting and the websocket server will return a json decoded version of the response.  Setting ids are as per the list of Command35 settings.
```
{"request":"setting","id": [SETTING ID]}
```

## All Commands
Will issue the full list of commands to the panel and return a json output of the decoded responses.  Known only parameter determines whether to use an incremental number list for the commands to run or the known list defined in the Status Commands list.  It will, however, not issue commands that are special and should not be sent to the panel.
```
{"request":"all_commands", "known_only": True}
```

## All Settings
Will issue the full list of settings requests to the panel and return a json output of the decoded responses.  Known only parameter determines whether to use an incremental number list for the settings to run or the known list defined in the Command35 Settings list.  There are a small number that will be skipped no matter what this setting as they maybe destructive.
```
{"request":"all_settings", "known_only": True}
```

## Turn On/Off

This allows turning on/off things.  At the moment it only supports Bypass and PGM.  In each case the zone or pgm_id is an integer.
```
{"request":"turn_on", "type":"bypass", "zone": [ZONE_ID]}

{"request":"turn_off", "type":"bypass", "zone": [ZONE_ID]}

{"request":"turn_on", "type":"pgm", "pgm_id": [PGM_ID]}

{"request":"turn_off", "type":"pgm", "pgm_id": [PGM_ID]}
```
## Arm

This allows arming and disarming of the panel.  The code parameter is an optional string and the websocket server will use the master user code if no code is passed.
State Id relates to the state id of the arming type as per the list below.  Partition id is a single integer representing the bits relating to partition number.  So if you want to arm all partitions (1,2 & 3) partition id is 7, arm just 1 and 3, id is 5, arm just 2, id is 2.
```
{"request":"arm", "state":[STATE], "partition":[PARTITION_ID], "code":"[USER_CODE]"}
```

### State Codes
    Disarm = 0
    Arm Home = 4
    Arm Away = 5
    Arm Instant Home = 14
    Arm Instant Away = 15

## Send Raw Message

This allows sending of a raw message to the panel.  The command must be in the full format required by the panel.  Ie. 0d b0 01 6a 00 43 a0 0a.  This does not return a result and you will need to see the logs for that.

```
{"request":"send_raw_command", "cmd":"[RAW HEX COMMAND]"}
