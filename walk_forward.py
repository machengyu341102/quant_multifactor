"""
Walk-Forward 回测框架
====================
滚动窗口优化 + 样本外验证, 检测策略过拟合:

  |--- 训练窗口 (in-sample) ---|- 测试窗口 (out-of-sample) -|
  |  参数优化 → 最优参数      |  用最优参数回测验证         |
                               |--- 滑动 →
  |      训练窗口 (滑动后)     |- 测试窗口 (滑动后) -|

指标:
  - OOS Efficiency = OOS收益 / IS收益 (>0.5说明未严重过拟合)
  - OOS Degradation = 1 - OOS胜率/IS胜率 (<20%为健康)
  - 各窗口的 IS/OOS 胜率、收益、夏普对比

用法:
  python3 walk_forward.py                   # 全策略 walk-forward
  python3 walk_forward.py breakout          # 单策略
  python3 walk_forward.py --windows 6       # 6个滚动窗口
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from json_store import safe_load, safe_save
from log_config import get_logger
from config import BACKTEST_PARAMS

logger = get_logger("walk_forward")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_WF_RESULTS_PATH = os.path.join(_BASE_DIR, "walk_forward_results.json")

# 默认参数
WF_DEFAULTS = {
    "n_windows": 5,             # 滚动窗口数
    "train_days": 120,          # 训练窗口 (天)
    "test_days": 30,            # 测试窗口 (天)
    "step_days": 30,            # 滑动步长 (天)
    "grid_size": 5,             # 参数网格大小
    "grid_delta": 0.05,         # 参数扰动幅度
    "min_trades_per_window": 5, # 每窗口最少交易笔数
}


# ================================================================
#  参数网格 (复用 batch_backtest 逻辑)
# ================================================================

def _generate_grid(weights: dict, grid_size: int = 5,
                   delta: float = 0.05) -> list[dict]:
    """围绕当前权重生成参数网格"""
    if not weights:
        return []

    keys = list(weights.keys())
    base_vals = np.array([weights[k] for k in keys])
    grid = [dict(zip(keys, base_vals.tolist()))]  # baseline

    rng = np.random.RandomState(42)
    for _ in range(grid_size):
        perturbation = rng.uniform(-delta, delta, len(keys))
        new_vals = base_vals + perturbation
        new_vals = np.maximum(new_vals, 0.01)
        new_vals = new_vals / new_vals.sum()
        grid.append(dict(zip(keys, new_vals.tolist())))

    return grid


def _get_current_weights(strategy: str) -> dict:
    """获取策略当前权重"""
    try:
        from auto_optimizer import get_tunable_params
        params = get_tunable_params(strategy)
        return params.get("weights", {})
    except Exception:
        return {}


# ================================================================
#  单窗口回测 (轻量版, 不拉数据, 复用 kline_map)
# ================================================================

def _backtest_window(kline_map: dict, strategy: str,
                     start_date: str, end_date: str,
                     param_overrides: dict | None = None) -> dict:
    """在指定日期范围内执行回测

    Args:
        kline_map: {code: DataFrame} 预加载的K线数据
        strategy: 策略名
        start_date: 起始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD
        param_overrides: 参数覆盖

    Returns:
        {win_rate, avg_return, total_return, sharpe, total_trades, trades}
    """
    from backtest import (
        _calc_tech_factors, _score_candidates, _calc_trade_cost,
    )
    from config import (
        TOP_N, STOP_LOSS_PCT, TAKE_PROFIT_PCT,
        SMART_TRADE_ENABLED,
    )

    # 收集回测日期范围内的所有交易日
    all_dates = set()
    for df in kline_map.values():
        if "date" in df.columns:
            dates = df["date"].tolist()
            all_dates.update(d for d in dates if start_date <= d <= end_date)

    trade_dates = sorted(all_dates)
    if len(trade_dates) < 2:
        return {"total_trades": 0, "win_rate": 0, "avg_return": 0,
                "total_return": 0, "sharpe": 0}

    # 最后一天不能开仓
    trade_dates_open = trade_dates[:-1]
    trade_cost = _calc_trade_cost(0, 0)

    trades = []
    for trade_date in trade_dates_open:
        next_idx = trade_dates.index(trade_date) + 1
        if next_idx >= len(trade_dates):
            break
        next_date = trade_dates[next_idx]

        # 对所有股票计算技术因子
        candidates = []
        for code, df in kline_map.items():
            if "date" not in df.columns:
                continue
            sub = df[df["date"] <= trade_date]
            if len(sub) < 60:
                continue

            closes = sub["close"].values.astype(float)
            highs = sub["high"].values.astype(float)
            lows = sub["low"].values.astype(float)
            volumes = sub["volume"].values.astype(float)

            factors = _calc_tech_factors(closes, highs, lows, volumes)
            if factors is None:
                continue

            # 放量突破初筛
            if strategy == "breakout":
                pct = factors["pct_chg"]
                vr = factors["vol_ratio"]
                if not (1.0 <= pct <= 7.0 and vr >= 2.0):
                    continue

            factors["code"] = code
            factors["entry_price"] = float(closes[-1])
            candidates.append(factors)

        selected = _score_candidates(candidates, strategy, param_overrides)
        if not selected:
            continue

        # 计算次日收益
        for sel in selected:
            code = sel["code"]
            entry_price = sel["entry_price"]
            df = kline_map[code]
            next_rows = df[df["date"] == next_date]
            if next_rows.empty:
                continue

            next_row = next_rows.iloc[0]
            next_close = float(next_row["close"])
            next_high = float(next_row["high"])
            next_low = float(next_row["low"])

            # 止损止盈
            exit_price = next_close
            if entry_price > 0:
                low_pnl = (next_low - entry_price) / entry_price * 100
                if low_pnl <= STOP_LOSS_PCT:
                    exit_price = entry_price * (1 + STOP_LOSS_PCT / 100)
                else:
                    high_pnl = (next_high - entry_price) / entry_price * 100
                    if high_pnl >= TAKE_PROFIT_PCT:
                        exit_price = entry_price * (1 + TAKE_PROFIT_PCT / 100)

            raw_return = (exit_price - entry_price) / entry_price if entry_price > 0 else 0
            net_return = raw_return - trade_cost

            trades.append({
                "date": trade_date,
                "code": code,
                "net_return": round(net_return * 100, 4),
            })

    # 统计
    if not trades:
        return {"total_trades": 0, "win_rate": 0, "avg_return": 0,
                "total_return": 0, "sharpe": 0}

    returns = [t["net_return"] for t in trades]
    wins = sum(1 for r in returns if r > 0)
    total = len(returns)

    avg_ret = float(np.mean(returns))
    nav = 1.0
    for r in returns:
        nav *= (1 + r / 100)
    total_ret = (nav - 1) * 100

    sharpe = 0
    if len(returns) > 1:
        std = float(np.std(returns))
        if std > 0:
            sharpe = float(np.mean(returns) / std * np.sqrt(252))

    return {
        "total_trades": total,
        "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
        "avg_return": round(avg_ret, 4),
        "total_return": round(total_ret, 2),
        "sharpe": round(sharpe, 2),
    }


# ================================================================
#  Walk-Forward 主流程
# ================================================================

def walk_forward_test(strategy: str = "breakout",
                      n_windows: int = None,
                      train_days: int = None,
                      test_days: int = None,
                      step_days: int = None,
                      grid_size: int = None) -> dict:
    """执行 Walk-Forward 回测

    流程:
      for each window:
        1. 在训练窗口内, 用参数网格搜索找最优参数
        2. 用最优参数在测试窗口回测
        3. 记录 IS/OOS 对比

    Returns:
        {
            strategy, windows: [{train_period, test_period, is_stats, oos_stats, best_params}],
            summary: {oos_efficiency, oos_degradation, avg_is_wr, avg_oos_wr, ...},
            overfitting_risk: "low" | "medium" | "high",
        }
    """
    n_windows = n_windows or WF_DEFAULTS["n_windows"]
    train_days = train_days or WF_DEFAULTS["train_days"]
    test_days = test_days or WF_DEFAULTS["test_days"]
    step_days = step_days or WF_DEFAULTS["step_days"]
    grid_size = grid_size or WF_DEFAULTS["grid_size"]
    delta = WF_DEFAULTS["grid_delta"]
    min_trades = WF_DEFAULTS["min_trades_per_window"]

    total_days = train_days + test_days + (n_windows - 1) * step_days
    logger.info("[WF] %s: %d窗口, 训练%d天, 测试%d天, 步长%d天, 总需%d天数据",
                strategy, n_windows, train_days, test_days, step_days, total_days)

    # 获取当前权重
    weights = _get_current_weights(strategy)
    if not weights:
        logger.warning("[WF] %s: 无可调参数, 跳过", strategy)
        return {"strategy": strategy, "error": "no_tunable_params"}

    # 拉取K线 (一次拉取, 所有窗口复用)
    logger.info("[WF] 拉取K线数据 (%d天)...", total_days)
    try:
        from backtest import _get_index_constituents, _fetch_klines
    except ImportError:
        return {"strategy": strategy, "error": "backtest_not_available"}

    all_codes = _get_index_constituents()
    if not all_codes:
        return {"strategy": strategy, "error": "no_stock_pool"}

    sample_size = min(150, len(all_codes))
    np.random.seed(42)
    codes = list(np.random.choice(all_codes, sample_size, replace=False))
    kline_map = _fetch_klines(codes, total_days)
    if not kline_map:
        return {"strategy": strategy, "error": "no_kline_data"}

    # 确定可用日期范围
    all_dates = set()
    for df in kline_map.values():
        if "date" in df.columns:
            all_dates.update(df["date"].tolist())
    all_dates_sorted = sorted(all_dates)

    if len(all_dates_sorted) < train_days + test_days:
        return {"strategy": strategy, "error": "insufficient_data",
                "available_days": len(all_dates_sorted),
                "required_days": train_days + test_days}

    # 生成参数网格
    grid = _generate_grid(weights, grid_size=grid_size, delta=delta)
    logger.info("[WF] 参数网格: %d 组 (含baseline)", len(grid))

    # 滚动窗口
    windows = []
    end_idx = len(all_dates_sorted)

    for w in range(n_windows):
        # 从尾部往前推算每个窗口的位置
        # 窗口 w 的测试结束位置
        test_end_idx = end_idx - w * step_days
        test_start_idx = test_end_idx - test_days
        train_end_idx = test_start_idx
        train_start_idx = train_end_idx - train_days

        if train_start_idx < 0:
            logger.info("[WF] 窗口 %d: 数据不足, 跳过", w + 1)
            break

        train_start = all_dates_sorted[train_start_idx]
        train_end = all_dates_sorted[train_end_idx - 1]
        test_start = all_dates_sorted[test_start_idx]
        test_end = all_dates_sorted[min(test_end_idx - 1, len(all_dates_sorted) - 1)]

        logger.info("[WF] 窗口 %d/%d: 训练 %s~%s, 测试 %s~%s",
                    w + 1, n_windows, train_start, train_end, test_start, test_end)

        # 1. 训练窗口: 网格搜索最优参数
        best_params = None
        best_score = -999
        baseline_is = None

        for i, params in enumerate(grid):
            override = {"weights": params} if i > 0 else None
            result = _backtest_window(
                kline_map, strategy, train_start, train_end, override)

            if result["total_trades"] < min_trades:
                continue

            # 综合评分
            score = (result["win_rate"] * 0.4 +
                     result["avg_return"] * 10 * 0.4 +
                     result.get("sharpe", 0) * 0.2)

            if i == 0:
                baseline_is = result

            if score > best_score:
                best_score = score
                best_params = params
                best_is = result

        if best_params is None:
            logger.warning("[WF] 窗口 %d: 训练阶段无有效结果", w + 1)
            continue

        # 2. 测试窗口: 用最优参数回测
        oos_result = _backtest_window(
            kline_map, strategy, test_start, test_end,
            {"weights": best_params})

        window_data = {
            "window": w + 1,
            "train_period": f"{train_start}~{train_end}",
            "test_period": f"{test_start}~{test_end}",
            "is_stats": best_is,
            "oos_stats": oos_result,
            "baseline_is": baseline_is,
            "best_params": {k: round(v, 4) for k, v in best_params.items()},
        }
        windows.append(window_data)

        logger.info("[WF] 窗口 %d: IS胜率%.1f%% OOS胜率%.1f%% | IS收益%.2f%% OOS收益%.2f%%",
                    w + 1,
                    best_is["win_rate"], oos_result["win_rate"],
                    best_is["avg_return"], oos_result["avg_return"])

    # ---- 汇总分析 ----
    if not windows:
        return {"strategy": strategy, "error": "no_valid_windows"}

    summary = _calc_wf_summary(windows)

    result = {
        "strategy": strategy,
        "timestamp": datetime.now().isoformat(),
        "n_windows": len(windows),
        "params": {
            "train_days": train_days,
            "test_days": test_days,
            "step_days": step_days,
            "grid_size": grid_size,
        },
        "windows": windows,
        "summary": summary,
    }

    # 持久化
    _save_wf_results(result)

    return result


# ================================================================
#  汇总分析
# ================================================================

def _calc_wf_summary(windows: list[dict]) -> dict:
    """计算 Walk-Forward 汇总指标"""
    is_wrs = []
    oos_wrs = []
    is_rets = []
    oos_rets = []
    is_sharpes = []
    oos_sharpes = []

    for w in windows:
        is_s = w.get("is_stats", {})
        oos_s = w.get("oos_stats", {})

        if is_s.get("total_trades", 0) > 0:
            is_wrs.append(is_s["win_rate"])
            is_rets.append(is_s["avg_return"])
            is_sharpes.append(is_s.get("sharpe", 0))

        if oos_s.get("total_trades", 0) > 0:
            oos_wrs.append(oos_s["win_rate"])
            oos_rets.append(oos_s["avg_return"])
            oos_sharpes.append(oos_s.get("sharpe", 0))

    if not is_rets or not oos_rets:
        return {"error": "insufficient_data"}

    avg_is_wr = float(np.mean(is_wrs))
    avg_oos_wr = float(np.mean(oos_wrs))
    avg_is_ret = float(np.mean(is_rets))
    avg_oos_ret = float(np.mean(oos_rets))
    avg_is_sharpe = float(np.mean(is_sharpes))
    avg_oos_sharpe = float(np.mean(oos_sharpes))

    # OOS Efficiency: OOS收益 / IS收益 (值越高越好, >0.5说明未严重过拟合)
    oos_efficiency = avg_oos_ret / avg_is_ret if avg_is_ret != 0 else 0

    # OOS Degradation: 1 - OOS胜率/IS胜率 (值越低越好, <0.2为健康)
    oos_degradation = 1 - avg_oos_wr / avg_is_wr if avg_is_wr > 0 else 1

    # Sharpe Decay
    sharpe_decay = 1 - avg_oos_sharpe / avg_is_sharpe if avg_is_sharpe > 0 else 1

    # 过拟合风险判定
    if oos_efficiency < 0.3 or oos_degradation > 0.3:
        overfitting_risk = "high"
    elif oos_efficiency < 0.5 or oos_degradation > 0.15:
        overfitting_risk = "medium"
    else:
        overfitting_risk = "low"

    # OOS 收益一致性 (标准差)
    oos_ret_std = float(np.std(oos_rets)) if len(oos_rets) > 1 else 0

    return {
        "avg_is_win_rate": round(avg_is_wr, 1),
        "avg_oos_win_rate": round(avg_oos_wr, 1),
        "avg_is_return": round(avg_is_ret, 4),
        "avg_oos_return": round(avg_oos_ret, 4),
        "avg_is_sharpe": round(avg_is_sharpe, 2),
        "avg_oos_sharpe": round(avg_oos_sharpe, 2),
        "oos_efficiency": round(oos_efficiency, 3),
        "oos_degradation": round(oos_degradation, 3),
        "sharpe_decay": round(sharpe_decay, 3),
        "oos_return_std": round(oos_ret_std, 4),
        "overfitting_risk": overfitting_risk,
        "valid_windows": len(windows),
    }


# ================================================================
#  报告生成
# ================================================================

def generate_wf_report(result: dict) -> str:
    """生成 Walk-Forward 分析报告 (Markdown)"""
    strategy = result.get("strategy", "?")
    summary = result.get("summary", {})
    windows = result.get("windows", [])

    lines = [
        f"## Walk-Forward 分析: {strategy}",
        f"时间: {result.get('timestamp', '?')[:19]}",
        f"窗口: {result.get('n_windows', 0)} 个"
        f" (训练{result.get('params', {}).get('train_days', '?')}天"
        f" + 测试{result.get('params', {}).get('test_days', '?')}天)",
        "",
    ]

    if summary.get("error"):
        lines.append(f"**错误:** {summary['error']}")
        return "\n".join(lines)

    # 过拟合风险
    risk = summary.get("overfitting_risk", "unknown")
    risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(risk, "⚪")
    lines.append(f"### 过拟合风险: {risk_emoji} {risk.upper()}")
    lines.append("")

    # 核心指标
    lines.append("### 核心指标")
    lines.append("| 指标 | IS (样本内) | OOS (样本外) | 衰减 |")
    lines.append("|------|-----------|------------|------|")

    is_wr = summary.get("avg_is_win_rate", 0)
    oos_wr = summary.get("avg_oos_win_rate", 0)
    wr_decay = is_wr - oos_wr
    lines.append(f"| 胜率 | {is_wr:.1f}% | {oos_wr:.1f}% | {wr_decay:+.1f}% |")

    is_ret = summary.get("avg_is_return", 0)
    oos_ret = summary.get("avg_oos_return", 0)
    ret_decay = is_ret - oos_ret
    lines.append(f"| 平均收益 | {is_ret:+.4f}% | {oos_ret:+.4f}% | {ret_decay:+.4f}% |")

    is_sr = summary.get("avg_is_sharpe", 0)
    oos_sr = summary.get("avg_oos_sharpe", 0)
    sr_decay = is_sr - oos_sr
    lines.append(f"| 夏普 | {is_sr:.2f} | {oos_sr:.2f} | {sr_decay:+.2f} |")
    lines.append("")

    # 关键比率
    lines.append("### 关键比率")
    eff = summary.get("oos_efficiency", 0)
    deg = summary.get("oos_degradation", 0)
    sd = summary.get("sharpe_decay", 0)
    lines.append(f"- OOS Efficiency: **{eff:.3f}** (>0.5 健康, <0.3 过拟合)")
    lines.append(f"- OOS Degradation: **{deg:.3f}** (<0.15 健康, >0.3 过拟合)")
    lines.append(f"- Sharpe Decay: **{sd:.3f}** (<0.3 健康)")
    lines.append(f"- OOS 收益波动: ±{summary.get('oos_return_std', 0):.4f}%")
    lines.append("")

    # 窗口明细
    if windows:
        lines.append("### 窗口明细")
        lines.append("| # | 训练期 | 测试期 | IS胜率 | OOS胜率 | IS收益 | OOS收益 |")
        lines.append("|---|--------|--------|--------|---------|--------|---------|")
        for w in windows:
            wn = w.get("window", "?")
            tp = w.get("train_period", "?")
            ttp = w.get("test_period", "?")
            is_s = w.get("is_stats", {})
            oos_s = w.get("oos_stats", {})
            lines.append(
                f"| {wn} | {tp} | {ttp} "
                f"| {is_s.get('win_rate', 0):.1f}% "
                f"| {oos_s.get('win_rate', 0):.1f}% "
                f"| {is_s.get('avg_return', 0):+.4f}% "
                f"| {oos_s.get('avg_return', 0):+.4f}% |"
            )

    return "\n".join(lines)


# ================================================================
#  批量 Walk-Forward
# ================================================================

def run_batch_walk_forward(strategies: list = None, **kwargs) -> dict:
    """对多个策略执行 Walk-Forward 分析

    Returns:
        {strategy: wf_result, ...}
    """
    if strategies is None:
        strategies = [
            "breakout", "auction", "afternoon",
            "dip_buy", "consolidation", "trend_follow",
            "sector_rotation", "news_event", "futures_trend",
            "crypto_trend", "us_stock",
        ]

    results = {}
    for strategy in strategies:
        logger.info("[WF] ====== %s ======", strategy)
        t0 = time.time()
        result = walk_forward_test(strategy, **kwargs)
        elapsed = time.time() - t0
        result["duration_sec"] = round(elapsed, 1)
        results[strategy] = result

        # 打印简要结果
        summary = result.get("summary", {})
        risk = summary.get("overfitting_risk", "?")
        eff = summary.get("oos_efficiency", 0)
        logger.info("[WF] %s: 过拟合风险=%s, OOS效率=%.3f (%.0fs)",
                    strategy, risk, eff, elapsed)

    return results


# ================================================================
#  持久化
# ================================================================

def _save_wf_results(result: dict):
    """保存 Walk-Forward 结果 (追加, 保留最近30条)"""
    history = safe_load(_WF_RESULTS_PATH, default=[])
    if not isinstance(history, list):
        history = []
    history.append(result)
    # 保留最近 30 条
    if len(history) > 30:
        history = history[-30:]
    safe_save(_WF_RESULTS_PATH, history)


def get_wf_history(strategy: str = None, days: int = 30) -> list:
    """获取 Walk-Forward 历史"""
    from datetime import date, timedelta
    history = safe_load(_WF_RESULTS_PATH, default=[])
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    filtered = [r for r in history if r.get("timestamp", "")[:10] >= cutoff]
    if strategy:
        filtered = [r for r in filtered if r.get("strategy") == strategy]
    return filtered


def get_latest_overfitting_risk(strategy: str) -> str:
    """获取策略最新的过拟合风险等级"""
    history = get_wf_history(strategy, days=30)
    if not history:
        return "unknown"
    latest = history[-1]
    return latest.get("summary", {}).get("overfitting_risk", "unknown")


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    args = sys.argv[1:]

    strategy = None
    n_windows = WF_DEFAULTS["n_windows"]

    i = 0
    while i < len(args):
        if args[i] == "--windows" and i + 1 < len(args):
            n_windows = int(args[i + 1])
            i += 2
        elif args[i] in ("breakout", "auction", "afternoon",
                          "dip_buy", "consolidation", "trend_follow",
                          "sector_rotation", "news_event", "futures_trend",
                          "crypto_trend", "us_stock"):
            strategy = args[i]
            i += 1
        elif args[i] == "report":
            # 打印最近报告
            history = get_wf_history(days=30)
            if not history:
                print("暂无 Walk-Forward 结果")
            else:
                for r in history[-3:]:
                    print(generate_wf_report(r))
                    print()
            sys.exit(0)
        else:
            print(f"未知参数: {args[i]}")
            print("用法:")
            print("  python3 walk_forward.py                   # 全策略")
            print("  python3 walk_forward.py breakout           # 单策略")
            print("  python3 walk_forward.py --windows 6        # 6个窗口")
            print("  python3 walk_forward.py report             # 查看报告")
            sys.exit(1)

    if strategy:
        result = walk_forward_test(strategy, n_windows=n_windows)
        print(generate_wf_report(result))
    else:
        results = run_batch_walk_forward(n_windows=n_windows)
        for s, r in results.items():
            print(generate_wf_report(r))
            print()
