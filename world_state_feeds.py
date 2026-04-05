from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from json_store import safe_load, safe_save

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT_DIR)))

POLICY_DIRECTION_CATALOG = DATA_DIR / "policy_direction_catalog.json"
POLICY_OFFICIAL_WATCH = DATA_DIR / "policy_official_watch.json"
POLICY_OFFICIAL_CARDS = DATA_DIR / "policy_official_cards.json"
POLICY_OFFICIAL_INGEST = DATA_DIR / "policy_official_ingest.json"
POLICY_EXECUTION_TIMELINE = DATA_DIR / "policy_execution_timeline.json"
INDUSTRY_CAPITAL_COMPANY_MAP = DATA_DIR / "industry_capital_company_map.json"
INDUSTRY_CAPITAL_RESEARCH_LOG = DATA_DIR / "industry_capital_research_log.json"
NEWS_DIGEST = DATA_DIR / "news_digest.json"
SIGNALS_DB = DATA_DIR / "signals_db.json"

AUTO_SOURCE_PREFIXES = ("系统自动", "系统跟踪", "自动研究")
GENERATOR_VERSION = "world-state-auto-v1"


def _utcnow() -> datetime:
    return datetime.now()


def _load_dict(path: Path) -> dict[str, Any]:
    payload = safe_load(str(path), default={})
    return payload if isinstance(payload, dict) else {}


def _load_list(path: Path) -> list[dict[str, Any]]:
    payload = safe_load(str(path), default=[])
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _direction_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    directions = payload.get("directions", [])
    if not isinstance(directions, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in directions:
        if not isinstance(item, dict):
            continue
        direction_id = str(item.get("id") or "").strip()
        if direction_id:
            result[direction_id] = item
    return result


def _parse_iso_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    head = text.split("T", 1)[0]
    try:
        return date.fromisoformat(head)
    except ValueError:
        return None


def _parse_iso_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1]
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        parsed_date = _parse_iso_date(text)
        if parsed_date is None:
            return None
        return datetime.combine(parsed_date, datetime.min.time())


def _slug(text: str) -> str:
    keep = []
    for ch in text.lower():
        if ch.isalnum():
            keep.append(ch)
        elif ch in {"-", "_"}:
            keep.append(ch)
    return "".join(keep) or "item"


def _normalize_terms(items: list[object]) -> list[str]:
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def _direction_terms(direction: dict[str, Any]) -> list[str]:
    terms = {
        str(direction.get("direction") or "").strip(),
        str(direction.get("policy_bucket") or "").strip(),
    }
    for key in (
        "keywords",
        "focus_sectors",
        "demand_drivers",
        "supply_drivers",
        "upstream",
        "midstream",
        "downstream",
        "milestones",
    ):
        values = direction.get(key, [])
        if isinstance(values, list):
            terms.update(_normalize_terms(values))
    return [term for term in terms if term]


def _match_direction(direction: dict[str, Any], text: str) -> bool:
    haystack = text.lower()
    terms = _direction_terms(direction)
    return any(term.lower() in haystack for term in terms if term)


def _recent_news_events(digest: dict[str, Any], direction: dict[str, Any]) -> list[dict[str, Any]]:
    events = digest.get("events", [])
    if not isinstance(events, list):
        return []
    matched: list[dict[str, Any]] = []
    for event in events[:48]:
        if not isinstance(event, dict):
            continue
        text = " ".join(
            [
                str(event.get("title") or ""),
                str(event.get("summary") or ""),
                str(event.get("strategy_implications") or ""),
                " ".join(str(item) for item in event.get("affected_sectors", []) if str(item).strip()),
            ]
        )
        if _match_direction(direction, text):
            matched.append(event)
    return matched


def _first_watch_source(watch_item: dict[str, Any]) -> str:
    sources = watch_item.get("official_sources", [])
    if isinstance(sources, list):
        for item in sources:
            text = str(item or "").strip()
            if text:
                return text
    return "系统跟踪"


def _base_watch_tags(direction: dict[str, Any], watch_item: dict[str, Any]) -> list[str]:
    tags = []
    for key in ("official_watchpoints",):
        values = watch_item.get(key, [])
        if isinstance(values, list):
            tags.extend(_normalize_terms(values))
    tags.extend(_normalize_terms(direction.get("keywords", [])[:2] if isinstance(direction.get("keywords"), list) else []))
    deduped = list(dict.fromkeys(tag for tag in tags if tag))
    return deduped[:4]


def _auto_official_entries(
    direction: dict[str, Any],
    watch_item: dict[str, Any],
    cards_item: dict[str, Any],
    digest: dict[str, Any],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    watch_tags = _base_watch_tags(direction, watch_item)
    issuer = _first_watch_source(watch_item)
    events = _recent_news_events(digest, direction)
    for index, event in enumerate(events[:2], start=1):
        timestamp = _parse_iso_datetime(event.get("timestamp"))
        published_at = timestamp.date().isoformat() if timestamp else None
        title = str(event.get("title") or "").strip()
        summary = str(event.get("summary") or event.get("strategy_implications") or "").strip()
        if not title or not summary:
            continue
        entries.append(
            {
                "title": title,
                "issuer": issuer,
                "published_at": published_at,
                "source_type": "系统跟踪",
                "excerpt": summary,
                "reference": str(event.get("category") or "news_event"),
                "reference_url": f"internal://news_digest/{direction.get('id')}/{index}",
                "key_points": [
                    str(event.get("strategy_implications") or summary)[:96],
                    f"继续观察 {direction.get('direction') or direction.get('id')} 的政策兑现和采购节奏。",
                ],
                "watch_tags": watch_tags,
                "source_origin": "auto_runtime",
            }
        )

    if entries:
        return entries

    cards = cards_item.get("official_cards", []) if isinstance(cards_item, dict) else []
    if not isinstance(cards, list):
        cards = []
    for index, card in enumerate(cards[:1], start=1):
        if not isinstance(card, dict):
            continue
        title = str(card.get("title") or "").strip()
        excerpt = str(card.get("excerpt") or card.get("why_it_matters") or "").strip()
        if not title or not excerpt:
            continue
        entries.append(
            {
                "title": title,
                "issuer": str(card.get("source") or issuer),
                "published_at": None,
                "source_type": "系统跟踪卡",
                "excerpt": excerpt,
                "reference": "official_card",
                "reference_url": f"internal://policy_official_cards/{direction.get('id')}/{index}",
                "key_points": [
                    str(card.get("why_it_matters") or excerpt)[:96],
                    str(card.get("next_watch") or "继续观察细则、项目、订单与采购动作。")[:96],
                ],
                "watch_tags": watch_tags,
                "source_origin": "auto_runtime",
            }
        )
    return entries


def _normalize_official_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        issuer = str(item.get("issuer") or "").strip()
        excerpt = str(item.get("excerpt") or "").strip()
        if not title or not issuer or not excerpt:
            continue
        key_points = [str(point).strip() for point in item.get("key_points", []) if str(point).strip()]
        watch_tags = [str(tag).strip() for tag in item.get("watch_tags", []) if str(tag).strip()]
        normalized.append(
            {
                "title": title,
                "issuer": issuer,
                "published_at": str(item.get("published_at") or "").strip() or None,
                "source_type": str(item.get("source_type") or "官方原文").strip() or "官方原文",
                "excerpt": excerpt,
                "reference": str(item.get("reference") or "").strip() or None,
                "reference_url": str(item.get("reference_url") or "").strip() or None,
                "key_points": key_points[:4],
                "watch_tags": watch_tags[:4],
                "source_origin": str(item.get("source_origin") or "").strip() or None,
            }
        )
    normalized.sort(key=lambda item: item.get("published_at") or "", reverse=True)
    return normalized


def refresh_policy_official_ingest(now: datetime | None = None) -> dict[str, Any]:
    now = now or _utcnow()
    catalog = _load_dict(POLICY_DIRECTION_CATALOG)
    watch_map = _direction_map(_load_dict(POLICY_OFFICIAL_WATCH))
    cards_map = _direction_map(_load_dict(POLICY_OFFICIAL_CARDS))
    digest = _load_dict(NEWS_DIGEST)
    existing_map = _direction_map(_load_dict(POLICY_OFFICIAL_INGEST))

    directions_out: list[dict[str, Any]] = []
    for direction in _direction_map(catalog).values():
        direction_id = str(direction.get("id") or "").strip()
        current = existing_map.get(direction_id, {})
        current_entries = current.get("official_source_entries", []) if isinstance(current, dict) else []
        manual_entries = [
            item
            for item in (current_entries if isinstance(current_entries, list) else [])
            if isinstance(item, dict)
            and str(item.get("source_origin") or "").strip() != "auto_runtime"
        ]
        auto_entries = _auto_official_entries(
            direction,
            watch_map.get(direction_id, {}),
            cards_map.get(direction_id, {}),
            digest,
        )
        directions_out.append(
            {
                "id": direction_id,
                "official_source_entries": _normalize_official_entries(
                    [*manual_entries, *auto_entries]
                ),
            }
        )

    payload = {
        "generator_version": GENERATOR_VERSION,
        "last_update": now.isoformat(timespec="seconds"),
        "directions": directions_out,
    }
    safe_save(str(POLICY_OFFICIAL_INGEST), payload)
    return payload


def _timeline_stage(index: int, checkpoint: str) -> str:
    if index == 0:
        return "官方定调"
    if any(token in checkpoint for token in ("项目", "招标", "采购", "试点")):
        return "项目落地"
    if any(token in checkpoint for token in ("盈利", "交付", "验证")):
        return "盈利验证"
    return "继续观察"


def refresh_policy_execution_timeline(now: datetime | None = None) -> dict[str, Any]:
    now = now or _utcnow()
    catalog = _load_dict(POLICY_DIRECTION_CATALOG)
    watch_map = _direction_map(_load_dict(POLICY_OFFICIAL_WATCH))
    company_map = _direction_map(_load_dict(INDUSTRY_CAPITAL_COMPANY_MAP))
    existing_map = _direction_map(_load_dict(POLICY_EXECUTION_TIMELINE))
    ingest_map = _direction_map(_load_dict(POLICY_OFFICIAL_INGEST))
    digest = _load_dict(NEWS_DIGEST)

    directions_out: list[dict[str, Any]] = []
    for direction in _direction_map(catalog).values():
        direction_id = str(direction.get("id") or "").strip()
        current = existing_map.get(direction_id, {})
        checkpoints = current.get("timeline_checkpoints", []) if isinstance(current, dict) else []
        if not isinstance(checkpoints, list) or not checkpoints:
            checkpoints = direction.get("milestones", [])
        official_documents = current.get("official_documents", []) if isinstance(current, dict) else []
        if not isinstance(official_documents, list) or not official_documents:
            official_documents = _normalize_terms(watch_map.get(direction_id, {}).get("official_sources", []))
        cooperation_targets = current.get("cooperation_targets", []) if isinstance(current, dict) else []
        if not isinstance(cooperation_targets, list) or not cooperation_targets:
            cooperation_targets = _normalize_terms(company_map.get(direction_id, {}).get("research_targets", []))
        cooperation_modes = current.get("cooperation_modes", []) if isinstance(current, dict) else []
        if not isinstance(cooperation_modes, list) or not cooperation_modes:
            cooperation_modes = ["政策跟踪", "项目验证", "订单跟踪", "产业调研"]

        ingest_entry = ingest_map.get(direction_id, {})
        official_entries = ingest_entry.get("official_source_entries", []) if isinstance(ingest_entry, dict) else []
        if not isinstance(official_entries, list):
            official_entries = []
        events = _recent_news_events(digest, direction)

        timeline_events: list[dict[str, Any]] = []
        for index, entry in enumerate(official_entries[:2], start=1):
            if not isinstance(entry, dict):
                continue
            summary = (
                "；".join(str(point).strip() for point in entry.get("key_points", []) if str(point).strip())
                or str(entry.get("excerpt") or "")
            )
            timeline_events.append(
                {
                    "id": f"{direction_id}-official-{index}",
                    "lane": "official",
                    "stage": "官方跟踪" if index > 1 else "官方定调",
                    "title": str(entry.get("title") or f"{direction.get('direction')} 官方口径"),
                    "summary": summary[:160],
                    "source": str(entry.get("issuer") or "官方口径"),
                    "signal_label": str(entry.get("source_type") or "官方原文"),
                    "emphasis": "info",
                    "timestamp": entry.get("published_at"),
                    "next_action": "继续跟踪采购、招标、试点和利润兑现。",
                }
            )
        for index, event in enumerate(events[:2], start=1):
            if not isinstance(event, dict):
                continue
            timeline_events.append(
                {
                    "id": f"{direction_id}-market-{index}",
                    "lane": "market",
                    "stage": "市场催化",
                    "title": str(event.get("title") or "市场催化"),
                    "summary": str(event.get("strategy_implications") or event.get("summary") or "")[:160],
                    "source": "news_digest",
                    "signal_label": "事件驱动",
                    "emphasis": "info",
                    "timestamp": event.get("timestamp"),
                    "next_action": "确认催化是否走向订单、项目和预算兑现。",
                }
            )
        for index, checkpoint in enumerate(_normalize_terms(checkpoints)[:4], start=1):
            timeline_events.append(
                {
                    "id": f"{direction_id}-execution-{index}",
                    "lane": "execution",
                    "stage": _timeline_stage(index - 1, checkpoint),
                    "title": f"兑现节点 {index}",
                    "summary": f"{direction.get('direction')} 当前需要推进到“{checkpoint}”，再确认兑现是否闭环。",
                    "source": official_documents[min(index - 1, max(len(official_documents) - 1, 0))] if official_documents else "执行时间线",
                    "signal_label": "兑现观察",
                    "emphasis": "neutral",
                    "timestamp": None,
                    "next_action": checkpoints[index] if index < len(checkpoints) else "继续观察交付、采购、利润和资本开支。",
                }
            )

        directions_out.append(
            {
                "id": direction_id,
                "official_documents": _normalize_terms(official_documents)[:4],
                "timeline_checkpoints": _normalize_terms(checkpoints)[:5],
                "cooperation_targets": _normalize_terms(cooperation_targets)[:4],
                "cooperation_modes": _normalize_terms(cooperation_modes)[:4],
                "timeline_events": timeline_events[:8],
            }
        )

    payload = {
        "generator_version": GENERATOR_VERSION,
        "last_update": now.isoformat(timespec="seconds"),
        "directions": directions_out,
    }
    safe_save(str(POLICY_EXECUTION_TIMELINE), payload)
    return payload


def _recent_signals() -> list[dict[str, Any]]:
    cutoff = _utcnow().date() - timedelta(days=45)
    items: list[dict[str, Any]] = []
    for signal in _load_list(SIGNALS_DB):
        signal_date = _parse_iso_date(signal.get("date"))
        if signal_date is not None and signal_date >= cutoff:
            items.append(signal)
    return items


def _signal_verify_return(signal: dict[str, Any], key: str) -> float | None:
    verify = signal.get("verify", {})
    if not isinstance(verify, dict):
        return None
    node = verify.get(key, {})
    if not isinstance(node, dict):
        return None
    value = node.get("return_pct")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _research_status(count: int, avg_t1: float | None, avg_t3: float | None, avg_t5: float | None) -> str:
    if count >= 2 and (avg_t3 or 0.0) >= 1.0 and (avg_t1 or 0.0) >= 0.0:
        return "验证增强"
    if count >= 2 and ((avg_t3 or 0.0) <= -1.0 or (avg_t5 or 0.0) <= -2.0):
        return "出现阻力"
    if count >= 1:
        return "继续验证"
    return "待验证"


def refresh_industry_capital_research_log(now: datetime | None = None) -> dict[str, Any]:
    now = now or _utcnow()
    catalog = _direction_map(_load_dict(POLICY_DIRECTION_CATALOG))
    company_map = _direction_map(_load_dict(INDUSTRY_CAPITAL_COMPANY_MAP))
    digest = _load_dict(NEWS_DIGEST)
    existing = _load_dict(INDUSTRY_CAPITAL_RESEARCH_LOG)
    manual_items = [
        item
        for item in existing.get("items", [])
        if isinstance(item, dict)
        and not any(str(item.get("source") or "").startswith(prefix) for prefix in AUTO_SOURCE_PREFIXES)
    ] if isinstance(existing.get("items"), list) else []

    signals = _recent_signals()
    auto_items: list[dict[str, Any]] = []
    for direction_id, direction in catalog.items():
        watch = company_map.get(direction_id, {})
        company_watchlist = watch.get("company_watchlist", []) if isinstance(watch, dict) else []
        codes = {str(item.get("code") or "").strip() for item in company_watchlist if isinstance(item, dict)}
        codes.discard("")
        names = {
            str(item.get("name") or "").strip()
            for item in company_watchlist
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }
        matched_signals = []
        for signal in signals:
            code = str(signal.get("code") or "").strip()
            name = str(signal.get("name") or "").strip()
            text = " ".join([code, name, str(signal.get("strategy") or ""), str(signal.get("direction") or "")])
            if code in codes or name in names or _match_direction(direction, text):
                matched_signals.append(signal)

        if not matched_signals and not _recent_news_events(digest, direction):
            continue

        best_signal = matched_signals[0] if matched_signals else {}
        t1_values = [value for value in (_signal_verify_return(item, "t1") for item in matched_signals) if value is not None]
        t3_values = [value for value in (_signal_verify_return(item, "t3") for item in matched_signals) if value is not None]
        t5_values = [value for value in (_signal_verify_return(item, "t5") for item in matched_signals) if value is not None]
        avg_t1 = round(sum(t1_values) / len(t1_values), 2) if t1_values else None
        avg_t3 = round(sum(t3_values) / len(t3_values), 2) if t3_values else None
        avg_t5 = round(sum(t5_values) / len(t5_values), 2) if t5_values else None
        status = _research_status(len(matched_signals), avg_t1, avg_t3, avg_t5)
        note_parts = [
            f"系统自动跟踪最近 {len(matched_signals)} 条相关信号。",
        ]
        if avg_t1 is not None:
            note_parts.append(f"T+1 均值 {avg_t1:+.2f}%")
        if avg_t3 is not None:
            note_parts.append(f"T+3 均值 {avg_t3:+.2f}%")
        if avg_t5 is not None:
            note_parts.append(f"T+5 均值 {avg_t5:+.2f}%")
        if matched_signals:
            note_parts.append(f"代表策略 {str(best_signal.get('strategy') or '继续观察')}")
        else:
            note_parts.append("暂无公司级信号，先做方向验证。")

        company_code = str(best_signal.get("code") or "").strip() or None
        company_name = str(best_signal.get("name") or "").strip() or None
        auto_items.append(
            {
                "id": f"icr_auto_{direction_id}_{now.strftime('%Y%m%d')}",
                "direction_id": direction_id,
                "direction": str(direction.get("direction") or direction_id),
                "title": f"{direction.get('direction')} 自动研究快照",
                "note": "；".join(note_parts),
                "source": "系统自动研究",
                "status": status,
                "company_code": company_code,
                "company_name": company_name,
                "created_at": now.isoformat(timespec="seconds"),
                "updated_at": now.isoformat(timespec="seconds"),
                "author": "system",
            }
        )

    payload = {
        "generator_version": GENERATOR_VERSION,
        "items": [*auto_items, *manual_items],
        "last_update": now.isoformat(timespec="seconds"),
    }
    safe_save(str(INDUSTRY_CAPITAL_RESEARCH_LOG), payload)
    return payload


def refresh_world_state_feeds(now: datetime | None = None) -> dict[str, Any]:
    now = now or _utcnow()
    ingest = refresh_policy_official_ingest(now)
    timeline = refresh_policy_execution_timeline(now)
    research = refresh_industry_capital_research_log(now)
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "generator_version": GENERATOR_VERSION,
        "official_ingest_count": len(ingest.get("directions", [])),
        "execution_timeline_count": len(timeline.get("directions", [])),
        "research_item_count": len(research.get("items", [])),
    }


def ensure_world_state_feeds_fresh(max_age_hours: int = 12) -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    now = _utcnow()
    threshold = timedelta(hours=max(1, max_age_hours))
    targets = [
        POLICY_OFFICIAL_INGEST,
        POLICY_EXECUTION_TIMELINE,
        INDUSTRY_CAPITAL_RESEARCH_LOG,
    ]
    for path in targets:
        if not path.exists():
            refresh_world_state_feeds(now)
            return True
        modified = datetime.fromtimestamp(path.stat().st_mtime)
        if now - modified > threshold:
            refresh_world_state_feeds(now)
            return True
    return False
