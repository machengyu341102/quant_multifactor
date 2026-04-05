import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestWorldEventCascade:
    def test_build_event_cascades_detects_oil_shipping_shock(self):
        from world_event_cascade import build_event_cascades

        cascades = build_event_cascades(
            [
                {
                    "title": "霍尔木兹海峡部分船只通行受限，原油运价走高",
                    "summary": "伊朗与美国博弈升级，油轮、保险与绕航成本抬升。",
                    "strategy_implications": "继续跟踪霍尔木兹海峡是否全面封锁，确认影响国家、船型和放行比例。",
                    "category": "commodity",
                    "impact_magnitude": 4,
                    "timestamp": "2026-03-30T10:00:00",
                }
            ]
        )

        assert cascades
        top = cascades[0]
        assert top["trigger_type"] == "commodity_supply_shock"
        assert "霍尔木兹海峡" in top["affected_routes"]
        assert "油气开采" in top["direct_beneficiaries"]
        assert top["trade_bias"] in {"继续增配受益方向", "保留受益仓位，边走边看"}
        assert top["restriction_scope"] in {"full_blockade", "partial_restriction", "specific_vessels", "inspection_delay"}
        assert top["estimated_flow_impact_pct"] > 0
        assert "航空" in top["exposed_industries"]
        assert top["theme_key"].startswith("commodity_supply_shock:")
        assert top["follow_up_signal"] in {"stable", "escalating"}
        assert top["confidence_score"] > 0

    def test_build_event_cascades_detects_chip_sanction(self):
        from world_event_cascade import build_event_cascades

        cascades = build_event_cascades(
            [
                {
                    "title": "美国升级芯片出口管制，国产替代预期升温",
                    "summary": "半导体设备和材料链关注度抬升。",
                    "strategy_implications": "看替代节奏和客户切换。",
                    "category": "trade",
                    "impact_magnitude": 3,
                    "timestamp": "2026-03-30T11:00:00",
                }
            ]
        )

        assert cascades
        top = cascades[0]
        assert top["trigger_type"] == "technology_sanction"
        assert "国产替代" in "".join(top["direct_beneficiaries"])

    def test_build_event_cascades_prefers_ai_breakthrough_over_generic_tech_category(self):
        from world_event_cascade import build_event_cascades

        cascades = build_event_cascades(
            [
                {
                    "title": "两部门：推动人工智能、脑机接口等与医疗装备融合创新",
                    "summary": "围绕人工智能、脑机接口和设备创新推进产业化。",
                    "strategy_implications": "看资本开支、订单和量产节奏。",
                    "category": "tech",
                    "impact_magnitude": 3,
                    "timestamp": "2026-03-31T10:00:00",
                }
            ]
        )

        assert cascades
        assert cascades[0]["trigger_type"] == "technology_breakthrough"
        assert cascades[0]["theme_key"].startswith("technology_breakthrough:")

    def test_build_event_cascades_groups_same_theme_and_marks_easing(self):
        from world_event_cascade import build_event_cascades

        cascades = build_event_cascades(
            [
                {
                    "title": "霍尔木兹海峡几乎完全关闭，原油和天然气价格飙升",
                    "summary": "运输中断，保险和绕航成本快速上行。",
                    "strategy_implications": "跟踪封锁范围。",
                    "category": "commodity",
                    "impact_magnitude": 5,
                    "timestamp": "2026-03-30T09:00:00",
                },
                {
                    "title": "霍尔木兹海峡逐步恢复通行，部分油轮复航",
                    "summary": "市场开始讨论复航节奏与风险溢价回落。",
                    "strategy_implications": "继续跟踪复航比例。",
                    "category": "commodity",
                    "impact_magnitude": 4,
                    "timestamp": "2026-03-30T11:30:00",
                },
            ]
        )

        assert len(cascades) == 1
        top = cascades[0]
        assert top["evidence_count"] == 2
        assert top["follow_up_signal"] == "easing"
        assert top["peak_severity"] == "critical"
        assert top["severity"] == "info"
        assert top["confidence_score"] >= 50
