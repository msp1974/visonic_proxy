# Visonic Proxy

This is currently in beta and not recommended to use.

- Alarm Monitor Port 5002


## Run standalone

Recommended to use a venv.  Requires Python 3.12 and installation of the requirements.txt file.

In visonic_proxy directory start with
```python
./run.py
```

### Run as docker container - NEEDS MORE TESTING

Use build.sh to create a container image
Use start.sh to run the container


### Run as a HA addon - NEEDS MORE TESTING

Copy all files into addons local directory in a visonic_proxy folder
Refresh list of addons
Install through Addons UI

## Status Messages

The Visonic proxy currently sends 1 status message on every connection change to the monitor clients connected.
Message is
```
0d e0 <no of alarm clients connected> <no of visonic clients connected> <no of monitor clients connected> <if in proxy mode> <if in stealth mode> <if panel in download mode> 43 <checksum> 0a
```
ie 
```
0d e0 01 01 01 00 00 43 d8 0a
```

## Commands

The CM Proxy currently supports 2 commands.  Commands are in the format
```
0d e0 <command> <value> 43 <checksum> 0d
```
ie 
```
0d e1 02 01 1b 0a
```

### Available Commands
```e1 01 00``` - send status e0 message

```e1 02 00``` - Exit stealth mode

```e1 02 01``` - Enter stealth mode

## Config Options

The following config options are availabe in const.py and adjust the operation of the Visonic proxy as below.

`PROXY_MODE` - Whether to connect to the Visonic servers or run in standalone mode

`LOG_LEVEL` - logging level

`LOG_TO_FILE` - write logs to files

`LOG_FILES_TO_KEEP` - number of lof files to keep.  Rotates on start of CM


`MESSAGE_LOG_LEVEL` - level of logging for system messages
(These may change)
- 1 connection/disconnection info only
- 2 same as 1 plus sent messages
- 3 same as 2 plus sent ACKs
- 4 same as 3 plus received messages
- 5 same as 4 plus ack waiting messages and builder messages
- 6 full debug


`VISONIC_HOST` - host ip of Visonic server

`MESSAGE_PORT `- connection port for Alarm and onward Visonic server connection

`ALARM_MONITOR_PORT` - Port to connect client to to receive messages form Alarm

`VISONIC_RECONNECT_INTERVAL` - When Visonic server disconnects, how long to wait before reconnecting

`KEEPALIVE_TIMER` - how long after last message to send a KeepAlive message

`WATHCHDOG_TIMEOUT` - how long to wait if no received message on connection before terminating it

`ACK_TIMEOUT` - how long to wait for ACK before continuing

`ALARM_MONITOR_SENDS_ACKS` - if the monitor client will send ACKs for messages sent to it

`ALARM_MONITOR_NEEDS_ACKS` - if the monitor client expects to be sent ACKs for messages it has sent

`ALARM_MONITOR_SENDS_KEEPALIVES` - if the monitor client sends KeepAlive meesages (stops CM sending them)

`ACK_B0_03_MESSAGES` - if the monitor client ACKs B0 messages

`SEND_E0_MESSAGES` - whether to send E0 status messages to monitor client

`FILTER_STD_COMMANDS` - list of standard commands from monitor to filter and not send to Alarm

`FILTER_B0_COMMANDS` - list of B0 messages from monitor to filter and not send to the Alarm