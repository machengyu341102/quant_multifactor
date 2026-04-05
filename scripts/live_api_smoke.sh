#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:18000}"
APP_AUTH_USERNAME="${APP_AUTH_USERNAME:-}"
APP_AUTH_PASSWORD="${APP_AUTH_PASSWORD:-}"

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

fetch_json() {
  local path="$1"
  local output="$2"
  shift 2
  curl -fsS "$@" "${BASE_URL}${path}" -o "$output"
}

assert_json_value() {
  local file="$1"
  local expr="$2"
  local label="$3"
  python3 - "$file" "$expr" "$label" <<'PY'
import json
import sys

file_path, expr, label = sys.argv[1:4]
with open(file_path, "r", encoding="utf-8") as fh:
    payload = json.load(fh)

try:
    value = eval(expr, {"payload": payload})
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"[smoke] {label}: eval failed: {exc}")

if not value:
    raise SystemExit(f"[smoke] {label}: assertion failed")
PY
}

echo "[smoke] checking liveness"
fetch_json "/health/live" "$tmp_dir/live.json"
assert_json_value "$tmp_dir/live.json" "payload.get('status') == 'live'" "health live"

echo "[smoke] checking readiness"
ready_code="$(curl -s -o "$tmp_dir/ready.json" -w '%{http_code}' "${BASE_URL}/health/ready")"
if [[ "$ready_code" != "200" && "$ready_code" != "503" ]]; then
  echo "[smoke] unexpected readiness status: $ready_code" >&2
  exit 1
fi
assert_json_value "$tmp_dir/ready.json" "'status' in payload" "health ready payload"

echo "[smoke] checking world state"
fetch_json "/api/world-state" "$tmp_dir/world.json"
assert_json_value "$tmp_dir/world.json" "bool(payload.get('market_phase'))" "world state market phase"
assert_json_value "$tmp_dir/world.json" "bool(payload.get('structural_summary'))" "world state structural summary"
assert_json_value "$tmp_dir/world.json" "isinstance(payload.get('components', []), list) and len(payload.get('components', [])) >= 3" "world state components"
assert_json_value "$tmp_dir/world.json" "bool(payload.get('dominant_component'))" "world state dominant component"
assert_json_value "$tmp_dir/world.json" "isinstance(payload.get('refresh_plan'), dict)" "world state refresh plan shape"
assert_json_value "$tmp_dir/world.json" "payload.get('refresh_plan', {}).get('hard_source_interval_minutes', 0) > 0" "world state hard source interval"
assert_json_value "$tmp_dir/world.json" "isinstance(payload.get('actions', []), list)" "world state actions shape"
assert_json_value "$tmp_dir/world.json" "isinstance(payload.get('checks', []), list)" "world state checks shape"
assert_json_value "$tmp_dir/world.json" "isinstance(payload.get('cross_asset_signals', []), list)" "world state cross asset signals shape"
assert_json_value "$tmp_dir/world.json" "isinstance(payload.get('regional_pressures', []), list)" "world state regional pressures shape"
assert_json_value "$tmp_dir/world.json" "any(item.get('key') == 'official_fulltext' for item in payload.get('source_statuses', []))" "world state hard source statuses"
assert_json_value "$tmp_dir/world.json" "any('origin_mode' in item and 'remote_configured' in item and 'degraded_to_derived' in item for item in payload.get('source_statuses', []))" "world state hard source runtime state"
assert_json_value "$tmp_dir/world.json" "all('hard_source_score' in item for item in payload.get('top_directions', []))" "world state hard source score"

echo "[smoke] checking world refresh plan"
fetch_json "/api/world-refresh-plan" "$tmp_dir/world_refresh_plan.json"
assert_json_value "$tmp_dir/world_refresh_plan.json" "payload.get('news_interval_minutes', 0) > 0" "world refresh plan news interval"
assert_json_value "$tmp_dir/world_refresh_plan.json" "isinstance(payload.get('overdue_sources', []), list)" "world refresh overdue sources shape"

echo "[smoke] checking execution policy"
fetch_json "/api/execution-policy" "$tmp_dir/execution_policy.json"
assert_json_value "$tmp_dir/execution_policy.json" "payload.get('risk_budget_pct', 0) >= 0" "execution policy risk budget"
assert_json_value "$tmp_dir/execution_policy.json" "isinstance(payload.get('allowed_strategies', []), list)" "execution policy strategies"

echo "[smoke] checking production guard"
fetch_json "/api/production-guard" "$tmp_dir/production_guard.json"
assert_json_value "$tmp_dir/production_guard.json" "'blocked_additions' in payload" "production guard additions flag"
assert_json_value "$tmp_dir/production_guard.json" "bool(payload.get('summary'))" "production guard summary"
fetch_json "/api/production-guard/actions?limit=3" "$tmp_dir/production_guard_actions.json"
assert_json_value "$tmp_dir/production_guard_actions.json" "isinstance(payload, list)" "production guard actions shape"

echo "[smoke] checking ops summary"
fetch_json "/api/ops/summary" "$tmp_dir/ops.json"
assert_json_value "$tmp_dir/ops.json" "payload.get('version')" "ops summary version"
assert_json_value "$tmp_dir/ops.json" "payload.get('production_guard') is not None" "ops summary production guard"
assert_json_value "$tmp_dir/ops.json" "payload.get('world_state_export') is not None" "ops summary world state export"

echo "[smoke] checking world state export"
fetch_json "/api/world-state/export/status?period=daily&ensure_fresh=1" "$tmp_dir/world_export_status.json"
assert_json_value "$tmp_dir/world_export_status.json" "bool(payload.get('latest_export_id'))" "world state export latest id"
assert_json_value "$tmp_dir/world_export_status.json" "bool(payload.get('latest_bundle_route'))" "world state export bundle route"

echo "[smoke] checking execution policy export"
fetch_json "/api/execution-policy/export/status?period=daily&ensure_fresh=1" "$tmp_dir/export_status.json"
assert_json_value "$tmp_dir/export_status.json" "bool(payload.get('latest_export_id'))" "execution export latest id"
assert_json_value "$tmp_dir/export_status.json" "bool(payload.get('latest_bundle_route'))" "execution export bundle route"

echo "[smoke] checking messages"
fetch_json "/api/messages?limit=10" "$tmp_dir/messages.json"
assert_json_value "$tmp_dir/messages.json" "isinstance(payload, list)" "messages shape"

echo "[smoke] checking limit-up opportunities"
fetch_json "/api/limit-up-opportunities?days=1&limit=3" "$tmp_dir/limit_up.json"
assert_json_value "$tmp_dir/limit_up.json" "isinstance(payload, list)" "limit-up opportunities shape"
assert_json_value "$tmp_dir/limit_up.json" "all('risk_gate' in item for item in payload)" "limit-up risk gate"
assert_json_value "$tmp_dir/limit_up.json" "all('board_pattern' in item for item in payload)" "limit-up board pattern"

echo "[smoke] checking hidden accumulation opportunities"
fetch_json "/api/hidden-accumulation-opportunities?limit=3" "$tmp_dir/hidden_accumulation.json"
assert_json_value "$tmp_dir/hidden_accumulation.json" "isinstance(payload, list)" "hidden accumulation shape"
assert_json_value "$tmp_dir/hidden_accumulation.json" "all('streak_days' in item for item in payload)" "hidden accumulation streak"
assert_json_value "$tmp_dir/hidden_accumulation.json" "all('consolidation_width_pct' in item for item in payload)" "hidden accumulation width"

if [[ -n "$APP_AUTH_USERNAME" && -n "$APP_AUTH_PASSWORD" ]]; then
  echo "[smoke] checking authenticated app routes"
  curl -fsS \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${APP_AUTH_USERNAME}\",\"password\":\"${APP_AUTH_PASSWORD}\"}" \
    "${BASE_URL}/api/auth/login" \
    -o "$tmp_dir/login.json"
  token="$(python3 - "$tmp_dir/login.json" <<'PY'
import json
import sys
with open(sys.argv[1], "r", encoding="utf-8") as fh:
    payload = json.load(fh)
print(payload["access_token"])
PY
)"
  fetch_json "/api/app/ops/summary" "$tmp_dir/app_ops.json" -H "Authorization: Bearer ${token}"
  assert_json_value "$tmp_dir/app_ops.json" "payload.get('production_guard') is not None" "app ops production guard"
fi

echo "[smoke] ok"
