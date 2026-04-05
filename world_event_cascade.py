from __future__ import annotations

from datetime import datetime
import re
from typing import Any


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_SEVERITY_RANK = {
    "critical": 3,
    "warning": 2,
    "info": 1,
}


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1]
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _severity_rank(value: object) -> int:
    return _SEVERITY_RANK.get(str(value or "info").strip(), 1)


def _severity_label(rank: int) -> str:
    for label, value in _SEVERITY_RANK.items():
        if value == rank:
            return label
    return "info"


def _unique_texts(items: list[object], *, limit: int = 8) -> list[str]:
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in result:
            continue
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _freshness_bonus(timestamp: object) -> float:
    parsed = _parse_datetime(timestamp)
    if parsed is None:
        return 0.0
    age_hours = max(0.0, (datetime.now() - parsed).total_seconds() / 3600.0)
    if age_hours <= 1:
        return 10.0
    if age_hours <= 6:
        return 8.0
    if age_hours <= 24:
        return 5.0
    if age_hours <= 48:
        return 2.0
    return 0.0


def _cluster_follow_up_signal(cluster: list[dict[str, Any]]) -> str:
    if not cluster:
        return "stable"
    ordered = sorted(
        cluster,
        key=lambda item: _parse_datetime(item.get("source_timestamp")) or datetime.min,
    )
    latest = ordered[-1]
    latest_signal = str(latest.get("follow_up_signal") or "").strip() or "stable"
    if latest_signal == "easing":
        return "easing"
    latest_rank = _severity_rank(latest.get("severity"))
    earliest_rank = _severity_rank(ordered[0].get("severity"))
    if latest_signal == "escalating" or latest_rank > earliest_rank:
        return "escalating"
    unique_signals = {str(item.get("follow_up_signal") or "stable").strip() or "stable" for item in ordered}
    if len(unique_signals) >= 3:
        return "mixed"
    if len(cluster) >= 3:
        return "confirming"
    if len(unique_signals) > 1:
        return "mixed"
    return latest_signal or "stable"


def _cluster_confidence_score(cluster: list[dict[str, Any]]) -> float:
    if not cluster:
        return 50.0
    latest = max(
        cluster,
        key=lambda item: _parse_datetime(item.get("source_timestamp")) or datetime.min,
    )
    evidence_count = max(1, len(cluster))
    impact = max((_to_float(item.get("impact_magnitude")) or 0.0) for item in cluster)
    severity_rank = max(_severity_rank(item.get("severity")) for item in cluster)
    follow_up = _cluster_follow_up_signal(cluster)
    score = (
        42.0
        + min(24.0, evidence_count * 7.5)
        + min(12.0, impact * 3.0)
        + severity_rank * 4.0
        + _freshness_bonus(latest.get("source_timestamp"))
        + (6.0 if follow_up == "confirming" else 0.0)
        - (4.0 if follow_up == "mixed" else 0.0)
    )
    return max(0.0, min(98.0, round(score, 1)))


def _aggregate_cascade_cluster(cluster: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        cluster,
        key=lambda item: _parse_datetime(item.get("source_timestamp")) or datetime.min,
    )
    latest = ordered[-1]
    peak_severity_rank = max(_severity_rank(item.get("severity")) for item in ordered)
    follow_up_signal = _cluster_follow_up_signal(ordered)
    confidence_score = _cluster_confidence_score(ordered)
    return {
        **latest,
        "severity": str(latest.get("severity") or "info"),
        "peak_severity": _severity_label(peak_severity_rank),
        "evidence_count": len(ordered),
        "follow_up_signal": follow_up_signal,
        "confidence_score": confidence_score,
        "affected_countries": _unique_texts(
            [country for item in ordered for country in item.get("affected_countries", [])],
            limit=8,
        ),
        "affected_routes": _unique_texts(
            [route for item in ordered for route in item.get("affected_routes", [])],
            limit=6,
        ),
        "direct_beneficiaries": _unique_texts(
            [target for item in ordered for target in item.get("direct_beneficiaries", [])],
            limit=6,
        ),
        "direct_losers": _unique_texts(
            [target for item in ordered for target in item.get("direct_losers", [])],
            limit=6,
        ),
        "exposed_industries": _unique_texts(
            [target for item in ordered for target in item.get("exposed_industries", [])],
            limit=8,
        ),
        "second_order_impacts": _unique_texts(
            [target for item in ordered for target in item.get("second_order_impacts", [])],
            limit=6,
        ),
        "commodity_links": _unique_texts(
            [target for item in ordered for target in item.get("commodity_links", [])],
            limit=6,
        ),
    }


def _detect_countries(text: str) -> list[str]:
    mapping = {
        "伊朗": "伊朗",
        "美国": "美国",
        "以色列": "以色列",
        "中国": "中国",
        "沙特": "沙特",
        "阿联酋": "阿联酋",
        "印度": "印度",
        "欧洲": "欧洲",
        "欧盟": "欧盟",
        "日本": "日本",
        "韩国": "韩国",
        "俄罗斯": "俄罗斯",
    }
    result: list[str] = []
    for token, label in mapping.items():
        if token in text and label not in result:
            result.append(label)
    return result[:6]


def _detect_routes(text: str) -> list[str]:
    routes = []
    for token, label in {
        "霍尔木兹": "霍尔木兹海峡",
        "霍尔木兹海峡": "霍尔木兹海峡",
        "红海": "红海",
        "苏伊士": "苏伊士运河",
        "巴拿马": "巴拿马运河",
        "曼德海峡": "曼德海峡",
    }.items():
        if token in text and label not in routes:
            routes.append(label)
    return routes[:4]


def _extract_percent(text: str) -> float | None:
    match = re.search(r"(\d{1,3})(?:\.\d+)?\s*%", text)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return max(0.0, min(100.0, value))


def _oil_cascade(title: str, text: str, event: dict[str, Any]) -> dict[str, Any]:
    routes = _detect_routes(text)
    countries = _detect_countries(text)
    blocked = _contains_any(text, ("封锁", "关闭", "中断", "阻断", "禁运", "不让通过"))
    partial = _contains_any(text, ("限行", "检查", "特定船只", "保险上调", "绕航", "减量通过"))
    easing = _contains_any(text, ("恢复", "复航", "缓和", "停火", "让步", "谈判"))
    specific_vessels = _contains_any(text, ("特定船只", "特定船型", "油轮", "lng船", "化学品船", "油船"))
    inspected = _contains_any(text, ("检查", "抽检", "安检"))
    flow_impact = _extract_percent(text)
    restriction_scope = "normal"

    if blocked:
        severity = "critical"
        continuity = "持续跟踪封锁范围、持续时间、替代航线与保险成本。"
        trade_bias = "继续增配受益方向"
        immediate_action = "增配能源安全、油气开采、油运和防御资产；压缩航空、化工下游和高估值成长。"
        restriction_scope = "full_blockade"
        follow_up_signal = "escalating"
    elif partial:
        severity = "warning"
        continuity = "继续跟踪通行船型、放行比例、运价与保费变化。"
        trade_bias = "保留受益仓位，边走边看"
        immediate_action = "维持油气/资源防御仓位，暂不追涨下游受损方向。"
        restriction_scope = "specific_vessels" if specific_vessels else "partial_restriction"
        follow_up_signal = "stable"
    elif easing:
        severity = "info"
        continuity = "继续跟踪复航节奏与风险溢价回落速度。"
        trade_bias = "逐步兑现防御仓位"
        immediate_action = "逐步减油气/黄金/航运防御仓位，关注成长和出行修复。"
        restriction_scope = "easing"
        follow_up_signal = "easing"
    else:
        severity = "warning"
        continuity = "继续跟踪油价、运价、通行限制和地缘升级信号。"
        trade_bias = "保持防御偏置"
        immediate_action = "先保留能源安全与资源仓位，再看事件是否升级成供给中断。"
        if inspected:
            restriction_scope = "inspection_delay"
        follow_up_signal = "stable"

    if flow_impact is None:
        if restriction_scope == "full_blockade":
            flow_impact = 80.0
        elif restriction_scope == "specific_vessels":
            flow_impact = 30.0
        elif restriction_scope in {"partial_restriction", "inspection_delay"}:
            flow_impact = 20.0
        elif restriction_scope == "easing":
            flow_impact = 5.0
        else:
            flow_impact = 12.0

    transport_note = (
        "需重点确认是一艘船受阻、特定船型受限，还是整条通道大范围受限。"
        if routes
        else "需重点确认是否出现运输瓶颈、保费抬升和绕航扩散。"
    )
    second_order = [
        "高油价 -> 通胀预期抬升 -> 降息预期后移 -> 高估值科技估值承压",
        "运价/保费上升 -> 航空、化工下游、消费链利润率承压",
        "能源安全强化 -> 油气、油服、油运、军工与黄金更受关注",
    ]
    direct_beneficiaries = ["油气开采", "油服", "油运", "黄金", "军工"]
    direct_losers = ["航空", "机场", "化工下游", "高运输成本制造", "高估值科技"]
    exposed_industries = ["油气", "航运", "航空", "化工下游", "高估值科技", "可选消费"]
    if easing:
        direct_beneficiaries = ["航空修复", "出行链", "成长科技估值修复"]
        direct_losers = ["油气防御仓位", "黄金脉冲仓位"]
        exposed_industries = ["航空", "出行链", "成长科技", "油气防御仓位"]
        second_order = [
            "风险溢价回落 -> 成长和科技估值修复",
            "运价回落 -> 航空与下游制造利润压力缓解",
        ]

    return {
        "theme_key": f"commodity_supply_shock:{routes[0] if routes else 'global_energy'}",
        "event_id": f"oil-{abs(hash(title)) % 100000}",
        "title": title,
        "trigger_type": "commodity_supply_shock",
        "severity": severity,
        "peak_severity": severity,
        "trade_bias": trade_bias,
        "immediate_action": immediate_action,
        "continuity_focus": continuity,
        "transport_focus": transport_note,
        "follow_up_signal": follow_up_signal,
        "confidence_score": 54.0,
        "restriction_scope": restriction_scope,
        "estimated_flow_impact_pct": flow_impact,
        "affected_countries": countries,
        "affected_routes": routes,
        "direct_beneficiaries": direct_beneficiaries,
        "direct_losers": direct_losers,
        "exposed_industries": exposed_industries,
        "second_order_impacts": second_order,
        "commodity_links": ["原油", "天然气", "航运保险", "炼化链"],
        "evidence_count": 1,
        "source_timestamp": str(event.get("timestamp") or "") or None,
    }


def _chip_sanction_cascade(title: str, text: str, event: dict[str, Any]) -> dict[str, Any]:
    countries = _detect_countries(text)
    severe = _contains_any(text, ("禁售", "禁运", "制裁", "出口管制", "限制"))
    easing = _contains_any(text, ("豁免", "放宽", "恢复供货", "和解"))
    if severe:
        trade_bias = "增配自主可控"
        immediate_action = "增配国产替代、设备材料、关键零部件；压缩高外部依赖链。"
        severity = "critical"
        follow_up_signal = "escalating"
    elif easing:
        trade_bias = "部分兑现国产替代脉冲"
        immediate_action = "兑现纯事件脉冲，保留真业绩受益链。"
        severity = "info"
        follow_up_signal = "easing"
    else:
        trade_bias = "继续观察"
        immediate_action = "继续看清单范围、替代节奏和客户采购变化。"
        severity = "warning"
        follow_up_signal = "stable"
    return {
        "theme_key": f"technology_sanction:{'-'.join(countries[:2]) if countries else 'global'}",
        "event_id": f"chip-{abs(hash(title)) % 100000}",
        "title": title,
        "trigger_type": "technology_sanction",
        "severity": severity,
        "peak_severity": severity,
        "trade_bias": trade_bias,
        "immediate_action": immediate_action,
        "continuity_focus": "重点跟踪限制清单、替代成本、国产设备/材料渗透率和客户切换节奏。",
        "transport_focus": "不是运输问题，核心是技术封锁、采购替代和产业链利润再分配。",
        "follow_up_signal": follow_up_signal,
        "confidence_score": 56.0,
        "restriction_scope": "technology_restriction",
        "estimated_flow_impact_pct": 0.0,
        "affected_countries": countries,
        "affected_routes": [],
        "direct_beneficiaries": ["国产替代", "半导体设备材料", "自主可控软件", "安全链"],
        "direct_losers": ["高外部依赖芯片链", "被限制的海外供应链映射"],
        "exposed_industries": ["半导体", "设备材料", "软件", "服务器"],
        "second_order_impacts": [
            "限制升级 -> 国产替代斜率提升 -> 设备/材料/设计链估值重构",
            "限制缓和 -> 纯主题溢价回落，回到业绩兑现和份额增长",
        ],
        "commodity_links": ["芯片", "设备", "材料", "EDA/IP"],
        "evidence_count": 1,
        "source_timestamp": str(event.get("timestamp") or "") or None,
    }


def _ai_breakthrough_cascade(title: str, text: str, event: dict[str, Any]) -> dict[str, Any]:
    if _contains_any(text, ("量产", "订单", "交付", "签约", "资本开支", "扩产")):
        follow_up_signal = "confirming"
    else:
        follow_up_signal = "stable"
    subtheme = "ai_compute"
    if _contains_any(text, ("机器人", "无人", "自动化")):
        subtheme = "robotics"
    elif _contains_any(text, ("电力", "储能", "电网")):
        subtheme = "power"
    elif _contains_any(text, ("光模块", "交换机", "网络", "卫星")):
        subtheme = "network"
    return {
        "theme_key": f"technology_breakthrough:{subtheme}",
        "event_id": f"ai-{abs(hash(title)) % 100000}",
        "title": title,
        "trigger_type": "technology_breakthrough",
        "severity": "info",
        "peak_severity": "info",
        "trade_bias": "沿技术扩散链跟踪",
        "immediate_action": "优先看算力、电力、网络、软件应用里真正能吃到资本开支和订单的环节。",
        "continuity_focus": "确认突破是否进入资本开支、采购、交付和业绩验证，不要只交易标题。",
        "transport_focus": "核心不是运输，而是算力、电力、设备、软件渗透率扩散。",
        "follow_up_signal": follow_up_signal,
        "confidence_score": 52.0,
        "restriction_scope": "technology_diffusion",
        "estimated_flow_impact_pct": 0.0,
        "affected_countries": _detect_countries(text),
        "affected_routes": [],
        "direct_beneficiaries": ["AI算力", "半导体", "电力设备", "光模块/网络", "软件应用"],
        "direct_losers": ["纯概念映射", "无法兑现订单的高估值票"],
        "exposed_industries": ["AI算力", "半导体", "电力设备", "软件应用"],
        "second_order_impacts": [
            "技术突破 -> 资本开支上修 -> 上游设备和电力链先受益",
            "突破若缺订单验证 -> 只能做短脉冲，不是长期重估",
        ],
        "commodity_links": ["算力", "电力", "服务器", "网络设备"],
        "evidence_count": 1,
        "source_timestamp": str(event.get("timestamp") or "") or None,
    }


def build_event_cascades(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_cascades: list[dict[str, Any]] = []
    for event in events[:36]:
        if not isinstance(event, dict):
            continue
        title = str(event.get("title") or "").strip()
        text = " ".join(
            [
                title,
                str(event.get("summary") or ""),
                str(event.get("strategy_implications") or ""),
                " ".join(str(item) for item in event.get("affected_sectors", []) if str(item).strip()),
            ]
        ).lower()
        category = str(event.get("category") or "").lower()
        cascade = None
        oil_terms = ("霍尔木兹", "海峡", "油轮", "原油", "油价", "天然气", "lng", "航运", "红海", "苏伊士")
        sanction_terms = ("出口管制", "制裁", "禁售", "禁运", "限制", "清单", "管制", "eda")
        ai_terms = ("ai", "人工智能", "算力", "模型", "机器人", "量产", "突破", "脑机接口")

        has_oil_signal = _contains_any(text, oil_terms) or category in {"commodity", "geopolitical"}
        has_sanction_signal = _contains_any(text, sanction_terms)
        has_ai_signal = _contains_any(text, ai_terms)

        if has_oil_signal:
            cascade = _oil_cascade(title, text, event)
        elif has_ai_signal and not has_sanction_signal:
            cascade = _ai_breakthrough_cascade(title, text, event)
        elif has_sanction_signal or category == "trade":
            cascade = _chip_sanction_cascade(title, text, event)
        elif has_ai_signal or category == "tech":
            cascade = _ai_breakthrough_cascade(title, text, event)
        if cascade is not None:
            cascade["impact_magnitude"] = _to_float(event.get("impact_magnitude")) or 0.0
            raw_cascades.append(cascade)

    clusters: dict[str, list[dict[str, Any]]] = {}
    for item in raw_cascades:
        theme_key = str(item.get("theme_key") or item.get("event_id") or "").strip()
        if not theme_key:
            theme_key = f"theme:{len(clusters) + 1}"
        clusters.setdefault(theme_key, []).append(item)

    cascades = [_aggregate_cascade_cluster(cluster) for cluster in clusters.values()]
    cascades.sort(
        key=lambda item: (
            {"critical": 0, "warning": 1, "info": 2}.get(str(item.get("severity") or "info"), 2),
            {"escalating": 0, "confirming": 1, "stable": 2, "mixed": 3, "easing": 4}.get(str(item.get("follow_up_signal") or "stable"), 2),
            -(float(item.get("confidence_score") or 0.0)),
            -float(item.get("impact_magnitude") or 0.0),
        )
    )
    return cascades[:5]
