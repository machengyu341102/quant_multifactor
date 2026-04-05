import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestWeeklyReportExecutionPolicySection:
    def test_generate_weekly_report_includes_execution_policy_section(self, monkeypatch):
        import scorecard

        monkeypatch.setattr(scorecard, "safe_load_strict", lambda path: [])
        monkeypatch.setattr(scorecard, "calc_equity_curve", lambda days=None: {"nav_series": [], "total_return": 0, "max_drawdown": 0, "sharpe": 0})

        class DummyStatus:
            latest_export_id = "execution-policy-weekly-20260330143000"
            latest_export_at = "2026-03-30T14:30:00"
            latest_report_route = "/api/execution-policy/export/files/execution-policy-weekly-20260330143000.md"
            latest_bundle_route = "/api/execution-policy/export/files/execution-policy-weekly-20260330143000.bundle.zip"
            latest_asset_count = 6

        class DummyManifest:
            market_phase_label = "震荡轮动"
            risk_budget_pct = 52.0
            cash_buffer_pct = 48.0
            allowed_styles = ["趋势低吸"]
            blocked_styles = ["隔夜追涨"]
            allowed_strategies = ["趋势跟踪选股"]
            observation_strategies = ["低吸回调选股"]
            blocked_strategies = ["隔夜选股"]
            preferred_holding_windows = ["2-5天趋势跟踪"]

        class DummyWorldStateStatus:
            latest_export_id = "world-state-weekly-20260330143000"
            latest_export_at = "2026-03-30T14:30:00"
            latest_report_route = "/api/world-state/export/files/world-state-weekly-20260330143000.md"
            latest_bundle_route = "/api/world-state/export/files/world-state-weekly-20260330143000.bundle.zip"

        class DummyWorldStateManifest:
            market_phase_label = "震荡轮动"
            dominant_component = "产业链控制力"
            valuation_regime = "均衡定价"
            capital_style = "产业链卡位"
            geopolitics_bias = "中性"
            supply_chain_mode = "盈利扩散"
            technology_breakthrough_score = 78.0

        monkeypatch.setattr("api_server._build_execution_policy_export_status", lambda period="weekly", ensure_fresh=True: DummyStatus())
        monkeypatch.setattr("api_server._latest_execution_policy_export_manifest", lambda period="weekly", ensure_fresh=False: DummyManifest())
        monkeypatch.setattr("api_server._build_world_state_export_status", lambda period="weekly", ensure_fresh=True: DummyWorldStateStatus())
        monkeypatch.setattr("api_server._latest_world_state_export_manifest", lambda period="weekly", ensure_fresh=False: DummyWorldStateManifest())
        monkeypatch.setattr(
            "api_server._build_production_guard_actions",
            lambda limit=3: [
                type(
                    "GuardAction",
                    (),
                    {
                        "code": "000001",
                        "name": "平安银行",
                        "mode": "先锁盈",
                        "suggested_reduce_pct": 50,
                        "suggested_reduce_quantity": 100,
                        "summary": "先锁盈后观察。",
                    },
                )()
            ],
        )

        report = scorecard.generate_weekly_report()

        assert "### 执行策略矩阵" in report
        assert "execution-policy-weekly-20260330143000" in report
        assert "趋势跟踪选股" in report
        assert "2-5天趋势跟踪" in report
        assert "execution-policy-weekly-20260330143000.bundle.zip" in report
        assert "### 顶层世界状态归档" in report
        assert "world-state-weekly-20260330143000" in report
        assert "产业链控制力" in report
        assert "### 生产风控动作" in report
        assert "000001 平安银行" in report
