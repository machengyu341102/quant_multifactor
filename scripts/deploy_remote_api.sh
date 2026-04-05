#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-}"
REMOTE_DIR="${REMOTE_DIR:-/opt/alpha-ai}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DRY_RUN="${DRY_RUN:-0}"
SERVICE_NAME="${SERVICE_NAME:-alpha-ai-backend}"
GATEWAY_SERVICE_NAME="${GATEWAY_SERVICE_NAME:-alpha-ai-world-gateway}"

if [[ -z "$TARGET" ]]; then
  echo "usage: $0 user@host" >&2
  exit 1
fi

RSYNC_EXCLUDES=(
  "--exclude=.git"
  "--exclude=.pytest_cache"
  "--exclude=.codex_tmp"
  "--exclude=__pycache__"
  "--exclude=*.pyc"
  "--exclude=quant_data.db*"
  "--exclude=scorecard.json"
  "--exclude=trade_journal.json"
  "--exclude=signals_db.json"
  "--exclude=signal_tracker.json"
  "--exclude=tunable_params.json"
  "--exclude=feature_config.json"
  "--exclude=exports"
)

run_remote() {
  local cmd="$1"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] ssh ${TARGET} ${cmd}"
    return 0
  fi
  ssh "$TARGET" "$cmd"
}

run_rsync() {
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] rsync -az --delete ${RSYNC_EXCLUDES[*]} ./ ${TARGET}:${REMOTE_DIR}/"
    return 0
  fi
  rsync -az --delete "${RSYNC_EXCLUDES[@]}" ./ "${TARGET}:${REMOTE_DIR}/"
}

echo "[deploy] ensuring remote directory"
run_remote "mkdir -p ${REMOTE_DIR}"

echo "[deploy] syncing project"
run_rsync

echo "[deploy] preparing virtualenv and dependencies"
run_remote "cd ${REMOTE_DIR} && ${PYTHON_BIN} -m venv venv && . venv/bin/activate && pip install -U pip && pip install -r requirements.txt"

echo "[deploy] syntax check"
run_remote "cd ${REMOTE_DIR} && . venv/bin/activate && PYTHONPYCACHEPREFIX=/tmp/alpha_ai_pycache ${PYTHON_BIN} -m py_compile api_server.py world_data_gateway.py scheduler.py scheduler_jobs.py scorecard.py smart_trader.py"

echo "[deploy] restarting service if present"
run_remote "if command -v systemctl >/dev/null 2>&1 && systemctl status ${SERVICE_NAME} >/dev/null 2>&1; then sudo systemctl restart ${SERVICE_NAME}; fi"
run_remote "if command -v systemctl >/dev/null 2>&1 && systemctl status ${GATEWAY_SERVICE_NAME} >/dev/null 2>&1; then sudo systemctl restart ${GATEWAY_SERVICE_NAME}; fi"

echo "[deploy] done"
