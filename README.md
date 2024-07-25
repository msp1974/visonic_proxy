# Visonic Proxy

This is currently in beta and not recommended to use.

- Alarm Monitor Port 5002
- Visonic Monitor Port 5003

## Run standalone

Recommended to use a venv.  Requires Python 3.12
In visonic_proxy directory start with
```python
python3 run.py
```

### Run as docker container

Use build.sh to create a container image
Use start.sh to run the container


### Run as a HA addon

Copy all files into addons local directory in a visonic_proxy folder
Refresh list of addons
Install through Addons UI