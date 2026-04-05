"""
智能交易优化模块
================
六大交易改进的核心模块:
  1. 市场环境检测 (大盘过滤)
  2. ATR + 自适应止损
  3. 追踪止盈
  4. 分批止盈
  5. 回测智能入场 (次日开盘 + 回撤)
  6. 动态仓位 (分数+波动率加权)

所有函数均为纯计算, 不依赖外部 API (除 detect_market_regime 需 akshare)
"""

from __future__ import annotations

import time
import numpy as np
from datetime import datetime, date

import logging
import os

logger = logging.getLogger(__name__)

from config import (
    SMART_TRADE_ENABLED,
    MARKET_REGIME_PARAMS,
    MARKET_SIGNAL_WEIGHTS,
    MARKET_SIGNAL_WEIGHTS_BACKTEST,
    MARKET_REGIME_THRESHOLDS,
    REGIME_STRATEGY_PARAMS,
    PULLBACK_ENTRY_PARAMS,
    ADAPTIVE_STOP_PARAMS,
    TRAILING_STOP_PARAMS,
    PARTIAL_EXIT_PARAMS,
    DYNAMIC_SIZING_PARAMS,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
)
from json_store import safe_load

_DIR = os.path.dirname(os.path.abspath(__file__))
_TUNABLE_PATH = os.path.join(_DIR, "tunable_params.json")


# ================================================================
#  1. 市场环境检测 — 8信号评分制 v2.0
# ================================================================

_regime_cache = {}  # {date_str + "_" + period: result_dict}


# ── 单信号函数 (每个返回 0.0 ~ 1.0) ──────────────────────────

def _signal_ma_trend(closes: np.ndarray) -> float:
    """S1 均线趋势: 价格 vs MA5/MA20/MA60, 多头排列给高分"""
    if len(closes) < 60:
        return 0.5
    ma5 = np.mean(closes[-5:])
    ma20 = np.mean(closes[-20:])
    ma60 = np.mean(closes[-60:])
    current = closes[-1]

    score = 0.0
    if current > ma5:
        score += 0.25
    if current > ma20:
        score += 0.25
    if current > ma60:
        score += 0.25
    if ma5 > ma20 > ma60:
        score += 0.25
    return score


def _signal_momentum(closes: np.ndarray) -> float:
    """S2 多周期动量: 5/10/20日涨跌幅综合"""
    if len(closes) < 21:
        return 0.5
    chg_5 = (closes[-1] - closes[-6]) / closes[-6] if closes[-6] > 0 else 0
    chg_10 = (closes[-1] - closes[-11]) / closes[-11] if len(closes) >= 11 and closes[-11] > 0 else 0
    chg_20 = (closes[-1] - closes[-21]) / closes[-21] if closes[-21] > 0 else 0

    # 将涨跌幅映射到 0~1: >7.5%=1.0, 0%=0.5, <-7.5%=0.0
    def _map(chg):
        return max(0.0, min(1.0, chg / 0.15 + 0.5))

    return 0.4 * _map(chg_5) + 0.35 * _map(chg_10) + 0.25 * _map(chg_20)


def _signal_volatility(closes: np.ndarray) -> float:
    """S3 波动率状态: 低波动=高分(稳定), 高波动=低分(恐慌)"""
    if len(closes) < 21:
        return 0.5
    daily_ret = np.diff(closes[-21:]) / closes[-21:-1]
    vol = float(np.std(daily_ret) * np.sqrt(252))

    # vol < 0.12 → 1.0, vol > 0.45 → 0.0
    if vol <= 0.12:
        return 1.0
    elif vol >= 0.45:
        return 0.0
    else:
        return 1.0 - (vol - 0.12) / 0.33


def _fetch_market_breadth():
    """拉取一次 A股实时行情, 返回涨跌幅数组 (供 S4/S5 共用)"""
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        price_col = "涨跌幅" if "涨跌幅" in df.columns else None
        if price_col is None:
            return None
        vals = df[price_col].apply(lambda x: float(x) if str(x).replace(".", "").replace("-", "").isdigit() else 0)
        return vals
    except Exception:
        return None


def _signal_advance_decline(vals=None) -> float:
    """S4 涨跌比: A股上涨家数/下跌家数"""
    if vals is None:
        return 0.5
    try:
        up = (vals > 0).sum()
        down = (vals < 0).sum()
        if down == 0:
            return 1.0
        ratio = up / down
        # ratio>2 → 1.0, ratio=1 → 0.5, ratio<0.5 → 0.0
        return max(0.0, min(1.0, (ratio - 0.5) / 1.5))
    except Exception:
        return 0.5


def _signal_limit_ratio(vals=None) -> float:
    """S5 涨跌停比: 涨停家数 vs 跌停家数"""
    if vals is None:
        return 0.5
    try:
        limit_up = (vals >= 9.5).sum()
        limit_down = (vals <= -9.5).sum()
        total = limit_up + limit_down
        if total == 0:
            return 0.5
        return max(0.0, min(1.0, limit_up / total))
    except Exception:
        return 0.5


def _signal_northbound() -> float:
    """S6 北向资金: 近5日净流入方向"""
    try:
        import akshare as ak
        df = ak.stock_hsgt_north_net_flow_in_em(symbol="北上")
        if df is None or df.empty:
            return 0.5
        val_col = None
        for c in df.columns:
            if "净流入" in c or "net" in c.lower():
                val_col = c
                break
        if val_col is None:
            val_col = df.columns[-1]
        vals = df[val_col].astype(float).values
        if len(vals) < 5:
            return 0.5
        flow_5d = float(np.sum(vals[-5:]))
        # +150亿→1.0, 0→0.5, -150亿→0.0
        return max(0.0, min(1.0, flow_5d / 300.0 + 0.5))
    except Exception:
        return 0.5


def _signal_margin_trend() -> float:
    """S7 融资趋势: 5日融资余额变化"""
    try:
        import akshare as ak
        df = ak.stock_margin_sse()
        if df is None or df.empty:
            return 0.5
        bal_col = None
        for c in df.columns:
            if "融资余额" in c:
                bal_col = c
                break
        if bal_col is None:
            return 0.5
        vals = df[bal_col].astype(float).values
        if len(vals) < 6:
            return 0.5
        chg = (vals[-1] - vals[-6]) / vals[-6]
        # +3%→1.0, 0→0.5, -3%→0.0
        return max(0.0, min(1.0, chg / 0.06 + 0.5))
    except Exception:
        return 0.5


def _signal_index_rsi(closes: np.ndarray, period: int = 14) -> float:
    """S8 指数RSI: RSI>60看多, RSI<40看空"""
    if len(closes) < period + 1:
        return 0.5
    deltas = np.diff(closes[-(period + 1):])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss == 0:
        rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100 - 100 / (1 + rs)
    # RSI 30~70 映射到 0~1
    return max(0.0, min(1.0, (rsi - 30) / 40))


# ── 合成评分 ─────────────────────────────────────────────────

def _compute_regime_score(signal_scores: dict, weights: dict) -> float:
    """加权合成评分, 自动归一化权重"""
    total_w = sum(weights.values())
    if total_w <= 0:
        return 0.5
    score = 0.0
    for key, w in weights.items():
        score += signal_scores.get(key, 0.5) * (w / total_w)
    return score


def _score_to_regime(score: float) -> str:
    """合成评分 → 市场状态"""
    th = MARKET_REGIME_THRESHOLDS
    if score >= th["bull"]:
        return "bull"
    elif score >= th["neutral"]:
        return "neutral"
    elif score >= th["weak"]:
        return "weak"
    else:
        return "bear"


_MARKET_PHASE_TRAITS = {
    "trend_markup": {
        "label": "趋势主升",
        "style_bias": "趋势/波段优先",
        "horizon_hint": "主线与趋势票更适合按 T+3/T+5 跟踪。",
        "limit_up_mode": "只做板前和分歧承接",
        "limit_up_allowed": True,
        "summary": "趋势结构和增量资金更重要，优先交易主升而不是纯情绪脉冲。",
    },
    "breakout_expansion": {
        "label": "连板扩散",
        "style_bias": "强势接力优先",
        "horizon_hint": "首板/二板优先看 T+1/T+2，主线龙头才允许延长持有。",
        "limit_up_mode": "可做板前和板后承接",
        "limit_up_allowed": True,
        "summary": "情绪扩散和龙头唯一性占优，强势股生态允许更积极一些。",
    },
    "rotation_up": {
        "label": "轮动走强",
        "style_bias": "轮动+趋势兼顾",
        "horizon_hint": "更适合按 T+2/T+3 跟踪，追高板不如做板前确认。",
        "limit_up_mode": "只做板前确认",
        "limit_up_allowed": True,
        "summary": "市场并非单线主升，先做轮动主线和趋势确认，再谈扩大战果。",
    },
    "range_rotation": {
        "label": "震荡轮动",
        "style_bias": "快切短拿",
        "horizon_hint": "更适合按 T+1/T+2 快切，不宜把多数票拖成波段。",
        "limit_up_mode": "只做板前，不做板上",
        "limit_up_allowed": True,
        "summary": "强弱切换快，赚的是节奏和兑现，不是长趋势幻想。",
    },
    "weak_chop": {
        "label": "弱势拉扯",
        "style_bias": "轻仓短拿",
        "horizon_hint": "尾盘短线和竞价修复更适合按 T1 跟踪。",
        "limit_up_mode": "只做板前确认，不追板",
        "limit_up_allowed": True,
        "summary": "指数并不强，但活口会集中在少数方向，快进快出比久拿更重要。",
    },
    "ice_repair": {
        "label": "冰点修复",
        "style_bias": "修复试错",
        "horizon_hint": "只做 T+1 修复，不把修复票硬拿成波段。",
        "limit_up_mode": "可做修复板前，但仓位要轻",
        "limit_up_allowed": True,
        "summary": "修复正在发生，但更像试错窗口，先确认承接再说。",
    },
    "valuation_reset": {
        "label": "杀估值",
        "style_bias": "防守/低估值优先",
        "horizon_hint": "高估值进攻票只宜看不宜做，优先看低估值和防守链条。",
        "limit_up_mode": "禁做高位强势接力",
        "limit_up_allowed": False,
        "summary": "当前主导项是折现率和风险溢价，先避开高估值与远期故事。",
    },
    "risk_off": {
        "label": "退潮避险",
        "style_bias": "现金与防守优先",
        "horizon_hint": "先防守，不做强势接力和高弹性追价。",
        "limit_up_mode": "禁做强势板",
        "limit_up_allowed": False,
        "summary": "退潮期先保命，任何激进打法都会放大回撤。",
    },
}


def _market_phase_traits(phase: str) -> dict:
    return _MARKET_PHASE_TRAITS.get(phase, _MARKET_PHASE_TRAITS["range_rotation"]).copy()


def _market_phase_driver_summary(signals: dict) -> list[str]:
    driver_map = {
        "s1_ma_trend": "均线趋势",
        "s2_momentum": "多周期动量",
        "s3_volatility": "波动率稳定度",
        "s4_advance_decline": "涨跌广度",
        "s5_limit_ratio": "涨跌停比",
        "s6_northbound": "北向资金",
        "s7_margin_trend": "融资趋势",
        "s8_index_rsi": "指数 RSI",
    }
    ranked = sorted(signals.items(), key=lambda item: abs((item[1] or 0.5) - 0.5), reverse=True)
    lines: list[str] = []
    for key, value in ranked[:4]:
        label = driver_map.get(key, key)
        if value >= 0.62:
            lines.append(f"{label}偏强")
        elif value <= 0.38:
            lines.append(f"{label}偏弱")
    return lines[:3]


def _classify_market_phase(signals: dict, regime: str, score: float) -> dict:
    trend = float(signals.get("s1_ma_trend", 0.5))
    momentum = float(signals.get("s2_momentum", 0.5))
    vol_stability = float(signals.get("s3_volatility", 0.5))
    breadth = float(signals.get("s4_advance_decline", 0.5))
    limit_ratio = float(signals.get("s5_limit_ratio", 0.5))
    northbound = float(signals.get("s6_northbound", 0.5))
    margin = float(signals.get("s7_margin_trend", 0.5))
    rsi = float(signals.get("s8_index_rsi", 0.5))

    if regime == "bull":
        if limit_ratio >= 0.68 and breadth >= 0.58 and momentum >= 0.58:
            phase = "breakout_expansion"
        elif trend >= 0.68 and momentum >= 0.56 and northbound >= 0.5 and vol_stability >= 0.42:
            phase = "trend_markup"
        else:
            phase = "rotation_up"
    elif regime == "neutral":
        if trend >= 0.62 and momentum >= 0.54 and breadth >= 0.5:
            phase = "rotation_up"
        elif limit_ratio >= 0.56 and breadth < 0.5 and momentum < 0.52:
            phase = "ice_repair"
        else:
            phase = "range_rotation"
    elif regime == "weak":
        if limit_ratio >= 0.53 and breadth <= 0.48:
            phase = "ice_repair"
        elif vol_stability <= 0.28 or (momentum <= 0.35 and breadth <= 0.4 and rsi <= 0.38):
            phase = "valuation_reset"
        else:
            phase = "weak_chop"
    else:
        if limit_ratio >= 0.5 and breadth >= 0.42:
            phase = "ice_repair"
        elif vol_stability <= 0.24 or (momentum <= 0.32 and breadth <= 0.38):
            phase = "risk_off"
        else:
            phase = "valuation_reset"

    traits = _market_phase_traits(phase)
    drivers = _market_phase_driver_summary(signals)
    if not drivers:
        drivers = [f"环境评分 {round(score * 100, 1)}"]

    return {
        "market_phase": phase,
        "market_phase_label": traits["label"],
        "style_bias": traits["style_bias"],
        "horizon_hint": traits["horizon_hint"],
        "limit_up_mode": traits["limit_up_mode"],
        "limit_up_allowed": traits["limit_up_allowed"],
        "phase_summary": traits["summary"],
        "top_drivers": drivers,
    }


def get_regime_params(regime: str) -> dict:
    """根据市场状态返回策略参数"""
    return REGIME_STRATEGY_PARAMS.get(regime, REGIME_STRATEGY_PARAMS["neutral"]).copy()


# ── 实盘大盘检测 (8信号) ──────────────────────────────────────

def detect_market_regime() -> dict:
    """拉取数据 + 8信号评分, 判断大盘状态

    返回:
        regime: "bull" / "neutral" / "weak" / "bear"
        score: 0.0 ~ 1.0
        position_scale: float
        should_trade: bool
        signals: {信号名: 分值}
        regime_params: 当前regime下的策略参数
    """
    today_str = date.today().isoformat()
    now = datetime.now()
    hour = now.hour
    minute = now.minute
    if hour < 12:
        period = "morning"    # 09:00-11:30
    else:
        period = "afternoon"  # 13:00-15:00
    cache_key = f"{today_str}_{period}"
    if cache_key in _regime_cache:
        return _regime_cache[cache_key]

    params = MARKET_REGIME_PARAMS
    index_code = params["index_code"]

    signals = {}
    try:
        import akshare as ak
        df = ak.index_zh_a_hist(
            symbol=index_code,
            period="daily",
            start_date=(datetime.now().replace(day=1) - __import__("datetime").timedelta(days=120)).strftime("%Y%m%d"),
            end_date=datetime.now().strftime("%Y%m%d"),
        )
        if df is None or df.empty or len(df) < 60:
            result = _fallback_regime("数据不足")
            _regime_cache[today_str] = result
            return result

        close_col = None
        for c in df.columns:
            if "收盘" in c or c.lower() == "close":
                close_col = c
                break
        if close_col is None:
            close_col = df.columns[4]
        closes = df[close_col].astype(float).values

        # Tier1: 价格结构 (纯K线)
        signals["s1_ma_trend"] = _signal_ma_trend(closes)
        signals["s2_momentum"] = _signal_momentum(closes)
        signals["s3_volatility"] = _signal_volatility(closes)

        # Tier2: 市场广度 (需要实时API, 共用一次拉取)
        breadth_vals = _fetch_market_breadth()
        signals["s4_advance_decline"] = _signal_advance_decline(breadth_vals)
        signals["s5_limit_ratio"] = _signal_limit_ratio(breadth_vals)
        signals["s6_northbound"] = _signal_northbound()

        # Tier3: 杠杆确认
        signals["s7_margin_trend"] = _signal_margin_trend()
        signals["s8_index_rsi"] = _signal_index_rsi(closes)

        # 优先从 tunable_params 读调优后的信号权重，否则用 config 默认值
        tunable = safe_load(_TUNABLE_PATH, default={})
        signal_weights = tunable.get("regime_signals", {}).get("weights", MARKET_SIGNAL_WEIGHTS)

        # 合成评分
        score = _compute_regime_score(signals, signal_weights)
        regime = _score_to_regime(score)
        rp = get_regime_params(regime)
        phase_payload = _classify_market_phase(signals, regime, score)

        result = {
            "regime": regime,
            "score": round(score, 4),
            "position_scale": rp["position_scale"],
            "should_trade": rp["position_scale"] > 0,
            "signals": {k: round(v, 4) for k, v in signals.items()},
            "signal_weights": signal_weights,
            "regime_params": rp,
            "index_close": float(closes[-1]),
            **phase_payload,
        }

    except Exception as e:
        result = _fallback_regime(str(e))

    _regime_cache[cache_key] = result

    # 发射行情事件到事件总线
    try:
        from event_bus import get_event_bus, Priority
        bus = get_event_bus()
        regime_str = result.get("regime", "neutral")
        priority = Priority.URGENT if regime_str == "bear" else Priority.NORMAL
        bus.emit(
            source="smart_trader",
            priority=priority,
            event_type="regime_change",
            category="regime",
            payload={
                "regime": regime_str,
                "score": result.get("score", 0),
                "message": f"行情检测: {regime_str} (评分{result.get('score', 0):.2f})",
            },
        )
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    return result


def _fallback_regime(error_msg: str) -> dict:
    """异常/数据不足时的回退结果"""
    rp = get_regime_params("neutral")
    phase_payload = _classify_market_phase({}, "neutral", 0.5)
    return {
        "regime": "neutral",
        "score": 0.5,
        "position_scale": rp["position_scale"],
        "should_trade": True,
        "signals": {},
        "regime_params": rp,
        "error": error_msg,
        **phase_payload,
    }


# ── 回测大盘检测 (4信号, 纯K线) ─────────────────────────────

def detect_market_regime_backtest(index_closes: np.ndarray, idx: int,
                                  index_highs: np.ndarray = None,
                                  index_lows: np.ndarray = None) -> dict:
    """回测专用: 4个纯K线信号评分 (S1/S2/S3/S8), 不调API

    Args:
        index_closes: 指数每日收盘价
        idx: 当日在数组中的索引
        index_highs/index_lows: 可选, 暂未用
    """
    if idx < 60:
        rp = get_regime_params("neutral")
        return {
            "regime": "neutral",
            "score": 0.5,
            "position_scale": rp["position_scale"],
            "should_trade": True,
            "regime_params": rp,
        }

    closes_slice = index_closes[:idx + 1]

    signals = {
        "s1_ma_trend": _signal_ma_trend(closes_slice),
        "s2_momentum": _signal_momentum(closes_slice),
        "s3_volatility": _signal_volatility(closes_slice),
        "s8_index_rsi": _signal_index_rsi(closes_slice),
    }

    score = _compute_regime_score(signals, MARKET_SIGNAL_WEIGHTS_BACKTEST)
    regime = _score_to_regime(score)
    rp = get_regime_params(regime)
    phase_payload = _classify_market_phase(signals, regime, score)

    return {
        "regime": regime,
        "score": round(score, 4),
        "position_scale": rp["position_scale"],
        "should_trade": rp["position_scale"] > 0,
        "signals": {k: round(v, 4) for k, v in signals.items()},
        "regime_params": rp,
        **phase_payload,
    }


# ================================================================
#  2. ATR + 自适应止损
# ================================================================

def calc_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
             period: int = 14) -> float:
    """计算 Average True Range

    需要至少 period+1 个数据点
    返回 ATR 值, 数据不足返回 NaN
    """
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return float("nan")

    # True Range = max(H-L, |H-prevC|, |L-prevC|)
    tr_list = []
    for i in range(-period, 0):
        h = highs[i]
        l = lows[i]
        prev_c = closes[i - 1]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        tr_list.append(tr)

    return float(np.mean(tr_list))


def calc_adaptive_stop(entry_price: float, atr: float,
                       atr_multiplier_override: float = None) -> float:
    """自适应止损价

    止损价 = entry_price - atr_multiplier × ATR
    限制在 [max_stop_pct, min_stop_pct] 范围内 (注意 max_stop_pct < min_stop_pct, 如 -5% < -2%)
    ATR 不可用时回退到 fallback_stop_pct

    atr_multiplier_override: 由regime参数覆盖的ATR乘数
    """
    params = ADAPTIVE_STOP_PARAMS

    if not params.get("enabled"):
        return entry_price * (1 + STOP_LOSS_PCT / 100)

    if np.isnan(atr) or atr <= 0:
        return entry_price * (1 + params["fallback_stop_pct"] / 100)

    multiplier = atr_multiplier_override if atr_multiplier_override is not None else params["atr_multiplier"]
    stop_price = entry_price - multiplier * atr

    # 计算止损百分比
    stop_pct = (stop_price - entry_price) / entry_price * 100  # 负数

    # clamp: max_stop_pct(-5%) <= stop_pct <= min_stop_pct(-2%)
    min_pct = params["min_stop_pct"]  # -2% (最紧)
    max_pct = params["max_stop_pct"]  # -5% (最宽)
    stop_pct = max(max_pct, min(min_pct, stop_pct))

    return entry_price * (1 + stop_pct / 100)


# ================================================================
#  3. 追踪止盈
# ================================================================

def calc_trailing_stop(entry_price: float, highest_since_entry: float,
                       current_price: float,
                       trail_pct_override: float = None,
                       initial_target_override: float = None) -> dict:
    """追踪止盈检查

    盈利 >= activation_pct 激活追踪
    从最高价回撤 trail_pct 触发卖出

    trail_pct_override/initial_target_override: 由regime参数覆盖

    返回:
        trailing_active: bool
        trail_stop_price: float (追踪止盈价)
        should_exit: bool
        exit_reason: str
    """
    params = TRAILING_STOP_PARAMS

    if not params.get("enabled") or entry_price <= 0:
        return {
            "trailing_active": False,
            "trail_stop_price": 0,
            "should_exit": False,
            "exit_reason": "",
        }

    activation_pct = params["activation_pct"]
    trail_pct = trail_pct_override if trail_pct_override is not None else params["trail_pct"]
    initial_target = initial_target_override if initial_target_override is not None else params["initial_target_pct"]

    # 最高盈利
    highest_pnl = (highest_since_entry - entry_price) / entry_price * 100
    current_pnl = (current_price - entry_price) / entry_price * 100

    # 是否激活追踪
    trailing_active = highest_pnl >= activation_pct

    if trailing_active:
        # 追踪止盈价 = 最高价 × (1 - trail_pct%)
        trail_stop_price = highest_since_entry * (1 - trail_pct / 100)

        should_exit = current_price <= trail_stop_price
        exit_reason = "追踪止盈" if should_exit else ""

        return {
            "trailing_active": True,
            "trail_stop_price": trail_stop_price,
            "should_exit": should_exit,
            "exit_reason": exit_reason,
        }
    else:
        # 未激活: 用固定止盈
        should_exit = current_pnl >= initial_target
        return {
            "trailing_active": False,
            "trail_stop_price": entry_price * (1 + initial_target / 100),
            "should_exit": should_exit,
            "exit_reason": "固定止盈" if should_exit else "",
        }


# ================================================================
#  4. 分批止盈
# ================================================================

def check_partial_exit(entry_price: float, current_price: float,
                       position_info: dict,
                       first_exit_pct_override: float = None,
                       first_exit_ratio_override: float = None) -> dict:
    """分批止盈检查

    盈利 >= first_exit_pct 且未分批过 → 卖出 first_exit_ratio

    Args:
        position_info: 需包含 partial_exited (bool), remaining_ratio (float)
        first_exit_pct_override/first_exit_ratio_override: 由regime参数覆盖

    返回:
        should_partial_exit: bool
        exit_ratio: float (本次卖出比例, 相对总仓位)
        remaining_ratio: float (卖出后剩余比例)
    """
    params = PARTIAL_EXIT_PARAMS

    if not params.get("enabled") or entry_price <= 0:
        return {
            "should_partial_exit": False,
            "exit_ratio": 0,
            "remaining_ratio": position_info.get("remaining_ratio", 1.0),
        }

    already_partial = position_info.get("partial_exited", False)
    remaining = position_info.get("remaining_ratio", 1.0)

    if already_partial:
        return {
            "should_partial_exit": False,
            "exit_ratio": 0,
            "remaining_ratio": remaining,
        }

    first_exit_pct = first_exit_pct_override if first_exit_pct_override is not None else params["first_exit_pct"]
    first_exit_ratio = first_exit_ratio_override if first_exit_ratio_override is not None else params["first_exit_ratio"]

    pnl_pct = (current_price - entry_price) / entry_price * 100

    if pnl_pct >= first_exit_pct:
        new_remaining = remaining * (1 - first_exit_ratio)
        return {
            "should_partial_exit": True,
            "exit_ratio": first_exit_ratio,
            "remaining_ratio": new_remaining,
        }

    return {
        "should_partial_exit": False,
        "exit_ratio": 0,
        "remaining_ratio": remaining,
    }


# ================================================================
#  5. 回测智能入场
# ================================================================

def calc_backtest_entry_price(next_open: float, next_high: float,
                              next_low: float, next_close: float,
                              atr: float) -> tuple:
    """回测入场价计算

    1. 基础价 = 次日开盘价 (消除前瞻偏差)
    2. 如果日内回撤到 open × (1 - pullback_pct%), 用回撤价入场
    3. 否则用开盘价

    返回: (entry_price, entry_method)
    """
    params = PULLBACK_ENTRY_PARAMS

    if not params.get("enabled"):
        return (next_open, "开盘价")

    base_price = next_open
    pullback_pct = params["pullback_pct"]
    pullback_target = base_price * (1 - pullback_pct / 100)

    # 日内最低价是否触及回撤目标
    if next_low <= pullback_target:
        return (pullback_target, "回撤入场")
    else:
        return (base_price, "开盘价")


# ================================================================
#  6. 回测完整交易模拟
# ================================================================

def simulate_backtest_trade(entry_price_old: float,
                            next_open: float, next_high: float,
                            next_low: float, next_close: float,
                            atr: float, score: float = 0) -> dict:
    """整合所有改进的单笔回测交易

    1. calc_backtest_entry_price → 智能入场
    2. calc_adaptive_stop → 先判止损 (next_low vs stop_price)
    3. 分批止盈 → 盘中最高触及 +3% 时, 50%@target + 50%@close
    4. 追踪止盈 → 最高 ≥+2% 且收盘低于 trail_stop
    5. 固定止盈 → 最高 ≥+5%
    6. 默认收盘平仓

    返回:
        entry_price: 实际入场价
        exit_price: 加权退出价
        exit_reason: str
        raw_return: float (百分比)
        entry_method: str
    """
    # 1. 智能入场
    entry_price, entry_method = calc_backtest_entry_price(
        next_open, next_high, next_low, next_close, atr
    )

    if entry_price <= 0:
        return {
            "entry_price": entry_price_old,
            "exit_price": next_close,
            "exit_reason": "收盘平仓",
            "raw_return": (next_close - entry_price_old) / entry_price_old * 100 if entry_price_old > 0 else 0,
            "entry_method": "旧逻辑",
        }

    # 2. ATR 自适应止损
    stop_price = calc_adaptive_stop(entry_price, atr)
    if next_low <= stop_price:
        # 触发止损
        exit_price = stop_price
        raw_return = (exit_price - entry_price) / entry_price * 100
        return {
            "entry_price": entry_price,
            "exit_price": round(exit_price, 4),
            "exit_reason": "自适应止损",
            "raw_return": round(raw_return, 4),
            "entry_method": entry_method,
        }

    # 3. 分批止盈: 盘中最高触及 first_exit_pct
    partial_params = PARTIAL_EXIT_PARAMS
    first_exit_pct = partial_params.get("first_exit_pct", 3.0)
    first_exit_ratio = partial_params.get("first_exit_ratio", 0.5)
    first_target = entry_price * (1 + first_exit_pct / 100)

    high_pnl = (next_high - entry_price) / entry_price * 100

    if partial_params.get("enabled") and high_pnl >= first_exit_pct:
        # 50% 在 first_target 卖出, 50% 在收盘卖出
        part1_price = first_target
        part2_price = next_close
        exit_price = part1_price * first_exit_ratio + part2_price * (1 - first_exit_ratio)
        raw_return = (exit_price - entry_price) / entry_price * 100
        return {
            "entry_price": entry_price,
            "exit_price": round(exit_price, 4),
            "exit_reason": "分批止盈",
            "raw_return": round(raw_return, 4),
            "entry_method": entry_method,
        }

    # 4. 追踪止盈: 盘中最高 ≥ activation_pct 且收盘低于 trail_stop
    trail_result = calc_trailing_stop(entry_price, next_high, next_close)
    if trail_result["trailing_active"] and trail_result["should_exit"]:
        exit_price = trail_result["trail_stop_price"]
        raw_return = (exit_price - entry_price) / entry_price * 100
        return {
            "entry_price": entry_price,
            "exit_price": round(exit_price, 4),
            "exit_reason": "追踪止盈",
            "raw_return": round(raw_return, 4),
            "entry_method": entry_method,
        }

    # 5. 固定止盈 (追踪未激活时的上限)
    initial_target = TRAILING_STOP_PARAMS.get("initial_target_pct", 5.0)
    if trail_result.get("should_exit") and not trail_result["trailing_active"]:
        exit_price = entry_price * (1 + initial_target / 100)
        raw_return = (exit_price - entry_price) / entry_price * 100
        return {
            "entry_price": entry_price,
            "exit_price": round(exit_price, 4),
            "exit_reason": "固定止盈",
            "raw_return": round(raw_return, 4),
            "entry_method": entry_method,
        }

    # 6. 默认收盘平仓
    exit_price = next_close
    raw_return = (exit_price - entry_price) / entry_price * 100
    return {
        "entry_price": entry_price,
        "exit_price": round(exit_price, 4),
        "exit_reason": "收盘平仓",
        "raw_return": round(raw_return, 4),
        "entry_method": entry_method,
    }


# ================================================================
#  7. 动态仓位
# ================================================================

def calc_dynamic_sizing(capital: float, items: list[dict],
                        regime_scale: float = 1.0) -> list[dict]:
    """动态仓位: 分数 + 波动率反比加权, 乘以 regime_scale

    items: 每项需含 price, score; 可选 volatility
    返回: 原 items 的 copy, 增加 suggested_shares, suggested_amount
    """
    params = DYNAMIC_SIZING_PARAMS

    if not params.get("enabled") or not items or capital <= 0:
        return items

    n = len(items)
    score_w = params["score_weight"]
    equal_w = params["equal_weight"]
    max_pct = params["max_single_pct"] / 100
    min_pct = params["min_single_pct"] / 100
    vol_adjust = params["volatility_adjust"]

    # 分数权重
    scores = np.array([float(it.get("score", 0)) for it in items])
    score_sum = scores.sum()
    if score_sum > 0:
        score_weights = scores / score_sum
    else:
        score_weights = np.ones(n) / n

    # 均等权重
    equal_weights = np.ones(n) / n

    # 混合
    weights = score_w * score_weights + equal_w * equal_weights

    # 波动率调整 (低波动多买)
    if vol_adjust:
        vols = np.array([float(it.get("volatility", 0.3)) for it in items])
        vols = np.clip(vols, 0.05, 1.0)
        inv_vol = 1.0 / vols
        inv_vol_sum = inv_vol.sum()
        if inv_vol_sum > 0:
            vol_weights = inv_vol / inv_vol_sum
        else:
            vol_weights = np.ones(n) / n
        # 再混合: 70% 原权重 + 30% 波动率反比
        weights = 0.7 * weights + 0.3 * vol_weights

    # 归一化
    w_sum = weights.sum()
    if w_sum > 0:
        weights = weights / w_sum

    # 应用 regime_scale
    effective_capital = capital * regime_scale

    result = []
    for i, it in enumerate(items):
        price = float(it.get("price", 0))
        if price <= 0:
            result.append(dict(it))
            continue

        # clamp 权重
        w = float(weights[i])
        w = max(min_pct, min(max_pct, w))

        amount = effective_capital * w
        shares = int(amount / price / 100) * 100
        if shares < 100:
            shares = 100
        actual_amount = shares * price

        it_copy = dict(it)
        it_copy["suggested_shares"] = shares
        it_copy["suggested_amount"] = round(actual_amount, 2)
        it_copy["weight_pct"] = round(w * 100, 1)
        result.append(it_copy)

    return result
