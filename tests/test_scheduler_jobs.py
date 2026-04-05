import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestExecutionPolicyExportJob:
    def test_job_execution_policy_export_normalizes_period_and_returns_manifest(self, monkeypatch):
        import scheduler_jobs

        class DummyManifest:
            export_id = "execution-policy-daily-20260330093000"
            market_phase_label = "弱势拉扯"
            risk_budget_pct = 38.0

        called = {}

        def fake_write(period: str):
            called["period"] = period
            return DummyManifest()

        monkeypatch.setattr("api_server._write_execution_policy_export", fake_write)

        result = scheduler_jobs.job_execution_policy_export("unexpected")

        assert called["period"] == "daily"
        assert result.export_id == "execution-policy-daily-20260330093000"


class TestWorldStateExportJob:
    def test_job_world_state_export_normalizes_period_and_returns_manifest(self, monkeypatch):
        import scheduler_jobs

        class DummyManifest:
            export_id = "world-state-daily-20260330093000"
            market_phase_label = "震荡轮动"
            dominant_component = "产业链控制力"

        called = {}

        def fake_write(period: str):
            called["period"] = period
            return DummyManifest()

        monkeypatch.setattr("api_server._write_world_state_export", fake_write)

        result = scheduler_jobs.job_world_state_export("unexpected")

        assert called["period"] == "daily"
        assert result.export_id == "world-state-daily-20260330093000"


class TestWorldStateFeedsJob:
    def test_job_world_state_feeds_returns_refresh_summary(self, monkeypatch):
        import scheduler_jobs

        called = {}

        def fake_refresh():
            called["ok"] = True
            return {
                "official_ingest_count": 9,
                "execution_timeline_count": 9,
                "research_item_count": 6,
            }

        monkeypatch.setattr("world_state_feeds.refresh_world_state_feeds", fake_refresh)

        result = scheduler_jobs.job_world_state_feeds()

        assert called["ok"] is True
        assert result["official_ingest_count"] == 9


class TestWorldHardSourcesJob:
    def test_job_world_hard_sources_returns_refresh_summary(self, monkeypatch):
        import scheduler_jobs

        called = {}

        def fake_refresh():
            called["ok"] = True
            return {
                "official_fulltext_count": 4,
                "shipping_ais_count": 3,
                "freight_rates_count": 2,
                "commodity_terminal_count": 5,
                "macro_rates_fx_count": 6,
            }

        monkeypatch.setattr("world_hard_source_feeds.refresh_world_hard_sources", fake_refresh)

        result = scheduler_jobs.job_world_hard_sources()

        assert called["ok"] is True
        assert result["official_fulltext_count"] == 4


class TestWorldRefreshTickJob:
    def test_job_world_refresh_tick_delegates_and_returns_plan(self, monkeypatch):
        import scheduler_jobs

        captured = {}

        def fake_run_world_refresh_tick(*, force=False, run_global_news=None, run_world_state_feeds=None, run_world_hard_sources=None):
            captured["force"] = force
            captured["run_global_news"] = callable(run_global_news)
            captured["run_world_state_feeds"] = callable(run_world_state_feeds)
            captured["run_world_hard_sources"] = callable(run_world_hard_sources)
            return {
                "plan": {
                    "mode_label": "事件升级",
                    "active_window_label": "盘中",
                    "news_interval_minutes": 5,
                    "feeds_interval_minutes": 5,
                    "hard_source_interval_minutes": 10,
                    "policy_interval_minutes": 15,
                },
                "ran_global_news": True,
                "ran_world_state_feeds": True,
                "ran_world_hard_sources": True,
                "ran_policy_refresh": True,
            }

        monkeypatch.setattr("world_refresh_planner.run_world_refresh_tick", fake_run_world_refresh_tick)

        result = scheduler_jobs.job_world_refresh_tick(force=True)

        assert captured["force"] is True
        assert captured["run_global_news"] is True
        assert captured["run_world_state_feeds"] is True
        assert captured["run_world_hard_sources"] is True
        assert result["plan"]["mode_label"] == "事件升级"
        assert result["ran_world_hard_sources"] is True
        assert result["ran_policy_refresh"] is True


class TestLearningProgressJob:
    def test_job_learning_progress_uses_unified_snapshot_wording(self, monkeypatch):
        import scheduler_jobs

        class DummyScheduler:
            def is_trading_day(self):
                return True

        sent = {}

        monkeypatch.setattr(scheduler_jobs, "_get_scheduler", lambda: DummyScheduler())
        monkeypatch.setattr("learning_engine.check_learning_health", lambda: {"checks": [{"status": "ok"}] * 4})
        monkeypatch.setattr("learning_engine.analyze_factor_importance", lambda strat: [{"correlation": 0.03}])
        monkeypatch.setattr("db_store.load_scorecard", lambda days=1: [{"strategy": "趋势跟踪选股"}] * 5)
        monkeypatch.setattr(
            "api_server._build_signals",
            lambda: [
                SimpleNamespace(strategy="趋势跟踪选股"),
                SimpleNamespace(strategy="低吸回调选股"),
                SimpleNamespace(strategy="趋势跟踪选股"),
            ],
        )
        monkeypatch.setattr("api_server._build_system_status", lambda: SimpleNamespace(today_signals=3))
        monkeypatch.setattr(
            "api_server._build_learning_progress",
            lambda: SimpleNamespace(today_cycles=2, decision_accuracy=0.68),
        )
        monkeypatch.setattr(
            "api_server._build_learning_advance_status",
            lambda: SimpleNamespace(status="pending", today_completed=False, ingested_signals=1),
        )
        monkeypatch.setattr(
            "notifier.notify_wechat_raw",
            lambda title, body: sent.update({"title": title, "body": body}),
        )

        scheduler_jobs.job_learning_progress()

        assert sent["title"] == "学习数据监控"
        assert "盘中候选: 3 条 / 正式信号: 3 条 / 正式入库: 1 条 / 回填验证: 5 条" in sent["body"]
        assert "今日数据:" not in sent["body"]
        assert "候选分布: 趋势跟踪选股2条, 低吸回调选股1条" in sent["body"]
        assert "日日精进: pending / 待收口" in sent["body"]
