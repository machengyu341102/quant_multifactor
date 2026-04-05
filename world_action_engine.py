from __future__ import annotations

from typing import Any


def _as_text_list(items: list[object], *, limit: int = 3) -> list[str]:
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in result:
            continue
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _priority_for_action(level: str, action_type: str) -> int:
    base = {
        "critical": 90,
        "warning": 70,
        "info": 50,
    }.get(level, 40)
    return base + {
        "reduce": 10,
        "avoid": 8,
        "add": 6,
        "observe": 2,
    }.get(action_type, 0)


def _follow_up_label(signal: str) -> str:
    return {
        "escalating": "事件升级中",
        "confirming": "事件确认中",
        "easing": "事件缓和中",
        "mixed": "事件分歧中",
        "stable": "事件持续跟踪",
    }.get(signal, "事件持续跟踪")


def build_world_actions_and_checks(
    *,
    market_phase: str,
    market_phase_label: str,
    valuation_regime: str,
    capital_style: str,
    strategic_direction: str | None,
    technology_focus: str | None,
    geopolitics_bias: str,
    supply_chain_mode: str,
    style_bias: str,
    horizon_hint: str,
    limit_up_allowed: bool,
    components: list[dict[str, Any]],
    source_statuses: list[dict[str, Any]],
    top_directions: list[dict[str, Any]],
    event_cascades: list[dict[str, Any]],
    operating_profile: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    actions: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    seen_action_keys: set[str] = set()
    seen_check_keys: set[str] = set()

    def add_action(
        *,
        key: str,
        level: str,
        action_type: str,
        title: str,
        summary: str,
        horizon: str,
        source_keys: list[str],
        targets: list[str] | None = None,
    ) -> None:
        if key in seen_action_keys:
            return
        seen_action_keys.add(key)
        actions.append(
            {
                "key": key,
                "level": level,
                "action_type": action_type,
                "priority": _priority_for_action(level, action_type),
                "title": title,
                "summary": summary,
                "horizon": horizon,
                "source_keys": _as_text_list(source_keys, limit=4),
                "targets": _as_text_list(targets or [], limit=4),
            }
        )

    def add_check(
        *,
        key: str,
        level: str,
        title: str,
        message: str,
        suggestion: str | None = None,
        source_keys: list[str] | None = None,
    ) -> None:
        if key in seen_check_keys:
            return
        seen_check_keys.add(key)
        checks.append(
            {
                "key": key,
                "level": level,
                "title": title,
                "message": message,
                "suggestion": suggestion,
                "source_keys": _as_text_list(source_keys or [], limit=4),
            }
        )

    operating_profile = operating_profile if isinstance(operating_profile, dict) else {}
    if operating_profile:
        profile_updated_at = str(operating_profile.get("updated_at") or "").strip()
        missing_profile_fields = _as_text_list(list(operating_profile.get("missing_fields") or []), limit=6)
        if not missing_profile_fields:
            primary_industries = _as_text_list(list(operating_profile.get("primary_industries") or []), limit=4)
            order_visibility = float(operating_profile.get("order_visibility_months") or 0.0)
            capacity_utilization = float(operating_profile.get("capacity_utilization_pct") or 0.0)
            inventory_days = int(float(operating_profile.get("inventory_days") or 0.0))
            supplier_concentration = float(operating_profile.get("supplier_concentration_pct") or 0.0)
            customer_concentration = float(operating_profile.get("customer_concentration_pct") or 0.0)
            cash_buffer = float(operating_profile.get("cash_buffer_months") or 0.0)
            missing_profile_fields = [
                label
                for label, ok in (
                    ("主营行业", bool(primary_industries)),
                    ("订单可见度", order_visibility > 0.0),
                    ("产能利用率", capacity_utilization > 0.0),
                    ("库存天数", inventory_days > 0),
                    ("供应商集中度", supplier_concentration > 0.0),
                    ("客户集中度", customer_concentration > 0.0),
                    ("现金缓冲", cash_buffer > 0.0),
                )
                if not ok
            ]
        if missing_profile_fields:
            labels = " / ".join(missing_profile_fields[:4])
            add_check(
                key="operating_profile_missing_fields",
                level="warning",
                title="经营画像字段不完整",
                message=(
                    f"当前经营画像完整度 {float(operating_profile.get('completeness_score') or 0.0):.0f} 分，"
                    f"还缺关键字段：{labels}。"
                ),
                suggestion="补齐订单、产能、库存、客户/供应商集中度和现金缓冲，经营动作才会更准。",
                source_keys=["operating_profile"],
            )
        if bool(operating_profile.get("stale")) and profile_updated_at:
            freshness_label = str(operating_profile.get("freshness_label") or "偏旧")
            add_check(
                key="operating_profile_stale",
                level="warning",
                title="经营画像已偏旧",
                message=f"当前经营画像状态 {freshness_label}，订单、库存和暴露可能已经变化。",
                suggestion="至少按周更新一次经营画像，重大事件当天补一轮。",
                source_keys=["operating_profile"],
            )
        elif profile_updated_at:
            from datetime import datetime
            try:
                updated = datetime.fromisoformat(profile_updated_at.replace("Z", "+00:00"))
                now = datetime.now(updated.tzinfo) if updated.tzinfo else datetime.now()
                age_hours = max(0.0, (now - updated).total_seconds() / 3600.0)
                if age_hours > 24 * 7:
                    add_check(
                        key="operating_profile_stale",
                        level="warning",
                        title="经营画像已偏旧",
                        message=f"当前经营画像距今约 {age_hours/24:.1f} 天，订单、库存和暴露可能已经变化。",
                        suggestion="至少按周更新一次经营画像，重大事件当天补一轮。",
                        source_keys=["operating_profile"],
                    )
            except Exception:
                add_check(
                    key="operating_profile_timestamp_invalid",
                    level="info",
                    title="经营画像更新时间格式异常",
                    message="经营画像的更新时间无法解析，默认按当前快照理解。",
                    suggestion="把经营画像 updated_at 改成 ISO 时间。",
                    source_keys=["operating_profile"],
                )

    required_source_issues = [
        item for item in source_statuses if item.get("required") and (not item.get("available") or item.get("stale"))
    ]
    if required_source_issues:
        labels = _as_text_list([item.get("label") for item in required_source_issues], limit=3)
        add_check(
            key="required_sources_stale",
            level="warning",
            title="关键外部源偏旧",
            message=f"当前关键源存在时效问题：{' / '.join(labels)}。",
            suggestion="先确认外部源是否刷新，再放大事件驱动和强趋势仓位。",
            source_keys=[str(item.get("key") or "") for item in required_source_issues],
        )

    hard_sources = [
        item
        for item in source_statuses
        if str(item.get("fetch_mode") or "") == "remote_or_derived"
    ]
    required_hard_sources = [item for item in hard_sources if item.get("required")]
    missing_remote_hard_sources = [
        item for item in required_hard_sources if not item.get("remote_configured")
    ]
    degraded_hard_sources = [
        item for item in hard_sources if item.get("degraded_to_derived")
    ]
    live_hard_sources = [
        item for item in hard_sources if str(item.get("origin_mode") or "") == "remote_live"
    ]
    if missing_remote_hard_sources:
        labels = _as_text_list([item.get("label") for item in missing_remote_hard_sources], limit=4)
        add_check(
            key="required_hard_sources_not_configured",
            level="warning",
            title="关键硬源尚未直连",
            message=f"当前关键硬源仍未配置真实外网入口：{' / '.join(labels)}。",
            suggestion="优先补齐真实 URL/凭据，否则世界模型会继续依赖派生源兜底。",
            source_keys=[str(item.get("key") or "") for item in missing_remote_hard_sources],
        )
        add_action(
            key="hard_sources_missing_reduce_event_risk",
            level="warning",
            action_type="observe",
            title="事件交易先看硬源是否直连",
            summary="关键硬源未直连前，事件驱动、地缘交易和跨资产切换只做确认，不要放大仓位。",
            horizon="先短拿，等待硬源直连后再决定是否扩仓。",
            source_keys=[str(item.get("key") or "") for item in missing_remote_hard_sources],
            targets=["事件驱动", "跨资产切换", "地缘交易"],
        )
    if degraded_hard_sources:
        labels = _as_text_list([item.get("label") for item in degraded_hard_sources], limit=4)
        add_check(
            key="hard_sources_degraded_to_derived",
            level="warning",
            title="硬源已退回派生源",
            message=f"以下硬源当前没有拿到实时外网载荷，已回退派生源：{' / '.join(labels)}。",
            suggestion="先确认远端接口可用性，再决定是否继续按事件方向加仓。",
            source_keys=[str(item.get("key") or "") for item in degraded_hard_sources],
        )
    if required_hard_sources and not live_hard_sources:
        add_check(
            key="required_hard_sources_no_live_feed",
            level="warning",
            title="关键硬源当前无直连样本",
            message="当前关键硬源都没有形成实时直连样本，世界模型更像高质量派生判断，不是全硬源确认。",
            suggestion="先看方向，不要把单次事件判断当成完全确认的世界级结论。",
            source_keys=[str(item.get("key") or "") for item in required_hard_sources],
        )

    sensitive_event_cascades = [
        item
        for item in event_cascades
        if str(item.get("trigger_type") or "").strip() in {
            "shipping_disruption",
            "energy_disruption",
            "sanction_escalation",
            "macro_policy_shock",
        }
    ]
    if sensitive_event_cascades:
        sensitive_keys: list[str] = []
        sensitive_map = {
            "shipping_disruption": {"shipping_ais", "freight_rates"},
            "energy_disruption": {"commodity_terminal", "shipping_ais"},
            "sanction_escalation": {"official_fulltext", "macro_rates_fx"},
            "macro_policy_shock": {"macro_rates_fx", "official_fulltext"},
        }
        for item in sensitive_event_cascades:
            sensitive_keys.extend(sensitive_map.get(str(item.get("trigger_type") or "").strip(), set()))
        sensitive_keys = [item for item in sensitive_keys if item]
        weak_sensitive_sources = [
            item
            for item in hard_sources
            if str(item.get("key") or "") in sensitive_keys
            and str(item.get("origin_mode") or "") != "remote_live"
        ]
        if weak_sensitive_sources:
            labels = _as_text_list([item.get("label") for item in weak_sensitive_sources], limit=4)
            add_check(
                key="event_sensitive_hard_sources_not_live",
                level="critical" if geopolitics_bias == "博弈升温" else "warning",
                title="敏感事件缺少硬源直连确认",
                message=f"当前敏感事件正在主导市场，但这些关键硬源还未直连确认：{' / '.join(labels)}。",
                suggestion="先把相关方向按观察/减仓处理，等硬源确认后再决定是否加仓。",
                source_keys=[str(item.get("key") or "") for item in weak_sensitive_sources],
            )

    top_direction = top_directions[0] if top_directions else None
    if top_direction is not None:
        direction = str(top_direction.get("direction") or "").strip()
        if direction:
            targets = [
                direction,
                str(top_direction.get("focus_sector") or "").strip(),
                str(top_direction.get("technology_focus") or "").strip(),
            ]
            add_action(
                key=f"top_direction_{str(top_direction.get('direction_id') or 'primary')}",
                level="info",
                action_type="add",
                title=f"主配 {direction}",
                summary=(
                    f"{direction} 当前总分 {float(top_direction.get('total_score') or 0.0):.1f}，"
                    f"先沿 {style_bias} 和 {horizon_hint} 推进，不要被边缘映射带偏。"
                ),
                horizon=horizon_hint,
                source_keys=["news_digest", "official_ingest", "execution_timeline", "industry_research"],
                targets=targets,
            )
            if float(top_direction.get("event_score") or 0.0) >= 74.0 and float(top_direction.get("official_score") or 0.0) < 58.0:
                add_check(
                    key=f"direction_event_without_official_{top_direction.get('direction_id')}",
                    level="warning",
                    title="事件热度强于官方确认",
                    message=f"{direction} 当前更像事件推动，官方确认和兑现节奏还不足。",
                    suggestion="只做前排确认和跟踪，不要把短脉冲误判成长期重估。",
                    source_keys=["news_digest", "official_ingest"],
                )
            if float(top_direction.get("chain_control_score") or 0.0) >= 74.0 and float(top_direction.get("research_score") or 0.0) < 56.0:
                add_check(
                    key=f"direction_chain_without_research_{top_direction.get('direction_id')}",
                    level="warning",
                    title="产业链强但公司验证不足",
                    message=f"{direction} 具备产业链卡位优势，但公司层验证和订单证据还偏少。",
                    suggestion="先看核心环节和龙头，不要把所有映射票一起抬仓位。",
                    source_keys=["industry_research", "execution_timeline"],
                )

    if valuation_regime == "折现率压制":
        add_action(
            key="valuation_reduce_growth",
            level="warning",
            action_type="reduce",
            title="压缩高估值进攻仓位",
            summary="当前更像折现率和风险溢价主导，先减高估值追涨和远期想象仓位。",
            horizon="先按 T+1/T+2 管理，再看是否重新扩仓。",
            source_keys=["news_digest", "official_ingest"],
            targets=["高估值成长", "纯主题科技", "高 beta 追涨"],
        )
    elif valuation_regime == "成长重估":
        add_action(
            key="valuation_add_growth",
            level="info",
            action_type="add",
            title="沿成长重估主线滚动",
            summary="当前更偏成长重估，优先沿订单、资本开支和真突破链做主线滚动。",
            horizon=horizon_hint,
            source_keys=["official_ingest", "industry_research"],
            targets=[technology_focus or "成长主线", strategic_direction or "继续观察"],
        )
    elif valuation_regime == "防守与资源重估":
        add_action(
            key="valuation_add_resources",
            level="info",
            action_type="add",
            title="保留资源与防御定价",
            summary="当前更偏防守和资源重估，先留受益于通胀与安全冗余的方向。",
            horizon="优先看 2-5 天防御滚动，再观察是否延伸成中段波段。",
            source_keys=["news_digest", "execution_timeline"],
            targets=["资源", "能源安全", "高股息防御"],
        )

    if capital_style == "通用技术扩散":
        add_action(
            key="capital_technology_diffusion",
            level="info",
            action_type="add",
            title="围绕通用技术扩散布阵",
            summary="资金当前更偏 AI、半导体、电力、网络这些扩散链，优先配真资本开支受益环节。",
            horizon=horizon_hint,
            source_keys=["official_ingest", "industry_research", "execution_timeline"],
            targets=[technology_focus or "通用技术扩散", "算力", "电力", "网络"],
        )
    elif capital_style == "产业链卡位":
        add_action(
            key="capital_chain_control",
            level="info",
            action_type="add",
            title="优先卡位核心环节",
            summary="资金更偏设备、材料、资源、平台这些卡位环节，不要把利润最薄的映射票当主仓。",
            horizon="优先按 2-5 天结构确认推进。",
            source_keys=["industry_research", "execution_timeline"],
            targets=["设备", "材料", "资源", "平台型龙头"],
        )
    elif capital_style == "防守现金流":
        add_action(
            key="capital_defensive_cashflow",
            level="warning",
            action_type="avoid",
            title="先防守后进攻",
            summary="当前资金更偏防守现金流，不要用高换手、高弹性玩法去硬抗。",
            horizon="先短拿，等风险偏好修复后再放大进攻仓位。",
            source_keys=["news_digest"],
            targets=["高股息", "现金流稳健", "防御资产"],
        )

    if geopolitics_bias == "博弈升温":
        add_action(
            key="geopolitics_add_self_reliance",
            level="warning",
            action_type="observe",
            title="盯紧博弈升温下的自主可控",
            summary="当前博弈升温，优先跟踪自主可控、能源安全和供应链再定价，不要无视外部风险继续无差别追涨。",
            horizon="先以事件确认和分歧承接为主。",
            source_keys=["news_digest", "official_ingest"],
            targets=["自主可控", "能源安全", "军工安全链"],
        )

    if supply_chain_mode == "产业链重构":
        add_action(
            key="supply_chain_rebuild",
            level="info",
            action_type="add",
            title="跟踪产业链重构受益端",
            summary="当前更像供给链重排，优先看有替代能力、订单承接和定价权提升的环节。",
            horizon="先看 2-5 天确认，再看是否演变成中期重估。",
            source_keys=["execution_timeline", "industry_research"],
            targets=["上游资源", "核心设备", "国产替代"],
        )

    if not limit_up_allowed:
        add_action(
            key="limit_up_disabled",
            level="warning",
            action_type="avoid",
            title="禁做板上接力",
            summary=f"当前阶段是 {market_phase_label}，强势股只看板前和板后承接，不做板上追价。",
            horizon="只做确认，不做情绪冲顶。",
            source_keys=["news_digest"],
            targets=["板上接力", "缩量秒板", "孤板高标"],
        )

    for index, cascade in enumerate(event_cascades[:2], start=1):
        title = str(cascade.get("title") or "").strip()
        beneficiaries = _as_text_list(cascade.get("direct_beneficiaries", []) if isinstance(cascade.get("direct_beneficiaries"), list) else [], limit=4)
        losers = _as_text_list(cascade.get("direct_losers", []) if isinstance(cascade.get("direct_losers"), list) else [], limit=4)
        trade_bias = str(cascade.get("trade_bias") or "").strip()
        immediate_action = str(cascade.get("immediate_action") or "").strip()
        continuity_focus = str(cascade.get("continuity_focus") or "").strip() or horizon_hint
        severity = str(cascade.get("severity") or "info").strip() or "info"
        follow_up_signal = str(cascade.get("follow_up_signal") or "stable").strip() or "stable"
        confidence_score = float(cascade.get("confidence_score") or 0.0)
        follow_up_label = _follow_up_label(follow_up_signal)
        if beneficiaries:
            add_action(
                key=f"cascade_add_{index}",
                level=severity if severity in {"critical", "warning"} else "info",
                action_type="add",
                title=f"事件受益链：{title}",
                summary=f"{trade_bias}。{immediate_action} {follow_up_label} / 可信度 {confidence_score:.0f}。",
                horizon=continuity_focus,
                source_keys=["news_digest"],
                targets=beneficiaries,
            )
        if losers:
            add_action(
                key=f"cascade_reduce_{index}",
                level="warning" if severity in {"critical", "warning"} else "info",
                action_type="reduce",
                title=f"事件受损链：{title}",
                summary=f"优先压缩 {' / '.join(losers[:3])}，避免把二阶受损方向当成低吸机会。{follow_up_label} / 可信度 {confidence_score:.0f}。",
                horizon=continuity_focus,
                source_keys=["news_digest"],
                targets=losers,
            )
        if follow_up_signal == "escalating":
            add_check(
                key=f"cascade_escalating_{index}",
                level="critical" if severity == "critical" else "warning",
                title="事件升级继续发酵",
                message=f"{title} 正在继续升级，先按 5m/15m 节奏盯后续确认，不要用旧结论硬扛。",
                suggestion="先看限制范围、放行比例、二阶受损和硬源确认，再决定是否继续放大仓位。",
                source_keys=["news_digest"],
            )
        elif follow_up_signal == "easing":
            add_action(
                key=f"cascade_easing_{index}",
                level="info",
                action_type="observe",
                title=f"事件缓和：{title}",
                summary="风险溢价开始回落，优先兑现纯脉冲仓位，再观察修复链是否形成持续性。",
                horizon="先看 1-2 个节奏确认，不急着把缓和直接当成反转。",
                source_keys=["news_digest"],
                targets=beneficiaries or losers,
            )
        elif confidence_score < 58.0:
            add_check(
                key=f"cascade_low_confidence_{index}",
                level="warning",
                title="事件确认还不够厚",
                message=f"{title} 当前可信度只有 {confidence_score:.0f}，更像早期判断，不适合直接放大方向仓位。",
                suggestion="先等更多新闻、官方口径或硬源确认，再决定是跟进还是反手。",
                source_keys=["news_digest"],
            )

    if technology_focus and "AI" in technology_focus and valuation_regime == "折现率压制":
        add_check(
            key="tech_vs_valuation_conflict",
            level="warning",
            title="科技主线与估值压制并存",
            message="当前科技主线存在，但折现率压制仍在，强科技只适合做确认后龙头，不适合普涨幻想。",
            suggestion="把科技仓位集中到最能兑现订单和资本开支的环节。",
            source_keys=["news_digest", "official_ingest", "industry_research"],
        )

    if market_phase in {"risk_off", "valuation_reset"} and strategic_direction:
        add_check(
            key="phase_requires_selectivity",
            level="info",
            title="当前只做少数强主线",
            message=f"{market_phase_label} 下不要面铺开做，优先只围绕 {strategic_direction} 前排确认。",
            suggestion="少做分散试错，多做聚焦验证。",
            source_keys=["news_digest", "execution_timeline"],
        )

    actions.sort(key=lambda item: (-int(item.get("priority") or 0), str(item.get("key") or "")))
    checks.sort(
        key=lambda item: (
            {"critical": 0, "warning": 1, "info": 2}.get(str(item.get("level") or "info"), 2),
            str(item.get("key") or ""),
        )
    )
    return {
        "actions": actions[:8],
        "checks": checks[:6],
    }
