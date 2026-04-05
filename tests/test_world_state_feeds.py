import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestWorldStateFeeds:
    def test_refresh_world_state_feeds_builds_official_timeline_and_research(self, monkeypatch, tmp_path):
        import world_state_feeds as feeds

        monkeypatch.setattr(feeds, "_utcnow", lambda: datetime(2026, 3, 30, 9, 30, 0))

        monkeypatch.setattr(feeds, "DATA_DIR", tmp_path)
        monkeypatch.setattr(feeds, "POLICY_DIRECTION_CATALOG", tmp_path / "policy_direction_catalog.json")
        monkeypatch.setattr(feeds, "POLICY_OFFICIAL_WATCH", tmp_path / "policy_official_watch.json")
        monkeypatch.setattr(feeds, "POLICY_OFFICIAL_CARDS", tmp_path / "policy_official_cards.json")
        monkeypatch.setattr(feeds, "POLICY_OFFICIAL_INGEST", tmp_path / "policy_official_ingest.json")
        monkeypatch.setattr(feeds, "POLICY_EXECUTION_TIMELINE", tmp_path / "policy_execution_timeline.json")
        monkeypatch.setattr(feeds, "INDUSTRY_CAPITAL_COMPANY_MAP", tmp_path / "industry_capital_company_map.json")
        monkeypatch.setattr(feeds, "INDUSTRY_CAPITAL_RESEARCH_LOG", tmp_path / "industry_capital_research_log.json")
        monkeypatch.setattr(feeds, "NEWS_DIGEST", tmp_path / "news_digest.json")
        monkeypatch.setattr(feeds, "SIGNALS_DB", tmp_path / "signals_db.json")

        (tmp_path / "policy_direction_catalog.json").write_text(
            json.dumps(
                {
                    "directions": [
                        {
                            "id": "ai-digital",
                            "direction": "AI与数字基础设施",
                            "policy_bucket": "国家战略",
                            "focus_sectors": ["科技", "半导体"],
                            "keywords": ["人工智能", "算力", "半导体", "数字中国"],
                            "milestones": ["政策定调", "预算落地", "招标", "交付"],
                            "upstream": ["算力芯片"],
                            "midstream": ["服务器"],
                            "downstream": ["行业应用"],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (tmp_path / "policy_official_watch.json").write_text(
            json.dumps(
                {
                    "directions": [
                        {
                            "id": "ai-digital",
                            "official_sources": ["国务院", "工信部"],
                            "official_watchpoints": ["算力建设", "招标兑现"],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (tmp_path / "policy_official_cards.json").write_text(
            json.dumps(
                {
                    "directions": [
                        {
                            "id": "ai-digital",
                            "official_cards": [
                                {
                                    "title": "数字中国主线继续推进",
                                    "source": "国务院",
                                    "excerpt": "数字基础设施继续加码。",
                                    "why_it_matters": "看预算、招标和交付。",
                                    "next_watch": "继续看采购和订单。",
                                }
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (tmp_path / "policy_official_ingest.json").write_text(
            json.dumps({"directions": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        (tmp_path / "policy_execution_timeline.json").write_text(
            json.dumps({"directions": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        (tmp_path / "industry_capital_company_map.json").write_text(
            json.dumps(
                {
                    "directions": [
                        {
                            "id": "ai-digital",
                            "company_watchlist": [
                                {"code": "603019", "name": "中科曙光"},
                            ],
                            "research_targets": ["算力设备商"],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (tmp_path / "industry_capital_research_log.json").write_text(
            json.dumps({"items": [], "last_update": "2026-03-29T10:00:00"}, ensure_ascii=False),
            encoding="utf-8",
        )
        (tmp_path / "news_digest.json").write_text(
            json.dumps(
                {
                    "timestamp": "2026-03-30T09:20:00",
                    "events": [
                        {
                            "title": "算力基础设施建设提速",
                            "summary": "人工智能和半导体链条受益。",
                            "strategy_implications": "继续观察预算和订单兑现。",
                            "timestamp": "2026-03-30T09:10:00",
                            "category": "tech",
                            "affected_sectors": ["半导体", "科技"],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (tmp_path / "signals_db.json").write_text(
            json.dumps(
                [
                    {
                        "date": "2026-03-28",
                        "strategy": "趋势跟踪选股",
                        "code": "603019",
                        "name": "中科曙光",
                        "verify": {
                            "t1": {"return_pct": 2.1},
                            "t3": {"return_pct": 3.8},
                            "t5": {"return_pct": 4.2},
                        },
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        result = feeds.refresh_world_state_feeds()

        assert result["official_ingest_count"] == 1
        assert result["execution_timeline_count"] == 1
        assert result["research_item_count"] >= 1

        ingest = json.loads((tmp_path / "policy_official_ingest.json").read_text(encoding="utf-8"))
        entries = ingest["directions"][0]["official_source_entries"]
        assert entries
        assert entries[0]["source_origin"] == "auto_runtime"

        timeline = json.loads((tmp_path / "policy_execution_timeline.json").read_text(encoding="utf-8"))
        assert timeline["directions"][0]["timeline_events"]

        research = json.loads((tmp_path / "industry_capital_research_log.json").read_text(encoding="utf-8"))
        assert research["items"]
        assert research["items"][0]["source"] == "系统自动研究"
        assert research["items"][0]["status"] in {"验证增强", "继续验证"}

    def test_ensure_world_state_feeds_fresh_rebuilds_missing_files(self, monkeypatch, tmp_path):
        import world_state_feeds as feeds

        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setattr(feeds, "_utcnow", lambda: datetime(2026, 3, 30, 9, 30, 0))
        monkeypatch.setattr(feeds, "DATA_DIR", tmp_path)
        monkeypatch.setattr(feeds, "POLICY_DIRECTION_CATALOG", tmp_path / "policy_direction_catalog.json")
        monkeypatch.setattr(feeds, "POLICY_OFFICIAL_WATCH", tmp_path / "policy_official_watch.json")
        monkeypatch.setattr(feeds, "POLICY_OFFICIAL_CARDS", tmp_path / "policy_official_cards.json")
        monkeypatch.setattr(feeds, "POLICY_OFFICIAL_INGEST", tmp_path / "policy_official_ingest.json")
        monkeypatch.setattr(feeds, "POLICY_EXECUTION_TIMELINE", tmp_path / "policy_execution_timeline.json")
        monkeypatch.setattr(feeds, "INDUSTRY_CAPITAL_COMPANY_MAP", tmp_path / "industry_capital_company_map.json")
        monkeypatch.setattr(feeds, "INDUSTRY_CAPITAL_RESEARCH_LOG", tmp_path / "industry_capital_research_log.json")
        monkeypatch.setattr(feeds, "NEWS_DIGEST", tmp_path / "news_digest.json")
        monkeypatch.setattr(feeds, "SIGNALS_DB", tmp_path / "signals_db.json")

        minimal_payload = {"directions": [{"id": "ai-digital", "direction": "AI与数字基础设施", "keywords": ["算力"]}]}
        for name in [
            "policy_direction_catalog.json",
            "policy_official_watch.json",
            "policy_official_cards.json",
            "industry_capital_company_map.json",
        ]:
            (tmp_path / name).write_text(json.dumps(minimal_payload, ensure_ascii=False), encoding="utf-8")
        (tmp_path / "news_digest.json").write_text(json.dumps({"events": [], "timestamp": "2026-03-30T09:00:00"}, ensure_ascii=False), encoding="utf-8")
        (tmp_path / "signals_db.json").write_text("[]", encoding="utf-8")

        refreshed = feeds.ensure_world_state_feeds_fresh(max_age_hours=1)

        assert refreshed is True
        assert (tmp_path / "policy_official_ingest.json").exists()
        assert (tmp_path / "policy_execution_timeline.json").exists()
        assert (tmp_path / "industry_capital_research_log.json").exists()
