"""
多策略共识引擎
=============
多策略同时选中同一只票 = 强共识信号。聚合跨策略一致性, 推送"今日共识股"。

核心:
  collect_today_picks()           — 从 trade_journal 读今日所有策略 picks
  score_consensus()               — 对 2+ 策略命中股打共识分
  get_consensus_recommendations() — 主入口
  check_consensus_history()       — 历史共识信号表现

调度:
  10:20 job_ensemble_midday (早盘策略后)
  14:40 job_ensemble_afternoon (午盘策略后)

CLI:
  python3 strategy_ensemble.py          # 运行并显示
  python3 strategy_ensemble.py status   # 显示当前状态
  python3 strategy_ensemble.py run      # 强制运行
  python3 strategy_ensemble.py history  # 历史共识表现
"""

import os
import sys
from datetime import datetime, date, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from log_config import get_logger
from json_store import safe_load, safe_save

logger = get_logger("strategy_ensemble")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from config import ENSEMBLE_PARAMS
except ImportError:
    ENSEMBLE_PARAMS = {
        "enabled": True, "min_strategies": 2, "top_n": 5,
        "weights": {
            "consensus_count": 0.35, "avg_score": 0.25,
            "family_diversity": 0.20, "regime_fit": 0.20,
        },
    }

# 策略族分类
STRATEGY_FAMILIES = {
    "momentum": ["放量突破选股", "趋势跟踪选股", "集合竞价选股"],
    "value":    ["低吸回调选股", "缩量整理选股"],
    "event":    ["事件驱动选股", "板块轮动选股", "尾盘短线选股"],
}

# 反向映射: 策略 → 族
_STRATEGY_TO_FAMILY = {}
for family, strategies in STRATEGY_FAMILIES.items():
    for s in strategies:
        _STRATEGY_TO_FAMILY[s] = family

# 所有A股策略名
_ALL_STRATEGIES = [
    "放量突破选股", "集合竞价选股", "尾盘短线选股",
    "低吸回调选股", "缩量整理选股", "趋势跟踪选股",
    "板块轮动选股", "事件驱动选股",
]


def collect_today_picks() -> dict:
    """从 trade_journal 读今日所有策略 picks, 按 code 分组

    Returns:
        {code: [{strategy, name, score, factor_scores}]}
    """
    try:
        from db_store import load_trade_journal
        journal = load_trade_journal(days=0)
    except Exception as e:
        logger.warning("load_trade_journal failed: %s", e)
        return {}

    today_str = date.today().isoformat()
    picks_by_code = defaultdict(list)

    for entry in journal:
        if entry.get("trade_date", entry.get("date", "")) != today_str:
            continue
        strategy = entry.get("strategy", "")
        picks = entry.get("picks", [])
        if isinstance(picks, str):
            try:
                import json
                picks = json.loads(picks)
            except Exception:
                continue

        for pick in (picks if isinstance(picks, list) else []):
            code = pick.get("code", "")
            if not code or len(code) != 6:
                continue
            picks_by_code[code].append({
                "strategy": strategy,
                "name": pick.get("name", ""),
                "score": pick.get("total_score", pick.get("score", 0)),
                "factor_scores": pick.get("factor_scores", {}),
            })

    return dict(picks_by_code)


def score_consensus(picks_by_code: dict, regime: dict = None) -> list:
    """对出现在 2+ 策略的股票打共识分

    - consensus_count (0.35): 策略数 / 总策略数
    - avg_score (0.25): 平均 total_score
    - family_diversity (0.20): 跨族数 / 3
    - regime_fit (0.20): 各策略在当前regime下胜率均值

    Returns:
        [{code, name, consensus_score, strategies[], family_count, avg_score}]
    """
    min_strategies = ENSEMBLE_PARAMS.get("min_strategies", 2)
    weights = ENSEMBLE_PARAMS.get("weights", {})
    w_count = weights.get("consensus_count", 0.35)
    w_score = weights.get("avg_score", 0.25)
    w_family = weights.get("family_diversity", 0.20)
    w_regime = weights.get("regime_fit", 0.20)

    # regime strategy matrix
    regime_matrix = {}
    current_regime = "neutral"
    if regime:
        current_regime = regime.get("regime", "neutral")
    try:
        from signal_tracker import get_regime_strategy_matrix
        regime_matrix = get_regime_strategy_matrix(days=60)
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    total_strategies = len(_ALL_STRATEGIES)
    total_families = len(STRATEGY_FAMILIES)
    results = []

    for code, picks in picks_by_code.items():
        strategies = list(set(p["strategy"] for p in picks))
        n_strategies = len(strategies)

        if n_strategies < min_strategies:
            continue

        # name: 用第一个 pick 的 name
        name = picks[0].get("name", code)

        # consensus_count
        s_count = min(1.0, n_strategies / total_strategies)

        # avg_score
        scores = [p["score"] for p in picks if p["score"] > 0]
        avg_sc = sum(scores) / len(scores) if scores else 0
        s_score = min(1.0, avg_sc)  # 已归一化

        # family_diversity
        families = set(_STRATEGY_TO_FAMILY.get(s, "unknown") for s in strategies)
        families.discard("unknown")
        family_count = len(families)
        s_family = min(1.0, family_count / total_families) if total_families > 0 else 0

        # regime_fit: 各策略在当前 regime 的胜率均值
        regime_rates = []
        for s in strategies:
            strat_data = regime_matrix.get(s, {})
            regime_data = strat_data.get(current_regime, {})
            wr = regime_data.get("win_rate", 0)
            if wr > 0:
                regime_rates.append(wr / 100)
        s_regime = sum(regime_rates) / len(regime_rates) if regime_rates else 0.5

        # 综合分
        consensus_score = (
            s_count * w_count +
            s_score * w_score +
            s_family * w_family +
            s_regime * w_regime
        )

        results.append({
            "code": code,
            "name": name,
            "consensus_score": round(consensus_score, 4),
            "n_strategies": n_strategies,
            "strategies": strategies,
            "family_count": family_count,
            "families": list(families),
            "avg_score": round(avg_sc, 4),
            "regime_fit": round(s_regime, 4),
        })

    results.sort(key=lambda x: x["consensus_score"], reverse=True)
    return results


def get_consensus_recommendations(min_strategies: int = None, top_n: int = None) -> list:
    """主入口: collect → score → 排序 → top_n"""
    if not ENSEMBLE_PARAMS.get("enabled", True):
        return []

    if min_strategies is None:
        min_strategies = ENSEMBLE_PARAMS.get("min_strategies", 2)
    if top_n is None:
        top_n = ENSEMBLE_PARAMS.get("top_n", 5)

    # 获取 regime
    regime = {}
    try:
        from smart_trader import detect_market_regime
        regime = detect_market_regime()
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    picks_by_code = collect_today_picks()
    if not picks_by_code:
        logger.info("今日无策略 picks")
        return []

    results = score_consensus(picks_by_code, regime)
    return results[:top_n]


def check_consensus_history(days: int = 30) -> dict:
    """回测历史共识信号表现

    从 scorecard 中找同日同code多策略命中的记录

    Returns:
        {total, win_rate, avg_return, vs_single_strategy_lift}
    """
    try:
        from db_store import load_scorecard
        records = load_scorecard(days=days)
    except Exception as e:
        logger.warning("load_scorecard failed: %s", e)
        return {}

    if not records:
        return {"total": 0}

    # 按日期+code分组
    daily_picks = defaultdict(lambda: defaultdict(list))
    for r in records:
        d = r.get("rec_date", "")
        code = r.get("code", "")
        if d and code:
            daily_picks[d][code].append(r)

    # 共识信号: 同日同code被2+策略推荐
    consensus_signals = []
    single_signals = []

    for d, codes in daily_picks.items():
        for code, recs in codes.items():
            strategies = list(set(r.get("strategy", "") for r in recs))
            ret = recs[0].get("net_return_pct", 0)  # 用第一条的收益
            if ret is None:
                continue

            if len(strategies) >= 2:
                consensus_signals.append({"return": ret, "strategies": len(strategies)})
            else:
                single_signals.append({"return": ret})

    if not consensus_signals:
        return {"total": 0}

    c_returns = [s["return"] for s in consensus_signals]
    c_wins = sum(1 for r in c_returns if r > 0)
    c_avg = sum(c_returns) / len(c_returns)

    s_returns = [s["return"] for s in single_signals]
    s_avg = sum(s_returns) / len(s_returns) if s_returns else 0

    return {
        "total": len(consensus_signals),
        "win_rate": round(c_wins / len(consensus_signals) * 100, 1),
        "avg_return": round(c_avg, 2),
        "single_total": len(single_signals),
        "single_avg_return": round(s_avg, 2),
        "vs_single_lift": round(c_avg - s_avg, 2),
    }


def get_ensemble_status() -> dict:
    """当前状态: 今日共识数, 历史胜率, 最近共识表现"""
    consensus = get_consensus_recommendations()
    history = check_consensus_history(days=30)

    return {
        "enabled": ENSEMBLE_PARAMS.get("enabled", True),
        "today_consensus_count": len(consensus),
        "today_picks": consensus[:5],
        "history_30d": history,
    }


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"

    print("=" * 55)
    print("  多策略共识引擎")
    print("=" * 55)

    if mode == "status":
        status = get_ensemble_status()
        print(f"\n  启用: {status['enabled']}")
        print(f"  今日共识: {status['today_consensus_count']} 只")
        if status["today_picks"]:
            for p in status["today_picks"]:
                print(f"    {p['code']}({p['name']}) "
                      f"共识分={p['consensus_score']:.3f} "
                      f"策略数={p['n_strategies']} "
                      f"族={p['families']}")
        h = status.get("history_30d", {})
        if h.get("total", 0) > 0:
            print(f"\n  30天历史: {h['total']}条 "
                  f"胜率{h['win_rate']}% "
                  f"均收{h['avg_return']:+.2f}% "
                  f"vs单策略 {h['vs_single_lift']:+.2f}%提升")

    elif mode == "history":
        h = check_consensus_history(days=60)
        if h.get("total", 0) > 0:
            print(f"\n  60天共识历史:")
            print(f"  共识信号: {h['total']}条")
            print(f"  共识胜率: {h['win_rate']}%")
            print(f"  共识均收: {h['avg_return']:+.2f}%")
            print(f"  单策略数: {h['single_total']}条")
            print(f"  单策略均收: {h['single_avg_return']:+.2f}%")
            print(f"  共识提升: {h['vs_single_lift']:+.2f}%")
        else:
            print("  暂无共识历史数据")

    else:  # run
        consensus = get_consensus_recommendations()
        if consensus:
            print(f"\n  今日共识 ({len(consensus)} 只):\n")
            for i, c in enumerate(consensus, 1):
                print(f"  {i}. {c['code']}({c['name']})")
                print(f"     共识分: {c['consensus_score']:.3f}")
                print(f"     策略数: {c['n_strategies']} → {c['strategies']}")
                print(f"     策略族: {c['families']} ({c['family_count']}族)")
                print(f"     均分: {c['avg_score']:.3f}  regime适配: {c['regime_fit']:.3f}")
                print()
        else:
            print("\n  今日无共识信号 (无股票被2+策略同时推荐)")
