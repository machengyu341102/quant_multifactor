"""
入场时机分析器
==============
分析历史信号: "立刻买" vs "等回踩再买" 哪个 T+1 更好? 给出入场建议。

核心:
  analyze_slot_performance()    — 各时段信号的 T+1/T+3 表现
  analyze_score_tier_timing()   — 高分 vs 低分在不同时段的差异
  analyze_pullback_opportunity() — 回踩空间分析
  get_timing_advice()           — 综合入场建议

不单独调度, 作为夜班任务的一部分。
结果写入 timing_analysis.json, morning_prep 读取展示。

CLI:
  python3 execution_timing.py          # 完整分析
  python3 execution_timing.py analyze  # 同上
  python3 execution_timing.py advice   # 仅显示建议
"""

import os
import sys
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from log_config import get_logger
from json_store import safe_load, safe_save

logger = get_logger("execution_timing")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_TIMING_PATH = os.path.join(_BASE_DIR, "timing_analysis.json")

try:
    from config import TIMING_PARAMS
except ImportError:
    TIMING_PARAMS = {"enabled": True, "lookback_days": 60, "min_samples": 20}

# 策略→时段映射
_STRATEGY_SLOT = {
    "集合竞价选股": "morning_open",
    "放量突破选股": "midday_10",
    "低吸回调选股": "midday_10",
    "缩量整理选股": "midday_10",
    "趋势跟踪选股": "midday_10",
    "尾盘短线选股": "afternoon",
    "板块轮动选股": "afternoon",
    "事件驱动选股": "morning_open",
}


def _load_scorecard(days: int) -> list:
    """加载 scorecard"""
    try:
        from db_store import load_scorecard
        return load_scorecard(days=days)
    except Exception as e:
        logger.warning("load_scorecard failed: %s", e)
        return []


def analyze_slot_performance(days: int = None) -> dict:
    """各时段信号的 T+1/T+3 表现

    Returns:
        {slot: {avg_t1, avg_t3, win_rate, n_signals}}
    """
    if days is None:
        days = TIMING_PARAMS.get("lookback_days", 60)

    records = _load_scorecard(days)
    if not records:
        return {}

    by_slot = defaultdict(list)
    for r in records:
        strategy = r.get("strategy", "")
        slot = _STRATEGY_SLOT.get(strategy, "other")
        ret = r.get("net_return_pct")
        if ret is None:
            continue
        by_slot[slot].append(r)

    result = {}
    for slot, recs in by_slot.items():
        n = len(recs)
        returns = [r.get("net_return_pct", 0) for r in recs]
        wins = sum(1 for r in returns if r > 0)

        result[slot] = {
            "avg_t1": round(sum(returns) / n, 2) if n > 0 else 0,
            "win_rate": round(wins / n * 100, 1) if n > 0 else 0,
            "n_signals": n,
        }

    return result


def analyze_score_tier_timing(days: int = None) -> dict:
    """高分 vs 低分信号在不同时段的表现差异

    Returns:
        {slot: {high_score_return, low_score_return, spread}}
    """
    if days is None:
        days = TIMING_PARAMS.get("lookback_days", 60)

    records = _load_scorecard(days)
    if not records:
        return {}

    # 按 slot 分组
    by_slot = defaultdict(list)
    for r in records:
        strategy = r.get("strategy", "")
        slot = _STRATEGY_SLOT.get(strategy, "other")
        score = r.get("score")
        ret = r.get("net_return_pct")
        if score is None or ret is None:
            continue
        by_slot[slot].append((score, ret))

    result = {}
    for slot, items in by_slot.items():
        if len(items) < 4:
            continue

        items.sort(key=lambda x: x[0], reverse=True)
        n = len(items)
        q = max(1, n // 4)

        high = items[:q]
        low = items[-q:]

        high_avg = sum(r for _, r in high) / len(high)
        low_avg = sum(r for _, r in low) / len(low)

        result[slot] = {
            "high_score_return": round(high_avg, 2),
            "low_score_return": round(low_avg, 2),
            "spread": round(high_avg - low_avg, 2),
            "n_high": len(high),
            "n_low": len(low),
        }

    return result


def analyze_pullback_opportunity(days: int = None) -> dict:
    """从 scorecard 分析: 信号后当日最低价 vs 入场价 → 回踩空间

    Returns:
        {strategy: {avg_pullback_pct, pullback_hit_rate, n_samples}}
    """
    if days is None:
        days = TIMING_PARAMS.get("lookback_days", 60)

    records = _load_scorecard(days)
    if not records:
        return {}

    by_strategy = defaultdict(list)
    for r in records:
        strategy = r.get("strategy", "")
        entry = r.get("entry_price") or r.get("rec_price")
        low = r.get("next_low")

        if entry and low and entry > 0:
            pullback = (low - entry) / entry * 100  # 负值 = 有回踩
            by_strategy[strategy].append(pullback)

    min_samples = TIMING_PARAMS.get("min_samples", 20)
    result = {}
    for strategy, pullbacks in by_strategy.items():
        if len(pullbacks) < min_samples:
            continue

        avg_pb = sum(pullbacks) / len(pullbacks)
        # 回踩命中率: 最低价低于入场价 0.5% 的比例
        hit = sum(1 for p in pullbacks if p < -0.5)
        hit_rate = hit / len(pullbacks)

        result[strategy] = {
            "avg_pullback_pct": round(avg_pb, 2),
            "pullback_hit_rate": round(hit_rate * 100, 1),
            "n_samples": len(pullbacks),
        }

    return result


def get_timing_advice() -> dict:
    """综合建议: 各策略的入场建议

    Returns:
        {strategy: {action: "buy_now"|"wait_pullback", pullback_target_pct, confidence}}
    """
    pullback = analyze_pullback_opportunity()
    slot_perf = analyze_slot_performance()

    result = {}
    for strategy, pb_data in pullback.items():
        avg_pb = pb_data["avg_pullback_pct"]
        hit_rate = pb_data["pullback_hit_rate"]

        # 回踩空间大(avg < -1%)且命中率高(>60%) → 建议等回踩
        if avg_pb < -1.0 and hit_rate > 60:
            action = "wait_pullback"
            target = round(avg_pb * 0.5, 2)  # 目标回踩=平均回踩的一半
            confidence = min(1.0, hit_rate / 100)
        else:
            action = "buy_now"
            target = 0
            confidence = max(0.3, 1.0 - hit_rate / 100)

        result[strategy] = {
            "action": action,
            "pullback_target_pct": target,
            "confidence": round(confidence, 2),
            "avg_pullback": avg_pb,
            "hit_rate": hit_rate,
        }

    return result


def run_timing_analysis(days: int = None) -> dict:
    """完整分析 → 持久化到 timing_analysis.json"""
    if not TIMING_PARAMS.get("enabled", True):
        return {}

    if days is None:
        days = TIMING_PARAMS.get("lookback_days", 60)

    slot_perf = analyze_slot_performance(days)
    score_tier = analyze_score_tier_timing(days)
    pullback = analyze_pullback_opportunity(days)
    advice = get_timing_advice()

    result = {
        "slot_performance": slot_perf,
        "score_tier_timing": score_tier,
        "pullback_opportunity": pullback,
        "timing_advice": advice,
        "days": days,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    safe_save(_TIMING_PATH, result)
    logger.info("入场分析完成: %d个时段, %d个策略有回踩数据",
                len(slot_perf), len(pullback))
    return result


def format_timing_report(result: dict) -> str:
    """格式化为 morning_prep 可用的建议文本"""
    lines = ["入场时机建议:"]

    advice = result.get("timing_advice", {})
    if not advice:
        lines.append("  (数据不足)")
        return "\n".join(lines)

    for strategy, adv in advice.items():
        action = adv["action"]
        if action == "wait_pullback":
            lines.append(f"  {strategy}: 等回踩 {adv['pullback_target_pct']:.1f}% "
                         f"(命中{adv['hit_rate']:.0f}% 信心{adv['confidence']:.0f}%)")
        else:
            lines.append(f"  {strategy}: 立即买入 (回踩机会少)")

    # 时段排行
    slot_perf = result.get("slot_performance", {})
    if slot_perf:
        best = max(slot_perf.items(), key=lambda x: x[1].get("avg_t1", 0))
        lines.append(f"\n  最佳时段: {best[0]} (T+1均收{best[1]['avg_t1']:+.2f}%)")

    return "\n".join(lines)


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "analyze"

    print("=" * 55)
    print("  入场时机分析器")
    print("=" * 55)

    if mode == "advice":
        advice = get_timing_advice()
        if advice:
            print(f"\n  入场建议:")
            for strategy, adv in advice.items():
                if adv["action"] == "wait_pullback":
                    print(f"  {strategy}: 等回踩 {adv['pullback_target_pct']:.1f}% "
                          f"(命中{adv['hit_rate']:.0f}%)")
                else:
                    print(f"  {strategy}: 立即买入")
        else:
            print("  (数据不足)")

    else:  # analyze
        result = run_timing_analysis()
        if result:
            report = format_timing_report(result)
            print(f"\n{report}")

            # 详细数据
            print(f"\n  时段表现:")
            for slot, data in result.get("slot_performance", {}).items():
                print(f"    {slot}: T+1={data['avg_t1']:+.2f}% "
                      f"胜率{data['win_rate']}% ({data['n_signals']}条)")

            print(f"\n  分数段差异:")
            for slot, data in result.get("score_tier_timing", {}).items():
                print(f"    {slot}: 高分{data['high_score_return']:+.2f}% "
                      f"低分{data['low_score_return']:+.2f}% "
                      f"价差{data['spread']:+.2f}%")

            print(f"\n  回踩空间:")
            for strategy, data in result.get("pullback_opportunity", {}).items():
                print(f"    {strategy}: 平均{data['avg_pullback_pct']:+.2f}% "
                      f"命中{data['pullback_hit_rate']}% ({data['n_samples']}条)")
        else:
            print("  分析未启用或数据不足")
