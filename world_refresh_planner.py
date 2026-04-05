from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from json_store import safe_load, safe_save

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT_DIR)))
EXPORT_DIR = DATA_DIR / "exports" / "world_refresh"
RUNTIME_STATE = EXPORT_DIR / "runtime_state.json"
NEWS_DIGEST = DATA_DIR / "news_digest.json"


def _now() -> datetime:
    return datetime.now()


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


def _load_digest() -> dict[str, Any]:
    payload = safe_load(str(NEWS_DIGEST), default={})
    return payload if isinstance(payload, dict) else {}


def _active_window(now: datetime) -> tuple[str, str]:
    hm = now.hour * 60 + now.minute
    if now.weekday() >= 5:
        if 8 * 60 <= hm < 23 * 60:
            return "weekend_watch", "周末观察"
        return "overnight", "隔夜观察"
    if 6 * 60 + 30 <= hm < 9 * 60 + 30:
        return "pre_open", "盘前"
    if 9 * 60 + 30 <= hm < 11 * 60 + 30 or 13 * 60 <= hm < 15 * 60 + 30:
        return "intraday", "盘中"
    if 15 * 60 + 30 <= hm < 19 * 60:
        return "post_close", "盘后"
    if 19 * 60 <= hm < 23 * 60 + 30:
        return "evening", "夜间"
    return "overnight", "隔夜观察"


def _base_intervals(window: str) -> tuple[int, int, int, int]:
    if window == "weekend_watch":
        return 60, 60, 120, 90
    if window == "overnight":
        return 180, 180, 240, 240
    return 15, 15, 30, 30


def _next_due_at(last_run_at: object, interval_minutes: int) -> str | None:
    last_dt = _parse_datetime(last_run_at)
    if last_dt is None:
        return None
    next_dt = last_dt + timedelta(minutes=max(1, interval_minutes))
    return next_dt.isoformat(timespec="seconds")


def _top_event_cascade(digest: dict[str, Any]) -> dict[str, Any] | None:
    try:
        from world_event_cascade import build_event_cascades

        events = digest.get("events", [])
        if not isinstance(events, list):
            return None
        cascades = build_event_cascades(events)
        if cascades and isinstance(cascades[0], dict):
            return cascades[0]
    except Exception:
        return None
    return None


def build_world_refresh_plan(
    now: datetime | None = None,
    digest: dict[str, Any] | None = None,
    runtime_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = now or _now()
    digest = digest or _load_digest()
    runtime_state = runtime_state if isinstance(runtime_state, dict) else load_world_refresh_runtime_state()
    window, window_label = _active_window(now)
    news_interval, feeds_interval, hard_source_interval, policy_interval = _base_intervals(window)
    cascade = _top_event_cascade(digest)
    escalation_active = False
    mode = "baseline"
    mode_label = "基础轮询"
    top_trigger = None
    trigger_type = None
    next_focus: list[str] = []

    if cascade is not None:
        top_trigger = str(cascade.get("title") or "").strip() or None
        trigger_type = str(cascade.get("trigger_type") or "").strip() or None
        severity = str(cascade.get("severity") or "info").strip()
        follow_up_signal = str(cascade.get("follow_up_signal") or "stable").strip() or "stable"
        confidence_score = float(cascade.get("confidence_score") or 0.0)
        if severity == "critical" or follow_up_signal == "escalating":
            escalation_active = True
            mode = "event_escalated"
            mode_label = "事件升级"
            news_interval, feeds_interval, hard_source_interval, policy_interval = 5, 5, 10, 15
        elif follow_up_signal == "easing":
            escalation_active = True
            mode = "event_cooling"
            mode_label = "事件缓和"
            news_interval, feeds_interval, hard_source_interval, policy_interval = 15, 15, 20, 30
        elif (
            severity == "warning"
            and trigger_type in {"commodity_supply_shock", "technology_sanction"}
        ) or follow_up_signal in {"confirming", "mixed"} or confidence_score >= 70.0:
            escalation_active = True
            mode = "event_heightened"
            mode_label = "事件跟踪"
            news_interval, feeds_interval, hard_source_interval, policy_interval = 10, 10, 15, 20
        next_focus = [
            str(cascade.get("continuity_focus") or "").strip(),
            str(cascade.get("transport_focus") or "").strip(),
            *[str(item).strip() for item in cascade.get("direct_beneficiaries", [])[:2] if str(item).strip()],
            *[str(item).strip() for item in cascade.get("direct_losers", [])[:2] if str(item).strip()],
        ]

    next_focus = [item for item in next_focus if item]
    overdue_sources: list[str] = []
    if _is_due(runtime_state.get("last_global_news_at"), news_interval, now):
        overdue_sources.append("news_digest")
    if _is_due(runtime_state.get("last_world_state_feeds_at"), feeds_interval, now):
        overdue_sources.append("world_state_feeds")
    if _is_due(runtime_state.get("last_world_hard_sources_at"), hard_source_interval, now):
        overdue_sources.append("world_hard_sources")
    if _is_due(runtime_state.get("last_policy_refresh_at"), policy_interval, now):
        overdue_sources.append("official_policy")

    summary = (
        f"当前按 {mode_label} 运行，处于 {window_label} 窗口："
        f"新闻 {news_interval} 分钟 / 世界模型 {feeds_interval} 分钟 / 硬源 {hard_source_interval} 分钟 / 官方与研究 {policy_interval} 分钟。"
    )
    if top_trigger:
        summary += f" 当前主触发事件：{top_trigger}。"
    if overdue_sources:
        summary += f" 待补抓：{' / '.join(overdue_sources)}。"

    return {
        "mode": mode,
        "mode_label": mode_label,
        "active_window": window,
        "active_window_label": window_label,
        "escalation_active": escalation_active,
        "top_trigger": top_trigger,
        "trigger_type": trigger_type,
        "news_interval_minutes": news_interval,
        "feeds_interval_minutes": feeds_interval,
        "hard_source_interval_minutes": hard_source_interval,
        "policy_interval_minutes": policy_interval,
        "overnight_watch": window in {"overnight", "weekend_watch"},
        "summary": summary,
        "next_focus": next_focus[:5],
        "next_news_due_at": _next_due_at(runtime_state.get("last_global_news_at"), news_interval),
        "next_feeds_due_at": _next_due_at(runtime_state.get("last_world_state_feeds_at"), feeds_interval),
        "next_hard_sources_due_at": _next_due_at(runtime_state.get("last_world_hard_sources_at"), hard_source_interval),
        "next_policy_due_at": _next_due_at(runtime_state.get("last_policy_refresh_at"), policy_interval),
        "overdue_sources": overdue_sources,
        "generated_at": now.isoformat(timespec="seconds"),
    }


def load_world_refresh_runtime_state() -> dict[str, Any]:
    payload = safe_load(str(RUNTIME_STATE), default={})
    return payload if isinstance(payload, dict) else {}


def save_world_refresh_runtime_state(payload: dict[str, Any]) -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    safe_save(str(RUNTIME_STATE), payload)


def _is_due(last_run_at: object, interval_minutes: int, now: datetime) -> bool:
    last_dt = _parse_datetime(last_run_at)
    if last_dt is None:
        return True
    age_minutes = max(0.0, (now - last_dt).total_seconds() / 60.0)
    return age_minutes >= max(1, interval_minutes)


def run_world_refresh_tick(
    *,
    now: datetime | None = None,
    force: bool = False,
    run_global_news=None,
    run_world_state_feeds=None,
    run_world_hard_sources=None,
) -> dict[str, Any]:
    now = now or _now()
    state = load_world_refresh_runtime_state()
    plan = build_world_refresh_plan(now=now, runtime_state=state)
    ran_news = False
    ran_feeds = False
    ran_hard_sources = False
    ran_policy = False

    news_due = force or "news_digest" in plan.get("overdue_sources", [])
    feeds_due = force or "world_state_feeds" in plan.get("overdue_sources", [])
    hard_sources_due = force or "world_hard_sources" in plan.get("overdue_sources", [])
    policy_due = force or "official_policy" in plan.get("overdue_sources", [])

    if news_due:
        if callable(run_global_news):
            run_global_news()
        state["last_global_news_at"] = now.isoformat(timespec="seconds")
        ran_news = True

    if feeds_due or policy_due:
        if callable(run_world_state_feeds):
            run_world_state_feeds()
        state["last_world_state_feeds_at"] = now.isoformat(timespec="seconds")
        state["last_policy_refresh_at"] = now.isoformat(timespec="seconds")
        ran_feeds = True
        ran_policy = True

    if hard_sources_due:
        if callable(run_world_hard_sources):
            run_world_hard_sources()
        state["last_world_hard_sources_at"] = now.isoformat(timespec="seconds")
        ran_hard_sources = True

    state["last_plan_at"] = now.isoformat(timespec="seconds")
    state["last_plan"] = build_world_refresh_plan(now=now, runtime_state=state, digest=_load_digest())
    save_world_refresh_runtime_state(state)
    return {
        "plan": state["last_plan"],
        "ran_global_news": ran_news,
        "ran_world_state_feeds": ran_feeds,
        "ran_world_hard_sources": ran_hard_sources,
        "ran_policy_refresh": ran_policy,
        "last_global_news_at": state.get("last_global_news_at"),
        "last_world_state_feeds_at": state.get("last_world_state_feeds_at"),
        "last_world_hard_sources_at": state.get("last_world_hard_sources_at"),
        "last_policy_refresh_at": state.get("last_policy_refresh_at"),
    }
