#!/usr/bin/with-contenv bashio
export VISONIC_HOST="$(bashio::config 'visonic_host')"
export WEBSOCKET_MODE="$(bashio::config 'websocket_mode')"
export WEBSOCKET_SSL="$(bashio::config 'websocket_ssl')"
export WEBSOCKET_AUTH_KEY="$(bashio::config 'websocket_auth_key')"
export MESSAGE_LOG_LEVEL="$(bashio::config 'message_log_level')"
export LOG_LEVEL="$(bashio::config 'log_level')"

cd /visonic_proxy
exec python3 ./run.py
