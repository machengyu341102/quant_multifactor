#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import world_hard_source_feeds as feeds  # noqa: E402
import world_data_gateway  # noqa: E402


def main() -> None:
    token = os.environ.get("WORLD_DATA_GATEWAY_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    routes = [
        ("official_fulltext", "/api/world-gateway/official-fulltext", "documents"),
        ("shipping_ais", "/api/world-gateway/shipping-ais", "routes"),
        ("freight_rates", "/api/world-gateway/freight-rates", "lanes"),
        ("commodity_terminal", "/api/world-gateway/commodity-terminal", "commodities"),
        ("macro_rates_fx", "/api/world-gateway/macro-rates-fx", "instruments"),
    ]

    with tempfile.TemporaryDirectory(prefix="alpha_ai_world_probe_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        original_paths = dict(feeds._SOURCE_PATHS)
        original_attrs = {
            "WORLD_OFFICIAL_FULLTEXT": feeds.WORLD_OFFICIAL_FULLTEXT,
            "WORLD_SHIPPING_AIS": feeds.WORLD_SHIPPING_AIS,
            "WORLD_FREIGHT_RATES": feeds.WORLD_FREIGHT_RATES,
            "WORLD_COMMODITY_TERMINAL": feeds.WORLD_COMMODITY_TERMINAL,
            "WORLD_MACRO_RATES_FX": feeds.WORLD_MACRO_RATES_FX,
        }
        try:
            feeds.WORLD_OFFICIAL_FULLTEXT = tmp_root / "world_official_fulltext.json"
            feeds.WORLD_SHIPPING_AIS = tmp_root / "world_shipping_ais.json"
            feeds.WORLD_FREIGHT_RATES = tmp_root / "world_freight_rates.json"
            feeds.WORLD_COMMODITY_TERMINAL = tmp_root / "world_commodity_terminal.json"
            feeds.WORLD_MACRO_RATES_FX = tmp_root / "world_macro_rates_fx.json"
            feeds._SOURCE_PATHS = {
                "official_fulltext": feeds.WORLD_OFFICIAL_FULLTEXT,
                "shipping_ais": feeds.WORLD_SHIPPING_AIS,
                "freight_rates": feeds.WORLD_FREIGHT_RATES,
                "commodity_terminal": feeds.WORLD_COMMODITY_TERMINAL,
                "macro_rates_fx": feeds.WORLD_MACRO_RATES_FX,
            }

            with TestClient(world_data_gateway.app) as client:
                for key, path, plural_key in routes:
                    response = client.get(path, headers=headers)
                    response.raise_for_status()
                    payload = response.json()
                    count = len(payload.get(plural_key, [])) if isinstance(payload.get(plural_key), list) else 0
                    print(
                        f"{key}: "
                        f"fetch_mode={payload.get('fetch_mode')} "
                        f"origin_mode={payload.get('origin_mode')} "
                        f"remote_configured={payload.get('remote_configured')} "
                        f"degraded_to_derived={payload.get('degraded_to_derived')} "
                        f"count={count} "
                        f"remote_url={payload.get('remote_url')} "
                        f"block_reason={payload.get('block_reason')} "
                        f"probe={payload.get('live_probe_summary')}"
                    )
        finally:
            for attr, path in original_attrs.items():
                setattr(feeds, attr, path)
            feeds._SOURCE_PATHS = original_paths


if __name__ == "__main__":
    main()
