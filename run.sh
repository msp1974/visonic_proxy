#!/usr/bin/with-contenv bashio
CONFIG_PATH=/data/options.json

PROXY_MODE="$(bashio::config 'proxy_mode')"
WEBSOCKET_MODE="$(bashio::config 'websocket_mode')"
WEBSOCKET_HOST="$(bashio::config 'websocket_host')"

cd /visonic_proxy || exit
python3 /visonic_proxy/run.py
