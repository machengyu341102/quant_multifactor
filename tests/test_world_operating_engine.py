import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestWorldOperatingEngine:
    def test_build_world_operating_actions_generates_expand_and_stockpile(self):
        from world_operating_engine import build_world_operating_actions

        payload = build_world_operating_actions(
            valuation_regime="折现率压制",
            capital_style="通用技术扩散",
            strategic_direction="AI与数字基础设施",
            technology_focus="AI/算力",
            geopolitics_bias="博弈升温",
            supply_chain_mode="产业链重构",
            top_directions=[
                {
                    "direction_id": "ai-digital",
                    "direction": "AI与数字基础设施",
                    "focus_sector": "科技",
                }
            ],
            event_cascades=[
                {
                    "event_id": "oil-1",
                    "trigger_type": "commodity_supply_shock",
                }
            ],
            operating_profile={
                "company_name": "测试经营体",
                "order_visibility_months": 4.6,
                "capacity_utilization_pct": 86.0,
                "inventory_days": 18,
                "supplier_concentration_pct": 52.0,
                "customer_concentration_pct": 44.0,
                "overseas_revenue_pct": 35.0,
                "sensitive_region_exposure_pct": 28.0,
                "cash_buffer_months": 5.0,
                "capex_flexibility": "低弹性",
                "inventory_strategy": "安全库存优先",
                "key_inputs": ["高端材料"],
                "key_routes": ["中东能源航线"],
                "strategic_projects": ["算力基础设施"],
            },
        )

        assert payload
        assert any(item["action_type"] == "expand" for item in payload)
        assert any(item["action_type"] == "stockpile" for item in payload)
        assert any("双备份" in item["summary"] or "替代验证" in item["summary"] for item in payload)
        assert any("现金缓冲" in item["summary"] for item in payload)
        assert any("供应商集中度" in item["summary"] or "客户集中度" in item["summary"] for item in payload)
