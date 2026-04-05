from __future__ import annotations

from typing import Any


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


_COUNTRY_REGION_MAP = {
    "伊朗": "中东",
    "沙特": "中东",
    "阿联酋": "中东",
    "以色列": "中东",
    "美国": "北美",
    "中国": "东亚",
    "日本": "东亚",
    "韩国": "东亚",
    "印度": "南亚",
    "欧洲": "欧洲",
    "欧盟": "欧洲",
    "俄罗斯": "俄欧链",
}


def _region_for_country(country: str) -> str:
    return _COUNTRY_REGION_MAP.get(country, "全球")


def _find_macro_score(instruments: list[dict[str, Any]], key: str, default: float = 50.0) -> float:
    for item in instruments:
        if str(item.get("key") or "").strip() == key:
            return _clamp(_to_float(item.get("score")) or default, 0.0, 100.0)
    return default


def build_cross_asset_signals_and_regions(
    *,
    macro_rates_fx: dict[str, Any],
    commodity_terminal: dict[str, Any],
    shipping_ais: dict[str, Any],
    freight_rates: dict[str, Any],
    official_fulltext: dict[str, Any],
    event_cascades: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    instruments = macro_rates_fx.get("instruments", []) if isinstance(macro_rates_fx.get("instruments"), list) else []
    commodities = commodity_terminal.get("commodities", []) if isinstance(commodity_terminal.get("commodities"), list) else []
    routes = shipping_ais.get("routes", []) if isinstance(shipping_ais.get("routes"), list) else []
    lanes = freight_rates.get("lanes", []) if isinstance(freight_rates.get("lanes"), list) else []
    documents = official_fulltext.get("documents", []) if isinstance(official_fulltext.get("documents"), list) else []

    risk_appetite = _find_macro_score(instruments, "ca_risk_appetite")
    us_momentum = _find_macro_score(instruments, "ca_us_momentum")
    vix_level = _find_macro_score(instruments, "ca_vix_level")
    a50_premium = _find_macro_score(instruments, "ca_a50_premium")
    hk_sentiment = _find_macro_score(instruments, "ca_hk_sentiment")

    max_flow_impact = max((_to_float(item.get("estimated_flow_impact_pct")) or 0.0) for item in routes) if routes else 0.0
    max_freight_pressure = 0.0
    for lane in lanes:
        change = abs(_to_float(lane.get("rate_change_pct_1d")) or 0.0)
        insurance = _to_float(lane.get("insurance_premium_bp")) or 0.0
        max_freight_pressure = max(max_freight_pressure, change * 3.0 + insurance * 0.25)
    shipping_pressure = _clamp(max_flow_impact * 0.8 + max_freight_pressure, 0.0, 100.0)

    commodity_pressure = 0.0
    energy_focus = 0.0
    for item in commodities:
        change_1d = abs(_to_float(item.get("change_pct_1d")) or 0.0)
        change_5d = abs(_to_float(item.get("change_pct_5d")) or 0.0)
        pressure_level = str(item.get("pressure_level") or "normal")
        bonus = 0.0
        if pressure_level == "critical":
            bonus = 18.0
        elif pressure_level == "warning":
            bonus = 10.0
        score = change_1d * 5.0 + change_5d * 2.0 + bonus
        commodity_pressure = max(commodity_pressure, score)
        name = str(item.get("name") or "").lower()
        if any(token in name for token in ("原油", "天然气", "lng", "煤", "油")):
            energy_focus = max(energy_focus, score)
    commodity_pressure = _clamp(commodity_pressure, 0.0, 100.0)
    energy_focus = _clamp(energy_focus or commodity_pressure, 0.0, 100.0)

    official_confirm_score = _clamp(len(documents) * 6.5, 0.0, 100.0)

    signals: list[dict[str, Any]] = []
    regional: dict[str, dict[str, Any]] = {}

    macro_bias = "risk_off" if risk_appetite <= 42.0 else "risk_on" if risk_appetite >= 62.0 else "neutral"
    signals.append(
        {
            "key": "macro_risk",
            "label": "全球风险偏好",
            "level": "warning" if macro_bias == "risk_off" else "info",
            "score": round(risk_appetite, 1),
            "bias": macro_bias,
            "summary": (
                f"当前全球风险偏好 {risk_appetite:.1f} 分，"
                f"美股动量 {us_momentum:.1f} / VIX 风险偏好 {vix_level:.1f} / A50 {a50_premium:.1f} / 港股 {hk_sentiment:.1f}。"
            ),
            "action_type": "reduce" if macro_bias == "risk_off" else "add" if macro_bias == "risk_on" else "observe",
            "targets": ["高 beta 成长", "高股息防御"] if macro_bias == "risk_off" else ["成长主线", "科技龙头"],
            "source_keys": ["macro_rates_fx"],
        }
    )

    if shipping_pressure > 0:
        signals.append(
            {
                "key": "shipping_pressure",
                "label": "航运与运力扰动",
                "level": "critical" if shipping_pressure >= 68.0 else "warning" if shipping_pressure >= 42.0 else "info",
                "score": round(shipping_pressure, 1),
                "bias": "stress" if shipping_pressure >= 42.0 else "monitor",
                "summary": f"当前航运/AIS 与运价合成压力 {shipping_pressure:.1f} 分，重点看通道限制、保费和绕航扩散。",
                "action_type": "add" if shipping_pressure >= 42.0 else "observe",
                "targets": ["油运", "能源安全", "航空下游风险"],
                "source_keys": ["shipping_ais", "freight_rates"],
            }
        )

    if commodity_pressure > 0:
        signals.append(
            {
                "key": "commodity_pressure",
                "label": "商品与通胀传导",
                "level": "warning" if commodity_pressure >= 48.0 else "info",
                "score": round(commodity_pressure, 1),
                "bias": "inflation_up" if energy_focus >= 42.0 else "mixed",
                "summary": f"当前商品终端合成压力 {commodity_pressure:.1f} 分，能源敏感链需要先看成本转嫁和估值压制。",
                "action_type": "reduce" if energy_focus >= 42.0 else "observe",
                "targets": ["高估值成长", "航空", "化工下游", "资源链"],
                "source_keys": ["commodity_terminal"],
            }
        )

    if official_confirm_score > 0:
        signals.append(
            {
                "key": "official_confirm",
                "label": "官方原文确认",
                "level": "info",
                "score": round(official_confirm_score, 1),
                "bias": "confirmed" if official_confirm_score >= 42.0 else "early",
                "summary": f"当前官方全文/原文确认强度 {official_confirm_score:.1f} 分，优先沿有权威原文支撑的方向布局。",
                "action_type": "add" if official_confirm_score >= 42.0 else "observe",
                "targets": ["政策主线", "预算兑现链"],
                "source_keys": ["official_fulltext"],
            }
        )

    for cascade in event_cascades[:16]:
        if not isinstance(cascade, dict):
            continue
        severity = str(cascade.get("severity") or "info")
        level = {"critical": "critical", "warning": "warning"}.get(severity, "info")
        impact = _to_float(cascade.get("estimated_flow_impact_pct")) or 0.0
        route_names = [str(item).strip() for item in cascade.get("affected_routes", []) if str(item).strip()]
        industries = [str(item).strip() for item in cascade.get("exposed_industries", []) if str(item).strip()]
        for country in cascade.get("affected_countries", []) if isinstance(cascade.get("affected_countries"), list) else []:
            name = str(country).strip()
            if not name:
                continue
            region = _region_for_country(name)
            bucket = regional.setdefault(
                region,
                {
                    "region": region,
                    "level": level,
                    "score": 0.0,
                    "summary": "",
                    "affected_countries": [],
                    "affected_routes": [],
                    "exposed_industries": [],
                },
            )
            bucket["score"] = max(float(bucket["score"]), 36.0 + impact * 0.6)
            if level == "critical":
                bucket["level"] = "critical"
            elif bucket["level"] != "critical" and level == "warning":
                bucket["level"] = "warning"
            if name not in bucket["affected_countries"]:
                bucket["affected_countries"].append(name)
            for route in route_names:
                if route not in bucket["affected_routes"]:
                    bucket["affected_routes"].append(route)
            for industry in industries:
                if industry not in bucket["exposed_industries"]:
                    bucket["exposed_industries"].append(industry)

    region_list: list[dict[str, Any]] = []
    for item in regional.values():
        item["score"] = round(_clamp(float(item["score"]), 0.0, 100.0), 1)
        item["summary"] = (
            f"{item['region']} 当前受事件与跨资产扰动影响较大，"
            f"重点看 {' / '.join(item['affected_routes'][:2]) or '关键通道'} 和 {' / '.join(item['exposed_industries'][:3]) or '敏感行业'}。"
        )
        region_list.append(item)

    signals.sort(key=lambda item: (-float(item["score"]), item["label"]))
    region_list.sort(key=lambda item: (-float(item["score"]), item["region"]))
    return {
        "signals": signals[:6],
        "regional_pressures": region_list[:5],
    }
