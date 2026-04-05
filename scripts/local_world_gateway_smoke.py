#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

from fastapi.testclient import TestClient

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import world_data_gateway  # noqa: E402


def expect(condition: bool, label: str) -> None:
    if not condition:
        raise SystemExit(f"[world-gateway-smoke] {label}: assertion failed")


def main() -> None:
    token = os.environ.get("WORLD_DATA_GATEWAY_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    with TestClient(world_data_gateway.app) as client:
        live = client.get("/health/live")
        expect(live.status_code == 200, "health live status")
        expect(live.json().get("status") == "live", "health live payload")

        status = client.get("/api/world-gateway/source-status", headers=headers)
        expect(status.status_code == 200, "source status")
        status_payload = status.json()
        expect(isinstance(status_payload.get("sources", []), list), "source status list")
        expect(len(status_payload.get("sources", [])) == 5, "source status count")

        for path, plural_key in (
            ("/api/world-gateway/official-fulltext", "documents"),
            ("/api/world-gateway/shipping-ais", "routes"),
            ("/api/world-gateway/freight-rates", "lanes"),
            ("/api/world-gateway/commodity-terminal", "commodities"),
            ("/api/world-gateway/macro-rates-fx", "instruments"),
        ):
            response = client.get(path, headers=headers)
            expect(response.status_code == 200, f"{path} status")
            payload = response.json()
            expect(bool(payload.get("source_key")), f"{path} source key")
            expect(isinstance(payload.get(plural_key, []), list), f"{path} payload list")

    print("[world-gateway-smoke] ok")


if __name__ == "__main__":
    main()
