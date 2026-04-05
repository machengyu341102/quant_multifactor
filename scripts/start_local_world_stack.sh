#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATEWAY_HOST="${WORLD_DATA_GATEWAY_HOST:-127.0.0.1}"
GATEWAY_PORT="${WORLD_DATA_GATEWAY_PORT:-18080}"
API_HOST="${ALPHA_API_HOST:-127.0.0.1}"
API_PORT="${ALPHA_API_PORT:-18000}"

export WORLD_DATA_GATEWAY_BASE_URL="${WORLD_DATA_GATEWAY_BASE_URL:-http://${GATEWAY_HOST}:${GATEWAY_PORT}}"

cd "${ROOT_DIR}"

echo "[world-stack] gateway=${WORLD_DATA_GATEWAY_BASE_URL}"
echo "[world-stack] api=http://${API_HOST}:${API_PORT}"

python3 world_data_gateway.py &
GATEWAY_PID=$!

cleanup() {
  if kill -0 "${GATEWAY_PID}" >/dev/null 2>&1; then
    kill "${GATEWAY_PID}" >/dev/null 2>&1 || true
    wait "${GATEWAY_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

ALPHA_API_HOST="${API_HOST}" ALPHA_API_PORT="${API_PORT}" python3 api_server.py
