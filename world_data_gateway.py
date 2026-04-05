from __future__ import annotations

import os
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Optional

import akshare as ak
from fastapi import Depends, FastAPI, Header, HTTPException

import world_hard_source_feeds as feeds

app = FastAPI(
    title="AlphaAI World Data Gateway",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)


_PLURAL_KEYS = {
    "official_fulltext": "documents",
    "shipping_ais": "routes",
    "freight_rates": "lanes",
    "commodity_terminal": "commodities",
    "macro_rates_fx": "instruments",
}

_PUBLIC_REQUEST_HEADERS = {
    "User-Agent": "AlphaAI-WorldGateway/1.0",
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
}

_CHINAMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/61.0.3163.91 Safari/537.36",
}

_EASTMONEY_MACRO_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_EASTMONEY_FUTURES_URL = "https://futsseapi.eastmoney.com/list/COMEX,NYMEX,COBOT,SGX,NYBOT,LME,MDEX,TOCOM,IPE"
_CHINAMONEY_FX_URL = "http://www.chinamoney.com.cn/r/cms/www/chinamoney/data/fx/rfx-sp-quot.json"

_SHIPPING_INDICATORS = {
    "波罗的海综合运价指数BDI": "EMI00107664",
    "巴拿马型运费指数BPI": "EMI00107665",
    "海岬型运费指数BCI": "EMI00107666",
    "成品油运输指数BCTI": "EMI00107669",
}

_COMMODITY_NAME_HINTS = ("原油", "布伦特", "WTI", "天然气", "黄金", "铜", "白银")

_MACRO_PAIR_HINTS = {
    "美元/人民币": "usd_cny",
    "欧元/人民币": "eur_cny",
    "100日元/人民币": "jpy_cny",
    "港币/人民币": "hkd_cny",
    "英镑/人民币": "gbp_cny",
}


def _gateway_token() -> str:
    return os.environ.get("WORLD_DATA_GATEWAY_TOKEN", "").strip()


def _gateway_enabled() -> bool:
    return bool(_gateway_token())


def _ensure_gateway_access(
    authorization: Optional[str] = Header(default=None),
    x_world_gateway_token: Optional[str] = Header(default=None),
) -> None:
    configured_token = _gateway_token()
    if not configured_token:
        return
    bearer_token = ""
    if authorization and authorization.lower().startswith("bearer "):
        bearer_token = authorization.split(" ", 1)[1].strip()
    candidate = x_world_gateway_token or bearer_token
    if candidate != configured_token:
        raise HTTPException(status_code=401, detail="invalid world data gateway token")


def _cached_or_fallback_payload(source_key: str) -> dict[str, Any]:
    public_live = _public_live_payload(source_key)
    if public_live is not None:
        return public_live

    path = feeds._SOURCE_PATHS[source_key]
    cached = feeds._safe_load_dict(path)
    plural_key = _PLURAL_KEYS[source_key]
    existing_items = cached.get(plural_key)
    if isinstance(existing_items, list) and existing_items:
        return cached

    now = datetime.now()
    if source_key == "official_fulltext":
        items = feeds._fallback_official_documents()
    elif source_key == "shipping_ais":
        items = feeds._fallback_shipping_routes()
    elif source_key == "freight_rates":
        items = feeds._fallback_freight_lanes(feeds._fallback_shipping_routes())
    elif source_key == "commodity_terminal":
        items = feeds._fallback_commodities()
    else:
        items = feeds._fallback_macro_instruments()
    return feeds._build_payload(source_key, items, now=now, fetch_mode="derived", remote_url=None)


def _http_request_json(url: str, *, params: dict[str, Any] | None = None, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: float = 2.0) -> Any:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request_headers = dict(_PUBLIC_REQUEST_HEADERS)
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, data=data, headers=request_headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="ignore"))


def _http_request_text(url: str, *, headers: dict[str, str] | None = None, timeout: float = 2.0) -> str:
    request_headers = dict(_PUBLIC_REQUEST_HEADERS)
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def _safe_float(value: Any) -> float | None:
    if value in (None, "", "---", "--", "N/A", "nan"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except Exception:
        return None


def _eastmoney_macro_series(indicator_id: str) -> list[dict[str, Any]]:
    payload = _http_request_json(
        _EASTMONEY_MACRO_URL,
        params={
            "sortColumns": "REPORT_DATE",
            "sortTypes": "-1",
            "pageSize": "3",
            "pageNumber": "1",
            "reportName": "RPT_INDUSTRY_INDEX",
            "columns": "REPORT_DATE,INDICATOR_VALUE,CHANGE_RATE,CHANGERATE_3M,CHANGERATE_6M,CHANGERATE_1Y,CHANGERATE_2Y,CHANGERATE_3Y",
            "filter": f"(INDICATOR_ID=\"{indicator_id}\")",
            "source": "WEB",
            "client": "WEB",
        },
    )
    result = payload.get("result", {}) if isinstance(payload, dict) else {}
    data = result.get("data", []) if isinstance(result, dict) else []
    return [item for item in data if isinstance(item, dict)]


def _public_live_shipping_or_freight() -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    routes: list[dict[str, Any]] = []
    lanes: list[dict[str, Any]] = []
    for name, indicator_id in _SHIPPING_INDICATORS.items():
        rows = _eastmoney_macro_series(indicator_id)
        if not rows:
            continue
        latest = rows[0]
        value = float(latest.get("INDICATOR_VALUE") or 0.0)
        change = float(latest.get("CHANGE_RATE") or 0.0)
        pressure = "normal"
        restriction_scope = "normal"
        if abs(change) >= 8:
            pressure = "critical"
            restriction_scope = "partial"
        elif abs(change) >= 3:
            pressure = "warning"
            restriction_scope = "tight"
        flow_impact = max(0.0, min(100.0, round(abs(change) * 2.5, 1)))
        routes.append(
            {
                "route": name,
                "restriction_scope": restriction_scope,
                "estimated_flow_impact_pct": flow_impact,
                "allowed_vessels": [],
                "blocked_vessels": [],
                "affected_countries": [],
                "notes": f"公开航运指数最新值 {value:.1f}，1日变化 {change:.2f}%。",
                "source_origin": "remote_public",
            }
        )
        lanes.append(
            {
                "route": name,
                "pressure_level": pressure,
                "rate_change_pct_1d": round(change, 2),
                "insurance_premium_bp": round(abs(change) * 4.0, 1),
                "tanker_bias": "up" if change >= 0 else "down",
                "notes": f"公开航运/运价指数 {name} 1日变化 {change:.2f}%。",
                "source_origin": "remote_public",
            }
        )
    if not routes and not lanes:
        return None
    return routes[:48], lanes[:48]


def _public_live_commodity_payload() -> dict[str, Any] | None:
    items = ak.futures_global_spot_em().to_dict("records")
    commodities: list[dict[str, Any]] = []
    for raw in items if isinstance(items, list) else []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("名称") or raw.get("name") or "").strip()
        if not name or not any(hint in name for hint in _COMMODITY_NAME_HINTS):
            continue
        latest = _safe_float(raw.get("最新价") or raw.get("p")) or 0.0
        change_pct = _safe_float(raw.get("涨跌幅") or raw.get("zdf")) or 0.0
        commodities.append(
            {
                "name": name,
                "price": latest,
                "change_pct_1d": change_pct,
                "change_pct_5d": change_pct,
                "pressure_level": "critical" if abs(change_pct) >= 4 else "warning" if abs(change_pct) >= 1.5 else "normal",
                "downstream_industries": [],
                "source_origin": "remote_public",
            }
        )
    if not commodities:
        return None
    return feeds._build_payload(
        "commodity_terminal",
        commodities[:64],
        now=datetime.now(),
        fetch_mode="remote_public_live",
        remote_url="akshare:futures_global_spot_em",
    )


def _public_live_macro_payload() -> dict[str, Any] | None:
    instruments: list[dict[str, Any]] = []
    try:
        fx_spot = ak.fx_spot_quote().to_dict("records")
    except Exception:
        fx_spot = []
    for raw in fx_spot if isinstance(fx_spot, list) else []:
        if not isinstance(raw, dict):
            continue
        pair = str(raw.get("货币对") or raw.get("ccyPair") or "").strip()
        if pair not in _MACRO_PAIR_HINTS:
            continue
        bid = _safe_float(raw.get("买报价") or raw.get("bidPrc"))
        ask = _safe_float(raw.get("卖报价") or raw.get("askPrc"))
        mid = (bid + ask) / 2 if bid is not None and ask is not None else bid or ask
        if mid is None:
            continue
        bias = "neutral"
        if pair == "美元/人民币":
            bias = "up" if mid >= 7.2 else "down" if mid <= 6.9 else "neutral"
        score = 50.0
        if pair == "美元/人民币":
            score = max(0.0, min(100.0, 100 - abs(mid - 7.0) * 30))
        instruments.append(
            {
                "key": _MACRO_PAIR_HINTS[pair],
                "label": pair,
                "category": "fx",
                "value": round(mid, 6),
                "score": round(score, 1),
                "bias": bias,
                "change_pct_1d": 0.0,
                "summary": f"{pair} 即期买卖报价 {0.0 if bid is None else bid:.4f}/{0.0 if ask is None else ask:.4f}。",
                "source_origin": "remote_public",
            }
        )

    if not instruments:
        try:
            boc_safe = ak.currency_boc_safe()
        except Exception:
            boc_safe = None
        if boc_safe is not None and not boc_safe.empty:
            latest = boc_safe.iloc[0].to_dict()
            for label, key in (
                ("美元", "usd_cny_mid"),
                ("欧元", "eur_cny_mid"),
                ("日元", "jpy_cny_mid"),
                ("港元", "hkd_cny_mid"),
                ("英镑", "gbp_cny_mid"),
            ):
                value = _safe_float(latest.get(label))
                if value is None:
                    continue
                bias = "up" if label == "美元" and value >= 7.2 else "neutral"
                score = max(0.0, min(100.0, 100 - abs(value - 7.0) * 30)) if label == "美元" else 50.0
                instruments.append(
                    {
                        "key": key,
                        "label": f"{label}/人民币中间价",
                        "category": "fx",
                        "value": round(value, 6),
                        "score": round(score, 1),
                        "bias": bias,
                        "change_pct_1d": 0.0,
                        "summary": f"{label}/人民币中间价 {value:.4f}。",
                        "source_origin": "remote_public",
                    }
                )
    if not instruments:
        return None
    return feeds._build_payload(
        "macro_rates_fx",
        instruments[:48],
        now=datetime.now(),
        fetch_mode="remote_public_live",
        remote_url="akshare:fx_spot_quote",
    )


def _public_live_official_payload() -> dict[str, Any] | None:
    ingest = feeds._safe_load_dict(feeds.POLICY_OFFICIAL_INGEST)
    directions = ingest.get("directions", []) if isinstance(ingest.get("directions"), list) else []
    documents: list[dict[str, Any]] = []
    candidate_reference_count = 0
    reachable_reference_count = 0
    unreachable_reference_count = 0
    last_error = ""
    for direction in directions:
        if not isinstance(direction, dict):
            continue
        direction_name = str(direction.get("direction") or "").strip()
        entries = direction.get("official_source_entries", []) if isinstance(direction.get("official_source_entries"), list) else []
        public_entries = [
            raw for raw in entries
            if isinstance(raw, dict)
            and str(raw.get("reference_url") or "").strip().startswith(("http://", "https://"))
        ]
        for raw in public_entries[:6]:
            if not isinstance(raw, dict):
                continue
            reference_url = str(raw.get("reference_url") or "").strip()
            title = str(raw.get("title") or "").strip()
            if not reference_url or not title:
                continue
            candidate_reference_count += 1
            try:
                text = feeds._strip_html(_http_request_text(reference_url, timeout=6.0))
            except Exception as exc:
                unreachable_reference_count += 1
                last_error = type(exc).__name__
                continue
            if len(text) < 80:
                unreachable_reference_count += 1
                continue
            reachable_reference_count += 1
            documents.append(
                {
                    "title": title,
                    "source": str(raw.get("issuer") or "官方口径").strip() or "官方口径",
                    "published_at": str(raw.get("published_at") or "").strip() or None,
                    "excerpt": text[:240],
                    "reference_url": reference_url,
                    "keywords": [str(item).strip() for item in raw.get("watch_tags", []) if str(item).strip()],
                    "affected_directions": [direction_name] if direction_name else [],
                    "affected_regions": [],
                    "source_origin": "remote_public",
                }
            )
        if len(documents) >= 8:
            break
    if documents:
        payload = feeds._build_payload(
            "official_fulltext",
            documents[:80],
            now=datetime.now(),
            fetch_mode="remote_public_live",
            remote_url="public_official_reference_urls",
        )
        payload["live_probe_summary"] = (
            f"官方全文候选 {candidate_reference_count} 条，成功抓取 {reachable_reference_count} 条。"
        )
        payload["candidate_reference_count"] = candidate_reference_count
        payload["reachable_reference_count"] = reachable_reference_count
        payload["unreachable_reference_count"] = unreachable_reference_count
        return payload
    if candidate_reference_count:
        payload = feeds._build_payload(
            "official_fulltext",
            feeds._fallback_official_documents(),
            now=datetime.now(),
            fetch_mode="derived",
            remote_url=None,
        )
        payload["block_reason"] = "official_public_references_unreachable"
        payload["live_probe_summary"] = (
            f"官方全文候选 {candidate_reference_count} 条，但可直连抓取 0 条；当前保留派生口径。"
        )
        payload["candidate_reference_count"] = candidate_reference_count
        payload["reachable_reference_count"] = 0
        payload["unreachable_reference_count"] = unreachable_reference_count
        if last_error:
            payload["last_probe_error"] = last_error
        return payload
    return None


def _public_live_payload(source_key: str) -> dict[str, Any] | None:
    try:
        if source_key == "official_fulltext":
            return _public_live_official_payload()
        if source_key in {"shipping_ais", "freight_rates"}:
            shipping_and_freight = _public_live_shipping_or_freight()
            if shipping_and_freight is None:
                return None
            routes, lanes = shipping_and_freight
            if source_key == "shipping_ais":
                return feeds._build_payload(
                    "shipping_ais",
                    routes,
                    now=datetime.now(),
                    fetch_mode="remote_public_live",
                    remote_url=_EASTMONEY_MACRO_URL,
                )
            return feeds._build_payload(
                "freight_rates",
                lanes,
                now=datetime.now(),
                fetch_mode="remote_public_live",
                remote_url=_EASTMONEY_MACRO_URL,
            )
        if source_key == "commodity_terminal":
            return _public_live_commodity_payload()
        if source_key == "macro_rates_fx":
            return _public_live_macro_payload()
    except Exception:
        return None
    return None


def _source_status_item(source_key: str) -> dict[str, Any]:
    payload = _cached_or_fallback_payload(source_key)
    plural_key = _PLURAL_KEYS[source_key]
    item = {
        "key": source_key,
        "updated_at": payload.get("updated_at"),
        "fetch_mode": payload.get("fetch_mode"),
        "origin_mode": payload.get("origin_mode"),
        "signal_count": len(payload.get(plural_key, [])) if isinstance(payload.get(plural_key), list) else 0,
        "remote_configured": bool(payload.get("remote_url")) or _gateway_enabled(),
        "degraded_to_derived": False,
    }
    for extra_key in (
        "block_reason",
        "live_probe_summary",
        "candidate_reference_count",
        "reachable_reference_count",
        "unreachable_reference_count",
        "last_probe_error",
    ):
        if extra_key in payload:
            item[extra_key] = payload.get(extra_key)
    return item


@app.get("/health/live")
def health_live() -> dict[str, Any]:
    return {
        "status": "live",
        "gateway_auth_enabled": _gateway_enabled(),
        "sources": list(_PLURAL_KEYS.keys()),
    }


@app.get("/api/world-gateway/source-status")
def source_status(_: None = Depends(_ensure_gateway_access)) -> dict[str, Any]:
    return {
        "status": "ok",
        "gateway_auth_enabled": _gateway_enabled(),
        "sources": [_source_status_item(source_key) for source_key in _PLURAL_KEYS],
    }


@app.get("/api/world-gateway/official-fulltext")
def official_fulltext(_: None = Depends(_ensure_gateway_access)) -> dict[str, Any]:
    return _cached_or_fallback_payload("official_fulltext")


@app.get("/api/world-gateway/shipping-ais")
def shipping_ais(_: None = Depends(_ensure_gateway_access)) -> dict[str, Any]:
    return _cached_or_fallback_payload("shipping_ais")


@app.get("/api/world-gateway/freight-rates")
def freight_rates(_: None = Depends(_ensure_gateway_access)) -> dict[str, Any]:
    return _cached_or_fallback_payload("freight_rates")


@app.get("/api/world-gateway/commodity-terminal")
def commodity_terminal(_: None = Depends(_ensure_gateway_access)) -> dict[str, Any]:
    return _cached_or_fallback_payload("commodity_terminal")


@app.get("/api/world-gateway/macro-rates-fx")
def macro_rates_fx(_: None = Depends(_ensure_gateway_access)) -> dict[str, Any]:
    return _cached_or_fallback_payload("macro_rates_fx")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "world_data_gateway:app",
        host=os.environ.get("WORLD_DATA_GATEWAY_HOST", "127.0.0.1"),
        port=int(os.environ.get("WORLD_DATA_GATEWAY_PORT", "18080")),
        reload=False,
    )
