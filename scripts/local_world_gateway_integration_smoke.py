#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def expect(condition: bool, label: str) -> None:
    if not condition:
        raise SystemExit(f"[world-gateway-integration-smoke] {label}: assertion failed")


class _GatewayHTTPResponse:
    def __init__(self, status_code: int, headers: dict[str, str], content: bytes):
        self.status = status_code
        self.headers = headers
        self._content = content

    def read(self) -> bytes:
        return self._content

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def main() -> None:
    gateway_token = os.environ.get("WORLD_DATA_GATEWAY_TOKEN", "").strip() or "alpha-world-gateway-local"
    gateway_base_url = "http://world-gateway.local"

    os.environ["WORLD_DATA_GATEWAY_BASE_URL"] = gateway_base_url
    os.environ["WORLD_DATA_GATEWAY_TOKEN"] = gateway_token
    os.environ.pop("WORLD_OFFICIAL_FULLTEXT_URL", None)
    os.environ.pop("WORLD_SHIPPING_AIS_URL", None)
    os.environ.pop("WORLD_FREIGHT_RATES_URL", None)
    os.environ.pop("WORLD_COMMODITY_TERMINAL_URL", None)
    os.environ.pop("WORLD_MACRO_RATES_FX_URL", None)

    import world_data_gateway
    import world_hard_source_feeds as feeds

    gateway_client = TestClient(world_data_gateway.app)
    original_urlopen = feeds.urllib.request.urlopen

    def fake_urlopen(request, timeout=0):
        if isinstance(request, urllib.request.Request):
            full_url = request.full_url
            headers = dict(request.header_items())
        else:
            full_url = str(request)
            headers = {}
        if not full_url.startswith(gateway_base_url):
            return original_urlopen(request, timeout=timeout)
        path = full_url[len(gateway_base_url):] or "/"
        response = gateway_client.get(path, headers=headers)
        return _GatewayHTTPResponse(response.status_code, dict(response.headers), response.content)

    with patch.object(feeds.urllib.request, "urlopen", fake_urlopen):
        feeds.refresh_world_hard_sources()

        import api_server

        with TestClient(api_server.app) as client:
            world = client.get("/api/world-state")
            expect(world.status_code == 200, "world state status")
            payload = world.json()
            statuses = {
                item.get("key"): item
                for item in payload.get("source_statuses", [])
                if isinstance(item, dict) and item.get("key")
            }

            for key in (
                "official_fulltext",
                "shipping_ais",
                "freight_rates",
                "commodity_terminal",
                "macro_rates_fx",
            ):
                item = statuses.get(key)
                expect(isinstance(item, dict), f"{key} source status exists")
                expect(bool(item.get("remote_configured")), f"{key} remote configured")
                expect(item.get("origin_mode") == "remote_live", f"{key} origin mode remote live")
                expect(not bool(item.get("degraded_to_derived")), f"{key} not degraded")

    print("[world-gateway-integration-smoke] ok")


if __name__ == "__main__":
    main()
