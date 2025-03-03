# Visonic Proxy

A proxy for Visonic Alarms to allow panels with Powerlink 3.1 modules to be able to work with HomeAssistant and the Visonic apps at the same time.

It is supported by the following HA integrations.

- Visonic Powerlink (websocket mode) - @msp1974 https://github.com/msp1974/visonic_powerlink
- Visonic Alarm Panel for Home Assistant (socket mode) - @davesmeghead https://github.com/davesmeghead/visonic

This is currently in beta, is designed to work with PowerMaster panels only and has been tested with the following panels.
- Powermaster 10
- Powermaster 30


It has a socket mode or websocket mode which can be configured in the addon configuration by turning off (socket mode) or on (websocket mode) the websocket mode option switch.
- Socket port - 5002
- Websocket port - 8082

## Running Visonic Proxy

### Run as a HA addon

Add the respository to your list of repositories - https://github.com/msp1974/visonic_proxy

Refresh the list of addons

Install through the Addons UI


### Run standalone

It is recommended to use a python venv.  Requires Python 3.12 and installation of the requirements.txt file.

In visonic_proxy directory start the proxy server with
```python
./run.py
```

### Run as docker container

Use build.sh to create a container image.

Use start.sh to run the container

## Configuring Visonic Alarm To Work With Visonic Proxy

This addon works as a proxy to a PowerManage server and requires you to have a PowerLink 3.1 module installed and configured to a monitor service.

In order to use this addon, you need to tell your alarm to connect to it instead of the PowerManage server directly and then block access to the PowerManage server for your alarm on your network.

### Configure via the Alarm Install app

Log into your panel using the app.
Select the Powerlink module and the configuration tab
In the Central Station Reporting section set the below settings:

- **Report Events to Central Station** - all *backup

- **Receiver 2 IP** - [IP of your homeassistant server running this addon]

### Configure via the Panel
Go into Installer Mode on your panel.  You will need to use the Master Installer code (not the normal installer code).  This is default 9999, whereas the default installer code is 8888.  However, this may (should) have been changed by you or your installer.

* Select Communication (option 04)
* Select C.S Reporting (option 03)
* Select Report Events (option 01)
* Change to all *backup
* Go back up to the C.S Reporting menu
* Select IP RCVR 2 (option 22)
* Enter the IP of your homeassistant server running this addon
* Exit Installer Mode.

NOTE: It is **not** recommended to remove the setting in Receiver IP 1 as this will allow you to still connect to the PowerManage monitor server directly in case of issues.

### Blocking Panel Access

In order for the panel to connect to this addon, you will need to stop it being able to connect to the PowerManage server.

There are many ways to block access for your panel to the PowerManage server depending on your network equipment.  In my case, I use parental control to block access to the internet for the alarm panel.  However, you could also use port blocking (Network Services Filter) on a firewall.  You need (as a minimum) to block ports 5001 and 8442 from the panel to the internet.

#### NOTES 
* Depending on your equipment, you may need to disconnect your alarm ethernet cable for 30s and reconnect it in order for it to connect to the addon the first time.  You can see in the addon logs if the alarm has connected.
* Do not block access for your HA instance to the PowerManage server as the addon connects to that.

## Issues

Please log issues on the github repository, providing useful logging where possible, along with what Visonic panel you have, firmware version of panel and powerlink module and a clear description of the issue.

