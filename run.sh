#!/usr/bin/with-contenv bashio
CONFIG_PATH=/data/options.json

PROXY_MODE="$(bashio::config 'proxy_mode')"
WEBSOCKET_MODE="$(bashio::config 'websocket_mode')"
WEBSOCKET_HOST="$(bashio::config 'websocket_host')"
MESSAGE_LOG_LEVEL="$(bashio::config 'message_log_level')"
LOG_LEVEL="$(bashio::config 'log_level')"

cd /visonic_proxy
python3 ./run.py
