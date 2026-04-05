#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-pre-deploy}"
RUN_LOCAL_SMOKE="${RUN_LOCAL_SMOKE:-1}"
RUN_BIND_SMOKE="${RUN_BIND_SMOKE:-0}"
SMOKE_HOST="${SMOKE_HOST:-127.0.0.1}"
SMOKE_PORT="${SMOKE_PORT:-18000}"
BASE_URL="${BASE_URL:-http://${SMOKE_HOST}:${SMOKE_PORT}}"
TMP_ROOT="${ROOT_DIR}/.codex_tmp"
PY_CACHE_DIR="${TMP_ROOT}/pycache"
PYTEST_BASETEMP="${TMP_ROOT}/pytest-basetemp"
TMPDIR_LOCAL="${TMP_ROOT}/tmp"
SERVER_PID=""

cleanup() {
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

wait_for_server() {
  local attempts=0
  until curl -fsS "${BASE_URL}/health/live" >/dev/null 2>&1; do
    attempts=$((attempts + 1))
    if [[ $attempts -ge 40 ]]; then
      echo "[gate] local api server did not become ready" >&2
      return 1
    fi
    sleep 0.5
  done
}

echo "[gate] mode=${MODE}"
cd "$ROOT_DIR"
mkdir -p "$TMP_ROOT" "$PY_CACHE_DIR" "$TMPDIR_LOCAL"
rm -rf "$PYTEST_BASETEMP"

echo "[gate] py_compile"
TMPDIR="$TMPDIR_LOCAL" PYTHONPYCACHEPREFIX="$PY_CACHE_DIR" \
  python3 -m py_compile \
    api_server.py \
    scorecard.py \
    scheduler.py \
    scheduler_jobs.py \
    smart_trader.py \
    world_source_adapters.py \
    world_hard_source_feeds.py \
    world_data_gateway.py \
    world_cross_asset_engine.py \
    world_action_engine.py \
    world_operating_engine.py \
    world_state_feeds.py \
    world_event_cascade.py \
    world_refresh_planner.py \
    scripts/local_api_smoke.py \
    scripts/local_world_gateway_smoke.py \
    scripts/local_world_gateway_integration_smoke.py

echo "[gate] pytest"
TMPDIR="$TMPDIR_LOCAL" python3 -m pytest -q --basetemp "$PYTEST_BASETEMP" \
  tests/test_scheduler_jobs.py \
  tests/test_scorecard_weekly.py \
  tests/test_api_server.py \
  tests/test_smart_trader.py \
  tests/test_regime_router.py \
  tests/test_signal_tracker.py \
  tests/test_world_source_adapters.py \
  tests/test_world_hard_source_feeds.py \
  tests/test_world_data_gateway.py \
  tests/test_world_cross_asset_engine.py \
  tests/test_world_action_engine.py \
  tests/test_world_event_cascade.py \
  tests/test_world_state_feeds.py \
  tests/test_world_refresh_planner.py \
  tests/test_world_operating_engine.py

if [[ -d "${ROOT_DIR}/native_app" ]]; then
  echo "[gate] native typecheck"
  (cd "${ROOT_DIR}/native_app" && npm run typecheck)
  echo "[gate] native lint"
  (cd "${ROOT_DIR}/native_app" && npm run lint)
fi

if [[ "$RUN_LOCAL_SMOKE" == "1" ]]; then
  echo "[gate] local api smoke"
  python3 "${ROOT_DIR}/scripts/local_api_smoke.py"
  echo "[gate] local world gateway smoke"
  python3 "${ROOT_DIR}/scripts/local_world_gateway_smoke.py"
  echo "[gate] local world gateway integration smoke"
  python3 "${ROOT_DIR}/scripts/local_world_gateway_integration_smoke.py"
fi

if [[ "$RUN_BIND_SMOKE" == "1" ]]; then
  if ! curl -fsS "${BASE_URL}/health/live" >/dev/null 2>&1; then
    echo "[gate] starting local api server for bind smoke"
    ALPHA_API_HOST="$SMOKE_HOST" ALPHA_API_PORT="$SMOKE_PORT" \
      python3 api_server.py >/tmp/alpha_ai_api_server.log 2>&1 &
    SERVER_PID="$!"
    wait_for_server
  else
    echo "[gate] reusing running api server"
  fi

  echo "[gate] live api smoke"
  BASE_URL="$BASE_URL" bash "${ROOT_DIR}/scripts/live_api_smoke.sh"
fi

echo "[gate] ok"
