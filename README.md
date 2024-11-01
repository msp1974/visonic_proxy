# Visonic Proxy

This is currently in beta and has been tested with the following panels.
- Powermaster 10
- Powermaster 30


It has both a socket mode and a websocket mode which can be configured in the options.
- Socket port - 5002
- Websocket port - 8082

### Run as a HA addon

Add the respository to your list of repositories - https://github.com/msp1974/visonic_proxy
Refresh list of addons
Install through Addons UI


## Run standalone

Recommended to use a venv.  Requires Python 3.12 and installation of the requirements.txt file.

In visonic_proxy directory start with
```python
./run.py
```

### Run as docker container

Use build.sh to create a container image
Use start.sh to run the container




## Configuring Visonic Alarm to work with this addon

This addon works as a proxy to a PowerManage server and requires you to have a PowerLink 3.1 module installed and configured to a monitor service.

In order to use this addon, you need to tell your alarm to connect to it instead of the PowerManage server directly and then block access to the PowerManage server for your alarm on your network.

### Configure via the Alarm Install app

Log into your panel using the app.
Select the Powerlink module and the configuration tab
In the Central Station Reporting section set the below settings:

Report Events to Central Station - all *backup
Receiver 2 IP - [IP of your homeassistant server running this addon]

### Configure via the Panel
Go into Installer Mode on your panel.  You will need to use the Master Installer code (not the normal installer code).  This is default 9999, whereas the default installer code is 8888.  However, this may (should) have been changed by you or your installer.

Select Communication (option 04)
Select C.S Reporting (option 03)
Select Report Events (option 01)
Change to all *backup
Go back up to the C.S Reporting menu
Select IP RCVR 2 (option 22)
Enter the IP of your homeassistant server running this addon
Exit Installer Mode.

NOTE: It is not recommended to remove the setting in Receiver IP 1 as this will allow you to still connect to the PowerManage monitor server directly in case of issues.

### Blocking Panel Access

In order for the panel to connect to this addon, you will need to stop it being able to connect to the PowerManage server.

There are many ways to block access for your panel to the PowerManage server depending on your network equipment.  In my case, I use parental control to block access to the internet for the alarm panel.  However, you could also use port blocking (Network Services Filter) on a firewall.  You need (as a minimum) to block ports 5001 and 8442 from the panel to the internet.

NOTE: Again, depending on your equipment, you may need to disconnect your alarm ethernet cable for 30s and reconnect it in order for it to connect to the addon the first time.

You can see in the addon logs if the alarm has connected.

