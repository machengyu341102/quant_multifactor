import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestWorldHardSourceFeeds:
    def test_refresh_world_hard_sources_builds_fallback_payloads(self, monkeypatch, tmp_path):
        import world_hard_source_feeds as feeds

        monkeypatch.delenv("WORLD_OFFICIAL_FULLTEXT_URL", raising=False)
        monkeypatch.delenv("WORLD_SHIPPING_AIS_URL", raising=False)
        monkeypatch.delenv("WORLD_FREIGHT_RATES_URL", raising=False)
        monkeypatch.delenv("WORLD_COMMODITY_TERMINAL_URL", raising=False)
        monkeypatch.delenv("WORLD_MACRO_RATES_FX_URL", raising=False)

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

        result = feeds.refresh_world_hard_sources(now=datetime(2026, 3, 31, 10, 30, 0))

        assert result["official_fulltext_count"] >= 1
        assert result["shipping_ais_count"] >= 1
        assert result["freight_rates_count"] >= 1
        assert result["commodity_terminal_count"] >= 1
        assert result["macro_rates_fx_count"] >= 1
        assert feeds.WORLD_OFFICIAL_FULLTEXT.exists()
        assert feeds.WORLD_SHIPPING_AIS.exists()
        assert feeds.WORLD_FREIGHT_RATES.exists()
        assert feeds.WORLD_COMMODITY_TERMINAL.exists()
        assert feeds.WORLD_MACRO_RATES_FX.exists()

    def test_refresh_world_hard_sources_sends_auth_header(self, monkeypatch, tmp_path):
        import world_hard_source_feeds as feeds

        monkeypatch.setenv("WORLD_OFFICIAL_FULLTEXT_URL", "https://gateway.local/official")
        monkeypatch.setenv("WORLD_HARD_SOURCE_AUTH_TOKEN", "gateway-secret")
        monkeypatch.delenv("WORLD_HARD_SOURCE_AUTH_HEADER", raising=False)
        monkeypatch.delenv("WORLD_SHIPPING_AIS_URL", raising=False)
        monkeypatch.delenv("WORLD_FREIGHT_RATES_URL", raising=False)
        monkeypatch.delenv("WORLD_COMMODITY_TERMINAL_URL", raising=False)
        monkeypatch.delenv("WORLD_MACRO_RATES_FX_URL", raising=False)

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

        feeds.POLICY_OFFICIAL_INGEST.write_text('{"directions": []}', encoding="utf-8")
        feeds.NEWS_DIGEST.write_text('{"events": []}', encoding="utf-8")

        captured: dict[str, str] = {}

        class _FakeResponse:
            headers = {"Content-Type": "application/json"}

            def read(self):
                return '{"documents":[{"title":"官方更新","source":"国务院","content":"test"}]}'.encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def fake_urlopen(request, timeout=0):
            captured["authorization"] = request.headers.get("Authorization") or request.headers.get("authorization") or ""
            return _FakeResponse()

        monkeypatch.setattr(feeds.urllib.request, "urlopen", fake_urlopen)

        result = feeds.refresh_world_hard_sources(now=datetime(2026, 3, 31, 10, 30, 0))

        assert result["official_fulltext_count"] == 1
        assert captured["authorization"] == "Bearer gateway-secret"

    def test_refresh_world_hard_sources_uses_gateway_base_url(self, monkeypatch):
        import world_hard_source_feeds as feeds

        monkeypatch.delenv("WORLD_OFFICIAL_FULLTEXT_URL", raising=False)
        monkeypatch.setenv("WORLD_DATA_GATEWAY_BASE_URL", "http://127.0.0.1:18080")

        assert feeds._resolve_remote_url("official_fulltext") == "http://127.0.0.1:18080/api/world-gateway/official-fulltext"

    def test_refresh_world_hard_sources_reuses_gateway_token_as_auth(self, monkeypatch):
        import world_hard_source_feeds as feeds

        monkeypatch.delenv("WORLD_HARD_SOURCE_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("WORLD_DATA_GATEWAY_TOKEN", "shared-token")

        headers = feeds._build_remote_headers("official_fulltext")

        assert headers["Authorization"] == "Bearer shared-token"
