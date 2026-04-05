from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1]
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        head = text.split("T", 1)[0]
        try:
            return datetime.fromisoformat(head)
        except ValueError:
            return None


def freshness_score(updated_at: object) -> float:
    parsed = _parse_datetime(updated_at)
    if parsed is None:
        return 0.0
    age_hours = max(0.0, (datetime.now() - parsed).total_seconds() / 3600.0)
    if age_hours <= 1.0:
        return 100.0
    if age_hours <= 4.0:
        return 92.0
    if age_hours <= 12.0:
        return 84.0
    if age_hours <= 24.0:
        return 68.0
    if age_hours <= 48.0:
        return 44.0
    if age_hours <= 96.0:
        return 26.0
    return 12.0


def freshness_label(score: float) -> str:
    if score >= 92.0:
        return "实时"
    if score >= 72.0:
        return "新鲜"
    if score >= 44.0:
        return "可用"
    if score >= 20.0:
        return "陈旧"
    return "缺失"


@dataclass(frozen=True)
class SourceAdapterSpec:
    key: str
    label: str
    category: str
    external: bool
    required: bool
    fetch_mode: str


_SOURCE_ADAPTER_SPECS: dict[str, SourceAdapterSpec] = {
    "news_digest": SourceAdapterSpec(
        key="news_digest",
        label="全球新闻摘要",
        category="news",
        external=True,
        required=True,
        fetch_mode="auto_digest",
    ),
    "official_ingest": SourceAdapterSpec(
        key="official_ingest",
        label="官方口径入库",
        category="policy",
        external=True,
        required=True,
        fetch_mode="auto_synthesized",
    ),
    "execution_timeline": SourceAdapterSpec(
        key="execution_timeline",
        label="执行时间线",
        category="timeline",
        external=False,
        required=True,
        fetch_mode="derived",
    ),
    "industry_research": SourceAdapterSpec(
        key="industry_research",
        label="产业资本调研",
        category="research",
        external=False,
        required=True,
        fetch_mode="derived",
    ),
    "official_fulltext": SourceAdapterSpec(
        key="official_fulltext",
        label="官方全文原文",
        category="policy_fulltext",
        external=True,
        required=True,
        fetch_mode="remote_or_derived",
    ),
    "shipping_ais": SourceAdapterSpec(
        key="shipping_ais",
        label="航运/AIS 通道",
        category="shipping",
        external=True,
        required=False,
        fetch_mode="remote_or_derived",
    ),
    "freight_rates": SourceAdapterSpec(
        key="freight_rates",
        label="运价与保费",
        category="freight",
        external=True,
        required=False,
        fetch_mode="remote_or_derived",
    ),
    "commodity_terminal": SourceAdapterSpec(
        key="commodity_terminal",
        label="商品终端价格",
        category="commodity",
        external=True,
        required=True,
        fetch_mode="remote_or_derived",
    ),
    "macro_rates_fx": SourceAdapterSpec(
        key="macro_rates_fx",
        label="宏观利率汇率",
        category="macro",
        external=True,
        required=True,
        fetch_mode="remote_or_derived",
    ),
}


def _default_spec(key: str, label: str | None = None) -> SourceAdapterSpec:
    return SourceAdapterSpec(
        key=key,
        label=label or key,
        category="runtime",
        external=False,
        required=False,
        fetch_mode="runtime",
    )


def source_adapter_spec(key: str, label: str | None = None) -> SourceAdapterSpec:
    return _SOURCE_ADAPTER_SPECS.get(key, _default_spec(key, label))


def build_source_status(raw_item: dict[str, Any]) -> dict[str, Any]:
    key = str(raw_item.get("key") or "").strip() or "unknown"
    label = str(raw_item.get("label") or "").strip() or key
    spec = source_adapter_spec(key, label)
    updated_at = str(raw_item.get("updated_at") or "").strip() or None
    freshness = _to_float(raw_item.get("freshness_score"))
    if freshness is None:
        freshness = freshness_score(updated_at)
    reliability = _clamp(_to_float(raw_item.get("reliability_score")) or 50.0, 0.0, 100.0)
    authority = _clamp(_to_float(raw_item.get("authority_score")) or 50.0, 0.0, 100.0)
    timeliness = _clamp(_to_float(raw_item.get("timeliness_score")) or freshness, 0.0, 100.0)
    signal_count = max(0, _to_int(raw_item.get("signal_count")))
    available = bool(raw_item.get("available")) if "available" in raw_item else bool(updated_at or signal_count > 0)
    fetch_mode = str(raw_item.get("fetch_mode") or spec.fetch_mode).strip() or spec.fetch_mode
    remote_configured = (
        bool(raw_item.get("remote_configured"))
        if "remote_configured" in raw_item
        else bool(str(raw_item.get("remote_url") or "").strip())
    )
    origin_mode = str(raw_item.get("origin_mode") or "").strip()
    if not origin_mode:
        if fetch_mode.startswith("remote_") and fetch_mode != "remote_failed_fallback":
            origin_mode = "remote_live"
        elif fetch_mode == "remote_failed_fallback":
            origin_mode = "derived_fallback"
        elif fetch_mode == "derived":
            origin_mode = "derived"
        elif fetch_mode in {"auto_digest", "auto_synthesized"}:
            origin_mode = "auto_runtime"
        else:
            origin_mode = "runtime"
    degraded_to_derived = (
        bool(raw_item.get("degraded_to_derived"))
        if "degraded_to_derived" in raw_item
        else bool(remote_configured and origin_mode in {"derived", "derived_fallback"})
    )
    stale_threshold = 56.0 if spec.required else 34.0
    stale = bool(raw_item.get("stale")) if "stale" in raw_item else freshness < stale_threshold
    data_quality_score = round(
        _clamp(
            reliability * 0.36
            + authority * 0.36
            + timeliness * 0.28
            - (8.0 if spec.external and spec.required and not remote_configured else 0.0)
            - (10.0 if degraded_to_derived else 0.0),
            0.0,
            100.0,
        ),
        1,
    )
    summary = str(raw_item.get("summary") or "").strip() or f"{label} 当前暂无摘要。"
    if not available:
        summary = f"{label} 当前还没有可用数据。"
    elif stale:
        summary = f"{summary} 当前时效偏旧，建议优先确认是否需要刷新。"
    if spec.external and spec.fetch_mode == "remote_or_derived":
        if not remote_configured:
            summary = f"{summary} 真实外网入口尚未配置，当前按派生源兜底。"
        elif degraded_to_derived:
            summary = f"{summary} 远端入口当前未取到有效载荷，已退回派生源。"
        elif origin_mode == "remote_live":
            summary = f"{summary} 当前已直连真实外网源。"
    return {
        "key": key,
        "label": label,
        "updated_at": updated_at,
        "freshness_score": round(freshness, 1),
        "freshness_label": freshness_label(freshness),
        "reliability_score": round(reliability, 1),
        "authority_score": round(authority, 1),
        "timeliness_score": round(timeliness, 1),
        "signal_count": signal_count,
        "summary": summary,
        "category": spec.category,
        "external": spec.external,
        "required": spec.required,
        "fetch_mode": spec.fetch_mode,
        "remote_configured": remote_configured,
        "degraded_to_derived": degraded_to_derived,
        "origin_mode": origin_mode,
        "available": available,
        "stale": stale,
        "data_quality_score": data_quality_score,
    }


def build_source_statuses(raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keyed: dict[str, dict[str, Any]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        keyed[key] = item

    statuses = [
        build_source_status(keyed[key])
        for key in _SOURCE_ADAPTER_SPECS
        if key in keyed
    ]
    for key, item in keyed.items():
        if key in _SOURCE_ADAPTER_SPECS:
            continue
        statuses.append(build_source_status(item))
    statuses.sort(
        key=lambda item: (
            0 if item.get("required") else 1,
            0 if item.get("available") else 1,
            0 if not item.get("stale") else 1,
            -(item.get("data_quality_score") or 0.0),
        )
    )
    return statuses
