"""
批量回测引擎 — 夜班参数网格搜索
================================
在夜班 (22:30+) 自动运行, 对所有策略做参数网格搜索:
  1. 基于当前权重构建参数网格
  2. 逐组回测, 计算胜率/收益/夏普
  3. 选出最优参数组合, 对比 baseline
  4. 结果存入 backtest_results.json
  5. 供 auto_optimizer 采纳

CLI:
  python3 batch_backtest.py                # 全量回测 (所有策略)
  python3 batch_backtest.py breakout       # 单策略回测
  python3 batch_backtest.py quick          # 快速模式 (缩小网格)
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from json_store import safe_load, safe_save
from config import NIGHT_SHIFT_PARAMS
from log_config import get_logger

logger = get_logger("batch_backtest")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_RESULTS_PATH = os.path.join(_BASE_DIR, "backtest_results.json")

# 支持的策略
STRATEGIES = [
    "breakout", "auction", "afternoon",
    "dip_buy", "consolidation", "trend_follow", "sector_rotation",
    "news_event", "futures_trend",
    "crypto_trend", "us_stock",
]


# ================================================================
#  参数网格生成
# ================================================================

def _get_current_weights(strategy: str) -> dict:
    """获取策略当前权重"""
    try:
        from auto_optimizer import get_tunable_params
        params = get_tunable_params(strategy)
        return params.get("weights", {})
    except Exception:
        return {}


def generate_param_grid(weights: dict, grid_size: int = 5,
                        delta: float = 0.05) -> list[dict]:
    """围绕当前权重生成参数网格

    对每个权重 ±delta, 生成 grid_size 组随机变体
    + 1 组 baseline (当前参数)

    Args:
        weights: 当前权重 {"s_volume": 0.2, "s_ma": 0.15, ...}
        grid_size: 生成的变体数量
        delta: 每个权重的最大偏移量

    Returns:
        [{"s_volume": 0.22, "s_ma": 0.13, ...}, ...]
    """
    if not weights:
        return []

    keys = list(weights.keys())
    base_vals = np.array([weights[k] for k in keys])
    grid = [dict(zip(keys, base_vals))]  # baseline

    rng = np.random.RandomState(42)
    for _ in range(grid_size):
        # 随机扰动
        perturbation = rng.uniform(-delta, delta, len(keys))
        new_vals = base_vals + perturbation
        new_vals = np.maximum(new_vals, 0.01)  # 最小 0.01
        # 归一化使总和 = 1
        new_vals = new_vals / new_vals.sum()
        grid.append(dict(zip(keys, new_vals.tolist())))

    return grid


# ================================================================
#  单策略批量回测
# ================================================================

def backtest_strategy_grid(strategy: str, lookback_days: int = 90,
                           grid_size: int = 5) -> dict:
    """对单策略做参数网格搜索

    Args:
        strategy: 策略名
        lookback_days: 回测天数
        grid_size: 网格大小 (不含 baseline)

    Returns:
        {
            "strategy": "breakout",
            "baseline": {win_rate, avg_return, sharpe, ...},
            "best": {params, win_rate, avg_return, sharpe, improvement},
            "all_results": [{params, win_rate, avg_return, sharpe}, ...],
            "duration_sec": 120.5,
        }
    """
    logger.info("[回测] %s: 开始网格搜索 (grid=%d, lookback=%d天)",
                strategy, grid_size, lookback_days)

    weights = _get_current_weights(strategy)
    if not weights:
        logger.warning("[回测] %s: 无可调参数, 跳过", strategy)
        return {"strategy": strategy, "error": "no_tunable_params"}

    grid = generate_param_grid(weights, grid_size=grid_size)
    logger.info("[回测] %s: 生成 %d 组参数 (含baseline)", strategy, len(grid))

    try:
        from backtest import backtest_strategy
    except ImportError:
        logger.error("[回测] backtest 模块不可用")
        return {"strategy": strategy, "error": "backtest_not_available"}

    t0 = time.time()
    all_results = []

    for i, params in enumerate(grid):
        label = "baseline" if i == 0 else f"variant_{i}"
        logger.info("[回测] %s [%d/%d] %s", strategy, i + 1, len(grid), label)

        try:
            result = backtest_strategy(
                strategy=strategy,
                lookback_days=lookback_days,
                param_overrides=params if i > 0 else None,
            )
            entry = {
                "label": label,
                "params": {k: round(v, 4) for k, v in params.items()},
                "win_rate": result.get("win_rate", 0),
                "avg_return": result.get("avg_net_return", 0),
                "total_return": result.get("total_net_return", 0),
                "sharpe": result.get("sharpe", 0),
                "max_drawdown": result.get("max_drawdown", 0),
                "total_trades": result.get("total_trades", 0),
            }
            all_results.append(entry)
        except Exception as e:
            logger.warning("[回测] %s variant_%d 失败: %s", strategy, i, e)
            all_results.append({
                "label": label,
                "error": str(e),
            })

    elapsed = time.time() - t0

    # 找最优
    baseline = all_results[0] if all_results else {}
    valid_results = [r for r in all_results if "error" not in r and r.get("total_trades", 0) > 0]

    best = baseline
    if len(valid_results) > 1:
        # 综合评分: 0.4*胜率 + 0.4*收益 + 0.2*夏普
        def score(r):
            return (r.get("win_rate", 0) * 0.4 +
                    r.get("avg_return", 0) * 10 * 0.4 +
                    r.get("sharpe", 0) * 0.2)

        best = max(valid_results, key=score)

    improvement = {}
    if baseline and best and best != baseline:
        improvement = {
            "win_rate": round(best.get("win_rate", 0) - baseline.get("win_rate", 0), 2),
            "avg_return": round(best.get("avg_return", 0) - baseline.get("avg_return", 0), 2),
            "sharpe": round(best.get("sharpe", 0) - baseline.get("sharpe", 0), 2),
        }

    result = {
        "strategy": strategy,
        "timestamp": datetime.now().isoformat(),
        "lookback_days": lookback_days,
        "grid_size": len(grid),
        "baseline": baseline,
        "best": best,
        "improvement": improvement,
        "all_results": all_results,
        "duration_sec": round(elapsed, 1),
    }

    logger.info("[回测] %s 完成: %.0fs, baseline胜率%.1f%% best胜率%.1f%%",
                strategy, elapsed,
                baseline.get("win_rate", 0), best.get("win_rate", 0))

    return result


# ================================================================
#  全量批量回测
# ================================================================

def run_batch_backtest(strategies: list = None, quick: bool = False) -> dict:
    """运行批量回测 (夜班调用入口)

    Args:
        strategies: 要回测的策略列表, None=全部
        quick: True=快速模式 (更小网格+更短回测)

    Returns:
        {
            "date": "2026-03-02",
            "total_duration_min": 45.2,
            "results": {strategy: backtest_result},
            "recommendations": [{strategy, action, reason}],
        }
    """
    if strategies is None:
        strategies = STRATEGIES

    bt_params = NIGHT_SHIFT_PARAMS.get("backtest", {})
    lookback = 30 if quick else bt_params.get("lookback_days", 90)
    grid_size = 3 if quick else bt_params.get("param_grid_size", 5)

    logger.info("[批量回测] 开始: %d 策略, lookback=%d天, grid=%d",
                len(strategies), lookback, grid_size)

    t0 = time.time()
    results = {}
    recommendations = []

    for strategy in strategies:
        try:
            result = backtest_strategy_grid(
                strategy, lookback_days=lookback, grid_size=grid_size)
            results[strategy] = result

            # 生成建议
            imp = result.get("improvement", {})
            wr_imp = imp.get("win_rate", 0)
            ar_imp = imp.get("avg_return", 0)

            if wr_imp > 2 and ar_imp > 0.5:
                recommendations.append({
                    "strategy": strategy,
                    "action": "adopt",
                    "reason": f"胜率+{wr_imp:.1f}% 收益+{ar_imp:.2f}%",
                    "params": result.get("best", {}).get("params"),
                })
            elif wr_imp < -5:
                recommendations.append({
                    "strategy": strategy,
                    "action": "alert",
                    "reason": f"当前参数已是最优, 网格搜索未找到更好方案",
                })

        except Exception as e:
            logger.error("[批量回测] %s 失败: %s", strategy, e)
            results[strategy] = {"error": str(e)}

    total_duration = time.time() - t0

    summary = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().isoformat(),
        "total_duration_min": round(total_duration / 60, 1),
        "strategies_tested": len(strategies),
        "results": results,
        "recommendations": recommendations,
    }

    # 持久化
    _save_results(summary)

    logger.info("[批量回测] 全部完成: %.1f分钟, %d 个建议",
                total_duration / 60, len(recommendations))

    return summary


def _save_results(summary: dict):
    """保存回测结果 (保留最近 30 天)"""
    history = safe_load(_RESULTS_PATH, default=[])
    if not isinstance(history, list):
        history = []
    # 保留最近 30 天
    today = summary.get("date", "")
    history = [h for h in history if h.get("date", "") >= today[:8]][-29:]
    history.append(summary)
    safe_save(_RESULTS_PATH, history)


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"

    if arg == "quick":
        result = run_batch_backtest(quick=True)
    elif arg == "all":
        result = run_batch_backtest()
    elif arg in STRATEGIES:
        result = backtest_strategy_grid(arg)
        print(f"\n{'=' * 60}")
        print(f"  {arg}: 胜率 {result.get('baseline', {}).get('win_rate', 0):.1f}%"
              f" → {result.get('best', {}).get('win_rate', 0):.1f}%")
        imp = result.get("improvement", {})
        if imp:
            print(f"  改进: 胜率{imp.get('win_rate', 0):+.1f}% "
                  f"收益{imp.get('avg_return', 0):+.2f}%")
        print(f"  耗时: {result.get('duration_sec', 0):.0f}s")
    else:
        print("用法:")
        print("  python3 batch_backtest.py          # 全量回测")
        print("  python3 batch_backtest.py quick     # 快速回测")
        print(f"  python3 batch_backtest.py <策略>    # 单策略")
        print(f"  支持: {', '.join(STRATEGIES)}")
