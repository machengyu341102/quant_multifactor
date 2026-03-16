"""
收益归因引擎
===========
5维度 P&L 拆解: 知道钱从哪来、亏在哪里, 让 Agent Brain "看明白"。

维度:
  1. 策略维度 — 各策略 P&L / 胜率 / Sharpe
  2. 因子维度 — 哪个因子贡献最多 alpha
  3. 环境维度 — bull/neutral/weak/bear 各环境 P&L
  4. 时段维度 — morning/midday/afternoon 时段 P&L
  5. 打分段维度 — 高/中/低分信号表现

调度: 16:20 (signal_tracker 16:05 后)
CLI:
  python3 attribution.py          # 完整归因
  python3 attribution.py full     # 同上
  python3 attribution.py strategy # 策略维度
  python3 attribution.py factor   # 因子维度
  python3 attribution.py regime   # 环境维度
  python3 attribution.py timing   # 时段维度
"""

import os
import sys
import math
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from log_config import get_logger

logger = get_logger("attribution")

try:
    from config import ATTRIBUTION_PARAMS
except ImportError:
    ATTRIBUTION_PARAMS = {"enabled": True, "lookback_days": 30}

# 策略→时段映射
_STRATEGY_SLOT = {
    "集合竞价选股": "morning",
    "事件驱动选股": "morning",
    "放量突破选股": "midday",
    "低吸回调选股": "midday",
    "缩量整理选股": "midday",
    "趋势跟踪选股": "midday",
    "尾盘短线选股": "afternoon",
    "板块轮动选股": "afternoon",
}


def _load_scorecard(days: int) -> list:
    """加载 scorecard 数据"""
    try:
        from db_store import load_scorecard
        return load_scorecard(days=days)
    except Exception as e:
        logger.warning("load_scorecard failed: %s", e)
        return []


def calc_strategy_pnl(days: int = 30) -> list:
    """按策略拆解 P&L

    Returns:
        [{strategy, total_pnl, win_rate, avg_return, n_signals, sharpe}]
    """
    records = _load_scorecard(days)
    if not records:
        return []

    by_strategy = defaultdict(list)
    for r in records:
        ret = r.get("net_return_pct")
        if ret is None:
            continue
        by_strategy[r.get("strategy", "unknown")].append(ret)

    results = []
    for strategy, returns in by_strategy.items():
        n = len(returns)
        total = sum(returns)
        wins = sum(1 for r in returns if r > 0)
        avg = total / n if n > 0 else 0

        # Sharpe 近似 (简化: 日收益均值/标准差, 年化×sqrt(250))
        if n > 1:
            mean = avg
            var = sum((r - mean) ** 2 for r in returns) / (n - 1)
            std = math.sqrt(var) if var > 0 else 1
            sharpe = round((mean / std) * math.sqrt(250), 2)
        else:
            sharpe = 0

        results.append({
            "strategy": strategy,
            "total_pnl": round(total, 2),
            "win_rate": round(wins / n * 100, 1) if n > 0 else 0,
            "avg_return": round(avg, 2),
            "n_signals": n,
            "sharpe": sharpe,
        })

    results.sort(key=lambda x: x["total_pnl"], reverse=True)
    return results


def calc_factor_contribution(days: int = 30) -> list:
    """按因子拆解: 哪个因子贡献最多 alpha

    对每个因子: top25%信号的avg_return vs bottom25%
    contribution = (top25_return - bottom25_return) × factor_weight

    Returns:
        [{factor, contribution, spread, weight, rank}]
    """
    try:
        from signal_tracker import get_factor_effectiveness
        factors = get_factor_effectiveness(days=days)
    except Exception as e:
        logger.warning("get_factor_effectiveness failed: %s", e)
        return []

    if not factors:
        return []

    # 读当前权重
    weights = {}
    try:
        from json_store import safe_load
        tp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tunable_params.json")
        tp = safe_load(tp_path, default={})
        for strat_data in tp.values():
            if isinstance(strat_data, dict) and "weights" in strat_data:
                weights.update(strat_data["weights"])
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    results = []
    for factor, data in factors.items():
        spread = data.get("spread", 0)
        w = weights.get(factor, 0.05)  # 默认 5%
        contribution = spread * w

        results.append({
            "factor": factor,
            "contribution": round(contribution, 4),
            "spread": round(spread, 4),
            "weight": round(w, 4),
            "predictive": data.get("predictive", False),
        })

    results.sort(key=lambda x: x["contribution"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return results


def calc_regime_pnl(days: int = 30) -> list:
    """按 regime 拆解 P&L

    Returns:
        [{regime, total_pnl, win_rate, avg_return, n_signals}]
    """
    records = _load_scorecard(days)
    if not records:
        return []

    by_regime = defaultdict(list)
    for r in records:
        ret = r.get("net_return_pct")
        if ret is None:
            continue
        regime = r.get("regime", "unknown")
        by_regime[regime].append(ret)

    results = []
    for regime, returns in by_regime.items():
        n = len(returns)
        total = sum(returns)
        wins = sum(1 for r in returns if r > 0)
        avg = total / n if n > 0 else 0

        results.append({
            "regime": regime,
            "total_pnl": round(total, 2),
            "win_rate": round(wins / n * 100, 1) if n > 0 else 0,
            "avg_return": round(avg, 2),
            "n_signals": n,
        })

    results.sort(key=lambda x: x["total_pnl"], reverse=True)
    return results


def calc_timing_pnl(days: int = 30) -> list:
    """按时段拆解 P&L

    策略名→时段映射: 见 _STRATEGY_SLOT

    Returns:
        [{slot, total_pnl, win_rate, avg_return, n_signals}]
    """
    records = _load_scorecard(days)
    if not records:
        return []

    by_slot = defaultdict(list)
    for r in records:
        ret = r.get("net_return_pct")
        if ret is None:
            continue
        strategy = r.get("strategy", "")
        slot = _STRATEGY_SLOT.get(strategy, "other")
        by_slot[slot].append(ret)

    results = []
    for slot, returns in by_slot.items():
        n = len(returns)
        total = sum(returns)
        wins = sum(1 for r in returns if r > 0)
        avg = total / n if n > 0 else 0

        results.append({
            "slot": slot,
            "total_pnl": round(total, 2),
            "win_rate": round(wins / n * 100, 1) if n > 0 else 0,
            "avg_return": round(avg, 2),
            "n_signals": n,
        })

    results.sort(key=lambda x: x["total_pnl"], reverse=True)
    return results


def calc_score_band_pnl(days: int = 30) -> list:
    """按打分段拆解: 高分(top25%)vs中vs低分

    Returns:
        [{band, total_pnl, win_rate, avg_return, n_signals}]
    """
    records = _load_scorecard(days)
    if not records:
        return []

    scored = [(r, r.get("score", 0), r.get("net_return_pct")) for r in records
              if r.get("net_return_pct") is not None and r.get("score") is not None]

    if not scored:
        return []

    # 排序确定分位
    scored.sort(key=lambda x: x[1], reverse=True)
    n = len(scored)
    q25 = max(1, n // 4)
    q75 = n - q25

    bands = {
        "high": scored[:q25],
        "mid": scored[q25:q75],
        "low": scored[q75:],
    }

    results = []
    for band, items in bands.items():
        returns = [it[2] for it in items]
        n_b = len(returns)
        if n_b == 0:
            continue
        total = sum(returns)
        wins = sum(1 for r in returns if r > 0)
        avg = total / n_b

        results.append({
            "band": band,
            "total_pnl": round(total, 2),
            "win_rate": round(wins / n_b * 100, 1),
            "avg_return": round(avg, 2),
            "n_signals": n_b,
        })

    return results


def run_full_attribution(days: int = None) -> dict:
    """汇总5维归因 + 识别 top3 alpha来源 / top3 alpha流失"""
    if days is None:
        days = ATTRIBUTION_PARAMS.get("lookback_days", 30)

    strategy = calc_strategy_pnl(days)
    factor = calc_factor_contribution(days)
    regime = calc_regime_pnl(days)
    timing = calc_timing_pnl(days)
    score_band = calc_score_band_pnl(days)

    # top3 alpha sources
    alpha_sources = []
    for s in strategy[:3]:
        if s["total_pnl"] > 0:
            alpha_sources.append(f"{s['strategy']} +{s['total_pnl']:.1f}%")
    for f in factor[:3]:
        if f["contribution"] > 0:
            alpha_sources.append(f"因子{f['factor']} +{f['contribution']:.3f}")

    # top3 alpha drains
    alpha_drains = []
    for s in reversed(strategy):
        if s["total_pnl"] < 0 and len(alpha_drains) < 3:
            alpha_drains.append(f"{s['strategy']} {s['total_pnl']:.1f}%")
    for f in reversed(factor):
        if f["contribution"] < 0 and len(alpha_drains) < 3:
            alpha_drains.append(f"因子{f['factor']} {f['contribution']:.3f}")

    return {
        "days": days,
        "strategy": strategy,
        "factor": factor,
        "regime": regime,
        "timing": timing,
        "score_band": score_band,
        "alpha_sources": alpha_sources[:3],
        "alpha_drains": alpha_drains[:3],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def format_attribution_report(result: dict) -> str:
    """格式化为微信推送文本"""
    lines = [f"收益归因 ({result.get('days', 30)}天)\n"]

    # alpha 来源 / 流失
    sources = result.get("alpha_sources", [])
    drains = result.get("alpha_drains", [])
    if sources:
        lines.append("Alpha来源:")
        for s in sources:
            lines.append(f"  ▲ {s}")
    if drains:
        lines.append("Alpha流失:")
        for d in drains:
            lines.append(f"  ▼ {d}")

    # 策略 top3
    lines.append("\n策略排行:")
    for s in result.get("strategy", [])[:5]:
        tag = "+" if s["total_pnl"] > 0 else ""
        lines.append(f"  {s['strategy']}: {tag}{s['total_pnl']:.1f}% "
                     f"胜率{s['win_rate']}% Sharpe{s['sharpe']}")

    # 环境
    lines.append("\n环境P&L:")
    for r in result.get("regime", []):
        tag = "+" if r["total_pnl"] > 0 else ""
        lines.append(f"  {r['regime']}: {tag}{r['total_pnl']:.1f}% ({r['n_signals']}条)")

    # 分数段
    lines.append("\n分数段验证:")
    for b in result.get("score_band", []):
        lines.append(f"  {b['band']}: 胜率{b['win_rate']}% 均收{b['avg_return']:+.2f}%")

    return "\n".join(lines)


# ================================================================
#  CLI
# ================================================================

def _print_dim(title, items, key_field, value_fields):
    print(f"\n  {title}:")
    if not items:
        print("    (无数据)")
        return
    for item in items:
        parts = [f"{item[key_field]}:"]
        for vf in value_fields:
            v = item.get(vf, 0)
            if isinstance(v, float):
                parts.append(f"{vf}={v:.2f}")
            else:
                parts.append(f"{vf}={v}")
        print(f"    {' '.join(parts)}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    days = ATTRIBUTION_PARAMS.get("lookback_days", 30)

    print("=" * 55)
    print("  收益归因引擎")
    print("=" * 55)

    if mode == "strategy":
        _print_dim("策略维度", calc_strategy_pnl(days), "strategy",
                   ["total_pnl", "win_rate", "avg_return", "sharpe", "n_signals"])

    elif mode == "factor":
        _print_dim("因子维度", calc_factor_contribution(days), "factor",
                   ["contribution", "spread", "weight"])

    elif mode == "regime":
        _print_dim("环境维度", calc_regime_pnl(days), "regime",
                   ["total_pnl", "win_rate", "avg_return", "n_signals"])

    elif mode == "timing":
        _print_dim("时段维度", calc_timing_pnl(days), "slot",
                   ["total_pnl", "win_rate", "avg_return", "n_signals"])

    else:  # full
        result = run_full_attribution(days)
        report = format_attribution_report(result)
        print(f"\n{report}")
