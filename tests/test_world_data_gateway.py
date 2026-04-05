import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestWorldDataGateway:
    def test_gateway_requires_token_when_configured(self, monkeypatch, tmp_path):
        import world_data_gateway as gateway
        import world_hard_source_feeds as feeds

        monkeypatch.setenv("WORLD_DATA_GATEWAY_TOKEN", "secret-token")
        monkeypatch.setattr(feeds, "WORLD_OFFICIAL_FULLTEXT", tmp_path / "world_official_fulltext.json")
        monkeypatch.setattr(feeds, "WORLD_SHIPPING_AIS", tmp_path / "world_shipping_ais.json")
        monkeypatch.setattr(feeds, "WORLD_FREIGHT_RATES", tmp_path / "world_freight_rates.json")
        monkeypatch.setattr(feeds, "WORLD_COMMODITY_TERMINAL", tmp_path / "world_commodity_terminal.json")
        monkeypatch.setattr(feeds, "WORLD_MACRO_RATES_FX", tmp_path / "world_macro_rates_fx.json")
        monkeypatch.setattr(
            feeds,
            "_SOURCE_PATHS",
            {
                "official_fulltext": feeds.WORLD_OFFICIAL_FULLTEXT,
                "shipping_ais": feeds.WORLD_SHIPPING_AIS,
                "freight_rates": feeds.WORLD_FREIGHT_RATES,
                "commodity_terminal": feeds.WORLD_COMMODITY_TERMINAL,
                "macro_rates_fx": feeds.WORLD_MACRO_RATES_FX,
            },
        )

        with TestClient(gateway.app) as client:
            unauthorized = client.get("/api/world-gateway/source-status")
            assert unauthorized.status_code == 401

            authorized = client.get(
                "/api/world-gateway/source-status",
                headers={"Authorization": "Bearer secret-token"},
            )
            assert authorized.status_code == 200
            payload = authorized.json()
            assert payload["gateway_auth_enabled"] is True
            assert len(payload["sources"]) == 5

    def test_gateway_serves_fallback_payloads(self, monkeypatch, tmp_path):
        import world_data_gateway as gateway
        import world_hard_source_feeds as feeds

        monkeypatch.delenv("WORLD_DATA_GATEWAY_TOKEN", raising=False)
        monkeypatch.setattr(feeds, "NEWS_DIGEST", tmp_path / "news_digest.json")
        monkeypatch.setattr(feeds, "POLICY_OFFICIAL_INGEST", tmp_path / "policy_official_ingest.json")
        monkeypatch.setattr(feeds, "WORLD_OFFICIAL_FULLTEXT", tmp_path / "world_official_fulltext.json")
        monkeypatch.setattr(feeds, "WORLD_SHIPPING_AIS", tmp_path / "world_shipping_ais.json")
        monkeypatch.setattr(feeds, "WORLD_FREIGHT_RATES", tmp_path / "world_freight_rates.json")
        monkeypatch.setattr(feeds, "WORLD_COMMODITY_TERMINAL", tmp_path / "world_commodity_terminal.json")
        monkeypatch.setattr(feeds, "WORLD_MACRO_RATES_FX", tmp_path / "world_macro_rates_fx.json")
        monkeypatch.setattr(
            feeds,
            "_SOURCE_PATHS",
            {
                "official_fulltext": feeds.WORLD_OFFICIAL_FULLTEXT,
                "shipping_ais": feeds.WORLD_SHIPPING_AIS,
                "freight_rates": feeds.WORLD_FREIGHT_RATES,
                "commodity_terminal": feeds.WORLD_COMMODITY_TERMINAL,
                "macro_rates_fx": feeds.WORLD_MACRO_RATES_FX,
            },
        )

        feeds.NEWS_DIGEST.write_text(
            """
            {
              "events": [
                {
                  "title": "霍尔木兹海峡部分限行，油轮绕航增加",
                  "summary": "原油与 LNG 运输受扰动。",
                  "strategy_implications": "继续跟踪放行船型与流量影响。",
                  "category": "commodity",
                  "impact_magnitude": 5,
                  "timestamp": "2026-03-31T10:00:00"
                }
              ]
            }
            """,
            encoding="utf-8",
        )
        feeds.POLICY_OFFICIAL_INGEST.write_text(
            """
            {
              "directions": [
                {
                  "direction": "AI与数字基础设施",
                  "official_source_entries": [
                    {
                      "title": "数字基础设施专项推进",
                      "issuer": "国务院",
                      "published_at": "2026-03-30",
                      "excerpt": "继续推进算力和数据基础设施建设。",
                      "watch_tags": ["算力", "数字基础设施"]
                    }
                  ]
                }
              ]
            }
            """,
            encoding="utf-8",
        )

        with TestClient(gateway.app) as client:
            official = client.get("/api/world-gateway/official-fulltext")
            shipping = client.get("/api/world-gateway/shipping-ais")
            freight = client.get("/api/world-gateway/freight-rates")
            commodity = client.get("/api/world-gateway/commodity-terminal")
            macro = client.get("/api/world-gateway/macro-rates-fx")

        assert official.status_code == 200
        assert shipping.status_code == 200
        assert freight.status_code == 200
        assert commodity.status_code == 200
        assert macro.status_code == 200
        assert len(official.json().get("documents", [])) >= 1
        assert len(shipping.json().get("routes", [])) >= 1
        assert isinstance(freight.json().get("lanes", []), list)
        assert isinstance(commodity.json().get("commodities", []), list)
        assert isinstance(macro.json().get("instruments", []), list)

    def test_gateway_marks_official_public_probe_failure(self, monkeypatch, tmp_path):
        import world_data_gateway as gateway
        import world_hard_source_feeds as feeds

        monkeypatch.delenv("WORLD_DATA_GATEWAY_TOKEN", raising=False)
        monkeypatch.setattr(feeds, "NEWS_DIGEST", tmp_path / "news_digest.json")
        monkeypatch.setattr(feeds, "POLICY_OFFICIAL_INGEST", tmp_path / "policy_official_ingest.json")
        monkeypatch.setattr(feeds, "WORLD_OFFICIAL_FULLTEXT", tmp_path / "world_official_fulltext.json")
        monkeypatch.setattr(feeds, "WORLD_SHIPPING_AIS", tmp_path / "world_shipping_ais.json")
        monkeypatch.setattr(feeds, "WORLD_FREIGHT_RATES", tmp_path / "world_freight_rates.json")
        monkeypatch.setattr(feeds, "WORLD_COMMODITY_TERMINAL", tmp_path / "world_commodity_terminal.json")
        monkeypatch.setattr(feeds, "WORLD_MACRO_RATES_FX", tmp_path / "world_macro_rates_fx.json")
        monkeypatch.setattr(
            feeds,
            "_SOURCE_PATHS",
            {
                "official_fulltext": feeds.WORLD_OFFICIAL_FULLTEXT,
                "shipping_ais": feeds.WORLD_SHIPPING_AIS,
                "freight_rates": feeds.WORLD_FREIGHT_RATES,
                "commodity_terminal": feeds.WORLD_COMMODITY_TERMINAL,
                "macro_rates_fx": feeds.WORLD_MACRO_RATES_FX,
            },
        )
        feeds.POLICY_OFFICIAL_INGEST.write_text(
            """
            {
              "directions": [
                {
                  "direction": "AI与数字基础设施",
                  "official_source_entries": [
                    {
                      "title": "公开官方口径测试",
                      "issuer": "国务院",
                      "published_at": "2026-03-31",
                      "reference_url": "https://www.gov.cn/example",
                      "watch_tags": ["算力"]
                    }
                  ]
                }
              ]
            }
            """,
            encoding="utf-8",
        )

        def fake_http_request_text(*args, **kwargs):
            raise RuntimeError("network down")

        monkeypatch.setattr(gateway, "_http_request_text", fake_http_request_text)

        with TestClient(gateway.app) as client:
            official = client.get("/api/world-gateway/official-fulltext")
            status = client.get("/api/world-gateway/source-status")

        assert official.status_code == 200
        payload = official.json()
        assert payload["fetch_mode"] == "derived"
        assert payload["block_reason"] == "official_public_references_unreachable"
        assert payload["candidate_reference_count"] == 1
        status_payload = status.json()
        official_status = next(item for item in status_payload["sources"] if item["key"] == "official_fulltext")
        assert official_status["block_reason"] == "official_public_references_unreachable"
