from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from json_store import safe_load, safe_save

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT_DIR)))

NEWS_DIGEST = DATA_DIR / "news_digest.json"
POLICY_OFFICIAL_INGEST = DATA_DIR / "policy_official_ingest.json"
WORLD_OFFICIAL_FULLTEXT = DATA_DIR / "world_official_fulltext.json"
WORLD_SHIPPING_AIS = DATA_DIR / "world_shipping_ais.json"
WORLD_FREIGHT_RATES = DATA_DIR / "world_freight_rates.json"
WORLD_COMMODITY_TERMINAL = DATA_DIR / "world_commodity_terminal.json"
WORLD_MACRO_RATES_FX = DATA_DIR / "world_macro_rates_fx.json"

_SOURCE_PATHS = {
    "official_fulltext": WORLD_OFFICIAL_FULLTEXT,
    "shipping_ais": WORLD_SHIPPING_AIS,
    "freight_rates": WORLD_FREIGHT_RATES,
    "commodity_terminal": WORLD_COMMODITY_TERMINAL,
    "macro_rates_fx": WORLD_MACRO_RATES_FX,
}

_SOURCE_ENVS = {
    "official_fulltext": "WORLD_OFFICIAL_FULLTEXT_URL",
    "shipping_ais": "WORLD_SHIPPING_AIS_URL",
    "freight_rates": "WORLD_FREIGHT_RATES_URL",
    "commodity_terminal": "WORLD_COMMODITY_TERMINAL_URL",
    "macro_rates_fx": "WORLD_MACRO_RATES_FX_URL",
}

_GATEWAY_PATHS = {
    "official_fulltext": "/api/world-gateway/official-fulltext",
    "shipping_ais": "/api/world-gateway/shipping-ais",
    "freight_rates": "/api/world-gateway/freight-rates",
    "commodity_terminal": "/api/world-gateway/commodity-terminal",
    "macro_rates_fx": "/api/world-gateway/macro-rates-fx",
}

_SOURCE_TOKEN_ENVS = {
    "official_fulltext": "WORLD_OFFICIAL_FULLTEXT_TOKEN",
    "shipping_ais": "WORLD_SHIPPING_AIS_TOKEN",
    "freight_rates": "WORLD_FREIGHT_RATES_TOKEN",
    "commodity_terminal": "WORLD_COMMODITY_TERMINAL_TOKEN",
    "macro_rates_fx": "WORLD_MACRO_RATES_FX_TOKEN",
}

_USER_AGENT = "AlphaAI-WorldModel/1.0"


def _iso_now(now: datetime | None = None) -> str:
    return (now or datetime.now()).isoformat(timespec="seconds")


def _safe_load_dict(path: Path) -> dict[str, Any]:
    payload = safe_load(str(path), default={})
    return payload if isinstance(payload, dict) else {}


def _safe_load_list(path: Path) -> list[dict[str, Any]]:
    payload = safe_load(str(path), default=[])
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _strip_html(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text)
    return " ".join(cleaned.split())


def _build_remote_headers(source_key: str) -> dict[str, str]:
    headers = {"User-Agent": _USER_AGENT}
    token = (
        os.environ.get(_SOURCE_TOKEN_ENVS.get(source_key, ""), "").strip()
        or os.environ.get("WORLD_HARD_SOURCE_AUTH_TOKEN", "").strip()
        or os.environ.get("WORLD_DATA_GATEWAY_TOKEN", "").strip()
    )
    if not token:
        return headers

    header_name = (
        os.environ.get(f"{source_key.upper()}_AUTH_HEADER", "").strip()
        or os.environ.get("WORLD_HARD_SOURCE_AUTH_HEADER", "").strip()
        or "Authorization"
    )
    header_value = token
    if header_name.lower() == "authorization" and not token.lower().startswith("bearer "):
        header_value = f"Bearer {token}"
    headers[header_name] = header_value
    return headers


def _resolve_remote_url(source_key: str) -> str | None:
    explicit_url = os.environ.get(_SOURCE_ENVS[source_key], "").strip()
    if explicit_url:
        return explicit_url
    gateway_base_url = os.environ.get("WORLD_DATA_GATEWAY_BASE_URL", "").strip().rstrip("/")
    if gateway_base_url:
        return f"{gateway_base_url}{_GATEWAY_PATHS[source_key]}"
    return None


def _fetch_remote_payload(url: str, *, timeout: int = 12, headers: dict[str, str] | None = None) -> tuple[object | None, str]:
    request_headers = {"User-Agent": _USER_AGENT}
    if isinstance(headers, dict):
        request_headers.update({str(key): str(value) for key, value in headers.items() if str(key).strip() and str(value).strip()})
    request = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        raw = response.read()
    decoded = raw.decode("utf-8", errors="ignore")
    if "json" in content_type.lower() or url.lower().endswith(".json"):
        try:
            return json.loads(decoded), "remote_json"
        except json.JSONDecodeError:
            return None, "remote_json"
    return decoded, "remote_text"


def _normalize_official_documents(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        raw_items = payload.get("documents") or payload.get("items") or payload.get("entries") or []
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raw_items = []
    documents: list[dict[str, Any]] = []
    for raw in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or raw.get("name") or "").strip()
        source = str(raw.get("source") or raw.get("issuer") or raw.get("department") or "").strip()
        content = _strip_html(str(raw.get("content") or raw.get("body") or raw.get("excerpt") or ""))
        published_at = str(raw.get("published_at") or raw.get("timestamp") or raw.get("date") or "").strip() or None
        if not title:
            continue
        documents.append(
            {
                "title": title,
                "source": source or "外部官方源",
                "published_at": published_at,
                "excerpt": content[:240],
                "reference_url": str(raw.get("reference_url") or raw.get("url") or "").strip() or None,
                "keywords": [str(item).strip() for item in raw.get("keywords", []) if str(item).strip()],
                "affected_directions": [str(item).strip() for item in raw.get("affected_directions", []) if str(item).strip()],
                "affected_regions": [str(item).strip() for item in raw.get("affected_regions", []) if str(item).strip()],
                "source_origin": "remote",
            }
        )
    return documents[:80]


def _fallback_official_documents() -> list[dict[str, Any]]:
    ingest = _safe_load_dict(POLICY_OFFICIAL_INGEST)
    directions = ingest.get("directions", []) if isinstance(ingest.get("directions"), list) else []
    documents: list[dict[str, Any]] = []
    for direction in directions:
        if not isinstance(direction, dict):
            continue
        direction_name = str(direction.get("direction") or "").strip()
        for raw in direction.get("official_source_entries", []) if isinstance(direction.get("official_source_entries"), list) else []:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or "").strip()
            if not title:
                continue
            documents.append(
                {
                    "title": title,
                    "source": str(raw.get("issuer") or "").strip() or "官方口径",
                    "published_at": str(raw.get("published_at") or "").strip() or None,
                    "excerpt": str(raw.get("excerpt") or "").strip(),
                    "reference_url": str(raw.get("reference_url") or "").strip() or None,
                    "keywords": [str(item).strip() for item in raw.get("watch_tags", []) if str(item).strip()],
                    "affected_directions": [direction_name] if direction_name else [],
                    "affected_regions": [],
                    "source_origin": "derived",
                }
            )
    return documents[:80]


def _normalize_shipping_routes(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        raw_items = payload.get("routes") or payload.get("items") or payload.get("alerts") or []
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raw_items = []
    routes: list[dict[str, Any]] = []
    for raw in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(raw, dict):
            continue
        route = str(raw.get("route") or raw.get("name") or raw.get("corridor") or "").strip()
        if not route:
            continue
        routes.append(
            {
                "route": route,
                "restriction_scope": str(raw.get("restriction_scope") or raw.get("status") or "normal").strip() or "normal",
                "estimated_flow_impact_pct": max(0.0, min(100.0, _to_float(raw.get("estimated_flow_impact_pct")) or _to_float(raw.get("flow_impact_pct")) or 0.0)),
                "allowed_vessels": [str(item).strip() for item in raw.get("allowed_vessels", []) if str(item).strip()],
                "blocked_vessels": [str(item).strip() for item in raw.get("blocked_vessels", []) if str(item).strip()],
                "affected_countries": [str(item).strip() for item in raw.get("affected_countries", []) if str(item).strip()],
                "notes": str(raw.get("notes") or raw.get("summary") or "").strip(),
                "source_origin": "remote",
            }
        )
    return routes[:48]


def _fallback_shipping_routes() -> list[dict[str, Any]]:
    digest = _safe_load_dict(NEWS_DIGEST)
    events = digest.get("events", []) if isinstance(digest.get("events"), list) else []
    try:
        from world_event_cascade import build_event_cascades

        cascades = build_event_cascades(events)
    except Exception:
        cascades = []
    routes: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in cascades:
        if not isinstance(item, dict):
            continue
        if str(item.get("trigger_type") or "") != "commodity_supply_shock":
            continue
        restriction_scope = str(item.get("restriction_scope") or "normal")
        for route in item.get("affected_routes", []) if isinstance(item.get("affected_routes"), list) else []:
            route_name = str(route).strip()
            if not route_name:
                continue
            key = (route_name, restriction_scope)
            if key in seen:
                continue
            seen.add(key)
            routes.append(
                {
                    "route": route_name,
                    "restriction_scope": restriction_scope,
                    "estimated_flow_impact_pct": max(0.0, min(100.0, _to_float(item.get("estimated_flow_impact_pct")) or 0.0)),
                    "allowed_vessels": [],
                    "blocked_vessels": [],
                    "affected_countries": [str(v).strip() for v in item.get("affected_countries", []) if str(v).strip()],
                    "notes": str(item.get("transport_focus") or "").strip(),
                    "source_origin": "derived",
                }
            )
    return routes[:48]


def _normalize_freight_lanes(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        raw_items = payload.get("lanes") or payload.get("items") or payload.get("indexes") or []
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raw_items = []
    lanes: list[dict[str, Any]] = []
    for raw in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(raw, dict):
            continue
        route = str(raw.get("route") or raw.get("lane") or raw.get("name") or "").strip()
        if not route:
            continue
        lanes.append(
            {
                "route": route,
                "pressure_level": str(raw.get("pressure_level") or raw.get("status") or "normal").strip() or "normal",
                "rate_change_pct_1d": _to_float(raw.get("rate_change_pct_1d")) or _to_float(raw.get("change_pct")) or 0.0,
                "insurance_premium_bp": _to_float(raw.get("insurance_premium_bp")) or 0.0,
                "tanker_bias": str(raw.get("tanker_bias") or raw.get("bias") or "").strip() or None,
                "notes": str(raw.get("notes") or raw.get("summary") or "").strip(),
                "source_origin": "remote",
            }
        )
    return lanes[:48]


def _fallback_freight_lanes(shipping_routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lanes: list[dict[str, Any]] = []
    for route in shipping_routes[:24]:
        impact = max(0.0, min(100.0, _to_float(route.get("estimated_flow_impact_pct")) or 0.0))
        pressure = "normal"
        if impact >= 60:
            pressure = "critical"
        elif impact >= 25:
            pressure = "warning"
        lanes.append(
            {
                "route": str(route.get("route") or "").strip(),
                "pressure_level": pressure,
                "rate_change_pct_1d": round(impact * 0.18, 1),
                "insurance_premium_bp": round(impact * 1.2, 1),
                "tanker_bias": "up" if impact >= 20 else "flat",
                "notes": str(route.get("notes") or "").strip(),
                "source_origin": "derived",
            }
        )
    return lanes[:48]


def _normalize_commodities(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        raw_items = payload.get("commodities") or payload.get("items") or payload.get("contracts") or []
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raw_items = []
    items: list[dict[str, Any]] = []
    for raw in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("commodity") or raw.get("symbol") or "").strip()
        if not name:
            continue
        items.append(
            {
                "name": name,
                "price": _to_float(raw.get("price")) or 0.0,
                "change_pct_1d": _to_float(raw.get("change_pct_1d")) or _to_float(raw.get("change_pct")) or 0.0,
                "change_pct_5d": _to_float(raw.get("change_pct_5d")) or 0.0,
                "pressure_level": str(raw.get("pressure_level") or raw.get("status") or "normal").strip() or "normal",
                "downstream_industries": [str(item).strip() for item in raw.get("downstream_industries", []) if str(item).strip()],
                "source_origin": "remote",
            }
        )
    return items[:64]


def _fallback_commodities() -> list[dict[str, Any]]:
    digest = _safe_load_dict(NEWS_DIGEST)
    events = digest.get("events", []) if isinstance(digest.get("events"), list) else []
    try:
        from world_event_cascade import build_event_cascades

        cascades = build_event_cascades(events)
    except Exception:
        cascades = []
    commodity_map: dict[str, dict[str, Any]] = {}
    for cascade in cascades:
        if not isinstance(cascade, dict):
            continue
        names = cascade.get("commodity_links", []) if isinstance(cascade.get("commodity_links"), list) else []
        for name in names:
            commodity = str(name).strip()
            if not commodity:
                continue
            current = commodity_map.setdefault(
                commodity,
                {
                    "name": commodity,
                    "price": 0.0,
                    "change_pct_1d": 0.0,
                    "change_pct_5d": 0.0,
                    "pressure_level": "normal",
                    "downstream_industries": [],
                    "source_origin": "derived",
                },
            )
            impact = max(0.0, min(100.0, _to_float(cascade.get("estimated_flow_impact_pct")) or 0.0))
            current["change_pct_1d"] = max(float(current["change_pct_1d"]), round(impact * 0.14, 1))
            current["change_pct_5d"] = max(float(current["change_pct_5d"]), round(impact * 0.28, 1))
            if impact >= 55:
                current["pressure_level"] = "critical"
            elif impact >= 20 and current["pressure_level"] != "critical":
                current["pressure_level"] = "warning"
            current["downstream_industries"] = sorted(
                set(current["downstream_industries"]) | {str(item).strip() for item in cascade.get("exposed_industries", []) if str(item).strip()}
            )[:6]
    return list(commodity_map.values())[:64]


def _normalize_macro_instruments(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        raw_items = payload.get("instruments") or payload.get("items") or payload.get("factors") or []
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raw_items = []
    instruments: list[dict[str, Any]] = []
    for raw in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("key") or raw.get("symbol") or raw.get("name") or "").strip()
        if not key:
            continue
        instruments.append(
            {
                "key": key,
                "label": str(raw.get("label") or raw.get("name") or key).strip() or key,
                "category": str(raw.get("category") or "macro").strip() or "macro",
                "value": _to_float(raw.get("value")) or 0.0,
                "score": _to_float(raw.get("score")) or 50.0,
                "bias": str(raw.get("bias") or "neutral").strip() or "neutral",
                "change_pct_1d": _to_float(raw.get("change_pct_1d")) or _to_float(raw.get("change_pct")) or 0.0,
                "summary": str(raw.get("summary") or "").strip(),
                "source_origin": "remote",
            }
        )
    return instruments[:48]


def _fallback_macro_instruments() -> list[dict[str, Any]]:
    instruments: list[dict[str, Any]] = []
    try:
        from cross_asset_factor import get_cross_asset_status

        status = get_cross_asset_status()
        today = status.get("today") if isinstance(status, dict) else None
    except Exception:
        today = None

    defaults = {
        "ca_us_momentum": 0.5,
        "ca_btc_trend": 0.5,
        "ca_a50_premium": 0.5,
        "ca_vix_level": 0.5,
        "ca_hk_sentiment": 0.5,
        "ca_risk_appetite": 0.5,
    }
    payload = defaults | (today if isinstance(today, dict) else {})
    labels = {
        "ca_us_momentum": "美股动量",
        "ca_btc_trend": "BTC 趋势",
        "ca_a50_premium": "A50 溢价",
        "ca_vix_level": "VIX 风险偏好",
        "ca_hk_sentiment": "港股情绪",
        "ca_risk_appetite": "全球风险偏好",
    }
    categories = {
        "ca_us_momentum": "equity",
        "ca_btc_trend": "crypto",
        "ca_a50_premium": "china_equity",
        "ca_vix_level": "volatility",
        "ca_hk_sentiment": "equity",
        "ca_risk_appetite": "macro",
    }
    for key, default_value in defaults.items():
        value = _to_float(payload.get(key))
        if value is None:
            value = default_value
        score = round(max(0.0, min(100.0, value * 100.0)), 1)
        bias = "neutral"
        if key == "ca_vix_level":
            bias = "risk_on" if value >= 0.65 else "risk_off" if value <= 0.35 else "neutral"
        else:
            bias = "up" if value >= 0.58 else "down" if value <= 0.42 else "neutral"
        instruments.append(
            {
                "key": key,
                "label": labels[key],
                "category": categories[key],
                "value": value,
                "score": score,
                "bias": bias,
                "change_pct_1d": 0.0,
                "summary": f"{labels[key]} 当前得分 {score:.1f}。",
                "source_origin": "derived",
            }
        )
    return instruments


def _build_payload(key: str, items: list[dict[str, Any]], *, now: datetime, fetch_mode: str, remote_url: str | None) -> dict[str, Any]:
    plural_key = {
        "official_fulltext": "documents",
        "shipping_ais": "routes",
        "freight_rates": "lanes",
        "commodity_terminal": "commodities",
        "macro_rates_fx": "instruments",
    }[key]
    summary = {
        "official_fulltext": f"官方全文 {len(items)} 篇，优先读取权威原文和全文上下文。",
        "shipping_ais": f"航运/AIS {len(items)} 条，关注通道限制、船型和流量影响。",
        "freight_rates": f"运价/保险 {len(items)} 条，关注运价和保费是否继续扩散。",
        "commodity_terminal": f"商品终端 {len(items)} 条，关注资源价格对产业链和估值的传导。",
        "macro_rates_fx": f"宏观利率汇率 {len(items)} 条，关注全球风险偏好和跨资产切换。",
    }[key]
    return {
        "source_key": key,
        "updated_at": _iso_now(now),
        "fetch_mode": fetch_mode,
        "remote_url": remote_url,
        "remote_configured": bool(remote_url),
        "degraded_to_derived": bool(remote_url) and fetch_mode in {"derived", "remote_failed_fallback"},
        "origin_mode": (
            "remote_live"
            if fetch_mode.startswith("remote_") and fetch_mode != "remote_failed_fallback"
            else "derived_fallback"
            if fetch_mode == "remote_failed_fallback"
            else "derived"
        ),
        "summary": summary,
        plural_key: items,
    }


def refresh_world_hard_sources(now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now()
    results: dict[str, Any] = {}
    official_documents: list[dict[str, Any]] = []
    shipping_routes: list[dict[str, Any]] = []

    for key in ("official_fulltext", "shipping_ais", "freight_rates", "commodity_terminal", "macro_rates_fx"):
        remote_url = _resolve_remote_url(key)
        fetch_mode = "derived"
        payload: object | None = None
        if remote_url:
            try:
                payload, fetch_mode = _fetch_remote_payload(remote_url, headers=_build_remote_headers(key))
            except (urllib.error.URLError, TimeoutError, ValueError):
                payload = None
                fetch_mode = "remote_failed_fallback"

        if key == "official_fulltext":
            items = _normalize_official_documents(payload) if payload is not None else []
            if not items:
                items = _fallback_official_documents()
            official_documents = items
        elif key == "shipping_ais":
            items = _normalize_shipping_routes(payload) if payload is not None else []
            if not items:
                items = _fallback_shipping_routes()
            shipping_routes = items
        elif key == "freight_rates":
            items = _normalize_freight_lanes(payload) if payload is not None else []
            if not items:
                items = _fallback_freight_lanes(shipping_routes or _fallback_shipping_routes())
        elif key == "commodity_terminal":
            items = _normalize_commodities(payload) if payload is not None else []
            if not items:
                items = _fallback_commodities()
        else:
            items = _normalize_macro_instruments(payload) if payload is not None else []
            if not items:
                items = _fallback_macro_instruments()

        out = _build_payload(key, items, now=now, fetch_mode=fetch_mode, remote_url=remote_url)
        safe_save(str(_SOURCE_PATHS[key]), out)
        results[f"{key}_count"] = len(items)

    results["updated_at"] = _iso_now(now)
    results["official_document_count"] = len(official_documents)
    results["shipping_route_count"] = len(shipping_routes)
    return results


def ensure_world_hard_sources_fresh(max_age_hours: int = 6) -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    now = datetime.now()
    refreshed = False
    for key, path in _SOURCE_PATHS.items():
        payload = _safe_load_dict(path)
        updated_at = str(payload.get("updated_at") or "").strip()
        if not updated_at:
            refresh_world_hard_sources(now)
            refreshed = True
            break
        try:
            updated = datetime.fromisoformat(updated_at)
        except ValueError:
            refresh_world_hard_sources(now)
            refreshed = True
            break
        age_hours = max(0.0, (now - updated).total_seconds() / 3600.0)
        if age_hours > max_age_hours:
            refresh_world_hard_sources(now)
            refreshed = True
            break
    return refreshed
