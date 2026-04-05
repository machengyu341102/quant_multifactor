"""
api_server.py 测试
=================
覆盖: 诊股增强、日日精进状态、运维建议
"""

import os
import sys
from datetime import date, datetime, timedelta
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestBuildStockDiagnosis:
    def test_enriches_diagnosis_with_regime_and_position(self, monkeypatch):
        import api_server
        import smart_trader
        import stock_analyzer

        monkeypatch.setattr(
            stock_analyzer,
            "analyze_stock",
            lambda code, push=False, journal=False: {
                "code": code,
                "name": "平安银行",
                "price": 10.6,
                "total_score": 0.78,
                "direction": "bullish",
                "signal_direction": "long",
                "actionable": True,
                "verdict": "看多",
                "advice": "量价配合",
                "report_text": "测试报告",
                "stop_loss": 10.1,
                "take_profit": 11.7,
                "scores": {
                    "trend": 0.82,
                    "momentum": 0.75,
                    "volume": 0.68,
                    "position": 0.55,
                    "fund_flow": 0.72,
                },
                "details": {
                    "trend": ["趋势向上"],
                    "momentum": ["动量不弱"],
                    "volume": ["量能配合"],
                    "position": ["位置中性"],
                    "fund_flow": ["主力流入"],
                },
            },
        )
        monkeypatch.setattr(
            smart_trader,
            "detect_market_regime",
            lambda: {"regime": "bull", "score": 0.81},
        )
        monkeypatch.setattr(
            api_server,
            "_build_system_status",
            lambda: api_server.SystemStatus(
                status="running",
                uptime_hours=12.0,
                health_score=88,
                today_signals=3,
                active_strategies=8,
                ooda_cycles=100,
                decision_accuracy=0.69,
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_learning_progress",
            lambda: api_server.LearningProgress(
                today_cycles=3,
                factor_adjustments=12,
                online_updates=8,
                experiments_running=2,
                new_factors_deployed=1,
                decision_accuracy=0.71,
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_strategies",
            lambda: [
                api_server.StrategyPerformance(
                    id="overnight",
                    name="隔夜选股",
                    status="active",
                    win_rate=71.2,
                    avg_return=0.18,
                    signal_count=320,
                    last_signal_time="2026-03-12 09:35:00",
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_signals",
            lambda days=1: [
                api_server.Signal(
                    id="sig-1",
                    code="000001",
                    name="平安银行",
                    strategy="overnight",
                    score=0.92,
                    price=10.6,
                    change_pct=1.2,
                    buy_price=10.5,
                    stop_loss=10.1,
                    target_price=11.7,
                    risk_reward=2.1,
                    timestamp="2026-03-12T09:35:00",
                    consensus_count=2,
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_load_portfolio",
            lambda: {
                "positions": [
                    {
                        "code": "000001",
                        "quantity": 300,
                        "profit_loss_pct": 4.2,
                    }
                ]
            },
        )

        diagnosis = api_server._build_stock_diagnosis("000001")

        assert diagnosis.actionable is True
        assert diagnosis.in_portfolio is True
        assert diagnosis.position_quantity == 300
        assert diagnosis.in_signal_board is True
        assert diagnosis.regime == "bull"
        assert diagnosis.top_strategy == "隔夜选股"
        assert diagnosis.risk_flags
        assert diagnosis.next_actions


class TestLearningAdvanceStatus:
    def test_recommends_running_learning_when_today_missing(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_build_learning_progress",
            lambda: api_server.LearningProgress(
                today_cycles=1,
                factor_adjustments=5,
                online_updates=2,
                experiments_running=1,
                new_factors_deployed=0,
                decision_accuracy=0.61,
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_learning_health_snapshot",
            lambda: {
                "status": "warning",
                "checks": [
                    {
                        "check": "online_learning",
                        "status": "warning",
                        "detail": "48h 未活跃",
                    }
                ],
            },
        )
        monkeypatch.setattr(
            api_server,
            "_learning_advance_state_snapshot",
            lambda: {
                "status": "idle",
                "in_progress": False,
                "last_started_at": None,
                "current_run_started_at": None,
                "last_completed_at": (
                    datetime.now() - timedelta(days=1, hours=2)
                ).isoformat(timespec="seconds"),
                "last_requested_by": "admin",
                "last_error": None,
                "last_report_excerpt": "",
                "last_ingested_signals": 1,
                "last_verified_signals": 3,
                "last_reviewed_decisions": 2,
            },
        )

        status = api_server._build_learning_advance_status()

        assert status.today_completed is False
        assert status.status == "pending"
        assert status.health_status == "warning"
        assert any("今天还没有完成日日精进" in item for item in status.recommendations)
        assert any(check.name == "online_learning" for check in status.checks)


class TestLearningHealthSnapshot:
    def test_prefers_newer_learning_health_file_over_embedded_state(self, monkeypatch, tmp_path):
        import api_server
        import json

        learning_state_path = tmp_path / "learning_state.json"
        health_file_path = tmp_path / "learning_health.json"

        learning_state_path.write_text(
            json.dumps(
                {
                    "health": {
                        "status": "critical",
                        "timestamp": "2026-03-30T16:30:21",
                        "checks": [
                            {
                                "check": "scorecard_freshness",
                                "status": "critical",
                                "detail": "近3天无新数据 → 学习引擎无输入",
                            }
                        ],
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        health_file_path.write_text(
            json.dumps(
                {
                    "status": "warning",
                    "timestamp": "2026-03-31T12:11:44",
                    "checks": [
                        {
                            "check": "scorecard_freshness",
                            "status": "warning",
                            "detail": "近3天无新回填，但 signals_db 仍有 222 条待验证/存量信号",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(api_server, "_LEARNING_STATE", str(learning_state_path))
        monkeypatch.setattr(api_server, "_DIR", str(tmp_path))

        health = api_server._build_learning_health_snapshot()

        assert health["status"] == "warning"
        assert health["checks"][0]["detail"] == "近3天无新回填，但 signals_db 仍有 222 条待验证/存量信号"


class TestOpsRecommendations:
    def test_prioritizes_readiness_and_learning_alerts(self):
        import api_server

        recommendations = api_server._build_ops_recommendations(
            ready=False,
            readiness_issues=["signals: load failed"],
            error_rate=0.052,
            p95_latency_ms=1480,
            system_health_score=76,
            data_status=api_server.OpsDataStatus(
                scorecard_records=0,
                trade_journal_records=0,
                signal_count=2,
                active_positions=4,
                feedback_items=3,
                push_devices=1,
            ),
            learning=api_server.LearningProgress(
                today_cycles=1,
                factor_adjustments=8,
                online_updates=4,
                experiments_running=1,
                new_factors_deployed=0,
                decision_accuracy=0.6,
            ),
            daily_advance=api_server.LearningAdvanceStatus(
                status="pending",
                in_progress=False,
                today_completed=False,
                last_started_at=None,
                current_run_started_at=None,
                last_completed_at=(date.today() - timedelta(days=1)).isoformat(),
                last_requested_by="admin",
                stale_hours=30.5,
                health_status="warning",
                summary="今天还没完成完整学习",
                last_error=None,
                last_report_excerpt="",
                ingested_signals=0,
                verified_signals=0,
                reviewed_decisions=0,
                checks=[],
                recommendations=[],
            ),
        )

        assert recommendations[0].title == "先修就绪问题"
        assert any(item.title == "接口延迟或错误偏高" for item in recommendations)

    def test_flags_stale_execution_policy_export(self):
        import api_server

        recommendations = api_server._build_ops_recommendations(
            ready=True,
            readiness_issues=[],
            error_rate=0.0,
            p95_latency_ms=120,
            system_health_score=92,
            data_status=api_server.OpsDataStatus(
                scorecard_records=12,
                trade_journal_records=8,
                signal_count=6,
                active_positions=2,
                feedback_items=1,
                push_devices=1,
            ),
            learning=api_server.LearningProgress(
                today_cycles=4,
                factor_adjustments=3,
                online_updates=6,
                experiments_running=0,
                new_factors_deployed=1,
                decision_accuracy=0.72,
            ),
            daily_advance=api_server.LearningAdvanceStatus(
                status="healthy",
                in_progress=False,
                today_completed=True,
                last_started_at=None,
                current_run_started_at=None,
                last_completed_at=date.today().isoformat(),
                last_requested_by="admin",
                stale_hours=1.0,
                health_status="ok",
                summary="学习已完成",
                last_error=None,
                last_report_excerpt="",
                ingested_signals=4,
                verified_signals=6,
                reviewed_decisions=2,
                checks=[],
                recommendations=[],
            ),
            execution_policy_export=api_server.ExecutionPolicyExportStatus(
                period="daily",
                latest_export_at="2026-03-29T09:30:00",
                latest_export_id="execution-policy-daily-20260329093000",
                latest_manifest_route="/api/execution-policy/export/files/execution-policy-daily-20260329093000.manifest.json",
                latest_report_route="/api/execution-policy/export/files/execution-policy-daily-20260329093000.md",
                latest_bundle_route="/api/execution-policy/export/files/execution-policy-daily-20260329093000.bundle.zip",
                latest_asset_count=6,
                history_count=1,
                stale=True,
            ),
        )

        assert any(item.title == "执行策略导出待刷新" for item in recommendations)


class TestAppMessages:
    def test_build_app_messages_sorted_and_limited(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_build_world_state_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_world_state_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_production_guard_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_health_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_monitor_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_takeover_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_composite_focus_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_industry_capital_focus_message", lambda: None)
        monkeypatch.setattr(
            api_server,
            "_load_app_message_center",
            lambda: {
                "items": [
                    {
                        "id": "m1",
                        "title": "旧消息",
                        "body": "old",
                        "preview": "old",
                        "level": "info",
                        "channel": "wechat_mirror",
                        "created_at": "2026-03-12T09:00:00",
                    },
                    {
                        "id": "m2",
                        "title": "新消息",
                        "body": "new",
                        "preview": "new",
                        "level": "warning",
                        "channel": "wechat_mirror",
                        "created_at": "2026-03-13T09:00:00",
                    },
                ]
            },
        )

        messages = api_server._build_app_messages(limit=1)

        assert len(messages) == 1
        assert messages[0].id == "m2"
        assert messages[0].title == "新消息"

    def test_build_app_messages_includes_takeover_message(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_load_app_message_center", lambda: {"items": []})
        monkeypatch.setattr(api_server, "_build_world_state_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_world_state_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_production_guard_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_health_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_monitor_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_composite_focus_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_industry_capital_focus_message", lambda: None)
        monkeypatch.setattr(
            api_server,
            "_build_takeover_message",
            lambda: {
                "id": "msg_takeover_shadow",
                "title": "综合榜 继续影子",
                "body": "样本还不够厚，继续观察。",
                "preview": "样本还不够厚，继续观察。",
                "level": "warning",
                "channel": "system_push",
                "created_at": "2026-03-14T16:40:00",
            },
        )

        messages = api_server._build_app_messages(limit=3)

        assert len(messages) == 1
        assert messages[0].id == "msg_takeover_shadow"
        assert messages[0].channel == "system_push"

    def test_build_app_messages_includes_composite_focus_message(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_load_app_message_center", lambda: {"items": []})
        monkeypatch.setattr(api_server, "_build_world_state_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_world_state_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_production_guard_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_health_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_monitor_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_takeover_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_industry_capital_focus_message", lambda: None)
        monkeypatch.setattr(
            api_server,
            "_build_composite_focus_message",
            lambda: {
                "id": "msg_composite_focus_000858",
                "title": "主线种子候选 000858 五粮液",
                "body": "主线种子 000858 五粮液，主线孵化，建议首仓 8%。下一步：先去决策台复核主线，再决定要不要转入推荐或诊股。",
                "preview": "主线种子 000858 五粮液，主线孵化，建议首仓 8%。",
                "level": "info",
                "channel": "system_focus",
                "created_at": "2026-03-14T16:41:00",
            },
        )

        messages = api_server._build_app_messages(limit=3)

        assert len(messages) == 1
        assert messages[0].id == "msg_composite_focus_000858"
        assert messages[0].channel == "system_focus"

    def test_build_app_messages_includes_industry_capital_focus_message(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_load_app_message_center", lambda: {"items": []})
        monkeypatch.setattr(api_server, "_build_world_state_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_world_state_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_production_guard_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_health_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_monitor_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_takeover_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_composite_focus_message", lambda: None)
        monkeypatch.setattr(
            api_server,
            "_build_industry_capital_focus_message",
            lambda: {
                "id": "msg_industry_capital_ic-1",
                "title": "产业资本方向 中美博弈与反制链",
                "body": "先看方向深页，确认官方观察点、兑现时间轴和合作对象。",
                "preview": "先看方向深页，确认官方观察点。",
                "level": "warning",
                "channel": "system_focus",
                "created_at": "2026-03-14T20:50:00",
                "route": "/industry-capital/ic-1",
            },
        )

        messages = api_server._build_app_messages(limit=3)

        assert len(messages) == 1
        assert messages[0].id == "msg_industry_capital_ic-1"
        assert messages[0].route == "/industry-capital/ic-1"

    def test_build_app_messages_includes_execution_policy_message(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_load_app_message_center", lambda: {"items": []})
        monkeypatch.setattr(api_server, "_build_world_state_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_world_state_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_production_guard_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_health_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_monitor_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_takeover_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_composite_focus_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_industry_capital_focus_message", lambda: None)
        monkeypatch.setattr(
            api_server,
            "_build_execution_policy_message",
            lambda: {
                "id": "msg_execution_policy_weak_chop",
                "title": "今日执行策略 弱势拉扯",
                "body": "当前先轻仓短拿，生产层先做趋势跟踪选股。",
                "preview": "当前先轻仓短拿，生产层先做趋势跟踪选股。",
                "level": "warning",
                "channel": "system_focus",
                "created_at": "2026-03-14T16:42:00",
                "route": "/(tabs)/brain",
            },
        )

        messages = api_server._build_app_messages(limit=3)

        assert len(messages) == 1
        assert messages[0].id == "msg_execution_policy_weak_chop"
        assert messages[0].route == "/(tabs)/brain"

    def test_build_app_messages_includes_execution_policy_export_message(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_load_app_message_center", lambda: {"items": []})
        monkeypatch.setattr(api_server, "_build_world_state_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_production_guard_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_health_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_monitor_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_world_state_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_takeover_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_composite_focus_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_industry_capital_focus_message", lambda: None)
        monkeypatch.setattr(
            api_server,
            "_build_execution_policy_export_message",
            lambda: {
                "id": "msg_execution_policy_export_daily",
                "title": "执行策略归档",
                "body": "最新 execution policy 导出已就位。",
                "preview": "最新 execution policy 导出已就位。",
                "level": "info",
                "channel": "system_focus",
                "created_at": "2026-03-30T14:15:00",
                "route": "/world",
            },
        )

        messages = api_server._build_app_messages(limit=3)

        assert len(messages) == 1
        assert messages[0].id == "msg_execution_policy_export_daily"
        assert messages[0].route == "/world"

    def test_build_app_messages_includes_world_state_export_message(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_load_app_message_center", lambda: {"items": []})
        monkeypatch.setattr(api_server, "_build_world_state_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_production_guard_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_health_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_monitor_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_takeover_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_composite_focus_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_industry_capital_focus_message", lambda: None)
        monkeypatch.setattr(
            api_server,
            "_build_world_state_export_message",
            lambda: {
                "id": "msg_world_state_export_daily",
                "title": "顶层世界状态归档",
                "body": "最新 world state 导出已就位。",
                "preview": "最新 world state 导出已就位。",
                "level": "info",
                "channel": "system_focus",
                "created_at": "2026-03-30T14:10:00",
                "route": "/world",
            },
        )
        monkeypatch.setattr(api_server, "_build_execution_policy_export_message", lambda: None)

        messages = api_server._build_app_messages(limit=3)

        assert len(messages) == 1
        assert messages[0].id == "msg_world_state_export_daily"
        assert messages[0].route == "/world"

    def test_build_app_messages_includes_operating_profile_message(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_load_app_message_center", lambda: {"items": []})
        monkeypatch.setattr(api_server, "_build_world_state_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_production_guard_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_health_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_monitor_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_world_state_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_takeover_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_composite_focus_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_industry_capital_focus_message", lambda: None)
        monkeypatch.setattr(
            api_server,
            "_build_operating_profile_message",
            lambda: {
                "id": "msg_operating_profile_current",
                "title": "经营画像维护",
                "body": "经营画像字段不完整，需要继续补齐。",
                "preview": "经营画像字段不完整，需要继续补齐。",
                "level": "warning",
                "channel": "system_focus",
                "created_at": "2026-03-31T15:00:00",
                "route": "/operating-profile",
            },
        )

        messages = api_server._build_app_messages(limit=3)

        assert len(messages) == 1
        assert messages[0].id == "msg_operating_profile_current"
        assert messages[0].route == "/operating-profile"

    def test_build_app_messages_includes_world_state_message(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_load_app_message_center", lambda: {"items": []})
        monkeypatch.setattr(api_server, "_build_world_state_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_production_guard_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_health_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_monitor_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_takeover_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_composite_focus_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_industry_capital_focus_message", lambda: None)
        monkeypatch.setattr(
            api_server,
            "_build_world_state_message",
            lambda: {
                "id": "msg_world_state_valuation_reset",
                "title": "顶层世界状态 杀估值",
                "body": "当前主导：估值重构 / 折现率压制。",
                "preview": "当前主导：估值重构 / 折现率压制。",
                "level": "warning",
                "channel": "system_focus",
                "created_at": "2026-03-30T15:00:00",
                "route": "/world",
            },
        )

        messages = api_server._build_app_messages(limit=3)

        assert len(messages) == 1
        assert messages[0].id == "msg_world_state_valuation_reset"
        assert messages[0].route == "/world"

    def test_build_app_messages_includes_production_guard_message(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_load_app_message_center", lambda: {"items": []})
        monkeypatch.setattr(api_server, "_build_world_state_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_world_state_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_health_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_monitor_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_takeover_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_composite_focus_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_industry_capital_focus_message", lambda: None)
        monkeypatch.setattr(
            api_server,
            "_build_production_guard_message",
            lambda: {
                "id": "msg_production_guard_valuation_reset",
                "title": "生产风控 杀估值",
                "body": "当前新增仓位继续压缩，先处理不稳定策略。",
                "preview": "当前新增仓位继续压缩，先处理不稳定策略。",
                "level": "critical",
                "channel": "system_focus",
                "created_at": "2026-03-30T15:01:00",
                "route": "/ops",
            },
        )

        messages = api_server._build_app_messages(limit=3)

        assert len(messages) == 1
        assert messages[0].id == "msg_production_guard_valuation_reset"
        assert messages[0].route == "/ops"

    def test_build_app_messages_includes_learning_health_message(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_load_app_message_center",
            lambda: {
                "items": [
                    {
                        "id": "old_learning_health",
                        "title": "学习健康告警",
                        "body": "旧口径",
                        "preview": "旧口径",
                        "level": "critical",
                        "channel": "wechat_mirror",
                        "created_at": "2026-03-01T08:00:00",
                    }
                ]
            },
        )
        monkeypatch.setattr(api_server, "_build_world_state_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_world_state_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_production_guard_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_monitor_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_takeover_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_composite_focus_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_industry_capital_focus_message", lambda: None)
        monkeypatch.setattr(
            api_server,
            "_build_learning_health_message",
            lambda: {
                "id": "msg_learning_health_current",
                "title": "学习健康告警",
                "body": "当前学习健康告警",
                "preview": "当前学习健康告警",
                "level": "warning",
                "channel": "system_focus",
                "created_at": "2026-03-31T10:20:00",
                "route": "/ops",
            },
        )

        messages = api_server._build_app_messages(limit=3)

        assert len(messages) == 1
        assert messages[0].id == "msg_learning_health_current"
        assert messages[0].body == "当前学习健康告警"

    def test_build_app_messages_includes_learning_monitor_message(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_load_app_message_center",
            lambda: {
                "items": [
                    {
                        "id": "old_learning_monitor",
                        "title": "学习数据监控",
                        "body": "旧口径",
                        "preview": "旧口径",
                        "level": "warning",
                        "channel": "wechat_mirror",
                        "created_at": "2026-03-01T08:00:00",
                    }
                ]
            },
        )
        monkeypatch.setattr(api_server, "_build_world_state_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_world_state_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_production_guard_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_health_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_takeover_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_composite_focus_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_industry_capital_focus_message", lambda: None)
        monkeypatch.setattr(
            api_server,
            "_build_learning_monitor_message",
            lambda: {
                "id": "msg_learning_monitor_current",
                "title": "学习数据监控",
                "body": "盘中候选: 3 条 / 正式信号: 2 条 / 正式入库: 1 条 / 回填验证: 4 条",
                "preview": "盘中候选: 3 条 / 正式信号: 2 条 / 正式入库: 1 条 / 回填验证: 4 条",
                "level": "warning",
                "channel": "system_focus",
                "created_at": "2026-03-31T10:21:00",
                "route": "/ops",
            },
        )

        messages = api_server._build_app_messages(limit=3)

        assert len(messages) == 1
        assert messages[0].id == "msg_learning_monitor_current"
        assert "盘中候选" in messages[0].body


class TestPushTakeover:
    def test_register_push_device_auto_dispatches_current_takeover(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_is_valid_expo_push_token", lambda token: True)
        registry_state = {"devices": [], "last_update": "2026-03-14T16:00:00"}
        monkeypatch.setattr(api_server, "_load_push_registry", lambda: registry_state)
        monkeypatch.setattr(api_server, "_save_push_registry", lambda payload: registry_state.update(payload) or registry_state)
        monkeypatch.setattr(
            api_server,
            "_load_push_state",
            lambda: {
                "takeover_auto_enabled": True,
                "last_takeover_sent_at": None,
                "last_takeover_sent_status": None,
                "last_takeover_fingerprint": None,
                "last_takeover_preview_at": None,
                "last_takeover_auto_run_at": None,
                "last_takeover_auto_run_status": None,
            },
        )
        monkeypatch.setattr(api_server, "_save_push_state", lambda payload: payload)
        monkeypatch.setattr(
            api_server,
            "_build_takeover_message",
            lambda: {
                "title": "综合榜 继续影子",
                "body": "样本还不够厚，继续观察。",
                "preview": "样本还不够厚，继续观察。",
            },
        )
        monkeypatch.setattr(api_server, "_takeover_auto_cooldown_remaining", lambda state: 0)
        monkeypatch.setattr(
            api_server,
            "_dispatch_push_takeover",
            lambda user, payload: api_server.PushDispatchResult(
                success=True,
                dry_run=False,
                targeted_devices=1,
                sent_devices=1,
                failed_devices=0,
                tickets=[
                    api_server.PushDispatchTicket(
                        expo_push_token=payload.target_token or "(none)",
                        status="ok",
                        message="sent",
                    )
                ],
            ),
        )

        user = api_server.AppUser(username="admin", display_name="Admin", role="operator")
        result = api_server._register_push_device(
            user,
            api_server.PushDeviceRegistrationRequest(
                expo_push_token="ExponentPushToken[newdevice123]",
                platform="android",
                device_name="Pixel",
                app_version="1.0.36",
                permission_state="granted",
            ),
        )

        assert result.success is True
        assert result.active_devices == 1
        assert result.takeover_dispatch is not None
        assert result.takeover_dispatch.sent_devices == 1

    def test_register_push_device_does_not_auto_dispatch_when_disabled(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_is_valid_expo_push_token", lambda token: True)
        registry_state = {"devices": [], "last_update": "2026-03-14T16:00:00"}
        monkeypatch.setattr(api_server, "_load_push_registry", lambda: registry_state)
        monkeypatch.setattr(api_server, "_save_push_registry", lambda payload: registry_state.update(payload) or registry_state)
        monkeypatch.setattr(
            api_server,
            "_load_push_state",
            lambda: {
                "takeover_auto_enabled": False,
                "last_takeover_sent_at": None,
                "last_takeover_sent_status": None,
                "last_takeover_fingerprint": None,
                "last_takeover_preview_at": None,
                "last_takeover_auto_run_at": None,
                "last_takeover_auto_run_status": None,
            },
        )
        monkeypatch.setattr(api_server, "_save_push_state", lambda payload: payload)
        monkeypatch.setattr(
            api_server,
            "_dispatch_push_takeover",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not dispatch")),
        )

        user = api_server.AppUser(username="admin", display_name="Admin", role="operator")
        result = api_server._register_push_device(
            user,
            api_server.PushDeviceRegistrationRequest(
                expo_push_token="ExponentPushToken[newdevice123]",
                platform="android",
                device_name="Pixel",
                app_version="1.0.36",
                permission_state="granted",
            ),
        )

        assert result.success is True
        assert result.takeover_dispatch is None

    def test_build_takeover_push_status_counts_pending_devices(self, monkeypatch):
        import api_server

        current_fingerprint = "abc123pending"
        monkeypatch.setattr(
            api_server,
            "_build_takeover_message",
            lambda: {
                "title": "综合榜 继续影子",
                "body": "样本还不够厚，继续观察。",
                "preview": "样本还不够厚，继续观察。",
            },
        )
        monkeypatch.setattr(api_server, "_takeover_fingerprint", lambda message: current_fingerprint)
        monkeypatch.setattr(
            api_server,
            "_load_push_registry",
            lambda: {
                "devices": [
                    {
                        "username": "admin",
                        "platform": "android",
                        "expo_push_token": "ExponentPushToken[abc123abc123abc123abc1]",
                        "device_name": "Pixel A",
                        "permission_state": "granted",
                        "status": "active",
                        "last_seen_at": "2026-03-14T16:00:00",
                        "last_takeover_fingerprint": current_fingerprint,
                    },
                    {
                        "username": "admin",
                        "platform": "android",
                        "expo_push_token": "ExponentPushToken[def456def456def456def4]",
                        "device_name": "Pixel B",
                        "permission_state": "granted",
                        "status": "active",
                        "last_seen_at": "2026-03-14T16:05:00",
                    },
                ]
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_push_state",
            lambda: {
                "last_takeover_sent_at": "2026-03-14T16:10:00",
                "last_takeover_sent_status": "ok",
                "last_takeover_fingerprint": current_fingerprint,
                "last_takeover_preview_at": "2026-03-14T16:11:00",
            },
        )

        user = api_server.AppUser(username="admin", display_name="Admin", role="operator")
        status = api_server._build_takeover_push_status(user)

        assert status.active_devices == 2
        assert status.synced_devices == 1
        assert status.pending_devices == 1
        assert status.should_send is True
        assert status.delivery_state == "pending_devices"
        assert status.auto_enabled is False
        assert status.auto_ready is False
        assert "1 台活跃设备没收到" in status.summary

    def test_build_industry_research_push_status_reports_latest_message(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_load_push_registry",
            lambda: {
                "devices": [
                    {
                        "username": "admin",
                        "status": "active",
                        "expo_push_token": "ExponentPushToken[test-token]",
                    }
                ]
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_push_state",
            lambda: {
                "takeover_auto_enabled": True,
                "last_industry_research_sent_at": "2026-03-15T11:00:00",
                "last_industry_research_sent_status": "ok",
            },
        )
        monkeypatch.setattr(
            api_server,
            "_build_app_messages",
            lambda limit=24: [
                api_server.AppMessage(
                    id="msg_industry_1",
                    title="中美博弈与反制链 验证增强",
                    body="测试消息",
                    preview="最近一次方向变化",
                    level="info",
                    channel="system_update",
                    created_at="2026-03-15T11:00:00",
                    route="/industry-capital/industry-capital-policy-watch-china-us-rivalry",
                )
            ],
        )

        user = api_server.AppUser(username="admin", display_name="Admin", role="operator")
        status = api_server._build_industry_research_push_status(user)

        assert status.active_devices == 1
        assert status.delivery_state == "active"
        assert status.auto_enabled is True
        assert status.last_sent_status == "ok"
        assert status.latest_title == "中美博弈与反制链 验证增强"
        assert status.latest_preview == "最近一次方向变化"

    def test_dispatch_push_takeover_supports_dry_run(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_load_push_registry",
            lambda: {
                "devices": [
                    {
                        "username": "admin",
                        "platform": "android",
                        "expo_push_token": "ExponentPushToken[abc123abc123abc123abc1]",
                        "device_name": "Pixel",
                        "app_version": "1.0.0",
                        "permission_state": "granted",
                        "is_physical_device": True,
                        "status": "active",
                        "last_seen_at": "2026-03-14T16:00:00",
                        "last_push_at": None,
                        "last_push_status": None,
                        "last_error": None,
                    }
                ]
            },
        )
        monkeypatch.setattr(
            api_server,
            "_build_takeover_message",
            lambda: {
                "title": "综合榜 继续影子",
                "body": "样本还不够厚，继续观察。",
            },
        )

        user = api_server.AppUser(username="admin", display_name="Admin", role="operator")
        result = api_server._dispatch_push_takeover(user, api_server.PushTakeoverRequest(dry_run=True))

        assert result.dry_run is True
        assert result.targeted_devices == 1
        assert result.sent_devices == 0
        assert result.tickets[0].status == "dry_run"

    def test_dispatch_push_takeover_dry_run_without_devices(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_load_push_registry", lambda: {"devices": []})
        monkeypatch.setattr(
            api_server,
            "_build_takeover_message",
            lambda: {
                "title": "综合榜 继续影子",
                "body": "样本还不够厚，继续观察。",
            },
        )

        user = api_server.AppUser(username="admin", display_name="Admin", role="operator")
        result = api_server._dispatch_push_takeover(user, api_server.PushTakeoverRequest(dry_run=True))

        assert result.success is True
        assert result.dry_run is True
        assert result.targeted_devices == 0
        assert result.tickets[0].message is not None

    def test_dispatch_push_takeover_skips_when_current_version_already_covered(self, monkeypatch):
        import api_server

        current_fingerprint = "abc123covered"
        monkeypatch.setattr(
            api_server,
            "_build_takeover_message",
            lambda: {
                "title": "综合榜 继续影子",
                "body": "样本还不够厚，继续观察。",
                "preview": "样本还不够厚，继续观察。",
            },
        )
        monkeypatch.setattr(api_server, "_takeover_fingerprint", lambda message: current_fingerprint)
        monkeypatch.setattr(
            api_server,
            "_load_push_registry",
            lambda: {
                "devices": [
                    {
                        "username": "admin",
                        "platform": "android",
                        "expo_push_token": "ExponentPushToken[abc123abc123abc123abc1]",
                        "device_name": "Pixel",
                        "permission_state": "granted",
                        "status": "active",
                        "last_seen_at": "2026-03-14T16:00:00",
                        "last_takeover_fingerprint": current_fingerprint,
                    }
                ]
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_push_state",
            lambda: {
                "last_takeover_sent_at": "2026-03-14T16:10:00",
                "last_takeover_sent_status": "ok",
                "last_takeover_fingerprint": current_fingerprint,
                "last_takeover_preview_at": None,
            },
        )
        monkeypatch.setattr(api_server, "_send_expo_push_messages", lambda messages: (_ for _ in ()).throw(AssertionError("should not send")))

        user = api_server.AppUser(username="admin", display_name="Admin", role="operator")
        result = api_server._dispatch_push_takeover(user, api_server.PushTakeoverRequest())

        assert result.success is True
        assert result.targeted_devices == 0
        assert result.tickets[0].status == "skipped"

    def test_dispatch_push_takeover_marks_devices_as_covered(self, monkeypatch):
        import api_server

        registry_state = {
            "devices": [
                {
                    "username": "admin",
                    "platform": "android",
                    "expo_push_token": "ExponentPushToken[abc123abc123abc123abc1]",
                    "device_name": "Pixel",
                    "permission_state": "granted",
                    "status": "active",
                    "last_seen_at": "2026-03-14T16:00:00",
                }
            ],
            "last_update": "2026-03-14T16:00:00",
        }
        push_state = {}
        current_fingerprint = "abc123fresh"

        monkeypatch.setattr(
            api_server,
            "_build_takeover_message",
            lambda: {
                "title": "综合榜 继续影子",
                "body": "样本还不够厚，继续观察。",
                "preview": "样本还不够厚，继续观察。",
            },
        )
        monkeypatch.setattr(api_server, "_takeover_fingerprint", lambda message: current_fingerprint)
        monkeypatch.setattr(api_server, "_load_push_registry", lambda: registry_state)
        monkeypatch.setattr(api_server, "_save_push_registry", lambda payload: registry_state.update(payload) or registry_state)
        monkeypatch.setattr(api_server, "_load_push_state", lambda: push_state)
        monkeypatch.setattr(api_server, "_save_push_state", lambda payload: push_state.update(payload) or push_state)
        monkeypatch.setattr(
            api_server,
            "_send_expo_push_messages",
            lambda messages: [{"status": "ok", "id": "ticket-1"}],
        )

        user = api_server.AppUser(username="admin", display_name="Admin", role="operator")
        result = api_server._dispatch_push_takeover(user, api_server.PushTakeoverRequest())

        assert result.success is True
        assert registry_state["devices"][0]["last_takeover_fingerprint"] == current_fingerprint
        assert registry_state["devices"][0]["last_takeover_push_at"] is not None
        assert push_state["last_takeover_fingerprint"] == current_fingerprint

    def test_run_takeover_auto_push_respects_disabled_state(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_build_takeover_push_status",
            lambda user: api_server.TakeoverPushStatus(
                title="综合榜 继续影子",
                body="样本还不够厚，继续观察。",
                readiness_label="继续影子",
                fingerprint="abc",
                active_devices=1,
                synced_devices=0,
                pending_devices=1,
                delivery_state="pending_update",
                should_send=True,
                summary="test",
                recommended_action="test",
                auto_enabled=False,
                auto_ready=False,
                auto_cooldown_seconds=0,
                last_sent_at=None,
                last_sent_status=None,
                last_sent_fingerprint=None,
                last_preview_at=None,
                last_auto_run_at=None,
                last_auto_run_status=None,
            ),
        )
        push_state = {"takeover_auto_enabled": False}
        monkeypatch.setattr(api_server, "_load_push_state", lambda: push_state)
        monkeypatch.setattr(api_server, "_save_push_state", lambda payload: push_state.update(payload) or push_state)
        monkeypatch.setattr(api_server, "_dispatch_push_takeover", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not dispatch")))

        user = api_server.AppUser(username="admin", display_name="Admin", role="operator")
        result = api_server._run_takeover_auto_push(user)

        assert result.success is True
        assert result.tickets[0].status == "disabled"
        assert push_state["last_takeover_auto_run_status"] == "disabled"

    def test_run_takeover_auto_push_dispatches_when_enabled(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_build_takeover_push_status",
            lambda user: api_server.TakeoverPushStatus(
                title="综合榜 继续影子",
                body="样本还不够厚，继续观察。",
                readiness_label="继续影子",
                fingerprint="abc",
                active_devices=1,
                synced_devices=0,
                pending_devices=1,
                delivery_state="pending_update",
                should_send=True,
                summary="test",
                recommended_action="test",
                auto_enabled=True,
                auto_ready=True,
                auto_cooldown_seconds=0,
                last_sent_at=None,
                last_sent_status=None,
                last_sent_fingerprint=None,
                last_preview_at=None,
                last_auto_run_at=None,
                last_auto_run_status=None,
            ),
        )
        push_state = {"takeover_auto_enabled": True}
        monkeypatch.setattr(api_server, "_load_push_state", lambda: push_state)
        monkeypatch.setattr(api_server, "_save_push_state", lambda payload: push_state.update(payload) or push_state)
        monkeypatch.setattr(api_server, "_takeover_auto_cooldown_remaining", lambda state: 0)
        monkeypatch.setattr(
            api_server,
            "_dispatch_push_takeover",
            lambda user, payload: api_server.PushDispatchResult(
                success=True,
                dry_run=False,
                targeted_devices=1,
                sent_devices=1,
                failed_devices=0,
                tickets=[
                    api_server.PushDispatchTicket(
                        expo_push_token="ExponentPushToken[abc123abc123abc123abc1]",
                        status="ok",
                        message="sent",
                    )
                ],
            ),
        )

        user = api_server.AppUser(username="admin", display_name="Admin", role="operator")
        result = api_server._run_takeover_auto_push(user)

        assert result.success is True
        assert result.sent_devices == 1
        assert push_state["last_takeover_auto_run_status"] == "ok"


class TestLiveSignalsFromJournal:
    def test_build_signals_prefers_trade_journal_stock_picks(self, monkeypatch):
        import api_server

        today = date.today().isoformat()

        monkeypatch.setattr(
            api_server,
            "load_trade_journal",
            lambda days=None, strategy=None: [
                {
                    "date": today,
                    "strategy": "趋势跟踪选股",
                    "regime": {"regime": "neutral", "score": 0.0},
                    "picks": [
                        {
                            "code": "603393",
                            "name": "新天然气",
                            "price": 42.67,
                            "total_score": 0.9788,
                            "factor_scores": {"s_trend": 0.8},
                        },
                        {
                            "code": "M",
                            "name": "豆粕",
                            "price": 3054.0,
                            "total_score": 0.8973,
                        },
                    ],
                }
            ],
        )

        signals = api_server._build_signals(days=1)

        assert len(signals) == 1
        assert signals[0].code == "603393"
        assert signals[0].name == "新天然气"
        assert signals[0].strategy == "趋势跟踪选股"

    def test_build_signal_detail_resolves_trade_journal_signal(self, monkeypatch):
        import api_server

        today = date.today().isoformat()

        monkeypatch.setattr(
            api_server,
            "load_trade_journal",
            lambda days=None, strategy=None: [
                {
                    "date": today,
                    "strategy": "集合竞价选股",
                    "regime": {"regime": "neutral", "score": 0.0},
                    "picks": [
                        {
                            "code": "600458",
                            "name": "时代新材",
                            "price": 14.74,
                            "total_score": 0.9249,
                            "factor_scores": {"s_gap": 0.9},
                        }
                    ],
                }
            ],
        )

        signals = api_server._build_signals(days=1)
        detail = api_server._build_signal_detail(signals[0].id)

        assert detail.code == "600458"
        assert detail.name == "时代新材"
        assert detail.strategy == "集合竞价选股"
        assert detail.factor_scores["s_gap"] == 0.9

    def test_build_signal_detail_adds_entry_guide_from_composite_and_positioning(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_build_production_guard_snapshot",
            lambda: api_server.ProductionGuardSnapshot(
                market_phase="rotation_up",
                market_phase_label="轮动走强",
                hard_risk_gate=False,
                blocked_additions=False,
                auto_reduce_positions=False,
                auto_exit_losers=False,
                current_drawdown_pct=-0.8,
                max_drawdown_pct=-3.0,
                drawdown_days=1,
                walk_forward_risk="low",
                walk_forward_efficiency=0.92,
                walk_forward_degradation=0.12,
                unstable_strategies=[],
                summary="当前允许按预算推进。",
                actions=["维持预算。"],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_find_signal_record",
            lambda signal_id: {
                "id": signal_id,
                "code": "002531",
                "name": "天顺风能",
                "strategy": "趋势跟踪选股",
                "score": 0.93,
                "price": 8.55,
                "change_pct": 1.8,
                "buy_price": 8.48,
                "stop_loss": 8.18,
                "target_price": 9.12,
                "risk_reward": 2.1,
                "timestamp": "2026-03-14T10:30:00",
                "consensus_count": 2,
                "regime": "neutral",
                "regime_score": 0.74,
                "factor_scores": {"s_trend": 0.82, "s_hot": 0.76},
            },
        )
        monkeypatch.setattr(
            api_server,
            "_build_composite_picks",
            lambda days=1, limit=12: [
                api_server.CompositePick(
                    id="cp-1",
                    signal_id="sig-live-1",
                    code="002531",
                    name="天顺风能",
                    strategy="趋势跟踪选股",
                    theme_sector="新能源",
                    theme_intensity="持续升温",
                    setup_label="综合进攻候选",
                    conviction="high",
                    composite_score=66.8,
                    strategy_score=72.0,
                    capital_score=61.0,
                    theme_score=68.0,
                    event_score=58.0,
                    event_bias="偏多",
                    event_summary="新能源主线与事件方向一致，允许先拿首仓。",
                    event_matched_sector="新能源",
                    execution_score=71.0,
                    first_position_pct=10,
                    price=8.55,
                    buy_price=8.48,
                    stop_loss=8.18,
                    target_price=9.12,
                    risk_reward=2.1,
                    timestamp="2026-03-14T10:30:00",
                    thesis="test",
                    action="先试错",
                    reasons=["test"],
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_positioning_plan",
            lambda days=1, limit=3: api_server.PositioningPlan(
                mode="平衡",
                regime="neutral",
                regime_score=58.0,
                event_bias="偏多",
                event_score=60.0,
                event_summary="事件偏多，允许按首仓纪律推进。",
                event_focus_sector="新能源",
                current_exposure_pct=0.0,
                target_exposure_pct=58.0,
                deployable_exposure_pct=58.0,
                cash_balance=100000.0,
                total_assets=100000.0,
                deployable_cash=58000.0,
                current_positions=0,
                available_slots=4,
                max_positions=6,
                first_entry_position_pct=10,
                max_single_position_pct=18,
                max_theme_exposure_pct=28,
                top_theme="新能源",
                focus="先看新能源。",
                reasons=["test"],
                actions=["test"],
                deployments=[],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_load_portfolio",
            lambda: {
                "positions": [
                    {
                        "code": "601012",
                        "name": "隆基光伏",
                        "quantity": 1000,
                        "current_price": 10.0,
                        "market_value": 10000.0,
                    }
                ],
                "cash": 90000.0,
                "total_assets": 100000.0,
            },
        )

        detail = api_server._build_signal_detail("sig-live-1")

        assert detail.code == "002531"
        assert detail.entry_guide.mode == "轻仓试错" or detail.entry_guide.mode == "允许首仓"
        assert detail.entry_guide.theme_sector == "新能源"
        assert detail.entry_guide.sector_bucket == "能源"
        assert detail.entry_guide.theme_alignment == "与事件主线一致"
        assert detail.entry_guide.recommended_first_position_pct == 10
        assert detail.entry_guide.max_single_position_pct == 18
        assert detail.entry_guide.max_theme_exposure_pct == 28
        assert detail.entry_guide.current_theme_exposure_pct == 10.0
        assert detail.entry_guide.projected_theme_exposure_pct >= 20.0
        assert detail.entry_guide.concentration_summary is not None
        assert detail.entry_guide.suggested_quantity >= 100

    def test_build_signal_detail_entry_guide_respects_production_guard(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_find_signal_record",
            lambda signal_id: {
                "id": signal_id,
                "code": "002531",
                "name": "天顺风能",
                "strategy": "趋势跟踪选股",
                "score": 0.93,
                "price": 8.55,
                "change_pct": 1.8,
                "buy_price": 8.48,
                "stop_loss": 8.18,
                "target_price": 9.12,
                "risk_reward": 2.1,
                "timestamp": "2026-03-14T10:30:00",
                "consensus_count": 2,
                "regime": "neutral",
                "regime_score": 0.74,
                "factor_scores": {"s_trend": 0.82, "s_hot": 0.76},
            },
        )
        monkeypatch.setattr(
            api_server,
            "_build_composite_picks",
            lambda days=1, limit=12: [
                api_server.CompositePick(
                    id="cp-1",
                    signal_id="sig-live-2",
                    code="002531",
                    name="天顺风能",
                    strategy="趋势跟踪选股",
                    theme_sector="新能源",
                    theme_intensity="持续升温",
                    setup_label="综合进攻候选",
                    conviction="high",
                    composite_score=70.0,
                    strategy_score=72.0,
                    capital_score=61.0,
                    theme_score=68.0,
                    event_score=58.0,
                    execution_score=71.0,
                    first_position_pct=10,
                    price=8.55,
                    buy_price=8.48,
                    stop_loss=8.18,
                    target_price=9.12,
                    risk_reward=2.1,
                    timestamp="2026-03-14T10:30:00",
                    thesis="test",
                    action="先试错",
                    reasons=["test"],
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_positioning_plan",
            lambda days=1, limit=3: api_server.PositioningPlan(
                mode="防守",
                regime="weak",
                regime_score=42.0,
                current_exposure_pct=24.0,
                target_exposure_pct=24.0,
                deployable_exposure_pct=0.0,
                hard_risk_gate=True,
                risk_budget_pct=18.0,
                cash_buffer_pct=82.0,
                risk_guard_summary="当前生产风控已禁止新增。",
                event_bias="偏空",
                event_score=38.0,
                event_summary="风险优先",
                event_focus_sector="新能源",
                cash_balance=76000.0,
                total_assets=100000.0,
                deployable_cash=0.0,
                current_positions=2,
                available_slots=0,
                max_positions=5,
                first_entry_position_pct=0,
                max_single_position_pct=12,
                max_theme_exposure_pct=18,
                top_theme="新能源",
                focus="禁止新增",
                reasons=["test"],
                actions=["test"],
                deployments=[],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_production_guard_snapshot",
            lambda: api_server.ProductionGuardSnapshot(
                market_phase="risk_off",
                market_phase_label="退潮避险",
                hard_risk_gate=True,
                blocked_additions=True,
                auto_reduce_positions=True,
                auto_exit_losers=True,
                current_drawdown_pct=-6.0,
                max_drawdown_pct=-9.0,
                drawdown_days=6,
                walk_forward_risk="high",
                walk_forward_efficiency=0.58,
                walk_forward_degradation=0.71,
                unstable_strategies=["趋势跟踪选股"],
                summary="当前生产风控已禁止新增。",
                actions=["暂停新增仓位。"],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_load_portfolio",
            lambda: {
                "positions": [],
                "cash": 76000.0,
                "total_assets": 100000.0,
            },
        )

        detail = api_server._build_signal_detail("sig-live-2")

        assert detail.entry_guide.mode == "先观察"
        assert detail.entry_guide.recommended_first_position_pct == 0
        assert detail.entry_guide.suggested_amount == 0
        assert any("生产风控" in warning for warning in detail.entry_guide.warnings)

    def test_system_status_counts_live_signals_today(self, monkeypatch):
        import api_server

        today = date.today().isoformat()
        now = datetime.now().isoformat()

        monkeypatch.setattr(
            api_server,
            "load_trade_journal",
            lambda days=None, strategy=None: [
                {
                    "date": today,
                    "strategy": "趋势跟踪选股",
                    "regime": {"regime": "neutral", "score": 0.0},
                    "picks": [
                        {"code": "603393", "name": "新天然气", "price": 42.67, "total_score": 0.9788},
                        {"code": "CF", "name": "棉花", "price": 15545.0, "total_score": 0.8716},
                    ],
                }
            ],
        )

        def fake_safe_load(path, default=None):
            if path == api_server._AGENT_MEMORY:
                return {
                    "start_time": now,
                    "health_score": 87,
                    "decision_accuracy": 0.7,
                    "ooda_cycles": 321,
                }
            if path == api_server._STRATEGIES_JSON:
                return [{"enabled": True}, {"enabled": False}, {"enabled": True}]
            if path == api_server._SIGNAL_TRACKER:
                return {"signals": []}
            return default

        monkeypatch.setattr(api_server, "safe_load", fake_safe_load)

        status = api_server._build_system_status()

        assert status.today_signals == 1
        assert status.active_strategies == 2


class TestStrongMoves:
    def test_build_strong_moves_ranks_continuation_and_swing_candidates(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_build_strategies",
            lambda: [
                api_server.StrategyPerformance(
                    id="trend",
                    name="趋势跟踪选股",
                    status="active",
                    win_rate=68.5,
                    avg_return=0.23,
                    signal_count=120,
                    last_signal_time="2026-03-13T10:30:00",
                ),
                api_server.StrategyPerformance(
                    id="dip",
                    name="低吸回调选股",
                    status="active",
                    win_rate=55.2,
                    avg_return=0.11,
                    signal_count=40,
                    last_signal_time="2026-03-13T10:30:00",
                ),
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_load_signal_records",
            lambda days=1: [
                {
                    "id": "sig-strong",
                    "code": "603393",
                    "name": "新天然气",
                    "strategy": "趋势跟踪选股",
                    "score": 0.97,
                    "price": 42.67,
                    "buy_price": 42.67,
                    "stop_loss": 41.39,
                    "target_price": 45.23,
                    "risk_reward": 2.0,
                    "timestamp": "2026-03-13T10:30:00",
                    "consensus_count": 2,
                    "regime": "neutral",
                    "factor_scores": {
                        "s_trend": 0.88,
                        "s_momentum": 0.84,
                        "s_hot": 0.79,
                        "s_volume_breakout": 0.81,
                        "s_fund_flow": 0.74,
                    },
                },
                {
                    "id": "sig-swing",
                    "code": "300315",
                    "name": "掌趣科技",
                    "strategy": "低吸回调选股",
                    "score": 0.91,
                    "price": 5.44,
                    "buy_price": 5.44,
                    "stop_loss": 5.28,
                    "target_price": 5.77,
                    "risk_reward": 2.06,
                    "timestamp": "2026-03-13T10:30:00",
                    "consensus_count": 1,
                    "regime": "neutral",
                    "factor_scores": {
                        "s_trend": 0.71,
                        "s_fundamental": 0.69,
                        "s_chip": 0.73,
                        "s_hot": 0.55,
                    },
                },
                {
                    "id": "sig-skip",
                    "code": "002170",
                    "name": "芭田股份",
                    "strategy": "隔夜选股",
                    "score": 0.0,
                    "price": 0.0,
                    "buy_price": 0.0,
                    "stop_loss": 0.0,
                    "target_price": 0.0,
                    "risk_reward": 0.0,
                    "timestamp": "2026-03-13T16:45:00",
                    "consensus_count": 1,
                    "regime": "neutral",
                    "factor_scores": {},
                },
            ],
        )

        candidates = api_server._build_strong_moves(days=1, limit=5)

        assert len(candidates) == 2
        assert candidates[0].code == "603393"
        assert candidates[0].composite_score >= candidates[1].composite_score
        assert all(item.price > 0 for item in candidates)


class TestPositionGuide:
    def test_build_position_detail_adds_position_guide(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_build_production_guard_snapshot",
            lambda: api_server.ProductionGuardSnapshot(
                market_phase="range_rotation",
                market_phase_label="震荡轮动",
                hard_risk_gate=False,
                blocked_additions=False,
                auto_reduce_positions=False,
                auto_exit_losers=False,
                current_drawdown_pct=-1.5,
                max_drawdown_pct=-4.2,
                drawdown_days=2,
                walk_forward_risk="medium",
                walk_forward_efficiency=0.78,
                walk_forward_degradation=0.28,
                unstable_strategies=[],
                summary="当前允许按预算推进。",
                actions=["维持预算。"],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_load_portfolio",
            lambda: {
                "positions": [
                    {
                        "code": "603588",
                        "name": "高能环境",
                        "quantity": 1000,
                        "cost_price": 14.2,
                        "current_price": 15.1,
                        "market_value": 15100.0,
                        "profit_loss": 900.0,
                        "profit_loss_pct": 6.34,
                        "stop_loss": 14.6,
                        "take_profit": 15.4,
                        "hold_days": 4,
                        "strategy": "趋势跟踪选股",
                        "buy_time": "2026-03-10 10:30:00",
                        "high_price": 15.3,
                        "low_price": 14.05,
                        "trailing_stop": False,
                        "trailing_trigger_price": 0,
                        "trades": [],
                    },
                    {
                        "code": "601899",
                        "name": "紫金矿业",
                        "quantity": 1000,
                        "current_price": 18.0,
                        "market_value": 18000.0,
                        "strategy": "趋势跟踪选股",
                    },
                ],
                "cash": 66900.0,
                "total_assets": 100000.0,
            },
        )
        monkeypatch.setattr(
            api_server,
            "_build_positioning_plan",
            lambda days=1, limit=3: api_server.PositioningPlan(
                mode="谨慎",
                regime="weak",
                regime_score=44.0,
                event_bias="偏空",
                event_score=38.0,
                event_summary="事件偏空，盈利仓位优先锁盈，弱势仓位不要拖。",
                event_focus_sector="制造",
                current_exposure_pct=33.1,
                target_exposure_pct=25.0,
                deployable_exposure_pct=0.0,
                cash_balance=66900.0,
                total_assets=100000.0,
                deployable_cash=0.0,
                current_positions=2,
                available_slots=0,
                max_positions=5,
                first_entry_position_pct=6,
                max_single_position_pct=18,
                max_theme_exposure_pct=19,
                top_theme="制造",
                focus="先控风险。",
                reasons=["test"],
                actions=["test"],
                deployments=[],
            ),
        )

        detail = api_server._build_position_detail("603588")

        assert detail.position_guide.mode in {"先锁盈", "锁盈观察"}
        assert detail.position_guide.event_bias == "偏空"
        assert detail.position_guide.sector_bucket in {"制造", "其他", "高能环境"}
        assert detail.position_guide.position_pct == 15.1
        assert detail.position_guide.current_theme_exposure_pct >= 0.0
        assert detail.position_guide.suggested_reduce_pct >= 30
        assert detail.position_guide.suggested_reduce_quantity > 0
        assert detail.position_guide.concentration_summary is not None
        assert detail.position_guide.warnings


class TestActionBoard:
    def test_build_action_board_prioritizes_positions_and_alerts(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_cached_runtime_value", lambda *args, **kwargs: kwargs["builder"]())
        monkeypatch.setattr(
            api_server,
            "_build_execution_policy",
            lambda: api_server.ExecutionPolicySnapshot(
                regime="weak",
                market_phase="weak_chop",
                market_phase_label="弱势拉扯",
                style_bias="轻仓短拿",
                horizon_hint="尾盘短线和竞价修复更适合按 T1 跟踪。",
                aggressiveness="谨慎",
                risk_budget_pct=42.0,
                cash_buffer_pct=58.0,
                limit_up_mode="只做板前确认，不追板",
                limit_up_allowed=True,
                allowed_styles=["竞价短拿", "低吸修复"],
                blocked_styles=["高位接力"],
                allowed_strategies=["趋势跟踪选股"],
                observation_strategies=["低吸回调选股"],
                blocked_strategies=["隔夜选股"],
                preferred_holding_windows=["T+1/T+2 观察"],
                summary="当前先轻仓短拿，生产层优先趋势跟踪选股。",
                key_actions=["总仓先按 42.0% 风险预算控制。"],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_risk_alerts",
            lambda: [
                api_server.RiskAlert(
                    id="risk-1",
                    level="critical",
                    title="603588 接近止损",
                    message="先降风险",
                    source="position",
                    source_id="603588",
                    created_at="2026-03-14T10:30:00",
                    route="/position/603588",
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_load_portfolio",
            lambda: {
                "positions": [
                    {
                        "code": "603588",
                        "name": "高能环境",
                        "quantity": 1000,
                        "cost_price": 14.2,
                        "current_price": 15.1,
                        "market_value": 15100.0,
                        "profit_loss": 900.0,
                        "profit_loss_pct": 6.34,
                        "stop_loss": 14.6,
                        "take_profit": 15.4,
                        "hold_days": 4,
                        "strategy": "趋势跟踪选股",
                        "buy_time": "2026-03-10 10:30:00",
                        "high_price": 15.3,
                        "low_price": 14.05,
                        "trailing_stop": False,
                        "trailing_trigger_price": 0,
                        "trades": [],
                    }
                ],
                "cash": 84900.0,
                "total_assets": 100000.0,
            },
        )
        monkeypatch.setattr(
            api_server,
            "_build_positioning_plan",
            lambda days=1, limit=3: api_server.PositioningPlan(
                mode="谨慎",
                regime="weak",
                regime_score=44.0,
                event_bias="偏空",
                event_score=38.0,
                event_summary="test",
                event_focus_sector="制造",
                current_exposure_pct=15.1,
                target_exposure_pct=25.0,
                deployable_exposure_pct=0.0,
                cash_balance=84900.0,
                total_assets=100000.0,
                deployable_cash=0.0,
                current_positions=1,
                available_slots=0,
                max_positions=5,
                first_entry_position_pct=6,
                max_single_position_pct=18,
                max_theme_exposure_pct=19,
                top_theme="制造",
                focus="test",
                reasons=["test"],
                actions=["test"],
                deployments=[],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_composite_picks",
            lambda days=1, limit=3: [
                api_server.CompositePick(
                    id="cp-1",
                    signal_id="sig-1",
                    code="002531",
                    name="天顺风能",
                    strategy="趋势跟踪选股",
                    theme_sector="新能源",
                    theme_intensity="持续升温",
                    setup_label="综合进攻候选",
                    conviction="high",
                    composite_score=65.2,
                    strategy_score=72.0,
                    capital_score=63.0,
                    theme_score=68.0,
                    event_score=58.0,
                    event_bias="偏多",
                    event_summary="test",
                    event_matched_sector="新能源",
                    execution_score=70.0,
                    first_position_pct=10,
                    source_category="theme_seed",
                    source_label="主线种子",
                    horizon_label="主线孵化",
                    price=8.5,
                    buy_price=8.4,
                    stop_loss=8.1,
                    target_price=9.1,
                    risk_reward=2.0,
                    timestamp="2026-03-14T10:30:00",
                    thesis="test",
                    action="看推荐",
                    reasons=["test"],
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_learning_advance_status",
            lambda: api_server.LearningAdvanceStatus(
                status="pending",
                in_progress=False,
                today_completed=False,
                last_started_at="2026-03-14T08:00:00",
                current_run_started_at=None,
                last_completed_at=None,
                last_requested_by="admin",
                stale_hours=8.0,
                health_status="warning",
                summary="今天学习还没跑完",
                last_error=None,
                last_report_excerpt="",
                ingested_signals=0,
                verified_signals=0,
                reviewed_decisions=0,
                checks=[],
                recommendations=[],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_composite_compare",
            lambda days=5: api_server.RecommendationCompareSnapshot(
                composite=api_server.RecommendationCompareSummary(
                    label="综合榜",
                    sample_days=5,
                    observed_t1_days=1,
                    observed_t3_days=0,
                    observed_t5_days=0,
                    avg_t1_return_pct=5.55,
                    avg_t3_return_pct=None,
                    avg_t5_return_pct=None,
                    t1_win_rate=100.0,
                    t3_win_rate=None,
                    t5_win_rate=None,
                ),
                baseline=api_server.RecommendationCompareSummary(
                    label="原推荐榜",
                    sample_days=5,
                    observed_t1_days=1,
                    observed_t3_days=0,
                    observed_t5_days=0,
                    avg_t1_return_pct=5.55,
                    avg_t3_return_pct=None,
                    avg_t5_return_pct=None,
                    t1_win_rate=100.0,
                    t3_win_rate=None,
                    t5_win_rate=None,
                ),
                advantage=["继续观察"],
                readiness=api_server.RecommendationTakeoverReadiness(
                    status="shadow",
                    label="继续影子",
                    confidence_score=58.0,
                    summary="样本还不够厚，先继续并行观察。",
                    recommended_action="继续累积 T+1/T+3 样本。",
                    conditions=["影子观察天数 5", "T+1 已验证 1 天"],
                ),
                days=[],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_industry_capital_map",
            lambda limit=2: [
                api_server.IndustryCapitalDirection(
                    id="industry-capital-policy-watch-china-us-rivalry",
                    direction="中美博弈与反制链",
                    policy_bucket="自主可控",
                    focus_sector="半导体",
                    strategic_label="逆风跟踪",
                    industry_phase="国产替代兑现前",
                    participation_label="先观察",
                    business_horizon="3-6个月跟踪",
                    capital_horizon="等待确认",
                    strategic_score=61.2,
                    policy_score=73.0,
                    demand_score=58.0,
                    supply_score=55.0,
                    capital_preference_score=41.0,
                    linked_signal_id=None,
                    linked_code="688981",
                    linked_name="中芯国际",
                    linked_setup_label=None,
                    summary="先看反制链和国产替代兑现节奏，再决定资本和事业动作。",
                    business_action="先梳理供应链平替与认证周期。",
                    capital_action="先看前排有没有出现承接和订单验证。",
                    risk_note="如果只有政策口号、没有兑现链和资金承接，就先别重仓。",
                    upstream=["设备"],
                    midstream=["晶圆制造"],
                    downstream=["终端应用"],
                    demand_drivers=["国产替代"],
                    supply_drivers=["制裁倒逼"],
                    milestones=["政策提出", "细则落地", "订单验证"],
                    transmission_paths=["制裁 -> 替代 -> 订单"],
                    opportunities=["设备替代"],
                    official_sources=["国务院"],
                    official_watchpoints=["出口管制清单"],
                    business_checklist=["确认客户认证周期"],
                    capital_checklist=["观察订单兑现"],
                    official_cards=[
                        api_server.IndustryCapitalOfficialCard(
                            title="制裁反制与产业安全",
                            source="国务院 / 商务部",
                            excerpt="先看产业安全链条是否从提法走到采购替代。",
                            why_it_matters="只有进入替代验证，方向才有中期价值。",
                            next_watch="继续盯采购替代和订单验证。",
                        )
                    ],
                    official_documents=["商务部反制口径"],
                    timeline_checkpoints=["政策提出"],
                    cooperation_targets=["设备厂"],
                    cooperation_modes=["联合验证"],
                    company_watchlist=[
                        api_server.IndustryCapitalCompanyItem(
                            code="688981",
                            name="中芯国际",
                            role="先进制造与替代主轴",
                            chain_position="中游",
                            tracking_reason="观察替代兑现。",
                            action="看资本开支和良率。",
                            tracking_score=74.0,
                            priority_label="优先跟踪",
                            market_alignment="方向焦点已锁定",
                            next_check="继续盯采购替代和订单验证。",
                            linked_setup_label=None,
                            linked_source=None,
                        )
                    ],
                    research_targets=["国产替代方案商"],
                    validation_signals=["订单验证"],
                    drivers=["战略分 61.2"],
                )
            ],
        )

        items = api_server._build_action_board(limit=6)

        assert len(items) >= 3
        assert items[0].kind in {"position", "alert"}
        assert any(item.kind == "execution_policy" for item in items)
        assert any(item.kind == "industry_capital" for item in items)
        assert any(item.kind == "composite_pick" for item in items)
        assert any(item.kind == "takeover" for item in items)
        assert any(item.kind == "learning" for item in items)
        composite_item = next(item for item in items if item.kind == "composite_pick")
        industry_item = next(item for item in items if item.kind == "industry_capital")
        assert composite_item.route == "/(tabs)/brain"
        assert composite_item.action_label == "去决策台复核"
        assert industry_item.route == "/industry-capital/industry-capital-policy-watch-china-us-rivalry"
        assert industry_item.action_label == "看方向深页"


class TestThemeRadar:
    def test_build_theme_radar_merges_sector_alerts_messages_and_strong_moves(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_load_sector_alert_history",
            lambda: {
                "alerts": {"稀土永磁": "2026-03-13T14:40:51"},
                "today_log": [
                    {
                        "date": "2026-03-13",
                        "time": "14:40:51",
                        "sector": "稀土永磁",
                        "type": "concept",
                        "change_pct": 2.61,
                        "score": 66.3,
                        "followers": [
                            {
                                "code": "600111",
                                "name": "北方稀土",
                                "change_pct": 3.4,
                                "label": "资金进场 盘中偏强",
                                "buy_price": 21.54,
                                "stop_loss": 20.92,
                                "target_price": 22.68,
                                "risk_reward": 1.8,
                            },
                            {
                                "code": "000831",
                                "name": "中国稀土",
                                "change_pct": 2.2,
                                "label": "跟随走强",
                                "buy_price": 30.1,
                                "stop_loss": 29.2,
                                "target_price": 31.6,
                                "risk_reward": 1.7,
                            },
                        ],
                    }
                ],
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_app_message_center",
            lambda: {
                "items": [
                    {
                        "id": "msg-1",
                        "title": "板块异动 → 跟涨潜力股",
                        "body": "稀土永磁 板块升温",
                        "preview": "稀土永磁 板块升温，龙头与跟风都在走强。",
                        "level": "warning",
                        "channel": "wechat_mirror",
                        "created_at": "2026-03-13T14:40:51",
                    }
                ],
                "last_update": "2026-03-13T14:40:51",
            },
        )
        monkeypatch.setattr(
            api_server,
            "_build_strong_moves",
            lambda days=1, limit=12: [
                api_server.StrongMoveCandidate(
                    id="strong-1",
                    signal_id="sig-1",
                    code="600111",
                    name="北方稀土",
                    strategy="趋势跟踪选股",
                    setup_label="波段候选",
                    conviction="high",
                    composite_score=88.5,
                    continuation_score=85.2,
                    swing_score=92.1,
                    strategy_win_rate=68.2,
                    price=21.54,
                    buy_price=21.54,
                    stop_loss=20.92,
                    target_price=22.68,
                    risk_reward=1.8,
                    timestamp="2026-03-13T14:40:00",
                    thesis="测试",
                    next_step="先打首仓",
                    reasons=["趋势与板块共振"],
                )
            ],
        )

        items = api_server._build_theme_radar(limit=3)

        assert len(items) == 1
        assert items[0].sector == "稀土永磁"
        assert items[0].linked_code == "600111"
        assert items[0].message_hint is not None
        assert len(items[0].followers) == 2


class TestCompositePicks:
    def test_build_composite_picks_falls_back_to_recent_window_when_today_is_empty(self, monkeypatch):
        import api_server

        calls: list[int] = []

        def fake_window(days=1, limit=5):
            calls.append(days)
            if days == 1:
                return []
            return [
                api_server.CompositePick(
                    id="cp-1",
                    signal_id="sig-1",
                    code="002531",
                    name="天顺风能",
                    strategy="趋势跟踪选股",
                    theme_sector="新能源",
                    theme_intensity="持续升温",
                    setup_label="综合进攻候选",
                    conviction="medium",
                    composite_score=63.7,
                    strategy_score=74.6,
                    capital_score=42.0,
                    theme_score=55.0,
                    execution_score=74.2,
                    first_position_pct=10,
                    price=11.72,
                    buy_price=11.72,
                    stop_loss=11.37,
                    target_price=12.42,
                    risk_reward=2.0,
                    timestamp="2026-03-13T10:30:00",
                    thesis="test",
                    action="先试错",
                    reasons=["test"],
                )
            ]

        monkeypatch.setattr(api_server, "_build_composite_picks_for_window", fake_window)

        picks = api_server._build_composite_picks(days=1, limit=5)

        assert calls == [1, 5]
        assert len(picks) == 1
        assert picks[0].code == "002531"

    def test_build_composite_pick_filters_low_upside_spread(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_build_world_state_snapshot",
            lambda: api_server.WorldStateSnapshot(
                regime="neutral",
                regime_score=58.0,
                market_phase="range_rotation",
                market_phase_label="震荡轮动",
                style_bias="快切确认",
                horizon_hint="先按 T+1/T+2 处理。",
                limit_up_mode="只做板前确认",
                limit_up_allowed=True,
                should_trade=True,
                summary="测试",
                drivers=[],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_execution_policy",
            lambda: api_server.ExecutionPolicySnapshot(
                regime="neutral",
                market_phase="range_rotation",
                market_phase_label="震荡轮动",
                style_bias="快切确认",
                horizon_hint="先按 T+1/T+2 处理。",
                aggressiveness="balanced",
                risk_budget_pct=48.0,
                cash_buffer_pct=32.0,
                limit_up_mode="只做板前确认",
                limit_up_allowed=True,
                allowed_styles=["趋势确认"],
                blocked_styles=[],
                allowed_strategies=["趋势跟踪选股"],
                observation_strategies=[],
                blocked_strategies=[],
                preferred_holding_windows=["T+1/T+2"],
                summary="测试",
                key_actions=["测试"],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_production_guard_snapshot",
            lambda: api_server.ProductionGuardSnapshot(
                market_phase="range_rotation",
                market_phase_label="震荡轮动",
                hard_risk_gate=False,
                blocked_additions=False,
                auto_reduce_positions=False,
                auto_exit_losers=False,
                current_drawdown_pct=-1.2,
                max_drawdown_pct=-3.5,
                drawdown_days=1,
                walk_forward_risk="low",
                walk_forward_efficiency=0.82,
                walk_forward_degradation=0.12,
                unstable_strategies=[],
                summary="测试",
                actions=["测试"],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_strategy_governance_map",
            lambda: {
                "趋势跟踪选股": api_server.StrategyGovernanceItem(
                    strategy_id="trend",
                    strategy_name="趋势跟踪选股",
                    family="trend",
                    state="production",
                    weight_pct=100.0,
                    top_down_fit=78.0,
                    recent_fit=68.0,
                    sample_count=10,
                    t1_win_rate=60.0,
                    t3_win_rate=52.0,
                    t5_win_rate=48.0,
                    avg_t1_return_pct=1.0,
                    avg_t3_return_pct=0.8,
                    avg_t5_return_pct=0.6,
                    holding_window_cap="2-5天趋势跟踪",
                    discipline_label="主线滚动",
                    reason="测试",
                )
            },
        )
        monkeypatch.setattr(
            api_server,
            "_strategy_governance_profile",
            lambda strategy_name: {"family": "trend"},
        )
        monkeypatch.setattr(
            api_server,
            "_build_event_control_snapshot",
            lambda signal, theme_item=None: {"score": 58.0, "multiplier": 1.0, "summary": "测试", "bias": "中性"},
        )

        signal = {
            "id": "sig-low-edge",
            "code": "600123",
            "name": "兰花科创",
            "strategy": "趋势跟踪选股",
            "score": 0.92,
            "price": 10.0,
            "buy_price": 10.0,
            "stop_loss": 9.91,
            "target_price": 10.18,
            "risk_reward": 2.0,
            "timestamp": "2026-04-03T10:30:00",
            "change_pct": 1.2,
            "consensus_count": 2,
            "regime": "neutral",
            "factor_scores": {
                "s_trend": 0.86,
                "s_momentum": 0.84,
                "s_hot": 0.71,
                "s_volume_ratio": 0.69,
                "s_fund_flow": 0.72,
            },
        }

        pick = api_server._build_composite_pick_from_record(
            signal,
            strategy_map={
                "趋势跟踪选股": api_server.StrategyPerformance(
                    id="trend",
                    name="趋势跟踪选股",
                    status="active",
                    win_rate=61.0,
                    avg_return=0.2,
                    signal_count=32,
                    last_signal_time="2026-04-03T10:30:00",
                )
            },
            strong_move_map={},
            theme_by_code={},
        )

        assert pick is None

    def test_build_composite_picks_merges_strategy_theme_and_money_flow(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_strategy_governance_map",
            lambda: {
                "趋势跟踪选股": api_server.StrategyGovernanceItem(
                    strategy_id="trend",
                    strategy_name="趋势跟踪选股",
                    family="trend",
                    state="production",
                    weight_pct=100.0,
                    top_down_fit=78.0,
                    recent_fit=68.0,
                    sample_count=10,
                    t1_win_rate=60.0,
                    t3_win_rate=52.0,
                    t5_win_rate=48.0,
                    avg_t1_return_pct=1.0,
                    avg_t3_return_pct=0.8,
                    avg_t5_return_pct=0.6,
                    holding_window_cap="2-5天趋势跟踪",
                    discipline_label="主线滚动",
                    reason="测试",
                ),
                "集合竞价选股": api_server.StrategyGovernanceItem(
                    strategy_id="auction",
                    strategy_name="集合竞价选股",
                    family="auction",
                    state="observation",
                    weight_pct=45.0,
                    top_down_fit=62.0,
                    recent_fit=55.0,
                    sample_count=10,
                    t1_win_rate=51.0,
                    t3_win_rate=46.0,
                    t5_win_rate=41.0,
                    avg_t1_return_pct=0.6,
                    avg_t3_return_pct=0.3,
                    avg_t5_return_pct=0.1,
                    holding_window_cap="T+1/T+2 速决",
                    discipline_label="竞价速决",
                    reason="测试",
                ),
            },
        )
        monkeypatch.setattr(
            api_server,
            "_strategy_governance_profile",
            lambda strategy_name: {"family": "trend" if "趋势" in strategy_name else "auction"},
        )
        monkeypatch.setattr(
            api_server,
            "_build_production_guard_snapshot",
            lambda: api_server.ProductionGuardSnapshot(
                market_phase="rotation_up",
                market_phase_label="轮动走强",
                hard_risk_gate=False,
                blocked_additions=False,
                auto_reduce_positions=False,
                auto_exit_losers=False,
                current_drawdown_pct=-0.5,
                max_drawdown_pct=-3.5,
                drawdown_days=1,
                walk_forward_risk="low",
                walk_forward_efficiency=0.91,
                walk_forward_degradation=0.18,
                unstable_strategies=[],
                summary="当前允许按预算推进。",
                actions=["维持预算。"],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_execution_policy",
            lambda: api_server.ExecutionPolicySnapshot(
                regime="neutral",
                market_phase="rotation_up",
                market_phase_label="轮动走强",
                style_bias="轮动+趋势兼顾",
                horizon_hint="更适合按 T+2/T+3 跟踪。",
                aggressiveness="均衡偏进攻",
                risk_budget_pct=72.0,
                cash_buffer_pct=28.0,
                limit_up_mode="只做板前确认",
                limit_up_allowed=True,
                allowed_styles=["趋势跟踪", "轮动快切"],
                blocked_styles=["高位孤板接力"],
                allowed_strategies=["趋势跟踪选股"],
                observation_strategies=["集合竞价选股"],
                blocked_strategies=[],
                preferred_holding_windows=["2-5天主线跟踪"],
                summary="测试",
                key_actions=["测试"],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_strategies",
            lambda: [
                api_server.StrategyPerformance(
                    id="trend",
                    name="趋势跟踪选股",
                    status="active",
                    win_rate=62.5,
                    avg_return=0.21,
                    signal_count=120,
                    last_signal_time="2026-03-13T10:30:00",
                ),
                api_server.StrategyPerformance(
                    id="auction",
                    name="集合竞价选股",
                    status="active",
                    win_rate=48.0,
                    avg_return=0.12,
                    signal_count=160,
                    last_signal_time="2026-03-13T09:35:00",
                ),
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_load_signal_records",
            lambda days=1: [
                {
                    "id": "sig-a",
                    "code": "600111",
                    "name": "北方稀土",
                    "strategy": "趋势跟踪选股",
                    "score": 0.94,
                    "price": 21.54,
                    "buy_price": 21.54,
                    "stop_loss": 20.92,
                    "target_price": 22.68,
                    "risk_reward": 2.0,
                    "timestamp": "2026-03-13T10:30:00",
                    "change_pct": 2.1,
                    "consensus_count": 2,
                    "regime": "neutral",
                    "factor_scores": {
                        "s_trend": 0.84,
                        "s_momentum": 0.81,
                        "s_hot": 0.77,
                        "s_volume_ratio": 0.73,
                        "s_fund_flow": 0.79,
                        "s_chip": 0.7,
                    },
                },
                {
                    "id": "sig-b",
                    "code": "600595",
                    "name": "中孚实业",
                    "strategy": "集合竞价选股",
                    "score": 0.91,
                    "price": 8.85,
                    "buy_price": 8.85,
                    "stop_loss": 8.58,
                    "target_price": 9.39,
                    "risk_reward": 2.0,
                    "timestamp": "2026-03-13T09:35:00",
                    "change_pct": 6.3,
                    "consensus_count": 1,
                    "regime": "neutral",
                    "factor_scores": {
                        "s_trend": 0.72,
                        "s_hot": 0.65,
                        "s_fund_flow": 0.58,
                    },
                },
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_strong_moves",
            lambda days=1, limit=10: [
                api_server.StrongMoveCandidate(
                    id="strong-a",
                    signal_id="sig-a",
                    code="600111",
                    name="北方稀土",
                    strategy="趋势跟踪选股",
                    setup_label="波段候选",
                    conviction="high",
                    composite_score=86.2,
                    continuation_score=82.0,
                    swing_score=90.4,
                    strategy_win_rate=62.5,
                    price=21.54,
                    buy_price=21.54,
                    stop_loss=20.92,
                    target_price=22.68,
                    risk_reward=2.0,
                    timestamp="2026-03-13T10:30:00",
                    thesis="test",
                    next_step="test",
                    reasons=["test"],
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_theme_radar",
            lambda limit=8: [
                api_server.ThemeRadarItem(
                    id="theme-1",
                    sector="稀土永磁",
                    theme_type="concept",
                    change_pct=2.61,
                    score=66.3,
                    intensity="高热主线",
                    timestamp="2026-03-13T14:40:51",
                    narrative="test",
                    action="test",
                    risk_note="test",
                    message_hint="test",
                    linked_signal_id="sig-a",
                    linked_code="600111",
                    linked_name="北方稀土",
                    linked_setup_label="波段候选",
                    followers=[
                        api_server.ThemeFollower(
                            code="600111",
                            name="北方稀土",
                            change_pct=3.4,
                            label="资金进场",
                            buy_price=21.54,
                            stop_loss=20.92,
                            target_price=22.68,
                            risk_reward=1.8,
                        )
                    ],
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_load_news_digest",
            lambda: {
                "timestamp": "2026-03-13T14:40:51",
                "event_count": 2,
                "events": [
                    {
                        "title": "稀土出口管理趋严",
                        "impact_direction": "bullish",
                        "impact_magnitude": 3,
                        "urgency": "urgent",
                    },
                    {
                        "title": "全球风险偏好回升",
                        "impact_direction": "bullish",
                        "impact_magnitude": 2,
                        "urgency": "normal",
                    },
                ],
                "heatmap": {
                    "sectors": {"稀土": 3, "能源": 1},
                    "sentiment": 0.42,
                    "sentiment_label": "整体偏多",
                },
            },
        )

        picks = api_server._build_composite_picks(days=1, limit=5)

        assert len(picks) == 2
        assert picks[0].code == "600111"
        assert picks[0].theme_sector == "稀土永磁"
        assert picks[0].first_position_pct >= 10
        assert picks[0].composite_score >= picks[1].composite_score
        assert picks[0].event_score > picks[1].event_score
        assert picks[0].event_bias == "偏多"
        assert picks[0].event_matched_sector == "稀土"
        assert picks[0].event_summary is not None
        assert picks[0].source_category in {"resonance", "strong_move"}
        assert picks[0].horizon_label == "中期波段"

    def test_build_composite_picks_penalizes_theme_under_macro_pressure(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_strategy_governance_map",
            lambda: {
                "趋势跟踪选股": api_server.StrategyGovernanceItem(
                    strategy_id="trend",
                    strategy_name="趋势跟踪选股",
                    family="trend",
                    state="production",
                    weight_pct=100.0,
                    top_down_fit=74.0,
                    recent_fit=66.0,
                    sample_count=12,
                    t1_win_rate=57.0,
                    t3_win_rate=51.0,
                    t5_win_rate=46.0,
                    avg_t1_return_pct=0.9,
                    avg_t3_return_pct=0.7,
                    avg_t5_return_pct=0.5,
                    holding_window_cap="2-5天趋势跟踪",
                    discipline_label="主线滚动",
                    reason="测试",
                )
            },
        )
        monkeypatch.setattr(
            api_server,
            "_strategy_governance_profile",
            lambda strategy_name: {"family": "trend"},
        )
        monkeypatch.setattr(
            api_server,
            "_build_execution_policy",
            lambda: api_server.ExecutionPolicySnapshot(
                regime="neutral",
                market_phase="range_rotation",
                market_phase_label="震荡轮动",
                style_bias="快切短拿",
                horizon_hint="更适合按 T+1/T+2 快切。",
                aggressiveness="均衡",
                risk_budget_pct=60.0,
                cash_buffer_pct=40.0,
                limit_up_mode="只做板前确认",
                limit_up_allowed=True,
                allowed_styles=["趋势跟踪"],
                blocked_styles=[],
                allowed_strategies=["趋势跟踪选股"],
                observation_strategies=[],
                blocked_strategies=[],
                preferred_holding_windows=["2-5天主线跟踪"],
                summary="测试",
                key_actions=["测试"],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_production_guard_snapshot",
            lambda: api_server.ProductionGuardSnapshot(
                market_phase="range_rotation",
                market_phase_label="震荡轮动",
                hard_risk_gate=False,
                blocked_additions=False,
                auto_reduce_positions=False,
                auto_exit_losers=False,
                current_drawdown_pct=-1.0,
                max_drawdown_pct=-3.0,
                drawdown_days=1,
                walk_forward_risk="low",
                walk_forward_efficiency=0.9,
                walk_forward_degradation=0.1,
                unstable_strategies=[],
                summary="测试",
                actions=["测试"],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_strategies",
            lambda: [
                api_server.StrategyPerformance(
                    id="trend",
                    name="趋势跟踪选股",
                    status="active",
                    win_rate=58.0,
                    avg_return=0.18,
                    signal_count=90,
                    last_signal_time="2026-03-13T10:30:00",
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_load_signal_records",
            lambda days=1: [
                {
                    "id": "sig-a",
                    "code": "600760",
                    "name": "中航沈飞",
                    "strategy": "趋势跟踪选股",
                    "score": 0.92,
                    "price": 50.2,
                    "buy_price": 50.2,
                    "stop_loss": 48.7,
                    "target_price": 54.0,
                    "risk_reward": 2.2,
                    "timestamp": "2026-03-13T10:30:00",
                    "change_pct": 1.8,
                    "consensus_count": 2,
                    "regime": "neutral",
                    "factor_scores": {
                        "s_trend": 0.81,
                        "s_hot": 0.69,
                        "s_fund_flow": 0.67,
                    },
                },
                {
                    "id": "sig-b",
                    "code": "600777",
                    "name": "新潮能源",
                    "strategy": "趋势跟踪选股",
                    "score": 0.89,
                    "price": 3.5,
                    "buy_price": 3.5,
                    "stop_loss": 3.38,
                    "target_price": 3.78,
                    "risk_reward": 2.3,
                    "timestamp": "2026-03-13T10:32:00",
                    "change_pct": 1.6,
                    "consensus_count": 2,
                    "regime": "neutral",
                    "factor_scores": {
                        "s_trend": 0.77,
                        "s_hot": 0.66,
                        "s_fund_flow": 0.7,
                    },
                },
            ],
        )
        monkeypatch.setattr(api_server, "_build_strong_moves", lambda days=1, limit=10: [])
        monkeypatch.setattr(
            api_server,
            "_build_theme_radar",
            lambda limit=8: [
                api_server.ThemeRadarItem(
                    id="theme-a",
                    sector="军工",
                    theme_type="industry",
                    change_pct=1.9,
                    score=58.0,
                    intensity="持续升温",
                    timestamp="2026-03-13T14:40:51",
                    narrative="test",
                    action="test",
                    risk_note="test",
                    message_hint=None,
                    linked_signal_id="sig-a",
                    linked_code="600760",
                    linked_name="中航沈飞",
                    linked_setup_label="观察",
                    followers=[
                        api_server.ThemeFollower(
                            code="600760",
                            name="中航沈飞",
                            change_pct=1.8,
                            label="跟随观察",
                            buy_price=50.2,
                            stop_loss=48.7,
                            target_price=54.0,
                            risk_reward=2.2,
                        )
                    ],
                ),
                api_server.ThemeRadarItem(
                    id="theme-b",
                    sector="能源",
                    theme_type="industry",
                    change_pct=1.6,
                    score=56.0,
                    intensity="持续升温",
                    timestamp="2026-03-13T14:42:00",
                    narrative="test",
                    action="test",
                    risk_note="test",
                    message_hint=None,
                    linked_signal_id="sig-b",
                    linked_code="600777",
                    linked_name="新潮能源",
                    linked_setup_label="观察",
                    followers=[
                        api_server.ThemeFollower(
                            code="600777",
                            name="新潮能源",
                            change_pct=1.6,
                            label="跟随观察",
                            buy_price=3.5,
                            stop_loss=3.38,
                            target_price=3.78,
                            risk_reward=2.3,
                        )
                    ],
                ),
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_load_news_digest",
            lambda: {
                "timestamp": "2026-03-13T14:50:00",
                "event_count": 3,
                "events": [
                    {
                        "title": "中东局势升级",
                        "impact_direction": "bearish",
                        "impact_magnitude": 3,
                        "urgency": "urgent",
                    },
                    {
                        "title": "油气供给趋紧",
                        "impact_direction": "bullish",
                        "impact_magnitude": 3,
                        "urgency": "urgent",
                    },
                ],
                "heatmap": {
                    "sectors": {"军工": -3, "能源": 3},
                    "sentiment": -0.3,
                    "sentiment_label": "中性偏空",
                },
            },
        )

        picks = api_server._build_composite_picks(days=1, limit=5)

        assert len(picks) == 2
        assert picks[0].code == "600777"
        assert picks[0].event_matched_sector == "能源"
        assert picks[1].event_matched_sector == "军工"
        assert picks[0].event_score > picks[1].event_score
        assert picks[1].first_position_pct <= picks[0].first_position_pct

    def test_build_composite_picks_scales_first_position_by_execution_policy(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_build_execution_policy",
            lambda: api_server.ExecutionPolicySnapshot(
                regime="weak",
                market_phase="weak_chop",
                market_phase_label="弱势拉扯",
                style_bias="轻仓短拿",
                horizon_hint="尾盘短线和竞价修复更适合按 T1 跟踪。",
                aggressiveness="谨慎",
                risk_budget_pct=28.0,
                cash_buffer_pct=72.0,
                limit_up_mode="只做板前确认，不追板",
                limit_up_allowed=True,
                allowed_styles=["竞价短拿", "低吸修复"],
                blocked_styles=["高位接力"],
                allowed_strategies=["趋势跟踪选股"],
                observation_strategies=[],
                blocked_strategies=[],
                preferred_holding_windows=["T+1/T+2 观察"],
                summary="测试",
                key_actions=["测试"],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_world_state_snapshot",
            lambda: api_server.WorldStateSnapshot(
                regime="weak",
                regime_score=42.0,
                market_phase="weak_chop",
                market_phase_label="弱势拉扯",
                style_bias="轻仓短拿",
                horizon_hint="尾盘短线和竞价修复更适合按 T1 跟踪。",
                limit_up_mode="只做板前确认，不追板",
                limit_up_allowed=True,
                should_trade=True,
                summary="测试",
                drivers=[],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_strategies",
            lambda: [
                api_server.StrategyPerformance(
                    id="trend",
                    name="趋势跟踪选股",
                    status="active",
                    win_rate=62.5,
                    avg_return=0.21,
                    signal_count=120,
                    last_signal_time="2026-03-13T10:30:00",
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_strategy_governance",
            lambda: api_server.StrategyGovernanceSnapshot(
                regime="weak",
                market_phase="weak_chop",
                market_phase_label="弱势拉扯",
                summary="测试",
                production_count=1,
                observation_count=0,
                disabled_count=0,
                items=[
                    api_server.StrategyGovernanceItem(
                        strategy_id="trend",
                        strategy_name="趋势跟踪选股",
                        family="trend",
                        state="production",
                        weight_pct=100.0,
                        top_down_fit=72.0,
                        recent_fit=64.0,
                        sample_count=12,
                        holding_window_cap="2-5天主线跟踪",
                        discipline_label="主线滚动",
                        reason="测试",
                    )
                ],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_load_signal_records",
            lambda days=1: [
                {
                    "id": "sig-a",
                    "code": "600111",
                    "name": "北方稀土",
                    "strategy": "趋势跟踪选股",
                    "score": 0.94,
                    "price": 21.54,
                    "buy_price": 21.54,
                    "stop_loss": 20.92,
                    "target_price": 22.68,
                    "risk_reward": 2.0,
                    "timestamp": "2026-03-13T10:30:00",
                    "change_pct": 2.1,
                    "consensus_count": 2,
                    "regime": "neutral",
                    "factor_scores": {
                        "s_trend": 0.84,
                        "s_momentum": 0.81,
                        "s_hot": 0.77,
                        "s_volume_ratio": 0.73,
                        "s_fund_flow": 0.79,
                        "s_chip": 0.7,
                    },
                }
            ],
        )
        monkeypatch.setattr(api_server, "_build_strong_moves", lambda days=1, limit=10: [])
        monkeypatch.setattr(api_server, "_build_theme_radar", lambda limit=8: [])
        monkeypatch.setattr(api_server, "_build_event_control_snapshot", lambda signal, theme_item: {"score": 50.0, "bias": "中性", "multiplier": 1.0, "summary": ""})

        picks = api_server._build_composite_picks(days=1, limit=5)

        assert len(picks) == 1
        assert picks[0].first_position_pct <= 8

    def test_build_composite_picks_filters_blocked_strategies_from_execution_policy(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_build_execution_policy",
            lambda: api_server.ExecutionPolicySnapshot(
                regime="weak",
                market_phase="weak_chop",
                market_phase_label="弱势拉扯",
                style_bias="轻仓短拿",
                horizon_hint="更适合短拿。",
                aggressiveness="谨慎",
                risk_budget_pct=28.0,
                cash_buffer_pct=72.0,
                limit_up_mode="只做板前确认，不追板",
                limit_up_allowed=True,
                allowed_styles=["竞价短拿"],
                blocked_styles=["高位接力"],
                allowed_strategies=["集合竞价选股"],
                observation_strategies=[],
                blocked_strategies=["趋势跟踪选股"],
                preferred_holding_windows=["T+1/T+2 观察"],
                summary="测试",
                key_actions=["测试"],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_world_state_snapshot",
            lambda: api_server.WorldStateSnapshot(
                regime="weak",
                regime_score=42.0,
                market_phase="weak_chop",
                market_phase_label="弱势拉扯",
                style_bias="轻仓短拿",
                horizon_hint="更适合短拿。",
                limit_up_mode="只做板前确认，不追板",
                limit_up_allowed=True,
                should_trade=True,
                summary="测试",
                drivers=[],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_strategies",
            lambda: [
                api_server.StrategyPerformance(
                    id="trend",
                    name="趋势跟踪选股",
                    status="active",
                    win_rate=62.5,
                    avg_return=0.21,
                    signal_count=120,
                    last_signal_time="2026-03-13T10:30:00",
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_strategy_governance",
            lambda: api_server.StrategyGovernanceSnapshot(
                regime="weak",
                market_phase="weak_chop",
                market_phase_label="弱势拉扯",
                summary="测试",
                production_count=1,
                observation_count=0,
                disabled_count=0,
                items=[
                    api_server.StrategyGovernanceItem(
                        strategy_id="trend",
                        strategy_name="趋势跟踪选股",
                        family="trend",
                        state="production",
                        weight_pct=100.0,
                        top_down_fit=72.0,
                        recent_fit=64.0,
                        sample_count=12,
                        holding_window_cap="2-5天主线跟踪",
                        discipline_label="主线滚动",
                        reason="测试",
                    )
                ],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_load_signal_records",
            lambda days=1: [
                {
                    "id": "sig-a",
                    "code": "600111",
                    "name": "北方稀土",
                    "strategy": "趋势跟踪选股",
                    "score": 0.94,
                    "price": 21.54,
                    "buy_price": 21.54,
                    "stop_loss": 20.92,
                    "target_price": 22.68,
                    "risk_reward": 2.0,
                    "timestamp": "2026-03-13T10:30:00",
                    "change_pct": 2.1,
                    "consensus_count": 2,
                    "regime": "neutral",
                    "factor_scores": {
                        "s_trend": 0.84,
                        "s_momentum": 0.81,
                        "s_hot": 0.77,
                        "s_volume_ratio": 0.73,
                        "s_fund_flow": 0.79,
                        "s_chip": 0.7,
                    },
                }
            ],
        )
        monkeypatch.setattr(api_server, "_build_strong_moves", lambda days=1, limit=10: [])
        monkeypatch.setattr(api_server, "_build_theme_radar", lambda limit=8: [])
        monkeypatch.setattr(
            api_server,
            "_build_event_control_snapshot",
            lambda signal, theme_item: {"score": 50.0, "bias": "中性", "multiplier": 1.0, "summary": ""},
        )

        picks = api_server._build_composite_picks(days=1, limit=5)

        assert picks == []

    def test_build_composite_picks_adds_theme_seed_candidates_without_strategy_signal(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_build_strategies",
            lambda: [
                api_server.StrategyPerformance(
                    id="trend",
                    name="趋势跟踪选股",
                    status="active",
                    win_rate=61.0,
                    avg_return=0.19,
                    signal_count=88,
                    last_signal_time="2026-03-14T10:30:00",
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_load_signal_records",
            lambda days=1: [
                {
                    "id": "sig-a",
                    "code": "600111",
                    "name": "北方稀土",
                    "strategy": "趋势跟踪选股",
                    "score": 0.93,
                    "price": 21.54,
                    "buy_price": 21.54,
                    "stop_loss": 20.92,
                    "target_price": 22.68,
                    "risk_reward": 2.0,
                    "timestamp": "2026-03-14T10:30:00",
                    "change_pct": 2.1,
                    "consensus_count": 2,
                    "regime": "neutral",
                    "factor_scores": {
                        "s_trend": 0.84,
                        "s_hot": 0.77,
                        "s_fund_flow": 0.79,
                    },
                }
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_strong_moves",
            lambda days=1, limit=10: [
                api_server.StrongMoveCandidate(
                    id="strong-a",
                    signal_id="sig-a",
                    code="600111",
                    name="北方稀土",
                    strategy="趋势跟踪选股",
                    setup_label="波段候选",
                    conviction="high",
                    composite_score=84.5,
                    continuation_score=80.1,
                    swing_score=88.2,
                    strategy_win_rate=61.0,
                    price=21.54,
                    buy_price=21.54,
                    stop_loss=20.92,
                    target_price=22.68,
                    risk_reward=2.0,
                    timestamp="2026-03-14T10:30:00",
                    thesis="test",
                    next_step="test",
                    reasons=["test"],
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_theme_radar",
            lambda limit=8: [
                api_server.ThemeRadarItem(
                    id="theme-1",
                    sector="稀土永磁",
                    theme_type="concept",
                    change_pct=2.61,
                    score=67.3,
                    intensity="高热主线",
                    timestamp="2026-03-14T14:40:51",
                    narrative="test",
                    action="test",
                    risk_note="test",
                    message_hint="test",
                    linked_signal_id="sig-a",
                    linked_code="600111",
                    linked_name="北方稀土",
                    linked_setup_label="波段候选",
                    followers=[
                        api_server.ThemeFollower(
                            code="603993",
                            name="洛阳钼业",
                            change_pct=2.8,
                            label="重点",
                            buy_price=7.52,
                            stop_loss=7.22,
                            target_price=8.18,
                            risk_reward=2.2,
                        )
                    ],
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_load_news_digest",
            lambda: {
                "timestamp": "2026-03-14T14:40:51",
                "event_count": 1,
                "events": [
                    {
                        "title": "关键金属供需持续偏紧",
                        "impact_direction": "bullish",
                        "impact_magnitude": 2,
                        "urgency": "normal",
                    }
                ],
                "heatmap": {
                    "sectors": {"稀土": 3},
                    "sentiment": 0.35,
                    "sentiment_label": "偏多",
                },
            },
        )

        picks = api_server._build_composite_picks(days=1, limit=5)

        seed_pick = next((item for item in picks if item.code == "603993"), None)
        assert seed_pick is not None
        assert seed_pick.theme_sector == "稀土永磁"
        assert seed_pick.strategy in {"主线资金共振", "主线接力"}
        assert seed_pick.event_bias == "偏多"
        assert seed_pick.composite_score >= 55
        assert seed_pick.source_category == "theme_seed"
        assert seed_pick.source_label == "主线种子"
        assert seed_pick.horizon_label == "主线孵化"


class TestThemeStageEngine:
    def test_build_theme_stage_engine_marks_theme_seed_as_early_stage(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_build_theme_radar",
            lambda limit=6: [
                api_server.ThemeRadarItem(
                    id="theme-1",
                    sector="奢侈品",
                    theme_type="concept",
                    change_pct=1.61,
                    score=52.3,
                    intensity="持续升温",
                    timestamp="2026-03-14T10:30:00",
                    narrative="test",
                    action="test",
                    risk_note="test",
                    message_hint="镜像里已经出现奢侈品",
                    linked_signal_id=None,
                    linked_code=None,
                    linked_name=None,
                    linked_setup_label=None,
                    followers=[
                        api_server.ThemeFollower(
                            code="000858",
                            name="五 粮 液",
                            change_pct=0.79,
                            label="资金进场 盘中偏强",
                            buy_price=102.77,
                            stop_loss=101.34,
                            target_price=105.14,
                            risk_reward=1.2,
                        )
                    ],
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_composite_picks",
            lambda days=1, limit=12: [
                api_server.CompositePick(
                    id="cp-1",
                    signal_id="theme-seed-1",
                    code="000858",
                    name="五 粮 液",
                    strategy="主线资金共振",
                    theme_sector="奢侈品",
                    theme_intensity="持续升温",
                    setup_label="备选观察",
                    conviction="low",
                    composite_score=55.9,
                    strategy_score=66.3,
                    capital_score=40.9,
                    theme_score=57.2,
                    event_score=52.1,
                    event_bias="中性",
                    event_summary="test",
                    event_matched_sector=None,
                    source_category="theme_seed",
                    source_label="主线种子",
                    horizon_label="主线孵化",
                    execution_score=58.1,
                    first_position_pct=8,
                    price=102.77,
                    buy_price=102.77,
                    stop_loss=101.34,
                    target_price=105.14,
                    risk_reward=1.2,
                    timestamp="2026-03-14T10:30:00",
                    thesis="test",
                    action="观察龙头确认",
                    reasons=["test"],
                )
            ],
        )
        monkeypatch.setattr(api_server, "_build_strong_moves", lambda days=1, limit=12: [])

        items = api_server._build_theme_stage_engine(limit=3)

        assert len(items) == 1
        assert items[0].sector == "奢侈品"
        assert items[0].stage_label in {"早期孵化", "中期扩散"}
        assert items[0].participation_label == "主线观察"

    def test_build_theme_stage_engine_marks_swing_as_mid_stage(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_build_theme_radar",
            lambda limit=6: [
                api_server.ThemeRadarItem(
                    id="theme-1",
                    sector="稀土永磁",
                    theme_type="concept",
                    change_pct=3.12,
                    score=68.3,
                    intensity="高热主线",
                    timestamp="2026-03-14T10:30:00",
                    narrative="test",
                    action="test",
                    risk_note="test",
                    message_hint="微信镜像已多次出现稀土",
                    linked_signal_id="sig-1",
                    linked_code="600111",
                    linked_name="北方稀土",
                    linked_setup_label="波段候选",
                    followers=[
                        api_server.ThemeFollower(
                            code="600111",
                            name="北方稀土",
                            change_pct=2.8,
                            label="资金抱团",
                            buy_price=21.54,
                            stop_loss=20.92,
                            target_price=22.68,
                            risk_reward=2.0,
                        )
                    ],
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_composite_picks",
            lambda days=1, limit=12: [
                api_server.CompositePick(
                    id="cp-1",
                    signal_id="sig-1",
                    code="600111",
                    name="北方稀土",
                    strategy="趋势跟踪选股",
                    theme_sector="稀土永磁",
                    theme_intensity="高热主线",
                    setup_label="综合进攻候选",
                    conviction="high",
                    composite_score=74.5,
                    strategy_score=76.3,
                    capital_score=72.1,
                    theme_score=80.2,
                    event_score=61.0,
                    event_bias="偏多",
                    event_summary="test",
                    event_matched_sector="稀土",
                    source_category="resonance",
                    source_label="主线共振",
                    horizon_label="中期波段",
                    execution_score=73.1,
                    first_position_pct=10,
                    price=21.54,
                    buy_price=21.54,
                    stop_loss=20.92,
                    target_price=22.68,
                    risk_reward=2.0,
                    timestamp="2026-03-14T10:30:00",
                    thesis="test",
                    action="test",
                    reasons=["test"],
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_strong_moves",
            lambda days=1, limit=12: [
                api_server.StrongMoveCandidate(
                    id="strong-1",
                    signal_id="sig-1",
                    code="600111",
                    name="北方稀土",
                    strategy="趋势跟踪选股",
                    setup_label="波段候选",
                    conviction="high",
                    composite_score=82.0,
                    continuation_score=74.0,
                    swing_score=86.0,
                    strategy_win_rate=61.0,
                    price=21.54,
                    buy_price=21.54,
                    stop_loss=20.92,
                    target_price=22.68,
                    risk_reward=2.0,
                    timestamp="2026-03-14T10:30:00",
                    thesis="test",
                    next_step="test",
                    reasons=["test"],
                )
            ],
        )

        items = api_server._build_theme_stage_engine(limit=3)

        assert len(items) == 1
        assert items[0].sector == "稀土永磁"
        assert items[0].stage_label in {"主升波段", "高位分歧"}
        assert items[0].participation_label == "中期波段"

    def test_build_theme_seed_signal_record_skips_delisted_or_st_names(self):
        import api_server

        theme_item = api_server.ThemeRadarItem(
            id="theme-1",
            sector="奢侈品",
            theme_type="concept",
            change_pct=1.6,
            score=52.3,
            intensity="持续升温",
            timestamp="2026-03-14T14:40:51",
            narrative="test",
            action="test",
            risk_note="test",
            message_hint=None,
            linked_signal_id=None,
            linked_code=None,
            linked_name=None,
            linked_setup_label=None,
            followers=[],
        )

        blocked = api_server._build_theme_seed_signal_record(
            theme_item,
            api_server.ThemeFollower(
                code="600086",
                name="退市金钰",
                change_pct=0.0,
                label="观察",
                buy_price=3.29,
                stop_loss=0.0,
                target_price=3.37,
                risk_reward=0.0,
            ),
            linked_signal=None,
        )

        assert blocked is None


class TestPolicyWatch:
    def test_build_policy_watch_identifies_ai_direction(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_load_news_digest",
            lambda: {
                "events": [
                    {
                        "title": "量子计算突破带动算力基础设施再受关注",
                        "category": "policy",
                        "impact_direction": "bullish",
                        "impact_magnitude": 2,
                        "affected_sectors": ["半导体", "通信", "科技"],
                        "sector_impacts": {"半导体": 2, "通信": 2, "科技": 2},
                        "strategy_implications": "关注算力和芯片链",
                        "urgency": "normal",
                        "confidence": 0.7,
                        "timestamp": "2026-03-14 15:52:35",
                    }
                ]
            },
        )
        monkeypatch.setattr(
            api_server,
            "_build_theme_radar",
            lambda limit=8: [
                api_server.ThemeRadarItem(
                    id="theme-tech",
                    sector="科技",
                    theme_type="concept",
                    change_pct=2.36,
                    score=66.4,
                    intensity="持续升温",
                    timestamp="2026-03-14T14:10:00",
                    narrative="test",
                    action="test",
                    risk_note="test",
                    message_hint="镜像里已经出现科技主线",
                    linked_signal_id="sig-tech",
                    linked_code="688256",
                    linked_name="寒武纪",
                    linked_setup_label="波段候选",
                    followers=[],
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_composite_picks",
            lambda days=1, limit=12: [
                api_server.CompositePick(
                    id="cp-tech",
                    signal_id="sig-tech",
                    code="688256",
                    name="寒武纪",
                    strategy="趋势跟踪选股",
                    theme_sector="科技",
                    theme_intensity="持续升温",
                    setup_label="综合进攻候选",
                    conviction="high",
                    composite_score=72.8,
                    strategy_score=74.1,
                    capital_score=70.5,
                    theme_score=76.0,
                    event_score=65.0,
                    event_bias="偏多",
                    event_summary="科技事件偏多",
                    event_matched_sector="科技",
                    source_category="resonance",
                    source_label="主线共振",
                    horizon_label="中期波段",
                    execution_score=69.4,
                    first_position_pct=10,
                    price=142.3,
                    buy_price=142.3,
                    stop_loss=137.8,
                    target_price=151.5,
                    risk_reward=2.1,
                    timestamp="2026-03-14T14:10:00",
                    thesis="test",
                    action="test",
                    reasons=["test"],
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_strong_moves",
            lambda days=1, limit=12: [
                api_server.StrongMoveCandidate(
                    id="strong-tech",
                    signal_id="sig-tech",
                    code="688256",
                    name="寒武纪",
                    strategy="趋势跟踪选股",
                    setup_label="波段候选",
                    conviction="high",
                    composite_score=80.0,
                    continuation_score=74.0,
                    swing_score=84.0,
                    strategy_win_rate=62.0,
                    price=142.3,
                    buy_price=142.3,
                    stop_loss=137.8,
                    target_price=151.5,
                    risk_reward=2.1,
                    timestamp="2026-03-14T14:10:00",
                    thesis="test",
                    next_step="test",
                    reasons=["test"],
                )
            ],
        )

        items = api_server._build_policy_watch(limit=3)

        assert items
        assert items[0].direction == "AI与数字基础设施"
        assert items[0].focus_sector == "科技"
        assert items[0].linked_code == "688256"
        assert items[0].stage_label in {"政策跟踪", "催化升温", "兑现扩散"}

    def test_build_policy_watch_can_surface_macro_direction_without_theme(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_load_news_digest",
            lambda: {
                "events": [
                    {
                        "title": "机构预计年内仍有降息窗口",
                        "category": "policy",
                        "impact_direction": "bullish",
                        "impact_magnitude": 2,
                        "affected_sectors": ["银行", "证券", "保险"],
                        "sector_impacts": {"银行": 2, "证券": 2, "保险": 2},
                        "strategy_implications": "关注金融稳增长链条",
                        "urgency": "normal",
                        "confidence": 0.6,
                        "timestamp": "2026-03-14 09:10:00",
                    }
                ]
            },
        )
        monkeypatch.setattr(api_server, "_build_theme_radar", lambda limit=8: [])
        monkeypatch.setattr(api_server, "_build_composite_picks", lambda days=1, limit=12: [])
        monkeypatch.setattr(api_server, "_build_strong_moves", lambda days=1, limit=12: [])

        items = api_server._build_policy_watch(limit=5)

        finance = next((item for item in items if item.direction == "金融稳增长"), None)
        assert finance is not None
        assert finance.policy_bucket == "宏观政策"
        assert finance.linked_code is None
        assert finance.participation_label in {"先观察", "主线观察"}


class TestPositioningPlan:
    def test_build_positioning_plan_summarizes_exposure_and_deployments(self, monkeypatch):
        import api_server
        import smart_trader

        monkeypatch.setattr(
            smart_trader,
            "detect_market_regime",
            lambda: {
                "regime": "neutral",
                "score": 0.58,
                "position_scale": 0.8,
                "regime_params": {"max_positions": 6},
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_portfolio",
            lambda: {
                "positions": [],
                "cash": 100000.0,
                "total_assets": 100000.0,
            },
        )
        monkeypatch.setattr(
            api_server,
            "_build_production_guard_snapshot",
            lambda: api_server.ProductionGuardSnapshot(
                market_phase="range_rotation",
                market_phase_label="震荡轮动",
                hard_risk_gate=False,
                blocked_additions=False,
                auto_reduce_positions=False,
                auto_exit_losers=False,
                current_drawdown_pct=0.0,
                max_drawdown_pct=-2.0,
                drawdown_days=0,
                walk_forward_risk="low",
                walk_forward_efficiency=1.0,
                walk_forward_degradation=0.1,
                unstable_strategies=[],
                summary="当前允许按预算推进。",
                actions=["维持预算。"],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_composite_picks",
            lambda days=1, limit=5: [
                api_server.CompositePick(
                    id="cp-1",
                    signal_id="sig-1",
                    code="002531",
                    name="天顺风能",
                    strategy="趋势跟踪选股",
                    theme_sector="新能源",
                    theme_intensity="持续升温",
                    setup_label="综合进攻候选",
                    conviction="medium",
                    composite_score=63.7,
                    strategy_score=74.6,
                    capital_score=42.0,
                    theme_score=55.0,
                    execution_score=74.2,
                    first_position_pct=10,
                    price=11.72,
                    buy_price=11.72,
                    stop_loss=11.37,
                    target_price=12.42,
                    risk_reward=2.0,
                    timestamp="2026-03-13T10:30:00",
                    thesis="test",
                    action="先试错",
                    reasons=["强势收益引擎已标记为波段候选。"],
                ),
                api_server.CompositePick(
                    id="cp-2",
                    signal_id="sig-2",
                    code="603393",
                    name="新天然气",
                    strategy="趋势跟踪选股",
                    theme_sector="能源",
                    theme_intensity="持续升温",
                    setup_label="备选观察",
                    conviction="medium",
                    composite_score=62.6,
                    strategy_score=76.7,
                    capital_score=38.5,
                    theme_score=55.0,
                    execution_score=72.2,
                    first_position_pct=10,
                    price=42.67,
                    buy_price=42.67,
                    stop_loss=41.39,
                    target_price=45.23,
                    risk_reward=2.0,
                    timestamp="2026-03-13T10:30:00",
                    thesis="test",
                    action="先试错",
                    reasons=["趋势形态仍在向上延续。"],
                ),
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_execution_policy",
            lambda: api_server.ExecutionPolicySnapshot(
                regime="neutral",
                market_phase="range_rotation",
                market_phase_label="震荡轮动",
                style_bias="轮动快切",
                horizon_hint="先做轮动。",
                aggressiveness="平衡",
                risk_budget_pct=58.0,
                cash_buffer_pct=42.0,
                limit_up_mode="只做板前确认",
                limit_up_allowed=True,
                allowed_styles=["低吸回调", "集合竞价短拿"],
                blocked_styles=["把短线票硬拿成波段"],
                allowed_strategies=["趋势跟踪选股", "低吸回调选股"],
                observation_strategies=["集合竞价选股"],
                blocked_strategies=[],
                preferred_holding_windows=["1-3天反弹跟踪", "2-5天趋势跟踪"],
                summary="测试",
                key_actions=["测试"],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_theme_radar",
            lambda limit=3: [
                api_server.ThemeRadarItem(
                    id="theme-1",
                    sector="新能源",
                    theme_type="concept",
                    change_pct=2.61,
                    score=66.3,
                    intensity="持续升温",
                    timestamp="2026-03-13T14:40:51",
                    narrative="test",
                    action="test",
                    risk_note="test",
                    message_hint="test",
                    linked_signal_id="sig-1",
                    linked_code="002531",
                    linked_name="天顺风能",
                    linked_setup_label="综合进攻候选",
                    followers=[],
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_load_news_digest",
            lambda: {
                "timestamp": "2026-03-13T14:50:00",
                "event_count": 2,
                "events": [
                    {
                        "title": "新能源政策继续加码",
                        "impact_direction": "bullish",
                        "impact_magnitude": 3,
                        "urgency": "urgent",
                    }
                ],
                "heatmap": {
                    "sectors": {"新能源": 3, "能源": 1},
                    "sentiment": 0.45,
                    "sentiment_label": "整体偏多",
                },
            },
        )
        monkeypatch.setattr(api_server, "_build_risk_alerts", lambda: [])

        plan = api_server._build_positioning_plan(days=1, limit=3)

        assert plan.mode in {"平衡", "进攻"}
        assert plan.target_exposure_pct >= 50
        assert plan.deployable_exposure_pct == plan.target_exposure_pct
        assert plan.first_entry_position_pct >= 10
        assert plan.max_single_position_pct >= 15
        assert plan.top_theme == "新能源"
        assert plan.event_bias == "偏多"
        assert plan.event_focus_sector == "新能源"
        assert plan.event_score > 50
        assert plan.event_summary is not None
        assert len(plan.deployments) >= 1
        assert plan.deployments[0].code == "002531"

    def test_build_positioning_plan_hard_gate_caps_exposure_and_first_entry(self, monkeypatch):
        import api_server
        import smart_trader

        monkeypatch.setattr(
            smart_trader,
            "detect_market_regime",
            lambda: {
                "regime": "weak",
                "score": 0.42,
                "position_scale": 0.6,
                "regime_params": {"max_positions": 5},
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_portfolio",
            lambda: {
                "positions": [{"code": "600000", "quantity": 1000, "current_price": 10.0}],
                "cash": 70000.0,
                "total_assets": 100000.0,
            },
        )
        monkeypatch.setattr(api_server, "_build_composite_picks", lambda days=1, limit=5: [])
        monkeypatch.setattr(api_server, "_build_theme_radar", lambda limit=3: [])
        monkeypatch.setattr(api_server, "_build_risk_alerts", lambda: [])
        monkeypatch.setattr(
            api_server,
            "_build_production_guard_snapshot",
            lambda: api_server.ProductionGuardSnapshot(
                market_phase="risk_off",
                market_phase_label="退潮避险",
                hard_risk_gate=True,
                blocked_additions=True,
                auto_reduce_positions=True,
                auto_exit_losers=True,
                current_drawdown_pct=-6.1,
                max_drawdown_pct=-9.8,
                drawdown_days=7,
                walk_forward_risk="high",
                walk_forward_efficiency=0.58,
                walk_forward_degradation=0.71,
                unstable_strategies=["趋势跟踪选股"],
                summary="当前生产风控禁止新增，先处理存量风险。",
                actions=["暂停新增仓位。"],
            ),
        )

        plan = api_server._build_positioning_plan(days=1, limit=3)

        assert plan.hard_risk_gate is True
        assert plan.first_entry_position_pct == 0
        assert plan.target_exposure_pct <= plan.current_exposure_pct
        assert plan.risk_guard_summary is not None
        assert any("生产风控" in action for action in plan.actions)

    def test_build_positioning_plan_reduces_exposure_when_macro_bias_is_bearish(self, monkeypatch):
        import api_server
        import smart_trader

        monkeypatch.setattr(
            smart_trader,
            "detect_market_regime",
            lambda: {
                "regime": "neutral",
                "score": 0.58,
                "position_scale": 0.8,
                "regime_params": {"max_positions": 6},
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_portfolio",
            lambda: {
                "positions": [],
                "cash": 100000.0,
                "total_assets": 100000.0,
            },
        )
        monkeypatch.setattr(
            api_server,
            "_build_composite_picks",
            lambda days=1, limit=5: [
                api_server.CompositePick(
                    id="cp-1",
                    signal_id="sig-1",
                    code="600760",
                    name="中航沈飞",
                    strategy="趋势跟踪选股",
                    theme_sector="军工",
                    theme_intensity="持续升温",
                    setup_label="综合进攻候选",
                    conviction="medium",
                    composite_score=68.0,
                    strategy_score=74.0,
                    capital_score=50.0,
                    theme_score=60.0,
                    execution_score=73.0,
                    first_position_pct=10,
                    price=50.2,
                    buy_price=50.2,
                    stop_loss=48.7,
                    target_price=54.0,
                    risk_reward=2.2,
                    timestamp="2026-03-13T10:30:00",
                    thesis="test",
                    action="先试错",
                    reasons=["test"],
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_theme_radar",
            lambda limit=3: [
                api_server.ThemeRadarItem(
                    id="theme-1",
                    sector="军工",
                    theme_type="industry",
                    change_pct=2.0,
                    score=60.0,
                    intensity="持续升温",
                    timestamp="2026-03-13T14:40:51",
                    narrative="test",
                    action="test",
                    risk_note="test",
                    message_hint="test",
                    linked_signal_id="sig-1",
                    linked_code="600760",
                    linked_name="中航沈飞",
                    linked_setup_label="综合进攻候选",
                    followers=[],
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_load_news_digest",
            lambda: {
                "timestamp": "2026-03-13T14:50:00",
                "event_count": 2,
                "events": [
                    {
                        "title": "地缘冲突升级",
                        "impact_direction": "bearish",
                        "impact_magnitude": 3,
                        "urgency": "urgent",
                    }
                ],
                "heatmap": {
                    "sectors": {"军工": -3},
                    "sentiment": -0.6,
                    "sentiment_label": "整体偏空",
                },
            },
        )
        monkeypatch.setattr(api_server, "_build_risk_alerts", lambda: [])

        plan = api_server._build_positioning_plan(days=1, limit=3)

        assert plan.event_bias == "偏空"
        assert plan.event_focus_sector == "军工"
        assert plan.event_score < 50
        assert plan.target_exposure_pct < 56
        assert plan.first_entry_position_pct < 10
        assert plan.max_theme_exposure_pct < 28


class TestCompositeReplay:
    def test_build_composite_replay_links_pick_with_verified_outcomes(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_strategy_governance_map",
            lambda: {
                "趋势跟踪选股": api_server.StrategyGovernanceItem(
                    strategy_id="trend",
                    strategy_name="趋势跟踪选股",
                    family="trend",
                    state="production",
                    weight_pct=100.0,
                    top_down_fit=78.0,
                    recent_fit=68.0,
                    sample_count=10,
                    t1_win_rate=60.0,
                    t3_win_rate=52.0,
                    t5_win_rate=48.0,
                    avg_t1_return_pct=1.0,
                    avg_t3_return_pct=0.8,
                    avg_t5_return_pct=0.6,
                    holding_window_cap="2-5天趋势跟踪",
                    discipline_label="主线滚动",
                    reason="测试",
                )
            },
        )
        monkeypatch.setattr(
            api_server,
            "_strategy_governance_profile",
            lambda strategy_name: {"family": "trend"},
        )
        monkeypatch.setattr(
            api_server,
            "_build_strategies",
            lambda: [
                api_server.StrategyPerformance(
                    id="trend",
                    name="趋势跟踪选股",
                    status="active",
                    win_rate=62.5,
                    avg_return=0.21,
                    signal_count=120,
                    last_signal_time="2026-03-13T10:30:00",
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_load_live_signal_records",
            lambda days=10: [
                {
                    "id": "sig-a",
                    "code": "600111",
                    "name": "北方稀土",
                    "strategy": "趋势跟踪选股",
                    "score": 0.94,
                    "price": 21.54,
                    "buy_price": 21.54,
                    "stop_loss": 20.92,
                    "target_price": 22.68,
                    "risk_reward": 2.0,
                    "timestamp": "2026-03-12T10:30:00",
                    "change_pct": 2.1,
                    "consensus_count": 2,
                    "regime": "neutral",
                    "factor_scores": {
                        "s_trend": 0.84,
                        "s_momentum": 0.81,
                        "s_hot": 0.77,
                        "s_volume_ratio": 0.73,
                        "s_fund_flow": 0.79,
                        "s_chip": 0.7,
                    },
                }
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_load_signal_verification_records",
            lambda days=20: {
                "2026-03-12|趋势跟踪选股|600111": {
                    "verify": {
                        "t1": {"return_pct": 2.31},
                        "t3": {"return_pct": 4.82},
                    }
                }
            },
        )

        items = api_server._build_composite_replay(days=5, per_day=1)

        assert len(items) == 1
        assert items[0].code == "600111"
        assert items[0].review_label == "验证通过"
        assert items[0].t1_return_pct == 2.31
        assert items[0].t3_return_pct == 4.82
        assert items[0].verified_days == 2


class TestCompositeCompare:
    def test_build_composite_compare_summarizes_shadow_vs_baseline(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_build_strategies",
            lambda: [
                api_server.StrategyPerformance(
                    id="trend",
                    name="趋势跟踪选股",
                    status="active",
                    win_rate=62.5,
                    avg_return=0.21,
                    signal_count=120,
                    last_signal_time="2026-03-13T10:30:00",
                ),
                api_server.StrategyPerformance(
                    id="overnight",
                    name="隔夜选股",
                    status="active",
                    win_rate=59.0,
                    avg_return=0.16,
                    signal_count=220,
                    last_signal_time="2026-03-13T09:35:00",
                ),
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_load_live_signal_records",
            lambda days=10: [
                {
                    "id": "sig-a",
                    "code": "600111",
                    "name": "北方稀土",
                    "strategy": "趋势跟踪选股",
                    "score": 0.91,
                    "price": 21.54,
                    "buy_price": 21.54,
                    "stop_loss": 20.92,
                    "target_price": 22.68,
                    "risk_reward": 2.0,
                    "timestamp": "2026-03-13T10:30:00",
                    "change_pct": 2.1,
                    "consensus_count": 2,
                    "regime": "neutral",
                },
                {
                    "id": "sig-b",
                    "code": "600618",
                    "name": "氯碱化工",
                    "strategy": "隔夜选股",
                    "score": 0.95,
                    "price": 10.54,
                    "buy_price": 10.54,
                    "stop_loss": 10.02,
                    "target_price": 11.3,
                    "risk_reward": 1.8,
                    "timestamp": "2026-03-13T09:35:00",
                    "change_pct": 1.2,
                    "consensus_count": 1,
                    "regime": "neutral",
                },
                {
                    "id": "sig-c",
                    "code": "002531",
                    "name": "天顺风能",
                    "strategy": "隔夜选股",
                    "score": 0.93,
                    "price": 9.83,
                    "buy_price": 9.83,
                    "stop_loss": 9.42,
                    "target_price": 10.6,
                    "risk_reward": 1.9,
                    "timestamp": "2026-03-12T09:35:00",
                    "change_pct": 1.5,
                    "consensus_count": 1,
                    "regime": "neutral",
                },
                {
                    "id": "sig-d",
                    "code": "603588",
                    "name": "高能环境",
                    "strategy": "趋势跟踪选股",
                    "score": 0.89,
                    "price": 7.52,
                    "buy_price": 7.52,
                    "stop_loss": 7.16,
                    "target_price": 8.1,
                    "risk_reward": 1.7,
                    "timestamp": "2026-03-12T10:30:00",
                    "change_pct": 0.6,
                    "consensus_count": 1,
                    "regime": "neutral",
                },
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_strong_move_candidate_from_record",
            lambda record, strategy_map=None: None,
        )

        def fake_composite_pick(signal, strategy_map, strong_move_map, theme_by_code):
            code = signal.get("code")
            score_map = {
                "600111": 78.0,
                "600618": 70.0,
                "002531": 68.0,
                "603588": 74.0,
            }
            return api_server.CompositePick(
                id=f"cp-{code}",
                signal_id=str(signal.get("id", "")),
                code=str(code),
                name=str(signal.get("name", "")),
                strategy=str(signal.get("strategy", "")),
                theme_sector=None,
                theme_intensity=None,
                setup_label="综合进攻候选" if score_map[code] >= 74 else "备选观察",
                conviction="high" if score_map[code] >= 74 else "medium",
                composite_score=score_map[code],
                strategy_score=72.0,
                capital_score=66.0,
                theme_score=58.0,
                event_score=52.0,
                event_bias="中性",
                event_summary=None,
                event_matched_sector=None,
                execution_score=64.0,
                first_position_pct=10 if score_map[code] >= 74 else 8,
                price=float(signal.get("price", 0)),
                buy_price=float(signal.get("buy_price", 0)),
                stop_loss=float(signal.get("stop_loss", 0)),
                target_price=float(signal.get("target_price", 0)),
                risk_reward=float(signal.get("risk_reward", 0)),
                timestamp=str(signal.get("timestamp", "")),
                thesis="test",
                action="test",
                reasons=["test"],
            )

        monkeypatch.setattr(api_server, "_build_composite_pick_from_record", fake_composite_pick)
        monkeypatch.setattr(
            api_server,
            "_load_signal_verification_records",
            lambda days=20: {
                "2026-03-13|趋势跟踪选股|600111": {
                    "verify": {"t1": {"return_pct": 3.0}, "t3": {"return_pct": 6.0}}
                },
                "2026-03-13|隔夜选股|600618": {
                    "verify": {"t1": {"return_pct": 1.0}, "t3": {"return_pct": 2.0}}
                },
                "2026-03-12|趋势跟踪选股|603588": {
                    "verify": {"t1": {"return_pct": -1.0}, "t3": {"return_pct": 0.5}}
                },
                "2026-03-12|隔夜选股|002531": {
                    "verify": {"t1": {"return_pct": 2.2}, "t3": {"return_pct": 1.1}}
                },
            },
        )

        snapshot = api_server._build_composite_compare(days=2)

        assert snapshot.composite.sample_days == 2
        assert snapshot.baseline.sample_days == 2
        assert snapshot.composite.avg_t3_return_pct == 3.25
        assert snapshot.baseline.avg_t3_return_pct == 1.55
        assert snapshot.advantage[0].startswith("T+3 平均收益综合榜领先")
        assert snapshot.readiness.status == "shadow"
        assert snapshot.readiness.label == "继续影子"
        assert snapshot.days[0].trade_date == "2026-03-13"
        assert snapshot.days[0].composite_code == "600111"
        assert snapshot.days[0].baseline_code == "600618"


class TestIndustryCapitalMap:
    def test_build_industry_capital_map_blends_policy_theme_and_capital(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_build_policy_watch",
            lambda limit=6: [
                api_server.PolicyWatchItem(
                    id="policy-watch-china-us-rivalry",
                    direction="中美博弈与反制链",
                    policy_bucket="全球博弈",
                    focus_sector="半导体",
                    stage_label="催化升温",
                    participation_label="主线观察",
                    industry_phase="博弈升温期",
                    direction_score=68.0,
                    policy_score=71.0,
                    trend_score=62.0,
                    attention_score=65.0,
                    capital_preference_score=58.0,
                    linked_signal_id="sig-1",
                    linked_code="688256",
                    linked_name="寒武纪",
                    linked_setup_label="主线观察",
                    summary="测试",
                    action="测试",
                    risk_note="注意兑现节奏",
                    phase_summary="需求侧来自替代需求，供给侧来自国产产能。",
                    demand_drivers=["自主可控采购", "政企替代"],
                    supply_drivers=["国产产能", "平替成熟"],
                    upstream=["设备", "材料"],
                    midstream=["芯片设计", "制造"],
                    downstream=["服务器", "终端"],
                    milestones=["政策提法", "预算落地", "订单兑现"],
                    transmission_paths=["制裁 -> 平替需求", "反制 -> 再定价"],
                    drivers=["政策分 71", "趋势分 62"],
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_theme_stage_engine",
            lambda limit=6: [
                api_server.ThemeStageItem(
                    id="theme-stage-semiconductor",
                    sector="半导体",
                    theme_type="国产替代",
                    intensity="持续升温",
                    stage_label="中期扩散",
                    participation_label="中期波段",
                    direction_score=66.0,
                    policy_event_score=64.0,
                    trend_score=61.0,
                    attention_score=67.0,
                    capital_preference_score=63.0,
                    stage_score=62.0,
                    linked_signal_id="sig-1",
                    linked_code="688256",
                    linked_name="寒武纪",
                    linked_setup_label="中期波段",
                    summary="测试",
                    action="测试",
                    risk_note="测试",
                    drivers=["测试"],
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_composite_picks",
            lambda days=1, limit=16: [
                api_server.CompositePick(
                    id="cp-688256",
                    signal_id="sig-1",
                    code="688256",
                    name="寒武纪",
                    strategy="趋势跟踪选股",
                    theme_sector="半导体",
                    theme_intensity="持续升温",
                    setup_label="综合进攻候选",
                    conviction="high",
                    composite_score=76.0,
                    strategy_score=68.0,
                    capital_score=72.0,
                    theme_score=65.0,
                    event_score=61.0,
                    event_bias="偏多",
                    event_summary="制裁升级带来国产替代",
                    event_matched_sector="半导体",
                    source_category="theme_seed",
                    source_label="主线种子",
                    horizon_label="中期波段",
                    execution_score=69.0,
                    first_position_pct=8,
                    price=612.0,
                    buy_price=612.0,
                    stop_loss=580.0,
                    target_price=680.0,
                    risk_reward=2.1,
                    timestamp="2026-03-14T10:00:00",
                    thesis="测试",
                    action="测试",
                    reasons=["测试"],
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_load_policy_official_watch",
            lambda: {
                "china-us-rivalry": {
                    "official_sources": ["国务院", "商务部"],
                    "official_watchpoints": ["出口管制清单", "反制与豁免"],
                    "business_checklist": ["梳理供应链备份", "确认客户替代验证周期"],
                    "capital_checklist": ["确认前排承接", "等待订单验证"],
                }
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_policy_execution_timeline",
            lambda: {
                "china-us-rivalry": {
                    "official_documents": ["商务部反制口径", "出口管制信息"],
                    "timeline_checkpoints": ["制裁升级", "反制落地", "采购替代"],
                    "cooperation_targets": ["国产替代方案商", "政企客户"],
                    "cooperation_modes": ["平替验证", "联合采购"],
                }
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_policy_official_cards",
            lambda: {
                "china-us-rivalry": {
                    "official_cards": [
                        {
                            "title": "制裁反制与产业安全",
                            "source": "国务院 / 商务部",
                            "excerpt": "先看产业安全链条是否从提法走到采购替代。",
                            "why_it_matters": "只有进入替代验证，方向才有中期价值。",
                            "next_watch": "继续盯采购替代和订单验证。",
                        }
                    ]
                }
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_policy_official_ingest",
            lambda: {
                "china-us-rivalry": {
                    "official_source_entries": [
                        {
                            "title": "制裁反制与产业安全",
                            "issuer": "国务院 / 商务部 / 工信部",
                            "published_at": "2026-03-05",
                            "source_type": "政府工作报告",
                            "reference": "2026 政府工作报告",
                            "reference_url": "https://www.gov.cn/example",
                            "excerpt": "测试摘要",
                            "key_points": ["先看产业安全链条", "再看采购替代兑现"],
                            "watch_tags": ["制裁清单", "采购替代"],
                        }
                    ]
                }
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_industry_capital_company_map",
            lambda: {
                "china-us-rivalry": {
                    "company_watchlist": [
                        {
                            "code": "688981",
                            "name": "中芯国际",
                            "role": "先进制造与替代主轴",
                            "chain_position": "中游",
                            "tracking_reason": "观察替代兑现。",
                            "action": "看资本开支和良率。",
                        }
                    ],
                    "research_targets": ["国产替代方案商", "政企采购部门"],
                    "validation_signals": ["采购替代加速", "订单改善"],
                }
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_industry_capital_research_log",
            lambda: {
                "items": [
                    {
                        "id": "icr_1",
                        "direction_id": "industry-capital-policy-watch-china-us-rivalry",
                        "direction": "中美博弈与反制链",
                        "title": "客户验证进入第二轮",
                        "note": "客户替代测试已进入第二轮，开始确认小批量导入。",
                        "source": "客户反馈",
                        "status": "已验证",
                        "company_code": "688981",
                        "company_name": "中芯国际",
                        "created_at": "2026-03-14T10:00:00",
                        "updated_at": "2026-03-14T10:00:00",
                        "author": "admin",
                    }
                ],
                "last_update": "2026-03-14T10:00:00",
            },
        )

        items = api_server._build_industry_capital_map(limit=1)

        assert len(items) == 1
        assert items[0].direction == "中美博弈与反制链"
        assert items[0].focus_sector == "半导体"
        assert items[0].linked_code == "688256"
        assert items[0].participation_label == "中期波段"
        assert items[0].strategic_label in {"中线布局", "早期卡位"}
        assert any("交易焦点 688256 寒武纪" == item for item in items[0].opportunities)
        assert items[0].official_sources == ["国务院", "商务部"]
        assert items[0].official_watchpoints[0] == "出口管制清单"
        assert items[0].business_checklist[0] == "梳理供应链备份"
        assert items[0].capital_checklist[0] == "确认前排承接"
        assert items[0].official_cards[0].title == "制裁反制与产业安全"
        assert items[0].official_source_entries[0].title == "制裁反制与产业安全"
        assert items[0].official_source_entries[0].published_at == "2026-03-05"
        assert items[0].official_source_entries[0].reference_url == "https://www.gov.cn/example"
        assert items[0].official_documents[0] == "商务部反制口径"
        assert items[0].timeline_checkpoints[0] == "制裁升级"
        assert items[0].current_timeline_stage == "调研验证"
        assert items[0].latest_catalyst_title == "客户验证进入第二轮"
        assert items[0].timeline_events[0].lane == "research"
        assert items[0].timeline_events[0].title == "客户验证进入第二轮"
        assert any(event.id.endswith("official-ingest-1") for event in items[0].timeline_events)
        assert items[0].cooperation_targets[0] == "国产替代方案商"
        assert items[0].cooperation_modes[0] == "平替验证"
        assert items[0].company_watchlist[0].code == "688981"
        assert items[0].company_watchlist[0].priority_label in {"优先深跟", "优先跟踪", "保持观察"}
        assert items[0].company_watchlist[0].tracking_score >= 50
        assert items[0].priority_score >= items[0].strategic_score
        assert items[0].official_freshness_score >= 58
        assert items[0].official_freshness_label in {"近10天官方催化", "近30天官方催化", "近季度官方口径"}
        assert items[0].drivers[0].startswith("优先级 ")
        assert items[0].research_signal_label == "验证增强"
        assert "已验证回写" in items[0].research_summary
        assert items[0].company_watchlist[0].research_signal_label == "验证增强"
        assert items[0].company_watchlist[0].recent_research_note is not None
        assert items[0].company_watchlist[0].timeline_alignment
        assert items[0].company_watchlist[0].catalyst_hint == "客户验证进入第二轮"
        assert items[0].research_targets[0] == "国产替代方案商"
        assert items[0].validation_signals[0] == "采购替代加速"

    def test_industry_capital_latest_catalyst_falls_back_to_official_card(self):
        import api_server

        policy = api_server.PolicyWatchItem(
            id="policy-watch-ai-digital",
            direction="AI与数字基础设施",
            policy_bucket="数字中国",
            focus_sector="算力",
            stage_label="催化升温",
            participation_label="主线观察",
            industry_phase="导入期",
            direction_score=61.0,
            policy_score=66.0,
            trend_score=59.0,
            attention_score=60.0,
            capital_preference_score=55.0,
            linked_signal_id=None,
            linked_code=None,
            linked_name=None,
            linked_setup_label=None,
            summary="测试方向",
            action="测试动作",
            risk_note="测试风险",
            phase_summary="测试阶段",
            demand_drivers=[],
            supply_drivers=[],
            upstream=[],
            midstream=[],
            downstream=[],
            milestones=[],
            transmission_paths=[],
            drivers=[],
        )

        events = api_server._build_industry_capital_timeline_events(
            direction_id="industry-capital-policy-watch-ai-digital",
            policy=policy,
            official_cards=[
                {
                    "title": "数字中国与算力基础设施",
                    "source": "国务院 / 国家数据局",
                    "excerpt": "测试摘要",
                    "why_it_matters": "测试重要性",
                    "next_watch": "测试下一步",
                }
            ],
            official_documents=["政府工作报告"],
            timeline_checkpoints=["政策定调", "项目落地"],
            research_items=[],
        )

        title, summary, stage = api_server._industry_capital_latest_catalyst(events, policy)

        assert title == "数字中国与算力基础设施"
        assert summary == "测试重要性"
        assert stage == "官方定调"

    def test_industry_capital_priority_score_rewards_research_and_midterm_setup(self):
        import api_server

        strong = api_server._industry_capital_priority_score(66.0, 68.0, "中期波段", "中期扩散")
        weak = api_server._industry_capital_priority_score(66.0, 50.0, "先观察", "承压观察")

        assert strong > weak
        assert strong > 66.0
        assert weak < 66.0


class TestIndustryCapitalResearchLog:
    def test_list_industry_capital_research_items_filters_by_direction(self, monkeypatch, tmp_path):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_INDUSTRY_CAPITAL_RESEARCH_LOG",
            str(tmp_path / "industry_capital_research_log.json"),
        )
        api_server._save_industry_capital_research_log(
            {
                "items": [
                    {
                        "id": "icr_1",
                        "direction_id": "industry-capital-policy-watch-china-us-rivalry",
                        "direction": "中美博弈与反制链",
                        "title": "客户替代在推进",
                        "note": "客户已进入导入测试阶段。",
                        "source": "客户反馈",
                        "status": "待验证",
                        "created_at": "2026-03-14T10:00:00",
                        "updated_at": "2026-03-14T10:00:00",
                        "author": "admin",
                    },
                    {
                        "id": "icr_2",
                        "direction_id": "industry-capital-policy-watch-ai-digital",
                        "direction": "AI与数字基础设施",
                        "title": "另一条方向",
                        "note": "无关记录",
                        "source": "产业调研",
                        "status": "待验证",
                        "created_at": "2026-03-14T09:00:00",
                        "updated_at": "2026-03-14T09:00:00",
                        "author": "admin",
                    },
                ]
            }
        )

        items = api_server._list_industry_capital_research_items(
            "industry-capital-policy-watch-china-us-rivalry"
        )

        assert len(items) == 1
        assert items[0].title == "客户替代在推进"
        assert items[0].source == "客户反馈"

    def test_submit_industry_capital_research_writes_log(self, monkeypatch, tmp_path):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_INDUSTRY_CAPITAL_RESEARCH_LOG",
            str(tmp_path / "industry_capital_research_log.json"),
        )
        dispatch_calls = []
        monkeypatch.setattr(
            api_server,
            "_dispatch_industry_research_push",
            lambda user, before, after, latest_item: dispatch_calls.append(
                (before.direction, after.direction, latest_item.title)
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_industry_capital_detail",
            lambda direction_id: api_server.IndustryCapitalDirection(
                id=direction_id,
                direction="中美博弈与反制链",
                policy_bucket="全球博弈",
                focus_sector="半导体",
                strategic_label="逆风跟踪",
                industry_phase="博弈升温期",
                participation_label="先观察",
                business_horizon="3-6个月跟踪",
                capital_horizon="等待确认",
                strategic_score=44.5,
                policy_score=36.7,
                demand_score=50.1,
                supply_score=50.9,
                capital_preference_score=44.8,
                linked_signal_id=None,
                linked_code=None,
                linked_name=None,
                linked_setup_label=None,
                summary="测试方向",
                business_action="测试事业动作",
                capital_action="测试资本动作",
                risk_note="测试风险",
                upstream=[],
                midstream=[],
                downstream=[],
                demand_drivers=[],
                supply_drivers=[],
                milestones=[],
                transmission_paths=[],
                opportunities=[],
                official_sources=[],
                official_watchpoints=[],
                business_checklist=[],
                capital_checklist=[],
                official_cards=[],
                official_documents=[],
                timeline_checkpoints=[],
                cooperation_targets=[],
                cooperation_modes=[],
                company_watchlist=[],
                research_targets=[],
                validation_signals=[],
                drivers=[],
            ),
        )

        result = api_server._submit_industry_capital_research(
            "industry-capital-policy-watch-china-us-rivalry",
            api_server.IndustryCapitalResearchSubmissionRequest(
                title="验证国产替代节奏",
                note="客户反馈替代测试已进入第二轮。",
                source="客户反馈",
                status="待验证",
                company_code="688981",
                company_name="中芯国际",
            ),
            api_server.AppUser(
                username="admin",
                display_name="Alpha Operator",
                role="operator",
                token="token",
            ),
        )

        assert result.success is True
        assert result.total_items == 1
        assert result.item.direction == "中美博弈与反制链"
        assert result.item.company_code == "688981"
        assert dispatch_calls == [("中美博弈与反制链", "中美博弈与反制链", "验证国产替代节奏")]
        items = api_server._list_industry_capital_research_items(
            "industry-capital-policy-watch-china-us-rivalry"
        )
        assert len(items) == 1
        assert items[0].note == "客户反馈替代测试已进入第二轮。"

    def test_submit_industry_capital_research_appends_change_messages(self, monkeypatch, tmp_path):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_INDUSTRY_CAPITAL_RESEARCH_LOG",
            str(tmp_path / "industry_capital_research_log.json"),
        )
        monkeypatch.setattr(
            api_server,
            "_APP_MESSAGE_CENTER",
            str(tmp_path / "app_message_center.json"),
        )

        before_direction = api_server.IndustryCapitalDirection(
            id="industry-capital-policy-watch-china-us-rivalry",
            direction="中美博弈与反制链",
            policy_bucket="全球博弈",
            focus_sector="半导体",
            strategic_label="逆风跟踪",
            industry_phase="博弈升温期",
            participation_label="先观察",
            business_horizon="3-6个月跟踪",
            capital_horizon="等待确认",
            priority_score=44.0,
            strategic_score=44.0,
            policy_score=40.0,
            demand_score=50.0,
            supply_score=49.0,
            capital_preference_score=43.0,
            research_signal_score=50.0,
            research_signal_label="暂无回写",
            linked_signal_id=None,
            linked_code=None,
            linked_name=None,
            linked_setup_label=None,
            summary="测试方向",
            business_action="测试事业动作",
            capital_action="测试资本动作",
            risk_note="测试风险",
            research_summary="当前还没有调研回写，先补客户、供应链和政策验证。",
            research_next_action="先补第一次方向调研记录。",
            upstream=[],
            midstream=[],
            downstream=[],
            demand_drivers=[],
            supply_drivers=[],
            milestones=[],
            transmission_paths=[],
            opportunities=[],
            official_sources=[],
            official_watchpoints=[],
            business_checklist=[],
            capital_checklist=[],
            official_cards=[],
            official_documents=[],
            timeline_checkpoints=[],
            cooperation_targets=[],
            cooperation_modes=[],
            company_watchlist=[
                api_server.IndustryCapitalCompanyItem(
                    code="688981",
                    name="中芯国际",
                    role="制造",
                    chain_position="中游",
                    tracking_reason="测试",
                    action="测试",
                    tracking_score=52.0,
                    priority_label="保持观察",
                    market_alignment="待确认",
                    next_check="继续看",
                    research_signal_score=50.0,
                    research_signal_label="暂无回写",
                )
            ],
            research_targets=[],
            validation_signals=[],
            drivers=[],
        )
        after_direction = api_server.IndustryCapitalDirection(
            **{
                **before_direction.model_dump(),
                "priority_score": 63.5,
                "participation_label": "中期波段",
                "capital_horizon": "1-3个月",
                "research_signal_score": 67.0,
                "research_signal_label": "验证增强",
                "research_summary": "最近 1 条已验证回写，方向开始从判断走向兑现。",
                "research_next_action": "优先复核已验证对象。",
                "current_timeline_stage": "调研验证",
                "latest_catalyst_title": "客户验证进入第二轮",
                "latest_catalyst_summary": "客户替代测试已进入第二轮，方向开始往兑现推进。",
                "company_watchlist": [
                    api_server.IndustryCapitalCompanyItem(
                        code="688981",
                        name="中芯国际",
                        role="制造",
                        chain_position="中游",
                        tracking_reason="测试",
                        action="测试",
                        tracking_score=66.0,
                        priority_label="优先跟踪",
                        market_alignment="主线共振",
                        next_check="跟订单",
                        research_signal_score=66.0,
                        research_signal_label="验证增强",
                        recent_research_note="客户反馈 / 已验证：替代测试进入第二轮。",
                    )
                ],
            }
        )

        directions = iter([before_direction, after_direction])
        monkeypatch.setattr(api_server, "_build_industry_capital_detail", lambda direction_id: next(directions))

        result = api_server._submit_industry_capital_research(
            "industry-capital-policy-watch-china-us-rivalry",
            api_server.IndustryCapitalResearchSubmissionRequest(
                title="验证国产替代节奏",
                note="客户反馈替代测试已进入第二轮。",
                source="客户反馈",
                status="已验证",
                company_code="688981",
                company_name="中芯国际",
            ),
            api_server.AppUser(
                username="admin",
                display_name="Alpha Operator",
                role="operator",
                token="token",
            ),
        )

        assert result.success is True
        center = api_server._load_app_message_center()
        titles = [item["title"] for item in center["items"]]
        assert "中美博弈与反制链 验证增强" in titles
        assert any("优先级升至重点推进" in title for title in titles)
        assert any("阶段切换到 调研验证" in title for title in titles)
        assert "中美博弈与反制链 最新催化更新" in titles
        assert any("中芯国际 验证增强" in title for title in titles)

    def test_build_industry_research_push_copy_includes_changed_state(self):
        import api_server

        before = api_server.IndustryCapitalDirection(
            id="industry-capital-policy-watch-china-us-rivalry",
            direction="中美博弈与反制链",
            policy_bucket="全球博弈",
            focus_sector="半导体",
            strategic_label="逆风跟踪",
            industry_phase="博弈升温期",
            participation_label="先观察",
            business_horizon="3-6个月跟踪",
            capital_horizon="等待确认",
            priority_score=44.0,
            strategic_score=44.0,
            policy_score=40.0,
            demand_score=50.0,
            supply_score=49.0,
            capital_preference_score=43.0,
            research_signal_score=50.0,
            research_signal_label="暂无回写",
            linked_signal_id=None,
            linked_code=None,
            linked_name=None,
            linked_setup_label=None,
            summary="测试方向",
            business_action="测试事业动作",
            capital_action="测试资本动作",
            risk_note="测试风险",
            research_summary="当前还没有调研回写，先补客户、供应链和政策验证。",
            research_next_action="先补第一次方向调研记录。",
            upstream=[],
            midstream=[],
            downstream=[],
            demand_drivers=[],
            supply_drivers=[],
            milestones=[],
            transmission_paths=[],
            opportunities=[],
            official_sources=[],
            official_watchpoints=[],
            business_checklist=[],
            capital_checklist=[],
            official_cards=[],
            official_documents=[],
            timeline_checkpoints=[],
            cooperation_targets=[],
            cooperation_modes=[],
            company_watchlist=[],
            research_targets=[],
            validation_signals=[],
            drivers=[],
        )
        after = api_server.IndustryCapitalDirection(
            **{
                **before.model_dump(),
                "priority_score": 63.5,
                "research_signal_score": 66.0,
                "research_signal_label": "验证增强",
                "capital_horizon": "1-3个月",
                "current_timeline_stage": "调研验证",
                "latest_catalyst_title": "客户验证进入第二轮",
                "latest_catalyst_summary": "客户替代进入第二轮验证。",
                "research_next_action": "优先复核已验证对象。",
            }
        )
        latest = api_server.IndustryCapitalResearchItem(
            id="icr_1",
            direction_id=before.id,
            direction=before.direction,
            title="验证国产替代节奏",
            note="客户反馈替代测试已进入第二轮。",
            source="客户反馈",
            status="已验证",
            company_code="688981",
            company_name="中芯国际",
            created_at="2026-03-15T11:00:00",
            updated_at="2026-03-15T11:00:00",
            author="admin",
        )

        title, body = api_server._build_industry_research_push_copy(before, after, latest)

        assert title == "中美博弈与反制链 验证增强"
        assert "调研信号 暂无回写->验证增强" in body
        assert "优先级 44.0->63.5" in body
        assert "阶段 继续观察->调研验证" in body
        assert "最新催化 客户验证进入第二轮" in body
        assert "公司 688981 中芯国际" in body

    def test_build_industry_research_push_status_exposes_latest_direction_context(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_load_push_registry", lambda: {"devices": []})
        monkeypatch.setattr(
            api_server,
            "_load_push_state",
            lambda: {
                "takeover_auto_enabled": True,
                "last_industry_research_sent_at": None,
                "last_industry_research_sent_status": None,
            },
        )
        monkeypatch.setattr(
            api_server,
            "_build_app_messages",
            lambda limit=24: [
                api_server.AppMessage(
                    id="msg-1",
                    title="中美博弈与反制链 阶段切换到 调研验证",
                    body="测试",
                    preview="测试预览",
                    level="info",
                    channel="system_update",
                    created_at="2026-03-15T12:00:00",
                    route="/industry-capital/industry-capital-policy-watch-china-us-rivalry",
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_industry_capital_map",
            lambda limit=1: [
                api_server.IndustryCapitalDirection(
                    id="industry-capital-policy-watch-china-us-rivalry",
                    direction="中美博弈与反制链",
                    policy_bucket="全球博弈",
                    focus_sector="半导体",
                    strategic_label="逆风跟踪",
                    industry_phase="博弈升温期",
                    participation_label="先观察",
                    business_horizon="3-6个月跟踪",
                    capital_horizon="等待确认",
                    priority_score=63.5,
                    strategic_score=44.0,
                    policy_score=40.0,
                    demand_score=50.0,
                    supply_score=49.0,
                    capital_preference_score=43.0,
                    research_signal_score=66.0,
                    research_signal_label="验证增强",
                    linked_signal_id=None,
                    linked_code=None,
                    linked_name=None,
                    linked_setup_label=None,
                    summary="测试方向",
                    business_action="测试事业动作",
                    capital_action="测试资本动作",
                    risk_note="测试风险",
                    research_summary="测试调研摘要",
                    research_next_action="测试下一步",
                    upstream=[],
                    midstream=[],
                    downstream=[],
                    demand_drivers=[],
                    supply_drivers=[],
                    milestones=[],
                    transmission_paths=[],
                    opportunities=[],
                    official_sources=[],
                    official_watchpoints=[],
                    business_checklist=[],
                    capital_checklist=[],
                    official_cards=[],
                    official_documents=[],
                    timeline_checkpoints=[],
                    current_timeline_stage="调研验证",
                    latest_catalyst_title="客户验证进入第二轮",
                    latest_catalyst_summary="客户验证进入第二轮。",
                    timeline_events=[],
                    cooperation_targets=[],
                    cooperation_modes=[],
                    company_watchlist=[],
                    research_targets=[],
                    validation_signals=[],
                    drivers=[],
                )
            ],
        )

        status = api_server._build_industry_research_push_status(
            api_server.AppUser(
                username="admin",
                display_name="Alpha Operator",
                role="operator",
                token="token",
            )
        )

        assert status.latest_direction == "中美博弈与反制链"
        assert status.latest_timeline_stage == "调研验证"
        assert status.latest_catalyst_title == "客户验证进入第二轮"


class TestWorldStateSnapshot:
    def test_build_world_state_snapshot_surfaces_market_phase(self, monkeypatch):
        import api_server
        import smart_trader

        monkeypatch.setattr(api_server, "_cached_runtime_value", lambda *args, **kwargs: kwargs["builder"]())
        monkeypatch.setattr(
            smart_trader,
            "detect_market_regime",
            lambda: {
                "regime": "weak",
                "score": 0.42,
                "should_trade": True,
                "market_phase": "weak_chop",
                "market_phase_label": "弱势拉扯",
                "style_bias": "轻仓短拿",
                "horizon_hint": "尾盘短线和竞价修复更适合按 T1 跟踪。",
                "limit_up_mode": "只做板前确认，不追板",
                "limit_up_allowed": True,
                "phase_summary": "指数并不强，但活口会集中在少数方向。",
                "signals": {
                    "s1_ma_trend": 0.41,
                    "s2_momentum": 0.36,
                    "s3_volatility": 0.52,
                    "s4_advance_decline": 0.34,
                    "s5_limit_ratio": 0.55,
                    "s6_northbound": 0.38,
                },
            },
        )

        snapshot = api_server._build_world_state_snapshot()

        assert snapshot.market_phase == "weak_chop"
        assert snapshot.market_phase_label == "弱势拉扯"
        assert snapshot.limit_up_allowed is True
        assert snapshot.drivers


class TestStrategyGovernance:
    def test_build_strategy_governance_promotes_trend_and_disables_overnight(self, monkeypatch, tmp_path):
        import json
        import api_server
        import signal_tracker

        monkeypatch.setattr(api_server, "_cached_runtime_value", lambda *args, **kwargs: kwargs["builder"]())
        strategies_path = tmp_path / "strategies.json"
        strategies_path.write_text(
            json.dumps(
                [
                    {"id": "trend", "name": "趋势跟踪选股", "enabled": True},
                    {"id": "dip_buy", "name": "低吸回调选股", "enabled": True},
                    {"id": "overnight", "name": "隔夜选股", "enabled": True},
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(api_server, "_STRATEGIES_JSON", str(strategies_path))
        monkeypatch.setattr(
            api_server,
            "_build_world_state_snapshot",
            lambda: api_server.WorldStateSnapshot(
                regime="neutral",
                regime_score=58.0,
                market_phase="rotation_up",
                market_phase_label="轮动走强",
                style_bias="轮动+趋势兼顾",
                horizon_hint="更适合按 T+2/T+3 跟踪。",
                limit_up_mode="只做板前确认",
                limit_up_allowed=True,
                should_trade=True,
                summary="测试",
                drivers=[],
            ),
        )
        monkeypatch.setattr(
            signal_tracker,
            "get_stats",
            lambda days=84: {
                "by_strategy": {
                    "趋势跟踪选股": {
                        "total": 14,
                        "t1_win_rate": 61.0,
                        "t3_win_rate": 57.0,
                        "t5_win_rate": 52.0,
                        "avg_t1": 1.2,
                        "avg_t3": 1.0,
                        "avg_t5": 0.8,
                    },
                    "低吸回调选股": {
                        "total": 8,
                        "t1_win_rate": 46.0,
                        "t3_win_rate": 50.0,
                        "t5_win_rate": 42.0,
                        "avg_t1": 0.1,
                        "avg_t3": 0.8,
                        "avg_t5": 0.3,
                    },
                    "隔夜选股": {
                        "total": 16,
                        "t1_win_rate": 25.0,
                        "t3_win_rate": 18.0,
                        "t5_win_rate": 12.0,
                        "avg_t1": -1.0,
                        "avg_t3": -2.0,
                        "avg_t5": -3.5,
                    },
                }
            },
        )
        monkeypatch.setattr(
            signal_tracker,
            "get_feedback_for_learning",
            lambda: {
                "strategy_regime_fit": {
                    "趋势跟踪选股": {"best_regime": "neutral", "worst_regime": "bear"},
                    "隔夜选股": {"best_regime": "bull", "worst_regime": "neutral"},
                },
                "signal_decay": {
                    "趋势跟踪选股": {"decay": 0.2},
                    "隔夜选股": {"decay": 2.8},
                },
            },
        )

        snapshot = api_server._build_strategy_governance()

        trend = next(item for item in snapshot.items if item.strategy_name == "趋势跟踪选股")
        overnight = next(item for item in snapshot.items if item.strategy_name == "隔夜选股")

        assert trend.state == "production"
        assert overnight.state == "disabled"
        assert snapshot.production_count >= 1
        assert snapshot.disabled_count >= 1


class TestExecutionPolicy:
    def test_build_execution_policy_surfaces_budget_and_strategy_matrix(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_cached_runtime_value", lambda *args, **kwargs: kwargs["builder"]())
        monkeypatch.setattr(
            api_server,
            "_build_world_state_snapshot",
            lambda: api_server.WorldStateSnapshot(
                regime="weak",
                regime_score=41.0,
                market_phase="weak_chop",
                market_phase_label="弱势拉扯",
                style_bias="轻仓短拿",
                horizon_hint="尾盘短线和竞价修复更适合按 T1 跟踪。",
                limit_up_mode="只做板前确认，不追板",
                limit_up_allowed=True,
                should_trade=True,
                summary="测试",
                drivers=[],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_strategy_governance",
            lambda: api_server.StrategyGovernanceSnapshot(
                regime="weak",
                market_phase="weak_chop",
                market_phase_label="弱势拉扯",
                summary="测试",
                production_count=1,
                observation_count=1,
                disabled_count=1,
                items=[
                    api_server.StrategyGovernanceItem(
                        strategy_id="auction",
                        strategy_name="集合竞价选股",
                        family="auction",
                        state="production",
                        weight_pct=48.0,
                        top_down_fit=68.0,
                        recent_fit=55.0,
                        sample_count=12,
                        holding_window_cap="T+1/T+2 观察",
                        discipline_label="竞价短拿",
                        reason="测试",
                    ),
                    api_server.StrategyGovernanceItem(
                        strategy_id="dip",
                        strategy_name="低吸回调选股",
                        family="dip",
                        state="observation",
                        weight_pct=28.0,
                        top_down_fit=57.0,
                        recent_fit=49.0,
                        sample_count=5,
                        holding_window_cap="1-3天反弹观察",
                        discipline_label="反弹兑现",
                        reason="测试",
                    ),
                    api_server.StrategyGovernanceItem(
                        strategy_id="overnight",
                        strategy_name="隔夜选股",
                        family="overnight",
                        state="disabled",
                        weight_pct=0.0,
                        top_down_fit=24.0,
                        recent_fit=18.0,
                        sample_count=18,
                        holding_window_cap="隔夜试错",
                        discipline_label="先停用",
                        reason="测试",
                    ),
                ],
            ),
        )

        snapshot = api_server._build_execution_policy()

        assert snapshot.market_phase == "weak_chop"
        assert snapshot.risk_budget_pct <= 42.0
        assert "集合竞价选股" in snapshot.allowed_strategies
        assert "隔夜选股" in snapshot.blocked_strategies
        assert snapshot.key_actions

    def test_build_execution_policy_uses_structural_components_to_tighten_budget(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_cached_runtime_value", lambda *args, **kwargs: kwargs["builder"]())
        monkeypatch.setattr(
            api_server,
            "_build_world_state_snapshot",
            lambda: api_server.WorldStateSnapshot(
                regime="neutral",
                regime_score=57.0,
                market_phase="valuation_reset",
                market_phase_label="杀估值",
                valuation_regime="折现率压制",
                capital_style="防守现金流",
                strategic_direction="自主可控",
                technology_focus="自主可控/半导体",
                geopolitics_bias="博弈升温",
                supply_chain_mode="产业链重构",
                phase_confidence=73.0,
                style_bias="先防守后轮动",
                horizon_hint="先压缩高估值，再看结构强票。",
                limit_up_mode="只做板前承接",
                limit_up_allowed=False,
                should_trade=True,
                summary="测试",
                structural_summary="测试",
                dominant_component="估值重构",
                components=[
                    api_server.WorldStateComponent(
                        key="valuation",
                        label="估值重构",
                        score=28.0,
                        bias="折现率压制",
                        summary="测试",
                        drivers=["高估值承压"],
                    ),
                    api_server.WorldStateComponent(
                        key="technology",
                        label="通用技术扩散",
                        score=76.0,
                        bias="自主可控/半导体",
                        summary="测试",
                        drivers=["国产替代"],
                    ),
                    api_server.WorldStateComponent(
                        key="chain_control",
                        label="产业链控制力",
                        score=78.0,
                        bias="产业链重构",
                        summary="测试",
                        drivers=["设备替代"],
                    ),
                    api_server.WorldStateComponent(
                        key="capital_flow",
                        label="资金风格切换",
                        score=34.0,
                        bias="防守现金流",
                        summary="测试",
                        drivers=["风险偏好收缩"],
                    ),
                    api_server.WorldStateComponent(
                        key="geopolitics",
                        label="国别博弈",
                        score=71.0,
                        bias="博弈升温",
                        summary="测试",
                        drivers=["制裁反制"],
                    ),
                ],
                drivers=[],
                checks=[
                    api_server.WorldStateCheck(
                        key="valuation_warning",
                        level="warning",
                        title="估值压制仍在",
                        message="先确认高估值和主线扩散是否能共存。",
                        suggestion="先做确认，别盲目追涨。",
                        source_keys=["news_digest", "official_ingest"],
                    )
                ],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_strategy_governance",
            lambda: api_server.StrategyGovernanceSnapshot(
                regime="neutral",
                market_phase="rotation_up",
                market_phase_label="轮动走强",
                summary="测试",
                production_count=2,
                observation_count=1,
                disabled_count=1,
                items=[
                    api_server.StrategyGovernanceItem(
                        strategy_id="trend",
                        strategy_name="趋势跟踪选股",
                        family="trend",
                        state="production",
                        weight_pct=52.0,
                        top_down_fit=70.0,
                        recent_fit=58.0,
                        sample_count=10,
                        holding_window_cap="2-5天趋势跟踪",
                        discipline_label="主线滚动",
                        reason="测试",
                    ),
                    api_server.StrategyGovernanceItem(
                        strategy_id="dip",
                        strategy_name="低吸回调选股",
                        family="dip",
                        state="production",
                        weight_pct=35.0,
                        top_down_fit=63.0,
                        recent_fit=55.0,
                        sample_count=9,
                        holding_window_cap="1-3天反弹跟踪",
                        discipline_label="回踩反弹",
                        reason="测试",
                    ),
                    api_server.StrategyGovernanceItem(
                        strategy_id="overnight",
                        strategy_name="隔夜选股",
                        family="overnight",
                        state="disabled",
                        weight_pct=0.0,
                        top_down_fit=18.0,
                        recent_fit=22.0,
                        sample_count=14,
                        holding_window_cap="隔日兑现",
                        discipline_label="暂停",
                        reason="测试",
                    ),
                ],
            ),
        )

        snapshot = api_server._build_execution_policy()

        assert snapshot.risk_budget_pct <= 28.0
        assert "产业链卡位" in snapshot.allowed_styles
        assert "隔夜选股" in snapshot.blocked_strategies
        assert any("高估值" in item for item in snapshot.key_actions)
        assert any("先确认" in item or "先处理" in item for item in snapshot.key_actions)


class TestWorldStateAndProductionGuard:
    def test_build_world_state_snapshot_exposes_structural_context(self, monkeypatch):
        import api_server
        import smart_trader

        monkeypatch.setattr(api_server, "_cached_runtime_value", lambda *args, **kwargs: kwargs["builder"]())
        monkeypatch.setattr(
            smart_trader,
            "detect_market_regime",
            lambda: {
                "regime": "neutral",
                "score": 0.67,
                "market_phase": "valuation_reset",
                "market_phase_label": "杀估值",
                "style_bias": "高股息防守",
                "horizon_hint": "先防守，再找结构性机会。",
                "limit_up_mode": "只做板前，不做板上",
                "limit_up_allowed": False,
                "should_trade": True,
                "phase_summary": "高估值资产承压。",
                "signals": {"s1_ma_trend": 0.41, "s6_northbound": 0.33},
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_policy_direction_catalog",
            lambda: [
                {
                    "id": "dir-1",
                    "direction": "AI 算力与半导体自主可控",
                    "keywords": ["人工智能", "算力", "半导体", "国产替代"],
                    "focus_sectors": ["半导体", "通信"],
                    "supply_drivers": ["国产替代", "关键设备替代"],
                }
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_load_news_digest",
            lambda: {
                "timestamp": "2026-03-30T09:00:00",
                "events": [
                    {
                        "title": "AI 算力投资继续扩张",
                        "summary": "半导体与服务器继续扩张。",
                        "impact_direction": "bullish",
                        "impact_magnitude": 2.2,
                        "confidence": 0.8,
                        "urgency": "urgent",
                        "category": "tech",
                        "affected_sectors": ["半导体", "通信"],
                        "timestamp": "2026-03-30 08:30:00",
                    },
                    {
                        "title": "中美博弈加剧",
                        "summary": "国产替代链加速。",
                        "impact_direction": "bullish",
                        "impact_magnitude": 1.8,
                        "confidence": 0.7,
                        "urgency": "normal",
                        "category": "trade",
                        "affected_sectors": ["半导体"],
                        "timestamp": "2026-03-30 08:45:00",
                    },
                ],
                "heatmap": {
                    "sentiment": -0.12,
                    "sectors": {"半导体": 2.4, "通信": 1.2},
                },
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_policy_official_watch",
            lambda: {
                "dir-1": {
                    "official_sources": ["国务院", "工信部"],
                    "official_watchpoints": ["专项支持", "订单落地"],
                }
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_policy_official_cards",
            lambda: {
                "dir-1": {
                    "official_cards": [
                        {"title": "政策提法", "source": "国务院", "excerpt": "支持", "why_it_matters": "重要", "next_watch": "跟踪"},
                    ]
                }
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_policy_official_ingest",
            lambda: {
                "dir-1": {
                    "official_source_entries": [
                        {
                            "title": "政府工作报告",
                            "issuer": "国务院",
                            "published_at": "2026-03-28",
                            "excerpt": "继续推进",
                        }
                    ]
                }
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_policy_execution_timeline",
            lambda: {
                "dir-1": {
                    "official_documents": ["政府工作报告"],
                    "timeline_checkpoints": ["政策定调", "订单落地", "业绩验证"],
                }
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_industry_capital_company_map",
            lambda: {
                "dir-1": {
                    "id": "dir-1",
                    "direction": "AI 算力与半导体自主可控",
                    "company_watchlist": [
                        {"code": "688981", "name": "中芯国际", "chain_control": 82}
                    ],
                    "research_targets": [],
                    "validation_signals": [],
                }
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_industry_capital_research_log",
            lambda: {
                "last_update": "2026-03-30T08:55:00",
                "items": [
                    {
                        "direction_id": "dir-1",
                        "status": "已验证",
                        "updated_at": "2026-03-30T08:50:00",
                    }
                ],
            },
        )

        snapshot = api_server._build_world_state_snapshot()

        assert snapshot.market_phase == "valuation_reset"
        assert snapshot.valuation_regime in {"估值压缩", "杀估值", "折现率压制"}
        assert snapshot.technology_focus == "AI/算力"
        assert snapshot.capital_style in {"防守现金流", "通用技术扩散", "产业链卡位"}
        assert snapshot.strategic_direction == "AI 算力与半导体自主可控"
        assert snapshot.structural_summary
        assert snapshot.dominant_component is not None
        assert len(snapshot.components) >= 5
        assert len(snapshot.source_statuses) >= 3
        assert snapshot.top_directions
        assert snapshot.top_directions[0].direction == "AI 算力与半导体自主可控"
        assert {item.key for item in snapshot.components} >= {
            "geopolitics",
            "technology",
            "chain_control",
            "valuation",
            "capital_flow",
        }

    def test_build_world_state_snapshot_uses_external_runtime_sources(self, monkeypatch):
        import api_server
        import smart_trader
        from datetime import datetime, timedelta

        now = datetime.now()
        recent_iso = lambda minutes=0: (now - timedelta(minutes=minutes)).isoformat(timespec="seconds")
        recent_date = lambda days=0: (now - timedelta(days=days)).date().isoformat()

        monkeypatch.setattr(api_server, "_cached_runtime_value", lambda *args, **kwargs: kwargs["builder"]())
        monkeypatch.setattr(
            smart_trader,
            "detect_market_regime",
            lambda: {
                "regime": "neutral",
                "score": 0.61,
                "market_phase": "rotation_up",
                "market_phase_label": "轮动走强",
                "style_bias": "轮动+趋势兼顾",
                "horizon_hint": "更适合按 T+2/T+3 跟踪。",
                "limit_up_mode": "只做板前确认",
                "limit_up_allowed": True,
                "should_trade": True,
                "phase_summary": "主线扩散开始增强。",
                "signals": {"s1_ma_trend": 0.58, "s6_northbound": 0.63},
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_policy_direction_catalog",
            lambda: [
                {
                    "id": "ai-digital",
                    "direction": "AI与数字基础设施",
                    "policy_bucket": "国家战略",
                    "focus_sectors": ["科技", "半导体", "通信"],
                    "keywords": ["人工智能", "算力", "芯片", "半导体", "数字中国"],
                    "demand_drivers": ["算力资本开支"],
                    "supply_drivers": ["国产替代", "服务器与光模块产能"],
                    "upstream": ["算力芯片", "IDC电力"],
                    "midstream": ["服务器", "交换机"],
                    "downstream": ["行业应用"],
                },
                {
                    "id": "energy-security",
                    "direction": "能源安全与资源重估",
                    "policy_bucket": "全球博弈",
                    "focus_sectors": ["能源", "石化"],
                    "keywords": ["油气", "能源安全", "资源"],
                    "demand_drivers": ["能源价格"],
                    "supply_drivers": ["油气供给"],
                },
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_load_news_digest",
            lambda: {
                "timestamp": "2026-03-30T09:10:00",
                "events": [
                    {
                    "title": "算力基础设施建设提速",
                        "summary": "半导体、服务器和电力底座受益。",
                        "impact_direction": "bullish",
                        "impact_magnitude": 2.4,
                        "confidence": 0.9,
                        "urgency": "urgent",
                        "category": "tech",
                        "affected_sectors": ["半导体", "通信"],
                    "timestamp": recent_iso(10).replace("T", " "),
                },
                {
                        "title": "数据基础设施专项继续推进",
                        "summary": "数字中国主线强化。",
                        "impact_direction": "bullish",
                        "impact_magnitude": 1.7,
                        "confidence": 0.8,
                        "urgency": "normal",
                        "category": "policy",
                        "affected_sectors": ["科技"],
                    "timestamp": recent_iso(30).replace("T", " "),
                },
            ],
                "heatmap": {
                    "sentiment": 0.22,
                    "sectors": {"半导体": 2.8, "通信": 1.8, "科技": 1.4},
                },
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_policy_official_watch",
            lambda: {
                "ai-digital": {
                    "official_sources": ["国务院", "国家数据局", "工信部"],
                    "official_watchpoints": ["算力建设", "行业应用示范", "预算兑现"],
                }
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_policy_official_cards",
            lambda: {
                "ai-digital": {
                    "official_cards": [
                        {"title": "数字中国", "source": "国务院", "excerpt": "继续推进", "why_it_matters": "强化主线", "next_watch": "看预算"},
                        {"title": "专项支持", "source": "工信部", "excerpt": "加速", "why_it_matters": "看订单", "next_watch": "看招标"},
                    ]
                }
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_policy_official_ingest",
            lambda: {
                "ai-digital": {
                    "official_source_entries": [
                        {"title": "报告", "issuer": "国务院", "published_at": "2026-03-29", "excerpt": "支持"},
                        {"title": "专项", "issuer": "工信部", "published_at": recent_date(1), "excerpt": "支持"},
                    ]
                }
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_policy_execution_timeline",
            lambda: {
                "ai-digital": {
                    "official_documents": ["政府工作报告", "专项支持"],
                    "timeline_checkpoints": ["政策定调", "预算落地", "招标", "交付"],
                }
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_industry_capital_company_map",
            lambda: {
                "ai-digital": {
                    "company_watchlist": [
                        {"code": "688981", "name": "中芯国际", "role": "核心制程", "chain_position": "上游"},
                        {"code": "603019", "name": "中科曙光", "role": "算力平台", "chain_position": "中游"},
                    ]
                }
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_industry_capital_research_log",
            lambda: {
                "last_update": "2026-03-30T09:05:00",
                "items": [
                    {"direction_id": "ai-digital", "status": "验证增强", "updated_at": "2026-03-30T09:01:00"},
                    {"direction_id": "ai-digital", "status": "已验证", "updated_at": "2026-03-30T08:58:00"},
                ],
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_world_official_fulltext",
            lambda: {
                "updated_at": "2026-03-30T09:06:00",
                "remote_url": "https://example.com/official.json",
                "fetch_mode": "remote_json",
                "remote_configured": True,
                "degraded_to_derived": False,
                "origin_mode": "remote_live",
                "documents": [
                    {
                        "title": "数字基础设施专项文件",
                        "source": "国务院",
                        "excerpt": "继续推进算力与数字基础设施。",
                        "affected_directions": ["AI与数字基础设施"],
                        "keywords": ["数字基础设施", "算力", "人工智能"],
                    }
                ],
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_world_shipping_ais",
            lambda: {
                "updated_at": "2026-03-30T09:07:00",
                "remote_url": "https://example.com/shipping.json",
                "fetch_mode": "remote_failed_fallback",
                "remote_configured": True,
                "degraded_to_derived": True,
                "origin_mode": "derived_fallback",
                "routes": [
                    {
                        "route": "霍尔木兹海峡",
                        "restriction_scope": "partial",
                        "estimated_flow_impact_pct": 35.0,
                        "affected_countries": ["伊朗", "沙特"],
                    }
                ],
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_world_freight_rates",
            lambda: {
                "updated_at": "2026-03-30T09:08:00",
                "fetch_mode": "derived",
                "remote_configured": False,
                "degraded_to_derived": False,
                "origin_mode": "derived",
                "lanes": [
                    {
                        "route": "中东-亚洲",
                        "rate_change_pct_1d": 4.2,
                        "insurance_premium_bp": 24.0,
                    }
                ],
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_world_commodity_terminal",
            lambda: {
                "updated_at": "2026-03-30T09:09:00",
                "remote_url": "https://example.com/commodity.json",
                "fetch_mode": "remote_json",
                "remote_configured": True,
                "degraded_to_derived": False,
                "origin_mode": "remote_live",
                "commodities": [
                    {
                        "name": "原油",
                        "change_pct_1d": 3.5,
                        "change_pct_5d": 7.8,
                        "pressure_level": "warning",
                    }
                ],
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_world_macro_rates_fx",
            lambda: {
                "updated_at": "2026-03-30T09:09:30",
                "remote_url": "https://example.com/macro.json",
                "fetch_mode": "remote_json",
                "remote_configured": True,
                "degraded_to_derived": False,
                "origin_mode": "remote_live",
                "instruments": [
                    {"key": "ca_risk_appetite", "score": 58.0},
                    {"key": "ca_us_momentum", "score": 62.0},
                    {"key": "ca_vix_level", "score": 44.0},
                    {"key": "ca_a50_premium", "score": 55.0},
                    {"key": "ca_hk_sentiment", "score": 57.0},
                ],
            },
        )
        monkeypatch.setattr(
            api_server,
            "_load_operating_profile",
            lambda: {
                "company_name": "测试经营主体",
                "primary_industries": ["AI与数字基础设施", "工业自动化"],
                "operating_mode": "增长与安全并重",
                "order_visibility_months": 4.2,
                "capacity_utilization_pct": 84.0,
                "inventory_days": 19,
                "supplier_concentration_pct": 48.0,
                "customer_concentration_pct": 42.0,
                "overseas_revenue_pct": 31.0,
                "sensitive_region_exposure_pct": 26.0,
                "cash_buffer_months": 5.5,
                "capex_flexibility": "低弹性",
                "inventory_strategy": "安全库存优先",
                "key_inputs": ["高端材料", "算力设备"],
                "key_routes": ["中东能源航线"],
                "strategic_projects": ["算力基础设施"],
                "summary": "测试经营画像摘要",
                "updated_at": "2026-03-30T09:06:00",
            },
        )

        snapshot = api_server._build_world_state_snapshot()

        assert snapshot.strategic_direction == "AI与数字基础设施"
        assert snapshot.technology_focus == "AI/算力"
        assert snapshot.capital_style in {"通用技术扩散", "产业链卡位"}
        assert any(item.key == "technology" and item.score >= 70 for item in snapshot.components)
        assert any(source.key == "official_ingest" and source.freshness_score >= 70 for source in snapshot.source_statuses)
        assert any(source.key == "official_ingest" and source.authority_score >= 80 for source in snapshot.source_statuses)
        assert any(source.key == "execution_timeline" and source.signal_count >= 0 for source in snapshot.source_statuses)
        assert any(source.key == "industry_research" and source.reliability_score >= 60 for source in snapshot.source_statuses)
        assert any(source.key == "official_ingest" and source.required for source in snapshot.source_statuses)
        assert any(source.key == "official_ingest" and source.data_quality_score >= 60 for source in snapshot.source_statuses)
        assert any(source.key == "official_fulltext" and source.external for source in snapshot.source_statuses)
        assert any(source.key == "shipping_ais" and source.fetch_mode == "remote_or_derived" for source in snapshot.source_statuses)
        assert any(source.key == "official_fulltext" and source.remote_configured and source.origin_mode == "remote_live" for source in snapshot.source_statuses)
        assert any(source.key == "shipping_ais" and source.degraded_to_derived and source.origin_mode == "derived_fallback" for source in snapshot.source_statuses)
        assert any(source.key == "freight_rates" and not source.remote_configured and source.origin_mode == "derived" for source in snapshot.source_statuses)
        assert any(source.key == "commodity_terminal" and source.required for source in snapshot.source_statuses)
        assert any(source.key == "macro_rates_fx" and source.data_quality_score >= 70 for source in snapshot.source_statuses)
        assert snapshot.top_directions[0].official_score >= 60
        assert snapshot.top_directions[0].research_score >= 60
        assert snapshot.top_directions[0].hard_source_score >= 55
        assert snapshot.top_directions[0].technology_breakthrough_score >= 60
        assert snapshot.technology_breakthrough_score >= 60
        assert snapshot.technology_breakthrough_summary
        assert snapshot.cross_asset_signals
        assert snapshot.regional_pressures
        assert snapshot.event_cascades
        assert snapshot.refresh_plan is not None
        assert snapshot.refresh_plan.news_interval_minutes > 0
        assert snapshot.refresh_plan.hard_source_interval_minutes > 0
        assert snapshot.refresh_plan.policy_interval_minutes > 0
        assert snapshot.actions
        assert snapshot.operating_actions
        assert snapshot.operating_profile is not None
        assert snapshot.operating_profile.company_name == "测试经营主体"
        assert snapshot.operating_profile.order_visibility_months == 4.2
        assert snapshot.operating_profile.completeness_score >= 80
        assert snapshot.operating_profile.completeness_label in {"完整", "可用"}
        assert snapshot.operating_profile.freshness_label in {"最新", "可用"}
        assert snapshot.operating_profile.missing_fields == []
        assert snapshot.operating_profile.recommended_actions
        assert snapshot.checks

    def test_app_operating_profile_routes_round_trip(self, monkeypatch):
        import api_server

        saved_payload = {}
        current = {
            "company_name": "测试经营主体",
            "primary_industries": ["AI与数字基础设施"],
            "operating_mode": "增长与安全并重",
            "order_visibility_months": 3.0,
            "capacity_utilization_pct": 76.0,
            "inventory_days": 28,
            "supplier_concentration_pct": 34.0,
            "customer_concentration_pct": 30.0,
            "overseas_revenue_pct": 18.0,
            "sensitive_region_exposure_pct": 10.0,
            "cash_buffer_months": 9.0,
            "capex_flexibility": "中等弹性",
            "inventory_strategy": "关键物料安全库存",
            "key_inputs": ["算力设备"],
            "key_routes": ["亚欧干线"],
            "strategic_projects": ["算力基础设施"],
            "summary": "测试摘要",
            "updated_at": "2026-03-31T16:10:00+08:00",
        }

        monkeypatch.setattr(api_server, "_load_operating_profile", lambda: api_server._normalize_operating_profile(dict(current)))

        def fake_save(payload):
            saved_payload.update(payload)
            return api_server._normalize_operating_profile(dict(payload))

        monkeypatch.setattr(api_server, "_save_operating_profile", fake_save)

        user = api_server.AppUser(username="pilot", display_name="Pilot", role="pilot")
        got = api_server.get_app_operating_profile(user=user)
        updated = api_server.update_app_operating_profile(
            api_server.WorldOperatingProfileUpdateRequest(
                order_visibility_months=5.0,
                inventory_days=21,
                summary="更新后的经营画像",
            ),
            user=user,
        )

        assert got.company_name == "测试经营主体"
        assert got.completeness_score >= 80
        assert got.freshness_label in {"最新", "可用"}
        assert got.recommended_actions
        assert saved_payload["order_visibility_months"] == 5.0
        assert saved_payload["inventory_days"] == 21
        assert updated.summary == "更新后的经营画像"
        assert updated.completeness_score >= 80
        assert updated.recommended_actions

    def test_build_production_guard_snapshot_blocks_additions_on_drawdown_and_wf_risk(self, monkeypatch):
        import api_server
        import portfolio_risk
        import walk_forward

        monkeypatch.setattr(api_server, "_cached_runtime_value", lambda *args, **kwargs: kwargs["builder"]())
        monkeypatch.setattr(
            api_server,
            "_build_world_state_snapshot",
            lambda: api_server.WorldStateSnapshot(
                regime="weak",
                regime_score=44.0,
                market_phase="weak_chop",
                market_phase_label="弱势拉扯",
                style_bias="轻仓短拿",
                horizon_hint="只做快切。",
                limit_up_mode="只做板前，不做板上",
                limit_up_allowed=False,
                should_trade=True,
                summary="弱势拉扯。",
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_execution_policy",
            lambda: api_server.ExecutionPolicySnapshot(
                regime="weak",
                market_phase="weak_chop",
                market_phase_label="弱势拉扯",
                style_bias="轻仓短拿",
                horizon_hint="只做快切。",
                aggressiveness="谨慎",
                risk_budget_pct=22.0,
                cash_buffer_pct=78.0,
                limit_up_mode="只做板前，不做板上",
                limit_up_allowed=False,
                allowed_styles=["竞价短拿"],
                blocked_styles=["高位接力"],
                allowed_strategies=["趋势跟踪选股"],
                observation_strategies=["低吸回调选股"],
                blocked_strategies=["隔夜选股"],
                preferred_holding_windows=["T+1/T+2"],
                summary="测试 execution policy",
                key_actions=["先控仓。"],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_strategy_governance",
            lambda: api_server.StrategyGovernanceSnapshot(
                regime="weak",
                market_phase="weak_chop",
                market_phase_label="弱势拉扯",
                summary="test",
                production_count=1,
                observation_count=0,
                disabled_count=0,
                items=[
                    api_server.StrategyGovernanceItem(
                        strategy_id="trend",
                        strategy_name="趋势跟踪选股",
                        family="trend",
                        state="production",
                        weight_pct=100.0,
                        top_down_fit=68.0,
                        recent_fit=52.0,
                        sample_count=9,
                        holding_window_cap="2-5天趋势跟踪",
                        discipline_label="主线滚动",
                        reason="test",
                    )
                ],
            ),
        )
        monkeypatch.setattr(
            portfolio_risk,
            "calc_portfolio_drawdown",
            lambda: {
                "current_drawdown_pct": -5.2,
                "max_drawdown_pct": -9.3,
                "drawdown_days": 6,
                "breached": False,
            },
        )
        monkeypatch.setattr(
            walk_forward,
            "get_wf_history",
            lambda strategy=None, days=45: [
                {
                    "strategy": strategy,
                    "summary": {
                        "overfitting_risk": "high",
                        "oos_efficiency": 0.58,
                        "oos_degradation": 0.71,
                    },
                }
            ],
        )

        snapshot = api_server._build_production_guard_snapshot()

        assert snapshot.blocked_additions is True
        assert snapshot.auto_reduce_positions is True
        assert snapshot.walk_forward_risk == "high"
        assert "趋势跟踪选股" in snapshot.unstable_strategies
        assert snapshot.actions

    def test_build_production_guard_actions_returns_ranked_position_actions(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_cached_runtime_value", lambda *args, **kwargs: kwargs["builder"]())
        monkeypatch.setattr(
            api_server,
            "_build_production_guard_snapshot",
            lambda: api_server.ProductionGuardSnapshot(
                market_phase="valuation_reset",
                market_phase_label="杀估值",
                hard_risk_gate=False,
                blocked_additions=True,
                auto_reduce_positions=True,
                auto_exit_losers=False,
                current_drawdown_pct=-3.6,
                max_drawdown_pct=-7.2,
                drawdown_days=4,
                walk_forward_risk="medium",
                unstable_strategies=["隔夜选股"],
                summary="先处理弱承接仓位。",
                actions=["先减仓。"],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_load_portfolio",
            lambda: {
                "positions": [
                    {"code": "000001", "quantity": 100},
                    {"code": "000002", "quantity": 200},
                ]
            },
        )

        def fake_detail(raw_position):
            code = raw_position["code"]
            mode = "优先减仓或平仓" if code == "000002" else "先锁盈"
            reduce_pct = 100 if code == "000002" else 50
            return api_server.PositionDetail(
                code=code,
                name=f"股票{code}",
                quantity=raw_position["quantity"],
                cost_price=10.0,
                current_price=11.0,
                market_value=2200.0,
                profit_loss=120.0 if code == "000001" else -160.0,
                profit_loss_pct=5.5 if code == "000001" else -8.0,
                hold_days=3,
                strategy="趋势跟踪选股",
                stop_loss=9.5,
                take_profit=12.5,
                buy_time="2026-03-30T09:30:00",
                high_price=11.2,
                low_price=9.8,
                trailing_stop=False,
                trailing_trigger_price=0.0,
                trades=[],
                position_guide=api_server.PositionGuide(
                    mode=mode,
                    summary=f"{code} {mode}",
                    next_action="处理",
                    event_bias="偏空",
                    event_score=42.0,
                    event_summary="偏空",
                    top_theme="AI",
                    sector_bucket="AI",
                    theme_alignment="一致",
                    can_add=False,
                    current_exposure_pct=42.0,
                    target_exposure_pct=18.0,
                    position_pct=14.0 if code == "000002" else 9.0,
                    current_theme_exposure_pct=28.0,
                    max_theme_exposure_pct=25.0,
                    suggested_stop_loss=10.2,
                    suggested_take_profit=12.0,
                    suggested_reduce_pct=reduce_pct,
                    suggested_reduce_quantity=raw_position["quantity"] if reduce_pct == 100 else 100,
                    concentration_summary=None,
                    warnings=["已有风险"],
                ),
                latest_signal=None,
            )

        monkeypatch.setattr(api_server, "_position_detail_model", fake_detail)

        actions = api_server._build_production_guard_actions(limit=5)

        assert len(actions) == 2
        assert actions[0].code == "000002"
        assert actions[0].action_label == "去平仓/减仓"
        assert actions[0].priority_score >= actions[1].priority_score
        assert actions[0].reasons


class TestPortfolioGuards:
    def test_open_signal_position_blocks_when_guard_blocks_additions(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_build_signal_detail",
            lambda signal_id: api_server.SignalDetail(
                id=signal_id,
                code="000001",
                name="平安银行",
                strategy="趋势跟踪选股",
                strategies=["趋势跟踪选股"],
                score=82.0,
                price=10.0,
                change_pct=1.2,
                high=10.2,
                low=9.8,
                volume=1000,
                turnover=100000,
                buy_price=10.0,
                stop_loss=9.5,
                target_price=11.0,
                risk_reward=2.0,
                timestamp="2026-03-30T10:00:00",
                consensus_count=2,
                factor_scores={},
                regime="neutral",
                regime_score=0.6,
                entry_guide=api_server.SignalEntryGuide(
                    mode="允许首仓",
                    summary="允许首仓",
                    action="先轻仓",
                    composite_score=78.0,
                    setup_label="主线孵化",
                    theme_sector="AI",
                    sector_bucket="AI",
                    theme_alignment="一致",
                    recommended_first_position_pct=8,
                    suggested_amount=1000.0,
                    suggested_quantity=100,
                    total_assets=100000.0,
                    max_single_position_pct=10,
                    max_theme_exposure_pct=25,
                    target_exposure_pct=40.0,
                    deployable_cash=5000.0,
                    current_theme_exposure_pct=8.0,
                    projected_theme_exposure_pct=9.0,
                    warnings=[],
                ),
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_production_guard_snapshot",
            lambda: api_server.ProductionGuardSnapshot(
                market_phase="valuation_reset",
                market_phase_label="杀估值",
                hard_risk_gate=False,
                blocked_additions=True,
                auto_reduce_positions=True,
                auto_exit_losers=False,
                current_drawdown_pct=-3.0,
                max_drawdown_pct=-6.0,
                drawdown_days=3,
                walk_forward_risk="medium",
                summary="当前先暂停新增。",
                actions=["暂停新增。"],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_strategy_governance",
            lambda: api_server.StrategyGovernanceSnapshot(
                regime="weak",
                market_phase="valuation_reset",
                market_phase_label="杀估值",
                summary="test",
                production_count=1,
                observation_count=0,
                disabled_count=0,
                items=[],
            ),
        )

        with pytest.raises(api_server.HTTPException) as excinfo:
            api_server._open_signal_position("sig-1", api_server.SignalOpenRequest(quantity=100))

        assert excinfo.value.status_code == 409
        assert "暂停新增" in str(excinfo.value.detail)

    def test_update_position_risk_rejects_widening_under_guard(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_load_portfolio",
            lambda: {
                "positions": [
                    {
                        "code": "000001",
                        "name": "平安银行",
                        "quantity": 100,
                        "stop_loss": 9.5,
                        "take_profit": 12.0,
                        "current_price": 10.5,
                        "trailing_trigger_price": 0,
                        "trades": [],
                    }
                ]
            },
        )
        monkeypatch.setattr(api_server, "_find_position_index", lambda portfolio, code: 0)
        monkeypatch.setattr(
            api_server,
            "_build_production_guard_snapshot",
            lambda: api_server.ProductionGuardSnapshot(
                market_phase="risk_off",
                market_phase_label="退潮避险",
                hard_risk_gate=True,
                blocked_additions=True,
                auto_reduce_positions=True,
                auto_exit_losers=True,
                current_drawdown_pct=-5.0,
                max_drawdown_pct=-8.0,
                drawdown_days=5,
                walk_forward_risk="high",
                summary="硬风控中。",
                actions=["降风险。"],
            ),
        )

        with pytest.raises(api_server.HTTPException) as excinfo:
            api_server._update_position_risk(
                "000001",
                api_server.PositionRiskUpdateRequest(stop_loss=9.0),
            )

        assert excinfo.value.status_code == 409
        assert "不允许下调止损" in str(excinfo.value.detail)


class TestExecutionPolicyExports:
    def test_write_export_exposes_latest_history_and_file_route(self, monkeypatch, tmp_path):
        import api_server

        monkeypatch.setattr(api_server, "_EXECUTION_POLICY_EXPORT_DIR", str(tmp_path / "execution_policy"))
        monkeypatch.setattr(
            api_server,
            "_execution_policy_export_payload",
            lambda period: {
                "period": period,
                "generated_at": "2026-03-30T09:30:00",
                "policy": {
                    "market_phase": "weak_chop",
                    "market_phase_label": "弱势拉扯",
                    "aggressiveness": "tight",
                    "risk_budget_pct": 38.0,
                    "cash_buffer_pct": 62.0,
                    "allowed_styles": ["轻仓短拿"],
                    "blocked_styles": ["高估值追涨"],
                    "allowed_strategies": ["集合竞价选股"],
                    "observation_strategies": ["低吸回调选股"],
                    "blocked_strategies": ["隔夜选股"],
                    "preferred_holding_windows": ["T+1/T+2"],
                    "summary": "测试摘要",
                    "key_actions": ["先控仓，再看承接。"],
                },
                "governance_summary": {
                    "production_count": 1,
                    "observation_count": 1,
                    "disabled_count": 1,
                    "top_production": ["集合竞价选股"],
                    "top_disabled": ["隔夜选股"],
                },
                "production_guard_actions": [
                    {
                        "code": "000001",
                        "name": "平安银行",
                        "mode": "先锁盈",
                        "action_label": "去锁盈/降仓",
                        "suggested_reduce_pct": 50,
                        "suggested_reduce_quantity": 100,
                        "priority_score": 72.0,
                        "summary": "先锁盈。",
                        "route": "/position/000001",
                    }
                ],
                "top_candidates": [
                    {
                        "code": "000001",
                        "name": "平安银行",
                        "strategy": "集合竞价选股",
                        "setup_label": "开盘速决",
                        "discipline_label": "竞价短拿",
                        "holding_window": "T+1/T+2",
                        "first_position_pct": 10.0,
                        "composite_score": 86.0,
                    }
                ],
                "limit_up_watchlist": [
                    {
                        "code": "000002",
                        "name": "万科A",
                        "strategy": "集合竞价选股",
                        "scenario_label": "板前确认",
                        "tradability_label": "可板前跟踪",
                        "holding_window": "T+1/T+2",
                        "opportunity_score": 82.0,
                    }
                ],
            },
        )

        manifest = api_server._write_execution_policy_export("daily")
        latest = api_server.get_execution_policy_export_latest(period="daily", ensure_fresh=False)
        history = api_server.get_execution_policy_export_history(period="daily", limit=5)
        status = api_server.get_execution_policy_export_status(period="daily", ensure_fresh=False)
        response = api_server.get_execution_policy_export_file(f"{manifest.export_id}.md")

        assert manifest.export_id.startswith("execution-policy-daily-20260330")
        assert latest.export_id == manifest.export_id
        assert history[0].export_id == manifest.export_id
        assert status.latest_export_id == manifest.export_id
        assert status.latest_bundle_route is not None
        assert status.latest_asset_count >= 7
        assert status.history_count >= 1
        assert response.path.endswith(f"{manifest.export_id}.md")
        bundle_response = api_server.get_execution_policy_export_file(f"{manifest.export_id}.bundle.zip")
        assert bundle_response.path.endswith(f"{manifest.export_id}.bundle.zip")
        assert any(asset.kind == "guard_actions_csv" for asset in manifest.assets)

    def test_build_ops_summary_includes_export_status_and_runtime_version(self, monkeypatch, tmp_path):
        import api_server

        app_config = tmp_path / "app.json"
        app_config.write_text('{"expo":{"version":"9.9.9"}}', encoding="utf-8")
        monkeypatch.setattr(api_server, "_NATIVE_APP_CONFIG", str(app_config))
        monkeypatch.setattr(api_server, "_readiness_snapshot", lambda: (True, []))
        monkeypatch.setattr(
            api_server,
            "_build_system_status",
            lambda: api_server.SystemStatus(
                status="running",
                uptime_hours=10.0,
                health_score=88,
                today_signals=4,
                active_strategies=6,
                ooda_cycles=12,
                decision_accuracy=0.66,
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_ops_data_status",
            lambda: api_server.OpsDataStatus(
                scorecard_records=10,
                trade_journal_records=5,
                signal_count=6,
                active_positions=2,
                feedback_items=1,
                push_devices=1,
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_learning_progress",
            lambda: api_server.LearningProgress(
                today_cycles=1,
                factor_adjustments=2,
                online_updates=3,
                experiments_running=0,
                new_factors_deployed=0,
                decision_accuracy=0.6,
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_learning_advance_status",
            lambda: api_server.LearningAdvanceStatus(
                status="pending",
                in_progress=False,
                today_completed=False,
                last_completed_at=None,
                health_status="ok",
                summary="测试",
                ingested_signals=1,
                verified_signals=2,
                reviewed_decisions=0,
                recommendations=[],
                checks=[],
            ),
        )
        monkeypatch.setattr(api_server, "_build_ops_recommendations", lambda **kwargs: [])
        monkeypatch.setattr(
            api_server,
            "_build_world_state_export_status",
            lambda period="daily", ensure_fresh=False: api_server.WorldStateExportStatus(
                period=period,
                latest_export_at="2026-03-30T09:25:00",
                latest_export_id="world-state-daily-20260330092500",
                latest_manifest_route="/api/world-state/export/files/world-state-daily-20260330092500.manifest.json",
                latest_report_route="/api/world-state/export/files/world-state-daily-20260330092500.md",
                latest_bundle_route="/api/world-state/export/files/world-state-daily-20260330092500.bundle.zip",
                latest_asset_count=6,
                history_count=2,
                stale=False,
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_execution_policy_export_status",
            lambda period="daily", ensure_fresh=False: api_server.ExecutionPolicyExportStatus(
                period=period,
                latest_export_at="2026-03-30T09:30:00",
                latest_export_id="execution-policy-daily-20260330093000",
                latest_manifest_route="/api/execution-policy/export/files/execution-policy-daily-20260330093000.manifest.json",
                latest_report_route="/api/execution-policy/export/files/execution-policy-daily-20260330093000.md",
                latest_bundle_route="/api/execution-policy/export/files/execution-policy-daily-20260330093000.bundle.zip",
                latest_asset_count=6,
                history_count=2,
                stale=False,
            ),
        )

        summary = api_server._build_ops_summary()

        assert summary.version == "9.9.9"
        assert summary.world_state_export is not None
        assert summary.world_state_export.latest_export_id == "world-state-daily-20260330092500"
        assert summary.world_state_export.latest_bundle_route == "/api/world-state/export/files/world-state-daily-20260330092500.bundle.zip"
        assert summary.world_state_export.latest_asset_count == 6
        assert summary.execution_policy_export is not None
        assert summary.execution_policy_export.latest_export_id == "execution-policy-daily-20260330093000"
        assert summary.execution_policy_export.latest_bundle_route == "/api/execution-policy/export/files/execution-policy-daily-20260330093000.bundle.zip"
        assert summary.execution_policy_export.latest_asset_count == 6
        assert api_server.root()["version"] == "9.9.9"

    def test_write_execution_policy_export_prunes_old_exports(self, monkeypatch, tmp_path):
        import api_server

        monkeypatch.setattr(api_server, "_EXECUTION_POLICY_EXPORT_DIR", str(tmp_path / "execution_policy"))
        monkeypatch.setattr(api_server, "_execution_policy_export_retention_limit", lambda period: 1)

        generated = iter(["2026-03-30T09:30:00", "2026-03-30T09:45:00"])

        def fake_payload(period):
            generated_at = next(generated)
            return {
                "period": period,
                "generated_at": generated_at,
                "policy": {
                    "market_phase": "weak_chop",
                    "market_phase_label": "弱势拉扯",
                    "aggressiveness": "tight",
                    "risk_budget_pct": 38.0,
                    "cash_buffer_pct": 62.0,
                    "allowed_styles": ["轻仓短拿"],
                    "blocked_styles": ["高估值追涨"],
                    "allowed_strategies": ["集合竞价选股"],
                    "observation_strategies": ["低吸回调选股"],
                    "blocked_strategies": ["隔夜选股"],
                    "preferred_holding_windows": ["T+1/T+2"],
                    "summary": "测试摘要",
                    "key_actions": ["先控仓，再看承接。"],
                },
                "world_state": {
                    "market_phase_label": "弱势拉扯",
                    "style_bias": "轻仓短拿",
                    "summary": "测试世界状态",
                },
                "governance_summary": {
                    "production_count": 1,
                    "observation_count": 1,
                    "disabled_count": 1,
                    "top_production": ["集合竞价选股"],
                    "top_disabled": ["隔夜选股"],
                },
                "governance_items": [],
                "top_candidates": [],
                "limit_up_watchlist": [],
            }

        monkeypatch.setattr(api_server, "_execution_policy_export_payload", fake_payload)

        first = api_server._write_execution_policy_export("daily")
        second = api_server._write_execution_policy_export("daily")

        history = api_server.get_execution_policy_export_history(period="daily", limit=10)
        export_dir = tmp_path / "execution_policy" / "daily"

        assert second.export_id != first.export_id
        assert [item.export_id for item in history] == [second.export_id]
        assert not (export_dir / f"{first.export_id}.manifest.json").exists()
        assert not (export_dir / f"{first.export_id}.bundle.zip").exists()
        assert (export_dir / f"{second.export_id}.manifest.json").exists()
        assert (export_dir / f"{second.export_id}.bundle.zip").exists()


class TestWorldStateExports:
    def test_write_world_state_export_and_fetch_routes(self, monkeypatch, tmp_path):
        import api_server

        monkeypatch.setattr(api_server, "_WORLD_STATE_EXPORT_DIR", str(tmp_path / "world_state"))
        monkeypatch.setattr(
            api_server,
            "_build_world_state_snapshot",
            lambda: api_server.WorldStateSnapshot(
                regime="neutral",
                regime_score=58.0,
                market_phase="range_rotation",
                market_phase_label="震荡轮动",
                valuation_regime="均衡定价",
                capital_style="产业链卡位",
                strategic_direction="AI与数字基础设施",
                technology_focus="AI/算力",
                geopolitics_bias="中性",
                supply_chain_mode="盈利扩散",
                technology_breakthrough_score=72.0,
                technology_breakthrough_summary="AI 基础设施资本开支继续扩散。",
                phase_confidence=74.0,
                style_bias="均衡轮动",
                horizon_hint="优先看 2-5 天结构确认。",
                limit_up_mode="只做板前确认",
                limit_up_allowed=True,
                should_trade=True,
                summary="测试世界状态",
                structural_summary="测试结构摘要",
                dominant_component="产业链控制力",
                components=[],
                source_statuses=[
                    {
                        "key": "news_digest",
                        "label": "全球新闻摘要",
                        "updated_at": "2026-03-30T09:30:00",
                        "freshness_score": 84.0,
                        "freshness_label": "新鲜",
                        "reliability_score": 66.0,
                        "authority_score": 46.0,
                        "timeliness_score": 84.0,
                        "signal_count": 12,
                        "summary": "测试",
                        "category": "news",
                        "external": True,
                        "required": True,
                        "fetch_mode": "auto",
                        "available": True,
                        "stale": False,
                        "data_quality_score": 68.0,
                    }
                ],
                top_directions=[
                    {
                        "direction_id": "dir-ai",
                        "direction": "AI与数字基础设施",
                        "focus_sector": "算力",
                        "policy_bucket": "科技",
                        "total_score": 86.0,
                        "event_score": 82.0,
                        "official_score": 74.0,
                        "timeline_score": 70.0,
                        "chain_control_score": 88.0,
                        "research_score": 66.0,
                        "technology_breakthrough_score": 78.0,
                        "technology_focus": "AI/算力",
                        "summary": "测试方向摘要",
                    }
                ],
                event_cascades=[
                    api_server.WorldEventCascade(
                        event_id="evt-1",
                        title="霍尔木兹扰动",
                        trigger_type="shipping_disruption",
                        severity="high",
                        trade_bias="reduce",
                        immediate_action="减持高耗油链",
                        continuity_focus="跟踪运力恢复",
                        transport_focus="霍尔木兹",
                        restriction_scope="partial_restriction",
                        estimated_flow_impact_pct=18.0,
                        affected_countries=["沙特"],
                        affected_routes=["霍尔木兹海峡"],
                        direct_beneficiaries=["油气上游"],
                        direct_losers=["航空"],
                        exposed_industries=["航空", "化工下游"],
                        second_order_impacts=["成长估值承压"],
                        commodity_links=["原油"],
                        evidence_count=3,
                        source_timestamp="2026-03-30T09:30:00",
                    )
                ],
                refresh_plan=None,
                actions=[
                    api_server.WorldStateAction(
                        key="add-energy",
                        level="high",
                        action_type="add",
                        priority=90,
                        title="增配能源安全",
                        summary="测试动作",
                        horizon="swing",
                        source_keys=["news_digest"],
                        targets=["油气上游"],
                    )
                ],
                operating_actions=[
                    api_server.WorldOperatingAction(
                        key="op-diversify",
                        level="high",
                        action_type="diversify",
                        priority=82,
                        title="双备份供应链",
                        summary="测试经营动作",
                        horizon="quarter",
                        targets=["供应链"],
                    )
                ],
                operating_profile=api_server.WorldOperatingProfile(
                    company_name="实体经营画像",
                    primary_industries=["能源化工", "工业软件"],
                    operating_mode="balanced",
                    order_visibility_months=4.5,
                    capacity_utilization_pct=82.0,
                    inventory_days=26,
                    supplier_concentration_pct=41.0,
                    customer_concentration_pct=36.0,
                    overseas_revenue_pct=22.0,
                    sensitive_region_exposure_pct=8.0,
                    cash_buffer_months=7.0,
                    capex_flexibility="medium",
                    inventory_strategy="balanced",
                    key_inputs=["原油", "工业控制芯片"],
                    key_routes=["中东航线"],
                    strategic_projects=["新产线"],
                    summary="经营画像测试摘要",
                    updated_at="2026-03-31T14:40:00",
                ),
                checks=[
                    api_server.WorldStateCheck(
                        key="check-1",
                        level="info",
                        title="继续跟踪",
                        message="测试检查",
                        suggestion="继续观察",
                        source_keys=["news_digest"],
                    )
                ],
            ),
        )

        manifest = api_server._write_world_state_export("daily")
        latest = api_server.get_world_state_export_latest(period="daily", ensure_fresh=False)
        history = api_server.get_world_state_export_history(period="daily", limit=5)
        status = api_server.get_world_state_export_status(period="daily", ensure_fresh=False)
        response = api_server.get_world_state_export_file(f"{manifest.export_id}.md")
        bundle_response = api_server.get_world_state_export_file(f"{manifest.export_id}.bundle.zip")

        assert manifest.export_id.startswith("world-state-daily-")
        assert latest.export_id == manifest.export_id
        assert history[0].export_id == manifest.export_id
        assert status.latest_export_id == manifest.export_id
        assert status.latest_bundle_route is not None
        assert status.latest_asset_count >= 7
        assert response.path.endswith(f"{manifest.export_id}.md")
        assert bundle_response.path.endswith(f"{manifest.export_id}.bundle.zip")
        assert any(asset.kind == "events_csv" for asset in manifest.assets)
        assert any(asset.kind == "operating_profile_csv" for asset in manifest.assets)

    def test_write_world_state_export_prunes_old_exports(self, monkeypatch, tmp_path):
        import api_server

        monkeypatch.setattr(api_server, "_WORLD_STATE_EXPORT_DIR", str(tmp_path / "world_state"))
        monkeypatch.setattr(api_server, "_world_state_export_retention_limit", lambda period: 1)

        generated = iter(["2026-03-30T09:30:00", "2026-03-30T09:45:00"])

        def fake_world_state():
            return api_server.WorldStateSnapshot(
                regime="neutral",
                regime_score=50.0,
                market_phase="range_rotation",
                market_phase_label="震荡轮动",
                valuation_regime="均衡定价",
                capital_style="均衡轮动",
                strategic_direction=None,
                technology_focus=None,
                geopolitics_bias="中性",
                supply_chain_mode="均衡供需",
                technology_breakthrough_score=50.0,
                technology_breakthrough_summary=None,
                phase_confidence=60.0,
                style_bias="均衡轮动",
                horizon_hint="测试",
                limit_up_mode="观察",
                limit_up_allowed=True,
                should_trade=True,
                summary="测试",
                structural_summary="测试",
                dominant_component="估值重构",
                components=[],
                source_statuses=[],
                top_directions=[],
                event_cascades=[],
                refresh_plan=None,
                actions=[],
                operating_actions=[],
                checks=[],
            )

        def fake_payload(period):
            generated_at = next(generated)
            snapshot = fake_world_state()
            return {
                "generated_at": generated_at,
                "period": period,
                "world_state": snapshot.model_dump(),
                "source_statuses": [],
                "top_directions": [],
                "event_cascades": [],
                "actions": [],
                "operating_actions": [],
                "checks": [],
            }

        monkeypatch.setattr(api_server, "_build_world_state_snapshot", fake_world_state)
        monkeypatch.setattr(api_server, "_world_state_export_payload", fake_payload)

        first = api_server._write_world_state_export("daily")
        second = api_server._write_world_state_export("daily")

        history = api_server.get_world_state_export_history(period="daily", limit=10)
        export_dir = tmp_path / "world_state" / "daily"

        assert second.export_id != first.export_id
        assert [item.export_id for item in history] == [second.export_id]
        assert not (export_dir / f"{first.export_id}.manifest.json").exists()
        assert not (export_dir / f"{first.export_id}.bundle.zip").exists()
        assert (export_dir / f"{second.export_id}.manifest.json").exists()
        assert (export_dir / f"{second.export_id}.bundle.zip").exists()


class TestLimitUpOpportunities:
    def test_build_limit_up_opportunities_prefers_preboard_and_filters_disabled(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_cached_runtime_value", lambda *args, **kwargs: kwargs["builder"]())
        monkeypatch.setattr(
            api_server,
            "_build_world_state_snapshot",
            lambda: api_server.WorldStateSnapshot(
                regime="neutral",
                regime_score=60.0,
                market_phase="rotation_up",
                market_phase_label="轮动走强",
                style_bias="轮动+趋势兼顾",
                horizon_hint="更适合按 T+2/T+3 跟踪。",
                limit_up_mode="只做板前确认",
                limit_up_allowed=True,
                should_trade=True,
                summary="测试",
                drivers=[],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_production_guard_snapshot",
            lambda: api_server.ProductionGuardSnapshot(
                market_phase="rotation_up",
                market_phase_label="轮动走强",
                hard_risk_gate=False,
                blocked_additions=False,
                auto_reduce_positions=False,
                auto_exit_losers=False,
                current_drawdown_pct=-1.2,
                max_drawdown_pct=-4.0,
                drawdown_days=2,
                walk_forward_risk="medium",
                walk_forward_efficiency=0.72,
                walk_forward_degradation=0.24,
                unstable_strategies=[],
                summary="测试",
                actions=["测试"],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_strategy_governance",
            lambda: api_server.StrategyGovernanceSnapshot(
                regime="neutral",
                market_phase="rotation_up",
                market_phase_label="轮动走强",
                summary="测试",
                production_count=1,
                observation_count=0,
                disabled_count=1,
                items=[
                    api_server.StrategyGovernanceItem(
                        strategy_id="trend",
                        strategy_name="趋势跟踪选股",
                        family="trend",
                        state="production",
                        weight_pct=60.0,
                        top_down_fit=78.0,
                        recent_fit=72.0,
                        sample_count=10,
                        t1_win_rate=60.0,
                        t3_win_rate=55.0,
                        t5_win_rate=50.0,
                        avg_t1_return_pct=1.0,
                        avg_t3_return_pct=0.8,
                        avg_t5_return_pct=0.5,
                        holding_window_cap="2-5天趋势跟踪",
                        discipline_label="主线滚动",
                        reason="测试",
                    ),
                    api_server.StrategyGovernanceItem(
                        strategy_id="overnight",
                        strategy_name="隔夜选股",
                        family="overnight",
                        state="disabled",
                        weight_pct=0.0,
                        top_down_fit=20.0,
                        recent_fit=18.0,
                        sample_count=12,
                        t1_win_rate=22.0,
                        t3_win_rate=15.0,
                        t5_win_rate=10.0,
                        avg_t1_return_pct=-1.0,
                        avg_t3_return_pct=-2.0,
                        avg_t5_return_pct=-3.0,
                        holding_window_cap="隔日兑现",
                        discipline_label="隔日速决",
                        reason="测试",
                    ),
                ],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_strategies",
            lambda: [
                api_server.StrategyPerformance(
                    id="trend",
                    name="趋势跟踪选股",
                    status="active",
                    win_rate=62.5,
                    avg_return=0.21,
                    signal_count=120,
                    last_signal_time="2026-03-13T10:30:00",
                ),
                api_server.StrategyPerformance(
                    id="overnight",
                    name="隔夜选股",
                    status="active",
                    win_rate=22.0,
                    avg_return=-0.6,
                    signal_count=120,
                    last_signal_time="2026-03-13T16:45:00",
                ),
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_strong_moves",
            lambda days=1, limit=15: [
                api_server.StrongMoveCandidate(
                    id="strong-1",
                    signal_id="sig-1",
                    code="600111",
                    name="北方稀土",
                    strategy="趋势跟踪选股",
                    setup_label="波段候选",
                    conviction="high",
                    composite_score=86.0,
                    continuation_score=84.0,
                    swing_score=88.0,
                    strategy_win_rate=62.5,
                    price=21.5,
                    buy_price=21.5,
                    stop_loss=20.9,
                    target_price=22.8,
                    risk_reward=2.0,
                    timestamp="2026-03-13T10:30:00",
                    thesis="test",
                    next_step="test",
                    reasons=["test"],
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_build_theme_radar",
            lambda limit=8: [
                api_server.ThemeRadarItem(
                    id="theme-1",
                    sector="稀土永磁",
                    theme_type="concept",
                    change_pct=2.61,
                    score=66.3,
                    intensity="高热主线",
                    timestamp="2026-03-13T14:40:51",
                    narrative="test",
                    action="test",
                    risk_note="test",
                    message_hint="test",
                    linked_signal_id="sig-1",
                    linked_code="600111",
                    linked_name="北方稀土",
                    linked_setup_label="波段候选",
                    followers=[],
                )
            ],
        )
        monkeypatch.setattr(
            api_server,
            "_load_signal_records",
            lambda days=1: [
                {
                    "id": "sig-1",
                    "code": "600111",
                    "name": "北方稀土",
                    "strategy": "趋势跟踪选股",
                    "score": 0.91,
                    "price": 21.54,
                    "buy_price": 21.54,
                    "stop_loss": 20.92,
                    "target_price": 22.68,
                    "risk_reward": 2.0,
                    "timestamp": "2026-03-13T10:30:00",
                    "change_pct": 5.4,
                    "consensus_count": 2,
                    "regime": "neutral",
                    "factor_scores": {
                        "s_trend": 0.84,
                        "s_momentum": 0.81,
                        "s_hot": 0.78,
                        "s_volume_ratio": 0.73,
                        "s_fund_flow": 0.79,
                        "s_chip": 0.7,
                    },
                },
                {
                    "id": "sig-2",
                    "code": "600222",
                    "name": "太龙药业",
                    "strategy": "隔夜选股",
                    "score": 0.93,
                    "price": 8.2,
                    "buy_price": 8.2,
                    "stop_loss": 7.9,
                    "target_price": 8.9,
                    "risk_reward": 1.8,
                    "timestamp": "2026-03-13T16:45:00",
                    "change_pct": 7.8,
                    "consensus_count": 1,
                    "regime": "neutral",
                    "factor_scores": {
                        "s_trend": 0.55,
                        "s_hot": 0.62,
                        "s_fund_flow": 0.48,
                    },
                },
            ],
        )

        items = api_server._build_limit_up_opportunities(days=1, limit=5)

        assert items
        assert items[0].code == "600111"
        assert items[0].scenario_label == "板前确认"
        assert items[0].board_pattern == "换手板前确认"
        assert items[0].leader_uniqueness_score > 50
        assert items[0].follow_through_score > 50
        assert items[0].risk_gate == "允许板前/板后承接"
        assert all(item.code != "600222" for item in items)

    def test_build_limit_up_opportunities_respects_production_guard_block(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_cached_runtime_value", lambda *args, **kwargs: kwargs["builder"]())
        monkeypatch.setattr(
            api_server,
            "_build_world_state_snapshot",
            lambda: api_server.WorldStateSnapshot(
                regime="weak",
                regime_score=43.0,
                market_phase="weak_chop",
                market_phase_label="弱势拉扯",
                style_bias="轻仓短拿",
                horizon_hint="先防守。",
                limit_up_mode="只做板前确认",
                limit_up_allowed=True,
                should_trade=True,
                summary="测试",
                drivers=[],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_production_guard_snapshot",
            lambda: api_server.ProductionGuardSnapshot(
                market_phase="weak_chop",
                market_phase_label="弱势拉扯",
                hard_risk_gate=True,
                blocked_additions=True,
                auto_reduce_positions=True,
                auto_exit_losers=True,
                current_drawdown_pct=-6.4,
                max_drawdown_pct=-9.1,
                drawdown_days=5,
                walk_forward_risk="high",
                walk_forward_efficiency=0.46,
                walk_forward_degradation=0.73,
                unstable_strategies=["趋势跟踪选股"],
                summary="当前硬风控已禁止新增。",
                actions=["暂停新增仓位。"],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_strategy_governance",
            lambda: api_server.StrategyGovernanceSnapshot(
                regime="weak",
                market_phase="weak_chop",
                market_phase_label="弱势拉扯",
                summary="测试",
                production_count=1,
                observation_count=0,
                disabled_count=0,
                items=[
                    api_server.StrategyGovernanceItem(
                        strategy_id="trend",
                        strategy_name="趋势跟踪选股",
                        family="trend",
                        state="production",
                        weight_pct=100.0,
                        top_down_fit=70.0,
                        recent_fit=55.0,
                        sample_count=10,
                        holding_window_cap="2-5天趋势跟踪",
                        discipline_label="主线滚动",
                        reason="测试",
                    )
                ],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_strategies",
            lambda: [
                api_server.StrategyPerformance(
                    id="trend",
                    name="趋势跟踪选股",
                    status="active",
                    win_rate=61.0,
                    avg_return=0.2,
                    signal_count=30,
                    last_signal_time="2026-03-13T10:30:00",
                )
            ],
        )
        monkeypatch.setattr(api_server, "_build_strong_moves", lambda days=1, limit=15: [])
        monkeypatch.setattr(api_server, "_build_theme_radar", lambda limit=8: [])
        monkeypatch.setattr(
            api_server,
            "_load_signal_records",
            lambda days=1: [
                {
                    "id": "sig-1",
                    "code": "300001",
                    "name": "特锐德",
                    "strategy": "趋势跟踪选股",
                    "score": 0.9,
                    "price": 18.2,
                    "timestamp": "2026-03-13T10:30:00",
                    "change_pct": 4.6,
                    "consensus_count": 2,
                    "factor_scores": {
                        "s_trend": 0.8,
                        "s_momentum": 0.74,
                        "s_hot": 0.76,
                        "s_volume_ratio": 0.71,
                        "s_fund_flow": 0.72,
                    },
                }
            ],
        )

        items = api_server._build_limit_up_opportunities(days=1, limit=3)

        assert items
        assert items[0].tradability_label in {"禁止出手", "只做记录"}
        assert items[0].risk_gate in {"硬风控开启", "暂停新增仓位"}
        assert any("禁止新增仓位" in warning for warning in items[0].warnings)

    def test_build_limit_up_opportunities_filters_low_upside_spread(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_cached_runtime_value", lambda *args, **kwargs: kwargs["builder"]())
        monkeypatch.setattr(
            api_server,
            "_build_world_state_snapshot",
            lambda: api_server.WorldStateSnapshot(
                regime="neutral",
                regime_score=61.0,
                market_phase="rotation_up",
                market_phase_label="轮动走强",
                style_bias="轮动+确认",
                horizon_hint="先按 T+1/T+2 快切。",
                limit_up_mode="只做板前确认",
                limit_up_allowed=True,
                should_trade=True,
                summary="测试",
                drivers=[],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_production_guard_snapshot",
            lambda: api_server.ProductionGuardSnapshot(
                market_phase="rotation_up",
                market_phase_label="轮动走强",
                hard_risk_gate=False,
                blocked_additions=False,
                auto_reduce_positions=False,
                auto_exit_losers=False,
                current_drawdown_pct=-1.0,
                max_drawdown_pct=-3.0,
                drawdown_days=1,
                walk_forward_risk="medium",
                walk_forward_efficiency=0.76,
                walk_forward_degradation=0.18,
                unstable_strategies=[],
                summary="测试",
                actions=["测试"],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_strategy_governance",
            lambda: api_server.StrategyGovernanceSnapshot(
                regime="neutral",
                market_phase="rotation_up",
                market_phase_label="轮动走强",
                summary="测试",
                production_count=1,
                observation_count=0,
                disabled_count=0,
                items=[
                    api_server.StrategyGovernanceItem(
                        strategy_id="trend",
                        strategy_name="趋势跟踪选股",
                        family="trend",
                        state="production",
                        weight_pct=100.0,
                        top_down_fit=76.0,
                        recent_fit=68.0,
                        sample_count=12,
                        t1_win_rate=60.0,
                        t3_win_rate=53.0,
                        t5_win_rate=49.0,
                        avg_t1_return_pct=1.0,
                        avg_t3_return_pct=0.8,
                        avg_t5_return_pct=0.6,
                        holding_window_cap="2-5天趋势跟踪",
                        discipline_label="主线滚动",
                        reason="测试",
                    )
                ],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_build_strategies",
            lambda: [
                api_server.StrategyPerformance(
                    id="trend",
                    name="趋势跟踪选股",
                    status="active",
                    win_rate=63.0,
                    avg_return=0.24,
                    signal_count=42,
                    last_signal_time="2026-04-03T10:30:00",
                )
            ],
        )
        monkeypatch.setattr(api_server, "_build_strong_moves", lambda days=1, limit=15: [])
        monkeypatch.setattr(api_server, "_build_theme_radar", lambda limit=8: [])
        monkeypatch.setattr(
            api_server,
            "_load_signal_records",
            lambda days=1: [
                {
                    "id": "sig-tight",
                    "code": "300002",
                    "name": "神州泰岳",
                    "strategy": "趋势跟踪选股",
                    "score": 0.92,
                    "price": 10.0,
                    "buy_price": 10.0,
                    "stop_loss": 9.91,
                    "target_price": 10.18,
                    "risk_reward": 2.0,
                    "timestamp": "2026-04-03T10:30:00",
                    "change_pct": 4.6,
                    "consensus_count": 2,
                    "factor_scores": {
                        "s_trend": 0.84,
                        "s_momentum": 0.81,
                        "s_hot": 0.78,
                        "s_volume_ratio": 0.73,
                        "s_fund_flow": 0.79,
                    },
                }
            ],
        )

        items = api_server._build_limit_up_opportunities(days=1, limit=3)

        assert items == []


class TestHiddenAccumulationOpportunities:
    def test_build_hidden_accumulation_opportunities_filters_for_weak_market_pattern(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_cached_runtime_value", lambda *args, **kwargs: kwargs["builder"]())
        monkeypatch.setattr(
            api_server,
            "_build_world_state_snapshot",
            lambda: api_server.WorldStateSnapshot(
                regime="weak",
                regime_score=38.0,
                market_phase="valuation_reset",
                market_phase_label="杀估值",
                style_bias="防守低估值",
                horizon_hint="先按 T+1/T+2 快切。",
                limit_up_mode="禁做高位接力",
                limit_up_allowed=False,
                should_trade=True,
                summary="高估值方向承压，低拥挤小票更容易走相对强势。",
                drivers=[],
            ),
        )
        monkeypatch.setattr(
            api_server,
            "_load_hidden_accumulation_small_float_universe",
            lambda max_float_mv_yi=300.0: [
                {"code": "600817", "name": "宇通重工", "float_mv_yi": 59.2},
                {"code": "603284", "name": "林平发展", "float_mv_yi": 38.0},
            ],
        )

        def fake_series(code: str, count: int = 20):
            if code == "600817":
                closes = [10.56, 10.60, 10.66, 10.71, 10.76, 10.82, 10.87, 10.91, 10.90, 11.02, 11.10, 11.14, 11.19]
            else:
                closes = [43.90, 44.15, 45.14, 45.16, 45.36, 46.65, 47.07, 49.88, 50.41, 50.65, 51.10, 52.80, 53.90]
            rows = []
            prev_close = None
            for index, close in enumerate(closes, start=1):
                pct = None if prev_close is None else round((close / prev_close - 1.0) * 100.0, 2)
                rows.append({"date": f"2026-04-{index:02d}", "close": close, "pct": pct})
                prev_close = close
            return [row for row in rows if row["pct"] is not None]

        monkeypatch.setattr(api_server, "_load_hidden_accumulation_daily_series", fake_series)

        items = api_server._build_hidden_accumulation_opportunities(limit=5)

        assert [item.code for item in items] == ["600817"]
        assert items[0].streak_days >= 2
        assert items[0].consolidation_width_pct <= 12.0
        assert "小流通" in " ".join(items[0].reasons)

    def test_build_hidden_accumulation_message_includes_focus_names(self, monkeypatch):
        import api_server

        monkeypatch.setattr(
            api_server,
            "_build_hidden_accumulation_opportunities",
            lambda limit=3: [
                api_server.HiddenAccumulationOpportunity(
                    id="hidden-600817",
                    code="600817",
                    name="宇通重工",
                    market_phase="valuation_reset",
                    market_phase_label="杀估值",
                    float_mv_yi=59.2,
                    streak_days=4,
                    consolidation_width_pct=9.63,
                    streak_gain_pct=2.64,
                    setup_label="弱市隐蔽吸筹",
                    tradability_label="先按 T+1/T+2 看承接",
                    accumulation_score=82.0,
                    holding_window="T+1/T+2 快切确认",
                    action="回踩不破再看承接。",
                    thesis="测试",
                    reasons=["测试"],
                    recent_closes=[10.91, 10.90, 11.02, 11.10, 11.14, 11.19],
                    tail_pcts=[1.1, 0.73, 0.36, 0.45],
                ),
                api_server.HiddenAccumulationOpportunity(
                    id="hidden-600094",
                    code="600094",
                    name="大名城",
                    market_phase="valuation_reset",
                    market_phase_label="杀估值",
                    float_mv_yi=89.9,
                    streak_days=4,
                    consolidation_width_pct=10.11,
                    streak_gain_pct=3.64,
                    setup_label="弱市隐蔽吸筹",
                    tradability_label="先按 T+1/T+2 看承接",
                    accumulation_score=79.0,
                    holding_window="T+1/T+2 快切确认",
                    action="回踩不破再看承接。",
                    thesis="测试",
                    reasons=["测试"],
                    recent_closes=[4.10, 4.08, 4.09, 4.12, 4.18, 4.23],
                    tail_pcts=[0.25, 0.73, 1.46, 1.2],
                ),
            ],
        )

        message = api_server._build_hidden_accumulation_message()

        assert message is not None
        assert message["title"] == "弱市隐蔽吸筹"
        assert "600817 宇通重工" in message["body"]
        assert "600094 大名城" in message["body"]
        assert message["route"] == "/hidden-accumulation"

    def test_build_app_messages_includes_hidden_accumulation_message(self, monkeypatch):
        import api_server

        monkeypatch.setattr(api_server, "_cached_runtime_value", lambda *args, **kwargs: kwargs["builder"]())
        monkeypatch.setattr(api_server, "_load_app_message_center", lambda: {"items": []})
        monkeypatch.setattr(api_server, "_build_world_state_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_operating_profile_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_production_guard_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_health_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_learning_monitor_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_world_state_export_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_execution_policy_export_message", lambda: None)
        monkeypatch.setattr(
            api_server,
            "_build_hidden_accumulation_message",
            lambda: {
                "id": "msg_hidden_accumulation_valuation_reset_600817",
                "title": "弱市隐蔽吸筹",
                "body": "测试",
                "preview": "测试",
                "level": "info",
                "channel": "system_focus",
                "created_at": "2026-04-03T12:00:00",
                "route": "/world",
            },
        )
        monkeypatch.setattr(api_server, "_build_takeover_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_composite_focus_message", lambda: None)
        monkeypatch.setattr(api_server, "_build_industry_capital_focus_message", lambda: None)

        messages = api_server._build_app_messages(limit=3)

        assert messages
        assert messages[0].title == "弱市隐蔽吸筹"
        assert messages[0].route == "/world"
