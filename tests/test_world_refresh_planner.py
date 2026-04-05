import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestWorldRefreshPlanner:
    def test_build_world_refresh_plan_escalates_on_critical_oil_event(self):
        from world_refresh_planner import build_world_refresh_plan

        plan = build_world_refresh_plan(
            now=datetime(2026, 3, 30, 10, 5, 0),
            digest={
                "events": [
                    {
                        "title": "霍尔木兹海峡几乎完全关闭，原油和天然气价格飙升",
                        "summary": "运输和保险成本快速上行。",
                        "strategy_implications": "继续跟踪放行比例和通行限制。",
                        "category": "commodity",
                        "impact_magnitude": 5,
                        "timestamp": "2026-03-30T10:00:00",
                    }
                ]
            },
        )

        assert plan["mode"] == "event_escalated"
        assert plan["news_interval_minutes"] == 5
        assert plan["feeds_interval_minutes"] == 5
        assert plan["hard_source_interval_minutes"] == 10
        assert plan["policy_interval_minutes"] == 15
        assert plan["escalation_active"] is True
        assert plan["top_trigger"]

    def test_build_world_refresh_plan_uses_overnight_baseline_without_trigger(self):
        from world_refresh_planner import build_world_refresh_plan

        plan = build_world_refresh_plan(
            now=datetime(2026, 3, 31, 2, 30, 0),
            digest={"events": []},
        )

        assert plan["active_window"] == "overnight"
        assert plan["news_interval_minutes"] == 180
        assert plan["feeds_interval_minutes"] == 180
        assert plan["hard_source_interval_minutes"] == 240
        assert plan["policy_interval_minutes"] == 240

    def test_build_world_refresh_plan_switches_to_cooling_on_easing_event(self):
        from world_refresh_planner import build_world_refresh_plan

        plan = build_world_refresh_plan(
            now=datetime(2026, 3, 30, 14, 5, 0),
            digest={
                "events": [
                    {
                        "title": "霍尔木兹海峡恢复部分通行，油轮复航",
                        "summary": "风险溢价回落，市场观察复航节奏。",
                        "strategy_implications": "继续跟踪恢复比例。",
                        "category": "commodity",
                        "impact_magnitude": 4,
                        "timestamp": "2026-03-30T14:00:00",
                    }
                ]
            },
        )

        assert plan["mode"] == "event_cooling"
        assert plan["news_interval_minutes"] == 15
        assert plan["hard_source_interval_minutes"] == 20
        assert plan["policy_interval_minutes"] == 30

    def test_run_world_refresh_tick_runs_due_jobs_and_updates_runtime_state(self, monkeypatch, tmp_path):
        import world_refresh_planner as planner

        monkeypatch.setattr(planner, "EXPORT_DIR", tmp_path / "exports")
        monkeypatch.setattr(planner, "RUNTIME_STATE", tmp_path / "exports" / "runtime_state.json")
        monkeypatch.setattr(planner, "NEWS_DIGEST", tmp_path / "news_digest.json")
        Path(planner.NEWS_DIGEST).write_text('{"events":[]}', encoding="utf-8")

        monkeypatch.setattr(
            planner,
            "build_world_refresh_plan",
            lambda now=None, digest=None, runtime_state=None: {
                "mode": "baseline",
                "mode_label": "基础轮询",
                "active_window": "intraday",
                "active_window_label": "盘中",
                "escalation_active": False,
                "top_trigger": None,
                "trigger_type": None,
                "news_interval_minutes": 15,
                "feeds_interval_minutes": 15,
                "hard_source_interval_minutes": 30,
                "policy_interval_minutes": 30,
                "overnight_watch": False,
                "summary": "测试",
                "next_focus": [],
                "next_news_due_at": None,
                "next_feeds_due_at": None,
                "next_hard_sources_due_at": None,
                "next_policy_due_at": None,
                "overdue_sources": ["news_digest", "world_state_feeds", "world_hard_sources", "official_policy"],
                "generated_at": "2026-03-30T10:00:00",
            },
        )

        calls = {"news": 0, "feeds": 0, "hard": 0}

        result = planner.run_world_refresh_tick(
            now=datetime(2026, 3, 30, 10, 0, 0),
            run_global_news=lambda: calls.__setitem__("news", calls["news"] + 1),
            run_world_state_feeds=lambda: calls.__setitem__("feeds", calls["feeds"] + 1),
            run_world_hard_sources=lambda: calls.__setitem__("hard", calls["hard"] + 1),
        )

        assert calls == {"news": 1, "feeds": 1, "hard": 1}
        assert result["ran_global_news"] is True
        assert result["ran_world_state_feeds"] is True
        assert result["ran_world_hard_sources"] is True
        assert result["ran_policy_refresh"] is True
        assert result["last_global_news_at"] == "2026-03-30T10:00:00"
        assert result["last_world_state_feeds_at"] == "2026-03-30T10:00:00"
        assert result["last_world_hard_sources_at"] == "2026-03-30T10:00:00"
        assert result["last_policy_refresh_at"] == "2026-03-30T10:00:00"
