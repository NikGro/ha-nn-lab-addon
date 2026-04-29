#!/usr/bin/with-contenv bashio
set -e

export HA_URL="$(bashio::config 'ha_url')"
export HA_TOKEN="${SUPERVISOR_TOKEN}"

exec python3 -m uvicorn app.backend.main:app --host 0.0.0.0 --port 8110
