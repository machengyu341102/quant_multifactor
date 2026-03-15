"""
Alpha AI 交易系统 - FastAPI 后端服务
=====================================
提供移动端PWA所需的RESTful API + WebSocket实时推送

端口: 8000
文档: http://localhost:8000/docs

API模块:
  /api/system   - 系统状态
  /api/strategies - 策略表现
  /api/signals  - 信号列表
  /api/positions - 持仓管理
  /api/learning - 学习进度
  /ws           - WebSocket实时推送
"""

from __future__ import annotations

import base64
import logging
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import deque
from datetime import date, datetime, timedelta
from threading import Lock, Thread
from typing import Optional
import jwt

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from json_store import safe_load, safe_save
from db_store import load_scorecard, load_trade_journal

_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_DIR, ".env"))


def _parse_cors_origins(value: str) -> list[str]:
    origins = [item.strip() for item in value.split(",") if item.strip()]
    return origins or ["*"]

# ================================================================
#  FastAPI App
# ================================================================

app = FastAPI(
    title="Alpha AI Trading API",
    description="量化交易系统移动端API",
    version="1.0.0"
)


@app.middleware("http")
async def collect_request_metrics(request: Request, call_next):
    started = time.perf_counter()
    status_code = 500
    failed = False

    try:
        response = await call_next(request)
        status_code = response.status_code
        failed = status_code >= 500
        return response
    except Exception as exc:
        failed = True
        logger.exception("Unhandled request error: %s %s", request.method, request.url.path)
        raise
    finally:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        _record_request_metric(
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            latency_ms=latency_ms,
            failed=failed,
        )
        logger.info(
            "%s %s -> %s %.2fms",
            request.method,
            request.url.path,
            status_code,
            latency_ms,
        )

# ================================================================
#  数据路径
# ================================================================

_AGENT_MEMORY = os.path.join(_DIR, "agent_memory.json")
_STRATEGIES_JSON = os.path.join(_DIR, "strategies.json")
_SCORECARD_JSON = os.path.join(_DIR, "scorecard.json")
_TUNABLE_PARAMS = os.path.join(_DIR, "tunable_params.json")
_PAPER_POSITIONS = os.path.join(_DIR, "paper_positions.json")
_LEARNING_STATE = os.path.join(_DIR, "learning_state.json")
_SIGNAL_TRACKER = os.path.join(_DIR, "signal_tracker.json")
_PUSH_TOKENS = os.path.join(_DIR, "push_tokens.json")
_FEEDBACK_BOX = os.path.join(_DIR, "feedback_box.json")
_LEARNING_DAILY_ADVANCE = os.path.join(_DIR, "learning_daily_advance.json")
_APP_MESSAGE_CENTER = os.path.join(_DIR, "app_message_center.json")
_SECTOR_ALERTS = os.path.join(_DIR, "sector_alerts.json")
_NEWS_DIGEST = os.path.join(_DIR, "news_digest.json")
_POLICY_DIRECTION_CATALOG = os.path.join(_DIR, "policy_direction_catalog.json")
_POLICY_OFFICIAL_WATCH = os.path.join(_DIR, "policy_official_watch.json")
_POLICY_OFFICIAL_CARDS = os.path.join(_DIR, "policy_official_cards.json")
_POLICY_OFFICIAL_INGEST = os.path.join(_DIR, "policy_official_ingest.json")
_POLICY_EXECUTION_TIMELINE = os.path.join(_DIR, "policy_execution_timeline.json")
_INDUSTRY_CAPITAL_COMPANY_MAP = os.path.join(_DIR, "industry_capital_company_map.json")
_INDUSTRY_CAPITAL_RESEARCH_LOG = os.path.join(_DIR, "industry_capital_research_log.json")
_PUSH_STATE = os.path.join(_DIR, "push_state.json")

_APP_AUTH_USERNAME = os.environ.get("APP_AUTH_USERNAME", "admin")
_APP_AUTH_PASSWORD = os.environ.get("APP_AUTH_PASSWORD", "SyHG!F1eK4*Y!5Re")
_APP_AUTH_DISPLAY_NAME = os.environ.get("APP_AUTH_DISPLAY_NAME", "Alpha Operator")
_APP_PILOT_USERNAME = os.environ.get("APP_PILOT_USERNAME", "pilot")
_APP_PILOT_PASSWORD = os.environ.get("APP_PILOT_PASSWORD", "jlCOyZM#GwUPWSH4")
_APP_PILOT_DISPLAY_NAME = os.environ.get("APP_PILOT_DISPLAY_NAME", "Alpha Pilot")
_APP_AUTH_SECRET = os.environ.get("APP_AUTH_SECRET", "alpha-ai-native-dev-secret")
_APP_LEGACY_AUTH_SECRET = os.environ.get("APP_LEGACY_AUTH_SECRET", "alpha-app-top-secret-2026")
_APP_AUTH_TOKEN_TTL_HOURS = int(os.environ.get("APP_AUTH_TOKEN_TTL_HOURS", "12"))
_APP_CORS_ORIGINS = _parse_cors_origins(os.environ.get("APP_CORS_ORIGINS", "*"))
_EXPO_PUSH_API_URL = "https://exp.host/--/api/v2/push/send"
_EXPO_ACCESS_TOKEN = os.environ.get("EXPO_ACCESS_TOKEN", "")
_PUSH_CHANNEL_ID = "alpha-ai-native.risk-alerts"
_TAKEOVER_AUTO_COOLDOWN_SECONDS = int(os.environ.get("TAKEOVER_AUTO_COOLDOWN_SECONDS", "1800"))
_APP_LOG_LEVEL = os.environ.get("APP_LOG_LEVEL", "INFO").upper()
_RUNTIME_STARTED_AT = datetime.now()
_OPS_LATENCY_WINDOW = 200
_OPS_LOCK = Lock()
_OPS_STATE = {
    "request_count": 0,
    "error_count": 0,
    "total_latency_ms": 0.0,
    "max_latency_ms": 0.0,
    "latencies_ms": deque(maxlen=_OPS_LATENCY_WINDOW),
    "routes": {},
    "last_error_at": None,
    "last_error_path": None,
}
_LEARNING_ADVANCE_LOCK = Lock()
_RUNTIME_CACHE_LOCK = Lock()
_RUNTIME_CACHE: dict[tuple[str, object], dict[str, object]] = {}
_LEARNING_ADVANCE_STATE = {
    "status": "idle",
    "in_progress": False,
    "last_started_at": None,
    "current_run_started_at": None,
    "last_completed_at": None,
    "last_requested_by": None,
    "last_error": None,
    "last_result_summary": "",
    "last_report_excerpt": "",
    "last_ingested_signals": 0,
    "last_verified_signals": 0,
    "last_reviewed_decisions": 0,
}
_loaded_learning_advance_state = safe_load(_LEARNING_DAILY_ADVANCE, default={})
if isinstance(_loaded_learning_advance_state, dict):
    for _key in _LEARNING_ADVANCE_STATE:
        if _key in _loaded_learning_advance_state:
            _LEARNING_ADVANCE_STATE[_key] = _loaded_learning_advance_state[_key]
    if _LEARNING_ADVANCE_STATE["status"] == "running":
        _LEARNING_ADVANCE_STATE["status"] = "warning"
        _LEARNING_ADVANCE_STATE["in_progress"] = False
        _LEARNING_ADVANCE_STATE["current_run_started_at"] = None
        _LEARNING_ADVANCE_STATE["last_error"] = (
            _LEARNING_ADVANCE_STATE.get("last_error")
            or "上一轮日日精进任务在进程重启前中断"
        )
        safe_save(_LEARNING_DAILY_ADVANCE, _LEARNING_ADVANCE_STATE)

from log_config import get_logger as _get_logger
logger = _get_logger("api_server")
logger.setLevel(_APP_LOG_LEVEL)

_QUANT_DB_PATH = os.path.join(_DIR, "quant_data.db")


def _cache_enabled() -> bool:
    return not bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _runtime_cache_paths(*paths: str) -> tuple[str, ...]:
    normalized = []
    for path in paths:
        if path:
            normalized.append(path)
    return tuple(dict.fromkeys(normalized))


def _db_dependency_paths() -> tuple[str, ...]:
    return _runtime_cache_paths(
        _QUANT_DB_PATH,
        f"{_QUANT_DB_PATH}-wal",
        f"{_QUANT_DB_PATH}-shm",
    )


def _runtime_cache_signature(paths: tuple[str, ...]) -> tuple[tuple[str, Optional[int], Optional[int]], ...]:
    signature: list[tuple[str, Optional[int], Optional[int]]] = []
    for path in paths:
        try:
            stat = os.stat(path)
            signature.append((path, stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            signature.append((path, None, None))
    return tuple(signature)


def _cached_runtime_value(
    namespace: str,
    key: object,
    *,
    ttl_seconds: int,
    dependency_paths: tuple[str, ...],
    builder,
):
    if not _cache_enabled():
        return builder()

    cache_key = (namespace, key)
    now = time.monotonic()
    signature = _runtime_cache_signature(dependency_paths)
    with _RUNTIME_CACHE_LOCK:
        entry = _RUNTIME_CACHE.get(cache_key)
        if (
            entry is not None
            and entry.get("signature") == signature
            and now < float(entry.get("expires_at", 0.0))
        ):
            return entry.get("value")

    value = builder()
    with _RUNTIME_CACHE_LOCK:
        _RUNTIME_CACHE[cache_key] = {
            "signature": signature,
            "expires_at": now + max(ttl_seconds, 1),
            "value": value,
        }
    return value


def _invalidate_runtime_cache(*prefixes: str) -> None:
    with _RUNTIME_CACHE_LOCK:
        if not prefixes:
            _RUNTIME_CACHE.clear()
            return

        keys = list(_RUNTIME_CACHE.keys())
        for key in keys:
            namespace = str(key[0])
            if any(namespace.startswith(prefix) for prefix in prefixes):
                _RUNTIME_CACHE.pop(key, None)

_POLICY_DIRECTION_REGISTRY = (
    {
        "id": "ai-digital",
        "direction": "AI与数字基础设施",
        "policy_bucket": "国家战略",
        "focus_sectors": ("科技", "半导体", "通信"),
        "keywords": ("人工智能", "ai", "算力", "量子", "芯片", "半导体", "模型", "数据", "数字中国"),
        "industry_phase_map": {
            "watch": "导入验证期",
            "warming": "渗透加速期",
            "expansion": "业绩兑现期",
        },
        "demand_drivers": ("算力资本开支", "模型迭代", "企业数字化需求"),
        "supply_drivers": ("先进制程", "国产替代", "服务器与光模块产能"),
        "upstream": ("算力芯片", "先进制程", "IDC电力"),
        "midstream": ("服务器", "交换机", "CPO/通信设备"),
        "downstream": ("行业应用", "企业软件", "智能终端"),
        "milestones": ("政策提法", "专项支持", "资本开支", "订单落地", "业绩验证"),
    },
    {
        "id": "new-energy",
        "direction": "新能源与电力系统",
        "policy_bucket": "产业升级",
        "focus_sectors": ("新能源", "电力", "光伏", "风电", "储能"),
        "keywords": ("新能源", "储能", "光伏", "风电", "电力", "新能源车", "电网"),
        "industry_phase_map": {
            "watch": "需求筑底期",
            "warming": "装机修复期",
            "expansion": "景气扩散期",
        },
        "demand_drivers": ("装机需求", "电网投资", "新能源车渗透率"),
        "supply_drivers": ("硅料电芯价格", "电网设备产能", "储能成本下降"),
        "upstream": ("锂电材料", "硅料", "电力设备原材"),
        "midstream": ("电池", "逆变器", "风机设备", "储能系统"),
        "downstream": ("电站运营", "工商业储能", "新能源车"),
        "milestones": ("政策提法", "项目核准", "装机数据", "订单验证", "盈利修复"),
    },
    {
        "id": "finance-demand",
        "direction": "金融稳增长",
        "policy_bucket": "宏观政策",
        "focus_sectors": ("银行", "证券", "保险"),
        "keywords": ("降息", "降准", "lpr", "宽松", "流动性", "信贷", "财政", "刺激"),
        "industry_phase_map": {
            "watch": "预期博弈期",
            "warming": "流动性改善期",
            "expansion": "信用扩张期",
        },
        "demand_drivers": ("融资需求", "市场活跃度", "居民资产配置"),
        "supply_drivers": ("货币政策", "财政发力", "资本市场改革"),
        "upstream": ("流动性", "政策利率", "财政投放"),
        "midstream": ("银行信贷", "券商经纪与投行", "保险资管"),
        "downstream": ("地产链融资", "消费金融", "权益市场"),
        "milestones": ("政策预期", "利率落地", "社融改善", "资产扩张", "盈利兑现"),
    },
    {
        "id": "energy-security",
        "direction": "能源安全",
        "policy_bucket": "全球博弈",
        "focus_sectors": ("能源", "石化"),
        "keywords": ("原油", "石油", "天然气", "中东", "战争", "制裁", "供应", "储备"),
        "industry_phase_map": {
            "watch": "供给扰动期",
            "warming": "价格抬升期",
            "expansion": "利润扩张期",
        },
        "demand_drivers": ("全球补库", "地缘冲突", "工业需求"),
        "supply_drivers": ("油气供给", "库存释放", "制裁扰动"),
        "upstream": ("原油", "天然气", "油服"),
        "midstream": ("炼化", "油气运输", "化工原料"),
        "downstream": ("化纤", "塑料", "终端制造"),
        "milestones": ("冲突升级", "供给收紧", "价格确认", "利润兑现", "资本开支反馈"),
    },
    {
        "id": "defense-security",
        "direction": "军工安全",
        "policy_bucket": "国家安全",
        "focus_sectors": ("军工", "航空", "国防", "航天"),
        "keywords": ("战争", "冲突", "军工", "国防", "导弹", "军演", "制裁"),
        "industry_phase_map": {
            "watch": "主题预热期",
            "warming": "订单预期升温期",
            "expansion": "装备兑现期",
        },
        "demand_drivers": ("装备更新", "国防预算", "地缘冲突升温"),
        "supply_drivers": ("军工产能", "关键材料", "航空航天配套"),
        "upstream": ("特种材料", "电子元件", "精密制造"),
        "midstream": ("整机制造", "导弹航天", "军工电子"),
        "downstream": ("装备交付", "航空航运保障", "军贸"),
        "milestones": ("安全议题", "预算确认", "订单预期", "交付加速", "业绩兑现"),
    },
    {
        "id": "consumption-recovery",
        "direction": "内需消费修复",
        "policy_bucket": "经济修复",
        "focus_sectors": ("消费", "白酒", "旅游", "零售"),
        "keywords": ("消费", "内需", "促消费", "假期", "零售", "白酒", "文旅"),
        "industry_phase_map": {
            "watch": "信心修复期",
            "warming": "需求回补期",
            "expansion": "盈利释放期",
        },
        "demand_drivers": ("居民收入预期", "促消费政策", "节假日客流"),
        "supply_drivers": ("渠道去库", "价格体系", "品牌升级"),
        "upstream": ("农产品", "包材", "物流"),
        "midstream": ("品牌商", "零售渠道", "酒旅供应"),
        "downstream": ("终端零售", "旅游服务", "餐饮与体验消费"),
        "milestones": ("政策刺激", "客流恢复", "价格稳定", "渠道回暖", "业绩兑现"),
    },
    {
        "id": "domestic-substitution",
        "direction": "国产替代与自主可控",
        "policy_bucket": "国家战略",
        "focus_sectors": ("国产替代", "自主可控", "信创", "华为概念"),
        "keywords": ("制裁", "贸易战", "关税", "断供", "出口管制", "自主可控", "国产替代", "信创", "华为"),
        "industry_phase_map": {
            "watch": "替代启动期",
            "warming": "验证放量期",
            "expansion": "份额提升期",
        },
        "demand_drivers": ("自主可控需求", "政企国产化", "关键环节替代"),
        "supply_drivers": ("国产产能", "兼容生态", "订单验证"),
        "upstream": ("基础软硬件", "关键器件", "设备材料"),
        "midstream": ("整机", "操作系统", "数据库中间件"),
        "downstream": ("政务", "金融", "电信能源等行业客户"),
        "milestones": ("政策提法", "试点推进", "采购放量", "行业复制", "盈利兑现"),
    },
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=_APP_CORS_ORIGINS,
    allow_credentials="*" not in _APP_CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _signal_date(value: object) -> Optional[str]:
    if not isinstance(value, str) or not value:
        return None
    return value[:10]


def _signal_trade_day(signal: dict) -> Optional[str]:
    # Real-time signals use `timestamp`; older records may still use `rec_date`.
    return _signal_date(signal.get("timestamp")) or _signal_date(signal.get("rec_date"))


def _is_stock_signal_code(code: str) -> bool:
    return len(code) == 6 and code.isdigit()


def _is_tradable_stock_name(name: str) -> bool:
    normalized = str(name).strip().upper().replace(" ", "")
    if not normalized:
        return False
    if normalized.startswith("退") or "退市" in normalized:
        return False
    if normalized.startswith("*ST") or normalized.startswith("ST"):
        return False
    return True


def _signal_id_from_journal_entry(trade_date: str, strategy: str, code: str) -> str:
    digest = hashlib.sha1(f"{trade_date}|{strategy}|{code}".encode("utf-8")).hexdigest()[:16]
    return f"sig_journal_{digest}"


def _signal_timestamp_from_strategy(trade_date: str, strategy: str) -> str:
    slot = "09:35:00"
    if strategy in {"趋势跟踪选股", "低吸回调选股", "缩量整理选股", "放量突破选股"}:
        slot = "10:30:00"
    elif strategy in {"板块轮动选股", "尾盘短线选股"}:
        slot = "14:50:00"
    elif strategy in {"隔夜选股", "overnight"}:
        slot = "16:45:00"
    return f"{trade_date}T{slot}"


def _default_signal_stop_loss(price: float) -> float:
    return _round_money(price * 0.97) if price > 0 else 0.0


def _default_signal_target(price: float, stop_loss: float) -> float:
    if price <= 0:
        return 0.0
    risk = max(price - stop_loss, price * 0.03)
    return _round_money(price + risk * 2)


def _default_signal_risk_reward(price: float, stop_loss: float, target_price: float) -> float:
    risk = max(price - stop_loss, 0.01)
    reward = max(target_price - price, 0)
    return round(reward / risk, 2) if reward > 0 else 0.0


def _build_signal_record_from_pick(trade_date: str, strategy: str, regime: dict, pick: dict) -> Optional[dict]:
    code = str(pick.get("code", "")).strip()
    if not _is_stock_signal_code(code):
        return None

    name = str(pick.get("name", "")).strip()
    if not _is_tradable_stock_name(name):
        return None
    price = _to_float(pick.get("price")) or 0.0
    score = _to_float(pick.get("total_score"))
    if score is None:
        score = _to_float(pick.get("score")) or 0.0

    stop_loss = _to_float(pick.get("stop_loss"))
    if stop_loss is None or stop_loss <= 0:
        stop_loss = _default_signal_stop_loss(price)

    target_price = _to_float(pick.get("target_price"))
    if target_price is None or target_price <= 0:
        target_price = _default_signal_target(price, stop_loss)

    risk_reward = _to_float(pick.get("risk_reward"))
    if risk_reward is None or risk_reward <= 0:
        risk_reward = _default_signal_risk_reward(price, stop_loss, target_price)

    factor_scores = pick.get("factor_scores", {})
    if not isinstance(factor_scores, dict):
        factor_scores = {}

    regime_label = "未知"
    regime_score = 0.0
    if isinstance(regime, dict):
        regime_label = str(regime.get("regime", "未知"))
        regime_score = _to_float(regime.get("score")) or 0.0

    return {
        "id": _signal_id_from_journal_entry(trade_date, strategy, code),
        "code": code,
        "name": name,
        "strategy": strategy,
        "strategies": [strategy],
        "score": score,
        "price": price,
        "change_pct": _to_float(pick.get("change_pct")) or 0.0,
        "high": _to_float(pick.get("high")) or price,
        "low": _to_float(pick.get("low")) or price,
        "volume": _to_float(pick.get("volume")) or 0.0,
        "turnover": _to_float(pick.get("turnover")) or 0.0,
        "buy_price": _to_float(pick.get("buy_price")) or price,
        "stop_loss": stop_loss,
        "target_price": target_price,
        "risk_reward": risk_reward,
        "timestamp": _signal_timestamp_from_strategy(trade_date, strategy),
        "consensus_count": max(1, _to_int(pick.get("consensus_count"))),
        "factor_scores": factor_scores,
        "regime": regime_label,
        "regime_score": regime_score,
        "source": "trade_journal",
    }


def _load_live_signal_records(days: int = 1) -> list[dict]:
    def builder() -> list[dict]:
        lookback_days = max(days + 2, 7)
        try:
            journal = load_trade_journal(days=lookback_days)
        except Exception:
            journal = []

        cutoff = date.today() - timedelta(days=max(days - 1, 0))
        result: list[dict] = []
        seen: set[str] = set()

        for entry in journal:
            trade_date = str(entry.get("date", ""))
            try:
                trade_day = date.fromisoformat(trade_date)
            except ValueError:
                continue

            if trade_day < cutoff:
                continue

            strategy = str(entry.get("strategy", "")).strip()
            regime = entry.get("regime", {})
            picks = entry.get("picks", [])
            if not isinstance(picks, list):
                continue

            for pick in picks:
                if not isinstance(pick, dict):
                    continue
                record = _build_signal_record_from_pick(trade_date, strategy, regime, pick)
                if not record:
                    continue
                signal_id = str(record.get("id", ""))
                if signal_id in seen:
                    continue
                seen.add(signal_id)
                result.append(record)

        result.sort(
            key=lambda item: (
                str(item.get("timestamp", "")),
                float(item.get("score", 0) or 0),
            ),
            reverse=True,
        )
        return result

    return _cached_runtime_value(
        "load_live_signal_records",
        days,
        ttl_seconds=8,
        dependency_paths=_db_dependency_paths(),
        builder=builder,
    )


def _load_legacy_signal_records(days: int = 1) -> list[dict]:
    def builder() -> list[dict]:
        signals = safe_load(_SIGNAL_TRACKER, default={}).get("signals", [])
        if not isinstance(signals, list):
            return []

        cutoff = date.today() - timedelta(days=max(days - 1, 0))
        result = []
        for signal in signals:
            if not isinstance(signal, dict):
                continue
            trade_day = _signal_trade_day(signal)
            if trade_day:
                try:
                    if date.fromisoformat(trade_day) < cutoff:
                        continue
                except ValueError:
                    pass
            result.append(signal)

        return result

    return _cached_runtime_value(
        "load_legacy_signal_records",
        days,
        ttl_seconds=8,
        dependency_paths=_runtime_cache_paths(_SIGNAL_TRACKER),
        builder=builder,
    )


def _load_signal_records(days: int = 1) -> list[dict]:
    live_records = _load_live_signal_records(days=days)
    if live_records:
        return live_records
    return _load_legacy_signal_records(days=days)


def _load_signal_verification_records(days: int = 30) -> dict[str, dict]:
    signals_db_path = os.path.join(_DIR, "signals_db.json")

    def builder() -> dict[str, dict]:
        raw_records = safe_load(signals_db_path, default=[])
        if not isinstance(raw_records, list):
            return {}

        cutoff = (date.today() - timedelta(days=max(days - 1, 0))).isoformat()
        result: dict[str, dict] = {}
        for item in raw_records:
            if not isinstance(item, dict):
                continue
            trade_date = str(item.get("date", ""))
            if not trade_date or trade_date < cutoff:
                continue
            code = str(item.get("code", "")).strip()
            strategy = str(item.get("strategy", "")).strip()
            if not code or not strategy or not _is_stock_signal_code(code):
                continue
            key = f"{trade_date}|{strategy}|{code}"
            result[key] = item
        return result

    return _cached_runtime_value(
        "load_signal_verification_records",
        days,
        ttl_seconds=12,
        dependency_paths=_runtime_cache_paths(signals_db_path),
        builder=builder,
    )


def _find_signal_record(signal_id: str) -> Optional[dict]:
    for signal in _load_live_signal_records(days=7):
        if signal.get("id") == signal_id:
            return signal

    legacy_signals = safe_load(_SIGNAL_TRACKER, default={}).get("signals", [])
    if isinstance(legacy_signals, list):
        return next((item for item in legacy_signals if item.get("id") == signal_id), None)
    return None


def _to_float(value: object) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _round_money(value: float) -> float:
    return round(float(value), 2)


def _parse_datetime(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _current_trade_time() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * ratio))))
    return ordered[index]


def _record_request_metric(
    *,
    method: str,
    path: str,
    status_code: int,
    latency_ms: float,
    failed: bool,
) -> None:
    route_key = f"{method} {path}"
    with _OPS_LOCK:
        _OPS_STATE["request_count"] += 1
        if failed:
            _OPS_STATE["error_count"] += 1
            _OPS_STATE["last_error_at"] = _iso_now()
            _OPS_STATE["last_error_path"] = path

        _OPS_STATE["total_latency_ms"] += latency_ms
        _OPS_STATE["max_latency_ms"] = max(_OPS_STATE["max_latency_ms"], latency_ms)
        _OPS_STATE["latencies_ms"].append(latency_ms)

        route_stats = _OPS_STATE["routes"].setdefault(
            route_key,
            {
                "method": method,
                "path": path,
                "count": 0,
                "error_count": 0,
                "total_latency_ms": 0.0,
                "max_latency_ms": 0.0,
                "last_status": 0,
                "last_seen_at": None,
            },
        )
        route_stats["count"] += 1
        if failed:
            route_stats["error_count"] += 1
        route_stats["total_latency_ms"] += latency_ms
        route_stats["max_latency_ms"] = max(route_stats["max_latency_ms"], latency_ms)
        route_stats["last_status"] = status_code
        route_stats["last_seen_at"] = _iso_now()


def _normalize_trade_record(raw_trade: object) -> Optional[dict]:
    if not isinstance(raw_trade, dict):
        return None

    return {
        "time": str(raw_trade.get("time", "")),
        "type": str(raw_trade.get("type", "")),
        "price": _round_money(_to_float(raw_trade.get("price")) or 0),
        "quantity": max(0, _to_int(raw_trade.get("quantity"))),
        "reason": str(raw_trade.get("reason", "")),
    }


def _position_hold_days(raw_position: dict) -> int:
    entry_time = _parse_datetime(raw_position.get("entry_date")) or _parse_datetime(
        raw_position.get("buy_time")
    )
    if not entry_time:
        return max(0, _to_int(raw_position.get("hold_days")))
    return max(0, (datetime.now() - entry_time).days)


def _normalize_position_record(raw_position: dict) -> dict:
    position = dict(raw_position)
    quantity = max(0, _to_int(position.get("quantity")))
    cost_price = _round_money(_to_float(position.get("cost_price")) or 0)
    current_price = _round_money(_to_float(position.get("current_price")) or cost_price)
    observed_prices = [
        price
        for price in (
            _to_float(position.get("high_price")),
            _to_float(position.get("low_price")),
            current_price,
            cost_price,
        )
        if price is not None and price > 0
    ]
    trades: list[dict] = []
    raw_trades = position.get("trades", [])
    if isinstance(raw_trades, list):
        for raw_trade in raw_trades:
            normalized_trade = _normalize_trade_record(raw_trade)
            if normalized_trade is not None:
                trades.append(normalized_trade)

    market_value = _round_money(current_price * quantity)
    profit_loss = _round_money(market_value - cost_price * quantity)
    profit_loss_pct = round((current_price / cost_price - 1) * 100, 2) if cost_price > 0 else 0
    position.update(
        {
            "code": str(position.get("code", "")),
            "name": str(position.get("name", "")),
            "quantity": quantity,
            "cost_price": cost_price,
            "current_price": current_price,
            "market_value": market_value,
            "profit_loss": profit_loss,
            "profit_loss_pct": profit_loss_pct,
            "stop_loss": _round_money(_to_float(position.get("stop_loss")) or 0),
            "take_profit": _round_money(_to_float(position.get("take_profit")) or 0),
            "hold_days": _position_hold_days(position),
            "strategy": str(position.get("strategy", "")),
            "buy_time": str(position.get("buy_time", "")),
            "high_price": _round_money(max(observed_prices)) if observed_prices else current_price,
            "low_price": _round_money(min(observed_prices)) if observed_prices else current_price,
            "trailing_stop": bool(position.get("trailing_stop", False)),
            "trailing_trigger_price": _round_money(
                _to_float(position.get("trailing_trigger_price")) or 0
            ),
            "trades": trades,
        }
    )
    return position


def _normalize_position_trades(raw_position: dict) -> list[PositionTrade]:
    trades: list[PositionTrade] = []
    for trade in _normalize_position_record(raw_position).get("trades", []):
        trades.append(
            PositionTrade(
                time=trade.get("time", ""),
                type=trade.get("type", ""),
                price=_to_float(trade.get("price")) or 0,
                quantity=max(0, _to_int(trade.get("quantity"))),
                reason=trade.get("reason", ""),
            )
        )
    return trades


def _position_summary_model(raw_position: dict) -> Position:
    position = _normalize_position_record(raw_position)
    return Position(
        code=position.get("code", ""),
        name=position.get("name", ""),
        quantity=position.get("quantity", 0),
        cost_price=position.get("cost_price", 0),
        current_price=position.get("current_price", 0),
        market_value=position.get("market_value", 0),
        profit_loss=position.get("profit_loss", 0),
        profit_loss_pct=position.get("profit_loss_pct", 0),
        stop_loss=position.get("stop_loss", 0),
        take_profit=position.get("take_profit", 0),
        hold_days=position.get("hold_days", 0),
        strategy=position.get("strategy", ""),
    )


def _position_detail_model(raw_position: dict) -> PositionDetail:
    position = _normalize_position_record(raw_position)
    position_guide = _build_position_guide(position)
    return PositionDetail(
        code=position.get("code", ""),
        name=position.get("name", ""),
        quantity=position.get("quantity", 0),
        cost_price=position.get("cost_price", 0),
        current_price=position.get("current_price", 0),
        market_value=position.get("market_value", 0),
        profit_loss=position.get("profit_loss", 0),
        profit_loss_pct=position.get("profit_loss_pct", 0),
        stop_loss=position.get("stop_loss", 0),
        take_profit=position.get("take_profit", 0),
        hold_days=position.get("hold_days", 0),
        strategy=position.get("strategy", ""),
        buy_time=position.get("buy_time", ""),
        high_price=position.get("high_price", 0),
        low_price=position.get("low_price", 0),
        trailing_stop=position.get("trailing_stop", False),
        trailing_trigger_price=position.get("trailing_trigger_price", 0),
        trades=_normalize_position_trades(position),
        position_guide=position_guide,
    )


def _closed_position_hold_days(raw_position: dict) -> int:
    entry_time = _parse_datetime(raw_position.get("entry_date")) or _parse_datetime(
        raw_position.get("buy_time")
    )
    closed_time = _parse_datetime(raw_position.get("closed_at"))
    if not entry_time or not closed_time:
        return _position_hold_days(raw_position)
    return max(0, (closed_time - entry_time).days)


def _closed_position_model(raw_position: dict) -> ClosedPosition:
    position = _normalize_position_record(raw_position)
    trades = _normalize_position_trades(position)
    last_sell_trade = next((trade for trade in reversed(trades) if trade.type == "sell"), None)
    close_price = _round_money(
        _to_float(raw_position.get("close_price"))
        or (last_sell_trade.price if last_sell_trade is not None else position.get("current_price", 0))
    )
    quantity = position.get("quantity", 0)
    cost_price = position.get("cost_price", 0)
    realized_profit_loss = _round_money(
        _to_float(raw_position.get("realized_profit_loss")) or (close_price - cost_price) * quantity
    )
    realized_profit_loss_pct = round((close_price / cost_price - 1) * 100, 2) if cost_price > 0 else 0
    return ClosedPosition(
        code=position.get("code", ""),
        name=position.get("name", ""),
        quantity=quantity,
        cost_price=cost_price,
        close_price=close_price,
        realized_profit_loss=realized_profit_loss,
        realized_profit_loss_pct=realized_profit_loss_pct,
        hold_days=_closed_position_hold_days(raw_position),
        strategy=position.get("strategy", ""),
        buy_time=position.get("buy_time", ""),
        closed_at=str(raw_position.get("closed_at") or (last_sell_trade.time if last_sell_trade else "")),
        close_reason=str(
            raw_position.get("close_reason")
            or (last_sell_trade.reason if last_sell_trade and last_sell_trade.reason else "")
        ),
        status=str(raw_position.get("status") or "closed"),
        trades=trades,
    )


def _trade_sort_value(value: object) -> float:
    parsed = _parse_datetime(value)
    return parsed.timestamp() if parsed is not None else 0.0


def _trade_ledger_entry(raw_position: dict, trade: PositionTrade, *, status: str) -> TradeLedgerEntry:
    position = _normalize_position_record(raw_position)
    return TradeLedgerEntry(
        id=f"{position.get('code', '')}-{trade.time}-{trade.type}-{trade.quantity}",
        code=position.get("code", ""),
        name=position.get("name", ""),
        strategy=position.get("strategy", ""),
        time=trade.time,
        type=trade.type,
        price=trade.price,
        quantity=trade.quantity,
        reason=trade.reason,
        status=status,
    )


def _build_portfolio_history(limit: int = 40) -> PortfolioHistory:
    portfolio = _load_portfolio()
    raw_closed_positions = [
        item for item in portfolio.get("closed_positions", []) if isinstance(item, dict)
    ]
    raw_closed_positions.sort(
        key=lambda item: _trade_sort_value(item.get("closed_at") or item.get("buy_time")),
        reverse=True,
    )
    closed_positions = [_closed_position_model(item) for item in raw_closed_positions]

    recent_trades: list[TradeLedgerEntry] = []
    for raw_position in [item for item in portfolio.get("positions", []) if isinstance(item, dict)]:
        for trade in _normalize_position_trades(raw_position):
            recent_trades.append(_trade_ledger_entry(raw_position, trade, status="open"))
    for raw_position in raw_closed_positions:
        for trade in _normalize_position_trades(raw_position):
            recent_trades.append(_trade_ledger_entry(raw_position, trade, status="closed"))

    recent_trades.sort(key=lambda item: _trade_sort_value(item.time), reverse=True)
    realized_profit_loss = _round_money(
        sum(item.realized_profit_loss for item in closed_positions if item.realized_profit_loss)
    )
    return PortfolioHistory(
        realized_profit_loss=realized_profit_loss,
        closed_positions=closed_positions,
        recent_trades=recent_trades[: max(1, min(limit, 120))],
    )


def _load_portfolio() -> dict:
    raw_portfolio = safe_load(_PAPER_POSITIONS, default={})
    if not isinstance(raw_portfolio, dict):
        raw_portfolio = {}

    positions = raw_portfolio.get("positions", [])
    if not isinstance(positions, list):
        positions = []

    closed_positions = raw_portfolio.get("closed_positions", [])
    if not isinstance(closed_positions, list):
        closed_positions = []

    portfolio = {
        **raw_portfolio,
        "positions": [
            _normalize_position_record(item) for item in positions if isinstance(item, dict)
        ],
        "closed_positions": [item for item in closed_positions if isinstance(item, dict)],
        "cash": _round_money(_to_float(raw_portfolio.get("cash")) or 0),
        "last_update": raw_portfolio.get("last_update", datetime.now().isoformat()),
    }
    _refresh_portfolio_totals(portfolio)
    return portfolio


def _refresh_portfolio_totals(portfolio: dict) -> dict:
    raw_positions = portfolio.get("positions", [])
    normalized_positions = []
    if isinstance(raw_positions, list):
        for item in raw_positions:
            if not isinstance(item, dict):
                continue
            position = _normalize_position_record(item)
            if position.get("quantity", 0) > 0:
                normalized_positions.append(position)

    portfolio["positions"] = normalized_positions
    portfolio["cash"] = _round_money(_to_float(portfolio.get("cash")) or 0)
    portfolio["total_assets"] = _round_money(
        portfolio["cash"] + sum(_to_float(item.get("market_value")) or 0 for item in normalized_positions)
    )
    if not isinstance(portfolio.get("closed_positions"), list):
        portfolio["closed_positions"] = []
    portfolio["last_update"] = datetime.now().isoformat()
    return portfolio


def _save_portfolio(portfolio: dict) -> dict:
    safe_save(_PAPER_POSITIONS, _refresh_portfolio_totals(portfolio))
    return portfolio


def _find_position_index(portfolio: dict, code: str) -> Optional[int]:
    positions = portfolio.get("positions", [])
    if not isinstance(positions, list):
        return None

    for index, position in enumerate(positions):
        if isinstance(position, dict) and position.get("code") == code and position.get("quantity", 0) > 0:
            return index
    return None


def _validate_risk_values(
    stop_loss: Optional[float],
    take_profit: Optional[float],
    *,
    reference_price: Optional[float] = None,
) -> None:
    if stop_loss is not None and stop_loss < 0:
        raise HTTPException(status_code=400, detail="止损价不能为负数")
    if take_profit is not None and take_profit < 0:
        raise HTTPException(status_code=400, detail="止盈价不能为负数")
    if stop_loss and take_profit and stop_loss >= take_profit:
        raise HTTPException(status_code=400, detail="止损价必须低于止盈价")
    if reference_price and stop_loss and stop_loss >= reference_price:
        raise HTTPException(status_code=400, detail="止损价需要低于开仓价")
    if reference_price and take_profit and take_profit <= reference_price:
        raise HTTPException(status_code=400, detail="止盈价需要高于开仓价")


def _normalize_push_device(raw_device: dict) -> dict:
    now = datetime.now().isoformat()
    last_push_at = raw_device.get("last_push_at")
    last_push_status = raw_device.get("last_push_status")
    last_error = raw_device.get("last_error")
    last_takeover_push_at = raw_device.get("last_takeover_push_at")
    last_takeover_fingerprint = raw_device.get("last_takeover_fingerprint")
    return {
        "username": str(raw_device.get("username", "")),
        "platform": str(raw_device.get("platform", "unknown")),
        "expo_push_token": str(raw_device.get("expo_push_token", "")).strip(),
        "device_name": str(raw_device.get("device_name") or "未命名设备"),
        "app_version": str(raw_device.get("app_version") or ""),
        "permission_state": str(raw_device.get("permission_state") or "unknown"),
        "is_physical_device": raw_device.get("is_physical_device")
        if isinstance(raw_device.get("is_physical_device"), bool)
        else None,
        "status": str(raw_device.get("status") or "active"),
        "last_seen_at": str(raw_device.get("last_seen_at") or now),
        "last_push_at": str(last_push_at) if isinstance(last_push_at, str) and last_push_at else None,
        "last_push_status": str(last_push_status)
        if isinstance(last_push_status, str) and last_push_status
        else None,
        "last_error": str(last_error) if isinstance(last_error, str) and last_error else None,
        "last_takeover_push_at": str(last_takeover_push_at)
        if isinstance(last_takeover_push_at, str) and last_takeover_push_at
        else None,
        "last_takeover_fingerprint": str(last_takeover_fingerprint)
        if isinstance(last_takeover_fingerprint, str) and last_takeover_fingerprint
        else None,
    }


def _push_device_model(raw_device: dict) -> PushDevice:
    device = _normalize_push_device(raw_device)
    return PushDevice(
        username=device["username"],
        platform=device["platform"],
        expo_push_token=device["expo_push_token"],
        device_name=device["device_name"],
        app_version=device["app_version"],
        permission_state=device["permission_state"],
        is_physical_device=device["is_physical_device"],
        status=device["status"],
        last_seen_at=device["last_seen_at"],
        last_push_at=device["last_push_at"],
        last_push_status=device["last_push_status"],
        last_error=device["last_error"],
    )


def _load_push_registry() -> dict:
    raw_registry = safe_load(_PUSH_TOKENS, default={})
    if not isinstance(raw_registry, dict):
        raw_registry = {}

    raw_devices = raw_registry.get("devices", [])
    if not isinstance(raw_devices, list):
        raw_devices = []

    return {
        "devices": [
            _normalize_push_device(device) for device in raw_devices if isinstance(device, dict)
        ],
        "last_update": raw_registry.get("last_update", datetime.now().isoformat()),
    }


def _save_push_registry(registry: dict) -> dict:
    devices = registry.get("devices", [])
    if not isinstance(devices, list):
        devices = []
    payload = {
        "devices": [_normalize_push_device(device) for device in devices if isinstance(device, dict)],
        "last_update": datetime.now().isoformat(),
    }
    safe_save(_PUSH_TOKENS, payload)
    return payload


def _load_push_state() -> dict:
    raw_state = safe_load(_PUSH_STATE, default={})
    if not isinstance(raw_state, dict):
        return {}
    return {
        "last_takeover_sent_at": str(raw_state.get("last_takeover_sent_at"))
        if raw_state.get("last_takeover_sent_at")
        else None,
        "last_takeover_sent_status": str(raw_state.get("last_takeover_sent_status"))
        if raw_state.get("last_takeover_sent_status")
        else None,
        "last_takeover_fingerprint": str(raw_state.get("last_takeover_fingerprint"))
        if raw_state.get("last_takeover_fingerprint")
        else None,
        "last_takeover_preview_at": str(raw_state.get("last_takeover_preview_at"))
        if raw_state.get("last_takeover_preview_at")
        else None,
        "takeover_auto_enabled": bool(raw_state.get("takeover_auto_enabled", False)),
        "last_takeover_auto_run_at": str(raw_state.get("last_takeover_auto_run_at"))
        if raw_state.get("last_takeover_auto_run_at")
        else None,
        "last_takeover_auto_run_status": str(raw_state.get("last_takeover_auto_run_status"))
        if raw_state.get("last_takeover_auto_run_status")
        else None,
        "last_industry_research_sent_at": str(raw_state.get("last_industry_research_sent_at"))
        if raw_state.get("last_industry_research_sent_at")
        else None,
        "last_industry_research_sent_status": str(raw_state.get("last_industry_research_sent_status"))
        if raw_state.get("last_industry_research_sent_status")
        else None,
    }


def _save_push_state(state: dict) -> dict:
    payload = {
        "last_takeover_sent_at": state.get("last_takeover_sent_at"),
        "last_takeover_sent_status": state.get("last_takeover_sent_status"),
        "last_takeover_fingerprint": state.get("last_takeover_fingerprint"),
        "last_takeover_preview_at": state.get("last_takeover_preview_at"),
        "takeover_auto_enabled": bool(state.get("takeover_auto_enabled", False)),
        "last_takeover_auto_run_at": state.get("last_takeover_auto_run_at"),
        "last_takeover_auto_run_status": state.get("last_takeover_auto_run_status"),
        "last_industry_research_sent_at": state.get("last_industry_research_sent_at"),
        "last_industry_research_sent_status": state.get("last_industry_research_sent_status"),
    }
    safe_save(_PUSH_STATE, payload)
    return payload


def _is_valid_expo_push_token(token: str) -> bool:
    return (
        isinstance(token, str)
        and token.endswith("]")
        and (token.startswith("ExponentPushToken[") or token.startswith("ExpoPushToken["))
    )


def _active_push_devices(registry: dict, username: str) -> list[dict]:
    devices = registry.get("devices", [])
    if not isinstance(devices, list):
        return []

    return [
        _normalize_push_device(device)
        for device in devices
        if isinstance(device, dict)
        and device.get("username") == username
        and device.get("status", "active") == "active"
    ]


def _register_push_device(
    user: AppUser,
    payload: PushDeviceRegistrationRequest,
) -> PushRegistrationResult:
    expo_push_token = payload.expo_push_token.strip()
    if not _is_valid_expo_push_token(expo_push_token):
        raise HTTPException(status_code=400, detail="Expo Push Token 格式无效")

    registry = _load_push_registry()
    devices = registry.get("devices", [])
    now = datetime.now().isoformat()
    normalized_device = {
        "username": user.username,
        "platform": (payload.platform or "unknown").strip().lower() or "unknown",
        "expo_push_token": expo_push_token,
        "device_name": (payload.device_name or "未命名设备").strip() or "未命名设备",
        "app_version": (payload.app_version or "").strip(),
        "permission_state": (payload.permission_state or "unknown").strip() or "unknown",
        "is_physical_device": payload.is_physical_device,
        "status": "active",
        "last_seen_at": now,
        "last_push_at": None,
        "last_push_status": None,
        "last_error": None,
    }

    existing_index = next(
        (
            index
            for index, device in enumerate(devices)
            if isinstance(device, dict) and device.get("expo_push_token") == expo_push_token
        ),
        None,
    )
    if existing_index is not None:
        existing = _normalize_push_device(devices[existing_index])
        normalized_device["last_push_at"] = existing.get("last_push_at")
        normalized_device["last_push_status"] = existing.get("last_push_status")
        normalized_device["last_error"] = existing.get("last_error")
        devices[existing_index] = normalized_device
        message = "远程推送设备已更新。"
    else:
        devices.append(normalized_device)
        message = "远程推送设备已注册。"

    registry["devices"] = devices
    registry = _save_push_registry(registry)
    active_devices = len(_active_push_devices(registry, user.username))
    takeover_dispatch = _dispatch_takeover_after_registration(user, expo_push_token)

    return PushRegistrationResult(
        success=True,
        message=message,
        device=_push_device_model(normalized_device),
        active_devices=active_devices,
        takeover_dispatch=takeover_dispatch,
    )


def _dispatch_takeover_after_registration(
    user: AppUser,
    expo_push_token: str,
) -> Optional[PushDispatchResult]:
    push_state = _load_push_state()
    if not push_state.get("takeover_auto_enabled"):
        return None

    message = _build_takeover_message()
    if not message:
        return None

    registry = _load_push_registry()
    target_device = next(
        (
            device
            for device in _active_push_devices(registry, user.username)
            if device.get("expo_push_token") == expo_push_token
        ),
        None,
    )
    if target_device is None:
        return None

    fingerprint = _takeover_fingerprint(message)
    if target_device.get("last_takeover_fingerprint") == fingerprint:
        return None

    cooldown_remaining = _takeover_auto_cooldown_remaining(push_state)
    now = datetime.now().isoformat()
    if cooldown_remaining > 0:
        push_state["last_takeover_auto_run_at"] = now
        push_state["last_takeover_auto_run_status"] = "cooldown"
        _save_push_state(push_state)
        return PushDispatchResult(
            success=True,
            dry_run=False,
            targeted_devices=0,
            sent_devices=0,
            failed_devices=0,
            tickets=[
                PushDispatchTicket(
                    expo_push_token=expo_push_token,
                    status="cooldown",
                    message=f"自动补发冷却中，约 {cooldown_remaining} 秒后再试。",
                )
            ],
        )

    result = _dispatch_push_takeover(
        user,
        PushTakeoverRequest(target_token=expo_push_token, force=True),
    )
    push_state = _load_push_state()
    push_state["last_takeover_auto_run_at"] = now
    first_ticket_status = result.tickets[0].status if result.tickets else ("ok" if result.success else "error")
    push_state["last_takeover_auto_run_status"] = f"register:{first_ticket_status}"
    _save_push_state(push_state)
    return result


def _send_expo_push_messages(messages: list[dict]) -> list[dict]:
    body = json.dumps(messages, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if _EXPO_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {_EXPO_ACCESS_TOKEN}"

    request = urllib.request.Request(
        _EXPO_PUSH_API_URL,
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(
            status_code=502,
            detail=f"Expo Push 服务返回错误: {detail or exc.reason}",
        ) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Expo Push 服务不可达: {exc.reason}",
        ) from exc

    result = payload.get("data")
    if isinstance(result, dict):
        return [result]
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    raise HTTPException(status_code=502, detail="Expo Push 响应格式异常")


def _dispatch_push_payload(
    user: AppUser,
    *,
    title: str,
    body: str,
    route: str,
    source: str,
    dry_run: bool = False,
    target_token: Optional[str] = None,
) -> PushDispatchResult:
    registry = _load_push_registry()
    devices = _active_push_devices(registry, user.username)
    if target_token:
        devices = [device for device in devices if device.get("expo_push_token") == target_token]

    devices = [
        device for device in devices if _is_valid_expo_push_token(device.get("expo_push_token", ""))
    ]
    if dry_run:
        if not devices:
            return PushDispatchResult(
                success=True,
                dry_run=True,
                targeted_devices=0,
                sent_devices=0,
                failed_devices=0,
                tickets=[
                    PushDispatchTicket(
                        expo_push_token="(none)",
                        status="dry_run",
                        message="当前没有可用设备，已完成消息预演，请先在真机点一次“同步远程推送”。",
                    )
                ],
            )
        return PushDispatchResult(
            success=True,
            dry_run=True,
            targeted_devices=len(devices),
            sent_devices=0,
            failed_devices=0,
            tickets=[
                PushDispatchTicket(
                    expo_push_token=device["expo_push_token"],
                    status="dry_run",
                    message="已命中设备，但未实际调用 Expo Push 服务。",
                )
                for device in devices
            ],
        )

    if not devices:
        raise HTTPException(status_code=404, detail="当前账号没有可用的远程推送设备")

    messages = [
        {
            "to": device["expo_push_token"],
            "title": title,
            "body": body,
            "sound": "default",
            "channelId": _PUSH_CHANNEL_ID,
            "data": {
                "route": route,
                "source": source,
            },
        }
        for device in devices
    ]
    results = _send_expo_push_messages(messages)

    tickets: list[PushDispatchTicket] = []
    sent_devices = 0
    failed_devices = 0
    by_token = {device["expo_push_token"]: device for device in registry.get("devices", [])}
    push_time = datetime.now().isoformat()

    for index, device in enumerate(devices):
        result = results[index] if index < len(results) else {}
        status = str(result.get("status") or "error")
        message = result.get("message")
        details = result.get("details")
        ticket_id = result.get("id")

        if status == "ok":
            sent_devices += 1
        else:
            failed_devices += 1

        tickets.append(
            PushDispatchTicket(
                expo_push_token=device["expo_push_token"],
                status=status,
                ticket_id=str(ticket_id) if ticket_id else None,
                message=str(message) if message else None,
                details=json.dumps(details, ensure_ascii=False)
                if isinstance(details, (dict, list))
                else (str(details) if details else None),
            )
        )

        registry_device = by_token.get(device["expo_push_token"])
        if registry_device is not None:
            registry_device["last_push_at"] = push_time
            registry_device["last_push_status"] = status
            registry_device["last_error"] = None if status == "ok" else (str(message) if message else None)

    _save_push_registry(registry)
    return PushDispatchResult(
        success=failed_devices == 0,
        dry_run=False,
        targeted_devices=len(devices),
        sent_devices=sent_devices,
        failed_devices=failed_devices,
        tickets=tickets,
    )


def _dispatch_push_test(user: AppUser, payload: PushTestRequest) -> PushDispatchResult:
    return _dispatch_push_payload(
        user,
        title=payload.title,
        body=payload.body,
        route=payload.route or "/alerts",
        source="remote_test",
        dry_run=payload.dry_run,
        target_token=payload.target_token,
    )


def _dispatch_push_takeover(user: AppUser, payload: PushTakeoverRequest) -> PushDispatchResult:
    message = _build_takeover_message()
    if not message:
        raise HTTPException(status_code=404, detail="当前没有可用的接管判断可下发")

    if not payload.dry_run:
        status = _build_takeover_push_status(user)
        if status.active_devices == 0:
            raise HTTPException(status_code=404, detail="当前账号没有可用的远程推送设备")
        if not payload.force and not status.should_send:
            return PushDispatchResult(
                success=True,
                dry_run=False,
                targeted_devices=0,
                sent_devices=0,
                failed_devices=0,
                tickets=[
                    PushDispatchTicket(
                        expo_push_token="(none)",
                        status="skipped",
                        message=status.summary,
                    )
                ],
            )

    title = str(message.get("title") or "综合榜 接管判断")
    body = str(message.get("body") or "综合榜当前判断已更新。")
    result = _dispatch_push_payload(
        user,
        title=title,
        body=body,
        route="/(tabs)/signals",
        source="takeover",
        dry_run=payload.dry_run,
        target_token=payload.target_token,
    )
    now = datetime.now().isoformat()
    state = _load_push_state()
    if payload.dry_run:
        state["last_takeover_preview_at"] = now
    else:
        state["last_takeover_sent_at"] = now
        state["last_takeover_sent_status"] = "ok" if result.success else "partial"
        fingerprint = _takeover_fingerprint(message)
        state["last_takeover_fingerprint"] = fingerprint

        registry = _load_push_registry()
        by_token = {device.get("expo_push_token"): device for device in registry.get("devices", [])}
        for ticket in result.tickets:
            if ticket.status != "ok":
                continue
            registry_device = by_token.get(ticket.expo_push_token)
            if registry_device is None:
                continue
            registry_device["last_takeover_push_at"] = now
            registry_device["last_takeover_fingerprint"] = fingerprint
        _save_push_registry(registry)
    _save_push_state(state)
    return result


def _build_industry_research_push_copy(
    before: IndustryCapitalDirection,
    after: IndustryCapitalDirection,
    latest_item: IndustryCapitalResearchItem,
) -> tuple[str, str]:
    title = f"{after.direction} 调研更新"
    if before.research_signal_label != after.research_signal_label:
        title = f"{after.direction} {after.research_signal_label}"

    change_parts: list[str] = []
    if before.research_signal_label != after.research_signal_label:
        change_parts.append(f"调研信号 {before.research_signal_label}->{after.research_signal_label}")

    before_band = _industry_capital_priority_band(before.priority_score)
    after_band = _industry_capital_priority_band(after.priority_score)
    if before_band != after_band or abs(after.priority_score - before.priority_score) >= 1.5:
        change_parts.append(f"优先级 {before.priority_score:.1f}->{after.priority_score:.1f}")
    if before.current_timeline_stage != after.current_timeline_stage:
        change_parts.append(f"阶段 {before.current_timeline_stage}->{after.current_timeline_stage}")
    if before.latest_catalyst_title != after.latest_catalyst_title:
        change_parts.append(f"最新催化 {after.latest_catalyst_title}")

    if latest_item.company_code or latest_item.company_name:
        company_label = " ".join(
            part for part in [latest_item.company_code or "", latest_item.company_name or ""] if part
        ).strip()
        if company_label:
            change_parts.append(f"公司 {company_label}")

    body = (
        f"{after.focus_sector} / {after.strategic_label} / 事业{after.business_horizon} / 资本{after.capital_horizon}。"
        f" 阶段：{after.current_timeline_stage}。最新催化：{after.latest_catalyst_title}。"
        f" 最新回写：{latest_item.title} / {latest_item.source} / {latest_item.status}。"
    )
    if change_parts:
        body += " 变化：" + "，".join(change_parts) + "。"
    body += f" 下一步：{after.research_next_action}"
    return title, body


def _dispatch_industry_research_push(
    user: AppUser,
    before: IndustryCapitalDirection,
    after: IndustryCapitalDirection,
    latest_item: IndustryCapitalResearchItem,
) -> Optional[PushDispatchResult]:
    registry = _load_push_registry()
    if not _active_push_devices(registry, user.username):
        return None

    title, body = _build_industry_research_push_copy(before, after, latest_item)
    try:
        result = _dispatch_push_payload(
            user,
            title=title,
            body=body,
            route=_industry_capital_route(after),
            source="industry_research",
            dry_run=False,
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        state = _load_push_state()
        state["last_industry_research_sent_at"] = datetime.now().isoformat()
        state["last_industry_research_sent_status"] = f"http_{exc.status_code}"
        _save_push_state(state)
        return None
    except Exception:
        state = _load_push_state()
        state["last_industry_research_sent_at"] = datetime.now().isoformat()
        state["last_industry_research_sent_status"] = "error"
        _save_push_state(state)
        return None

    state = _load_push_state()
    state["last_industry_research_sent_at"] = datetime.now().isoformat()
    state["last_industry_research_sent_status"] = "ok" if result.success else "partial"
    _save_push_state(state)
    return result


def _run_takeover_auto_push(user: AppUser, *, force: bool = False) -> PushDispatchResult:
    push_state = _load_push_state()
    status = _build_takeover_push_status(user)
    cooldown_remaining = _takeover_auto_cooldown_remaining(push_state)

    if status.active_devices == 0:
        result = PushDispatchResult(
            success=True,
            dry_run=False,
            targeted_devices=0,
            sent_devices=0,
            failed_devices=0,
            tickets=[
                PushDispatchTicket(
                    expo_push_token="(none)",
                    status="no_device",
                    message=status.summary,
                )
            ],
        )
        push_state["last_takeover_auto_run_at"] = datetime.now().isoformat()
        push_state["last_takeover_auto_run_status"] = "no_device"
        _save_push_state(push_state)
        return result

    if not push_state.get("takeover_auto_enabled") and not force:
        result = PushDispatchResult(
            success=True,
            dry_run=False,
            targeted_devices=0,
            sent_devices=0,
            failed_devices=0,
            tickets=[
                PushDispatchTicket(
                    expo_push_token="(none)",
                    status="disabled",
                    message="自动下发未开启，当前只做手工判断。",
                )
            ],
        )
        push_state["last_takeover_auto_run_at"] = datetime.now().isoformat()
        push_state["last_takeover_auto_run_status"] = "disabled"
        _save_push_state(push_state)
        return result

    if cooldown_remaining > 0 and not force:
        result = PushDispatchResult(
            success=True,
            dry_run=False,
            targeted_devices=0,
            sent_devices=0,
            failed_devices=0,
            tickets=[
                PushDispatchTicket(
                    expo_push_token="(none)",
                    status="cooldown",
                    message=f"自动下发冷却中，约 {cooldown_remaining} 秒后再试。",
                )
            ],
        )
        push_state["last_takeover_auto_run_at"] = datetime.now().isoformat()
        push_state["last_takeover_auto_run_status"] = "cooldown"
        _save_push_state(push_state)
        return result

    result = _dispatch_push_takeover(user, PushTakeoverRequest(force=force))
    push_state = _load_push_state()
    push_state["last_takeover_auto_run_at"] = datetime.now().isoformat()
    first_ticket_status = result.tickets[0].status if result.tickets else ("ok" if result.success else "error")
    push_state["last_takeover_auto_run_status"] = first_ticket_status
    _save_push_state(push_state)
    return result


def _strategy_keys(strategy: dict) -> set[str]:
    keys = set()
    for value in [strategy.get("id"), strategy.get("name")]:
        if isinstance(value, str) and value:
            keys.add(value)
    for value in strategy.get("cli_aliases", []):
        if isinstance(value, str) and value:
            keys.add(value)
    return keys


def _scorecard_matches_strategy(record: dict, strategy: dict) -> bool:
    record_strategy = record.get("strategy")
    if not isinstance(record_strategy, str) or not record_strategy:
        return False
    return record_strategy in _strategy_keys(strategy)


def _scorecard_return_pct(record: dict) -> Optional[float]:
    return _to_float(record.get("return_pct")) or _to_float(record.get("net_return_pct"))


def _scorecard_is_win(record: dict) -> bool:
    result = record.get("result")
    if isinstance(result, str) and result:
        return result.lower() == "win"
    ret = _scorecard_return_pct(record)
    return ret is not None and ret > 0


def _app_accounts() -> dict[str, dict]:
    accounts = {
        _APP_AUTH_USERNAME: {
            "username": _APP_AUTH_USERNAME,
            "password": _APP_AUTH_PASSWORD,
            "legacy_passwords": ["admin123", "Alpha123456"],
            "display_name": _APP_AUTH_DISPLAY_NAME,
            "role": "operator",
        }
    }
    if _APP_PILOT_USERNAME and _APP_PILOT_PASSWORD:
        accounts[_APP_PILOT_USERNAME] = {
            "username": _APP_PILOT_USERNAME,
            "password": _APP_PILOT_PASSWORD,
            "legacy_passwords": ["pilot123", "Pilot123456"],
            "display_name": _APP_PILOT_DISPLAY_NAME,
            "role": "pilot",
        }
    return accounts


def _resolve_app_account(username: str) -> Optional[dict]:
    if not isinstance(username, str) or not username:
        return None
    return _app_accounts().get(username)


def _normalize_feedback_item(raw_item: dict) -> dict:
    now = datetime.now().isoformat()
    return {
        "id": str(raw_item.get("id") or f"fb_{uuid.uuid4().hex[:10]}"),
        "username": str(raw_item.get("username") or ""),
        "title": str(raw_item.get("title") or "未命名意见"),
        "message": str(raw_item.get("message") or ""),
        "category": str(raw_item.get("category") or "general"),
        "priority": str(raw_item.get("priority") or "medium"),
        "decision_status": str(raw_item.get("decision_status") or "pending"),
        "owner_note": str(raw_item.get("owner_note") or ""),
        "source_type": str(raw_item.get("source_type") or ""),
        "source_id": str(raw_item.get("source_id") or ""),
        "source_route": str(raw_item.get("source_route") or ""),
        "created_at": str(raw_item.get("created_at") or now),
        "updated_at": str(raw_item.get("updated_at") or raw_item.get("created_at") or now),
        "decided_at": str(raw_item.get("decided_at")) if raw_item.get("decided_at") else None,
        "decided_by": str(raw_item.get("decided_by")) if raw_item.get("decided_by") else None,
    }


def _feedback_item_model(raw_item: dict) -> FeedbackItem:
    item = _normalize_feedback_item(raw_item)
    return FeedbackItem(
        id=item["id"],
        username=item["username"],
        title=item["title"],
        message=item["message"],
        category=item["category"],
        priority=item["priority"],
        decision_status=item["decision_status"],
        owner_note=item["owner_note"],
        source_type=item["source_type"],
        source_id=item["source_id"],
        source_route=item["source_route"],
        created_at=item["created_at"],
        updated_at=item["updated_at"],
        decided_at=item["decided_at"],
        decided_by=item["decided_by"],
    )


def _normalize_app_message(raw_item: dict) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "id": str(raw_item.get("id") or f"msg_{uuid.uuid4().hex[:10]}"),
        "title": str(raw_item.get("title") or "未命名消息"),
        "body": str(raw_item.get("body") or ""),
        "preview": str(raw_item.get("preview") or raw_item.get("body") or "")[:140],
        "level": str(raw_item.get("level") or "neutral"),
        "channel": str(raw_item.get("channel") or "wechat_mirror"),
        "created_at": str(raw_item.get("created_at") or now),
        "route": str(raw_item.get("route")) if raw_item.get("route") else None,
    }


def _app_message_model(raw_item: dict) -> AppMessage:
    item = _normalize_app_message(raw_item)
    return AppMessage(
        id=item["id"],
        title=item["title"],
        body=item["body"],
        preview=item["preview"],
        level=item["level"],
        channel=item["channel"],
        created_at=item["created_at"],
        route=item["route"],
    )


def _load_app_message_center() -> dict:
    raw_box = safe_load(_APP_MESSAGE_CENTER, default={})
    if not isinstance(raw_box, dict):
        raw_box = {}

    raw_items = raw_box.get("items", [])
    if not isinstance(raw_items, list):
        raw_items = []

    return {
        "items": [_normalize_app_message(item) for item in raw_items if isinstance(item, dict)],
        "last_update": str(raw_box.get("last_update") or datetime.now().isoformat(timespec="seconds")),
    }


def _save_app_message_center(box: dict) -> dict:
    raw_items = box.get("items", [])
    if not isinstance(raw_items, list):
        raw_items = []

    payload = {
        "items": [_normalize_app_message(item) for item in raw_items if isinstance(item, dict)],
        "last_update": datetime.now().isoformat(timespec="seconds"),
    }
    safe_save(_APP_MESSAGE_CENTER, payload)
    _invalidate_runtime_cache("app_messages", "action_board")
    return payload


def _append_app_messages(new_items: list[dict]) -> dict:
    center = _load_app_message_center()
    items = list(center.get("items", []))
    existing_ids = {str(item.get("id") or "") for item in items}
    for item in new_items:
        normalized = _normalize_app_message(item)
        if normalized["id"] in existing_ids:
            continue
        items.append(normalized)
        existing_ids.add(normalized["id"])
    items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return _save_app_message_center({"items": items[:120]})


def _load_sector_alert_history() -> dict:
    raw_box = safe_load(_SECTOR_ALERTS, default={})
    if not isinstance(raw_box, dict):
        raw_box = {}

    today_log = raw_box.get("today_log", [])
    if not isinstance(today_log, list):
        today_log = []

    return {
        "alerts": raw_box.get("alerts", {}),
        "today_log": [item for item in today_log if isinstance(item, dict)],
    }


def _load_feedback_box() -> dict:
    raw_box = safe_load(_FEEDBACK_BOX, default={})
    if not isinstance(raw_box, dict):
        raw_box = {}

    raw_items = raw_box.get("items", [])
    if not isinstance(raw_items, list):
        raw_items = []

    return {
        "items": [_normalize_feedback_item(item) for item in raw_items if isinstance(item, dict)],
        "last_update": str(raw_box.get("last_update") or datetime.now().isoformat()),
    }


def _normalize_industry_capital_research_item(raw_item: dict) -> dict:
    now = datetime.now().isoformat()
    return {
        "id": str(raw_item.get("id") or f"icr_{uuid.uuid4().hex[:10]}"),
        "direction_id": str(raw_item.get("direction_id") or ""),
        "direction": str(raw_item.get("direction") or "未命名方向"),
        "title": str(raw_item.get("title") or "未命名调研"),
        "note": str(raw_item.get("note") or ""),
        "source": str(raw_item.get("source") or "产业调研"),
        "status": str(raw_item.get("status") or "待验证"),
        "company_code": str(raw_item.get("company_code")) if raw_item.get("company_code") else None,
        "company_name": str(raw_item.get("company_name")) if raw_item.get("company_name") else None,
        "created_at": str(raw_item.get("created_at") or now),
        "updated_at": str(raw_item.get("updated_at") or raw_item.get("created_at") or now),
        "author": str(raw_item.get("author") or ""),
    }


def _industry_capital_research_item_model(raw_item: dict) -> IndustryCapitalResearchItem:
    item = _normalize_industry_capital_research_item(raw_item)
    return IndustryCapitalResearchItem(
        id=item["id"],
        direction_id=item["direction_id"],
        direction=item["direction"],
        title=item["title"],
        note=item["note"],
        source=item["source"],
        status=item["status"],
        company_code=item["company_code"],
        company_name=item["company_name"],
        created_at=item["created_at"],
        updated_at=item["updated_at"],
        author=item["author"],
    )


def _load_industry_capital_research_log() -> dict:
    def builder() -> dict:
        raw_box = safe_load(_INDUSTRY_CAPITAL_RESEARCH_LOG, default={})
        if not isinstance(raw_box, dict):
            raw_box = {}

        raw_items = raw_box.get("items", [])
        if not isinstance(raw_items, list):
            raw_items = []

        return {
            "items": [
                _normalize_industry_capital_research_item(item)
                for item in raw_items
                if isinstance(item, dict)
            ],
            "last_update": str(raw_box.get("last_update") or datetime.now().isoformat()),
        }

    return _cached_runtime_value(
        "load_industry_capital_research_log",
        "default",
        ttl_seconds=6,
        dependency_paths=_runtime_cache_paths(_INDUSTRY_CAPITAL_RESEARCH_LOG),
        builder=builder,
    )


def _save_industry_capital_research_log(box: dict) -> dict:
    items = box.get("items", [])
    if not isinstance(items, list):
        items = []

    payload = {
        "items": [
            _normalize_industry_capital_research_item(item)
            for item in items
            if isinstance(item, dict)
        ],
        "last_update": datetime.now().isoformat(),
    }
    safe_save(_INDUSTRY_CAPITAL_RESEARCH_LOG, payload)
    _invalidate_runtime_cache(
        "load_industry_capital_research_log",
        "industry_capital_map",
        "industry_capital_detail",
        "app_messages",
        "action_board",
    )
    return payload


def _list_industry_capital_research_items(
    direction_id: str,
    *,
    limit: int = 12,
) -> list[IndustryCapitalResearchItem]:
    box = _load_industry_capital_research_log()
    items = [
        item
        for item in box.get("items", [])
        if item.get("direction_id") == direction_id
    ]
    items.sort(
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
        reverse=True,
    )
    return [_industry_capital_research_item_model(item) for item in items[: max(1, limit)]]


def _submit_industry_capital_research(
    direction_id: str,
    payload: IndustryCapitalResearchSubmissionRequest,
    user: AppUser,
) -> IndustryCapitalResearchSubmissionResult:
    title = payload.title.strip()
    note = payload.note.strip()
    if not title:
        raise HTTPException(status_code=400, detail="调研标题不能为空")
    if not note:
        raise HTTPException(status_code=400, detail="调研内容不能为空")

    direction_before = _build_industry_capital_detail(direction_id)
    box = _load_industry_capital_research_log()
    now = datetime.now().isoformat()
    item = _normalize_industry_capital_research_item(
        {
            "id": f"icr_{uuid.uuid4().hex[:10]}",
            "direction_id": direction_before.id,
            "direction": direction_before.direction,
            "title": title,
            "note": note,
            "source": payload.source.strip() or "产业调研",
            "status": payload.status.strip() or "待验证",
            "company_code": (payload.company_code or "").strip() or None,
            "company_name": (payload.company_name or "").strip() or None,
            "created_at": now,
            "updated_at": now,
            "author": user.username,
        }
    )
    box["items"].insert(0, item)
    _save_industry_capital_research_log(box)
    direction_after = _build_industry_capital_detail(direction_id)
    total_items = sum(1 for entry in box["items"] if entry.get("direction_id") == direction_before.id)
    change_messages = _build_industry_capital_change_messages(
        direction_before,
        direction_after,
        _industry_capital_research_item_model(item),
    )
    if change_messages:
        _append_app_messages(change_messages)
    _dispatch_industry_research_push(
        user,
        direction_before,
        direction_after,
        _industry_capital_research_item_model(item),
    )

    return IndustryCapitalResearchSubmissionResult(
        success=True,
        message="调研记录已回写到方向档案。",
        item=_industry_capital_research_item_model(item),
        total_items=total_items,
    )


def _research_log_recency_weight(timestamp: Optional[str]) -> float:
    if not timestamp:
        return 0.45
    try:
        signal_time = datetime.fromisoformat(str(timestamp))
    except ValueError:
        return 0.45
    hours = max(0.0, (datetime.now() - signal_time).total_seconds() / 3600)
    if hours <= 72:
        return 1.0
    if hours <= 7 * 24:
        return 0.82
    if hours <= 14 * 24:
        return 0.64
    if hours <= 30 * 24:
        return 0.48
    return 0.32


def _research_log_status_weight(status: str) -> float:
    normalized = str(status or "").strip()
    if normalized == "已验证":
        return 1.0
    if normalized == "有阻力":
        return -1.0
    return 0.28


def _research_log_source_weight(source: str) -> float:
    normalized = str(source or "").strip()
    return {
        "客户反馈": 1.18,
        "供应链验证": 1.08,
        "产业调研": 0.86,
        "政策跟踪": 0.72,
    }.get(normalized, 0.8)


def _industry_research_signal_label(score: float, has_items: bool) -> str:
    if not has_items:
        return "暂无回写"
    if score >= 62:
        return "验证增强"
    if score <= 42:
        return "出现阻力"
    return "继续验证"


def _build_industry_capital_research_signal(direction_id: str) -> dict[str, object]:
    items = _list_industry_capital_research_items(direction_id, limit=24)
    if not items:
        return {
            "score": 50.0,
            "label": "暂无回写",
            "summary": "当前还没有调研回写，先补客户、供应链和政策验证。",
            "next_action": "先补第一次方向调研记录，再决定要不要提高方向优先级。",
            "companies": {},
        }

    verified_count = 0
    blocked_count = 0
    pending_count = 0
    raw_score = 50.0
    company_scores: dict[str, float] = {}
    company_latest_notes: dict[str, str] = {}

    for item in items:
        status_weight = _research_log_status_weight(item.status)
        source_weight = _research_log_source_weight(item.source)
        recency_weight = _research_log_recency_weight(item.updated_at)
        signal_value = status_weight * source_weight * recency_weight
        raw_score += signal_value * 10.5

        if item.status == "已验证":
            verified_count += 1
        elif item.status == "有阻力":
            blocked_count += 1
        else:
            pending_count += 1

        if item.company_code:
            company_scores[item.company_code] = company_scores.get(item.company_code, 50.0) + signal_value * 14.0
            company_latest_notes.setdefault(
                item.company_code,
                f"{item.source} / {item.status}：{_truncate_hint(item.note, limit=34)}",
            )

    direction_score = round(
        _clamp(
            raw_score + verified_count * 1.8 - blocked_count * 1.6 + min(pending_count, 3) * 0.6,
            24.0,
            88.0,
        ),
        1,
    )
    label = _industry_research_signal_label(direction_score, has_items=True)
    latest_item = items[0]
    latest_summary = _truncate_hint(latest_item.title, limit=24)

    if label == "验证增强":
        summary = (
            f"最近 {verified_count} 条已验证回写，方向开始从判断走向兑现。"
            f" 最新进展：{latest_summary}。"
        )
        next_action = "优先复核已验证对象，把客户、订单、价格和承接信号连起来看。"
    elif label == "出现阻力":
        summary = (
            f"最近出现 {blocked_count} 条阻力回写，方向还没走到顺畅兑现。"
            f" 最新卡点：{latest_summary}。"
        )
        next_action = "先定位阻力是在政策、客户、价格还是供应链，再决定要不要下调优先级。"
    else:
        summary = (
            f"当前已有 {len(items)} 条调研回写，但还在验证窗口里。"
            f" 最新记录：{latest_summary}。"
        )
        next_action = "继续补客户、供应链和订单验证，等已验证记录再厚一点。"

    companies: dict[str, dict[str, object]] = {}
    for code, raw_company_score in company_scores.items():
        company_score = round(_clamp(raw_company_score, 28.0, 90.0), 1)
        companies[code] = {
            "score": company_score,
            "label": _industry_research_signal_label(company_score, has_items=True),
            "note": company_latest_notes.get(code),
        }

    return {
        "score": direction_score,
        "label": label,
        "summary": summary,
        "next_action": next_action,
        "companies": companies,
    }


def _industry_capital_priority_score(
    strategic_score: float,
    research_signal_score: float,
    participation_label: str,
    stage_label: str,
    official_freshness_score: float = 50.0,
) -> float:
    priority = strategic_score
    priority += (research_signal_score - 50.0) * 0.36
    priority += (official_freshness_score - 50.0) * 0.18

    if participation_label == "连涨接力":
        priority += 4.5
    elif participation_label == "中期波段":
        priority += 3.0
    elif participation_label == "主线观察":
        priority += 1.5

    if stage_label == "承压观察":
        priority -= 3.5
    elif stage_label == "主升波段":
        priority += 2.0
    elif stage_label == "中期扩散":
        priority += 1.2

    return round(_clamp(priority, 25.0, 96.0), 1)


def _industry_capital_priority_band(score: float) -> str:
    if score >= 62:
        return "重点推进"
    if score >= 50:
        return "持续跟踪"
    return "降级观察"


def _industry_capital_company_lookup(
    direction: IndustryCapitalDirection,
    code: Optional[str],
) -> Optional[IndustryCapitalCompanyItem]:
    target = str(code or "").strip()
    if not target:
        return None
    for item in direction.company_watchlist:
        if item.code == target:
            return item
    return None


def _build_industry_capital_change_messages(
    before: IndustryCapitalDirection,
    after: IndustryCapitalDirection,
    latest_item: IndustryCapitalResearchItem,
) -> list[dict]:
    route = _industry_capital_route(after)
    created_at = latest_item.updated_at or datetime.now().isoformat(timespec="seconds")
    messages: list[dict] = []

    if before.research_signal_label != after.research_signal_label:
        level = "warning" if after.research_signal_label == "出现阻力" else "info"
        body = (
            f"{after.direction} 的调研信号从 {before.research_signal_label} 变为 {after.research_signal_label}。"
            f" 最新回写：{latest_item.title} / {latest_item.source} / {latest_item.status}。"
            f" {after.research_next_action}"
        )
        messages.append(
            {
                "id": f"msg_industry_research_label_{after.id}_{latest_item.id}",
                "title": f"{after.direction} {after.research_signal_label}",
                "body": body,
                "preview": body,
                "level": level,
                "channel": "system_update",
                "created_at": created_at,
                "route": route,
            }
        )

    before_band = _industry_capital_priority_band(before.priority_score)
    after_band = _industry_capital_priority_band(after.priority_score)
    if before_band != after_band:
        change_word = "升至" if after.priority_score >= before.priority_score else "降至"
        level = "warning" if after_band == "降级观察" else "info"
        body = (
            f"{after.direction} 的综合优先级从 {before.priority_score:.1f} 变为 {after.priority_score:.1f}，"
            f" 当前档位 {change_word}{after_band}。"
            f" 最新回写：{latest_item.title}。{after.research_summary}"
        )
        messages.append(
            {
                "id": f"msg_industry_priority_{after.id}_{latest_item.id}",
                "title": f"{after.direction} 优先级{change_word}{after_band}",
                "body": body,
                "preview": body,
                "level": level,
                "channel": "system_update",
                "created_at": created_at,
                "route": route,
            }
        )

    if before.current_timeline_stage != after.current_timeline_stage:
        level = "warning" if after.current_timeline_stage in {"调研阻力", "承压观察"} else "info"
        body = (
            f"{after.direction} 的方向阶段从 {before.current_timeline_stage} 变为 {after.current_timeline_stage}。"
            f" 最新催化：{after.latest_catalyst_title}。"
            f" 最新回写：{latest_item.title} / {latest_item.source} / {latest_item.status}。"
            f" {after.research_next_action}"
        )
        messages.append(
            {
                "id": f"msg_industry_timeline_stage_{after.id}_{latest_item.id}",
                "title": f"{after.direction} 阶段切换到 {after.current_timeline_stage}",
                "body": body,
                "preview": body,
                "level": level,
                "channel": "system_update",
                "created_at": created_at,
                "route": route,
            }
        )

    if before.latest_catalyst_title != after.latest_catalyst_title:
        body = (
            f"{after.direction} 的最新催化更新为 {after.latest_catalyst_title}。"
            f" {after.latest_catalyst_summary}"
            f" 最新回写：{latest_item.title} / {latest_item.source} / {latest_item.status}。"
        )
        messages.append(
            {
                "id": f"msg_industry_catalyst_{after.id}_{latest_item.id}",
                "title": f"{after.direction} 最新催化更新",
                "body": body,
                "preview": body,
                "level": "info",
                "channel": "system_update",
                "created_at": created_at,
                "route": route,
            }
        )

    if before.official_freshness_label != after.official_freshness_label:
        first_entry = after.official_source_entries[0] if after.official_source_entries else None
        entry_title = first_entry.get("title") if isinstance(first_entry, dict) else "官方原文"
        entry_source = first_entry.get("issuer") if isinstance(first_entry, dict) else "官方口径"
        body = (
            f"{after.direction} 刚刚收到 {entry_source} 的官方原文：{entry_title}。"
            f" 官方新鲜度从 {before.official_freshness_label} 升至 {after.official_freshness_label}。"
            f" 继续盯官宣细节、项目和采购拥堵。"
        )
        messages.append(
            {
                "id": f"msg_industry_official_{after.id}_{latest_item.id}",
                "title": f"{after.direction} 官方新鲜度 {after.official_freshness_label}",
                "body": body,
                "preview": body,
                "level": "info",
                "channel": "system_update",
                "created_at": created_at,
                "route": route,
            }
        )

    before_company = _industry_capital_company_lookup(before, latest_item.company_code)
    after_company = _industry_capital_company_lookup(after, latest_item.company_code)
    if (
        before_company is not None
        and after_company is not None
        and before_company.research_signal_label != after_company.research_signal_label
    ):
        level = "warning" if after_company.research_signal_label == "出现阻力" else "info"
        company_name = after_company.name or latest_item.company_name or latest_item.company_code or "重点公司"
        company_code = after_company.code or latest_item.company_code or ""
        body = (
            f"{company_code} {company_name} 的调研信号从 {before_company.research_signal_label}"
            f" 变为 {after_company.research_signal_label}。"
            f" 最新备注：{after_company.recent_research_note or latest_item.note}"
        )
        messages.append(
            {
                "id": f"msg_industry_company_{after.id}_{company_code}_{latest_item.id}",
                "title": f"{company_code} {company_name} {after_company.research_signal_label}".strip(),
                "body": body,
                "preview": body,
                "level": level,
                "channel": "system_update",
                "created_at": created_at,
                "route": route,
            }
        )

    return messages


def _save_feedback_box(box: dict) -> dict:
    items = box.get("items", [])
    if not isinstance(items, list):
        items = []

    payload = {
        "items": [_normalize_feedback_item(item) for item in items if isinstance(item, dict)],
        "last_update": datetime.now().isoformat(),
    }
    safe_save(_FEEDBACK_BOX, payload)
    return payload


def _list_feedback_items(user: AppUser) -> list[FeedbackItem]:
    box = _load_feedback_box()
    items = box.get("items", [])
    if user.role != "operator":
        items = [item for item in items if item.get("username") == user.username]
    items.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
    return [_feedback_item_model(item) for item in items]


def _submit_feedback(user: AppUser, payload: FeedbackSubmissionRequest) -> FeedbackSubmissionResult:
    title = payload.title.strip()
    message = payload.message.strip()
    if not title:
        raise HTTPException(status_code=400, detail="意见标题不能为空")
    if not message:
        raise HTTPException(status_code=400, detail="意见内容不能为空")

    box = _load_feedback_box()
    now = datetime.now().isoformat()
    item = _normalize_feedback_item(
        {
            "id": f"fb_{uuid.uuid4().hex[:10]}",
            "username": user.username,
            "title": title,
            "message": message,
            "category": payload.category,
            "priority": payload.priority,
            "decision_status": "pending",
            "owner_note": "",
            "source_type": payload.source_type,
            "source_id": payload.source_id,
            "source_route": payload.source_route,
            "created_at": now,
            "updated_at": now,
        }
    )
    box["items"].insert(0, item)
    _save_feedback_box(box)

    return FeedbackSubmissionResult(
        success=True,
        message="意见已进入试验收集箱，是否采纳仍需手动决策。",
        item=_feedback_item_model(item),
        pending_count=sum(1 for feedback in box["items"] if feedback.get("decision_status") == "pending"),
    )


def _decide_feedback(
    feedback_id: str,
    payload: FeedbackDecisionRequest,
    user: AppUser,
) -> FeedbackDecisionResult:
    if user.role != "operator":
        raise HTTPException(status_code=403, detail="只有决策账号可以处理意见")
    if payload.decision not in {"pending", "watchlist", "accepted", "rejected"}:
        raise HTTPException(status_code=400, detail="决策状态不合法")

    box = _load_feedback_box()
    items = box.get("items", [])
    for index, raw_item in enumerate(items):
        if raw_item.get("id") != feedback_id:
            continue

        now = datetime.now().isoformat()
        updated_item = _normalize_feedback_item(raw_item)
        updated_item["decision_status"] = payload.decision
        updated_item["owner_note"] = (payload.owner_note or "").strip()
        updated_item["updated_at"] = now
        updated_item["decided_at"] = now
        updated_item["decided_by"] = user.username
        items[index] = updated_item
        _save_feedback_box(box)

        return FeedbackDecisionResult(
            success=True,
            message="该意见的最终处置状态已更新。",
            item=_feedback_item_model(updated_item),
        )

    raise HTTPException(status_code=404, detail="意见不存在")


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def _app_user_payload(username: str) -> dict:
    account = _resolve_app_account(username) or {
        "display_name": _APP_AUTH_DISPLAY_NAME,
        "role": "pilot",
    }
    return {
        "sub": username,
        "display_name": account.get("display_name", _APP_AUTH_DISPLAY_NAME),
        "role": account.get("role", "pilot"),
    }


def _create_access_token(username: str) -> tuple[str, datetime]:
    expires_at = datetime.now() + timedelta(hours=_APP_AUTH_TOKEN_TTL_HOURS)
    payload = {
        **_app_user_payload(username),
        "exp": int(expires_at.timestamp()),
    }
    payload_segment = _b64url_encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    signature = hmac.new(
        _APP_AUTH_SECRET.encode("utf-8"),
        payload_segment.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload_segment}.{signature}", expires_at


def _decode_access_token(token: str) -> dict:
    if token.count(".") == 2:
        try:
            payload = jwt.decode(
                token,
                _APP_LEGACY_AUTH_SECRET,
                algorithms=["HS256"],
            )
        except Exception as jwt_exc:
            raise HTTPException(status_code=401, detail="令牌签名无效") from jwt_exc

        return {
            "sub": payload.get("sub", ""),
            "display_name": payload.get("display_name", payload.get("sub", _APP_AUTH_DISPLAY_NAME)),
            "role": payload.get("role", "operator"),
            "exp": payload.get("exp", 0),
        }

    try:
        payload_segment, signature = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="令牌格式错误") from exc

    expected_signature = hmac.new(
        _APP_AUTH_SECRET.encode("utf-8"),
        payload_segment.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(status_code=401, detail="令牌签名无效")

    try:
        payload = json.loads(_b64url_decode(payload_segment).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=401, detail="令牌内容无效") from exc

    if int(payload.get("exp", 0)) <= int(time.time()):
        raise HTTPException(status_code=401, detail="令牌已过期")

    return payload

# ================================================================
#  Pydantic Models
# ================================================================

class AppUser(BaseModel):
    username: str
    display_name: str
    role: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    expires_at: str
    user: AppUser


class SystemStatus(BaseModel):
    status: str
    uptime_hours: float
    health_score: int
    today_signals: int
    active_strategies: int
    ooda_cycles: int
    decision_accuracy: float

class StrategyPerformance(BaseModel):
    id: str
    name: str
    status: str
    win_rate: float
    avg_return: float
    signal_count: int
    last_signal_time: Optional[str]

class Signal(BaseModel):
    id: str
    code: str
    name: str
    strategy: str
    score: float
    price: float
    change_pct: float
    buy_price: float
    stop_loss: float
    target_price: float
    risk_reward: float
    timestamp: str
    consensus_count: int  # 多策略共识数


class SignalEntryGuide(BaseModel):
    mode: str
    summary: str
    action: str
    composite_score: float
    setup_label: Optional[str]
    theme_sector: Optional[str]
    sector_bucket: Optional[str]
    theme_alignment: str
    event_bias: str = "中性"
    event_score: float = 50.0
    event_summary: Optional[str] = None
    recommended_first_position_pct: int
    suggested_amount: float
    suggested_quantity: int
    total_assets: float
    max_single_position_pct: int
    max_theme_exposure_pct: int
    target_exposure_pct: float
    deployable_cash: float
    current_theme_exposure_pct: float
    projected_theme_exposure_pct: float
    concentration_summary: Optional[str] = None
    warnings: list[str]


class SignalDetail(BaseModel):
    id: str
    code: str
    name: str
    strategy: str
    strategies: list[str]
    score: float
    price: float
    change_pct: float
    high: float
    low: float
    volume: float
    turnover: float
    buy_price: float
    stop_loss: float
    target_price: float
    risk_reward: float
    timestamp: str
    consensus_count: int
    factor_scores: dict[str, float]
    regime: str
    regime_score: float
    entry_guide: SignalEntryGuide


class StrongMoveCandidate(BaseModel):
    id: str
    signal_id: str
    code: str
    name: str
    strategy: str
    setup_label: str
    conviction: str
    composite_score: float
    continuation_score: float
    swing_score: float
    strategy_win_rate: float
    price: float
    buy_price: float
    stop_loss: float
    target_price: float
    risk_reward: float
    timestamp: str
    thesis: str
    next_step: str
    reasons: list[str]


class ThemeFollower(BaseModel):
    code: str
    name: str
    change_pct: float
    label: str
    buy_price: float
    stop_loss: float
    target_price: float
    risk_reward: float


class ThemeRadarItem(BaseModel):
    id: str
    sector: str
    theme_type: str
    change_pct: float
    score: float
    intensity: str
    timestamp: str
    narrative: str
    action: str
    risk_note: str
    message_hint: Optional[str]
    linked_signal_id: Optional[str]
    linked_code: Optional[str]
    linked_name: Optional[str]
    linked_setup_label: Optional[str]
    followers: list[ThemeFollower]


class ThemeStageItem(BaseModel):
    id: str
    sector: str
    theme_type: str
    intensity: str
    stage_label: str
    participation_label: str
    direction_score: float
    policy_event_score: float
    trend_score: float
    attention_score: float
    capital_preference_score: float
    stage_score: float
    linked_signal_id: Optional[str]
    linked_code: Optional[str]
    linked_name: Optional[str]
    linked_setup_label: Optional[str]
    summary: str
    action: str
    risk_note: str
    drivers: list[str]


class PolicyWatchItem(BaseModel):
    id: str
    direction: str
    policy_bucket: str
    focus_sector: str
    stage_label: str
    participation_label: str
    industry_phase: str
    direction_score: float
    policy_score: float
    trend_score: float
    attention_score: float
    capital_preference_score: float
    linked_signal_id: Optional[str]
    linked_code: Optional[str]
    linked_name: Optional[str]
    linked_setup_label: Optional[str]
    summary: str
    action: str
    risk_note: str
    phase_summary: str
    demand_drivers: list[str]
    supply_drivers: list[str]
    upstream: list[str]
    midstream: list[str]
    downstream: list[str]
    milestones: list[str]
    transmission_paths: list[str]
    drivers: list[str]


class IndustryCapitalOfficialCard(BaseModel):
    title: str
    source: str
    excerpt: str
    why_it_matters: str
    next_watch: str


class IndustryCapitalOfficialSourceEntry(BaseModel):
    title: str
    issuer: str
    published_at: Optional[str] = None
    source_type: str = "官方原文"
    excerpt: str
    reference: Optional[str] = None
    reference_url: Optional[str] = None
    key_points: list[str] = Field(default_factory=list)
    watch_tags: list[str] = Field(default_factory=list)


class IndustryCapitalTimelineEvent(BaseModel):
    id: str
    lane: str
    stage: str
    title: str
    summary: str
    source: Optional[str] = None
    signal_label: str = "观察中"
    emphasis: str = "neutral"
    timestamp: Optional[str] = None
    next_action: Optional[str] = None


class IndustryCapitalCompanyItem(BaseModel):
    code: str
    name: str
    role: str
    chain_position: str
    tracking_reason: str
    action: str
    tracking_score: float = 50.0
    priority_label: str = "持续跟踪"
    market_alignment: str = "待确认"
    next_check: str = "继续跟踪兑现与承接"
    linked_setup_label: Optional[str] = None
    linked_source: Optional[str] = None
    research_signal_score: float = 50.0
    research_signal_label: str = "暂无回写"
    recent_research_note: Optional[str] = None
    timeline_alignment: str = "时间轴待确认"
    catalyst_hint: Optional[str] = None


class IndustryCapitalResearchItem(BaseModel):
    id: str
    direction_id: str
    direction: str
    title: str
    note: str
    source: str
    status: str
    company_code: Optional[str] = None
    company_name: Optional[str] = None
    created_at: str
    updated_at: str
    author: str


class IndustryCapitalResearchSubmissionRequest(BaseModel):
    title: str
    note: str
    source: str = "产业调研"
    status: str = "待验证"
    company_code: Optional[str] = None
    company_name: Optional[str] = None


class IndustryCapitalResearchSubmissionResult(BaseModel):
    success: bool
    message: str
    item: IndustryCapitalResearchItem
    total_items: int


class IndustryCapitalDirection(BaseModel):
    id: str
    direction: str
    policy_bucket: str
    focus_sector: str
    strategic_label: str
    industry_phase: str
    participation_label: str
    business_horizon: str
    capital_horizon: str
    priority_score: float = 50.0
    strategic_score: float
    policy_score: float
    demand_score: float
    supply_score: float
    capital_preference_score: float
    research_signal_score: float = 50.0
    research_signal_label: str = "暂无回写"
    official_freshness_score: float = 50.0
    official_freshness_label: str = "待补官方日期"
    linked_signal_id: Optional[str]
    linked_code: Optional[str]
    linked_name: Optional[str]
    linked_setup_label: Optional[str]
    summary: str
    business_action: str
    capital_action: str
    risk_note: str
    research_summary: str = "当前还没有调研回写，先补客户、供应链和政策验证。"
    research_next_action: str = "先补第一次方向调研记录。"
    upstream: list[str]
    midstream: list[str]
    downstream: list[str]
    demand_drivers: list[str]
    supply_drivers: list[str]
    milestones: list[str]
    transmission_paths: list[str]
    opportunities: list[str]
    official_sources: list[str]
    official_watchpoints: list[str]
    business_checklist: list[str]
    capital_checklist: list[str]
    official_cards: list[IndustryCapitalOfficialCard]
    official_source_entries: list[IndustryCapitalOfficialSourceEntry] = Field(default_factory=list)
    official_documents: list[str]
    timeline_checkpoints: list[str]
    current_timeline_stage: str = "继续观察"
    latest_catalyst_title: str = "等待新的方向催化"
    latest_catalyst_summary: str = "当前先看官方口径、兑现节点和调研回写是否继续强化。"
    timeline_events: list[IndustryCapitalTimelineEvent] = Field(default_factory=list)
    cooperation_targets: list[str]
    cooperation_modes: list[str]
    company_watchlist: list[IndustryCapitalCompanyItem]
    research_targets: list[str]
    validation_signals: list[str]
    drivers: list[str]


class CompositePick(BaseModel):
    id: str
    signal_id: str
    code: str
    name: str
    strategy: str
    theme_sector: Optional[str]
    theme_intensity: Optional[str]
    setup_label: str
    conviction: str
    composite_score: float
    strategy_score: float
    capital_score: float
    theme_score: float
    event_score: float = 50.0
    event_bias: str = "中性"
    event_summary: Optional[str] = None
    event_matched_sector: Optional[str] = None
    source_category: str = "strategy"
    source_label: str = "策略候选"
    horizon_label: str = "短线观察"
    execution_score: float
    first_position_pct: int
    price: float
    buy_price: float
    stop_loss: float
    target_price: float
    risk_reward: float
    timestamp: str
    thesis: str
    action: str
    reasons: list[str]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class PositioningDeployment(BaseModel):
    code: str
    name: str
    setup_label: str
    suggested_position_pct: int
    suggested_amount: float
    theme_sector: Optional[str]
    reason: str


class PositioningPlan(BaseModel):
    mode: str
    regime: str
    regime_score: float
    event_bias: str = "中性"
    event_score: float = 50.0
    event_summary: Optional[str] = None
    event_focus_sector: Optional[str] = None
    current_exposure_pct: float
    target_exposure_pct: float
    deployable_exposure_pct: float
    cash_balance: float
    total_assets: float
    deployable_cash: float
    current_positions: int
    available_slots: int
    max_positions: int
    first_entry_position_pct: int
    max_single_position_pct: int
    max_theme_exposure_pct: int
    top_theme: Optional[str]
    focus: str
    reasons: list[str]
    actions: list[str]
    deployments: list[PositioningDeployment]


class CompositeReplayItem(BaseModel):
    id: str
    trade_date: str
    signal_id: str
    code: str
    name: str
    strategy: str
    setup_label: str
    conviction: str
    composite_score: float
    first_position_pct: int
    theme_sector: Optional[str]
    review_label: str
    verified_days: int
    t1_return_pct: Optional[float] = None
    t3_return_pct: Optional[float] = None
    t5_return_pct: Optional[float] = None
    outcome_summary: str
    review: str


class RecommendationCompareSummary(BaseModel):
    label: str
    sample_days: int
    observed_t1_days: int
    observed_t3_days: int
    observed_t5_days: int
    avg_t1_return_pct: Optional[float] = None
    avg_t3_return_pct: Optional[float] = None
    avg_t5_return_pct: Optional[float] = None
    t1_win_rate: Optional[float] = None
    t3_win_rate: Optional[float] = None
    t5_win_rate: Optional[float] = None


class RecommendationCompareDay(BaseModel):
    trade_date: str
    composite_signal_id: Optional[str] = None
    composite_code: Optional[str] = None
    composite_name: Optional[str] = None
    composite_score: Optional[float] = None
    composite_t1_return_pct: Optional[float] = None
    composite_t3_return_pct: Optional[float] = None
    composite_t5_return_pct: Optional[float] = None
    baseline_signal_id: Optional[str] = None
    baseline_code: Optional[str] = None
    baseline_name: Optional[str] = None
    baseline_score: Optional[float] = None
    baseline_t1_return_pct: Optional[float] = None
    baseline_t3_return_pct: Optional[float] = None
    baseline_t5_return_pct: Optional[float] = None
    winner_label: str
    summary: str


class RecommendationTakeoverReadiness(BaseModel):
    status: str
    label: str
    confidence_score: float
    summary: str
    recommended_action: str
    conditions: list[str]


class RecommendationCompareSnapshot(BaseModel):
    composite: RecommendationCompareSummary
    baseline: RecommendationCompareSummary
    advantage: list[str]
    readiness: RecommendationTakeoverReadiness
    days: list[RecommendationCompareDay]


class Position(BaseModel):
    code: str
    name: str
    quantity: int
    cost_price: float
    current_price: float
    market_value: float
    profit_loss: float
    profit_loss_pct: float
    stop_loss: float
    take_profit: float
    hold_days: int
    strategy: str


class PositionTrade(BaseModel):
    time: str
    type: str
    price: float
    quantity: int
    reason: str


class PositionDetail(BaseModel):
    code: str
    name: str
    quantity: int
    cost_price: float
    current_price: float
    market_value: float
    profit_loss: float
    profit_loss_pct: float
    stop_loss: float
    take_profit: float
    hold_days: int
    strategy: str
    buy_time: str
    high_price: float
    low_price: float
    trailing_stop: bool
    trailing_trigger_price: float
    trades: list[PositionTrade]
    position_guide: "PositionGuide"


class PositionGuide(BaseModel):
    mode: str
    summary: str
    next_action: str
    event_bias: str = "中性"
    event_score: float = 50.0
    event_summary: Optional[str] = None
    top_theme: Optional[str] = None
    sector_bucket: Optional[str] = None
    theme_alignment: str
    can_add: bool
    current_exposure_pct: float
    target_exposure_pct: float
    position_pct: float
    current_theme_exposure_pct: float
    max_theme_exposure_pct: int
    suggested_stop_loss: float
    suggested_take_profit: float
    suggested_reduce_pct: int
    suggested_reduce_quantity: int
    concentration_summary: Optional[str] = None
    warnings: list[str]


class ClosedPosition(BaseModel):
    code: str
    name: str
    quantity: int
    cost_price: float
    close_price: float
    realized_profit_loss: float
    realized_profit_loss_pct: float
    hold_days: int
    strategy: str
    buy_time: str
    closed_at: str
    close_reason: str
    status: str
    trades: list[PositionTrade]


class TradeLedgerEntry(BaseModel):
    id: str
    code: str
    name: str
    strategy: str
    time: str
    type: str
    price: float
    quantity: int
    reason: str
    status: str


class KlineBar(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float


class RiskAlert(BaseModel):
    id: str
    level: str
    title: str
    message: str
    source: str
    source_id: str
    created_at: str
    route: Optional[str]


class AppMessage(BaseModel):
    id: str
    title: str
    body: str
    preview: str
    level: str
    channel: str
    created_at: str
    route: Optional[str] = None


class ActionBoardItem(BaseModel):
    id: str
    kind: str
    level: str
    title: str
    summary: str
    action_label: str
    route: Optional[str]
    source: str
    source_id: str
    created_at: str


class LearningProgress(BaseModel):
    today_cycles: int
    factor_adjustments: int
    online_updates: int
    experiments_running: int
    new_factors_deployed: int
    decision_accuracy: float


class AppBootstrap(BaseModel):
    user: AppUser
    system: SystemStatus
    strategies: list[StrategyPerformance]
    signals: list[Signal]
    positions: list[Position]
    learning: LearningProgress


class PortfolioHistory(BaseModel):
    realized_profit_loss: float
    closed_positions: list[ClosedPosition]
    recent_trades: list[TradeLedgerEntry]


class FeedbackItem(BaseModel):
    id: str
    username: str
    title: str
    message: str
    category: str
    priority: str
    decision_status: str
    owner_note: str
    source_type: str
    source_id: str
    source_route: str
    created_at: str
    updated_at: str
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None


class FeedbackSubmissionRequest(BaseModel):
    title: str
    message: str
    category: str = "general"
    priority: str = "medium"
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    source_route: Optional[str] = None


class FeedbackSubmissionResult(BaseModel):
    success: bool
    message: str
    item: FeedbackItem
    pending_count: int


class FeedbackDecisionRequest(BaseModel):
    decision: str
    owner_note: Optional[str] = None


class FeedbackDecisionResult(BaseModel):
    success: bool
    message: str
    item: FeedbackItem


class SignalOpenRequest(BaseModel):
    quantity: int = 100
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


class PositionRiskUpdateRequest(BaseModel):
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    trailing_stop: Optional[bool] = None
    trailing_trigger_price: Optional[float] = None


class PositionCloseRequest(BaseModel):
    price: Optional[float] = None
    reason: Optional[str] = None
    quantity: Optional[int] = None


class PortfolioActionResult(BaseModel):
    success: bool
    action: str
    code: str
    name: str
    message: str
    executed_at: str
    quantity: int
    execution_price: float
    cash_balance: float
    total_assets: float
    position: Optional[PositionDetail] = None
    realized_profit_loss: Optional[float] = None


class PushDevice(BaseModel):
    username: str
    platform: str
    expo_push_token: str
    device_name: str
    app_version: str
    permission_state: str
    is_physical_device: Optional[bool] = None
    status: str
    last_seen_at: str
    last_push_at: Optional[str] = None
    last_push_status: Optional[str] = None
    last_error: Optional[str] = None


class PushDeviceRegistrationRequest(BaseModel):
    expo_push_token: str
    platform: str
    device_name: Optional[str] = None
    app_version: Optional[str] = None
    permission_state: Optional[str] = None
    is_physical_device: Optional[bool] = None


class PushRegistrationResult(BaseModel):
    success: bool
    message: str
    device: PushDevice
    active_devices: int
    takeover_dispatch: Optional["PushDispatchResult"] = None


class PushTestRequest(BaseModel):
    title: str = "Alpha AI 远程推送测试"
    body: str = "这是一条来自 Alpha AI 后台的远程推送测试。"
    route: Optional[str] = "/alerts"
    dry_run: bool = False
    target_token: Optional[str] = None


class PushTakeoverRequest(BaseModel):
    dry_run: bool = False
    target_token: Optional[str] = None
    force: bool = False


class PushDispatchTicket(BaseModel):
    expo_push_token: str
    status: str
    ticket_id: Optional[str] = None
    message: Optional[str] = None
    details: Optional[str] = None


class PushDispatchResult(BaseModel):
    success: bool
    dry_run: bool
    targeted_devices: int
    sent_devices: int
    failed_devices: int
    tickets: list[PushDispatchTicket]


class TakeoverPushStatus(BaseModel):
    title: str
    body: str
    readiness_label: str
    fingerprint: str
    active_devices: int
    synced_devices: int
    pending_devices: int
    delivery_state: str
    should_send: bool
    summary: str
    recommended_action: str
    auto_enabled: bool
    auto_ready: bool
    auto_cooldown_seconds: int
    last_sent_at: Optional[str] = None
    last_sent_status: Optional[str] = None
    last_sent_fingerprint: Optional[str] = None
    last_preview_at: Optional[str] = None
    last_auto_run_at: Optional[str] = None
    last_auto_run_status: Optional[str] = None


class IndustryResearchPushStatus(BaseModel):
    title: str
    latest_title: Optional[str] = None
    latest_preview: Optional[str] = None
    latest_direction: Optional[str] = None
    latest_timeline_stage: Optional[str] = None
    latest_catalyst_title: Optional[str] = None
    active_devices: int
    delivery_state: str
    auto_enabled: bool
    summary: str
    recommended_action: str
    last_sent_at: Optional[str] = None
    last_sent_status: Optional[str] = None


class TakeoverPushSettingsRequest(BaseModel):
    auto_enabled: bool


class OpsRouteStat(BaseModel):
    method: str
    path: str
    count: int
    error_count: int
    avg_latency_ms: float
    max_latency_ms: float
    last_status: int
    last_seen_at: Optional[str] = None


class OpsDataStatus(BaseModel):
    scorecard_records: int
    trade_journal_records: int
    signal_count: int
    active_positions: int
    feedback_items: int
    push_devices: int


class OpsRecommendation(BaseModel):
    level: str
    title: str
    message: str


class OpsSummary(BaseModel):
    service: str
    version: str
    started_at: str
    uptime_seconds: int
    ready: bool
    readiness_issues: list[str]
    request_count: int
    error_count: int
    error_rate: float
    avg_latency_ms: float
    max_latency_ms: float
    p95_latency_ms: float
    last_error_at: Optional[str] = None
    last_error_path: Optional[str] = None
    websocket_connections: int
    system_status: str
    system_health_score: int
    today_signals: int
    active_strategies: int
    data_status: OpsDataStatus
    routes: list[OpsRouteStat]
    recommendations: list[OpsRecommendation] = Field(default_factory=list)


class StockDiagnosis(BaseModel):
    code: str
    name: str
    price: float
    as_of: str
    total_score: float
    verdict: str
    direction: str
    signal_direction: str
    actionable: bool
    confidence_label: str
    advice: str
    report_text: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    scores: dict[str, float]
    details: dict[str, list[str]]
    regime: str
    regime_score: float
    regime_summary: str
    health_bias: str
    in_portfolio: bool
    position_quantity: int
    position_profit_loss_pct: Optional[float] = None
    in_signal_board: bool
    top_strategy: Optional[str] = None
    top_strategy_win_rate: Optional[float] = None
    top_strategy_avg_return: Optional[float] = None
    risk_flags: list[str]
    next_actions: list[str]


class LearningAdvanceCheck(BaseModel):
    name: str
    status: str
    detail: str


class LearningAdvanceStatus(BaseModel):
    status: str
    in_progress: bool
    today_completed: bool
    last_started_at: Optional[str] = None
    current_run_started_at: Optional[str] = None
    last_completed_at: Optional[str] = None
    last_requested_by: Optional[str] = None
    stale_hours: Optional[float] = None
    health_status: str
    summary: str
    last_error: Optional[str] = None
    last_report_excerpt: str = ""
    ingested_signals: int
    verified_signals: int
    reviewed_decisions: int
    checks: list[LearningAdvanceCheck] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


def _require_app_user(authorization: Optional[str] = Header(default=None)) -> AppUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="缺少 Bearer Token")

    payload = _decode_access_token(authorization.split(" ", 1)[1].strip())
    return AppUser(
        username=payload.get("sub", ""),
        display_name=payload.get("display_name", _APP_AUTH_DISPLAY_NAME),
        role=payload.get("role", "operator"),
    )


def _build_system_status() -> SystemStatus:
    memory = safe_load(_AGENT_MEMORY, default={})

    start_time_str = memory.get("system_start_time", "")
    if start_time_str:
        try:
            start_time = datetime.fromisoformat(start_time_str)
            uptime_hours = (datetime.now() - start_time).total_seconds() / 3600
        except:
            uptime_hours = 0
    else:
        uptime_hours = 0

    today = datetime.now().strftime("%Y-%m-%d")
    today_signals = len([s for s in _load_signal_records(days=1) if _signal_trade_day(s) == today])

    strategies = safe_load(_STRATEGIES_JSON, default=[])
    active_count = len([s for s in strategies if s.get("enabled", False)])

    return SystemStatus(
        status="running",
        uptime_hours=round(uptime_hours, 1),
        health_score=memory.get("health_score", 85),
        today_signals=today_signals,
        active_strategies=active_count,
        ooda_cycles=memory.get("ooda_cycles", 0),
        decision_accuracy=memory.get("decision_accuracy", 0.68),
    )


def _build_strategies() -> list[StrategyPerformance]:
    def builder() -> list[StrategyPerformance]:
        strategies = safe_load(_STRATEGIES_JSON, default=[])
        memory = safe_load(_AGENT_MEMORY, default={})
        strategy_states = memory.get("strategy_states", {})

        scorecard = load_scorecard()
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        recent = [r for r in scorecard if r.get("rec_date", "") >= cutoff]

        result = []
        for strat in strategies:
            strat_id = strat.get("id", "")
            strat_name = strat.get("name", "")
            state = strategy_states.get(strat_id, {})
            status = state.get("status", "active" if strat.get("enabled") else "disabled")
            strat_records = [r for r in recent if _scorecard_matches_strategy(r, strat)]

            if strat_records:
                wins = len([r for r in strat_records if _scorecard_is_win(r)])
                win_rate = wins / len(strat_records) if strat_records else 0
                returns = [_scorecard_return_pct(r) for r in strat_records]
                valid_returns = [r for r in returns if r is not None]
                avg_return = sum(valid_returns) / len(valid_returns) if valid_returns else 0
                last_signal = max(r.get("rec_date", "") for r in strat_records)
            else:
                win_rate = 0
                avg_return = 0
                last_signal = None

            result.append(
                StrategyPerformance(
                    id=strat_id,
                    name=strat_name,
                    status=status,
                    win_rate=round(win_rate * 100, 1),
                    avg_return=round(avg_return, 2),
                    signal_count=len(strat_records),
                    last_signal_time=last_signal,
                )
            )

        result.sort(key=lambda x: x.win_rate, reverse=True)
        return result

    return _cached_runtime_value(
        "strategies",
        "default",
        ttl_seconds=12,
        dependency_paths=_runtime_cache_paths(
            _STRATEGIES_JSON,
            _AGENT_MEMORY,
            *_db_dependency_paths(),
        ),
        builder=builder,
    )


def _build_signals(days: int = 1) -> list[Signal]:
    signals_data = _load_signal_records(days=days)

    result = []
    for sig in signals_data:
        result.append(
            Signal(
                id=sig.get("id", ""),
                code=sig.get("code", ""),
                name=sig.get("name", ""),
                strategy=sig.get("strategy", ""),
                score=sig.get("score", 0),
                price=sig.get("price", 0),
                change_pct=sig.get("change_pct", 0),
                buy_price=sig.get("buy_price", 0),
                stop_loss=sig.get("stop_loss", 0),
                target_price=sig.get("target_price", 0),
                risk_reward=sig.get("risk_reward", 0),
                timestamp=sig.get("timestamp", ""),
                consensus_count=sig.get("consensus_count", 1),
            )
        )

    result.sort(key=lambda x: x.score, reverse=True)
    return result


def _round_lot_quantity(amount: float, reference_price: float) -> int:
    if amount <= 0 or reference_price <= 0:
        return 0
    lots = int(amount // (reference_price * 100))
    return max(0, lots * 100)


def _find_composite_pick_for_signal(
    signal_id: str,
    code: str,
    picks: list[CompositePick],
) -> Optional[CompositePick]:
    exact = next((item for item in picks if item.signal_id == signal_id), None)
    if exact is not None:
        return exact
    return next((item for item in picks if item.code == code), None)


def _position_market_value(raw_position: dict) -> float:
    market_value = _to_float(raw_position.get("market_value"))
    if market_value is not None and market_value > 0:
        return market_value
    quantity = max(0, _to_int(raw_position.get("quantity")))
    price = _to_float(raw_position.get("current_price"))
    if price is None or price <= 0:
        price = _to_float(raw_position.get("cost_price")) or 0.0
    return max(0.0, quantity * price)


def _theme_bucket_name(theme_sector: Optional[str]) -> Optional[str]:
    if not theme_sector:
        return None
    try:
        from risk_manager import classify_sector

        bucket = classify_sector(str(theme_sector))
        if bucket and bucket != "其他":
            return bucket
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)
    return str(theme_sector)


def _portfolio_bucket_exposure_pct(portfolio: dict, bucket: Optional[str]) -> float:
    if not bucket:
        return 0.0
    total_assets = _to_float(portfolio.get("total_assets")) or 0.0
    if total_assets <= 0:
        return 0.0

    try:
        from risk_manager import classify_sector
    except Exception:
        def classify_sector(name: str) -> str:
            return "其他"

    exposure = 0.0
    for raw_position in portfolio.get("positions", []):
        if not isinstance(raw_position, dict) or _to_int(raw_position.get("quantity")) <= 0:
            continue
        position_bucket = classify_sector(str(raw_position.get("name", "")))
        if position_bucket == bucket:
            exposure += _position_market_value(raw_position)
    return round(exposure / total_assets * 100, 1)


def _position_pct_of_assets(raw_position: dict, total_assets: float) -> float:
    if total_assets <= 0:
        return 0.0
    return round(_position_market_value(raw_position) / total_assets * 100, 1)


def _round_to_board_lot(quantity: int) -> int:
    return max(0, int(quantity // 100) * 100)


def _suggest_position_reduction(position: dict, guide_mode: str) -> tuple[int, int]:
    quantity = max(0, _to_int(position.get("quantity")))
    if quantity <= 0:
        return 0, 0

    reduce_pct = 0
    if guide_mode == "优先减仓或平仓":
        reduce_pct = 100
    elif guide_mode == "先降风险":
        reduce_pct = 50
    elif guide_mode == "先锁盈":
        reduce_pct = 50
    elif guide_mode == "锁盈观察":
        reduce_pct = 30

    if reduce_pct <= 0:
        return 0, 0

    close_quantity = quantity if reduce_pct >= 100 else _round_to_board_lot(quantity * reduce_pct / 100)
    if close_quantity <= 0 and quantity > 0:
        close_quantity = min(quantity, 100)
    if close_quantity >= quantity:
        return 100, quantity
    return reduce_pct, close_quantity


def _build_position_guide(raw_position: dict) -> PositionGuide:
    portfolio = _load_portfolio()
    positioning_plan = _build_positioning_plan(days=1, limit=3)
    total_assets = _to_float(portfolio.get("total_assets")) or positioning_plan.total_assets or 0.0
    position_pct = _position_pct_of_assets(raw_position, total_assets)
    sector_bucket = _theme_bucket_name(str(raw_position.get("name", "")))
    current_theme_exposure_pct = _portfolio_bucket_exposure_pct(portfolio, sector_bucket)
    current_price = _to_float(raw_position.get("current_price")) or 0.0
    cost_price = _to_float(raw_position.get("cost_price")) or 0.0
    stop_loss = _to_float(raw_position.get("stop_loss")) or 0.0
    take_profit = _to_float(raw_position.get("take_profit")) or 0.0
    profit_loss_pct = _to_float(raw_position.get("profit_loss_pct")) or 0.0
    hold_days = max(0, _to_int(raw_position.get("hold_days")))
    stop_buffer_pct = (
        (current_price - stop_loss) / current_price if current_price > 0 and stop_loss > 0 else None
    )
    target_gap_pct = (
        (take_profit - current_price) / current_price if current_price > 0 and take_profit > 0 else None
    )

    top_theme = positioning_plan.top_theme
    if sector_bucket and top_theme and sector_bucket == top_theme:
        theme_alignment = "和当前主线一致"
    elif sector_bucket and positioning_plan.event_focus_sector and sector_bucket == positioning_plan.event_focus_sector:
        theme_alignment = "和事件总控焦点一致"
    elif sector_bucket and top_theme and sector_bucket != top_theme:
        theme_alignment = "和当前主线不一致"
    elif sector_bucket:
        theme_alignment = "主线匹配待观察"
    else:
        theme_alignment = "暂未识别到明确主题"

    event_bias = positioning_plan.event_bias
    event_score = positioning_plan.event_score
    event_summary = positioning_plan.event_summary

    suggested_stop_loss = stop_loss
    suggested_take_profit = take_profit
    if current_price > 0:
        if profit_loss_pct >= 5:
            suggested_stop_loss = max(stop_loss, round(current_price * 0.97, 2))
            if take_profit <= 0:
                suggested_take_profit = round(current_price * 1.04, 2)
        elif profit_loss_pct >= 2:
            suggested_stop_loss = max(stop_loss, round(max(cost_price, current_price * 0.96), 2))
            if take_profit <= 0:
                suggested_take_profit = round(current_price * 1.05, 2)
        elif profit_loss_pct < 0 and stop_loss <= 0:
            suggested_stop_loss = round(current_price * 0.97, 2)

    warnings: list[str] = []
    if stop_buffer_pct is not None and stop_buffer_pct <= 0:
        warnings.append(f"当前价已经跌破止损 {stop_loss:.2f}，这笔仓位不该继续拖。")
    elif stop_buffer_pct is not None and stop_buffer_pct <= 0.02:
        warnings.append(f"距离止损只剩 {stop_buffer_pct * 100:.1f}% 左右，风险很近。")

    if (
        sector_bucket
        and positioning_plan.max_theme_exposure_pct > 0
        and current_theme_exposure_pct > positioning_plan.max_theme_exposure_pct
    ):
        warnings.append(
            f"{sector_bucket} 当前已经占组合 {current_theme_exposure_pct:.1f}% ，高于主题上限 {positioning_plan.max_theme_exposure_pct}%。"
        )

    if event_bias == "偏空" and profit_loss_pct <= 0:
        warnings.append("事件总控偏空，弱势仓位更不适合死扛。")
    elif event_bias == "偏空" and profit_loss_pct > 0:
        warnings.append("事件总控偏空，盈利仓位更要先想锁盈，不是继续硬扛波动。")

    if position_pct > positioning_plan.max_single_position_pct > 0:
        warnings.append(
            f"这笔仓位当前已占总资产 {position_pct:.1f}% ，高于单票上限 {positioning_plan.max_single_position_pct}%。"
        )

    if stop_buffer_pct is not None and stop_buffer_pct <= 0:
        mode = "优先减仓或平仓"
        summary = "这笔仓位已经失守，先把风险砍掉，比继续找理由更重要。"
        next_action = "优先平掉或至少大幅减仓，再回头复盘为什么失效。"
    elif stop_buffer_pct is not None and stop_buffer_pct <= 0.02:
        mode = "先降风险"
        summary = "仓位已经贴近止损，下一步先收缩风险，而不是再去赌反弹。"
        next_action = "先减仓一部分，或者把止损提到更明确的位置。"
    elif profit_loss_pct >= 5 and (target_gap_pct is None or target_gap_pct <= 0.04):
        mode = "先锁盈"
        summary = "利润已经出来了，现在的重点是保利润，而不是把盈利单拖成回吐单。"
        next_action = "优先锁盈一部分，同时把止损上移。"
    elif event_bias == "偏空" and profit_loss_pct >= 0:
        mode = "锁盈观察"
        summary = "事件层偏空，这类仓位可以继续盯，但不适合太贪。"
        next_action = "考虑先减一部分，把仓位压回更舒服的位置。"
    elif profit_loss_pct < 0:
        mode = "浮亏观察"
        summary = "这笔仓位还没彻底失效，但现在只能按纪律观察，不能情绪化加仓。"
        next_action = "盯住止损，等确认而不是补幻想。"
    else:
        mode = "继续持有"
        summary = "仓位总体还在纪律内，可以继续拿，但保护线要跟着盈利走。"
        next_action = "不急着乱动，优先优化止损和止盈，让仓位继续有章法。"

    suggested_reduce_pct, suggested_reduce_quantity = _suggest_position_reduction(raw_position, mode)
    can_add = (
        event_bias != "偏空"
        and position_pct < positioning_plan.max_single_position_pct
        and current_theme_exposure_pct <= positioning_plan.max_theme_exposure_pct
        and profit_loss_pct >= 0
    )

    concentration_summary = None
    if sector_bucket:
        concentration_summary = (
            f"{sector_bucket} 方向当前占组合 {current_theme_exposure_pct:.1f}% ，"
            f"系统主题上限是 {positioning_plan.max_theme_exposure_pct}% 。"
        )

    return PositionGuide(
        mode=mode,
        summary=summary,
        next_action=next_action,
        event_bias=event_bias,
        event_score=event_score,
        event_summary=event_summary,
        top_theme=top_theme,
        sector_bucket=sector_bucket,
        theme_alignment=theme_alignment,
        can_add=can_add,
        current_exposure_pct=positioning_plan.current_exposure_pct,
        target_exposure_pct=positioning_plan.target_exposure_pct,
        position_pct=position_pct,
        current_theme_exposure_pct=current_theme_exposure_pct,
        max_theme_exposure_pct=positioning_plan.max_theme_exposure_pct,
        suggested_stop_loss=_round_money(suggested_stop_loss),
        suggested_take_profit=_round_money(suggested_take_profit),
        suggested_reduce_pct=suggested_reduce_pct,
        suggested_reduce_quantity=suggested_reduce_quantity,
        concentration_summary=concentration_summary,
        warnings=warnings,
    )


def _build_signal_entry_guide(raw_signal: dict) -> SignalEntryGuide:
    signal_id = str(raw_signal.get("id", ""))
    code = str(raw_signal.get("code", ""))
    composite_picks = _build_composite_picks(days=1, limit=12)
    composite_pick = _find_composite_pick_for_signal(signal_id, code, composite_picks)
    positioning_plan = _build_positioning_plan(days=1, limit=3)
    portfolio = _load_portfolio()

    reference_price = _round_money(
        _to_float(raw_signal.get("buy_price")) or _to_float(raw_signal.get("price")) or 0.0
    )
    composite_score = composite_pick.composite_score if composite_pick is not None else 0.0
    recommended_first_position_pct = (
        composite_pick.first_position_pct
        if composite_pick is not None and composite_pick.first_position_pct > 0
        else positioning_plan.first_entry_position_pct
    )
    if positioning_plan.max_single_position_pct > 0:
        recommended_first_position_pct = min(
            recommended_first_position_pct,
            positioning_plan.max_single_position_pct,
        )
    recommended_first_position_pct = max(0, recommended_first_position_pct)

    suggested_amount = 0.0
    if recommended_first_position_pct > 0:
        suggested_amount = min(
            positioning_plan.deployable_cash,
            _round_money(positioning_plan.total_assets * recommended_first_position_pct / 100.0),
        )
    suggested_quantity = _round_lot_quantity(suggested_amount, reference_price)

    theme_sector = composite_pick.theme_sector if composite_pick is not None else None
    sector_bucket = _theme_bucket_name(theme_sector)
    event_matched_sector = (
        composite_pick.event_matched_sector if composite_pick is not None else None
    )
    if theme_sector and event_matched_sector and theme_sector == event_matched_sector:
        theme_alignment = "与事件主线一致"
    elif theme_sector and positioning_plan.top_theme and theme_sector == positioning_plan.top_theme:
        theme_alignment = "与当前首要主线一致"
    elif theme_sector and positioning_plan.event_focus_sector and theme_sector != positioning_plan.event_focus_sector:
        theme_alignment = "不在当前事件主线中心"
    elif theme_sector:
        theme_alignment = "主线匹配待观察"
    else:
        theme_alignment = "暂未识别到明确主线"

    current_theme_exposure_pct = _portfolio_bucket_exposure_pct(portfolio, sector_bucket)
    suggested_position_pct = 0.0
    if positioning_plan.total_assets > 0 and suggested_amount > 0:
        suggested_position_pct = round(suggested_amount / positioning_plan.total_assets * 100, 1)
    projected_theme_exposure_pct = round(current_theme_exposure_pct + suggested_position_pct, 1)

    event_bias = (
        composite_pick.event_bias if composite_pick is not None else positioning_plan.event_bias
    )
    event_score = (
        composite_pick.event_score if composite_pick is not None else positioning_plan.event_score
    )
    event_summary = (
        composite_pick.event_summary
        if composite_pick is not None and composite_pick.event_summary
        else positioning_plan.event_summary
    )

    warnings: list[str] = []
    if event_bias == "偏空":
        warnings.append("事件总控当前偏空，新增仓位只能按轻仓纪律推进。")
    if positioning_plan.available_slots <= 0:
        warnings.append("当前组合可用槽位不足，先处理存量仓位再谈新增。")
    if positioning_plan.deployable_cash <= 0:
        warnings.append("当前没有可再部署现金，信号先看，不直接动手。")
    if (
        theme_sector
        and positioning_plan.top_theme
        and theme_sector != positioning_plan.top_theme
    ):
        warnings.append(
            f"这条票所属主线是 {theme_sector}，当前系统优先主线是 {positioning_plan.top_theme}。"
        )
    if (
        sector_bucket
        and projected_theme_exposure_pct > 0
        and projected_theme_exposure_pct > positioning_plan.max_theme_exposure_pct > 0
    ):
        warnings.append(
            f"{sector_bucket} 方向执行这一笔后，主题暴露会到 {projected_theme_exposure_pct:.1f}% ，"
            f"高于当前上限 {positioning_plan.max_theme_exposure_pct}% 。"
        )
    if suggested_amount > 0 and suggested_quantity <= 0:
        warnings.append("按 A 股一手 100 股取整后，这笔首仓暂时不够一手。")

    concentration_summary = None
    if sector_bucket:
        concentration_summary = (
            f"当前 {sector_bucket} 方向已占组合 {current_theme_exposure_pct:.1f}% 。"
            f" 如果按建议首仓执行，会到 {projected_theme_exposure_pct:.1f}% ，"
            f"当前主题上限是 {positioning_plan.max_theme_exposure_pct}% 。"
        )

    if (
        positioning_plan.deployable_cash <= 0
        or positioning_plan.available_slots <= 0
        or positioning_plan.target_exposure_pct <= 0
    ):
        mode = "先观察"
        summary = "组合当前不适合新增仓位，这条信号保留观察，不直接开新仓。"
    elif event_bias == "偏空" and event_score < 45:
        mode = "轻仓试错"
        summary = "事件层偏空，先保留进攻资格，但只能用更轻的首仓试单。"
    elif composite_score >= 68 and event_score >= 55 and recommended_first_position_pct >= 8:
        mode = "允许首仓"
        summary = "综合分、主线匹配和仓位环境都过线，可以按首仓纪律执行。"
    elif composite_score >= 58:
        mode = "轻仓试错"
        summary = "信号本身能看，但更适合先拿小仓确认，不值得一把打满。"
    else:
        mode = "优先观察"
        summary = "这条票先留在观察区，等综合分或主线匹配更硬再出手。"

    action = (
        f"先按 {recommended_first_position_pct}% 首仓试错，"
        f"单票上限 {positioning_plan.max_single_position_pct}% ，"
        f"主题上限 {positioning_plan.max_theme_exposure_pct}% 。"
    )
    if suggested_quantity > 0 and suggested_amount > 0:
        action += f" 按当前总资产估算，这一笔大约是 {suggested_quantity} 股 / {suggested_amount:.0f} 元。"
    elif suggested_amount > 0:
        action += " 但按 100 股一手取整后暂时不够一手，先别硬开。"

    return SignalEntryGuide(
        mode=mode,
        summary=summary,
        action=action,
        composite_score=round(composite_score, 1),
        setup_label=composite_pick.setup_label if composite_pick is not None else None,
        theme_sector=theme_sector,
        sector_bucket=sector_bucket,
        theme_alignment=theme_alignment,
        event_bias=event_bias,
        event_score=round(event_score, 1),
        event_summary=event_summary,
        recommended_first_position_pct=recommended_first_position_pct,
        suggested_amount=_round_money(suggested_amount),
        suggested_quantity=suggested_quantity,
        total_assets=positioning_plan.total_assets,
        max_single_position_pct=positioning_plan.max_single_position_pct,
        max_theme_exposure_pct=positioning_plan.max_theme_exposure_pct,
        target_exposure_pct=positioning_plan.target_exposure_pct,
        deployable_cash=positioning_plan.deployable_cash,
        current_theme_exposure_pct=current_theme_exposure_pct,
        projected_theme_exposure_pct=projected_theme_exposure_pct,
        concentration_summary=concentration_summary,
        warnings=warnings,
    )


def _build_signal_detail(signal_id: str) -> SignalDetail:
    raw_signal = _find_signal_record(signal_id)

    if not raw_signal:
        raise HTTPException(status_code=404, detail="信号不存在")

    raw_factor_scores = raw_signal.get("factor_scores", {})
    factor_scores = {}
    if isinstance(raw_factor_scores, dict):
        factor_scores = {
            str(key): _to_float(value) or 0
            for key, value in raw_factor_scores.items()
        }

    strategies = raw_signal.get("strategies", [])
    if not isinstance(strategies, list) or not strategies:
        strategy = raw_signal.get("strategy", "")
        strategies = [strategy] if strategy else []

    entry_guide = _build_signal_entry_guide(raw_signal)

    return SignalDetail(
        id=raw_signal.get("id", ""),
        code=raw_signal.get("code", ""),
        name=raw_signal.get("name", ""),
        strategy=raw_signal.get("strategy", ""),
        strategies=[str(item) for item in strategies],
        score=_to_float(raw_signal.get("score")) or 0,
        price=_to_float(raw_signal.get("price")) or 0,
        change_pct=_to_float(raw_signal.get("change_pct")) or 0,
        high=_to_float(raw_signal.get("high")) or _to_float(raw_signal.get("price")) or 0,
        low=_to_float(raw_signal.get("low")) or _to_float(raw_signal.get("price")) or 0,
        volume=_to_float(raw_signal.get("volume")) or 0,
        turnover=_to_float(raw_signal.get("turnover")) or 0,
        buy_price=_to_float(raw_signal.get("buy_price")) or 0,
        stop_loss=_to_float(raw_signal.get("stop_loss")) or 0,
        target_price=_to_float(raw_signal.get("target_price")) or 0,
        risk_reward=_to_float(raw_signal.get("risk_reward")) or 0,
        timestamp=raw_signal.get("timestamp", ""),
        consensus_count=int(raw_signal.get("consensus_count", 1) or 1),
        factor_scores=factor_scores,
        regime=raw_signal.get("regime", "未知"),
        regime_score=_to_float(raw_signal.get("regime_score")) or 0,
        entry_guide=entry_guide,
    )


def _normalize_factor_score(value: object) -> Optional[float]:
    numeric = _to_float(value)
    if numeric is None:
        return None
    if numeric < 0:
        return max(0.0, min(1.0, (numeric + 1.0) / 2.0))
    return max(0.0, min(1.0, numeric))


def _factor_bucket(raw_scores: dict[str, object], names: list[str]) -> float:
    values = []
    for name in names:
        normalized = _normalize_factor_score(raw_scores.get(name))
        if normalized is not None:
            values.append(normalized)
    if not values:
        return 0.0
    return sum(values) / len(values)


def _strong_move_label(continuation_score: float, swing_score: float, heat_score: float) -> tuple[str, str]:
    if continuation_score >= 78 and heat_score >= 62:
        return "连涨候选", "high"
    if swing_score >= 75:
        return "波段候选", "high"
    if continuation_score >= 66:
        return "续强观察", "medium"
    return "趋势观察", "low"


def _strong_move_reasons(
    *,
    strategy_win_rate: float,
    trend_score: float,
    heat_score: float,
    flow_score: float,
    signal_score: float,
    risk_reward: float,
) -> list[str]:
    reasons: list[str] = []
    if heat_score >= 0.62:
        reasons.append("题材热度和承接在前排")
    if trend_score >= 0.60:
        reasons.append("趋势结构保持上行")
    if flow_score >= 0.58:
        reasons.append("资金与筹码配合较顺")
    if signal_score >= 0.90:
        reasons.append("原始信号强度靠前")
    if strategy_win_rate >= 60:
        reasons.append("所属策略近期命中率较稳")
    if risk_reward >= 2.0:
        reasons.append("盈亏比达到进攻标准")
    if not reasons:
        reasons.append("当前更像观察单，等确认后再出手")
    return reasons[:3]


def _strong_move_next_step(setup_label: str) -> str:
    if setup_label == "连涨候选":
        return "先打首仓，分时承接确认后再加仓。"
    if setup_label == "波段候选":
        return "更适合分批布局，用移动止盈去拿波段。"
    if setup_label == "续强观察":
        return "先盯竞价和量能确认，不要一把打满。"
    return "保持跟踪，等结构和量能同步改善。"


def _composite_conviction(score: float) -> str:
    if score >= 76:
        return "high"
    if score >= 60:
        return "medium"
    return "low"


def _composite_setup_label(score: float, theme_intensity: str | None, strong_label: str | None) -> str:
    if strong_label == "连涨候选":
        return "主线龙头候选"
    if theme_intensity == "高热主线" and score >= 74:
        return "主线共振"
    if strong_label == "波段候选" and score >= 62:
        return "综合进攻候选"
    if strong_label == "续强观察" and score >= 58:
        return "综合观察候选"
    if score >= 72:
        return "综合进攻候选"
    if score >= 64:
        return "综合观察候选"
    return "备选观察"


def _entry_window_score(change_pct: float) -> float:
    if change_pct <= 0:
        return 0.74
    if change_pct <= 3:
        return 0.88
    if change_pct <= 5:
        return 0.68
    if change_pct <= 7:
        return 0.46
    return 0.22


def _composite_first_position_pct(composite_score: float, risk_reward: float, theme_intensity: str | None) -> int:
    pct = 8
    if composite_score >= 60:
        pct = 10
    if composite_score >= 74:
        pct = 12
    if composite_score >= 82:
        pct = 15
    if risk_reward >= 2.2:
        pct += 1
    if theme_intensity == "高热主线":
        pct += 1
    return min(pct, 18)


def _build_composite_pick_reasons(
    *,
    theme_item: ThemeRadarItem | None,
    strong_move: StrongMoveCandidate | None,
    strategy_win_rate: float,
    heat_score: float,
    flow_score: float,
    trend_score: float,
    risk_reward: float,
) -> list[str]:
    reasons: list[str] = []
    if theme_item:
        reasons.append(f"{theme_item.sector} 处于{theme_item.intensity}，题材资金开始聚焦。")
    if strong_move:
        reasons.append(f"强势收益引擎已标记为 {strong_move.setup_label}。")
    if heat_score >= 0.6:
        reasons.append("热度和承接处于前排。")
    if flow_score >= 0.56:
        reasons.append("资金与筹码结构配合较顺。")
    if trend_score >= 0.6:
        reasons.append("趋势形态仍在向上延续。")
    if strategy_win_rate >= 55:
        reasons.append(f"所属策略近期胜率 {strategy_win_rate:.1f}% ，稳定性尚可。")
    if risk_reward >= 2:
        reasons.append("盈亏比达到首仓试错标准。")
    if not reasons:
        reasons.append("当前更适合作为观察对象，等待进一步确认。")
    return reasons[:3]


def _composite_action(
    *,
    theme_item: ThemeRadarItem | None,
    strong_move: StrongMoveCandidate | None,
    first_position_pct: int,
    setup_label: str,
) -> str:
    if theme_item and strong_move:
        return (
            f"主线、资金和策略已经共振，建议先打 {first_position_pct}% 首仓，"
            "确认分时承接后再决定是否加仓。"
        )
    if strong_move:
        return (
            f"这票更像 {setup_label}，建议先用 {first_position_pct}% 首仓试错，"
            "不要一把打满。"
        )
    if theme_item:
        return "主线开始升温，但强票还不够硬，先观察龙头确认再行动。"
    return "保留在综合候选池，等题材和量能再同步一轮。"


def _build_theme_seed_signal_record(
    theme_item: ThemeRadarItem,
    follower: ThemeFollower,
    *,
    linked_signal: StrongMoveCandidate | None,
) -> Optional[dict]:
    code = str(follower.code).strip()
    name = str(follower.name).strip()
    if not code or not name or not _is_stock_signal_code(code) or not _is_tradable_stock_name(name):
        return None

    price = _to_float(follower.buy_price) or 0.0
    if price <= 0:
        return None

    theme_norm = _clamp((_to_float(theme_item.score) or 0.0) / 100.0, 0.0, 1.0)
    change_pct = _to_float(follower.change_pct) or 0.0
    change_norm = _clamp(abs(change_pct) / 9.0, 0.0, 1.0)
    follower_rr = _to_float(follower.risk_reward) or 0.0
    rr_norm = _clamp(follower_rr / 3.0, 0.0, 1.0)
    linked_norm = (
        _clamp((_to_float(linked_signal.composite_score) or 0.0) / 100.0, 0.0, 1.0)
        if linked_signal is not None
        else 0.0
    )
    intensity_bonus = {"高热主线": 0.18, "持续升温": 0.11}.get(theme_item.intensity, 0.05)
    label_bonus = {
        "观察": 0.0,
        "跟随": 0.03,
        "优先": 0.05,
        "重点": 0.08,
    }.get(str(follower.label).strip(), 0.02)

    score = round(
        _clamp(
            0.43
            + theme_norm * 0.24
            + change_norm * 0.10
            + rr_norm * 0.08
            + linked_norm * 0.09
            + intensity_bonus
            + label_bonus,
            0.45,
            0.92,
        ),
        3,
    )

    stop_loss = _to_float(follower.stop_loss) or round(price * 0.95, 2)
    if stop_loss >= price:
        stop_loss = round(price * 0.96, 2)

    target_price = _to_float(follower.target_price) or 0.0
    if target_price <= price:
        target_price = round(
            max(
                price * 1.05,
                price + max(price - stop_loss, 0.01) * 2.2,
            ),
            2,
        )

    risk_reward = follower_rr
    if risk_reward <= 0:
        risk_reward = _default_signal_risk_reward(price, stop_loss, target_price)

    strategy = "主线资金共振"
    if linked_signal is not None and linked_norm >= 0.55:
        strategy = "主线接力"

    factor_scores = {
        "s_hot": round(theme_norm, 3),
        "s_sector_momentum": round(_clamp(theme_norm + intensity_bonus, 0.0, 1.0), 3),
        "s_fund_flow": round(_clamp(theme_norm * 0.55 + linked_norm * 0.45, 0.0, 1.0), 3),
        "s_flow_trend": round(_clamp(theme_norm * 0.4 + rr_norm * 0.25 + linked_norm * 0.35, 0.0, 1.0), 3),
        "s_trend": round(_clamp(change_norm * 0.45 + theme_norm * 0.35 + linked_norm * 0.2, 0.0, 1.0), 3),
        "s_relative_strength": round(_clamp(change_norm * 0.4 + theme_norm * 0.4 + 0.15, 0.0, 1.0), 3),
        "s_volume_ratio": round(_clamp(theme_norm * 0.45 + linked_norm * 0.35 + 0.2, 0.0, 1.0), 3),
        "s_turnover": round(_clamp(theme_norm * 0.5 + change_norm * 0.3 + 0.15, 0.0, 1.0), 3),
    }

    regime = "neutral"
    if linked_signal is not None and str(linked_signal.setup_label).startswith("连涨"):
        regime = "bull"

    return {
        "id": f"theme-seed-{theme_item.id}-{code}",
        "code": code,
        "name": name,
        "strategy": strategy,
        "strategies": [strategy],
        "score": score,
        "price": price,
        "change_pct": change_pct,
        "high": max(price, target_price),
        "low": min(price, stop_loss),
        "volume": 0.0,
        "turnover": round((_to_float(theme_item.score) or 0.0) * 1000000, 2),
        "buy_price": price,
        "stop_loss": stop_loss,
        "target_price": target_price,
        "risk_reward": risk_reward,
        "timestamp": theme_item.timestamp,
        "consensus_count": 2 if theme_item.intensity in {"高热主线", "持续升温"} else 1,
        "factor_scores": factor_scores,
        "regime": regime,
        "regime_score": 0.6 if regime == "bull" else 0.5,
        "source": "theme_seed",
    }


def _build_theme_seed_signal_records(
    theme_radar: list[ThemeRadarItem],
    strong_move_map: dict[str, StrongMoveCandidate],
    *,
    existing_codes: set[str],
) -> list[dict]:
    theme_seed_records: list[dict] = []
    for theme_item in theme_radar:
        linked_signal = strong_move_map.get(theme_item.linked_code or "")
        for follower in theme_item.followers:
            code = str(follower.code).strip()
            if not code or code in existing_codes:
                continue
            seed_signal = _build_theme_seed_signal_record(
                theme_item,
                follower,
                linked_signal=strong_move_map.get(code) or linked_signal,
            )
            if seed_signal is None:
                continue
            existing_codes.add(code)
            theme_seed_records.append(seed_signal)
    return theme_seed_records


def _composite_source_profile(
    signal: dict,
    *,
    theme_item: ThemeRadarItem | None,
    strong_move: StrongMoveCandidate | None,
    composite_score: float,
) -> tuple[str, str, str]:
    source = str(signal.get("source", "")).strip()
    if source == "theme_seed":
        source_category = "theme_seed"
        source_label = "主线种子"
    elif theme_item is not None and strong_move is not None:
        source_category = "resonance"
        source_label = "主线共振"
    elif strong_move is not None:
        source_category = "strong_move"
        source_label = "强势续强"
    else:
        source_category = "strategy"
        source_label = "策略候选"

    strong_label = str(strong_move.setup_label) if strong_move is not None else ""
    if source_category == "theme_seed":
        horizon_label = "主线孵化"
    elif strong_label == "波段候选":
        horizon_label = "中期波段"
    elif strong_label == "连涨候选":
        horizon_label = "连涨接力"
    elif composite_score >= 70:
        horizon_label = "进攻观察"
    else:
        horizon_label = "短线观察"

    return source_category, source_label, horizon_label


def _theme_intensity(score: float, change_pct: float, follower_count: int) -> str:
    if score >= 60 or (change_pct >= 2.5 and follower_count >= 3):
        return "高热主线"
    if score >= 45 or change_pct >= 1.2:
        return "持续升温"
    return "观察中"


def _theme_action(intensity: str, linked_signal: StrongMoveCandidate | None) -> str:
    if linked_signal and intensity == "高热主线":
        return f"主线和强势候选已经共振，先看 {linked_signal.code} 的分时承接，再决定首仓。"
    if linked_signal:
        return f"先跟踪 {linked_signal.code} 这类强票，等板块继续放量后再加火力。"
    if intensity == "高热主线":
        return "板块已经开始聚焦，但先挑前排，不要把火力打在跟风票上。"
    if intensity == "持续升温":
        return "先观察是否有龙头走出来，再决定是不是把它抬到主线层。"
    return "先放进观察池，等题材热度和承接再同步一轮。"


def _theme_risk_note(followers: list[dict], change_pct: float) -> str:
    if any(_to_float(item.get("stop_loss")) <= 0 for item in followers):
        return "跟随票里有止损结构失真的样本，低质量补涨票先不要碰。"
    if change_pct >= 3.5:
        return "板块已经明显异动，追高风险抬升，优先看分歧后的承接。"
    if any((_to_float(item.get("risk_reward")) or 0.0) < 1.0 for item in followers):
        return "板块能看，但不是所有跟随票都值得做，盈亏比低的先排除。"
    return "优先盯前排核心票，分仓参与，不要平均撒网。"


def _truncate_hint(text: str, limit: int = 72) -> str:
    normalized = " ".join(str(text).split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1]}…"


def _load_news_digest() -> dict:
    def builder() -> dict:
        digest = safe_load(_NEWS_DIGEST, default={})
        return digest if isinstance(digest, dict) else {}

    return _cached_runtime_value(
        "load_news_digest",
        "default",
        ttl_seconds=8,
        dependency_paths=_runtime_cache_paths(_NEWS_DIGEST),
        builder=builder,
    )


def _load_policy_direction_catalog() -> list[dict]:
    def builder() -> list[dict]:
        payload = safe_load(_POLICY_DIRECTION_CATALOG, default={})
        if isinstance(payload, dict):
            directions = payload.get("directions", [])
            if isinstance(directions, list) and directions:
                normalized: list[dict] = []
                for item in directions:
                    if isinstance(item, dict):
                        normalized.append(item)
                if normalized:
                    return normalized
        return [dict(item) for item in _POLICY_DIRECTION_REGISTRY]

    return _cached_runtime_value(
        "load_policy_direction_catalog",
        "default",
        ttl_seconds=30,
        dependency_paths=_runtime_cache_paths(_POLICY_DIRECTION_CATALOG),
        builder=builder,
    )


def _load_policy_official_watch() -> dict[str, dict]:
    def builder() -> dict[str, dict]:
        payload = safe_load(_POLICY_OFFICIAL_WATCH, default={})
        if not isinstance(payload, dict):
            return {}

        directions = payload.get("directions", [])
        if not isinstance(directions, list):
            return {}

        normalized: dict[str, dict] = {}
        for item in directions:
            if not isinstance(item, dict):
                continue
            direction_id = str(item.get("id", "")).strip()
            if direction_id:
                normalized[direction_id] = item
        return normalized

    return _cached_runtime_value(
        "load_policy_official_watch",
        "default",
        ttl_seconds=30,
        dependency_paths=_runtime_cache_paths(_POLICY_OFFICIAL_WATCH),
        builder=builder,
    )


def _load_policy_official_cards() -> dict[str, dict]:
    def builder() -> dict[str, dict]:
        payload = safe_load(_POLICY_OFFICIAL_CARDS, default={})
        if not isinstance(payload, dict):
            return {}

        directions = payload.get("directions", [])
        if not isinstance(directions, list):
            return {}

        normalized: dict[str, dict] = {}
        for item in directions:
            if not isinstance(item, dict):
                continue
            direction_id = str(item.get("id", "")).strip()
            if direction_id:
                normalized[direction_id] = item
        return normalized

    return _cached_runtime_value(
        "load_policy_official_cards",
        "default",
        ttl_seconds=30,
        dependency_paths=_runtime_cache_paths(_POLICY_OFFICIAL_CARDS),
        builder=builder,
    )


def _load_policy_official_ingest() -> dict[str, dict]:
    def builder() -> dict[str, dict]:
        payload = safe_load(_POLICY_OFFICIAL_INGEST, default={})
        if not isinstance(payload, dict):
            return {}

        directions = payload.get("directions", [])
        if not isinstance(directions, list):
            return {}

        normalized: dict[str, dict] = {}
        for item in directions:
            if not isinstance(item, dict):
                continue
            direction_id = str(item.get("id", "")).strip()
            if direction_id:
                normalized[direction_id] = item
        return normalized

    return _cached_runtime_value(
        "load_policy_official_ingest",
        "default",
        ttl_seconds=30,
        dependency_paths=_runtime_cache_paths(_POLICY_OFFICIAL_INGEST),
        builder=builder,
    )


def _load_policy_execution_timeline() -> dict[str, dict]:
    def builder() -> dict[str, dict]:
        payload = safe_load(_POLICY_EXECUTION_TIMELINE, default={})
        if not isinstance(payload, dict):
            return {}

        directions = payload.get("directions", [])
        if not isinstance(directions, list):
            return {}

        normalized: dict[str, dict] = {}
        for item in directions:
            if not isinstance(item, dict):
                continue
            direction_id = str(item.get("id", "")).strip()
            if direction_id:
                normalized[direction_id] = item
        return normalized

    return _cached_runtime_value(
        "load_policy_execution_timeline",
        "default",
        ttl_seconds=30,
        dependency_paths=_runtime_cache_paths(_POLICY_EXECUTION_TIMELINE),
        builder=builder,
    )


def _load_industry_capital_company_map() -> dict[str, dict]:
    def builder() -> dict[str, dict]:
        payload = safe_load(_INDUSTRY_CAPITAL_COMPANY_MAP, default={})
        if not isinstance(payload, dict):
            return {}

        directions = payload.get("directions", [])
        if not isinstance(directions, list):
            return {}

        normalized: dict[str, dict] = {}
        for item in directions:
            if not isinstance(item, dict):
                continue
            direction_id = str(item.get("id", "")).strip()
            if direction_id:
                normalized[direction_id] = item
        return normalized

    return _cached_runtime_value(
        "load_industry_capital_company_map",
        "default",
        ttl_seconds=30,
        dependency_paths=_runtime_cache_paths(_INDUSTRY_CAPITAL_COMPANY_MAP),
        builder=builder,
    )


def _normalize_theme_key(value: object) -> str:
    normalized = "".join(str(value or "").split()).strip().lower()
    for token in ("板块", "概念", "主题", "行业", "产业"):
        normalized = normalized.replace(token, "")
    return normalized


def _match_event_sector(
    target_sector: Optional[str],
    sector_scores: dict[str, object],
) -> tuple[Optional[str], float]:
    if not target_sector or not isinstance(sector_scores, dict):
        return None, 0.0

    normalized_target = _normalize_theme_key(target_sector)
    if not normalized_target:
        return None, 0.0

    best_sector: Optional[str] = None
    best_score = 0.0

    for sector_name, raw_score in sector_scores.items():
        normalized_sector = _normalize_theme_key(sector_name)
        if not normalized_sector:
            continue
        if (
            normalized_target == normalized_sector
            or normalized_target in normalized_sector
            or normalized_sector in normalized_target
        ):
            score = _to_float(raw_score) or 0.0
            if best_sector is None or abs(score) > abs(best_score):
                best_sector = str(sector_name)
                best_score = score

    return best_sector, best_score


def _event_bias(sentiment: float, bullish_pressure: float, bearish_pressure: float) -> str:
    if sentiment <= -0.35 or bearish_pressure - bullish_pressure >= 2.5:
        return "偏空"
    if sentiment >= 0.35 or bullish_pressure - bearish_pressure >= 2.5:
        return "偏多"
    return "中性"


def _build_event_control_snapshot(signal: dict, theme_item: ThemeRadarItem | None) -> dict[str, object]:
    digest = _load_news_digest()
    heatmap = digest.get("heatmap", {})
    if not isinstance(heatmap, dict):
        heatmap = {}

    sentiment = _to_float(heatmap.get("sentiment"))
    if sentiment is None:
        sentiment = _to_float(digest.get("sentiment")) or 0.0

    sector_scores = heatmap.get("sectors", {})
    if not isinstance(sector_scores, dict):
        sector_scores = {}

    raw_events = digest.get("events", [])
    events = raw_events if isinstance(raw_events, list) else []
    bullish_pressure = 0.0
    bearish_pressure = 0.0
    for event in events:
        if not isinstance(event, dict):
            continue
        magnitude = max(1.0, _to_float(event.get("impact_magnitude")) or 1.0)
        urgency = str(event.get("urgency", "normal"))
        urgency_weight = {
            "critical": 1.8,
            "urgent": 1.45,
            "normal": 1.0,
            "low": 0.65,
        }.get(urgency, 1.0)
        pressure = magnitude * urgency_weight / 2.0
        direction = str(event.get("impact_direction", "neutral"))
        if direction == "bullish":
            bullish_pressure += pressure
        elif direction == "bearish":
            bearish_pressure += pressure

    bias = _event_bias(sentiment, bullish_pressure, bearish_pressure)
    theme_sector = theme_item.sector if theme_item else None
    matched_sector, matched_score = _match_event_sector(theme_sector, sector_scores)

    base_score = 50.0 + sentiment * 12.0
    if matched_sector:
        base_score += matched_score * 7.0
    elif theme_item and theme_item.intensity == "高热主线":
        base_score += 4.0 if sentiment >= 0 else -4.0

    if bias == "偏空" and matched_score <= 0:
        base_score -= 4.0
    elif bias == "偏多" and (matched_score > 0 or theme_item is not None):
        base_score += 4.0

    event_score = round(min(max(base_score, 28.0), 88.0), 1)

    if matched_sector and matched_score > 0:
        summary = f"事件总控偏向 {bias}，{matched_sector} 在宏观热力图里受益，综合层允许更积极地排前。"
    elif matched_sector and matched_score < 0:
        summary = f"事件总控偏向 {bias}，{matched_sector} 在宏观热力图里承压，这类票会被自动降权。"
    elif bias == "偏空":
        summary = "全球事件面偏空，综合层会主动收紧追高和无主线扩张。"
    elif bias == "偏多":
        summary = "全球事件面偏多，综合层会优先把主线清晰、承接更强的票抬到前排。"
    else:
        summary = "全球事件面暂时中性，综合层继续以主线、资金和执行位置为主。"

    position_adjustment = 0
    if matched_score >= 1.5 and bias != "偏空":
        position_adjustment = 2
    elif matched_score <= -1.5 or (bias == "偏空" and matched_score <= 0):
        position_adjustment = -2

    multiplier = 1.0 + (event_score - 50.0) / 400.0
    if matched_score <= -1.5:
        multiplier = min(multiplier, 0.94)
    elif matched_score >= 1.5 and bias == "偏多":
        multiplier = max(multiplier, 1.04)

    return {
        "score": event_score,
        "bias": bias,
        "summary": summary,
        "matched_sector": matched_sector,
        "position_adjustment": position_adjustment,
        "multiplier": round(multiplier, 4),
    }


def _build_event_positioning_overlay(
    *,
    top_theme: Optional[str],
    top_pick: CompositePick | None,
) -> dict[str, object]:
    digest = _load_news_digest()
    heatmap = digest.get("heatmap", {})
    if not isinstance(heatmap, dict):
        heatmap = {}

    sentiment = _to_float(heatmap.get("sentiment"))
    if sentiment is None:
        sentiment = _to_float(digest.get("sentiment")) or 0.0

    sector_scores = heatmap.get("sectors", {})
    if not isinstance(sector_scores, dict):
        sector_scores = {}

    raw_events = digest.get("events", [])
    events = raw_events if isinstance(raw_events, list) else []
    bullish_pressure = 0.0
    bearish_pressure = 0.0
    for event in events:
        if not isinstance(event, dict):
            continue
        magnitude = max(1.0, _to_float(event.get("impact_magnitude")) or 1.0)
        urgency = str(event.get("urgency", "normal"))
        urgency_weight = {
            "critical": 1.8,
            "urgent": 1.45,
            "normal": 1.0,
            "low": 0.65,
        }.get(urgency, 1.0)
        pressure = magnitude * urgency_weight / 2.0
        direction = str(event.get("impact_direction", "neutral"))
        if direction == "bullish":
            bullish_pressure += pressure
        elif direction == "bearish":
            bearish_pressure += pressure

    bias = _event_bias(sentiment, bullish_pressure, bearish_pressure)
    matched_sector, matched_score = _match_event_sector(top_theme, sector_scores)
    score = 50.0 + sentiment * 14.0
    if matched_sector:
        score += matched_score * 7.0
    score = round(min(max(score, 25.0), 85.0), 1)

    exposure_adjustment = 0.0
    first_entry_adjustment = 0
    single_cap_adjustment = 0
    theme_cap_adjustment = 0

    if bias == "偏空":
        exposure_adjustment -= 10.0 if sentiment <= -0.5 else 6.0
        first_entry_adjustment -= 2
        single_cap_adjustment -= 2
        theme_cap_adjustment -= 4
    elif bias == "偏多":
        exposure_adjustment += 4.0
        first_entry_adjustment += 1
        single_cap_adjustment += 1

    if matched_score >= 1.5:
        exposure_adjustment += 4.0
        first_entry_adjustment += 1
        single_cap_adjustment += 1
        theme_cap_adjustment += 4
    elif matched_score <= -1.5:
        exposure_adjustment -= 6.0
        first_entry_adjustment -= 2
        single_cap_adjustment -= 2
        theme_cap_adjustment -= 6

    if matched_sector and matched_score > 0:
        summary = (
            f"事件总控当前{bias}，且 {matched_sector} 在全球新闻热力图里受益。"
            " 仓位层允许更积极地向这条主线倾斜，但仍按分仓执行。"
        )
    elif matched_sector and matched_score < 0:
        summary = (
            f"事件总控当前{bias}，且 {matched_sector} 在全球新闻热力图里承压。"
            " 仓位层会主动收紧这条主线的总仓和首仓。"
        )
    elif bias == "偏空":
        summary = "全球事件面偏空，仓位层会先降总仓、降首仓，再谈新增进攻。"
    elif bias == "偏多":
        summary = "全球事件面偏多，仓位层允许在主线明确时更快部署，但不鼓励一把打满。"
    else:
        summary = "全球事件面暂时中性，仓位层继续以市场状态和综合推荐为主。"

    if top_pick is not None and top_pick.theme_sector and matched_sector and matched_score > 0:
        summary += f" 当前头部候选 {top_pick.code} {top_pick.name} 与事件主线更一致。"

    return {
        "bias": bias,
        "score": score,
        "summary": summary,
        "focus_sector": matched_sector or top_theme,
        "exposure_adjustment": exposure_adjustment,
        "first_entry_adjustment": first_entry_adjustment,
        "single_cap_adjustment": single_cap_adjustment,
        "theme_cap_adjustment": theme_cap_adjustment,
    }


def _build_strong_move_candidate_from_record(
    signal: dict,
    strategy_map: dict[str, StrategyPerformance],
) -> Optional[StrongMoveCandidate]:
    price = _to_float(signal.get("price")) or 0.0
    score = _to_float(signal.get("score")) or 0.0
    if price <= 0 or score < 0.45:
        return None

    raw_factor_scores = signal.get("factor_scores", {})
    factor_scores = raw_factor_scores if isinstance(raw_factor_scores, dict) else {}
    trend_score = _factor_bucket(
        factor_scores,
        [
            "s_trend",
            "s_momentum",
            "s_ma_alignment",
            "s_relative_strength",
            "s_sector_momentum",
            "s_trend_score",
        ],
    )
    heat_score = _factor_bucket(
        factor_scores,
        [
            "s_hot",
            "s_auction",
            "s_gap",
            "s_pm_gain",
            "s_5m_speed",
            "s_volume_breakout",
            "s_volume_ratio",
            "s_turnover",
            "s_vol_turn",
        ],
    )
    flow_score = _factor_bucket(
        factor_scores,
        [
            "s_fund_flow",
            "s_flow_1d",
            "s_flow_trend",
            "s_chip",
            "s_forecast",
            "s_fundamental",
        ],
    )
    strategy_name = str(signal.get("strategy", ""))
    strategy_perf = strategy_map.get(strategy_name)
    strategy_win_rate = strategy_perf.win_rate if strategy_perf else 50.0
    consensus_strength = min(max(_to_int(signal.get("consensus_count")), 1), 3) / 3
    regime_support = (
        0.7 if str(signal.get("regime", "")).lower() in {"bull", "neutral", "震荡", "强势"} else 0.45
    )
    rr = min(max((_to_float(signal.get("risk_reward")) or 0.0) / 3.0, 0.0), 1.0)
    strategy_quality = min(max(strategy_win_rate / 100.0, 0.0), 1.0)

    continuation_score = (
        score * 0.34
        + heat_score * 0.23
        + trend_score * 0.18
        + flow_score * 0.10
        + rr * 0.07
        + consensus_strength * 0.04
        + strategy_quality * 0.04
    )
    swing_score = (
        score * 0.27
        + trend_score * 0.28
        + flow_score * 0.16
        + strategy_quality * 0.10
        + rr * 0.10
        + regime_support * 0.09
    )
    continuation_pct = round(continuation_score * 100, 1)
    swing_pct = round(swing_score * 100, 1)
    composite_pct = round((continuation_score * 0.55 + swing_score * 0.45) * 100, 1)
    setup_label, conviction = _strong_move_label(continuation_pct, swing_pct, heat_score * 100)
    reasons = _strong_move_reasons(
        strategy_win_rate=strategy_win_rate,
        trend_score=trend_score,
        heat_score=heat_score,
        flow_score=flow_score,
        signal_score=score,
        risk_reward=_to_float(signal.get("risk_reward")) or 0.0,
    )

    return StrongMoveCandidate(
        id=f"strong-{signal.get('id', '')}",
        signal_id=str(signal.get("id", "")),
        code=str(signal.get("code", "")),
        name=str(signal.get("name", "")),
        strategy=strategy_name,
        setup_label=setup_label,
        conviction=conviction,
        composite_score=composite_pct,
        continuation_score=continuation_pct,
        swing_score=swing_pct,
        strategy_win_rate=round(strategy_win_rate, 1),
        price=price,
        buy_price=_to_float(signal.get("buy_price")) or price,
        stop_loss=_to_float(signal.get("stop_loss")) or 0.0,
        target_price=_to_float(signal.get("target_price")) or 0.0,
        risk_reward=_to_float(signal.get("risk_reward")) or 0.0,
        timestamp=str(signal.get("timestamp", "")),
        thesis=f"{setup_label}，当前更适合在风险可控下集中火力，而不是平均分仓追所有票。",
        next_step=_strong_move_next_step(setup_label),
        reasons=reasons,
    )


def _build_composite_pick_from_record(
    signal: dict,
    strategy_map: dict[str, StrategyPerformance],
    strong_move_map: dict[str, StrongMoveCandidate],
    theme_by_code: dict[str, ThemeRadarItem],
) -> Optional[CompositePick]:
    price = _to_float(signal.get("price")) or 0.0
    score = _to_float(signal.get("score")) or 0.0
    if price <= 0 or score < 0.45:
        return None

    strategy_name = str(signal.get("strategy", ""))
    strategy_perf = strategy_map.get(strategy_name)
    strategy_win_rate = strategy_perf.win_rate if strategy_perf else 50.0
    raw_factor_scores = signal.get("factor_scores", {})
    factor_scores = raw_factor_scores if isinstance(raw_factor_scores, dict) else {}
    trend_score = _factor_bucket(
        factor_scores,
        ["s_trend", "s_momentum", "s_ma_alignment", "s_relative_strength", "s_trend_score"],
    )
    heat_score = _factor_bucket(
        factor_scores,
        ["s_hot", "s_auction", "s_gap", "s_pm_gain", "s_volume_breakout", "s_volume_ratio", "s_turnover"],
    )
    flow_score = _factor_bucket(
        factor_scores,
        ["s_fund_flow", "s_flow_1d", "s_flow_trend", "s_chip", "s_forecast", "s_fundamental"],
    )
    consensus_strength = min(max(_to_int(signal.get("consensus_count")), 1), 3) / 3
    risk_reward = _to_float(signal.get("risk_reward")) or 0.0
    rr_norm = min(max(risk_reward / 3.0, 0.0), 1.0)
    regime_support = (
        0.75 if str(signal.get("regime", "")).lower() in {"bull", "neutral", "震荡", "强势"} else 0.4
    )
    strategy_quality = min(max(strategy_win_rate / 100.0, 0.0), 1.0)
    change_pct = _to_float(signal.get("change_pct")) or 0.0
    entry_window = _entry_window_score(change_pct)

    theme_item = theme_by_code.get(str(signal.get("code", "")))
    strong_move = strong_move_map.get(str(signal.get("code", "")))
    event_control = _build_event_control_snapshot(signal, theme_item)
    event_score = _to_float(event_control.get("score")) or 50.0

    strategy_score = round((score * 0.72 + strategy_quality * 0.28) * 100, 1)
    capital_score = round(
        (heat_score * 0.34 + flow_score * 0.31 + trend_score * 0.21 + consensus_strength * 0.14) * 100,
        1,
    )

    if theme_item:
        intensity_bonus = {"高热主线": 0.86, "持续升温": 0.68}.get(theme_item.intensity, 0.48)
        theme_score = round(
            (
                min(max(theme_item.score / 100.0, 0.0), 1.0) * 0.55
                + intensity_bonus * 0.30
                + min(max(theme_item.change_pct / 3.0, 0.0), 1.0) * 0.15
            )
            * 100,
            1,
        )
    else:
        sector_factor = _factor_bucket(factor_scores, ["s_sector_trend", "s_sector_momentum"])
        theme_score = round((sector_factor * 0.7 + 0.2) * 100, 1)

    execution_score = round(
        (rr_norm * 0.42 + regime_support * 0.22 + entry_window * 0.24 + trend_score * 0.12) * 100,
        1,
    )

    composite_score = (
        strategy_score * 0.32
        + capital_score * 0.24
        + theme_score * 0.18
        + event_score * 0.14
        + execution_score * 0.12
    )
    if strong_move:
        composite_score = composite_score * 0.8 + strong_move.composite_score * 0.2
    composite_score *= _to_float(event_control.get("multiplier")) or 1.0
    composite_score = round(composite_score, 1)

    setup_label = _composite_setup_label(
        composite_score,
        theme_item.intensity if theme_item else None,
        strong_move.setup_label if strong_move else None,
    )
    conviction = _composite_conviction(composite_score)
    first_position_pct = _composite_first_position_pct(
        composite_score,
        risk_reward,
        theme_item.intensity if theme_item else None,
    )
    first_position_pct = max(
        6,
        min(
            18,
            first_position_pct + _to_int(event_control.get("position_adjustment")),
        ),
    )
    reasons = _build_composite_pick_reasons(
        theme_item=theme_item,
        strong_move=strong_move,
        strategy_win_rate=strategy_win_rate,
        heat_score=heat_score,
        flow_score=flow_score,
        trend_score=trend_score,
        risk_reward=risk_reward,
    )
    event_summary = str(event_control.get("summary", "")).strip()
    if event_summary:
        reasons.insert(0, event_summary)
    reasons = reasons[:3]
    action = _composite_action(
        theme_item=theme_item,
        strong_move=strong_move,
        first_position_pct=first_position_pct,
        setup_label=setup_label,
    )
    source_category, source_label, horizon_label = _composite_source_profile(
        signal,
        theme_item=theme_item,
        strong_move=strong_move,
        composite_score=composite_score,
    )
    thesis = (
        f"{setup_label}：策略信号、资金承接、主题热度和执行位置已经进入同一张表，"
        "现在又叠加了事件总控排序，更适合优先看这类综合候选，而不是只盯单一评分。"
    )

    return CompositePick(
        id=f"composite-{signal.get('id', '')}",
        signal_id=str(signal.get("id", "")),
        code=str(signal.get("code", "")),
        name=str(signal.get("name", "")),
        strategy=strategy_name,
        theme_sector=theme_item.sector if theme_item else None,
        theme_intensity=theme_item.intensity if theme_item else None,
        setup_label=setup_label,
        conviction=conviction,
        composite_score=composite_score,
        strategy_score=strategy_score,
        capital_score=capital_score,
        theme_score=theme_score,
        event_score=event_score,
        event_bias=str(event_control.get("bias", "中性")),
        event_summary=event_summary or None,
        event_matched_sector=(
            str(event_control.get("matched_sector"))
            if event_control.get("matched_sector") is not None
            else None
        ),
        source_category=source_category,
        source_label=source_label,
        horizon_label=horizon_label,
        execution_score=execution_score,
        first_position_pct=first_position_pct,
        price=price,
        buy_price=_to_float(signal.get("buy_price")) or price,
        stop_loss=_to_float(signal.get("stop_loss")) or 0.0,
        target_price=_to_float(signal.get("target_price")) or 0.0,
        risk_reward=risk_reward,
        timestamp=str(signal.get("timestamp", "")),
        thesis=thesis,
        action=action,
        reasons=reasons,
    )


def _build_theme_radar(limit: int = 3) -> list[ThemeRadarItem]:
    def builder() -> list[ThemeRadarItem]:
        history = _load_sector_alert_history()
        raw_logs = history.get("today_log", [])
        if not isinstance(raw_logs, list):
            raw_logs = []

        message_center = _load_app_message_center()
        raw_messages = message_center.get("items", [])
        if not isinstance(raw_messages, list):
            raw_messages = []

        strong_moves = _build_strong_moves(days=1, limit=12)
        strong_move_map = {item.code: item for item in strong_moves}
        board_message_pool = [
            item for item in raw_messages if str(item.get("channel", "")) == "wechat_mirror"
        ]

        deduped_logs: dict[str, dict] = {}
        for item in raw_logs:
            sector_name = str(item.get("sector", "")).strip()
            if not sector_name:
                continue
            previous = deduped_logs.get(sector_name)
            prev_score = _to_float(previous.get("score")) if previous else -1.0
            current_score = _to_float(item.get("score"))
            prev_stamp = f"{previous.get('date', '')} {previous.get('time', '')}" if previous else ""
            current_stamp = f"{item.get('date', '')} {item.get('time', '')}"
            if previous is None or current_score >= prev_score or current_stamp >= prev_stamp:
                deduped_logs[sector_name] = item

        radar_items: list[ThemeRadarItem] = []
        for item in deduped_logs.values():
            sector_name = str(item.get("sector", "")).strip()
            followers_raw = item.get("followers", [])
            followers_list = followers_raw if isinstance(followers_raw, list) else []
            followers = [
                ThemeFollower(
                    code=str(follower.get("code", "")),
                    name=str(follower.get("name", "")),
                    change_pct=round(_to_float(follower.get("change_pct")) or 0.0, 3),
                    label=str(follower.get("label", "") or "观察"),
                    buy_price=round(_to_float(follower.get("buy_price")) or 0.0, 2),
                    stop_loss=round(_to_float(follower.get("stop_loss")) or 0.0, 2),
                    target_price=round(_to_float(follower.get("target_price")) or 0.0, 2),
                    risk_reward=round(_to_float(follower.get("risk_reward")) or 0.0, 2),
                )
                for follower in followers_list[:3]
                if str(follower.get("code", "")).strip()
            ]
            linked_signal = next(
                (strong_move_map[follower.code] for follower in followers if follower.code in strong_move_map),
                None,
            )
            intensity = _theme_intensity(
                score=_to_float(item.get("score")) or 0.0,
                change_pct=_to_float(item.get("change_pct")) or 0.0,
                follower_count=len(followers),
            )
            matching_message = next(
                (
                    message
                    for message in board_message_pool
                    if sector_name and sector_name in f"{message.get('title', '')} {message.get('body', '')}"
                ),
                None,
            )
            if matching_message is None:
                matching_message = next(
                    (
                        message
                        for message in board_message_pool
                        if "板块异动" in str(message.get("title", ""))
                    ),
                    None,
                )

            change_pct = round(_to_float(item.get("change_pct")) or 0.0, 3)
            score = round(_to_float(item.get("score")) or 0.0, 1)
            timestamp = f"{item.get('date', '')}T{item.get('time', '')}"
            narrative = (
                f"{sector_name} 当前涨幅 {change_pct:+.2f}% ，热度分 {score:.1f}。"
                f" 这更像 {intensity}，重点看板块里有没有票从跟涨走成主升。"
            )
            radar_items.append(
                ThemeRadarItem(
                    id=f"theme-{sector_name}-{item.get('date', '')}-{item.get('time', '')}",
                    sector=sector_name,
                    theme_type=str(item.get("type", "") or "theme"),
                    change_pct=change_pct,
                    score=score,
                    intensity=intensity,
                    timestamp=timestamp,
                    narrative=narrative,
                    action=_theme_action(intensity, linked_signal),
                    risk_note=_theme_risk_note(followers_list, change_pct),
                    message_hint=_truncate_hint(matching_message.get("preview")) if matching_message else None,
                    linked_signal_id=linked_signal.signal_id if linked_signal else None,
                    linked_code=linked_signal.code if linked_signal else None,
                    linked_name=linked_signal.name if linked_signal else None,
                    linked_setup_label=linked_signal.setup_label if linked_signal else None,
                    followers=followers,
                )
            )

        radar_items.sort(
            key=lambda item: (item.score, item.change_pct, len(item.followers)),
            reverse=True,
        )
        return radar_items[:limit]

    return _cached_runtime_value(
        "theme_radar",
        limit,
        ttl_seconds=10,
        dependency_paths=_runtime_cache_paths(
            _SECTOR_ALERTS,
            _APP_MESSAGE_CENTER,
            _SIGNAL_TRACKER,
            *_db_dependency_paths(),
        ),
        builder=builder,
    )


def _parse_digest_timestamp(value: object) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _policy_recency_weight(timestamp: object) -> float:
    parsed = _parse_digest_timestamp(timestamp)
    if parsed is None:
        return 0.9

    age_hours = max((datetime.now() - parsed).total_seconds() / 3600.0, 0.0)
    if age_hours <= 12:
        return 1.25
    if age_hours <= 36:
        return 1.05
    if age_hours <= 72:
        return 0.85
    return 0.65


def _match_policy_focus_sectors(focus_sectors: tuple[str, ...], candidates: list[str]) -> list[str]:
    matched: list[str] = []
    normalized_focus = {_normalize_theme_key(item): item for item in focus_sectors if item}
    for candidate in candidates:
        normalized_candidate = _normalize_theme_key(candidate)
        if not normalized_candidate:
            continue
        for normalized_focus_sector, focus_sector in normalized_focus.items():
            if (
                normalized_candidate == normalized_focus_sector
                or normalized_candidate in normalized_focus_sector
                or normalized_focus_sector in normalized_candidate
            ):
                if focus_sector not in matched:
                    matched.append(focus_sector)
                break
    return matched


def _policy_keyword_hits(text: str, keywords: tuple[str, ...]) -> int:
    normalized = text.lower()
    return sum(1 for keyword in keywords if keyword and keyword.lower() in normalized)


def _policy_stage_label(stage_score: float, net_pressure: float) -> str:
    if stage_score < 42 or net_pressure <= -1.0:
        return "承压观察"
    if stage_score < 58:
        return "政策跟踪"
    if stage_score < 74:
        return "催化升温"
    return "兑现扩散"


def _policy_industry_phase(stage_label: str, phase_map: dict[str, object]) -> str:
    if stage_label == "承压观察":
        return str(phase_map.get("watch", "导入验证期"))
    if stage_label == "政策跟踪":
        return str(phase_map.get("watch", "导入验证期"))
    if stage_label == "催化升温":
        return str(phase_map.get("warming", "渗透加速期"))
    return str(phase_map.get("expansion", "业绩兑现期"))


def _policy_participation_label(
    stage_label: str,
    top_pick: CompositePick | None,
    strongest_move: StrongMoveCandidate | None,
) -> str:
    if stage_label == "承压观察":
        return "先观察"
    if strongest_move and strongest_move.setup_label == "连涨候选":
        return "连涨接力"
    if top_pick and top_pick.horizon_label == "中期波段":
        return "中期波段"
    if stage_label == "兑现扩散":
        return "主线推进"
    return "主线观察"


def _policy_direction_action(
    direction: str,
    participation_label: str,
    linked_code: Optional[str],
    linked_name: Optional[str],
) -> str:
    if linked_code:
        return (
            f"{direction} 当前先盯 {linked_code} {linked_name or ''}，"
            f"按 {participation_label} 节奏做，不要把后排跟风票当成政策主线本体。"
        ).strip()
    if participation_label == "先观察":
        return f"{direction} 先挂到观察层，等板块里真正走出前排承接后再上强度。"
    return f"{direction} 方向已经能看，但要先等板块里最强票把节奏带出来。"


def _policy_direction_risk_note(
    stage_label: str,
    positive_pressure: float,
    negative_pressure: float,
    has_linked_pick: bool,
) -> str:
    if negative_pressure > positive_pressure + 0.8:
        return "政策和地缘消息还在互相打架，先别把 headline 当成已经兑现的产业逻辑。"
    if stage_label == "兑现扩散":
        return "方向不差，但位置已经不早，别把高位情绪票误当成底部政策票。"
    if not has_linked_pick:
        return "方向已经进入雷达，但板块里还没走出足够硬的前排承接票。"
    return "方向能看，但执行上仍要分仓，先主线前排，再看是否有扩散机会。"


def _policy_phase_summary(
    industry_phase: str,
    demand_drivers: list[str],
    supply_drivers: list[str],
) -> str:
    demand = "、".join(demand_drivers[:2]) if demand_drivers else "需求验证"
    supply = "、".join(supply_drivers[:2]) if supply_drivers else "供给修复"
    return f"{industry_phase}：需求侧先看 {demand}，供给侧重点跟踪 {supply}。"


def _build_policy_watch_item(
    *,
    entry: dict,
    events: list[dict],
    theme_radar: list[ThemeRadarItem],
    composite_picks: list[CompositePick],
    strong_move_map: dict[str, StrongMoveCandidate],
) -> Optional[PolicyWatchItem]:
    focus_sectors = tuple(str(item) for item in entry.get("focus_sectors", []) if str(item).strip())
    keywords = tuple(str(item) for item in entry.get("keywords", []) if str(item).strip())
    phase_map_raw = entry.get("industry_phase_map", {})
    phase_map = phase_map_raw if isinstance(phase_map_raw, dict) else {}
    demand_drivers = [str(item) for item in entry.get("demand_drivers", []) if str(item).strip()]
    supply_drivers = [str(item) for item in entry.get("supply_drivers", []) if str(item).strip()]
    upstream = [str(item) for item in entry.get("upstream", []) if str(item).strip()]
    midstream = [str(item) for item in entry.get("midstream", []) if str(item).strip()]
    downstream = [str(item) for item in entry.get("downstream", []) if str(item).strip()]
    milestones = [str(item) for item in entry.get("milestones", []) if str(item).strip()]
    transmission_paths = [str(item) for item in entry.get("transmission_paths", []) if str(item).strip()]
    positive_pressure = 0.0
    negative_pressure = 0.0
    attention_units = 0.0
    matched_event_count = 0
    driver_titles: list[str] = []
    matched_focuses: list[str] = []

    for event in events:
        if not isinstance(event, dict):
            continue

        title = str(event.get("title", "")).strip()
        implications = str(event.get("strategy_implications", "")).strip()
        text = f"{title} {implications}".strip()
        keyword_hits = _policy_keyword_hits(text, keywords)

        affected_sectors = event.get("affected_sectors", [])
        if not isinstance(affected_sectors, list):
            affected_sectors = []
        sector_impacts = event.get("sector_impacts", {})
        if not isinstance(sector_impacts, dict):
            sector_impacts = {}
        event_sectors = [str(item) for item in affected_sectors] + [str(item) for item in sector_impacts.keys()]
        matched_sectors = _match_policy_focus_sectors(focus_sectors, event_sectors)

        if keyword_hits == 0 and not matched_sectors:
            continue

        matched_event_count += 1
        for focus_sector in matched_sectors:
            if focus_sector not in matched_focuses:
                matched_focuses.append(focus_sector)

        magnitude = max(1.0, _to_float(event.get("impact_magnitude")) or 1.0)
        confidence = _clamp(_to_float(event.get("confidence")) or 0.5, 0.3, 1.0)
        urgency_weight = {
            "critical": 1.8,
            "urgent": 1.45,
            "normal": 1.0,
            "low": 0.65,
        }.get(str(event.get("urgency", "normal")), 1.0)
        recency_weight = _policy_recency_weight(event.get("timestamp"))
        base_weight = magnitude * confidence * urgency_weight * recency_weight
        base_weight *= 1.0 + keyword_hits * 0.12 + len(matched_sectors) * 0.08

        sector_signal = 0.0
        for sector_name, raw_score in sector_impacts.items():
            if _match_policy_focus_sectors(focus_sectors, [str(sector_name)]):
                sector_signal += _to_float(raw_score) or 0.0
        if sector_signal == 0.0:
            direction = str(event.get("impact_direction", "neutral"))
            if direction == "bullish":
                sector_signal = magnitude
            elif direction == "bearish":
                sector_signal = -magnitude

        attention_units += base_weight
        if sector_signal >= 0:
            positive_pressure += abs(sector_signal) * base_weight
        else:
            negative_pressure += abs(sector_signal) * base_weight

        if title and title not in driver_titles:
            driver_titles.append(title)

    related_themes = [
        item
        for item in theme_radar
        if _match_policy_focus_sectors(focus_sectors, [item.sector])
    ]
    related_themes.sort(key=lambda item: (item.score, item.change_pct, len(item.followers)), reverse=True)
    top_theme = related_themes[0] if related_themes else None

    related_picks = [
        pick
        for pick in composite_picks
        if _match_policy_focus_sectors(
            focus_sectors,
            [pick.theme_sector or "", pick.event_matched_sector or ""],
        )
    ]
    related_picks.sort(key=lambda item: item.composite_score, reverse=True)
    top_pick = related_picks[0] if related_picks else None

    strongest_move: StrongMoveCandidate | None = None
    if top_pick is not None:
        strongest_move = strong_move_map.get(top_pick.code)
    if strongest_move is None and top_theme and top_theme.linked_code:
        strongest_move = strong_move_map.get(top_theme.linked_code)

    if matched_event_count == 0 and top_theme is None and top_pick is None:
        return None

    policy_score = round(
        _clamp(
            48.0
            + (positive_pressure - negative_pressure) * 4.2
            + (4.0 if top_theme is not None else 0.0)
            + (
                4.0
                if top_pick is not None and top_pick.event_bias == "偏多"
                else -4.0 if top_pick is not None and top_pick.event_bias == "偏空" else 0.0
            ),
            22.0,
            92.0,
        ),
        1,
    )
    attention_score = round(
        _clamp(
            34.0
            + attention_units * 7.0
            + matched_event_count * 3.5
            + (5.0 if top_theme is not None and top_theme.message_hint else 0.0),
            18.0,
            92.0,
        ),
        1,
    )
    capital_score = round(
        _clamp(
            (top_pick.capital_score if top_pick is not None else 45.0) * 0.62
            + (strongest_move.continuation_score if strongest_move is not None else 44.0) * 0.38
            + (
                6.0
                if top_theme is not None and top_theme.intensity == "高热主线"
                else 3.0 if top_theme is not None and top_theme.intensity == "持续升温" else 0.0
            ),
            20.0,
            92.0,
        ),
        1,
    )
    trend_score = round(
        _clamp(
            (strongest_move.swing_score if strongest_move is not None else 42.0) * 0.44
            + (top_pick.theme_score if top_pick is not None else 45.0) * 0.28
            + (min(max((top_theme.change_pct if top_theme is not None else 0.0) * 18.0, 0.0), 35.0) * 0.28),
            18.0,
            92.0,
        ),
        1,
    )

    raw_stage = 40.0
    if policy_score >= 60:
        raw_stage += 10.0
    if top_theme is not None:
        raw_stage += 8.0 if top_theme.intensity == "高热主线" else 4.0
    if strongest_move is not None:
        if strongest_move.setup_label == "波段候选":
            raw_stage += 16.0
        elif strongest_move.setup_label == "连涨候选":
            raw_stage += 24.0
    if top_pick is not None and top_pick.horizon_label == "中期波段":
        raw_stage += 10.0
    if negative_pressure > positive_pressure + 0.8:
        raw_stage -= 14.0
    elif positive_pressure > negative_pressure + 0.8:
        raw_stage += 8.0
    stage_score = round(_clamp(raw_stage, 22.0, 90.0), 1)
    net_pressure = positive_pressure - negative_pressure
    stage_label = _policy_stage_label(stage_score, net_pressure)
    industry_phase = _policy_industry_phase(stage_label, phase_map)
    participation_label = _policy_participation_label(stage_label, top_pick, strongest_move)
    direction_score = round(
        policy_score * 0.34
        + trend_score * 0.20
        + attention_score * 0.18
        + capital_score * 0.18
        + stage_score * 0.10,
        1,
    )

    linked_signal_id = (top_pick.signal_id if top_pick is not None else None) or (
        top_theme.linked_signal_id if top_theme is not None else None
    )
    linked_code = (
        (top_pick.code if top_pick is not None else None)
        or (top_theme.linked_code if top_theme is not None else None)
        or (top_theme.followers[0].code if top_theme is not None and top_theme.followers else None)
    )
    linked_name = (
        (top_pick.name if top_pick is not None else None)
        or (top_theme.linked_name if top_theme is not None else None)
        or (top_theme.followers[0].name if top_theme is not None and top_theme.followers else None)
    )
    linked_setup_label = (
        (top_pick.horizon_label if top_pick is not None else None)
        or (top_theme.linked_setup_label if top_theme is not None else None)
        or (strongest_move.setup_label if strongest_move is not None else None)
    )
    focus_sector = (
        top_theme.sector
        if top_theme is not None
        else matched_focuses[0]
        if matched_focuses
        else focus_sectors[0]
    )

    summary = (
        f"{entry['direction']} 当前更像 {stage_label}，{focus_sector} 是最直接的映射方向。"
        f" 当前行业阶段是 {industry_phase}，政策分 {policy_score:.1f}，"
        "先看它能不能继续把主线承接带起来。"
    )
    action = _policy_direction_action(str(entry["direction"]), participation_label, linked_code, linked_name)
    risk_note = _policy_direction_risk_note(
        stage_label,
        positive_pressure=positive_pressure,
        negative_pressure=negative_pressure,
        has_linked_pick=bool(linked_code),
    )
    phase_summary = _policy_phase_summary(industry_phase, demand_drivers, supply_drivers)

    drivers = [
        f"政策分 {policy_score:.1f}",
        f"趋势分 {trend_score:.1f}",
        f"关注度分 {attention_score:.1f}",
        f"资金偏好分 {capital_score:.1f}",
    ]
    if matched_event_count > 0:
        drivers.append(f"最近匹配政策/事件 {matched_event_count} 条")
    if milestones:
        drivers.append(f"兑现链：{' -> '.join(milestones[:3])}")
    for title in driver_titles[:2]:
        drivers.append(_truncate_hint(title, limit=48))

    return PolicyWatchItem(
        id=f"policy-watch-{entry['id']}",
        direction=str(entry["direction"]),
        policy_bucket=str(entry["policy_bucket"]),
        focus_sector=focus_sector,
        stage_label=stage_label,
        participation_label=participation_label,
        industry_phase=industry_phase,
        direction_score=direction_score,
        policy_score=policy_score,
        trend_score=trend_score,
        attention_score=attention_score,
        capital_preference_score=capital_score,
        linked_signal_id=linked_signal_id,
        linked_code=linked_code,
        linked_name=linked_name,
        linked_setup_label=linked_setup_label,
        summary=summary,
        action=action,
        risk_note=risk_note,
        phase_summary=phase_summary,
        demand_drivers=demand_drivers[:3],
        supply_drivers=supply_drivers[:3],
        upstream=upstream[:3],
        midstream=midstream[:3],
        downstream=downstream[:3],
        milestones=milestones[:5],
        transmission_paths=transmission_paths[:3],
        drivers=drivers[:6],
    )


def _build_policy_watch(limit: int = 3) -> list[PolicyWatchItem]:
    def builder() -> list[PolicyWatchItem]:
        digest = _load_news_digest()
        raw_events = digest.get("events", [])
        events = raw_events if isinstance(raw_events, list) else []
        policy_catalog = _load_policy_direction_catalog()
        theme_radar = _build_theme_radar(limit=8)
        composite_picks = _build_composite_picks(days=1, limit=12)
        strong_moves = _build_strong_moves(days=1, limit=12)
        strong_move_map = {item.code: item for item in strong_moves}

        items: list[PolicyWatchItem] = []
        for entry in policy_catalog:
            item = _build_policy_watch_item(
                entry=entry,
                events=events,
                theme_radar=theme_radar,
                composite_picks=composite_picks,
                strong_move_map=strong_move_map,
            )
            if item is not None:
                items.append(item)

        items.sort(
            key=lambda item: (item.direction_score, item.policy_score, item.attention_score, item.capital_preference_score),
            reverse=True,
        )
        return items[:limit]

    return _cached_runtime_value(
        "policy_watch",
        limit,
        ttl_seconds=12,
        dependency_paths=_runtime_cache_paths(
            _NEWS_DIGEST,
            _POLICY_DIRECTION_CATALOG,
            _SECTOR_ALERTS,
            _APP_MESSAGE_CENTER,
            _SIGNAL_TRACKER,
            *_db_dependency_paths(),
        ),
        builder=builder,
    )


def _industry_capital_label(
    strategic_score: float,
    stage_label: str,
    participation_label: str,
) -> str:
    if stage_label == "承压观察" or strategic_score < 46:
        return "逆风跟踪"
    if participation_label in {"中期波段", "连涨接力"} or strategic_score >= 72:
        return "中线布局"
    if participation_label in {"主线观察", "先观察"}:
        return "早期卡位"
    return "兑现推进"


def _industry_business_horizon(industry_phase: str, stage_label: str) -> str:
    if stage_label == "承压观察":
        return "3-6个月跟踪"
    if "升温" in industry_phase or "早期" in industry_phase:
        return "6-24个月布局"
    if "扩散" in industry_phase or "加速" in industry_phase:
        return "3-12个月推进"
    return "1-3个季度兑现"


def _industry_capital_horizon(participation_label: str) -> str:
    if participation_label == "连涨接力":
        return "1-10个交易日"
    if participation_label == "中期波段":
        return "1-3个月"
    if participation_label == "主线观察":
        return "1-4周"
    return "等待确认"


def _industry_business_action(
    direction: str,
    industry_phase: str,
    stage_label: str,
    focus_sector: str,
    upstream: list[str],
    midstream: list[str],
    downstream: list[str],
) -> str:
    if stage_label == "承压观察":
        return (
            f"{direction} 先做产业链跟踪，不急着投资源。先围绕 {focus_sector} 建调研清单，"
            "优先确认替代空间、价格传导和政策兑现节奏。"
        )
    if "升温" in industry_phase or "早期" in industry_phase:
        focus = "、".join((upstream[:1] + midstream[:1])[:2]) or focus_sector
        return f"{direction} 适合先卡位 {focus}，优先做供应链摸底、能力验证和合作名单。"
    if "扩散" in industry_phase or "加速" in industry_phase:
        focus = "、".join((midstream[:1] + downstream[:1])[:2]) or focus_sector
        return f"{direction} 已进入可推进区，先围绕 {focus} 跟订单、扩产和渠道兑现。"
    focus = "、".join(downstream[:1]) or focus_sector
    return f"{direction} 先盯 {focus} 的兑现节奏，再决定是否扩大事业投入。"


def _industry_capital_action(
    participation_label: str,
    linked_code: Optional[str],
    linked_name: Optional[str],
    focus_sector: str,
) -> str:
    if participation_label == "连涨接力":
        target = f"{linked_code} {linked_name}" if linked_code and linked_name else focus_sector
        return f"资本侧只做强承接龙头，优先盯 {target}，轻仓快进快出，不碰后排。"
    if participation_label == "中期波段":
        target = f"{linked_code} {linked_name}" if linked_code and linked_name else focus_sector
        return f"资本侧可围绕 {target} 做中期波段，按首仓和主题上限分批介入。"
    if participation_label == "主线观察":
        target = f"{linked_code} {linked_name}" if linked_code and linked_name else focus_sector
        return f"资本侧先把 {target} 放进主线观察池，诊股确认后再试错。"
    return f"资本侧先观察 {focus_sector}，不要急着追价，等主线和资金再确认。"


def _policy_direction_key(policy: PolicyWatchItem) -> str:
    return policy.id.removeprefix("policy-watch-")


def _default_official_sources(policy: PolicyWatchItem) -> list[str]:
    bucket_map = {
        "国家战略": ["国务院", "发改委", "工信部"],
        "全球博弈": ["国务院", "商务部", "工信部"],
        "国家安全": ["国务院", "财政预算口径", "工信部"],
        "产业升级": ["发改委", "工信部", "国家能源局"],
        "宏观政策": ["国务院", "央行", "财政部"],
        "经济修复": ["国务院", "商务部", "统计局"],
    }
    return bucket_map.get(policy.policy_bucket, ["国务院", "发改委", "工信部"])


def _default_official_watchpoints(policy: PolicyWatchItem) -> list[str]:
    watchpoints = [
        f"跟踪 {policy.direction} 对 {policy.focus_sector} 的政策提法和细则",
        f"确认 {policy.focus_sector} 是否出现订单、招标或项目兑现",
        f"观察 {policy.focus_sector} 是否出现主线承接和资金扩散",
    ]
    if policy.milestones:
        watchpoints.append(f"沿着 {' -> '.join(policy.milestones[:3])} 跟兑现节奏")
    return watchpoints[:4]


def _default_business_checklist(policy: PolicyWatchItem) -> list[str]:
    checklist = [
        f"梳理 {policy.focus_sector} 上下游关键环节和替代关系",
        f"确认需求侧 {'、'.join(policy.demand_drivers[:2]) if policy.demand_drivers else '核心驱动'} 是否持续",
        f"确认供给侧 {'、'.join(policy.supply_drivers[:2]) if policy.supply_drivers else '关键约束'} 是否变化",
        "建立项目、订单、价格和利润的跟踪表",
    ]
    return checklist[:4]


def _default_capital_checklist(policy: PolicyWatchItem) -> list[str]:
    checklist = [
        "先看前排承接和成交额，再决定是否提高仓位",
        "确认主线是否从事件刺激走向持续扩散",
        "只做真受益环节，不碰后排伪概念",
        "等资金和兑现同步后再扩大仓位",
    ]
    if policy.stage_label == "承压观察":
        checklist[0] = "先观察，不急着出手，等资金确认后再试错"
    return checklist[:4]


def _default_official_documents(policy: PolicyWatchItem) -> list[str]:
    docs = [f"{policy.policy_bucket} 相关官方口径", f"{policy.direction} 对应政策文件", "政府工作报告/部委文件"]
    return docs[:3]


def _default_timeline_checkpoints(policy: PolicyWatchItem) -> list[str]:
    if policy.milestones:
        return policy.milestones[:5]
    return ["政策定调", "细则落地", "项目/采购", "订单/价格", "业绩验证"]


def _default_cooperation_targets(policy: PolicyWatchItem) -> list[str]:
    targets: list[str] = []
    if policy.upstream:
        targets.append(f"上游 {policy.upstream[0]}")
    if policy.midstream:
        targets.append(f"中游 {policy.midstream[0]}")
    if policy.downstream:
        targets.append(f"下游 {policy.downstream[0]}")
    targets.append(f"{policy.focus_sector} 重点客户与渠道方")
    return targets[:4]


def _default_cooperation_modes(policy: PolicyWatchItem) -> list[str]:
    modes = ["联合试点", "供应链导入", "渠道合作", "项目协同"]
    if policy.stage_label == "承压观察":
        modes[0] = "先调研验证"
    return modes[:4]


def _default_company_watchlist(policy: PolicyWatchItem) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if policy.linked_code and policy.linked_name:
        items.append(
            {
                "code": policy.linked_code,
                "name": policy.linked_name,
                "role": "交易焦点",
                "chain_position": "市场焦点",
                "tracking_reason": "这是当前系统已经识别出的焦点票，适合先拿来做资本验证。",
                "action": "先诊股，再确认是否进入首批观察。",
            }
        )

    for label, chain_nodes in (
        ("上游机会", policy.upstream),
        ("中游能力", policy.midstream),
        ("下游兑现", policy.downstream),
    ):
        if not chain_nodes:
            continue
        items.append(
            {
                "code": "",
                "name": chain_nodes[0],
                "role": label,
                "chain_position": label.removesuffix("机会").removesuffix("能力").removesuffix("兑现"),
                "tracking_reason": f"先围绕 {chain_nodes[0]} 建名单，再找真正的受益公司和调研对象。",
                "action": "先补公司名单和客户验证。",
            }
        )
        if len(items) >= 3:
            break

    return items[:4]


def _normalize_company_watchlist(items: object) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []

    normalized: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        normalized.append(
            {
                "code": str(item.get("code") or "").strip(),
                "name": name,
                "role": str(item.get("role") or "观察标的").strip() or "观察标的",
                "chain_position": str(item.get("chain_position") or "产业链").strip() or "产业链",
                "tracking_reason": str(item.get("tracking_reason") or "").strip(),
                "action": str(item.get("action") or "").strip(),
            }
        )
    return normalized


def _default_research_targets(policy: PolicyWatchItem) -> list[str]:
    targets: list[str] = []
    if policy.upstream:
        targets.append(f"{policy.upstream[0]} 供应商")
    if policy.midstream:
        targets.append(f"{policy.midstream[0]} 集成商/制造方")
    if policy.downstream:
        targets.append(f"{policy.downstream[0]} 客户")
    targets.append(f"{policy.focus_sector} 行业专家")
    return targets[:4]


def _default_validation_signals(policy: PolicyWatchItem) -> list[str]:
    signals = [
        f"{policy.focus_sector} 是否出现订单、招标或项目验证",
        f"{policy.focus_sector} 前排龙头是否出现承接和放量",
        "价格、利润或渗透率是否开始兑现",
        "政策口径是否升级为细则和采购动作",
    ]
    return signals[:4]


def _default_official_cards(
    policy: PolicyWatchItem,
    official_sources: list[str],
    official_documents: list[str],
    official_watchpoints: list[str],
    timeline_checkpoints: list[str],
) -> list[dict[str, str]]:
    source = " / ".join(official_sources[:2]) or "国务院 / 部委口径"
    primary_document = official_documents[0] if official_documents else f"{policy.direction} 相关官方口径"
    primary_watch = (
        official_watchpoints[0]
        if official_watchpoints
        else f"跟踪 {policy.focus_sector} 的政策细则、项目和采购动作"
    )
    next_timeline = (
        timeline_checkpoints[1]
        if len(timeline_checkpoints) > 1
        else (timeline_checkpoints[0] if timeline_checkpoints else "细则和项目落地")
    )
    return [
        {
            "title": primary_document,
            "source": source,
            "excerpt": (
                f"{policy.direction} 当前主要围绕 {policy.focus_sector} 展开，"
                f"行业阶段是 {policy.industry_phase}。"
            ),
            "why_it_matters": (
                f"这决定了 {policy.focus_sector} 现在更适合先做跟踪、试点验证，"
                f"还是已经进入可交易、可扩张的兑现阶段。"
            ),
            "next_watch": primary_watch,
        },
        {
            "title": f"{policy.focus_sector} 兑现链观察",
            "source": source,
            "excerpt": (
                f"当前需要从 {timeline_checkpoints[0] if timeline_checkpoints else '政策定调'}"
                f" 继续推进到订单、招标、价格或利润验证。"
            ),
            "why_it_matters": "只有政策从提法走到动作，方向才有资格从故事变成主线。",
            "next_watch": next_timeline,
        },
    ]


def _normalize_official_cards(items: object) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []

    normalized: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        source = str(item.get("source") or "").strip()
        excerpt = str(item.get("excerpt") or "").strip()
        why_it_matters = str(item.get("why_it_matters") or "").strip()
        next_watch = str(item.get("next_watch") or "").strip()
        if not title or not excerpt:
            continue
        normalized.append(
            {
                "title": title,
                "source": source or "官方口径",
                "excerpt": excerpt,
                "why_it_matters": why_it_matters or "继续跟踪政策兑现、供需变化和资金承接。",
                "next_watch": next_watch or "继续跟踪细则、项目和采购动作。",
            }
        )
    return normalized


def _default_official_source_entries(
    policy: PolicyWatchItem,
    official_sources: list[str],
    official_documents: list[str],
    official_watchpoints: list[str],
    official_cards: list[dict[str, str]],
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for index, card in enumerate(official_cards[:2]):
        issuer = card.get("source") or "官方口径"
        title = official_documents[index] if index < len(official_documents) else card.get("title") or policy.direction
        entries.append(
            {
                "title": title,
                "issuer": issuer,
                "published_at": None,
                "source_type": "官方原文",
                "excerpt": card.get("excerpt") or policy.summary,
                "reference": None,
                "reference_url": None,
                "key_points": [
                    card.get("why_it_matters") or f"{policy.focus_sector} 的方向判断需要继续验证。",
                    official_watchpoints[index] if index < len(official_watchpoints) else policy.action,
                ],
                "watch_tags": official_watchpoints[:2],
            }
        )
    if not entries and official_documents:
        entries.append(
            {
                "title": official_documents[0],
                "issuer": " / ".join(official_sources[:2]) or "官方口径",
                "published_at": None,
                "source_type": "官方原文",
                "excerpt": policy.summary,
                "reference": None,
                "reference_url": None,
                "key_points": official_watchpoints[:2] or [policy.action],
                "watch_tags": official_watchpoints[:2],
            }
        )
    return entries


def _normalize_official_source_entries(items: object) -> list[dict[str, object]]:
    if not isinstance(items, list):
        return []

    normalized: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        issuer = str(item.get("issuer") or item.get("source") or "").strip()
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
                "reference_url": str(item.get("reference_url") or item.get("url") or "").strip() or None,
                "key_points": key_points[:4],
                "watch_tags": watch_tags[:4],
            }
        )
    return normalized


def _industry_official_freshness(
    official_source_entries: list[dict[str, object]],
) -> tuple[float, str]:
    published_dates: list[date] = []
    for item in official_source_entries:
        raw = str(item.get("published_at") or "").strip()
        if not raw:
            continue
        try:
            published_dates.append(date.fromisoformat(raw))
        except ValueError:
            continue

    if not published_dates:
        return 46.0, "待补官方日期"

    latest = max(published_dates)
    age_days = max((date.today() - latest).days, 0)
    if age_days <= 10:
        return 72.0, "近10天官方催化"
    if age_days <= 30:
        return 66.0, "近30天官方催化"
    if age_days <= 90:
        return 58.0, "近季度官方口径"
    return 52.0, "存量官方口径"


def _timeline_emphasis(signal_label: str, lane: str) -> str:
    normalized = str(signal_label or "").strip()
    if normalized in {"已验证", "验证增强"}:
        return "success"
    if normalized in {"有阻力", "出现阻力"}:
        return "warning"
    if lane == "official":
        return "info"
    return "neutral"


def _timeline_stage_label(
    lane: str,
    *,
    index: int = 0,
    checkpoint: str = "",
    item: Optional[IndustryCapitalResearchItem] = None,
) -> str:
    if lane == "official":
        return "官方定调" if index == 0 else "官方跟踪"
    if lane == "execution":
        return checkpoint or "兑现节点"
    if item is not None:
        if item.status == "已验证":
            return "调研验证"
        if item.status == "有阻力":
            return "调研阻力"
        return "调研跟踪"
    return "观察中"


def _build_industry_capital_timeline_events(
    *,
    direction_id: str,
    policy: PolicyWatchItem,
    official_source_entries: list[dict[str, object]] | None = None,
    official_cards: list[dict[str, str]],
    official_documents: list[str],
    timeline_checkpoints: list[str],
    research_items: list[IndustryCapitalResearchItem],
) -> list[IndustryCapitalTimelineEvent]:
    events: list[IndustryCapitalTimelineEvent] = []
    official_source_entries = official_source_entries or []

    if official_source_entries:
        for index, entry in enumerate(official_source_entries[:2]):
            key_points = entry.get("key_points", [])
            first_point = key_points[0] if isinstance(key_points, list) and key_points else None
            watch_tags = entry.get("watch_tags", [])
            next_action = (
                "继续盯 " + "、".join(watch_tags[:2])
                if isinstance(watch_tags, list) and watch_tags
                else (timeline_checkpoints[0] if timeline_checkpoints else "继续跟踪细则和采购动作")
            )
            events.append(
                IndustryCapitalTimelineEvent(
                    id=f"{direction_id}-official-ingest-{index + 1}",
                    lane="official",
                    stage=_timeline_stage_label("official", index=index),
                    title=str(entry.get("title") or f"{policy.direction} 官方口径"),
                    summary=str(first_point or entry.get("excerpt") or policy.summary),
                    source=str(entry.get("issuer") or "官方口径"),
                    signal_label=str(entry.get("source_type") or "官方原文"),
                    emphasis=_timeline_emphasis("官方原文", "official"),
                    timestamp=str(entry.get("published_at") or "") or None,
                    next_action=next_action,
                )
            )
    else:
        for index, card in enumerate(official_cards[:2]):
            events.append(
                IndustryCapitalTimelineEvent(
                    id=f"{direction_id}-official-{index + 1}",
                    lane="official",
                    stage=_timeline_stage_label("official", index=index),
                    title=card.get("title") or f"{policy.direction} 官方口径",
                    summary=card.get("why_it_matters") or card.get("excerpt") or policy.summary,
                    source=card.get("source") or "官方口径",
                    signal_label="官方原文",
                    emphasis=_timeline_emphasis("官方原文", "official"),
                    next_action=card.get("next_watch") or (
                        timeline_checkpoints[0] if timeline_checkpoints else "继续跟踪细则和采购动作"
                    ),
                )
            )

    for index, checkpoint in enumerate(timeline_checkpoints[:4]):
        stage = _timeline_stage_label("execution", checkpoint=checkpoint)
        source = official_documents[index] if index < len(official_documents) else (
            official_documents[0] if official_documents else policy.policy_bucket
        )
        summary = (
            f"{policy.direction} 当前兑现链需要推进到“{checkpoint}”，"
            f"重点看 {policy.focus_sector} 是否从提法走到订单、项目或利润验证。"
        )
        next_action = (
            timeline_checkpoints[index + 1]
            if index + 1 < len(timeline_checkpoints)
            else "继续验证订单、招标、价格和利润是否形成闭环。"
        )
        events.append(
            IndustryCapitalTimelineEvent(
                id=f"{direction_id}-execution-{index + 1}",
                lane="execution",
                stage=stage,
                title=f"兑现节点 {index + 1}",
                summary=summary,
                source=source,
                signal_label="兑现观察",
                emphasis=_timeline_emphasis("兑现观察", "execution"),
                next_action=next_action,
            )
        )

    for index, item in enumerate(research_items[:4]):
        company_hint = (
            f"{item.company_code} {item.company_name or ''}".strip()
            if item.company_code or item.company_name
            else None
        )
        summary = item.note
        if company_hint:
            summary = f"{company_hint}：{summary}"
        events.append(
            IndustryCapitalTimelineEvent(
                id=item.id,
                lane="research",
                stage=_timeline_stage_label("research", item=item),
                title=item.title,
                summary=summary,
                source=item.source,
                signal_label=item.status,
                emphasis=_timeline_emphasis(item.status, "research"),
                timestamp=item.updated_at,
                next_action="继续回写更多客户、供应链和订单验证。",
            )
        )

    # Research items are the freshest catalysts; keep them ahead, then official, then execution.
    research_events = [item for item in events if item.lane == "research"]
    official_events = [item for item in events if item.lane == "official"]
    execution_events = [item for item in events if item.lane == "execution"]
    research_events.sort(key=lambda item: str(item.timestamp or ""), reverse=True)
    official_events.sort(key=lambda item: str(item.timestamp or ""), reverse=True)
    return (research_events + official_events + execution_events)[:8]


def _industry_capital_latest_catalyst(
    timeline_events: list[IndustryCapitalTimelineEvent],
    policy: PolicyWatchItem,
) -> tuple[str, str, str]:
    if timeline_events:
        preferred = next((item for item in timeline_events if item.lane in {"research", "official"}), None)
        head = preferred or timeline_events[0]
        title = head.title
        summary = head.summary or policy.summary
        stage = head.stage or policy.stage_label
        return title, summary, stage
    return (
        "等待新的方向催化",
        "当前先看官方口径、兑现节点和调研回写是否继续强化。",
        policy.stage_label,
    )


def _company_priority_label(score: float, participation_label: str, has_market_proof: bool) -> str:
    if has_market_proof and score >= 76:
        return "优先深跟"
    if score >= 68:
        return "优先跟踪"
    if participation_label in {"主线观察", "先观察"} and score >= 56:
        return "观察卡位"
    if score >= 52:
        return "保持观察"
    return "资料跟踪"


def _company_market_alignment(
    policy: PolicyWatchItem,
    company_code: str,
    matched_pick: Optional[CompositePick],
    matched_theme: Optional[ThemeStageItem],
    linked_code: Optional[str],
) -> str:
    if matched_pick is not None:
        if matched_pick.source_category == "theme-seed":
            return "主线种子共振"
        if matched_pick.horizon_label == "中期波段":
            return "资金承接验证中"
        if matched_pick.horizon_label == "连涨接力":
            return "短线强承接"
        return "策略与主线共振"
    if company_code and linked_code and company_code == linked_code:
        return "方向焦点已锁定"
    if matched_theme is not None:
        return "方向先行，等待资金扩散"
    if policy.stage_label == "承压观察":
        return "政策先行，市场待确认"
    return "等待市场确认"


def _company_next_check(
    policy: PolicyWatchItem,
    item: dict[str, str],
    matched_pick: Optional[CompositePick],
    linked_setup_label: Optional[str],
) -> str:
    if matched_pick is not None:
        if matched_pick.source_category == "theme-seed":
            return "先看是否从主线种子转入综合候选，再决定是否加深跟踪。"
        if matched_pick.horizon_label == "中期波段":
            return "优先验证量价承接、订单映射和波段延续。"
        if matched_pick.horizon_label == "连涨接力":
            return "盯住强承接、换手质量和分歧转一致。"
        return "继续跟踪策略与主线是否同步走强。"
    if linked_setup_label:
        return f"继续验证 {linked_setup_label} 是否成立，再决定是否提升优先级。"
    if policy.stage_label == "承压观察":
        return "先盯官方细则、订单和客户验证，不急着追价。"
    return str(item.get("action") or "继续跟踪兑现和承接。")


def _company_timeline_adjustment(
    *,
    item: dict[str, str],
    current_timeline_stage: str,
    latest_catalyst_title: str,
) -> tuple[float, str, Optional[str]]:
    chain_position = str(item.get("chain_position") or "")
    role = str(item.get("role") or "")
    catalyst_hint = latest_catalyst_title.strip() or None

    if current_timeline_stage in {"官方定调", "官方跟踪", "制裁升级", "反制落地"}:
        if chain_position == "上游":
            delta = 3.8
        elif chain_position == "中游":
            delta = 2.8
        else:
            delta = 1.4
        alignment = "官方定调期，先看上游卡位与中游替代"
    elif current_timeline_stage in {"采购替代", "项目落地", "行业扩散"}:
        if chain_position == "中游":
            delta = 3.6
        elif chain_position == "下游":
            delta = 2.8
        else:
            delta = 1.6
        alignment = "兑现扩散期，优先看中下游承接"
    elif current_timeline_stage in {"盈利验证", "交付验证", "调研验证"}:
        if chain_position == "下游":
            delta = 3.4
        elif chain_position == "中游":
            delta = 2.2
        else:
            delta = 1.2
        alignment = "验证期，优先看订单、交付和利润兑现"
    else:
        delta = 1.0
        alignment = "时间轴待确认，保持基础跟踪"

    if any(keyword in role for keyword in ("主轴", "龙头", "核心")):
        delta += 1.4

    if catalyst_hint:
        if any(keyword in catalyst_hint for keyword in ("制裁", "反制", "出口", "安全")) and chain_position in {"上游", "中游"}:
            delta += 1.0
            alignment = f"{alignment} / 关键环节更受催化"
        elif any(keyword in catalyst_hint for keyword in ("采购", "订单", "招标", "交付")) and chain_position in {"中游", "下游"}:
            delta += 1.0
            alignment = f"{alignment} / 兑现链条开始抬升"

    return round(delta, 2), alignment, catalyst_hint


def _build_scored_company_watchlist(
    *,
    policy: PolicyWatchItem,
    base_items: list[dict[str, str]],
    strategic_score: float,
    participation_label: str,
    linked_code: Optional[str],
    linked_setup_label: Optional[str],
    matched_theme: Optional[ThemeStageItem],
    composite_picks: list[CompositePick],
    research_signal: dict[str, object],
    current_timeline_stage: str,
    latest_catalyst_title: str,
) -> list[dict[str, object]]:
    pick_by_code: dict[str, CompositePick] = {
        item.code: item for item in composite_picks if item.code
    }
    research_companies = research_signal.get("companies", {}) if isinstance(research_signal, dict) else {}
    scored_items: list[dict[str, object]] = []
    for item in base_items:
        code = str(item.get("code") or "").strip()
        matched_pick = pick_by_code.get(code) if code else None
        role = str(item.get("role") or "")
        timeline_delta, timeline_alignment, catalyst_hint = _company_timeline_adjustment(
            item=item,
            current_timeline_stage=current_timeline_stage,
            latest_catalyst_title=latest_catalyst_title,
        )
        base_score = (
            strategic_score * 0.46
            + ((matched_pick.composite_score if matched_pick is not None else 46.0) * 0.34)
            + ((matched_theme.direction_score if matched_theme is not None else 46.0) * 0.20)
            + timeline_delta
        )
        if any(keyword in role for keyword in ("主轴", "龙头", "核心")):
            base_score += 7.0
        if code and linked_code and code == linked_code:
            base_score += 4.0
        research_company = (
            research_companies.get(code, {}) if code and isinstance(research_companies, dict) else {}
        )
        research_signal_score = round(_to_float(research_company.get("score")) or 50.0, 1)
        research_signal_label = str(research_company.get("label") or "暂无回写")
        recent_research_note = (
            str(research_company.get("note")).strip() if research_company.get("note") else None
        )
        tracking_score = round(
            _clamp(base_score + (research_signal_score - 50.0) * 0.34, 28.0, 95.0),
            1,
        )
        market_alignment = _company_market_alignment(
            policy,
            code,
            matched_pick,
            matched_theme,
            linked_code,
        )
        if research_signal_label == "验证增强":
            market_alignment = f"{market_alignment} / 调研验证增强"
        elif research_signal_label == "出现阻力":
            market_alignment = f"{market_alignment} / 调研出现阻力"
        priority_label = _company_priority_label(
            tracking_score,
            participation_label,
            has_market_proof=matched_pick is not None or (code and linked_code == code),
        )
        if research_signal_label == "验证增强" and tracking_score >= 58:
            priority_label = "优先深跟" if tracking_score >= 68 else "优先跟踪"
        elif research_signal_label == "出现阻力" and priority_label == "优先深跟":
            priority_label = "保持观察"
        next_check = _company_next_check(
            policy,
            item,
            matched_pick,
            matched_pick.horizon_label if matched_pick is not None else (linked_setup_label if code == linked_code else None),
        )
        if recent_research_note:
            next_check = (
                f"先看最近回写：{recent_research_note}"
                if research_signal_label != "出现阻力"
                else f"先拆阻力点：{recent_research_note}"
            )
        scored_items.append(
            {
                **item,
                "tracking_score": tracking_score,
                "priority_label": priority_label,
                "market_alignment": market_alignment,
                "next_check": next_check,
                "linked_setup_label": (
                    matched_pick.horizon_label
                    if matched_pick is not None
                    else (linked_setup_label if code and linked_code and code == linked_code else None)
                ),
                "linked_source": matched_pick.source_label if matched_pick is not None else None,
                "research_signal_score": research_signal_score,
                "research_signal_label": research_signal_label,
                "recent_research_note": recent_research_note,
                "timeline_alignment": timeline_alignment,
                "catalyst_hint": catalyst_hint,
            }
        )

    scored_items.sort(
        key=lambda item: (
            _to_float(item.get("tracking_score")) or 0,
            1 if str(item.get("priority_label")) == "优先深跟" else 0,
        ),
        reverse=True,
    )
    return scored_items


def _build_industry_capital_direction(
    *,
    policy: PolicyWatchItem,
    theme_stages: list[ThemeStageItem],
    composite_picks: list[CompositePick],
    official_watch: dict[str, dict],
    official_cards_map: dict[str, dict],
    official_ingest_map: dict[str, dict],
    execution_timeline: dict[str, dict],
    company_map: dict[str, dict],
) -> Optional[IndustryCapitalDirection]:
    direction_id = f"industry-capital-{policy.id}"
    matched_theme = next(
        (
            item
            for item in theme_stages
            if _match_policy_focus_sectors((policy.focus_sector,), [item.sector])
        ),
        None,
    )
    matched_pick = next(
        (
            item
            for item in composite_picks
            if _match_policy_focus_sectors(
                (policy.focus_sector,),
                [item.theme_sector or "", item.event_matched_sector or ""],
            )
            or (policy.linked_code and item.code == policy.linked_code)
        ),
        None,
    )

    demand_score = round(
        _clamp(
            policy.trend_score * 0.52
            + policy.attention_score * 0.16
            + min(len(policy.demand_drivers), 3) * 7.0
            + ((matched_theme.attention_score if matched_theme is not None else 45.0) * 0.12),
            22.0,
            92.0,
        ),
        1,
    )
    supply_signal = 6.0 if any(
        any(keyword in item for keyword in ("涨价", "供给", "供需", "产能", "替代", "脱钩", "短缺"))
        for item in (policy.transmission_paths + policy.milestones)
    ) else 0.0
    supply_score = round(
        _clamp(
            policy.policy_score * 0.48
            + min(len(policy.supply_drivers), 3) * 7.0
            + supply_signal
            + ((matched_theme.policy_event_score if matched_theme is not None else 45.0) * 0.14),
            22.0,
            92.0,
        ),
        1,
    )
    capital_preference_score = round(
        _clamp(
            policy.capital_preference_score * 0.44
            + ((matched_theme.capital_preference_score if matched_theme is not None else 45.0) * 0.30)
            + ((matched_pick.capital_score if matched_pick is not None else 45.0) * 0.26),
            20.0,
            92.0,
        ),
        1,
    )
    strategic_score = round(
        _clamp(
            policy.direction_score * 0.34
            + demand_score * 0.18
            + supply_score * 0.16
            + capital_preference_score * 0.18
            + ((matched_theme.direction_score if matched_theme is not None else 46.0) * 0.14),
            22.0,
            94.0,
        ),
        1,
    )

    strategic_label = _industry_capital_label(
        strategic_score,
        policy.stage_label,
        matched_theme.participation_label if matched_theme is not None else policy.participation_label,
    )
    participation_label = matched_theme.participation_label if matched_theme is not None else policy.participation_label
    business_horizon = _industry_business_horizon(policy.industry_phase, policy.stage_label)
    capital_horizon = _industry_capital_horizon(participation_label)
    linked_signal_id = (
        (matched_pick.signal_id if matched_pick is not None else None)
        or policy.linked_signal_id
        or (matched_theme.linked_signal_id if matched_theme is not None else None)
    )
    linked_code = (
        (matched_pick.code if matched_pick is not None else None)
        or policy.linked_code
        or (matched_theme.linked_code if matched_theme is not None else None)
    )
    linked_name = (
        (matched_pick.name if matched_pick is not None else None)
        or policy.linked_name
        or (matched_theme.linked_name if matched_theme is not None else None)
    )
    linked_setup_label = (
        (matched_pick.horizon_label if matched_pick is not None else None)
        or policy.linked_setup_label
        or (matched_theme.linked_setup_label if matched_theme is not None else None)
    )
    summary = (
        f"{policy.direction} 当前更适合按 {strategic_label} 来看：大方向落在 {policy.focus_sector}，"
        f"产业阶段是 {policy.industry_phase}，资本参与更像 {participation_label}。"
    )
    business_action = _industry_business_action(
        policy.direction,
        policy.industry_phase,
        policy.stage_label,
        policy.focus_sector,
        policy.upstream,
        policy.midstream,
        policy.downstream,
    )
    capital_action = _industry_capital_action(
        participation_label,
        linked_code,
        linked_name,
        policy.focus_sector,
    )
    official_entry = official_watch.get(_policy_direction_key(policy), {})
    official_cards_entry = official_cards_map.get(_policy_direction_key(policy), {})
    official_ingest_entry = official_ingest_map.get(_policy_direction_key(policy), {})
    timeline_entry = execution_timeline.get(_policy_direction_key(policy), {})
    company_entry = company_map.get(_policy_direction_key(policy), {})
    research_signal = _build_industry_capital_research_signal(direction_id)
    research_items = _list_industry_capital_research_items(direction_id, limit=6)
    research_signal_score = _to_float(research_signal.get("score")) or 50.0
    research_signal_label = str(research_signal.get("label") or "暂无回写")
    official_sources = [
        str(item)
        for item in official_entry.get("official_sources", _default_official_sources(policy))
        if str(item).strip()
    ]
    official_watchpoints = [
        str(item)
        for item in official_entry.get("official_watchpoints", _default_official_watchpoints(policy))
        if str(item).strip()
    ]
    business_checklist = [
        str(item)
        for item in official_entry.get("business_checklist", _default_business_checklist(policy))
        if str(item).strip()
    ]
    capital_checklist = [
        str(item)
        for item in official_entry.get("capital_checklist", _default_capital_checklist(policy))
        if str(item).strip()
    ]
    official_cards = _normalize_official_cards(
        official_cards_entry.get(
            "official_cards",
            _default_official_cards(
                policy,
                official_sources,
                official_documents=[
                    str(item)
                    for item in timeline_entry.get(
                        "official_documents",
                        _default_official_documents(policy),
                    )
                    if str(item).strip()
                ],
                official_watchpoints=official_watchpoints,
                timeline_checkpoints=[
                    str(item)
                    for item in timeline_entry.get(
                        "timeline_checkpoints",
                        _default_timeline_checkpoints(policy),
                    )
                    if str(item).strip()
                ],
            ),
        )
    )
    official_documents = [
        str(item)
        for item in timeline_entry.get("official_documents", _default_official_documents(policy))
        if str(item).strip()
    ]
    official_source_entries = _normalize_official_source_entries(
        official_ingest_entry.get(
            "official_source_entries",
            _default_official_source_entries(
                policy,
                official_sources=official_sources,
                official_documents=official_documents,
                official_watchpoints=official_watchpoints,
                official_cards=official_cards,
            ),
        )
    )
    official_freshness_score, official_freshness_label = _industry_official_freshness(
        official_source_entries
    )
    priority_score = _industry_capital_priority_score(
        strategic_score,
        research_signal_score,
        participation_label,
        policy.stage_label,
        official_freshness_score,
    )
    timeline_checkpoints = [
        str(item)
        for item in timeline_entry.get("timeline_checkpoints", _default_timeline_checkpoints(policy))
        if str(item).strip()
    ]
    cooperation_targets = [
        str(item)
        for item in timeline_entry.get("cooperation_targets", _default_cooperation_targets(policy))
        if str(item).strip()
    ]
    cooperation_modes = [
        str(item)
        for item in timeline_entry.get("cooperation_modes", _default_cooperation_modes(policy))
        if str(item).strip()
    ]
    research_targets = [
        str(item)
        for item in company_entry.get("research_targets", _default_research_targets(policy))
        if str(item).strip()
    ]
    validation_signals = [
        str(item)
        for item in company_entry.get("validation_signals", _default_validation_signals(policy))
        if str(item).strip()
    ]
    timeline_events = _build_industry_capital_timeline_events(
        direction_id=direction_id,
        policy=policy,
        official_source_entries=official_source_entries,
        official_cards=official_cards,
        official_documents=official_documents,
        timeline_checkpoints=timeline_checkpoints,
        research_items=research_items,
    )
    latest_catalyst_title, latest_catalyst_summary, current_timeline_stage = _industry_capital_latest_catalyst(
        timeline_events,
        policy,
    )
    company_watchlist = _build_scored_company_watchlist(
        policy=policy,
        base_items=_normalize_company_watchlist(
            company_entry.get("company_watchlist", _default_company_watchlist(policy))
        ),
        strategic_score=strategic_score,
        participation_label=participation_label,
        linked_code=linked_code,
        linked_setup_label=linked_setup_label,
        matched_theme=matched_theme,
        composite_picks=composite_picks,
        research_signal=research_signal,
        current_timeline_stage=current_timeline_stage,
        latest_catalyst_title=latest_catalyst_title,
    )
    opportunities: list[str] = []
    if policy.upstream:
        opportunities.append(f"上游先看 {'、'.join(policy.upstream[:2])}")
    if policy.midstream:
        opportunities.append(f"中游能力环节 {'、'.join(policy.midstream[:2])}")
    if policy.downstream:
        opportunities.append(f"下游兑现环节 {'、'.join(policy.downstream[:2])}")
    if linked_code and linked_name:
        opportunities.append(f"交易焦点 {linked_code} {linked_name}")
    if policy.milestones:
        opportunities.append(f"兑现链 {' -> '.join(policy.milestones[:3])}")

    drivers = [
        f"优先级 {priority_score:.1f}",
        f"战略分 {strategic_score:.1f}",
        f"需求分 {demand_score:.1f}",
        f"供给分 {supply_score:.1f}",
        f"资金偏好 {capital_preference_score:.1f}",
        f"官方新鲜度 {official_freshness_label} / {official_freshness_score:.1f}",
    ]
    if research_signal_label != "暂无回写":
        drivers.append(f"调研信号 {research_signal_label} / {research_signal_score:.1f}")
    if matched_theme is not None:
        drivers.append(f"主线阶段 {matched_theme.stage_label} / {matched_theme.participation_label}")
    if matched_pick is not None:
        drivers.append(f"综合候选 {matched_pick.code} / {matched_pick.horizon_label}")

    return IndustryCapitalDirection(
        id=direction_id,
        direction=policy.direction,
        policy_bucket=policy.policy_bucket,
        focus_sector=policy.focus_sector,
        strategic_label=strategic_label,
        industry_phase=policy.industry_phase,
        participation_label=participation_label,
        business_horizon=business_horizon,
        capital_horizon=capital_horizon,
        priority_score=priority_score,
        strategic_score=strategic_score,
        policy_score=policy.policy_score,
        demand_score=demand_score,
        supply_score=supply_score,
        capital_preference_score=capital_preference_score,
        research_signal_score=research_signal_score,
        research_signal_label=research_signal_label,
        official_freshness_score=official_freshness_score,
        official_freshness_label=official_freshness_label,
        linked_signal_id=linked_signal_id,
        linked_code=linked_code,
        linked_name=linked_name,
        linked_setup_label=linked_setup_label,
        summary=summary,
        business_action=business_action,
        capital_action=capital_action,
        risk_note=policy.risk_note,
        research_summary=str(research_signal.get("summary") or "当前还没有调研回写，先补客户、供应链和政策验证。"),
        research_next_action=str(research_signal.get("next_action") or "先补第一次方向调研记录。"),
        upstream=policy.upstream[:3],
        midstream=policy.midstream[:3],
        downstream=policy.downstream[:3],
        demand_drivers=policy.demand_drivers[:3],
        supply_drivers=policy.supply_drivers[:3],
        milestones=policy.milestones[:5],
        transmission_paths=policy.transmission_paths[:3],
        opportunities=opportunities[:5],
        official_sources=official_sources[:4],
        official_watchpoints=official_watchpoints[:4],
        business_checklist=business_checklist[:4],
        capital_checklist=capital_checklist[:4],
        official_cards=official_cards[:3],
        official_source_entries=[
            IndustryCapitalOfficialSourceEntry(**item) for item in official_source_entries[:3]
        ],
        official_documents=official_documents[:4],
        timeline_checkpoints=timeline_checkpoints[:5],
        current_timeline_stage=current_timeline_stage,
        latest_catalyst_title=latest_catalyst_title,
        latest_catalyst_summary=latest_catalyst_summary,
        timeline_events=timeline_events,
        cooperation_targets=cooperation_targets[:4],
        cooperation_modes=cooperation_modes[:4],
        company_watchlist=company_watchlist[:4],
        research_targets=research_targets[:4],
        validation_signals=validation_signals[:4],
        drivers=drivers[:6],
    )


def _build_industry_capital_map(limit: int = 3) -> list[IndustryCapitalDirection]:
    def builder() -> list[IndustryCapitalDirection]:
        policy_watch = _build_policy_watch(limit=max(limit + 3, 6))
        theme_stages = _build_theme_stage_engine(limit=max(limit + 3, 6))
        composite_picks = _build_composite_picks(days=1, limit=16)
        official_watch = _load_policy_official_watch()
        official_cards_map = _load_policy_official_cards()
        official_ingest_map = _load_policy_official_ingest()
        execution_timeline = _load_policy_execution_timeline()
        company_map = _load_industry_capital_company_map()

        items: list[IndustryCapitalDirection] = []
        for policy in policy_watch:
            item = _build_industry_capital_direction(
                policy=policy,
                theme_stages=theme_stages,
                composite_picks=composite_picks,
                official_watch=official_watch,
                official_cards_map=official_cards_map,
                official_ingest_map=official_ingest_map,
                execution_timeline=execution_timeline,
                company_map=company_map,
            )
            if item is not None:
                items.append(item)

        items.sort(
            key=lambda item: (
                item.priority_score,
                item.strategic_score,
                item.policy_score,
                item.capital_preference_score,
                item.demand_score,
            ),
            reverse=True,
        )
        return items[:limit]

    return _cached_runtime_value(
        "industry_capital_map",
        limit,
        ttl_seconds=15,
        dependency_paths=_runtime_cache_paths(
            _POLICY_OFFICIAL_WATCH,
            _POLICY_OFFICIAL_CARDS,
            _POLICY_EXECUTION_TIMELINE,
            _INDUSTRY_CAPITAL_COMPANY_MAP,
            _INDUSTRY_CAPITAL_RESEARCH_LOG,
            _NEWS_DIGEST,
            _POLICY_DIRECTION_CATALOG,
            _SECTOR_ALERTS,
            _APP_MESSAGE_CENTER,
            _SIGNAL_TRACKER,
            *_db_dependency_paths(),
        ),
        builder=builder,
    )


def _build_industry_capital_detail(direction_id: str) -> IndustryCapitalDirection:
    direction_key = str(direction_id or "").strip()
    if not direction_key:
        raise HTTPException(status_code=400, detail="缺少产业资本方向 ID")

    def builder() -> IndustryCapitalDirection:
        for item in _build_industry_capital_map(limit=24):
            if item.id == direction_key:
                return item
        raise HTTPException(status_code=404, detail="未找到对应的产业资本方向")

    return _cached_runtime_value(
        "industry_capital_detail",
        direction_key,
        ttl_seconds=15,
        dependency_paths=_runtime_cache_paths(
            _POLICY_OFFICIAL_WATCH,
            _POLICY_OFFICIAL_CARDS,
            _POLICY_EXECUTION_TIMELINE,
            _INDUSTRY_CAPITAL_COMPANY_MAP,
            _INDUSTRY_CAPITAL_RESEARCH_LOG,
            _NEWS_DIGEST,
            _POLICY_DIRECTION_CATALOG,
            _SECTOR_ALERTS,
            _APP_MESSAGE_CENTER,
            _SIGNAL_TRACKER,
            *_db_dependency_paths(),
        ),
        builder=builder,
    )


def _industry_capital_route(item: IndustryCapitalDirection) -> str:
    return f"/industry-capital/{item.id}"


def _industry_capital_level(item: IndustryCapitalDirection) -> str:
    if item.research_signal_label == "出现阻力":
        return "warning"
    if item.strategic_label == "逆风跟踪":
        return "warning"
    if item.participation_label in {"中期波段", "连涨接力"}:
        return "info"
    return "info"


def _build_industry_capital_focus_message() -> Optional[dict]:
    items = _build_industry_capital_map(limit=3)
    if not items:
        return None

    focus = items[0]
    body = (
        f"{focus.direction} / {focus.focus_sector} / {focus.strategic_label} / 事业{focus.business_horizon}"
        f" / 资本{focus.capital_horizon} / 优先级{focus.priority_score:.1f} / 阶段{focus.current_timeline_stage}。{focus.summary}"
        f" 最新催化：{focus.latest_catalyst_title}。{focus.latest_catalyst_summary}"
        f" 调研信号：{focus.research_summary}"
        "。下一步：先看方向深页，确认官方观察点、兑现时间轴、调研回写和合作对象。"
    )
    title = f"产业资本方向 {focus.direction}"
    if focus.research_signal_label in {"验证增强", "出现阻力"}:
        title = f"产业资本方向 {focus.direction} {focus.research_signal_label}"
    return _normalize_app_message(
        {
            "id": f"msg_industry_capital_{focus.id}",
            "title": title,
            "body": body,
            "preview": body[:140],
            "level": _industry_capital_level(focus),
            "channel": "system_focus",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "route": _industry_capital_route(focus),
        }
    )


def _theme_stage_label(stage_score: float) -> str:
    if stage_score < 45:
        return "早期孵化"
    if stage_score < 62:
        return "中期扩散"
    if stage_score < 78:
        return "主升波段"
    return "高位分歧"


def _theme_participation_label(
    stage_score: float,
    top_pick: CompositePick | None,
    strongest_move: StrongMoveCandidate | None,
) -> str:
    if strongest_move and strongest_move.setup_label == "连涨候选":
        return "连涨接力"
    if top_pick and top_pick.horizon_label == "中期波段":
        return "中期波段"
    if stage_score >= 80:
        return "后排回避"
    if stage_score >= 58:
        return "中期波段"
    return "主线观察"


def _build_theme_stage_item(
    *,
    theme: ThemeRadarItem,
    composite_picks: list[CompositePick],
    policy_watch: list[PolicyWatchItem],
    strong_move_map: dict[str, StrongMoveCandidate],
) -> Optional[ThemeStageItem]:
    normalized_theme = _normalize_theme_key(theme.sector)
    related_picks = [
        pick
        for pick in composite_picks
        if _normalize_theme_key(pick.theme_sector) == normalized_theme
        or _normalize_theme_key(pick.event_matched_sector) == normalized_theme
    ]
    top_pick = related_picks[0] if related_picks else None

    strongest_move: StrongMoveCandidate | None = None
    if top_pick is not None:
        strongest_move = strong_move_map.get(top_pick.code)
    if strongest_move is None and theme.linked_code:
        strongest_move = strong_move_map.get(theme.linked_code)
    if strongest_move is None:
        strongest_move = next(
            (strong_move_map.get(follower.code) for follower in theme.followers if follower.code in strong_move_map),
            None,
        )

    top_pick_sectors = []
    if top_pick is not None:
        top_pick_sectors = [top_pick.theme_sector or "", top_pick.event_matched_sector or ""]
    matched_policy = next(
        (
            item
            for item in policy_watch
            if _match_policy_focus_sectors((item.focus_sector,), [theme.sector])
            or _match_policy_focus_sectors((item.focus_sector,), top_pick_sectors)
        ),
        None,
    )

    policy_event_score = (
        top_pick.event_score
        if top_pick is not None
        else min(max(48.0 + theme.score * 0.08, 35.0), 78.0)
    )
    if matched_policy is not None:
        policy_event_score = round(policy_event_score * 0.62 + matched_policy.policy_score * 0.38, 1)
    attention_score = round(
        _clamp(
            theme.score * 0.72
            + min(len(theme.followers), 3) * 6.0
            + (6.0 if theme.message_hint else 0.0)
            + (8.0 if theme.intensity == "高热主线" else 4.0 if theme.intensity == "持续升温" else 0.0),
            25.0,
            92.0,
        ),
        1,
    )
    capital_score = round(
        _clamp(
            (top_pick.capital_score if top_pick is not None else 42.0) * 0.62
            + (strongest_move.continuation_score if strongest_move is not None else 45.0) * 0.38
            + (4.0 if any("资金" in follower.label for follower in theme.followers) else 0.0),
            20.0,
            95.0,
        ),
        1,
    )
    trend_score = round(
        _clamp(
            (strongest_move.swing_score if strongest_move is not None else 42.0) * 0.54
            + min(max(theme.change_pct * 18.0, 0.0), 35.0) * 0.26
            + (top_pick.execution_score if top_pick is not None else 48.0) * 0.20,
            20.0,
            95.0,
        ),
        1,
    )

    raw_stage = 38.0
    if top_pick is not None and top_pick.source_category == "theme_seed":
        raw_stage += 6.0
    if strongest_move is not None:
        if strongest_move.setup_label == "波段候选":
            raw_stage += 28.0
        elif strongest_move.setup_label == "连涨候选":
            raw_stage += 38.0
    if theme.intensity == "高热主线":
        raw_stage += 16.0
    elif theme.intensity == "持续升温":
        raw_stage += 8.0
    if top_pick is not None and top_pick.horizon_label == "中期波段":
        raw_stage += 12.0
    if top_pick is not None and top_pick.horizon_label == "连涨接力":
        raw_stage += 18.0
    if top_pick is not None and top_pick.event_bias == "偏空":
        raw_stage -= 8.0
    if matched_policy is not None:
        if matched_policy.stage_label == "兑现扩散":
            raw_stage += 8.0
        elif matched_policy.stage_label == "催化升温":
            raw_stage += 4.0
        elif matched_policy.stage_label == "承压观察":
            raw_stage -= 6.0
    stage_score = round(_clamp(raw_stage, 25.0, 92.0), 1)

    stage_label = _theme_stage_label(stage_score)
    participation_label = _theme_participation_label(stage_score, top_pick, strongest_move)
    direction_score = round(
        (
            policy_event_score * 0.22
            + trend_score * 0.24
            + attention_score * 0.18
            + capital_score * 0.24
            + stage_score * 0.12
        ),
        1,
    )

    focus_code = (
        (top_pick.code if top_pick is not None else None)
        or theme.linked_code
        or (theme.followers[0].code if theme.followers else None)
    )
    focus_name = (
        (top_pick.name if top_pick is not None else None)
        or theme.linked_name
        or (theme.followers[0].name if theme.followers else None)
    )
    focus_signal_id = (top_pick.signal_id if top_pick is not None else None) or theme.linked_signal_id
    focus_setup = (
        (top_pick.horizon_label if top_pick is not None else None)
        or theme.linked_setup_label
        or (strongest_move.setup_label if strongest_move is not None else None)
    )

    drivers: list[str] = [
        f"政策/事件代理分 {policy_event_score:.1f}",
        f"趋势分 {trend_score:.1f}",
        f"关注度分 {attention_score:.1f}",
        f"资金偏好分 {capital_score:.1f}",
        f"阶段分 {stage_score:.1f}",
    ]
    if matched_policy is not None:
        drivers.append(f"政策方向 {matched_policy.direction} / {matched_policy.industry_phase}")
    if theme.message_hint:
        drivers.append("微信镜像里已经出现这条线")
    if strongest_move is not None:
        drivers.append(f"当前最强跟随票形态是 {strongest_move.setup_label}")

    summary = (
        f"{theme.sector} 当前更像 {stage_label}，适合按 {participation_label} 看待。"
        f" 方向分 {direction_score:.1f}，先看 {focus_code or '主线核心票'} 是否继续证明这条线。"
    )
    action = (
        f"先盯 {focus_code or '前排核心票'} {focus_name or ''}，"
        f"按 {participation_label} 的节奏处理，不要把后排补涨票当成主线本体。"
    ).strip()

    return ThemeStageItem(
        id=f"theme-stage-{theme.id}",
        sector=theme.sector,
        theme_type=theme.theme_type,
        intensity=theme.intensity,
        stage_label=stage_label,
        participation_label=participation_label,
        direction_score=direction_score,
        policy_event_score=round(policy_event_score, 1),
        trend_score=trend_score,
        attention_score=attention_score,
        capital_preference_score=capital_score,
        stage_score=stage_score,
        linked_signal_id=focus_signal_id,
        linked_code=focus_code,
        linked_name=focus_name,
        linked_setup_label=focus_setup,
        summary=summary,
        action=action,
        risk_note=theme.risk_note,
        drivers=drivers[:6],
    )


def _build_theme_stage_engine(limit: int = 3) -> list[ThemeStageItem]:
    def builder() -> list[ThemeStageItem]:
        theme_radar = _build_theme_radar(limit=max(limit + 2, 6))
        composite_picks = _build_composite_picks(days=1, limit=12)
        strong_moves = _build_strong_moves(days=1, limit=12)
        policy_watch = _build_policy_watch(limit=8)
        strong_move_map = {item.code: item for item in strong_moves}

        items: list[ThemeStageItem] = []
        for theme in theme_radar:
            item = _build_theme_stage_item(
                theme=theme,
                composite_picks=composite_picks,
                policy_watch=policy_watch,
                strong_move_map=strong_move_map,
            )
            if item is not None:
                items.append(item)

        items.sort(key=lambda item: (item.direction_score, item.trend_score, item.capital_preference_score), reverse=True)
        return items[:limit]

    return _cached_runtime_value(
        "theme_stage",
        limit,
        ttl_seconds=12,
        dependency_paths=_runtime_cache_paths(
            _NEWS_DIGEST,
            _POLICY_DIRECTION_CATALOG,
            _SECTOR_ALERTS,
            _APP_MESSAGE_CENTER,
            _SIGNAL_TRACKER,
            *_db_dependency_paths(),
        ),
        builder=builder,
    )


def _build_composite_picks_for_window(days: int = 1, limit: int = 5) -> list[CompositePick]:
    strategy_map = {item.name: item for item in _build_strategies()}
    strong_moves = _build_strong_moves(days=days, limit=max(limit * 3, 10))
    strong_move_map = {item.code: item for item in strong_moves}
    theme_radar = _build_theme_radar(limit=8)
    theme_by_code: dict[str, ThemeRadarItem] = {}

    for item in theme_radar:
        for follower in item.followers:
            theme_by_code[follower.code] = item
        if item.linked_code:
            theme_by_code[item.linked_code] = item

    signal_records = _load_signal_records(days=days)
    seed_codes = {
        str(item.get("code", "")).strip()
        for item in signal_records
        if str(item.get("code", "")).strip()
    }
    signal_records.extend(
        _build_theme_seed_signal_records(
            theme_radar,
            strong_move_map,
            existing_codes=seed_codes,
        )
    )

    picks: list[CompositePick] = []
    for signal in signal_records:
        composite_pick = _build_composite_pick_from_record(
            signal,
            strategy_map=strategy_map,
            strong_move_map=strong_move_map,
            theme_by_code=theme_by_code,
        )
        if composite_pick is not None:
            picks.append(composite_pick)

    picks.sort(
        key=lambda item: (
            item.composite_score,
            item.theme_score,
            item.capital_score,
            item.strategy_score,
        ),
        reverse=True,
    )
    return picks[:limit]


def _build_composite_picks(days: int = 1, limit: int = 5) -> list[CompositePick]:
    def builder() -> list[CompositePick]:
        picks = _build_composite_picks_for_window(days=days, limit=limit)
        if picks or days > 1:
            return picks

        fallback_days = 5
        return _build_composite_picks_for_window(days=fallback_days, limit=limit)

    return _cached_runtime_value(
        "composite_picks",
        (days, limit),
        ttl_seconds=10,
        dependency_paths=_runtime_cache_paths(
            _NEWS_DIGEST,
            _SECTOR_ALERTS,
            _APP_MESSAGE_CENTER,
            _SIGNAL_TRACKER,
            _STRATEGIES_JSON,
            _AGENT_MEMORY,
            *_db_dependency_paths(),
        ),
        builder=builder,
    )


def _replay_review_label(t1_return: Optional[float], t3_return: Optional[float], t5_return: Optional[float]) -> str:
    if t3_return is not None:
        return "验证通过" if t3_return > 0 else "验证走弱"
    if t1_return is not None:
        return "短线承接" if t1_return > 0 else "短线走弱"
    if t5_return is not None:
        return "波段兑现" if t5_return > 0 else "波段失效"
    return "待观察"


def _replay_outcome_summary(
    trade_date: str,
    t1_return: Optional[float],
    t3_return: Optional[float],
    t5_return: Optional[float],
) -> str:
    parts = [trade_date]
    if t1_return is not None:
        parts.append(f"T+1 {t1_return:+.2f}%")
    if t3_return is not None:
        parts.append(f"T+3 {t3_return:+.2f}%")
    if t5_return is not None:
        parts.append(f"T+5 {t5_return:+.2f}%")
    if len(parts) == 1:
        parts.append("还没到验证窗口")
    return " / ".join(parts)


def _build_composite_replay(days: int = 5, per_day: int = 1) -> list[CompositeReplayItem]:
    lookback_days = max(days + 5, 10)
    strategy_map = {item.name: item for item in _build_strategies()}
    verification_map = _load_signal_verification_records(days=max(days + 10, 20))
    signal_records = _load_live_signal_records(days=lookback_days)

    records_by_day: dict[str, list[dict]] = {}
    for signal in signal_records:
        trade_day = _signal_trade_day(signal)
        if not trade_day:
            continue
        records_by_day.setdefault(trade_day, []).append(signal)

    replay_items: list[CompositeReplayItem] = []
    sorted_days = sorted(records_by_day.keys(), reverse=True)[:days]
    for trade_day in sorted_days:
        day_records = records_by_day.get(trade_day, [])
        strong_candidates: list[StrongMoveCandidate] = []
        for record in day_records:
            candidate = _build_strong_move_candidate_from_record(record, strategy_map=strategy_map)
            if candidate is not None:
                strong_candidates.append(candidate)
        strong_candidates.sort(
            key=lambda item: (item.composite_score, item.continuation_score, item.swing_score),
            reverse=True,
        )
        strong_move_map = {item.code: item for item in strong_candidates}

        day_picks: list[CompositePick] = []
        for record in day_records:
            pick = _build_composite_pick_from_record(
                record,
                strategy_map=strategy_map,
                strong_move_map=strong_move_map,
                theme_by_code={},
            )
            if pick is not None:
                day_picks.append(pick)

        day_picks.sort(
            key=lambda item: (
                item.composite_score,
                item.theme_score,
                item.capital_score,
                item.strategy_score,
            ),
            reverse=True,
        )

        for pick in day_picks[:per_day]:
            verify_key = f"{trade_day}|{pick.strategy}|{pick.code}"
            verify_record = verification_map.get(verify_key, {})
            verify_box = verify_record.get("verify", {}) if isinstance(verify_record, dict) else {}
            t1_box = verify_box.get("t1", {}) if isinstance(verify_box, dict) else {}
            t3_box = verify_box.get("t3", {}) if isinstance(verify_box, dict) else {}
            t5_box = verify_box.get("t5", {}) if isinstance(verify_box, dict) else {}

            t1_return = _to_float(t1_box.get("return_pct")) if isinstance(t1_box, dict) else None
            t3_return = _to_float(t3_box.get("return_pct")) if isinstance(t3_box, dict) else None
            t5_return = _to_float(t5_box.get("return_pct")) if isinstance(t5_box, dict) else None
            verified_days = sum(
                1 for value in (t1_return, t3_return, t5_return) if value is not None
            )
            review_label = _replay_review_label(t1_return, t3_return, t5_return)
            review = (
                f"{pick.code} {pick.name} 当天以 {pick.setup_label} 入榜。"
                f" 后续结果是 {_replay_outcome_summary(trade_day, t1_return, t3_return, t5_return)}。"
            )
            if t3_return is not None and t3_return > 0:
                review += " 这说明它至少在 3 日窗口里没有掉链子。"
            elif t1_return is not None and t1_return <= 0:
                review += " 这说明它虽然当时看起来不错，但隔天承接不够硬。"
            elif verified_days == 0:
                review += " 目前还在观察窗口里，先别急着下结论。"

            replay_items.append(
                CompositeReplayItem(
                    id=f"replay-{trade_day}-{pick.code}",
                    trade_date=trade_day,
                    signal_id=pick.signal_id,
                    code=pick.code,
                    name=pick.name,
                    strategy=pick.strategy,
                    setup_label=pick.setup_label,
                    conviction=pick.conviction,
                    composite_score=pick.composite_score,
                    first_position_pct=pick.first_position_pct,
                    theme_sector=pick.theme_sector,
                    review_label=review_label,
                    verified_days=verified_days,
                    t1_return_pct=t1_return,
                    t3_return_pct=t3_return,
                    t5_return_pct=t5_return,
                    outcome_summary=_replay_outcome_summary(trade_day, t1_return, t3_return, t5_return),
                    review=review,
                )
            )

    replay_items.sort(
        key=lambda item: (item.trade_date, item.composite_score),
        reverse=True,
    )
    return replay_items


def _verification_returns(
    verification_map: dict[str, dict],
    trade_day: str,
    strategy: str,
    code: str,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    verify_key = f"{trade_day}|{strategy}|{code}"
    verify_record = verification_map.get(verify_key, {})
    verify_box = verify_record.get("verify", {}) if isinstance(verify_record, dict) else {}
    t1_box = verify_box.get("t1", {}) if isinstance(verify_box, dict) else {}
    t3_box = verify_box.get("t3", {}) if isinstance(verify_box, dict) else {}
    t5_box = verify_box.get("t5", {}) if isinstance(verify_box, dict) else {}
    t1_return = _to_float(t1_box.get("return_pct")) if isinstance(t1_box, dict) else None
    t3_return = _to_float(t3_box.get("return_pct")) if isinstance(t3_box, dict) else None
    t5_return = _to_float(t5_box.get("return_pct")) if isinstance(t5_box, dict) else None
    return t1_return, t3_return, t5_return


def _average_pct(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def _win_rate_pct(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(1 for value in values if value > 0) * 100 / len(values), 1)


def _build_compare_summary(
    label: str,
    rows: list[RecommendationCompareDay],
    *,
    side: str,
) -> RecommendationCompareSummary:
    t1_values = [
        value
        for value in [
            getattr(item, f"{side}_t1_return_pct")
            for item in rows
        ]
        if value is not None
    ]
    t3_values = [
        value
        for value in [
            getattr(item, f"{side}_t3_return_pct")
            for item in rows
        ]
        if value is not None
    ]
    t5_values = [
        value
        for value in [
            getattr(item, f"{side}_t5_return_pct")
            for item in rows
        ]
        if value is not None
    ]
    return RecommendationCompareSummary(
        label=label,
        sample_days=len(rows),
        observed_t1_days=len(t1_values),
        observed_t3_days=len(t3_values),
        observed_t5_days=len(t5_values),
        avg_t1_return_pct=_average_pct(t1_values),
        avg_t3_return_pct=_average_pct(t3_values),
        avg_t5_return_pct=_average_pct(t5_values),
        t1_win_rate=_win_rate_pct(t1_values),
        t3_win_rate=_win_rate_pct(t3_values),
        t5_win_rate=_win_rate_pct(t5_values),
    )


def _compare_winner_label(
    composite_t1: Optional[float],
    composite_t3: Optional[float],
    composite_t5: Optional[float],
    baseline_t1: Optional[float],
    baseline_t3: Optional[float],
    baseline_t5: Optional[float],
) -> tuple[str, str]:
    if composite_t3 is not None and baseline_t3 is not None:
        diff = composite_t3 - baseline_t3
        if diff > 0.5:
            return "综合领先", f"T+3 领先 {diff:.2f}%"
        if diff < -0.5:
            return "原推荐领先", f"T+3 落后 {abs(diff):.2f}%"
        return "表现接近", "T+3 表现接近"
    if composite_t1 is not None and baseline_t1 is not None:
        diff = composite_t1 - baseline_t1
        if diff > 0.5:
            return "综合领先", f"T+1 领先 {diff:.2f}%"
        if diff < -0.5:
            return "原推荐领先", f"T+1 落后 {abs(diff):.2f}%"
        return "表现接近", "T+1 表现接近"
    if composite_t5 is not None and baseline_t5 is not None:
        diff = composite_t5 - baseline_t5
        if diff > 0.5:
            return "综合领先", f"T+5 领先 {diff:.2f}%"
        if diff < -0.5:
            return "原推荐领先", f"T+5 落后 {abs(diff):.2f}%"
        return "表现接近", "T+5 表现接近"
    return "仍在观察", "还在观察窗口里，先不下结论"


def _build_compare_readiness(
    composite_summary: RecommendationCompareSummary,
    baseline_summary: RecommendationCompareSummary,
) -> RecommendationTakeoverReadiness:
    t1_win_diff = None
    if composite_summary.t1_win_rate is not None and baseline_summary.t1_win_rate is not None:
        t1_win_diff = composite_summary.t1_win_rate - baseline_summary.t1_win_rate

    t3_return_diff = None
    if (
        composite_summary.avg_t3_return_pct is not None
        and baseline_summary.avg_t3_return_pct is not None
    ):
        t3_return_diff = composite_summary.avg_t3_return_pct - baseline_summary.avg_t3_return_pct

    conditions = [
        f"影子观察天数 {composite_summary.sample_days}",
        f"T+1 已验证 {composite_summary.observed_t1_days} 天",
        f"T+3 已验证 {composite_summary.observed_t3_days} 天",
    ]
    if t1_win_diff is not None:
        conditions.append(f"T+1 胜率差 {t1_win_diff:+.1f}pct")
    if t3_return_diff is not None:
        conditions.append(f"T+3 收益差 {t3_return_diff:+.2f}%")

    if composite_summary.sample_days < 5 or composite_summary.observed_t1_days < 3:
        confidence = min(58.0, 32.0 + composite_summary.sample_days * 4 + composite_summary.observed_t1_days * 6)
        return RecommendationTakeoverReadiness(
            status="shadow",
            label="继续影子",
            confidence_score=round(confidence, 1),
            summary="样本还不够厚，先继续并行观察，不急着让综合榜接管主排序。",
            recommended_action="继续累积 T+1/T+3 样本，先看它能不能稳定跑出差异。",
            conditions=conditions,
        )

    if composite_summary.observed_t3_days < 2:
        confidence = min(64.0, 48.0 + composite_summary.observed_t1_days * 3)
        return RecommendationTakeoverReadiness(
            status="shadow",
            label="继续影子",
            confidence_score=round(confidence, 1),
            summary="T+1 已经开始形成样本，但 T+3 持续性样本还不够，不适合直接接管。",
            recommended_action="继续观察主线延续和回撤表现，重点看 T+3 而不是只盯隔日。",
            conditions=conditions,
        )

    if (
        t3_return_diff is not None
        and t3_return_diff >= 1.2
        and (t1_win_diff is None or t1_win_diff >= 6)
        and composite_summary.sample_days >= 8
        and composite_summary.observed_t3_days >= 3
    ):
        return RecommendationTakeoverReadiness(
            status="ready",
            label="可接管主排序",
            confidence_score=82.0,
            summary="综合榜在持续性和隔日承接上都已经拉开差距，可以考虑接管主排序。",
            recommended_action="先把综合榜接管推荐页排序，再保留原推荐做旁路观察。",
            conditions=conditions,
        )

    if (
        t3_return_diff is not None
        and t3_return_diff >= 0.6
        and (t1_win_diff is None or t1_win_diff >= 3)
        and composite_summary.observed_t3_days >= 2
    ):
        return RecommendationTakeoverReadiness(
            status="pilot",
            label="可局部接管",
            confidence_score=71.0,
            summary="综合榜已经表现出领先迹象，但样本还不算特别厚，更适合先局部接管。",
            recommended_action="先让综合榜接管首屏焦点推荐，原推荐榜继续保留二级队列。",
            conditions=conditions,
        )

    if (
        (t3_return_diff is not None and t3_return_diff <= -0.5)
        or (t1_win_diff is not None and t1_win_diff <= -5)
    ):
        return RecommendationTakeoverReadiness(
            status="hold",
            label="暂缓接管",
            confidence_score=38.0,
            summary="综合榜目前没有跑赢原推荐，接管会放大错误，不值得冒这个险。",
            recommended_action="继续影子观察，同时修正事件权重、主题映射和执行打分。",
            conditions=conditions,
        )

    return RecommendationTakeoverReadiness(
        status="shadow",
        label="继续影子",
        confidence_score=56.0,
        summary="当前新旧两条链路差异还不够显著，贸然接管没有收益优势。",
        recommended_action="继续看差异统计，等 T+3 和胜率形成更稳定优势再推进。",
        conditions=conditions,
    )


def _build_composite_compare(days: int = 5) -> RecommendationCompareSnapshot:
    def builder() -> RecommendationCompareSnapshot:
        lookback_days = max(days + 5, 10)
        strategy_map = {item.name: item for item in _build_strategies()}
        verification_map = _load_signal_verification_records(days=max(days + 10, 20))
        signal_records = _load_signal_records(days=lookback_days)

        records_by_day: dict[str, list[dict]] = {}
        for signal in signal_records:
            trade_day = _signal_trade_day(signal)
            if not trade_day:
                continue
            records_by_day.setdefault(trade_day, []).append(signal)

        compare_rows: list[RecommendationCompareDay] = []
        sorted_days = sorted(records_by_day.keys(), reverse=True)[:days]
        for trade_day in sorted_days:
            day_records = records_by_day.get(trade_day, [])
            if not day_records:
                continue

            strong_candidates: list[StrongMoveCandidate] = []
            for record in day_records:
                candidate = _build_strong_move_candidate_from_record(record, strategy_map=strategy_map)
                if candidate is not None:
                    strong_candidates.append(candidate)
            strong_candidates.sort(
                key=lambda item: (item.composite_score, item.continuation_score, item.swing_score),
                reverse=True,
            )
            strong_move_map = {item.code: item for item in strong_candidates}

            day_picks: list[CompositePick] = []
            for record in day_records:
                pick = _build_composite_pick_from_record(
                    record,
                    strategy_map=strategy_map,
                    strong_move_map=strong_move_map,
                    theme_by_code={},
                )
                if pick is not None:
                    day_picks.append(pick)

            day_picks.sort(
                key=lambda item: (
                    item.composite_score,
                    item.theme_score,
                    item.capital_score,
                    item.strategy_score,
                ),
                reverse=True,
            )
            composite_pick = day_picks[0] if day_picks else None
            baseline_signal = max(
                day_records,
                key=lambda item: (
                    _to_float(item.get("score")) or 0.0,
                    _to_int(item.get("consensus_count")),
                    _to_float(item.get("risk_reward")) or 0.0,
                ),
            )

            composite_t1, composite_t3, composite_t5 = (None, None, None)
            if composite_pick is not None:
                composite_t1, composite_t3, composite_t5 = _verification_returns(
                    verification_map,
                    trade_day,
                    composite_pick.strategy,
                    composite_pick.code,
                )

            baseline_t1, baseline_t3, baseline_t5 = _verification_returns(
                verification_map,
                trade_day,
                str(baseline_signal.get("strategy", "")),
                str(baseline_signal.get("code", "")),
            )
            winner_label, winner_summary = _compare_winner_label(
                composite_t1,
                composite_t3,
                composite_t5,
                baseline_t1,
                baseline_t3,
                baseline_t5,
            )
            compare_rows.append(
                RecommendationCompareDay(
                    trade_date=trade_day,
                    composite_signal_id=composite_pick.signal_id if composite_pick is not None else None,
                    composite_code=composite_pick.code if composite_pick is not None else None,
                    composite_name=composite_pick.name if composite_pick is not None else None,
                    composite_score=composite_pick.composite_score if composite_pick is not None else None,
                    composite_t1_return_pct=composite_t1,
                    composite_t3_return_pct=composite_t3,
                    composite_t5_return_pct=composite_t5,
                    baseline_signal_id=str(baseline_signal.get("id", "")),
                    baseline_code=str(baseline_signal.get("code", "")),
                    baseline_name=str(baseline_signal.get("name", "")),
                    baseline_score=round(_to_float(baseline_signal.get("score")) or 0.0, 3),
                    baseline_t1_return_pct=baseline_t1,
                    baseline_t3_return_pct=baseline_t3,
                    baseline_t5_return_pct=baseline_t5,
                    winner_label=winner_label,
                    summary=winner_summary,
                )
            )

        composite_summary = _build_compare_summary("综合榜", compare_rows, side="composite")
        baseline_summary = _build_compare_summary("原推荐榜", compare_rows, side="baseline")

        advantage: list[str] = []
        if (
            composite_summary.avg_t3_return_pct is not None
            and baseline_summary.avg_t3_return_pct is not None
        ):
            diff = composite_summary.avg_t3_return_pct - baseline_summary.avg_t3_return_pct
            if diff > 0.3:
                advantage.append(f"T+3 平均收益综合榜领先 {diff:.2f}%")
            elif diff < -0.3:
                advantage.append(f"T+3 平均收益原推荐榜领先 {abs(diff):.2f}%")
            else:
                advantage.append("T+3 平均收益两条链路接近")

        if composite_summary.t1_win_rate is not None and baseline_summary.t1_win_rate is not None:
            diff = composite_summary.t1_win_rate - baseline_summary.t1_win_rate
            if diff > 5:
                advantage.append(f"T+1 胜率综合榜领先 {diff:.1f}pct")
            elif diff < -5:
                advantage.append(f"T+1 胜率原推荐榜领先 {abs(diff):.1f}pct")
            else:
                advantage.append("T+1 胜率差异不大，继续观察")

        if not advantage:
            advantage.append("当前样本还不够大，先继续影子观察，不急着接管主排序")

        return RecommendationCompareSnapshot(
            composite=composite_summary,
            baseline=baseline_summary,
            advantage=advantage,
            readiness=_build_compare_readiness(composite_summary, baseline_summary),
            days=compare_rows,
        )

    return _cached_runtime_value(
        "composite_compare",
        days,
        ttl_seconds=15,
        dependency_paths=_runtime_cache_paths(
            _SIGNAL_TRACKER,
            _STRATEGIES_JSON,
            _AGENT_MEMORY,
            os.path.join(_DIR, "signals_db.json"),
            *_db_dependency_paths(),
        ),
        builder=builder,
    )


def _build_strong_moves(days: int = 1, limit: int = 5) -> list[StrongMoveCandidate]:
    def builder() -> list[StrongMoveCandidate]:
        strategy_map = {item.name: item for item in _build_strategies()}
        candidates: list[StrongMoveCandidate] = []

        for signal in _load_signal_records(days=days):
            candidate = _build_strong_move_candidate_from_record(signal, strategy_map=strategy_map)
            if candidate is not None:
                candidates.append(candidate)

        candidates.sort(
            key=lambda item: (item.composite_score, item.continuation_score, item.swing_score),
            reverse=True,
        )
        return candidates[:limit]

    return _cached_runtime_value(
        "strong_moves",
        (days, limit),
        ttl_seconds=10,
        dependency_paths=_runtime_cache_paths(
            _SIGNAL_TRACKER,
            _STRATEGIES_JSON,
            _AGENT_MEMORY,
            *_db_dependency_paths(),
        ),
        builder=builder,
    )


def _build_positions() -> list[Position]:
    positions = _load_portfolio().get("positions", [])

    result = []
    for pos in positions:
        if pos.get("quantity", 0) == 0:
            continue
        result.append(_position_summary_model(pos))

    result.sort(key=lambda x: x.profit_loss_pct, reverse=True)
    return result


def _regime_display_name(regime: str) -> str:
    mapping = {
        "bull": "偏强",
        "neutral": "震荡",
        "weak": "偏弱",
        "bear": "防守",
    }
    return mapping.get(str(regime).lower(), "震荡")


def _positioning_mode(
    regime: str,
    target_exposure_pct: float,
    critical_alerts: int,
    warning_alerts: int,
) -> str:
    regime = str(regime).lower()
    if critical_alerts > 0 or regime == "bear" or target_exposure_pct <= 10:
        return "防守"
    if regime == "weak" or target_exposure_pct <= 35 or warning_alerts >= 3:
        return "谨慎"
    if regime == "bull" and target_exposure_pct >= 70:
        return "进攻"
    return "平衡"


def _build_positioning_plan(days: int = 1, limit: int = 3) -> PositioningPlan:
    from config import RISK_PARAMS

    try:
        from smart_trader import detect_market_regime

        regime_result = detect_market_regime() or {}
    except Exception:
        regime_result = {}

    portfolio = _load_portfolio()
    positions = portfolio.get("positions", [])
    cash_balance = _round_money(_to_float(portfolio.get("cash")) or 0.0)
    total_assets = _round_money(_to_float(portfolio.get("total_assets")) or cash_balance)
    if total_assets <= 0:
        total_assets = cash_balance

    current_exposure_pct = 0.0
    if total_assets > 0:
        current_exposure_pct = round(max(total_assets - cash_balance, 0.0) / total_assets * 100, 1)

    regime = str(regime_result.get("regime", "neutral")).lower()
    regime_score = round((_to_float(regime_result.get("score")) or 0.5) * 100, 1)
    regime_scale = _to_float(regime_result.get("position_scale"))
    if regime_scale is None:
        regime_scale = 0.8
    regime_params = regime_result.get("regime_params", {})
    if not isinstance(regime_params, dict):
        regime_params = {}

    composite_picks = _build_composite_picks(days=days, limit=max(limit + 2, 5))
    theme_radar = _build_theme_radar(limit=3)
    alerts = _build_risk_alerts()
    critical_alerts = sum(1 for item in alerts if item.level == "critical")
    warning_alerts = sum(1 for item in alerts if item.level == "warning")

    top_pick = composite_picks[0] if composite_picks else None
    top_theme = None
    if top_pick and top_pick.theme_sector:
        top_theme = top_pick.theme_sector
    elif theme_radar:
        top_theme = theme_radar[0].sector

    event_overlay = _build_event_positioning_overlay(top_theme=top_theme, top_pick=top_pick)
    event_summary = str(event_overlay.get("summary", "")).strip()

    base_target_exposure_pct = regime_scale * 70.0
    risk_penalty = critical_alerts * 18 + max(warning_alerts - 1, 0) * 6
    opportunity_bonus = 0.0
    if critical_alerts == 0 and top_pick is not None:
        if top_pick.composite_score >= 68:
            opportunity_bonus = 6.0
        elif top_pick.composite_score >= 60:
            opportunity_bonus = 3.0
    opportunity_bonus += _to_float(event_overlay.get("exposure_adjustment")) or 0.0

    if regime == "bear":
        target_exposure_pct = 0.0
    else:
        target_exposure_pct = round(
            min(90.0, max(0.0, base_target_exposure_pct - risk_penalty + opportunity_bonus)),
            1,
        )

    if not composite_picks and not positions:
        target_exposure_pct = min(target_exposure_pct, 30.0)

    deployable_exposure_pct = round(max(0.0, target_exposure_pct - current_exposure_pct), 1)
    deployable_cash = _round_money(total_assets * deployable_exposure_pct / 100.0)

    risk_max_positions = _to_int(RISK_PARAMS.get("max_positions")) or 9
    regime_max_positions = _to_int(regime_params.get("max_positions")) or risk_max_positions
    max_positions = max(0, min(risk_max_positions, regime_max_positions))
    available_slots = max(0, max_positions - len(positions))

    first_entry_position_pct = top_pick.first_position_pct if top_pick is not None else 0
    if first_entry_position_pct <= 0 and target_exposure_pct > 0:
        first_entry_position_pct = 8 if target_exposure_pct >= 50 else 5
    if first_entry_position_pct > 0:
        first_entry_position_pct = max(
            4,
            min(
                18,
                first_entry_position_pct + _to_int(event_overlay.get("first_entry_adjustment")),
            ),
        )

    base_single_cap = _to_int(RISK_PARAMS.get("single_position_pct")) or 15
    max_single_position_pct = 0
    if target_exposure_pct > 0:
        max_single_position_pct = min(
            25,
            max(
                10,
                max(base_single_cap, first_entry_position_pct + 8)
                + _to_int(event_overlay.get("single_cap_adjustment")),
            ),
        )

    max_theme_exposure_pct = 0
    if target_exposure_pct > 0:
        max_theme_exposure_pct = min(
            40,
            max(
                16,
                max(max_single_position_pct + 10, 18)
                + _to_int(event_overlay.get("theme_cap_adjustment")),
            ),
        )

    recommended_new_positions = 0
    if first_entry_position_pct > 0:
        recommended_new_positions = int(deployable_exposure_pct // first_entry_position_pct)
    recommended_new_positions = max(0, min(available_slots, recommended_new_positions))

    sector_focus = None
    if positions:
        try:
            from risk_manager import classify_sector

            sector_counts: dict[str, int] = {}
            for raw_position in positions:
                sector = classify_sector(str(raw_position.get("name", "")))
                sector_counts[sector] = sector_counts.get(sector, 0) + 1
            if sector_counts:
                sector_focus = max(sector_counts.items(), key=lambda item: item[1])
        except Exception:
            sector_focus = None

    mode = _positioning_mode(regime, target_exposure_pct, critical_alerts, warning_alerts)
    focus = (
        f"当前更像 {mode} 节奏。总仓先控在 {target_exposure_pct:.1f}% 左右，"
        "先看综合候选，再决定是否继续加火力。"
    )
    if mode == "防守":
        focus = (
            f"当前更像 {mode} 日。优先保住现金和纪律，先把风险压住，"
            "不要为了追机会把节奏打乱。"
        )
    elif top_pick is not None:
        focus = (
            f"{top_pick.code} {top_pick.name} 是当前最值得先看的综合候选。"
            f"总仓建议 {target_exposure_pct:.1f}%，先用 {first_entry_position_pct}% 首仓试错。"
        )
    if event_summary:
        focus = f"{focus} {event_summary}"

    reasons = [
        f"市场状态目前是 {_regime_display_name(regime)}，评分 {regime_score:.1f}。",
        f"当前组合实仓 {current_exposure_pct:.1f}% ，目标总仓 {target_exposure_pct:.1f}% 。",
    ]
    if event_summary:
        reasons.append(event_summary)
    if top_pick is not None:
        reasons.append(
            f"综合推荐头部是 {top_pick.code} {top_pick.name}，当前标签是 {top_pick.setup_label}。"
        )
    if top_theme:
        reasons.append(f"当前优先关注的主线是 {top_theme}，不要平均撒到无关方向。")
    if sector_focus is not None:
        reasons.append(f"当前组合持仓最集中的方向是 {sector_focus[0]}，已有 {sector_focus[1]} 个仓位。")
    elif not positions:
        reasons.append("当前组合接近空仓，现金充足，更适合按计划逐步建仓而不是一把打满。")
    if critical_alerts or warning_alerts:
        reasons.append(f"系统当前还有 {critical_alerts} 条高优先级、{warning_alerts} 条一般风险提醒。")

    actions = [
        f"总仓先控在 {target_exposure_pct:.1f}% 左右，当前还可再部署 {deployable_exposure_pct:.1f}% / {deployable_cash:.0f} 元。",
    ]
    if first_entry_position_pct > 0:
        actions.append(
            f"单票先用 {first_entry_position_pct}% 首仓试错，单票满仓不要超过 {max_single_position_pct}% 。"
        )
    if max_theme_exposure_pct > 0:
        actions.append(f"单一主线或主题的暴露先压在 {max_theme_exposure_pct}% 以内。")
    if event_summary:
        actions.append(event_summary)
    if critical_alerts > 0:
        actions.append("先处理高优先级风险提醒，再决定是否继续开新仓。")
    elif top_pick is not None:
        actions.append(f"今天先从 {top_pick.code} {top_pick.name} 这种综合候选开始，不要平均撒网。")

    deployments: list[PositioningDeployment] = []
    remaining_pct = deployable_exposure_pct
    max_deployments = available_slots if available_slots > 0 else 0
    for pick in composite_picks[:limit]:
        if len(deployments) >= max_deployments or remaining_pct <= 0:
            break
        suggested_position_pct = min(
            max_single_position_pct,
            pick.first_position_pct or first_entry_position_pct,
            int(max(0.0, remaining_pct)),
        )
        if suggested_position_pct < max(4, first_entry_position_pct // 2 if first_entry_position_pct else 4):
            continue
        deployments.append(
            PositioningDeployment(
                code=pick.code,
                name=pick.name,
                setup_label=pick.setup_label,
                suggested_position_pct=suggested_position_pct,
                suggested_amount=_round_money(total_assets * suggested_position_pct / 100.0),
                theme_sector=pick.theme_sector,
                reason=pick.reasons[0] if pick.reasons else pick.action,
            )
        )
        remaining_pct = max(0.0, remaining_pct - suggested_position_pct)

    return PositioningPlan(
        mode=mode,
        regime=regime,
        regime_score=regime_score,
        event_bias=str(event_overlay.get("bias", "中性")),
        event_score=_to_float(event_overlay.get("score")) or 50.0,
        event_summary=event_summary or None,
        event_focus_sector=(
            str(event_overlay.get("focus_sector"))
            if event_overlay.get("focus_sector") is not None
            else None
        ),
        current_exposure_pct=current_exposure_pct,
        target_exposure_pct=target_exposure_pct,
        deployable_exposure_pct=deployable_exposure_pct,
        cash_balance=cash_balance,
        total_assets=total_assets,
        deployable_cash=deployable_cash,
        current_positions=len(positions),
        available_slots=available_slots,
        max_positions=max_positions,
        first_entry_position_pct=first_entry_position_pct,
        max_single_position_pct=max_single_position_pct,
        max_theme_exposure_pct=max_theme_exposure_pct,
        top_theme=top_theme,
        focus=focus,
        reasons=reasons,
        actions=actions,
        deployments=deployments,
    )


def _build_position_detail(code: str) -> PositionDetail:
    positions = _load_portfolio().get("positions", [])
    raw_position = next((item for item in positions if item.get("code") == code), None)

    if not raw_position or raw_position.get("quantity", 0) == 0:
        raise HTTPException(status_code=404, detail="持仓不存在")

    return _position_detail_model(raw_position)


def _action_result(
    *,
    action: str,
    code: str,
    name: str,
    message: str,
    executed_at: Optional[str] = None,
    quantity: int,
    execution_price: float,
    cash_balance: float,
    total_assets: float,
    position: Optional[dict] = None,
    realized_profit_loss: Optional[float] = None,
) -> PortfolioActionResult:
    return PortfolioActionResult(
        success=True,
        action=action,
        code=code,
        name=name,
        message=message,
        executed_at=executed_at or datetime.now().isoformat(),
        quantity=quantity,
        execution_price=_round_money(execution_price),
        cash_balance=_round_money(cash_balance),
        total_assets=_round_money(total_assets),
        position=_position_detail_model(position) if position else None,
        realized_profit_loss=_round_money(realized_profit_loss)
        if realized_profit_loss is not None
        else None,
    )


def _open_signal_position(signal_id: str, payload: SignalOpenRequest) -> PortfolioActionResult:
    quantity = max(0, int(payload.quantity))
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="买入数量必须大于 0")

    signal = _build_signal_detail(signal_id)
    execution_price = _round_money(
        payload.price if payload.price is not None else (signal.buy_price or signal.price)
    )
    market_price = _round_money(signal.price or execution_price)
    stop_loss = (
        _round_money(payload.stop_loss)
        if payload.stop_loss is not None
        else _round_money(signal.stop_loss)
    )
    take_profit = (
        _round_money(payload.take_profit)
        if payload.take_profit is not None
        else _round_money(signal.target_price)
    )
    _validate_risk_values(stop_loss, take_profit, reference_price=execution_price)

    if execution_price <= 0:
        raise HTTPException(status_code=400, detail="开仓价格无效")

    portfolio = _load_portfolio()
    required_cash = _round_money(execution_price * quantity)
    if required_cash > portfolio.get("cash", 0):
        raise HTTPException(
            status_code=400,
            detail=f"可用资金不足，需 {required_cash:.2f}，当前仅有 {portfolio.get('cash', 0):.2f}",
        )

    trade_time = _current_trade_time()
    position_index = _find_position_index(portfolio, signal.code)
    reason = f"模拟开仓: {signal.strategy} 信号 {signal.id} (得分{signal.score:.3f})"

    if position_index is not None:
        position = dict(portfolio["positions"][position_index])
        old_quantity = position.get("quantity", 0)
        new_quantity = old_quantity + quantity
        blended_cost = _round_money(
            (position.get("cost_price", 0) * old_quantity + execution_price * quantity) / new_quantity
        )
        position["quantity"] = new_quantity
        position["cost_price"] = blended_cost
        position["current_price"] = market_price
        position["stop_loss"] = (
            _round_money(payload.stop_loss)
            if payload.stop_loss is not None
            else position.get("stop_loss", stop_loss) or stop_loss
        )
        position["take_profit"] = (
            _round_money(payload.take_profit)
            if payload.take_profit is not None
            else position.get("take_profit", take_profit) or take_profit
        )
        price_floor = [
            price
            for price in (
                _to_float(position.get("low_price")),
                _to_float(signal.low),
                market_price,
                execution_price,
            )
            if price is not None and price > 0
        ]
        price_ceiling = [
            price
            for price in (
                _to_float(position.get("high_price")),
                _to_float(signal.high),
                market_price,
                execution_price,
            )
            if price is not None and price > 0
        ]
        position["low_price"] = _round_money(min(price_floor)) if price_floor else market_price
        position["high_price"] = _round_money(max(price_ceiling)) if price_ceiling else market_price
        trades = list(position.get("trades", []))
        trades.append(
            {
                "time": trade_time,
                "type": "buy",
                "price": execution_price,
                "quantity": quantity,
                "reason": reason,
            }
        )
        position["trades"] = trades
        portfolio["positions"][position_index] = position
    else:
        floor_candidates = [
            price
            for price in (_to_float(signal.low), market_price, execution_price)
            if price is not None and price > 0
        ]
        ceiling_candidates = [
            price
            for price in (_to_float(signal.high), market_price, execution_price)
            if price is not None and price > 0
        ]
        portfolio["positions"].append(
            {
                "code": signal.code,
                "name": signal.name,
                "quantity": quantity,
                "cost_price": execution_price,
                "current_price": market_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "hold_days": 0,
                "strategy": signal.strategy,
                "buy_time": trade_time,
                "high_price": _round_money(max(ceiling_candidates))
                if ceiling_candidates
                else market_price,
                "low_price": _round_money(min(floor_candidates))
                if floor_candidates
                else market_price,
                "trailing_stop": False,
                "trailing_trigger_price": 0,
                "trades": [
                    {
                        "time": trade_time,
                        "type": "buy",
                        "price": execution_price,
                        "quantity": quantity,
                        "reason": reason,
                    }
                ],
            }
        )

    portfolio["cash"] = _round_money(portfolio.get("cash", 0) - required_cash)
    _save_portfolio(portfolio)
    updated_index = _find_position_index(portfolio, signal.code)
    updated_position = portfolio["positions"][updated_index] if updated_index is not None else None
    return _action_result(
        action="open",
        code=signal.code,
        name=signal.name,
        message=f"已按 {execution_price:.2f} 模拟开仓 {quantity} 股。",
        executed_at=trade_time,
        quantity=quantity,
        execution_price=execution_price,
        cash_balance=portfolio.get("cash", 0),
        total_assets=portfolio.get("total_assets", 0),
        position=updated_position,
    )


def _update_position_risk(code: str, payload: PositionRiskUpdateRequest) -> PortfolioActionResult:
    if (
        payload.stop_loss is None
        and payload.take_profit is None
        and payload.trailing_stop is None
        and payload.trailing_trigger_price is None
    ):
        raise HTTPException(status_code=400, detail="至少提交一个风控字段")

    portfolio = _load_portfolio()
    position_index = _find_position_index(portfolio, code)
    if position_index is None:
        raise HTTPException(status_code=404, detail="持仓不存在")

    position = dict(portfolio["positions"][position_index])
    stop_loss = (
        _round_money(payload.stop_loss)
        if payload.stop_loss is not None
        else position.get("stop_loss", 0)
    )
    take_profit = (
        _round_money(payload.take_profit)
        if payload.take_profit is not None
        else position.get("take_profit", 0)
    )
    trailing_trigger_price = (
        _round_money(payload.trailing_trigger_price)
        if payload.trailing_trigger_price is not None
        else position.get("trailing_trigger_price", 0)
    )
    if trailing_trigger_price < 0:
        raise HTTPException(status_code=400, detail="追踪触发价不能为负数")

    _validate_risk_values(stop_loss, take_profit)

    position["stop_loss"] = stop_loss
    position["take_profit"] = take_profit
    if payload.trailing_stop is not None:
        position["trailing_stop"] = payload.trailing_stop
    if payload.trailing_trigger_price is not None:
        position["trailing_trigger_price"] = trailing_trigger_price

    change_notes = []
    if payload.stop_loss is not None:
        change_notes.append(f"止损 {stop_loss:.2f}" if stop_loss > 0 else "清空止损")
    if payload.take_profit is not None:
        change_notes.append(f"止盈 {take_profit:.2f}" if take_profit > 0 else "清空止盈")
    if payload.trailing_stop is not None:
        change_notes.append("启用追踪止盈" if payload.trailing_stop else "关闭追踪止盈")
    if payload.trailing_trigger_price is not None:
        change_notes.append(
            f"追踪触发价 {trailing_trigger_price:.2f}"
            if trailing_trigger_price > 0
            else "清空追踪触发价"
        )

    trades = list(position.get("trades", []))
    trades.append(
        {
            "time": _current_trade_time(),
            "type": "adjust",
            "price": position.get("current_price", 0),
            "quantity": position.get("quantity", 0),
            "reason": " / ".join(change_notes) or "更新风控计划",
        }
    )
    position["trades"] = trades
    portfolio["positions"][position_index] = position

    _save_portfolio(portfolio)
    updated_position = portfolio["positions"][position_index]
    return _action_result(
        action="risk_update",
        code=updated_position.get("code", ""),
        name=updated_position.get("name", ""),
        message="风控计划已保存。",
        executed_at=trades[-1]["time"] if trades else None,
        quantity=updated_position.get("quantity", 0),
        execution_price=updated_position.get("current_price", 0),
        cash_balance=portfolio.get("cash", 0),
        total_assets=portfolio.get("total_assets", 0),
        position=updated_position,
    )


def _close_position(code: str, payload: PositionCloseRequest) -> PortfolioActionResult:
    portfolio = _load_portfolio()
    position_index = _find_position_index(portfolio, code)
    if position_index is None:
        raise HTTPException(status_code=404, detail="持仓不存在")

    position = dict(portfolio["positions"][position_index])
    execution_price = _round_money(
        payload.price if payload.price is not None else position.get("current_price", 0)
    )
    if execution_price <= 0:
        raise HTTPException(status_code=400, detail="平仓价格无效")

    quantity = max(0, position.get("quantity", 0))
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="当前没有可平仓数量")
    close_quantity = quantity if payload.quantity is None else max(0, int(payload.quantity))
    if close_quantity <= 0:
        raise HTTPException(status_code=400, detail="卖出数量必须大于 0")
    if close_quantity > quantity:
        raise HTTPException(status_code=400, detail="卖出数量不能超过当前持仓")

    proceeds = _round_money(execution_price * close_quantity)
    realized_profit_loss = _round_money(
        (execution_price - position.get("cost_price", 0)) * close_quantity
    )
    trade_time = _current_trade_time()
    sell_reason = (payload.reason or "").strip() or "手动平仓"

    trades = list(position.get("trades", []))
    trades.append(
        {
            "time": trade_time,
            "type": "sell",
            "price": execution_price,
            "quantity": close_quantity,
            "reason": sell_reason,
        }
    )

    portfolio["cash"] = _round_money(portfolio.get("cash", 0) + proceeds)
    if close_quantity == quantity:
        closed_position = {
            **position,
            "current_price": execution_price,
            "trades": trades,
            "status": "closed",
            "close_price": execution_price,
            "closed_at": datetime.now().isoformat(),
            "close_reason": sell_reason,
            "realized_profit_loss": realized_profit_loss,
        }
        del portfolio["positions"][position_index]
        portfolio["closed_positions"].append(closed_position)
        _save_portfolio(portfolio)

        return _action_result(
            action="close",
            code=position.get("code", ""),
            name=position.get("name", ""),
            message=f"已按 {execution_price:.2f} 手动平仓，成交 {close_quantity} 股。",
            executed_at=trade_time,
            quantity=close_quantity,
            execution_price=execution_price,
            cash_balance=portfolio.get("cash", 0),
            total_assets=portfolio.get("total_assets", 0),
            realized_profit_loss=realized_profit_loss,
        )

    remaining_position = dict(position)
    remaining_position["quantity"] = quantity - close_quantity
    remaining_position["current_price"] = execution_price
    remaining_position["trades"] = trades
    portfolio["positions"][position_index] = remaining_position
    _save_portfolio(portfolio)
    updated_position = portfolio["positions"][position_index]

    return _action_result(
        action="close",
        code=updated_position.get("code", ""),
        name=updated_position.get("name", ""),
        message=(
            f"已按 {execution_price:.2f} 卖出 {close_quantity} 股，"
            f"剩余 {updated_position.get('quantity', 0)} 股。"
        ),
        executed_at=trade_time,
        quantity=close_quantity,
        execution_price=execution_price,
        cash_balance=portfolio.get("cash", 0),
        total_assets=portfolio.get("total_assets", 0),
        position=updated_position,
        realized_profit_loss=realized_profit_loss,
    )


def _build_kline_bars(code: str, days: int = 60) -> list[KlineBar]:
    try:
        from stock_analyzer import _fetch_klines

        rows = _fetch_klines(code, days=max(20, min(days, 180)))
    except Exception:
        rows = []

    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        result.append(
            KlineBar(
                date=str(row.get("date", "")),
                open=_to_float(row.get("open")) or 0,
                high=_to_float(row.get("high")) or 0,
                low=_to_float(row.get("low")) or 0,
                close=_to_float(row.get("close")) or 0,
                volume=_to_float(row.get("volume")) or 0,
                turnover=_to_float(row.get("turnover")) or 0,
            )
        )

    return result


def _build_risk_alerts() -> list[RiskAlert]:
    created_at = datetime.now().isoformat()
    system = _build_system_status()
    learning = _build_learning_progress()
    positions = _build_positions()
    signals = _build_signals()
    alerts: list[RiskAlert] = []

    def add_alert(
        alert_id: str,
        level: str,
        title: str,
        message: str,
        source: str,
        source_id: str = "",
        route: Optional[str] = None,
    ) -> None:
        alerts.append(
            RiskAlert(
                id=alert_id,
                level=level,
                title=title,
                message=message,
                source=source,
                source_id=source_id,
                created_at=created_at,
                route=route,
            )
        )

    if system.health_score < 80:
        add_alert(
            alert_id="system-health",
            level="critical" if system.health_score < 70 else "warning",
            title="系统健康分偏低",
            message=f"当前健康分 {system.health_score}，建议检查调度、日志和数据抓取状态。",
            source="system",
            route="/",
        )

    if learning.decision_accuracy < 0.65:
        add_alert(
            alert_id="learning-accuracy",
            level="warning",
            title="学习准确率偏弱",
            message=f"当前决策准确率 {round(learning.decision_accuracy * 100, 1)}%，建议复查近期因子调整。",
            source="learning",
            route="/brain",
        )

    if learning.experiments_running == 0:
        add_alert(
            alert_id="learning-experiments",
            level="info",
            title="当前没有实验在跑",
            message="学习链当前没有活跃实验，注意确认自学习引擎是否空转。",
            source="learning",
            route="/brain",
        )

    if signals:
        strongest = signals[0]
        if strongest.score >= 0.95:
            add_alert(
                alert_id=f"signal-{strongest.id}",
                level="info",
                title="出现高置信度信号",
                message=(
                    f"{strongest.code} {strongest.name} 得分 {strongest.score:.3f}，"
                    f"盈亏比 {strongest.risk_reward:.1f}:1。"
                ),
                source="signal",
                source_id=strongest.id,
                route=f"/signal/{strongest.id}",
            )

    for position in positions:
        if position.stop_loss > 0 and position.current_price <= position.stop_loss:
            add_alert(
                alert_id=f"position-stop-hit-{position.code}",
                level="critical",
                title=f"{position.code} 已触及止损线",
                message=(
                    f"{position.name} 当前价 {position.current_price:.2f}，"
                    f"已低于止损价 {position.stop_loss:.2f}。"
                ),
                source="position",
                source_id=position.code,
                route=f"/position/{position.code}",
            )
            continue

        if position.stop_loss > 0 and position.current_price <= position.stop_loss * 1.03:
            distance = (position.current_price / position.stop_loss - 1) * 100
            add_alert(
                alert_id=f"position-stop-near-{position.code}",
                level="warning",
                title=f"{position.code} 接近止损位",
                message=(
                    f"{position.name} 离止损仅剩 {max(distance, 0):.2f}%，"
                    f"当前价 {position.current_price:.2f} / 止损 {position.stop_loss:.2f}。"
                ),
                source="position",
                source_id=position.code,
                route=f"/position/{position.code}",
            )

        if position.take_profit > 0 and position.current_price >= position.take_profit * 0.98:
            add_alert(
                alert_id=f"position-profit-near-{position.code}",
                level="info",
                title=f"{position.code} 接近止盈位",
                message=(
                    f"{position.name} 当前价 {position.current_price:.2f}，"
                    f"已接近止盈价 {position.take_profit:.2f}。"
                ),
                source="position",
                source_id=position.code,
                route=f"/position/{position.code}",
            )

        if position.profit_loss_pct <= -3:
            add_alert(
                alert_id=f"position-drawdown-{position.code}",
                level="warning",
                title=f"{position.code} 回撤偏大",
                message=(
                    f"{position.name} 当前浮亏 {position.profit_loss_pct:.2f}%，"
                    "建议复查仓位和风控计划。"
                ),
                source="position",
                source_id=position.code,
                route=f"/position/{position.code}",
            )

    level_order = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda item: (level_order.get(item.level, 9), item.id))
    return alerts[:12]


def _build_app_messages(limit: int = 30) -> list[AppMessage]:
    def builder() -> list[AppMessage]:
        center = _load_app_message_center()
        items = list(center.get("items", []))
        takeover_message = _build_takeover_message()
        if takeover_message:
            items.append(takeover_message)
        composite_focus_message = _build_composite_focus_message()
        if composite_focus_message:
            items.append(composite_focus_message)
        industry_capital_message = _build_industry_capital_focus_message()
        if industry_capital_message:
            items.append(industry_capital_message)
        items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return [_app_message_model(item) for item in items[: max(1, min(limit, 100))]]

    return _cached_runtime_value(
        "app_messages",
        limit,
        ttl_seconds=6,
        dependency_paths=_runtime_cache_paths(
            _APP_MESSAGE_CENTER,
            _INDUSTRY_CAPITAL_RESEARCH_LOG,
            _PUSH_STATE,
            _LEARNING_DAILY_ADVANCE,
            _SECTOR_ALERTS,
            _NEWS_DIGEST,
            _POLICY_DIRECTION_CATALOG,
            _POLICY_OFFICIAL_WATCH,
            _POLICY_OFFICIAL_CARDS,
            _POLICY_EXECUTION_TIMELINE,
            _INDUSTRY_CAPITAL_COMPANY_MAP,
            _SIGNAL_TRACKER,
            os.path.join(_DIR, "signals_db.json"),
            *_db_dependency_paths(),
        ),
        builder=builder,
    )


def _action_priority(level: str, kind: str) -> int:
    base = {"critical": 0, "warning": 1, "info": 2}.get(level, 3)
    kind_bias = {
        "position": 0,
        "alert": 1,
        "industry_capital": 2,
        "composite_pick": 3,
        "signal": 3,
        "takeover": 4,
        "learning": 5,
    }.get(kind, 5)
    return base * 10 + kind_bias


def _composite_pick_action_route(pick: CompositePick) -> str:
    if pick.source_category == "theme_seed" or str(pick.signal_id).startswith("theme-seed-"):
        return "/(tabs)/brain"
    return f"/signal/{pick.signal_id}"


def _composite_pick_action_label(pick: CompositePick) -> str:
    if pick.source_category == "theme_seed" or str(pick.signal_id).startswith("theme-seed-"):
        return "去决策台复核"
    return "看推荐"


def _composite_pick_level(pick: CompositePick) -> str:
    if pick.event_bias == "偏空":
        return "warning"
    return "info"


def _build_composite_focus_message() -> Optional[dict]:
    composite_picks = _build_composite_picks(days=1, limit=8)
    if not composite_picks:
        return None

    top_theme_seed = next((item for item in composite_picks if item.source_category == "theme_seed"), None)
    top_swing = next(
        (item for item in composite_picks if item.horizon_label in {"中期波段", "连涨接力"}),
        None,
    )
    focus_pick = top_theme_seed or top_swing or composite_picks[0]

    title = "今天先看主线种子"
    if top_theme_seed:
        title = f"主线种子候选 {top_theme_seed.code} {top_theme_seed.name}"
    elif top_swing:
        title = f"中期波段候选 {top_swing.code} {top_swing.name}"
    else:
        title = f"综合候选 {focus_pick.code} {focus_pick.name}"

    summary_parts: list[str] = []
    if top_theme_seed:
        summary_parts.append(
            f"主线种子 {top_theme_seed.code} {top_theme_seed.name}，{top_theme_seed.horizon_label}，"
            f"事件{top_theme_seed.event_bias}，建议首仓 {top_theme_seed.first_position_pct}%"
        )
    if top_swing and (top_theme_seed is None or top_swing.signal_id != top_theme_seed.signal_id):
        summary_parts.append(
            f"中期波段 {top_swing.code} {top_swing.name}，{top_swing.setup_label}，"
            f"建议首仓 {top_swing.first_position_pct}%"
        )
    if not summary_parts:
        summary_parts.append(
            f"{focus_pick.source_label} {focus_pick.code} {focus_pick.name}，{focus_pick.horizon_label}，"
            f"建议首仓 {focus_pick.first_position_pct}%"
        )

    next_step = "先去决策台复核主线，再决定要不要转入推荐或诊股。"
    if top_theme_seed is None and top_swing is not None:
        next_step = "先去推荐页看中期波段候选，再决定是否进入执行观察。"
    elif focus_pick.source_category not in {"theme_seed"}:
        next_step = "先去推荐页深看原因和风险，再决定是不是今天的首要机会。"

    body = "；".join(summary_parts) + f"。下一步：{next_step}"
    level = _composite_pick_level(focus_pick)

    return _normalize_app_message(
        {
            "id": f"msg_composite_focus_{focus_pick.code}_{focus_pick.horizon_label}",
            "title": title,
            "body": body,
            "preview": body[:140],
            "level": level,
            "channel": "system_focus",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
    )


def _build_action_board(limit: int = 6) -> list[ActionBoardItem]:
    def builder() -> list[ActionBoardItem]:
        now = datetime.now().isoformat()
        items: list[ActionBoardItem] = []

        for alert in _build_risk_alerts()[:3]:
            items.append(
                ActionBoardItem(
                    id=f"action-alert-{alert.id}",
                    kind="alert",
                    level=alert.level,
                    title=alert.title,
                    summary=alert.message,
                    action_label="立即处理",
                    route=alert.route,
                    source=alert.source,
                    source_id=alert.source_id,
                    created_at=alert.created_at,
                )
            )

        portfolio = _load_portfolio()
        for raw_position in portfolio.get("positions", []):
            if not isinstance(raw_position, dict) or _to_int(raw_position.get("quantity")) <= 0:
                continue
            detail = _position_detail_model(raw_position)
            guide = detail.position_guide
            if guide.mode == "继续持有" and not guide.warnings:
                continue
            action_label = "处理仓位"
            if guide.suggested_reduce_quantity > 0:
                action_label = "去减仓/锁盈"
            elif guide.suggested_stop_loss > 0 or guide.suggested_take_profit > 0:
                action_label = "去调风控"
            level = "warning"
            if guide.mode in {"优先减仓或平仓", "先降风险"}:
                level = "critical"
            elif guide.mode in {"先锁盈", "锁盈观察"}:
                level = "warning"
            items.append(
                ActionBoardItem(
                    id=f"action-position-{detail.code}",
                    kind="position",
                    level=level,
                    title=f"{detail.code} {guide.mode}",
                    summary=guide.summary,
                    action_label=action_label,
                    route=f"/position/{detail.code}",
                    source="position",
                    source_id=detail.code,
                    created_at=detail.buy_time or now,
                )
            )

        composite_picks = _build_composite_picks(days=1, limit=8)
        composite_focus: list[CompositePick] = []
        top_theme_seed = next((item for item in composite_picks if item.source_category == "theme_seed"), None)
        top_swing = next(
            (item for item in composite_picks if item.horizon_label in {"中期波段", "连涨接力"}),
            None,
        )
        top_strategy = next(
            (
                item
                for item in composite_picks
                if item.source_category not in {"theme_seed"}
                and item.horizon_label not in {"中期波段", "连涨接力"}
            ),
            None,
        )
        for pick in (top_theme_seed, top_swing, top_strategy):
            if pick is None:
                continue
            if any(existing.signal_id == pick.signal_id for existing in composite_focus):
                continue
            composite_focus.append(pick)

        for pick in composite_focus[:2]:
            summary = f"{pick.source_label} / {pick.horizon_label} / {pick.action}"
            items.append(
                ActionBoardItem(
                    id=f"action-composite-{pick.signal_id}",
                    kind="composite_pick",
                    level=_composite_pick_level(pick),
                    title=f"{pick.code} {pick.source_label}",
                    summary=summary,
                    action_label=_composite_pick_action_label(pick),
                    route=_composite_pick_action_route(pick),
                    source="signal",
                    source_id=pick.signal_id,
                    created_at=pick.timestamp,
                )
            )

        industry_capital = _build_industry_capital_map(limit=2)
        if industry_capital:
            focus = industry_capital[0]
            title = f"{focus.direction} {focus.strategic_label}"
            if focus.research_signal_label in {"验证增强", "出现阻力"}:
                title = f"{focus.direction} {focus.research_signal_label}"
            items.append(
                ActionBoardItem(
                    id=f"action-industry-capital-{focus.id}",
                    kind="industry_capital",
                    level=_industry_capital_level(focus),
                    title=title,
                    summary=(
                        f"优先级 {focus.priority_score:.1f}。{focus.summary} 调研信号：{focus.research_summary}"
                        " 下一步：先看方向深页，确认兑现节点、调研回写和合作对象。"
                    ),
                    action_label="看方向深页",
                route=_industry_capital_route(focus),
                source="industry_capital",
                source_id=focus.id,
                created_at=now,
            )
        )
            if focus.official_freshness_score >= 60 and focus.official_source_entries:
                source_entry = focus.official_source_entries[0]
                items.append(
                    ActionBoardItem(
                        id=f"action-industry-official-{focus.id}",
                        kind="industry_official",
                        level="info",
                        title=f"{focus.direction} 官方更新 {focus.official_freshness_label}",
                        summary=(
                            f"{source_entry.title} / {source_entry.issuer} "
                            f"({focus.official_freshness_label})，rapid follow-up on policy details."
                        ),
                        action_label="看官方原文",
                        route=_industry_capital_route(focus),
                        source="industry_capital",
                        source_id=f"{focus.id}-official",
                        created_at=now,
                    )
                )

        composite_compare = _build_composite_compare(days=5)
        readiness = composite_compare.readiness
        if readiness.status in {"shadow", "pilot", "hold", "ready"}:
            takeover_level = "info"
            if readiness.status in {"shadow", "hold"}:
                takeover_level = "warning"
            items.append(
                ActionBoardItem(
                    id="action-takeover-composite",
                    kind="takeover",
                    level=takeover_level,
                    title=f"综合榜 {readiness.label}",
                    summary=f"{readiness.summary} 下一步：{readiness.recommended_action}",
                    action_label="看接管判断",
                    route="/(tabs)/signals",
                    source="composite_compare",
                    source_id=readiness.status,
                    created_at=now,
                )
            )

        daily_advance = _build_learning_advance_status()
        if not daily_advance.today_completed:
            items.append(
                ActionBoardItem(
                    id="action-learning-daily-advance",
                    kind="learning",
                    level="warning",
                    title="日日精进今天还没跑完",
                    summary=daily_advance.summary,
                    action_label="去决策台",
                    route="/(tabs)/brain",
                    source="learning",
                    source_id="daily-advance",
                    created_at=daily_advance.last_started_at or now,
                )
            )

        items.sort(
            key=lambda item: (_action_priority(item.level, item.kind), str(item.created_at)),
            reverse=False,
        )
        return items[: max(1, min(limit, 12))]

    return _cached_runtime_value(
        "action_board",
        limit,
        ttl_seconds=6,
        dependency_paths=_runtime_cache_paths(
            _PAPER_POSITIONS,
            _APP_MESSAGE_CENTER,
            _INDUSTRY_CAPITAL_RESEARCH_LOG,
            _LEARNING_DAILY_ADVANCE,
            _NEWS_DIGEST,
            _POLICY_DIRECTION_CATALOG,
            _POLICY_OFFICIAL_WATCH,
            _POLICY_OFFICIAL_CARDS,
            _POLICY_EXECUTION_TIMELINE,
            _INDUSTRY_CAPITAL_COMPANY_MAP,
            _SECTOR_ALERTS,
            _SIGNAL_TRACKER,
            _PUSH_STATE,
            os.path.join(_DIR, "signals_db.json"),
            *_db_dependency_paths(),
        ),
        builder=builder,
    )


def _build_takeover_message() -> Optional[dict]:
    compare = _build_composite_compare(days=5)
    readiness = compare.readiness
    composite_picks = _build_composite_picks(days=1, limit=1)
    top_pick = composite_picks[0] if composite_picks else None

    title = f"综合榜 {readiness.label}"
    detail = readiness.summary
    if top_pick:
        detail = (
            f"{detail} 当前头部候选是 {top_pick.code} {top_pick.name}，"
            f"{top_pick.setup_label}，建议首仓 {top_pick.first_position_pct}% 。"
        )
    body = f"{detail} 下一步：{readiness.recommended_action}"
    level = "info"
    if readiness.status in {"shadow", "hold"}:
        level = "warning"
    elif readiness.status == "ready":
        level = "success"

    return _normalize_app_message(
        {
            "id": f"msg_takeover_{readiness.status}",
            "title": title,
            "body": body,
            "preview": body[:140],
            "level": level,
            "channel": "system_push",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
    )


def _takeover_fingerprint(message: dict) -> str:
    return hashlib.sha1(
        json.dumps(
            {
                "title": message.get("title"),
                "body": message.get("body"),
                "preview": message.get("preview"),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]


def _takeover_auto_cooldown_remaining(push_state: dict) -> int:
    last_auto_run_at = _parse_datetime(push_state.get("last_takeover_auto_run_at"))
    if last_auto_run_at is None:
        return 0

    elapsed = int((datetime.now() - last_auto_run_at).total_seconds())
    remaining = _TAKEOVER_AUTO_COOLDOWN_SECONDS - elapsed
    return remaining if remaining > 0 else 0


def _build_takeover_push_status(user: AppUser) -> TakeoverPushStatus:
    message = _build_takeover_message()
    if not message:
        raise HTTPException(status_code=404, detail="当前没有可用的接管判断")

    registry = _load_push_registry()
    active_device_entries = _active_push_devices(registry, user.username)
    active_devices = len(active_device_entries)
    push_state = _load_push_state()
    fingerprint = _takeover_fingerprint(message)
    last_sent_fingerprint = push_state.get("last_takeover_fingerprint")
    synced_devices = sum(
        1 for device in active_device_entries if device.get("last_takeover_fingerprint") == fingerprint
    )
    pending_devices = max(active_devices - synced_devices, 0)
    should_send = pending_devices > 0
    readiness_label = str(message.get("title") or "综合榜 接管判断").replace("综合榜 ", "", 1)
    auto_enabled = bool(push_state.get("takeover_auto_enabled", False))
    auto_cooldown_seconds = _takeover_auto_cooldown_remaining(push_state)
    auto_ready = auto_enabled and should_send and auto_cooldown_seconds == 0
    display_auto_cooldown_seconds = auto_cooldown_seconds if auto_enabled else 0

    if active_devices == 0:
        delivery_state = "no_device"
        summary = "当前还没有远程推送设备，先在真机点一次“同步远程推送”。"
        recommended_action = "先同步远程推送，再考虑真发。"
    elif last_sent_fingerprint == fingerprint and pending_devices > 0:
        delivery_state = "pending_devices"
        summary = f"当前判断没变，但还有 {pending_devices} 台活跃设备没收到这一版接管判断。"
        recommended_action = "可以先预演，再把当前判断补发给新设备。"
    elif should_send:
        delivery_state = "pending_update"
        summary = f"当前接管判断相对上次已变化，{pending_devices} 台活跃设备待更新。"
        recommended_action = "可以先预演，再决定是否真实下发。"
    else:
        delivery_state = "synced"
        summary = f"当前接管判断已经覆盖全部 {active_devices} 台活跃设备，没有必要重复打扰。"
        recommended_action = "继续观察，等判断变化后再发。"

    return TakeoverPushStatus(
        title=str(message.get("title") or "综合榜 接管判断"),
        body=str(message.get("body") or ""),
        readiness_label=readiness_label,
        fingerprint=fingerprint,
        active_devices=active_devices,
        synced_devices=synced_devices,
        pending_devices=pending_devices,
        delivery_state=delivery_state,
        should_send=should_send,
        summary=summary,
        recommended_action=recommended_action,
        auto_enabled=auto_enabled,
        auto_ready=auto_ready,
        auto_cooldown_seconds=display_auto_cooldown_seconds,
        last_sent_at=push_state.get("last_takeover_sent_at"),
        last_sent_status=push_state.get("last_takeover_sent_status"),
        last_sent_fingerprint=last_sent_fingerprint,
        last_preview_at=push_state.get("last_takeover_preview_at"),
        last_auto_run_at=push_state.get("last_takeover_auto_run_at"),
        last_auto_run_status=push_state.get("last_takeover_auto_run_status"),
    )


def _build_industry_research_push_status(user: AppUser) -> IndustryResearchPushStatus:
    registry = _load_push_registry()
    active_devices = len(_active_push_devices(registry, user.username))
    push_state = _load_push_state()
    auto_enabled = bool(push_state.get("takeover_auto_enabled", False))
    last_sent_at = push_state.get("last_industry_research_sent_at")
    last_sent_status = push_state.get("last_industry_research_sent_status")

    messages = _build_app_messages(limit=24)
    latest_message = next(
        (
            item
            for item in messages
            if item.channel == "system_update" and (item.route or "").startswith("/industry-capital/")
        ),
        None,
    )
    directions = _build_industry_capital_map(limit=1)
    latest_direction = directions[0] if directions else None

    if active_devices == 0:
        delivery_state = "no_device"
        summary = "当前没有可用的远程推送设备。方向变化消息已经会写进消息中心，但还推不到真机。"
        recommended_action = "先在真机点一次“同步远程推送”，后续方向变化才会自动补发到设备。"
    elif last_sent_at:
        delivery_state = "active"
        summary = "方向变化推送链已经可用，后续调研回写会自动尝试把变化下发到当前账号设备。"
        recommended_action = "继续回写真实调研，重点看方向信号变化和优先级变化是否及时同步到设备。"
    else:
        delivery_state = "ready"
        summary = "设备已就绪，但还没有发生过一次方向变化推送。下一条调研回写将触发自动尝试下发。"
        recommended_action = "继续回写一条真实调研，验证方向变化消息是否会自动推到真机。"

    return IndustryResearchPushStatus(
        title="产业资本方向推送状态",
        latest_title=latest_message.title if latest_message else None,
        latest_preview=latest_message.preview if latest_message else None,
        latest_direction=latest_direction.direction if latest_direction else None,
        latest_timeline_stage=latest_direction.current_timeline_stage if latest_direction else None,
        latest_catalyst_title=latest_direction.latest_catalyst_title if latest_direction else None,
        active_devices=active_devices,
        delivery_state=delivery_state,
        auto_enabled=auto_enabled,
        summary=summary,
        recommended_action=recommended_action,
        last_sent_at=last_sent_at,
        last_sent_status=last_sent_status,
    )


def _build_learning_progress() -> LearningProgress:
    learning = safe_load(_LEARNING_STATE, default={})
    memory = safe_load(_AGENT_MEMORY, default={})

    return LearningProgress(
        today_cycles=learning.get("today_cycles", 0),
        factor_adjustments=learning.get("factor_adjustments", 0),
        online_updates=learning.get("online_updates", 0),
        experiments_running=learning.get("experiments_running", 0),
        new_factors_deployed=learning.get("new_factors_deployed", 0),
        decision_accuracy=memory.get("decision_accuracy", 0.68),
    )


def _learning_advance_state_snapshot() -> dict:
    with _LEARNING_ADVANCE_LOCK:
        return dict(_LEARNING_ADVANCE_STATE)


def _persist_learning_advance_state(**updates: object) -> dict:
    with _LEARNING_ADVANCE_LOCK:
        _LEARNING_ADVANCE_STATE.update(updates)
        snapshot = dict(_LEARNING_ADVANCE_STATE)
        safe_save(_LEARNING_DAILY_ADVANCE, snapshot)
        return snapshot


def _build_learning_health_snapshot() -> dict:
    learning = safe_load(_LEARNING_STATE, default={})
    health = learning.get("health")
    if isinstance(health, dict) and health:
        return health
    return safe_load(os.path.join(_DIR, "learning_health.json"), default={})


def _summarize_regime(regime: str, score: float) -> str:
    if regime == "bull":
        return f"市场偏多，环境分 {round(score * 100, 1)}，顺势交易容错更高。"
    if regime == "bear":
        return f"市场偏弱，环境分 {round(score * 100, 1)}，更适合防守和轻仓。"
    return f"市场中性，环境分 {round(score * 100, 1)}，诊股结果要和量能一起看。"


def _confidence_label(total_score: float, actionable: bool) -> str:
    if actionable and total_score >= 0.8:
        return "高置信"
    if actionable and total_score >= 0.65:
        return "可跟踪"
    if total_score <= 0.35:
        return "风险偏高"
    return "观察单"


def _build_stock_diagnosis(code: str) -> StockDiagnosis:
    normalized_code = str(code).strip()
    if not normalized_code.isdigit() or len(normalized_code) != 6:
        raise HTTPException(status_code=400, detail="诊股代码必须是 6 位数字")

    from stock_analyzer import analyze_stock

    try:
        raw = analyze_stock(normalized_code, push=False, journal=False)
    except Exception as exc:
        logger.exception("诊股引擎执行失败 %s", normalized_code)
        raise HTTPException(status_code=500, detail=f"诊股引擎异常: {exc}") from exc
    if raw.get("error"):
        raise HTTPException(status_code=502, detail=str(raw["error"]))

    try:
        from smart_trader import detect_market_regime

        regime_payload = detect_market_regime() or {}
    except Exception as exc:
        logger.warning("市场环境检测失败 %s: %s", normalized_code, exc)
        regime_payload = {}

    regime = str(regime_payload.get("regime", "neutral"))
    regime_score = _to_float(regime_payload.get("score")) or 0.5
    system = _build_system_status()
    learning = _build_learning_progress()
    strategies = sorted(
        _build_strategies(),
        key=lambda item: (item.signal_count, item.win_rate, item.avg_return),
        reverse=True,
    )
    top_strategy = strategies[0] if strategies else None
    live_signals = _build_signals()
    portfolio = _load_portfolio()
    positions = portfolio.get("positions", [])
    held_position = next(
        (
            position
            for position in positions
            if isinstance(position, dict) and str(position.get("code", "")) == normalized_code
        ),
        None,
    )

    risk_flags: list[str] = []
    scores = raw.get("scores", {})
    if raw.get("total_score", 0) < 0.65:
        risk_flags.append("综合评分还没穿透到强信号阈值，先观察比直接出手更稳。")
    if regime == "bear":
        risk_flags.append("当前市场环境偏弱，再好的单票也要控制仓位。")
    if (_to_float(scores.get("volume")) or 0) < 0.35:
        risk_flags.append("量能不足，突破延续性可能不够。")
    if (_to_float(scores.get("fund_flow")) or 0) < 0.35:
        risk_flags.append("资金面偏弱，盘中回撤时容易放大波动。")
    if system.health_score < 80:
        risk_flags.append("系统健康分偏低，优先确认数据链和调度链稳定。")
    if learning.decision_accuracy < 0.65:
        risk_flags.append("近期决策准确率一般，诊股结果要结合人工复核。")
    if not risk_flags:
        risk_flags.append("当前没有明显的系统性风险项，但仍要按止损执行。")

    next_actions = []
    if raw.get("actionable"):
        next_actions.append("先看开盘后量价是否继续配合，再决定是否执行。")
        if raw.get("stop_loss") is not None:
            next_actions.append(f"若参与，止损先盯 {raw['stop_loss']:.2f}，不要拖成情绪单。")
        if raw.get("take_profit") is not None:
            next_actions.append(f"目标位先看 {raw['take_profit']:.2f}，盈利后再谈加仓。")
    else:
        next_actions.append("先列入观察池，不把诊股结果直接当交易指令。")
        next_actions.append("等评分、量能或资金面再确认一轮，再看是否升级成可交易信号。")

    if held_position:
        next_actions.append("这只票已在持仓里，先按持仓风控处理，不重复开仓。")

    health_bias = (
        "系统健康和学习链当前都在线，这份诊股可以当成可执行前的前置判断。"
        if system.health_score >= 80 and learning.decision_accuracy >= 0.65
        else "诊股本身可看，但系统健康或学习准确率偏弱，适合轻仓和人工复核。"
    )

    return StockDiagnosis(
        code=normalized_code,
        name=str(raw.get("name", normalized_code)),
        price=float(raw.get("price", 0.0) or 0.0),
        as_of=_iso_now(),
        total_score=float(raw.get("total_score", 0.0) or 0.0),
        verdict=str(raw.get("verdict", "")),
        direction=str(raw.get("direction", "neutral")),
        signal_direction=str(raw.get("signal_direction", "neutral")),
        actionable=bool(raw.get("actionable", False)),
        confidence_label=_confidence_label(float(raw.get("total_score", 0.0) or 0.0), bool(raw.get("actionable", False))),
        advice=str(raw.get("advice", "")),
        report_text=str(raw.get("report_text", "")),
        stop_loss=_to_float(raw.get("stop_loss")),
        take_profit=_to_float(raw.get("take_profit")),
        scores={str(key): float(value) for key, value in raw.get("scores", {}).items()},
        details={
            str(key): [str(item) for item in value]
            for key, value in raw.get("details", {}).items()
            if isinstance(value, list)
        },
        regime=regime,
        regime_score=regime_score,
        regime_summary=_summarize_regime(regime, regime_score),
        health_bias=health_bias,
        in_portfolio=held_position is not None,
        position_quantity=_to_int(held_position.get("quantity")) if isinstance(held_position, dict) else 0,
        position_profit_loss_pct=_to_float(held_position.get("profit_loss_pct")) if isinstance(held_position, dict) else None,
        in_signal_board=any(signal.code == normalized_code for signal in live_signals),
        top_strategy=top_strategy.name if top_strategy else None,
        top_strategy_win_rate=top_strategy.win_rate if top_strategy else None,
        top_strategy_avg_return=top_strategy.avg_return if top_strategy else None,
        risk_flags=risk_flags[:4],
        next_actions=next_actions[:4],
    )


def _build_learning_advance_status() -> LearningAdvanceStatus:
    progress = _build_learning_progress()
    health = _build_learning_health_snapshot()
    state = _learning_advance_state_snapshot()
    last_completed_at = state.get("last_completed_at")
    completed_at = _parse_datetime(last_completed_at)
    stale_hours = None
    if completed_at is not None:
        stale_hours = round((datetime.now() - completed_at).total_seconds() / 3600, 1)

    today_completed = bool(last_completed_at and str(last_completed_at).startswith(date.today().isoformat()))
    health_status = str(health.get("status", "unknown"))
    checks = [
        LearningAdvanceCheck(
            name=str(check.get("check", "unknown")),
            status=str(check.get("status", "unknown")),
            detail=str(check.get("detail", "")),
        )
        for check in health.get("checks", [])[:6]
        if isinstance(check, dict)
    ]

    recommendations: list[str] = []
    if state.get("in_progress"):
        recommendations.append("日日精进任务正在跑，先等本轮落盘完成再看结论。")
    elif not today_completed:
        recommendations.append("今天还没有完成日日精进，建议手动触发一次完整学习。")
    if progress.today_cycles < 3:
        recommendations.append("今日学习轮次偏少，至少补到 3 轮再观察准确率。")
    if health_status == "critical":
        recommendations.append("学习健康已到 critical，先修数据源和模型新鲜度。")
    elif health_status == "warning":
        recommendations.append("学习链有 warning，先处理告警项再放大学习节奏。")
    if progress.decision_accuracy < 0.65:
        recommendations.append("当前决策准确率偏弱，优先复盘最近一周错误样本。")
    if stale_hours is not None and stale_hours > 30:
        recommendations.append("上次日日精进已经过久，说明学习节奏断了。")
    if not recommendations:
        recommendations.append("学习链当前在线，继续按日推进并盯住新验证样本。")

    if state.get("in_progress"):
        summary = "日日精进任务正在运行，本轮会顺带做信号验证、决策回查和学习周期。"
        status = "running"
    elif state.get("status") == "failed":
        summary = state.get("last_error") or "上一轮日日精进失败，需要先看错误信息。"
        status = "failed"
    elif health_status == "critical":
        summary = "学习链已经进入 critical，先稳住健康项，再谈提效。"
        status = "critical"
    elif not today_completed:
        summary = "今天还没完成完整学习，系统还不算真正进入日日精进状态。"
        status = "pending"
    else:
        summary = (
            f"最近一次日日精进已完成，今日学习 {progress.today_cycles} 轮，"
            f"准确率 {round(progress.decision_accuracy * 100, 1)}%。"
        )
        status = "healthy" if health_status == "ok" else "warning"

    return LearningAdvanceStatus(
        status=status,
        in_progress=bool(state.get("in_progress")),
        today_completed=today_completed,
        last_started_at=state.get("last_started_at"),
        current_run_started_at=state.get("current_run_started_at"),
        last_completed_at=last_completed_at,
        last_requested_by=state.get("last_requested_by"),
        stale_hours=stale_hours,
        health_status=health_status,
        summary=summary,
        last_error=state.get("last_error"),
        last_report_excerpt=str(state.get("last_report_excerpt", "")),
        ingested_signals=_to_int(state.get("last_ingested_signals")),
        verified_signals=_to_int(state.get("last_verified_signals")),
        reviewed_decisions=_to_int(state.get("last_reviewed_decisions")),
        checks=checks,
        recommendations=recommendations[:4],
    )


def _build_ops_recommendations(
    *,
    ready: bool,
    readiness_issues: list[str],
    error_rate: float,
    p95_latency_ms: float,
    system_health_score: int,
    data_status: OpsDataStatus,
    learning: LearningProgress,
    daily_advance: LearningAdvanceStatus,
) -> list[OpsRecommendation]:
    recommendations: list[OpsRecommendation] = []

    if not ready or readiness_issues:
        recommendations.append(
            OpsRecommendation(
                level="critical",
                title="先修就绪问题",
                message=f"readiness 未完全通过，当前核心问题是 {readiness_issues[0] if readiness_issues else '未知异常'}。",
            )
        )
    if error_rate >= 0.03 or p95_latency_ms >= 1200:
        recommendations.append(
            OpsRecommendation(
                level="warning",
                title="接口延迟或错误偏高",
                message=f"当前错误率 {round(error_rate * 100, 2)}%，P95 延迟 {round(p95_latency_ms)}ms，建议优先查热点路由。",
            )
        )
    if system_health_score < 80:
        recommendations.append(
            OpsRecommendation(
                level="warning",
                title="系统健康分偏低",
                message=f"健康分只有 {system_health_score}，先确认数据采集、调度和仓位风控链。",
            )
        )
    if data_status.scorecard_records == 0 or data_status.trade_journal_records == 0:
        recommendations.append(
            OpsRecommendation(
                level="warning",
                title="学习输入不足",
                message="scorecard 或 trade_journal 数据偏少，学习链会缺少真实反馈样本。",
            )
        )
    if learning.today_cycles < 3 or not daily_advance.today_completed:
        recommendations.append(
            OpsRecommendation(
                level="info",
                title="今日学习还没打满",
                message="当前学习轮次不足或日日精进未完成，建议至少补到 3 轮并完成一次完整学习。",
            )
        )
    if learning.decision_accuracy < 0.65:
        recommendations.append(
            OpsRecommendation(
                level="warning",
                title="准确率需要复盘",
                message=f"当前决策准确率 {round(learning.decision_accuracy * 100, 1)}%，说明模型和规则还要继续校正。",
            )
        )

    if not recommendations:
        recommendations.append(
            OpsRecommendation(
                level="success",
                title="系统当前在线",
                message="活性、就绪、学习和数据链都处在可工作的区间，可以继续盯交易与回测样本。",
            )
        )

    return recommendations[:4]


def _run_learning_daily_advance(requested_by: str) -> None:
    last_error: Optional[str] = None
    status = "healthy"
    report_excerpt = ""
    ingested = 0
    verified = 0
    reviewed = 0
    summary_parts: list[str] = []

    try:
        try:
            from signal_tracker import ingest_from_journal, verify_outcomes

            ingested = int(ingest_from_journal() or 0)
            verify_result = verify_outcomes() or {}
            verified = _to_int(verify_result.get("verified"))
            summary_parts.append(f"新增信号 {ingested} 条")
            summary_parts.append(f"完成验证点 {verified} 个")
        except Exception as exc:
            logger.exception("日日精进: 信号验证阶段失败")
            last_error = f"信号验证阶段失败: {exc}"
            status = "warning"
            summary_parts.append("信号验证阶段未完整完成")

        try:
            from agent_brain import verify_past_decisions

            decision_reviews = verify_past_decisions() or []
            reviewed = len(decision_reviews)
            summary_parts.append(f"回查历史决策 {reviewed} 条")
        except Exception as exc:
            logger.exception("日日精进: 决策回查阶段失败")
            if last_error is None:
                last_error = f"决策回查阶段失败: {exc}"
            status = "warning" if status != "failed" else status
            summary_parts.append("决策回查阶段未完整完成")

        try:
            from learning_engine import run_learning_cycle

            report = run_learning_cycle() or ""
            report_excerpt = " ".join(line.strip() for line in report.splitlines() if line.strip())[:240]
            summary_parts.append("学习周期已执行")
        except Exception as exc:
            logger.exception("日日精进: 学习周期失败")
            last_error = f"学习周期失败: {exc}"
            status = "failed"
            summary_parts.append("学习周期执行失败")

        health = _build_learning_health_snapshot()
        health_status = str(health.get("status", "unknown"))
        if status != "failed" and health_status == "critical":
            status = "critical"
        elif status == "healthy" and health_status == "warning":
            status = "warning"
    except Exception as exc:
        logger.exception("日日精进: 任务收口失败")
        last_error = f"日日精进任务异常中断: {exc}"
        status = "failed"
        summary_parts.append("日日精进任务异常中断")
    finally:
        summary = "；".join(summary_parts) if summary_parts else "日日精进完成"
        _persist_learning_advance_state(
            status=status,
            in_progress=False,
            current_run_started_at=None,
            last_completed_at=_iso_now(),
            last_requested_by=requested_by,
            last_error=last_error,
            last_result_summary=summary,
            last_report_excerpt=report_excerpt,
            last_ingested_signals=ingested,
            last_verified_signals=verified,
            last_reviewed_decisions=reviewed,
        )


def _start_learning_daily_advance(user: AppUser) -> LearningAdvanceStatus:
    state = _learning_advance_state_snapshot()
    if state.get("in_progress"):
        return _build_learning_advance_status()

    started_at = _iso_now()
    _persist_learning_advance_state(
        status="running",
        in_progress=True,
        last_started_at=started_at,
        current_run_started_at=started_at,
        last_requested_by=user.username,
        last_error=None,
        last_result_summary="日日精进任务已启动",
        last_report_excerpt="",
    )

    worker = Thread(target=_run_learning_daily_advance, args=(user.username,), daemon=True)
    worker.start()
    return _build_learning_advance_status()


def _build_ops_data_status() -> OpsDataStatus:
    portfolio = _load_portfolio()
    positions = portfolio.get("positions", [])
    registry = _load_push_registry()
    feedback_box = _load_feedback_box()
    scorecard = load_scorecard()
    trade_journal = load_trade_journal()

    return OpsDataStatus(
        scorecard_records=len(scorecard) if isinstance(scorecard, list) else 0,
        trade_journal_records=len(trade_journal) if isinstance(trade_journal, list) else 0,
        signal_count=len(_build_signals()),
        active_positions=len(
            [
                position
                for position in positions
                if isinstance(position, dict) and _to_int(position.get("quantity")) > 0
            ]
        ),
        feedback_items=len(feedback_box.get("items", [])),
        push_devices=len(
            [
                device
                for device in registry.get("devices", [])
                if isinstance(device, dict) and device.get("status", "active") == "active"
            ]
        ),
    )


def _readiness_snapshot() -> tuple[bool, list[str]]:
    checks = [
        ("system", _build_system_status),
        ("signals", _build_signals),
        ("positions", _build_positions),
        ("learning", _build_learning_progress),
        ("push_registry", _load_push_registry),
        ("feedback_box", _load_feedback_box),
    ]
    issues: list[str] = []

    for name, check in checks:
        try:
            check()
        except Exception as exc:
            issues.append(f"{name}: {exc}")

    return len(issues) == 0, issues


def _build_ops_summary() -> OpsSummary:
    ready, readiness_issues = _readiness_snapshot()
    system = _build_system_status()
    data_status = _build_ops_data_status()
    learning = _build_learning_progress()
    daily_advance = _build_learning_advance_status()

    with _OPS_LOCK:
        request_count = int(_OPS_STATE["request_count"])
        error_count = int(_OPS_STATE["error_count"])
        total_latency_ms = float(_OPS_STATE["total_latency_ms"])
        max_latency_ms = float(_OPS_STATE["max_latency_ms"])
        latencies_ms = list(_OPS_STATE["latencies_ms"])
        routes = list(_OPS_STATE["routes"].values())
        last_error_at = _OPS_STATE["last_error_at"]
        last_error_path = _OPS_STATE["last_error_path"]

    avg_latency_ms = round(total_latency_ms / request_count, 2) if request_count else 0
    error_rate = round(error_count / request_count, 4) if request_count else 0
    p95_latency_ms = round(_percentile(latencies_ms, 0.95), 2) if latencies_ms else 0

    route_items = [
        OpsRouteStat(
            method=str(route.get("method", "GET")),
            path=str(route.get("path", "/")),
            count=int(route.get("count", 0)),
            error_count=int(route.get("error_count", 0)),
            avg_latency_ms=round(
                float(route.get("total_latency_ms", 0.0)) / max(int(route.get("count", 0)), 1),
                2,
            ),
            max_latency_ms=round(float(route.get("max_latency_ms", 0.0)), 2),
            last_status=int(route.get("last_status", 0)),
            last_seen_at=route.get("last_seen_at"),
        )
        for route in routes
    ]
    route_items.sort(key=lambda item: (item.error_count, item.count), reverse=True)

    return OpsSummary(
        service="Alpha AI Trading API",
        version="1.0.0",
        started_at=_RUNTIME_STARTED_AT.isoformat(),
        uptime_seconds=max(0, int((datetime.now() - _RUNTIME_STARTED_AT).total_seconds())),
        ready=ready,
        readiness_issues=readiness_issues,
        request_count=request_count,
        error_count=error_count,
        error_rate=error_rate,
        avg_latency_ms=avg_latency_ms,
        max_latency_ms=round(max_latency_ms, 2),
        p95_latency_ms=p95_latency_ms,
        last_error_at=last_error_at,
        last_error_path=last_error_path,
        websocket_connections=len(manager.active_connections),
        system_status=system.status,
        system_health_score=system.health_score,
        today_signals=system.today_signals,
        active_strategies=system.active_strategies,
        data_status=data_status,
        routes=route_items[:8],
        recommendations=_build_ops_recommendations(
            ready=ready,
            readiness_issues=readiness_issues,
            error_rate=error_rate,
            p95_latency_ms=p95_latency_ms,
            system_health_score=system.health_score,
            data_status=data_status,
            learning=learning,
            daily_advance=daily_advance,
        ),
    )


def _render_metrics_text() -> str:
    summary = _build_ops_summary()
    lines = [
        "# HELP alpha_api_ready Readiness state of the API process.",
        "# TYPE alpha_api_ready gauge",
        f"alpha_api_ready {1 if summary.ready else 0}",
        "# HELP alpha_api_requests_total Total HTTP requests handled by the API process.",
        "# TYPE alpha_api_requests_total counter",
        f"alpha_api_requests_total {summary.request_count}",
        "# HELP alpha_api_request_errors_total Total HTTP 5xx responses or unhandled errors.",
        "# TYPE alpha_api_request_errors_total counter",
        f"alpha_api_request_errors_total {summary.error_count}",
        "# HELP alpha_api_request_latency_ms_avg Average request latency in milliseconds.",
        "# TYPE alpha_api_request_latency_ms_avg gauge",
        f"alpha_api_request_latency_ms_avg {summary.avg_latency_ms}",
        "# HELP alpha_api_request_latency_ms_p95 Recent p95 request latency in milliseconds.",
        "# TYPE alpha_api_request_latency_ms_p95 gauge",
        f"alpha_api_request_latency_ms_p95 {summary.p95_latency_ms}",
        "# HELP alpha_api_websocket_connections Current websocket connection count.",
        "# TYPE alpha_api_websocket_connections gauge",
        f"alpha_api_websocket_connections {summary.websocket_connections}",
        "# HELP alpha_api_system_health_score Trading system health score.",
        "# TYPE alpha_api_system_health_score gauge",
        f"alpha_api_system_health_score {summary.system_health_score}",
        "# HELP alpha_api_today_signals Current trade-day signal count.",
        "# TYPE alpha_api_today_signals gauge",
        f"alpha_api_today_signals {summary.today_signals}",
    ]

    for route in summary.routes:
        method = route.method.replace('"', '\\"')
        path = route.path.replace('"', '\\"')
        lines.append(
            f'alpha_api_route_requests_total{{method="{method}",path="{path}"}} {route.count}'
        )
        lines.append(
            f'alpha_api_route_errors_total{{method="{method}",path="{path}"}} {route.error_count}'
        )
        lines.append(
            f'alpha_api_route_latency_ms_avg{{method="{method}",path="{path}"}} {route.avg_latency_ms}'
        )

    return "\n".join(lines) + "\n"

# ================================================================
#  API Endpoints
# ================================================================

@app.get("/")
def root():
    return {"message": "Alpha AI Trading API", "version": "1.0.0"}


@app.get("/health/live")
def get_liveness():
    return {
        "status": "live",
        "service": "Alpha AI Trading API",
        "started_at": _RUNTIME_STARTED_AT.isoformat(),
        "timestamp": _iso_now(),
    }


@app.get("/health/ready")
def get_readiness():
    ready, issues = _readiness_snapshot()
    payload = {
        "status": "ready" if ready else "degraded",
        "service": "Alpha AI Trading API",
        "timestamp": _iso_now(),
        "issues": issues,
    }
    if ready:
        return payload
    return JSONResponse(status_code=503, content=payload)


@app.get("/metrics", response_class=PlainTextResponse)
def get_metrics():
    return _render_metrics_text()


@app.get("/api/ops/summary", response_model=OpsSummary)
def get_ops_summary():
    return _build_ops_summary()


@app.post("/api/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    account = _resolve_app_account(payload.username)
    valid_passwords = set(account.get("legacy_passwords", [])) if account else set()
    if account is not None:
        valid_passwords.add(str(account.get("password", "")))
    if account is None or payload.password not in valid_passwords:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    access_token, expires_at = _create_access_token(payload.username)
    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_at=expires_at.isoformat(),
        user=AppUser(
            username=payload.username,
            display_name=account.get("display_name", _APP_AUTH_DISPLAY_NAME),
            role=account.get("role", "pilot"),
        ),
    )


@app.get("/api/auth/me", response_model=AppUser)
def get_me(user: AppUser = Depends(_require_app_user)):
    return user


@app.get("/api/system", response_model=SystemStatus)
def get_system_status():
    """系统状态"""
    return _build_system_status()

@app.get("/api/strategies", response_model=list[StrategyPerformance])
def get_strategies():
    """策略表现列表"""
    return _build_strategies()

@app.get("/api/signals", response_model=list[Signal])
def get_signals(days: int = 1):
    """信号列表 (默认今日)"""
    return _build_signals(days)

@app.get("/api/signals/{signal_id}", response_model=SignalDetail)
def get_signal_detail(signal_id: str):
    """信号详情"""
    return _build_signal_detail(signal_id)

@app.get("/api/strong-moves", response_model=list[StrongMoveCandidate])
def get_strong_moves(days: int = 1, limit: int = 5):
    """强势股与波段候选"""
    return _build_strong_moves(days=days, limit=limit)

@app.get("/api/composite-picks", response_model=list[CompositePick])
def get_composite_picks(days: int = 1, limit: int = 5):
    """事件、资金、策略综合候选池（影子模式）"""
    return _build_composite_picks(days=days, limit=limit)

@app.get("/api/composite-replay", response_model=list[CompositeReplayItem])
def get_composite_replay(days: int = 5, per_day: int = 1):
    """综合推荐榜连续观察回放（影子模式）"""
    return _build_composite_replay(days=days, per_day=per_day)

@app.get("/api/composite-compare", response_model=RecommendationCompareSnapshot)
def get_composite_compare(days: int = 5):
    """综合推荐榜 vs 原推荐榜对比（影子模式）"""
    return _build_composite_compare(days=days)

@app.get("/api/positioning-plan", response_model=PositioningPlan)
def get_positioning_plan(days: int = 1):
    """仓位、分仓与防守建议（影子模式）"""
    return _build_positioning_plan(days=days)

@app.get("/api/theme-radar", response_model=list[ThemeRadarItem])
def get_theme_radar(limit: int = 3):
    """主题资金迁移与板块异动"""
    return _build_theme_radar(limit=limit)


@app.get("/api/theme-stage", response_model=list[ThemeStageItem])
def get_theme_stage(limit: int = 3):
    """主线发现与阶段引擎（影子模式）"""
    return _build_theme_stage_engine(limit=limit)


@app.get("/api/policy-watch", response_model=list[PolicyWatchItem])
def get_policy_watch(limit: int = 3):
    """政策方向雷达（影子模式）"""
    return _build_policy_watch(limit=limit)


@app.get("/api/industry-capital", response_model=list[IndustryCapitalDirection])
def get_industry_capital(limit: int = 3):
    """产业资本方向中枢（影子模式）"""
    return _build_industry_capital_map(limit=limit)


@app.get("/api/industry-capital/{direction_id}", response_model=IndustryCapitalDirection)
def get_industry_capital_detail(direction_id: str):
    """产业资本方向详情"""
    return _build_industry_capital_detail(direction_id)

@app.get("/api/industry-capital/{direction_id}/research-log", response_model=list[IndustryCapitalResearchItem])
def get_industry_capital_research_log(direction_id: str, limit: int = 12):
    """产业资本方向调研记录"""
    return _list_industry_capital_research_items(direction_id, limit=limit)

@app.get("/api/positions", response_model=list[Position])
def get_positions():
    """持仓列表"""
    return _build_positions()

@app.get("/api/positions/{code}", response_model=PositionDetail)
def get_position_detail(code: str):
    """持仓详情"""
    return _build_position_detail(code)

@app.get("/api/market/{code}/kline", response_model=list[KlineBar])
def get_kline(code: str, days: int = 60):
    """历史K线"""
    return _build_kline_bars(code, days)

@app.get("/api/alerts", response_model=list[RiskAlert])
def get_alerts():
    """风险提醒"""
    return _build_risk_alerts()

@app.get("/api/messages", response_model=list[AppMessage])
def get_app_messages_public(limit: int = 30):
    """APP 消息中心（微信推送镜像）"""
    return _build_app_messages(limit)

@app.get("/api/action-board", response_model=list[ActionBoardItem])
def get_action_board(limit: int = 6):
    """首页/消息中心统一待办看板"""
    return _build_action_board(limit)

@app.get("/api/diagnosis/{code}", response_model=StockDiagnosis)
def get_stock_diagnosis(code: str):
    """个股诊断"""
    return _build_stock_diagnosis(code)

@app.get("/api/learning", response_model=LearningProgress)
def get_learning_progress():
    """学习进度"""
    return _build_learning_progress()


@app.get("/api/learning/daily-advance", response_model=LearningAdvanceStatus)
def get_learning_daily_advance():
    """日日精进状态"""
    return _build_learning_advance_status()


@app.get("/api/portfolio/history", response_model=PortfolioHistory)
def get_portfolio_history():
    """组合历史与最近动作"""
    return _build_portfolio_history()


@app.get("/api/app/bootstrap", response_model=AppBootstrap)
def get_app_bootstrap(user: AppUser = Depends(_require_app_user)):
    return AppBootstrap(
        user=user,
        system=_build_system_status(),
        strategies=_build_strategies(),
        signals=_build_signals(),
        positions=_build_positions(),
        learning=_build_learning_progress(),
    )


@app.get("/api/app/system", response_model=SystemStatus)
def get_app_system(user: AppUser = Depends(_require_app_user)):
    return _build_system_status()


@app.get("/api/app/ops/summary", response_model=OpsSummary)
def get_app_ops_summary(user: AppUser = Depends(_require_app_user)):
    return _build_ops_summary()


@app.get("/api/app/strategies", response_model=list[StrategyPerformance])
def get_app_strategies(user: AppUser = Depends(_require_app_user)):
    return _build_strategies()


@app.get("/api/app/signals", response_model=list[Signal])
def get_app_signals(days: int = 1, user: AppUser = Depends(_require_app_user)):
    return _build_signals(days)

@app.get("/api/app/signals/{signal_id}", response_model=SignalDetail)
def get_app_signal_detail(signal_id: str, user: AppUser = Depends(_require_app_user)):
    return _build_signal_detail(signal_id)

@app.get("/api/app/strong-moves", response_model=list[StrongMoveCandidate])
def get_app_strong_moves(
    days: int = 1,
    limit: int = 5,
    user: AppUser = Depends(_require_app_user),
):
    return _build_strong_moves(days=days, limit=limit)

@app.get("/api/app/composite-picks", response_model=list[CompositePick])
def get_app_composite_picks(
    days: int = 1,
    limit: int = 5,
    user: AppUser = Depends(_require_app_user),
):
    return _build_composite_picks(days=days, limit=limit)

@app.get("/api/app/composite-replay", response_model=list[CompositeReplayItem])
def get_app_composite_replay(
    days: int = 5,
    per_day: int = 1,
    user: AppUser = Depends(_require_app_user),
):
    return _build_composite_replay(days=days, per_day=per_day)

@app.get("/api/app/composite-compare", response_model=RecommendationCompareSnapshot)
def get_app_composite_compare(
    days: int = 5,
    user: AppUser = Depends(_require_app_user),
):
    return _build_composite_compare(days=days)

@app.get("/api/app/positioning-plan", response_model=PositioningPlan)
def get_app_positioning_plan(days: int = 1, user: AppUser = Depends(_require_app_user)):
    return _build_positioning_plan(days=days)

@app.get("/api/app/theme-radar", response_model=list[ThemeRadarItem])
def get_app_theme_radar(limit: int = 3, user: AppUser = Depends(_require_app_user)):
    return _build_theme_radar(limit=limit)


@app.get("/api/app/theme-stage", response_model=list[ThemeStageItem])
def get_app_theme_stage(limit: int = 3, user: AppUser = Depends(_require_app_user)):
    return _build_theme_stage_engine(limit=limit)


@app.get("/api/app/policy-watch", response_model=list[PolicyWatchItem])
def get_app_policy_watch(limit: int = 3, user: AppUser = Depends(_require_app_user)):
    return _build_policy_watch(limit=limit)


@app.get("/api/app/industry-capital", response_model=list[IndustryCapitalDirection])
def get_app_industry_capital(limit: int = 3, user: AppUser = Depends(_require_app_user)):
    return _build_industry_capital_map(limit=limit)


@app.get("/api/app/industry-capital/{direction_id}", response_model=IndustryCapitalDirection)
def get_app_industry_capital_detail(
    direction_id: str,
    user: AppUser = Depends(_require_app_user),
):
    return _build_industry_capital_detail(direction_id)

@app.get("/api/app/industry-capital/{direction_id}/research-log", response_model=list[IndustryCapitalResearchItem])
def get_app_industry_capital_research_log(
    direction_id: str,
    limit: int = 12,
    user: AppUser = Depends(_require_app_user),
):
    return _list_industry_capital_research_items(direction_id, limit=limit)

@app.post(
    "/api/app/industry-capital/{direction_id}/research-log",
    response_model=IndustryCapitalResearchSubmissionResult,
)
def submit_app_industry_capital_research_log(
    direction_id: str,
    payload: IndustryCapitalResearchSubmissionRequest,
    user: AppUser = Depends(_require_app_user),
):
    return _submit_industry_capital_research(direction_id, payload, user)


@app.get("/api/app/positions", response_model=list[Position])
def get_app_positions(user: AppUser = Depends(_require_app_user)):
    return _build_positions()

@app.get("/api/app/positions/{code}", response_model=PositionDetail)
def get_app_position_detail(code: str, user: AppUser = Depends(_require_app_user)):
    return _build_position_detail(code)

@app.get("/api/app/market/{code}/kline", response_model=list[KlineBar])
def get_app_kline(code: str, days: int = 60, user: AppUser = Depends(_require_app_user)):
    return _build_kline_bars(code, days)

@app.get("/api/app/alerts", response_model=list[RiskAlert])
def get_app_alerts(user: AppUser = Depends(_require_app_user)):
    return _build_risk_alerts()


@app.get("/api/app/messages", response_model=list[AppMessage])
def get_app_messages(limit: int = 30, user: AppUser = Depends(_require_app_user)):
    return _build_app_messages(limit)

@app.get("/api/app/action-board", response_model=list[ActionBoardItem])
def get_app_action_board(limit: int = 6, user: AppUser = Depends(_require_app_user)):
    return _build_action_board(limit)


@app.get("/api/app/diagnosis/{code}", response_model=StockDiagnosis)
def get_app_stock_diagnosis(code: str, user: AppUser = Depends(_require_app_user)):
    return _build_stock_diagnosis(code)


@app.get("/api/app/learning", response_model=LearningProgress)
def get_app_learning(user: AppUser = Depends(_require_app_user)):
    return _build_learning_progress()


@app.get("/api/app/learning/daily-advance", response_model=LearningAdvanceStatus)
def get_app_learning_daily_advance(user: AppUser = Depends(_require_app_user)):
    return _build_learning_advance_status()


@app.post("/api/app/learning/daily-advance", response_model=LearningAdvanceStatus)
def run_app_learning_daily_advance(user: AppUser = Depends(_require_app_user)):
    return _start_learning_daily_advance(user)


@app.get("/api/app/feedback", response_model=list[FeedbackItem])
def get_app_feedback(user: AppUser = Depends(_require_app_user)):
    return _list_feedback_items(user)


@app.post("/api/app/feedback", response_model=FeedbackSubmissionResult)
def submit_app_feedback(
    payload: FeedbackSubmissionRequest,
    user: AppUser = Depends(_require_app_user),
):
    return _submit_feedback(user, payload)


@app.patch("/api/app/feedback/{feedback_id}/decision", response_model=FeedbackDecisionResult)
def decide_app_feedback(
    feedback_id: str,
    payload: FeedbackDecisionRequest,
    user: AppUser = Depends(_require_app_user),
):
    return _decide_feedback(feedback_id, payload, user)


@app.get("/api/app/portfolio/history", response_model=PortfolioHistory)
def get_app_portfolio_history(user: AppUser = Depends(_require_app_user)):
    return _build_portfolio_history()


@app.get("/api/app/push/devices", response_model=list[PushDevice])
def get_app_push_devices(user: AppUser = Depends(_require_app_user)):
    registry = _load_push_registry()
    devices = _active_push_devices(registry, user.username)
    devices.sort(key=lambda item: item.get("last_seen_at", ""), reverse=True)
    return [_push_device_model(device) for device in devices]


@app.get("/api/app/push/takeover/status", response_model=TakeoverPushStatus)
def get_app_push_takeover_status(user: AppUser = Depends(_require_app_user)):
    return _build_takeover_push_status(user)


@app.get("/api/app/push/industry-research/status", response_model=IndustryResearchPushStatus)
def get_app_push_industry_research_status(user: AppUser = Depends(_require_app_user)):
    return _build_industry_research_push_status(user)


@app.patch("/api/app/push/takeover/settings", response_model=TakeoverPushStatus)
def update_app_push_takeover_settings(
    payload: TakeoverPushSettingsRequest,
    user: AppUser = Depends(_require_app_user),
):
    state = _load_push_state()
    state["takeover_auto_enabled"] = payload.auto_enabled
    _save_push_state(state)
    return _build_takeover_push_status(user)


@app.post("/api/app/push/register", response_model=PushRegistrationResult)
def register_app_push_device(
    payload: PushDeviceRegistrationRequest,
    user: AppUser = Depends(_require_app_user),
):
    return _register_push_device(user, payload)


@app.post("/api/app/push/test", response_model=PushDispatchResult)
def send_app_push_test(
    payload: PushTestRequest,
    user: AppUser = Depends(_require_app_user),
):
    return _dispatch_push_test(user, payload)


@app.post("/api/app/push/takeover", response_model=PushDispatchResult)
def send_app_push_takeover(
    payload: PushTakeoverRequest,
    user: AppUser = Depends(_require_app_user),
):
    return _dispatch_push_takeover(user, payload)


@app.post("/api/app/push/takeover/auto-run", response_model=PushDispatchResult)
def run_app_push_takeover_auto(
    payload: PushTakeoverRequest,
    user: AppUser = Depends(_require_app_user),
):
    return _run_takeover_auto_push(user, force=payload.force)


@app.post("/api/app/signals/{signal_id}/open", response_model=PortfolioActionResult)
def open_app_signal_position(
    signal_id: str,
    payload: SignalOpenRequest,
    user: AppUser = Depends(_require_app_user),
):
    return _open_signal_position(signal_id, payload)


@app.patch("/api/app/positions/{code}/risk", response_model=PortfolioActionResult)
def update_app_position_risk(
    code: str,
    payload: PositionRiskUpdateRequest,
    user: AppUser = Depends(_require_app_user),
):
    return _update_position_risk(code, payload)


@app.post("/api/app/positions/{code}/close", response_model=PortfolioActionResult)
def close_app_position(
    code: str,
    payload: PositionCloseRequest,
    user: AppUser = Depends(_require_app_user),
):
    return _close_position(code, payload)

# ================================================================
#  WebSocket 实时推送
# ================================================================

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as _exc:
                logger.warning("Suppressed exception: %s", _exc)

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # 保持连接 (客户端可发心跳)
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# ================================================================
#  启动
# ================================================================

if __name__ == "__main__":
    import uvicorn
    print("🚀 Alpha AI Trading API 启动中...")
    print("📖 API文档: http://localhost:8000/docs")
    print("🔌 WebSocket: ws://localhost:8000/ws")
    uvicorn.run(app, host="0.0.0.0", port=8000)
