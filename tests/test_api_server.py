"""
api_server.py 测试
=================
覆盖: 诊股增强、日日精进状态、运维建议
"""

import os
import sys
from datetime import date, datetime, timedelta

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


class TestAppMessages:
    def test_build_app_messages_sorted_and_limited(self, monkeypatch):
        import api_server

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

    def test_build_composite_picks_merges_strategy_theme_and_money_flow(self, monkeypatch):
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
        assert picks[0].first_position_pct >= 12
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
        assert "官方催化" in items[0].official_freshness_label
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
