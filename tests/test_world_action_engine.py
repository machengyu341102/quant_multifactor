import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestWorldActionEngine:
    def test_build_world_actions_and_checks_generates_actions_for_top_direction_and_event(self):
        from world_action_engine import build_world_actions_and_checks

        payload = build_world_actions_and_checks(
            market_phase="valuation_reset",
            market_phase_label="杀估值",
            valuation_regime="折现率压制",
            capital_style="通用技术扩散",
            strategic_direction="AI与数字基础设施",
            technology_focus="AI/算力",
            geopolitics_bias="中性",
            supply_chain_mode="产业链重构",
            style_bias="先防守后轮动",
            horizon_hint="优先按 T+1/T+2 管理。",
            limit_up_allowed=False,
            components=[],
            source_statuses=[
                {
                    "key": "news_digest",
                    "label": "全球新闻摘要",
                    "required": True,
                    "available": True,
                    "stale": False,
                },
                {
                    "key": "official_ingest",
                    "label": "官方口径入库",
                    "required": True,
                    "available": True,
                    "stale": False,
                },
            ],
            top_directions=[
                {
                    "direction_id": "ai-digital",
                    "direction": "AI与数字基础设施",
                    "focus_sector": "科技",
                    "technology_focus": "AI/算力",
                    "total_score": 82.0,
                    "event_score": 78.0,
                    "official_score": 52.0,
                    "chain_control_score": 76.0,
                    "research_score": 48.0,
                }
            ],
            event_cascades=[
                {
                    "title": "霍尔木兹海峡部分船只通行受限",
                    "severity": "warning",
                    "trade_bias": "保留受益仓位，边走边看",
                    "immediate_action": "维持油气/资源防御仓位，暂不追涨下游受损方向。",
                    "continuity_focus": "继续跟踪通行船型、放行比例、运价与保费变化。",
                    "direct_beneficiaries": ["油气开采", "油运", "黄金"],
                    "direct_losers": ["航空", "化工下游", "高估值科技"],
                }
            ],
        )

        assert payload["actions"]
        assert any(item["action_type"] == "add" for item in payload["actions"])
        assert any(item["action_type"] == "reduce" for item in payload["actions"])
        assert any("AI与数字基础设施" in item["title"] for item in payload["actions"])
        assert payload["checks"]
        assert any("官方确认" in item["title"] or "验证不足" in item["title"] for item in payload["checks"])

    def test_build_world_actions_and_checks_warns_on_required_source_issue(self):
        from world_action_engine import build_world_actions_and_checks

        payload = build_world_actions_and_checks(
            market_phase="rotation_up",
            market_phase_label="轮动走强",
            valuation_regime="成长重估",
            capital_style="产业链卡位",
            strategic_direction="国产替代与自主可控",
            technology_focus="自主可控/半导体",
            geopolitics_bias="博弈升温",
            supply_chain_mode="产业链重构",
            style_bias="轮动+趋势兼顾",
            horizon_hint="优先按 T+2/T+3 跟踪。",
            limit_up_allowed=True,
            components=[],
            source_statuses=[
                {
                    "key": "official_ingest",
                    "label": "官方口径入库",
                    "required": True,
                    "available": False,
                    "stale": True,
                }
            ],
            top_directions=[],
            event_cascades=[],
        )

        assert payload["checks"]
        assert payload["checks"][0]["title"] == "关键外部源偏旧"

    def test_build_world_actions_and_checks_marks_hard_sources_missing_or_degraded(self):
        from world_action_engine import build_world_actions_and_checks

        payload = build_world_actions_and_checks(
            market_phase="risk_off",
            market_phase_label="退潮避险",
            valuation_regime="防守与资源重估",
            capital_style="防守现金流",
            strategic_direction="能源安全与资源重估",
            technology_focus=None,
            geopolitics_bias="博弈升温",
            supply_chain_mode="产业链重构",
            style_bias="先防守后轮动",
            horizon_hint="优先按 T+1/T+2 管理。",
            limit_up_allowed=False,
            components=[],
            source_statuses=[
                {
                    "key": "official_fulltext",
                    "label": "官方全文原文",
                    "required": True,
                    "available": True,
                    "stale": False,
                    "fetch_mode": "remote_or_derived",
                    "remote_configured": False,
                    "degraded_to_derived": False,
                    "origin_mode": "derived",
                },
                {
                    "key": "shipping_ais",
                    "label": "航运/AIS 通道",
                    "required": False,
                    "available": True,
                    "stale": False,
                    "fetch_mode": "remote_or_derived",
                    "remote_configured": True,
                    "degraded_to_derived": True,
                    "origin_mode": "derived_fallback",
                },
                {
                    "key": "commodity_terminal",
                    "label": "商品终端价格",
                    "required": True,
                    "available": True,
                    "stale": False,
                    "fetch_mode": "remote_or_derived",
                    "remote_configured": False,
                    "degraded_to_derived": False,
                    "origin_mode": "derived",
                },
            ],
            top_directions=[],
            event_cascades=[
                {
                    "title": "霍尔木兹受限",
                    "trigger_type": "shipping_disruption",
                    "severity": "warning",
                    "trade_bias": "先防守",
                    "immediate_action": "先减受损方向。",
                    "continuity_focus": "继续观察船型与流量。",
                    "direct_beneficiaries": ["油气"],
                    "direct_losers": ["航空"],
                }
            ],
        )

        titles = [item["title"] for item in payload["checks"]]
        assert "关键硬源尚未直连" in titles
        assert "硬源已退回派生源" in titles
        assert "关键硬源当前无直连样本" in titles
        assert "敏感事件缺少硬源直连确认" in titles
        assert any(item["title"] == "事件交易先看硬源是否直连" for item in payload["actions"])

    def test_build_world_actions_and_checks_responds_to_event_follow_up_signal(self):
        from world_action_engine import build_world_actions_and_checks

        payload = build_world_actions_and_checks(
            market_phase="range_rotation",
            market_phase_label="震荡轮动",
            valuation_regime="成长重估",
            capital_style="均衡轮动",
            strategic_direction="AI与数字基础设施",
            technology_focus="AI/算力",
            geopolitics_bias="中性",
            supply_chain_mode="盈利扩散",
            style_bias="先确认后推进",
            horizon_hint="优先按 T+1/T+2 管理。",
            limit_up_allowed=True,
            components=[],
            source_statuses=[],
            top_directions=[],
            event_cascades=[
                {
                    "title": "霍尔木兹海峡恢复部分通行",
                    "severity": "info",
                    "trade_bias": "逐步兑现防御仓位",
                    "immediate_action": "逐步减油气/黄金/航运防御仓位，关注成长和出行修复。",
                    "continuity_focus": "继续跟踪复航节奏与风险溢价回落速度。",
                    "direct_beneficiaries": ["航空修复", "成长科技估值修复"],
                    "direct_losers": ["油气防御仓位"],
                    "follow_up_signal": "easing",
                    "confidence_score": 74.0,
                }
            ],
        )

        action_titles = [item["title"] for item in payload["actions"]]
        assert any("事件缓和" in title for title in action_titles)

    def test_build_world_actions_and_checks_warns_on_stale_or_missing_operating_profile(self):
        from world_action_engine import build_world_actions_and_checks

        payload = build_world_actions_and_checks(
            market_phase="range_rotation",
            market_phase_label="震荡轮动",
            valuation_regime="成长重估",
            capital_style="均衡轮动",
            strategic_direction="AI与数字基础设施",
            technology_focus="AI/算力",
            geopolitics_bias="中性",
            supply_chain_mode="盈利扩散",
            style_bias="先确认后推进",
            horizon_hint="优先按 T+1/T+2 管理。",
            limit_up_allowed=True,
            components=[],
            source_statuses=[],
            top_directions=[],
            event_cascades=[],
            operating_profile={
                "company_name": "测试经营体",
                "primary_industries": [],
                "order_visibility_months": 0,
                "capacity_utilization_pct": 0,
                "inventory_days": 0,
                "supplier_concentration_pct": 0,
                "customer_concentration_pct": 0,
                "cash_buffer_months": 0,
                "updated_at": "2026-03-01T10:00:00+08:00",
            },
        )

        titles = [item["title"] for item in payload["checks"]]
        assert "经营画像字段不完整" in titles
        assert "经营画像已偏旧" in titles
