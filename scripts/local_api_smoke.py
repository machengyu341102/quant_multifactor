#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

from fastapi.testclient import TestClient

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import api_server  # noqa: E402


def expect(condition: bool, label: str) -> None:
    if not condition:
        raise SystemExit(f"[local-smoke] {label}: assertion failed")


def main() -> None:
    username = os.environ.get("APP_AUTH_USERNAME", "")
    password = os.environ.get("APP_AUTH_PASSWORD", "")

    with TestClient(api_server.app) as client:
        live = client.get("/health/live")
        expect(live.status_code == 200, "health live status")
        expect(live.json().get("status") == "live", "health live payload")

        ready = client.get("/health/ready")
        expect(ready.status_code in {200, 503}, "health ready status")
        expect("status" in ready.json(), "health ready payload")

        world = client.get("/api/world-state")
        expect(world.status_code == 200, "world state status")
        world_payload = world.json()
        expect(bool(world_payload.get("market_phase")), "world state market phase")
        expect(bool(world_payload.get("structural_summary")), "world state structural summary")
        expect(len(world_payload.get("components", [])) >= 3, "world state components")
        expect(bool(world_payload.get("dominant_component")), "world state dominant component")
        expect(isinstance(world_payload.get("refresh_plan"), dict), "world state refresh plan shape")
        expect(world_payload.get("refresh_plan", {}).get("hard_source_interval_minutes", 0) > 0, "world state hard source interval")
        expect(isinstance(world_payload.get("actions", []), list), "world state actions shape")
        expect(isinstance(world_payload.get("checks", []), list), "world state checks shape")
        expect(isinstance(world_payload.get("cross_asset_signals", []), list), "world state cross asset signals shape")
        expect(isinstance(world_payload.get("regional_pressures", []), list), "world state regional pressures shape")
        expect(
            any(item.get("key") == "official_fulltext" for item in world_payload.get("source_statuses", [])),
            "world state hard source statuses",
        )
        expect(
            any("origin_mode" in item and "remote_configured" in item and "degraded_to_derived" in item for item in world_payload.get("source_statuses", [])),
            "world state hard source runtime state",
        )
        expect(
            all("hard_source_score" in item for item in world_payload.get("top_directions", [])),
            "world state hard source score",
        )

        refresh_plan = client.get("/api/world-refresh-plan")
        expect(refresh_plan.status_code == 200, "world refresh plan status")
        refresh_payload = refresh_plan.json()
        expect(refresh_payload.get("news_interval_minutes", 0) > 0, "world refresh plan news interval")
        expect(isinstance(refresh_payload.get("overdue_sources", []), list), "world refresh overdue sources shape")

        policy = client.get("/api/execution-policy")
        expect(policy.status_code == 200, "execution policy status")
        policy_payload = policy.json()
        expect(policy_payload.get("risk_budget_pct", 0) >= 0, "execution policy risk budget")
        expect(isinstance(policy_payload.get("allowed_strategies", []), list), "execution policy strategies")

        production_guard = client.get("/api/production-guard")
        expect(production_guard.status_code == 200, "production guard status")
        guard_payload = production_guard.json()
        expect("blocked_additions" in guard_payload, "production guard additions flag")
        expect(bool(guard_payload.get("summary")), "production guard summary")

        production_guard_actions = client.get("/api/production-guard/actions?limit=3")
        expect(production_guard_actions.status_code == 200, "production guard actions status")
        guard_actions_payload = production_guard_actions.json()
        expect(isinstance(guard_actions_payload, list), "production guard actions shape")

        ops = client.get("/api/ops/summary")
        expect(ops.status_code == 200, "ops summary status")
        ops_payload = ops.json()
        expect(bool(ops_payload.get("version")), "ops summary version")
        expect(ops_payload.get("production_guard") is not None, "ops summary production guard")
        expect(ops_payload.get("world_state") is not None, "ops summary world state")
        expect(ops_payload.get("world_state_export") is not None, "ops summary world state export")

        world_export_status = client.get("/api/world-state/export/status?period=daily&ensure_fresh=1")
        expect(world_export_status.status_code == 200, "world state export status")
        world_export_payload = world_export_status.json()
        expect(bool(world_export_payload.get("latest_export_id")), "world state export latest id")
        expect(bool(world_export_payload.get("latest_bundle_route")), "world state export bundle route")

        export_status = client.get("/api/execution-policy/export/status?period=daily&ensure_fresh=1")
        expect(export_status.status_code == 200, "execution export status")
        export_payload = export_status.json()
        expect(bool(export_payload.get("latest_export_id")), "execution export latest id")
        expect(bool(export_payload.get("latest_bundle_route")), "execution export bundle route")

        messages = client.get("/api/messages?limit=10")
        expect(messages.status_code == 200, "messages status")
        expect(isinstance(messages.json(), list), "messages payload shape")

        limit_up = client.get("/api/limit-up-opportunities?days=1&limit=3")
        expect(limit_up.status_code == 200, "limit up status")
        limit_payload = limit_up.json()
        expect(isinstance(limit_payload, list), "limit up payload shape")
        expect(all("risk_gate" in item for item in limit_payload), "limit up risk gate")
        expect(all("board_pattern" in item for item in limit_payload), "limit up board pattern")

        hidden_accumulation = client.get("/api/hidden-accumulation-opportunities?limit=3")
        expect(hidden_accumulation.status_code == 200, "hidden accumulation status")
        hidden_payload = hidden_accumulation.json()
        expect(isinstance(hidden_payload, list), "hidden accumulation payload shape")
        expect(all("streak_days" in item for item in hidden_payload), "hidden accumulation streak")
        expect(all("consolidation_width_pct" in item for item in hidden_payload), "hidden accumulation width")

        if username and password:
            login = client.post(
                "/api/auth/login",
                json={"username": username, "password": password},
            )
            expect(login.status_code == 200, "login status")
            token = login.json().get("access_token")
            expect(bool(token), "login access token")
            app_ops = client.get(
                "/api/app/ops/summary",
                headers={"Authorization": f"Bearer {token}"},
            )
            expect(app_ops.status_code == 200, "app ops summary status")
            app_ops_payload = app_ops.json()
            expect(app_ops_payload.get("production_guard") is not None, "app ops production guard")
            expect(app_ops_payload.get("world_state") is not None, "app ops world state")

    print("[local-smoke] ok")


if __name__ == "__main__":
    main()
