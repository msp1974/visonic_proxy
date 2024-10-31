# Visonic Proxy

This is currently in beta.

- Alarm Monitor Port 5002
- Websocket Port - 8082


## Run standalone

Recommended to use a venv.  Requires Python 3.12 and installation of the requirements.txt file.

In visonic_proxy directory start with
```python
./run.py
```

### Run as docker container

Use build.sh to create a container image
Use start.sh to run the container


### Run as a HA addon

Add the respository to your list of repositories - https://github.com/msp1974/visonic_proxy
Refresh list of addons
Install through Addons UI

