from __future__ import annotations

from typing import Any


def _as_text_list(items: list[object], *, limit: int = 4) -> list[str]:
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in result:
            continue
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _priority(level: str, action_type: str) -> int:
    base = {"critical": 90, "warning": 70, "info": 50}.get(level, 40)
    return base + {
        "stockpile": 10,
        "diversify": 8,
        "hedge": 7,
        "expand": 6,
        "accelerate_rnd": 5,
        "defer_capex": 4,
        "observe": 2,
    }.get(action_type, 0)


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_world_operating_actions(
    *,
    valuation_regime: str,
    capital_style: str,
    strategic_direction: str | None,
    technology_focus: str | None,
    geopolitics_bias: str,
    supply_chain_mode: str,
    top_directions: list[dict[str, Any]],
    event_cascades: list[dict[str, Any]],
    operating_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    seen: set[str] = set()
    operating_profile = operating_profile or {}
    company_name = str(operating_profile.get("company_name") or "经营主体").strip() or "经营主体"
    order_visibility_months = _to_float(operating_profile.get("order_visibility_months")) or 0.0
    capacity_utilization_pct = _to_float(operating_profile.get("capacity_utilization_pct")) or 0.0
    inventory_days = int(_to_float(operating_profile.get("inventory_days")) or 0.0)
    supplier_concentration_pct = _to_float(operating_profile.get("supplier_concentration_pct")) or 0.0
    customer_concentration_pct = _to_float(operating_profile.get("customer_concentration_pct")) or 0.0
    overseas_revenue_pct = _to_float(operating_profile.get("overseas_revenue_pct")) or 0.0
    sensitive_region_exposure_pct = _to_float(operating_profile.get("sensitive_region_exposure_pct")) or 0.0
    cash_buffer_months = _to_float(operating_profile.get("cash_buffer_months")) or 0.0
    capex_flexibility = str(operating_profile.get("capex_flexibility") or "中性").strip() or "中性"
    inventory_strategy = str(operating_profile.get("inventory_strategy") or "按需补库").strip() or "按需补库"
    key_inputs = _as_text_list(list(operating_profile.get("key_inputs") or []), limit=4)
    key_routes = _as_text_list(list(operating_profile.get("key_routes") or []), limit=4)
    strategic_projects = _as_text_list(list(operating_profile.get("strategic_projects") or []), limit=4)

    def add_action(
        *,
        key: str,
        level: str,
        action_type: str,
        title: str,
        summary: str,
        horizon: str,
        targets: list[str] | None = None,
    ) -> None:
        if key in seen:
            return
        seen.add(key)
        actions.append(
            {
                "key": key,
                "level": level,
                "action_type": action_type,
                "priority": _priority(level, action_type),
                "title": title,
                "summary": summary,
                "horizon": horizon,
                "targets": _as_text_list(targets or []),
            }
        )

    top_direction = top_directions[0] if top_directions else None
    if top_direction is not None:
        direction = str(top_direction.get("direction") or "").strip()
        focus_sector = str(top_direction.get("focus_sector") or "").strip()
        if direction:
            add_action(
                key=f"direction_expand_{top_direction.get('direction_id') or 'primary'}",
                level="info",
                action_type="expand",
                title=f"沿 {direction} 做经营投入倾斜",
                summary=(
                    f"当前主导方向是 {direction}，优先把经营资源往"
                    f"{focus_sector or technology_focus or '主导链条'}倾斜，先抓真实订单和交付。"
                ),
                horizon="先看 1-2 个季度的项目、预算和交付节奏。",
                targets=[direction, focus_sector, technology_focus],
            )
            if capacity_utilization_pct >= 82.0:
                add_action(
                    key=f"direction_capacity_{top_direction.get('direction_id') or 'primary'}",
                    level="warning",
                    action_type="expand",
                    title="先扩瓶颈产能，再放大主导方向订单",
                    summary=(
                        f"{company_name} 当前产能利用率已到 {capacity_utilization_pct:.0f}% ，"
                        f"主导方向 {direction} 已经能看，先补瓶颈工序和关键交付，再接更大订单。"
                    ),
                    horizon="优先排未来 1-2 个季度的瓶颈产能与交付节奏。",
                    targets=[direction, focus_sector or direction, *strategic_projects],
                )
            if order_visibility_months >= 4.0:
                add_action(
                    key=f"direction_orders_{top_direction.get('direction_id') or 'primary'}",
                    level="info",
                    action_type="expand",
                    title="订单可见度够长，经营动作可以更前置",
                    summary=(
                        f"{company_name} 当前订单可见度约 {order_visibility_months:.1f} 个月，"
                        f"对 {direction} 不用只停留在研究层，可以前置排产、交付和客户转化。"
                    ),
                    horizon="以 1-2 个季度订单兑现为主线推进。",
                    targets=[direction, *strategic_projects],
                )

    if capital_style == "通用技术扩散":
        add_action(
            key="operating_accelerate_technology",
            level="info",
            action_type="accelerate_rnd",
            title="加快通用技术和基础设施投入",
            summary="优先加研发、算力、电力、网络和自动化改造，不要把技术主线只当成证券题材。",
            horizon="以 1-3 年产能、研发和资本开支节奏规划。",
            targets=[technology_focus or "AI/半导体", "电力", "网络"],
        )

    if supply_chain_mode == "产业链重构":
        add_action(
            key="operating_diversify_supply_chain",
            level="warning",
            action_type="diversify",
            title="提前做供应链备份和替代验证",
            summary=(
                f"当前更像产业链重构，先做供应商双备份、关键物料认证和交期冗余。"
                f"{company_name} 当前供应商集中度约 {supplier_concentration_pct:.0f}% ，不要等事件恶化后被动补救。"
            ),
            horizon="优先在未来 1-2 个季度完成关键替代验证。",
            targets=["关键物料", "核心设备", "备份供应商", *key_inputs],
        )
        if supplier_concentration_pct >= 45.0:
            add_action(
                key="operating_supplier_concentration",
                level="critical",
                action_type="diversify",
                title="单一供应商依赖偏高，先拆集中度",
                summary=(
                    f"{company_name} 供应商集中度已到 {supplier_concentration_pct:.0f}% ，"
                    "当前不适合继续把采购压在单一链路上，先把替代料号、备份厂和交期冗余做出来。"
                ),
                horizon="先在 1 个季度内完成关键供应商双备份。",
                targets=["供应商双备份", *key_inputs, *key_routes],
            )

    if geopolitics_bias == "博弈升温":
        add_action(
            key="operating_geopolitics_hedge",
            level="warning",
            action_type="hedge",
            title="提高地缘和区域暴露对冲",
            summary=(
                f"对高外部依赖客户、区域和结算链先做风险映射。"
                f"{company_name} 当前海外收入 {overseas_revenue_pct:.0f}% / 敏感区域暴露 {sensitive_region_exposure_pct:.0f}% ，"
                "先压缩单一地区和单一客户暴露。"
            ),
            horizon="按月更新客户、区域和结算风险敞口。",
            targets=["区域敞口", "客户集中度", "结算链路", *key_routes],
        )
        if customer_concentration_pct >= 40.0 or sensitive_region_exposure_pct >= 25.0:
            add_action(
                key="operating_customer_region_hedge",
                level="critical",
                action_type="hedge",
                title="客户和区域暴露偏高，先降单点风险",
                summary=(
                    f"{company_name} 客户集中度 {customer_concentration_pct:.0f}% / 敏感区域暴露 {sensitive_region_exposure_pct:.0f}% ，"
                    "当前先做客户分散、区域替代和结算链备份，再决定是否继续加区域订单。"
                ),
                horizon="优先按月降低单一客户与单一区域暴露。",
                targets=["客户分散", "区域替代", "结算备份"],
            )

    if valuation_regime == "折现率压制":
        add_action(
            key="operating_defer_optional_capex",
            level="warning",
            action_type="defer_capex",
            title="压缩可选资本开支，现金优先",
            summary=(
                f"当前更像估值和折现率压制阶段，非刚性扩产、低回报项目和可选 CAPEX 先往后排。"
                f"{company_name} 当前现金缓冲约 {cash_buffer_months:.1f} 个月 / CAPEX 弹性 {capex_flexibility}。"
            ),
            horizon="先按季度做现金流和回报率筛选。",
            targets=["可选 CAPEX", "低回报项目", "现金流"],
        )
        if cash_buffer_months <= 6.0:
            add_action(
                key="operating_cash_buffer",
                level="critical",
                action_type="defer_capex",
                title="现金缓冲偏薄，先保现金流",
                summary=(
                    f"{company_name} 现金缓冲只有 {cash_buffer_months:.1f} 个月，"
                    "折现率压制阶段先压非核心开支、慢回款项目和低回报扩产。"
                ),
                horizon="先按月盯现金流、库存周转和回款质量。",
                targets=["现金流", "库存周转", "回款质量"],
            )

    for cascade in event_cascades[:2]:
        trigger_type = str(cascade.get("trigger_type") or "").strip()
        if trigger_type == "commodity_supply_shock":
            add_action(
                key=f"event_stockpile_{cascade.get('event_id')}",
                level="warning",
                action_type="stockpile",
                title="锁关键原料与运力",
                summary=(
                    f"供给冲击下先锁原料、运力、保险和关键交期，再决定是否扩价和转嫁成本。"
                    f"当前库存策略是 {inventory_strategy} ，在 {inventory_days} 天库存下优先盯 {', '.join(key_inputs[:2]) or '关键原料'}。"
                ),
                horizon="按周跟踪运价、保费、放行比例和替代航线。",
                targets=["原油/天然气", "运力", "保险", "关键交付", *key_inputs, *key_routes],
            )
            if inventory_days <= 21:
                add_action(
                    key=f"event_stockpile_urgent_{cascade.get('event_id')}",
                    level="critical",
                    action_type="stockpile",
                    title="安全库存偏薄，先补原料和运力冗余",
                    summary=(
                        f"{company_name} 当前库存只有 {inventory_days} 天，"
                        "供给冲击下不适合继续按极致周转运行，先补安全库存和替代物流。"
                    ),
                    horizon="先在 2-4 周内补齐关键物料和航线冗余。",
                    targets=[*key_inputs, *key_routes],
                )
        elif trigger_type == "technology_sanction":
            add_action(
                key=f"event_diversify_{cascade.get('event_id')}",
                level="warning",
                action_type="diversify",
                title="优先补齐受限技术替代链",
                summary="技术限制不是交易脉冲，先做设备、材料、IP 和软件替代验证，确认谁真能接住订单。",
                horizon="按季度看替代率、良率和客户切换。",
                targets=["设备", "材料", "IP/EDA", "客户替代"],
            )
        elif trigger_type == "technology_breakthrough":
            add_action(
                key=f"event_accelerate_rnd_{cascade.get('event_id')}",
                level="info",
                action_type="accelerate_rnd",
                title="把技术突破转成产品和订单",
                summary="突破出现后先抓产品化、采购、交付和毛利，不要停在概念映射和讲故事。",
                horizon="以 1-4 个季度为单位跟踪订单兑现。",
                targets=["研发", "产品化", "采购", "交付", *strategic_projects],
            )

    actions.sort(key=lambda item: (-int(item["priority"]), item["title"]))
    return actions[:8]
