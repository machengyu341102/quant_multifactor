import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestWorldCrossAssetEngine:
    def test_build_cross_asset_signals_and_regions_surfaces_macro_shipping_and_regions(self):
        from world_cross_asset_engine import build_cross_asset_signals_and_regions

        payload = build_cross_asset_signals_and_regions(
            macro_rates_fx={
                "instruments": [
                    {"key": "ca_risk_appetite", "score": 36.0},
                    {"key": "ca_us_momentum", "score": 42.0},
                    {"key": "ca_vix_level", "score": 30.0},
                    {"key": "ca_a50_premium", "score": 46.0},
                    {"key": "ca_hk_sentiment", "score": 44.0},
                ]
            },
            commodity_terminal={
                "commodities": [
                    {
                        "name": "原油",
                        "change_pct_1d": 6.2,
                        "change_pct_5d": 12.8,
                        "pressure_level": "critical",
                    }
                ]
            },
            shipping_ais={
                "routes": [
                    {
                        "route": "霍尔木兹海峡",
                        "restriction_scope": "partial",
                        "estimated_flow_impact_pct": 55.0,
                        "affected_countries": ["伊朗", "沙特"],
                    }
                ]
            },
            freight_rates={
                "lanes": [
                    {
                        "route": "中东-亚洲",
                        "rate_change_pct_1d": 8.0,
                        "insurance_premium_bp": 42.0,
                    }
                ]
            },
            official_fulltext={
                "documents": [
                    {"title": "能源保供通知"},
                    {"title": "数字基础设施推进通知"},
                ]
            },
            event_cascades=[
                {
                    "severity": "critical",
                    "estimated_flow_impact_pct": 55.0,
                    "affected_routes": ["霍尔木兹海峡"],
                    "affected_countries": ["伊朗", "沙特"],
                    "exposed_industries": ["油运", "航空", "化工下游"],
                }
            ],
        )

        keys = {item["key"] for item in payload["signals"]}
        assert "macro_risk" in keys
        assert "shipping_pressure" in keys
        assert "commodity_pressure" in keys
        assert "official_confirm" in keys
        assert payload["regional_pressures"]
        assert payload["regional_pressures"][0]["affected_routes"]
