"""
回测引擎
========
用历史日K线数据模拟策略运行, 计算胜率、收益率、夏普等指标

采用**代理回测法** (简化回测):
- 只用日K线技术因子 (RSI, MA, 量比, 波动率等)
- 买入价 = 当日收盘价, 卖出价 = 次日收盘价
- 止损止盈用次日最高/最低价判断
- 交易成本按 TRADE_COST 配置扣除

限制说明:
  完整回测不可行 — 集合竞价需历史竞价数据(API不提供),
  尾盘需历史分钟线(API限制当天), 基本面/新闻无法回溯。
  本回测回答的核心问题: "这套技术因子在历史上是否有效"。

用法:
  python3 backtest.py                  # 回测全部3个策略
  python3 backtest.py breakout         # 只回测放量突破
  python3 backtest.py auction          # 只回测集合竞价
  python3 backtest.py afternoon        # 只回测尾盘短线
  python3 backtest.py --days 180       # 回测180天
"""

from __future__ import annotations

import sys
import os
import time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import akshare as ak

from config import (
    TOP_N, TRADE_COST, BACKTEST_PARAMS,
    STOP_LOSS_PCT, TAKE_PROFIT_PCT,
    BREAKOUT_PARAMS,
    SMART_TRADE_ENABLED,
    MARKET_REGIME_PARAMS,
)
from overnight_strategy import (
    _retry, _tx_sym, REQUEST_DELAY,
    calc_rsi, calc_ma,
)


# ================================================================
#  交易成本计算
# ================================================================

def _calc_trade_cost(buy_price: float, sell_price: float) -> float:
    """计算单笔交易的总成本比例 (占买入价)"""
    comm = TRADE_COST["commission"]
    stamp = TRADE_COST["stamp_tax"]
    slip = TRADE_COST["slippage"]
    # 佣金双边 + 印花税卖出 + 滑点
    cost = comm * 2 + stamp + slip
    return cost


# ================================================================
#  获取股票池
# ================================================================

def _get_index_constituents() -> list[str]:
    """获取中证1000成分股代码"""
    print("[回测] 获取中证1000成分股...")
    try:
        df = _retry(ak.index_stock_cons, symbol="000852")
        col = "品种代码" if "品种代码" in df.columns else df.columns[0]
        codes = df[col].astype(str).str.zfill(6).tolist()
        # 排除科创(688)、北交(8)、三板(4)
        codes = [c for c in codes if not c.startswith(("688", "8", "4"))]
        print(f"  成分股: {len(codes)} 只")
        return codes
    except Exception as e:
        print(f"  获取成分股失败: {e}")
        return []


# ================================================================
#  批量拉取K线
# ================================================================

def _fetch_klines(codes: list[str], days: int) -> dict:
    """批量拉取日K线, 返回 {code: DataFrame}

    DataFrame 列: date, open, close, high, low, volume
    """
    end_date = datetime.now().strftime("%Y%m%d")
    # 多拉一些天用于计算技术指标
    start_date = (datetime.now() - timedelta(days=days + 120)).strftime("%Y%m%d")

    kline_map = {}
    total = len(codes)
    fail_count = 0

    print(f"[回测] 拉取K线数据 ({total} 只, 请耐心等待)...")

    for i, code in enumerate(codes):
        try:
            time.sleep(REQUEST_DELAY)
            df = _retry(
                ak.stock_zh_a_hist_tx,
                symbol=_tx_sym(code),
                start_date=start_date, end_date=end_date, adjust="qfq"
            )
            if df is None or df.empty or len(df) < 60:
                continue

            # 统一列名
            rename = {}
            for col in df.columns:
                cl = col.lower()
                if "日期" in col or "date" in cl:
                    rename[col] = "date"
                elif col == "open" or "开盘" in col:
                    rename[col] = "open"
                elif col == "close" or "收盘" in col:
                    rename[col] = "close"
                elif col == "high" or "最高" in col:
                    rename[col] = "high"
                elif col == "low" or "最低" in col:
                    rename[col] = "low"
                elif col in ("成交量", "volume", "amount"):
                    rename[col] = "volume"
            df = df.rename(columns=rename)

            for c in ["open", "close", "high", "low", "volume"]:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")

            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                df = df.sort_values("date").reset_index(drop=True)

            kline_map[code] = df

        except Exception:
            fail_count += 1

        if (i + 1) % 100 == 0:
            print(f"  进度: {i + 1}/{total}  有效: {len(kline_map)}  失败: {fail_count}")

    print(f"  K线数据: {len(kline_map)} 只有效 (失败 {fail_count})")
    return kline_map


# ================================================================
#  技术因子计算 (每日快照)
# ================================================================

def _calc_tech_factors(closes: np.ndarray, highs: np.ndarray,
                       lows: np.ndarray, volumes: np.ndarray) -> dict | None:
    """基于历史价格序列计算技术因子 (用于当日打分)

    输入: 截至当日(含)的价格序列
    返回: 因子字典, 或 None (数据不足)
    """
    if len(closes) < 60:
        return None

    # RSI
    rsi_vals = calc_rsi(closes, 14)
    rsi = rsi_vals[-1] if len(rsi_vals) > 0 and not np.isnan(rsi_vals[-1]) else 50

    # MA
    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60)

    above_ma60 = bool(closes[-1] > ma60[-1]) if len(ma60) >= 60 and not np.isnan(ma60[-1]) else False

    # 均线多头排列
    ma_aligned = False
    if (len(ma5) >= 5 and len(ma10) >= 10 and len(ma20) >= 20
            and not any(np.isnan([ma5[-1], ma10[-1], ma20[-1]]))):
        ma_aligned = bool(closes[-1] > ma5[-1] > ma10[-1] > ma20[-1])

    # 波动率 (20日)
    if len(closes) >= 21:
        daily_ret = np.diff(closes[-21:]) / closes[-21:-1]
        volatility = float(np.std(daily_ret) * np.sqrt(252))
    else:
        volatility = 0.3

    # 量比 (今日量 / 前5日均量)
    if len(volumes) >= 6:
        avg_vol_5 = np.mean(volumes[-6:-1])
        vol_ratio = float(volumes[-1] / avg_vol_5) if avg_vol_5 > 0 else 1
    else:
        vol_ratio = 1

    # 连续放量 (3日)
    consecutive_vol = False
    if len(volumes) >= 6:
        avg_vol = np.mean(volumes[-6:-1])
        if avg_vol > 0:
            consecutive_vol = all(
                volumes[-j] > avg_vol for j in range(1, min(4, len(volumes)))
            )

    # 回撤
    high_5d = float(np.max(highs[-5:])) if len(highs) >= 5 else closes[-1]
    high_20d = float(np.max(highs[-20:])) if len(highs) >= 20 else closes[-1]
    pullback_5d = closes[-1] / high_5d - 1 if high_5d > 0 else 0
    pullback_20d = closes[-1] / high_20d - 1 if high_20d > 0 else 0

    # 3日收益
    ret_3d = float(closes[-1] / closes[-3] - 1) if len(closes) >= 3 else 0

    # 突破阻力位
    resistance_ratio = float(closes[-1] / high_20d) if high_20d > 0 else 0

    # 日内涨幅 (当日收盘 vs 前日收盘)
    pct_chg = float((closes[-1] - closes[-2]) / closes[-2] * 100) if len(closes) >= 2 else 0

    # ATR (智能交易用)
    atr_14 = float("nan")
    if SMART_TRADE_ENABLED and len(closes) >= 15:
        from smart_trader import calc_atr
        atr_14 = calc_atr(highs, lows, closes, period=14)

    return {
        "rsi": rsi,
        "above_ma60": above_ma60,
        "ma_aligned": ma_aligned,
        "volatility": volatility,
        "vol_ratio": vol_ratio,
        "consecutive_vol": consecutive_vol,
        "pullback_5d": pullback_5d,
        "pullback_20d": pullback_20d,
        "ret_3d": ret_3d,
        "resistance_ratio": resistance_ratio,
        "pct_chg": pct_chg,
        "atr_14": atr_14,
    }


# ================================================================
#  打分函数
# ================================================================

def _zscore_array(arr: np.ndarray) -> np.ndarray:
    """Z-score 标准化"""
    mean = np.mean(arr)
    std = np.std(arr)
    if std < 1e-8:
        return np.zeros_like(arr)
    return (arr - mean) / std


def _score_candidates(candidates: list[dict], strategy: str,
                      param_overrides: dict | None = None) -> list[dict]:
    """对候选股打分, 返回排序后的 TOP N

    使用放量突破策略的权重模板 (技术因子通用)
    param_overrides: 临时覆盖权重, 不修改 config
    """
    if not candidates:
        return []

    df = pd.DataFrame(candidates)

    # --- s_volume_breakout: 量比强度 ---
    df["s_vol"] = _zscore_array(df["vol_ratio"].values)
    df.loc[df["consecutive_vol"], "s_vol"] += 0.5

    # --- s_ma_alignment: 均线排列 ---
    df["s_ma"] = 0.0
    df.loc[df["ma_aligned"], "s_ma"] = 1.0
    df.loc[df["above_ma60"], "s_ma"] += 0.5

    # --- s_momentum: 动量 ---
    df["s_mom"] = 0.0
    # 涨幅 1-3% 最优
    mask = (df["pct_chg"] >= 1) & (df["pct_chg"] <= 3)
    df.loc[mask, "s_mom"] = 1.0
    mask2 = (df["pct_chg"] > 3) & (df["pct_chg"] <= 5)
    df.loc[mask2, "s_mom"] = 0.5
    # 3日趋势
    df["s_mom"] += _zscore_array(df["ret_3d"].values) * 0.3

    # --- s_rsi: RSI 偏强 ---
    df["s_rsi"] = 0.0
    df.loc[(df["rsi"] >= 45) & (df["rsi"] <= 65), "s_rsi"] = 1.0
    df.loc[(df["rsi"] >= 30) & (df["rsi"] < 45), "s_rsi"] = 0.5
    df.loc[(df["rsi"] > 65) & (df["rsi"] <= 75), "s_rsi"] = 0.3

    # --- s_volatility: 波动率 (低波优先) ---
    df["s_vola"] = 0.0
    df.loc[df["volatility"] < 0.30, "s_vola"] = 1.0
    df.loc[(df["volatility"] >= 0.30) & (df["volatility"] < 0.45), "s_vola"] = 0.5

    # --- s_resistance: 突破度 ---
    df["s_res"] = _zscore_array(df["resistance_ratio"].values)

    # 加权总分
    if strategy == "breakout":
        w = (param_overrides or {}).get("weights", BREAKOUT_PARAMS["weights"])
        df["total_score"] = (
            df["s_vol"]  * w.get("s_volume_breakout", 0.20) +
            df["s_ma"]   * w.get("s_ma_alignment", 0.15) +
            df["s_mom"]  * w.get("s_momentum", 0.10) +
            df["s_rsi"]  * w.get("s_rsi", 0.08) +
            df["s_vola"] * 0.10 +
            df["s_res"]  * w.get("s_resistance_break", 0.03)
        )
    else:
        # 通用权重 (集合竞价/尾盘)
        df["total_score"] = (
            df["s_vol"]  * 0.15 +
            df["s_ma"]   * 0.15 +
            df["s_mom"]  * 0.12 +
            df["s_rsi"]  * 0.10 +
            df["s_vola"] * 0.13 +
            df["s_res"]  * 0.05
        )

    df = df.sort_values("total_score", ascending=False).head(TOP_N)
    return df.to_dict("records")


# ================================================================
#  单策略回测
# ================================================================

def backtest_strategy(strategy: str = "breakout", lookback_days: int = None,
                      param_overrides: dict | None = None) -> dict:
    """单策略回测

    1. 获取中证1000成分股
    2. 拉取 lookback_days 的日K线
    3. 对每个历史交易日: 计算技术指标 → 打分 → 取TOP3
    4. 计算次日收益 (含止损止盈 + 交易成本)
    5. 返回统计结果

    param_overrides: 临时覆盖权重, 不修改 config (供优化器调用)
    """
    if lookback_days is None:
        lookback_days = BACKTEST_PARAMS["lookback_days"]

    print(f"\n{'=' * 60}")
    print(f"  回测策略: {_strategy_label(strategy)} (近{lookback_days}天)")
    print(f"{'=' * 60}")

    # 1. 获取成分股 (采样以加快速度)
    all_codes = _get_index_constituents()
    if not all_codes:
        return {"error": "无法获取成分股"}

    # 采样200只 (全量太慢)
    sample_size = min(200, len(all_codes))
    np.random.seed(42)
    codes = list(np.random.choice(all_codes, sample_size, replace=False))
    print(f"  采样 {sample_size} 只用于回测")

    # 2. 拉取K线
    kline_map = _fetch_klines(codes, lookback_days)
    if not kline_map:
        return {"error": "无法获取K线数据"}

    # 3. 确定回测日期范围
    all_dates = set()
    for df in kline_map.values():
        if "date" in df.columns:
            all_dates.update(df["date"].tolist())
    all_dates = sorted(all_dates)

    # 只取最近 lookback_days 个交易日
    if len(all_dates) > lookback_days:
        backtest_dates = all_dates[-lookback_days:]
    else:
        backtest_dates = all_dates

    # 需要至少留一天作为 "次日" 结算
    if len(backtest_dates) < 2:
        return {"error": "交易日不足"}

    trade_dates = backtest_dates[:-1]  # 最后一天不能开仓 (无次日数据)
    trade_cost = _calc_trade_cost(0, 0)

    # 智能交易: 拉取中证1000指数历史 (用于大盘过滤)
    index_closes = None
    index_date_map = {}  # {date_str: index_in_array}
    if SMART_TRADE_ENABLED:
        try:
            from smart_trader import detect_market_regime_backtest
            idx_code = MARKET_REGIME_PARAMS["index_code"]
            start_dt = (datetime.now() - timedelta(days=lookback_days + 120)).strftime("%Y%m%d")
            end_dt = datetime.now().strftime("%Y%m%d")
            idx_df = _retry(
                ak.index_zh_a_hist,
                symbol=idx_code, period="daily",
                start_date=start_dt, end_date=end_dt,
            )
            if idx_df is not None and not idx_df.empty:
                # 统一列名
                close_col = None
                date_col = None
                for c in idx_df.columns:
                    if "收盘" in c or c.lower() == "close":
                        close_col = c
                    if "日期" in c or c.lower() == "date":
                        date_col = c
                if close_col and date_col:
                    idx_df[date_col] = pd.to_datetime(idx_df[date_col]).dt.strftime("%Y-%m-%d")
                    idx_df = idx_df.sort_values(date_col).reset_index(drop=True)
                    index_closes = idx_df[close_col].astype(float).values
                    for i, d in enumerate(idx_df[date_col]):
                        index_date_map[d] = i
                    print(f"  指数数据: {len(index_closes)} 天 ({idx_code})")
        except Exception as e:
            print(f"  指数数据获取失败: {e}, 跳过大盘过滤")

    print(f"  回测区间: {trade_dates[0]} ~ {trade_dates[-1]} ({len(trade_dates)} 个交易日)")
    print(f"  交易成本: {trade_cost * 100:.2f}% (佣金+印花税+滑点)")
    if SMART_TRADE_ENABLED:
        print(f"  智能交易: 开启 (ATR止损 + 追踪止盈 + 分批 + 大盘过滤)")
    else:
        print(f"  止损: {STOP_LOSS_PCT}%  止盈: {TAKE_PROFIT_PCT}%")
    print(f"\n[回测] 模拟交易中...")

    # 4. 逐日模拟
    trades = []
    skip_bear_days = 0
    for day_idx, trade_date in enumerate(trade_dates):
        next_date = backtest_dates[trade_dates.index(trade_date) + 1]

        # 智能交易: 大盘过滤 (v2.0 — 4信号评分)
        regime_params = None
        if SMART_TRADE_ENABLED and index_closes is not None:
            idx = index_date_map.get(trade_date)
            if idx is not None:
                regime = detect_market_regime_backtest(index_closes, idx)
                regime_params = regime.get("regime_params")
                if not regime["should_trade"]:
                    skip_bear_days += 1
                    continue

        # 对所有股票计算当日技术因子
        candidates = []
        for code, df in kline_map.items():
            if "date" not in df.columns:
                continue
            # 截至当日的数据
            mask = df["date"] <= trade_date
            sub = df[mask]
            if len(sub) < 60:
                continue

            closes = sub["close"].values.astype(float)
            highs = sub["high"].values.astype(float)
            lows = sub["low"].values.astype(float)
            volumes = sub["volume"].values.astype(float)

            factors = _calc_tech_factors(closes, highs, lows, volumes)
            if factors is None:
                continue

            # 策略初筛 (v2.0: 量比阈值跟随regime)
            if strategy == "breakout":
                pct = factors["pct_chg"]
                vr = factors["vol_ratio"]
                pct_min = 1.0
                pct_max = 7.0
                vr_min = 2.0
                if regime_params:
                    pct_min = regime_params.get("min_single_pct", pct_min)
                    pct_max = regime_params.get("max_single_pct", pct_max)
                    vr_min = regime_params.get("volume_ratio_min", vr_min)
                if not (pct_min <= pct <= pct_max and vr >= vr_min):
                    continue

            factors["code"] = code
            factors["entry_price"] = float(closes[-1])
            candidates.append(factors)

        # 打分选TOP
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
            next_open = float(next_row["open"])

            if SMART_TRADE_ENABLED:
                # 智能交易: 使用 simulate_backtest_trade
                from smart_trader import simulate_backtest_trade
                atr = sel.get("atr_14", float("nan"))
                score = sel.get("total_score", 0)
                sim = simulate_backtest_trade(
                    entry_price_old=entry_price,
                    next_open=next_open, next_high=next_high,
                    next_low=next_low, next_close=next_close,
                    atr=atr, score=score,
                )
                actual_entry = sim["entry_price"]
                exit_price = sim["exit_price"]
                exit_reason = sim["exit_reason"]
                raw_return = sim["raw_return"] / 100  # 转回小数
            else:
                # 原逻辑
                actual_entry = entry_price
                exit_price = next_close
                exit_reason = "收盘卖出"

                if entry_price > 0:
                    low_pnl = (next_low - entry_price) / entry_price * 100
                    if low_pnl <= STOP_LOSS_PCT:
                        exit_price = entry_price * (1 + STOP_LOSS_PCT / 100)
                        exit_reason = "止损"
                    else:
                        high_pnl = (next_high - entry_price) / entry_price * 100
                        if high_pnl >= TAKE_PROFIT_PCT:
                            exit_price = entry_price * (1 + TAKE_PROFIT_PCT / 100)
                            exit_reason = "止盈"

                raw_return = (exit_price - entry_price) / entry_price if entry_price > 0 else 0

            net_return = raw_return - trade_cost

            trades.append({
                "date": trade_date,
                "code": code,
                "entry_price": round(actual_entry, 4),
                "exit_price": round(exit_price, 2),
                "exit_reason": exit_reason,
                "raw_return": round(raw_return * 100, 4),
                "net_return": round(net_return * 100, 4),
                "cost": round(trade_cost * 100, 4),
            })

        # 进度
        if (day_idx + 1) % 20 == 0:
            print(f"  进度: {day_idx + 1}/{len(trade_dates)} 天, 已产生 {len(trades)} 笔交易")

    if SMART_TRADE_ENABLED and skip_bear_days > 0:
        print(f"  大盘过滤: 跳过 {skip_bear_days} 个熊市交易日")

    print(f"  模拟完成: {len(trades)} 笔交易")

    # 5. 计算统计
    stats = calc_backtest_stats(trades)
    stats["strategy"] = strategy
    stats["lookback_days"] = lookback_days
    stats["trade_dates"] = len(trade_dates)

    return stats


# ================================================================
#  回测统计计算
# ================================================================

def calc_backtest_stats(trades: list[dict]) -> dict:
    """计算回测统计指标"""
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0,
            "avg_return": 0,
            "total_return": 0,
            "max_drawdown": 0,
            "sharpe_ratio": 0,
            "profit_factor": 0,
            "avg_win": 0,
            "avg_loss": 0,
            "best_trade": 0,
            "worst_trade": 0,
            "total_cost": 0,
            "daily_returns": [],
        }

    returns = [t["net_return"] for t in trades]
    raw_returns = [t["raw_return"] for t in trades]
    costs = [t["cost"] for t in trades]

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]

    total_trades = len(returns)
    win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0

    avg_return = float(np.mean(returns))
    avg_win = float(np.mean(wins)) if wins else 0
    avg_loss = float(np.mean(losses)) if losses else 0
    best_trade = float(max(returns))
    worst_trade = float(min(returns))
    total_cost = float(sum(costs))

    # 累计收益 (复利)
    capital = BACKTEST_PARAMS["initial_capital"]
    nav = [capital]
    for r in returns:
        capital *= (1 + r / 100)
        nav.append(capital)
    total_return = (nav[-1] / nav[0] - 1) * 100

    # 最大回撤
    peak = nav[0]
    max_dd = 0
    for v in nav:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # 夏普比率 (假设每笔交易间隔1天, 年化)
    if len(returns) > 1:
        ret_arr = np.array(returns)
        mean_r = np.mean(ret_arr)
        std_r = np.std(ret_arr)
        # 年化: 假设一年约 250 个交易日, 每日 TOP_N 笔
        trades_per_day = TOP_N
        annualized_factor = np.sqrt(250 * trades_per_day)
        sharpe = float(mean_r / std_r * annualized_factor) if std_r > 0 else 0
    else:
        sharpe = 0

    # 盈亏比
    total_wins = sum(wins) if wins else 0
    total_losses = abs(sum(losses)) if losses else 0
    profit_factor = total_wins / total_losses if total_losses > 0 else float("inf")

    # 按日汇总收益 (用于画图)
    daily_map = {}
    for t in trades:
        d = t["date"]
        if d not in daily_map:
            daily_map[d] = []
        daily_map[d].append(t["net_return"])
    daily_returns = []
    for d in sorted(daily_map.keys()):
        daily_returns.append({
            "date": d,
            "avg_return": round(float(np.mean(daily_map[d])), 4),
            "trade_count": len(daily_map[d]),
        })

    return {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 1),
        "avg_return": round(avg_return, 4),
        "total_return": round(total_return, 2),
        "max_drawdown": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "best_trade": round(best_trade, 2),
        "worst_trade": round(worst_trade, 2),
        "total_cost": round(total_cost, 2),
        "daily_returns": daily_returns,
    }


# ================================================================
#  打印回测报告
# ================================================================

def _strategy_label(name: str) -> str:
    labels = {
        "breakout": "放量突破策略",
        "auction": "集合竞价策略",
        "afternoon": "尾盘短线策略",
        "dip_buy": "低吸回调策略",
        "consolidation": "缩量整理策略",
        "trend_follow": "趋势跟踪策略",
        "sector_rotation": "板块轮动策略",
        "news_event": "事件驱动策略",
        "futures_trend": "期货趋势策略",
        "crypto_trend": "币圈趋势策略",
        "us_stock": "美股分析策略",
    }
    return labels.get(name, name)


def print_backtest_report(stats: dict, strategy_name: str):
    """格式化打印回测报告"""
    label = _strategy_label(strategy_name)
    days = stats.get("lookback_days", "?")
    td = stats.get("trade_dates", "?")

    print()
    print("=" * 60)
    print(f"  回测报告: {label} (近{days}天, {td}个交易日)")
    print("=" * 60)

    if stats.get("error"):
        print(f"  错误: {stats['error']}")
        print("=" * 60)
        return

    total = stats["total_trades"]
    if total == 0:
        print("  无交易记录")
        print("=" * 60)
        return

    wr = stats["win_rate"]
    avg_r = stats["avg_return"]
    total_r = stats["total_return"]
    max_dd = stats["max_drawdown"]
    sharpe = stats["sharpe_ratio"]
    pf = stats["profit_factor"]
    avg_w = stats["avg_win"]
    avg_l = stats["avg_loss"]
    best = stats["best_trade"]
    worst = stats["worst_trade"]
    cost = stats["total_cost"]

    sign_avg = "+" if avg_r >= 0 else ""
    sign_total = "+" if total_r >= 0 else ""
    sign_best = "+" if best >= 0 else ""
    sign_worst = "+" if worst >= 0 else ""
    sign_w = "+" if avg_w >= 0 else ""
    sign_l = "+" if avg_l >= 0 else ""

    pf_str = f"{pf:.1f}:1" if pf < 100 else "INF"

    print(f"  交易次数:    {total} 笔 (每日{TOP_N}只 x {td}个交易日)")
    print(f"  胜率:        {wr:.1f}%")
    print(f"  平均收益:    {sign_avg}{avg_r:.2f}% (扣除成本后)")
    print(f"  累计收益:    {sign_total}{total_r:.1f}%")
    print(f"  最大回撤:    -{max_dd:.1f}%")
    print(f"  夏普比率:    {sharpe:.2f}")
    print(f"  盈亏比:      {pf_str}")
    print(f"  平均盈利:    {sign_w}{avg_w:.2f}%  |  平均亏损:  {sign_l}{avg_l:.2f}%")
    print(f"  最佳单笔:    {sign_best}{best:.1f}%  |  最差单笔:  {sign_worst}{worst:.1f}%")
    print(f"  {'─' * 56}")
    print(f"  交易成本累计: -{cost:.1f}% (佣金+印花税+滑点)")
    print("=" * 60)


# ================================================================
#  运行全部回测
# ================================================================

def run_backtest(strategies: list[str] = None, lookback_days: int = None):
    """运行指定策略的回测, 打印汇总报告"""
    if strategies is None:
        strategies = [
            "breakout", "auction", "afternoon",
            "dip_buy", "consolidation", "trend_follow", "sector_rotation",
            "news_event", "futures_trend",
            "crypto_trend", "us_stock",
        ]

    print("\n" + "#" * 60)
    print("  回测引擎启动")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  策略: {', '.join(_strategy_label(s) for s in strategies)}")
    print("#" * 60)

    results = {}
    for s in strategies:
        stats = backtest_strategy(s, lookback_days)
        results[s] = stats
        print_backtest_report(stats, s)

    # 汇总对比
    if len(results) > 1:
        print("\n" + "=" * 60)
        print("  策略对比汇总")
        print("=" * 60)
        header = f"  {'策略':<12} {'胜率':>6} {'平均收益':>8} {'累计收益':>8} {'夏普':>6} {'最大回撤':>8}"
        print(header)
        print("  " + "─" * 56)
        for s, st in results.items():
            if st.get("error"):
                print(f"  {_strategy_label(s):<12} {'错误':>6}")
                continue
            wr = st["win_rate"]
            ar = st["avg_return"]
            tr = st["total_return"]
            sr = st["sharpe_ratio"]
            md = st["max_drawdown"]
            sign_ar = "+" if ar >= 0 else ""
            sign_tr = "+" if tr >= 0 else ""
            print(f"  {_strategy_label(s):<10} {wr:>5.1f}% {sign_ar}{ar:>7.2f}% "
                  f"{sign_tr}{tr:>7.1f}% {sr:>5.2f}  -{md:>6.1f}%")
        print("=" * 60)

    return results


# ================================================================
#  CLI 入口
# ================================================================

if __name__ == "__main__":
    args = sys.argv[1:]

    strategies = None
    days = None

    i = 0
    while i < len(args):
        if args[i] == "--days" and i + 1 < len(args):
            days = int(args[i + 1])
            i += 2
        elif args[i] in ("breakout", "auction", "afternoon",
                         "dip_buy", "consolidation", "trend_follow",
                         "sector_rotation", "news_event", "futures_trend",
                         "crypto_trend", "us_stock"):
            strategies = [args[i]]
            i += 1
        else:
            print(f"未知参数: {args[i]}")
            print("用法:")
            print("  python3 backtest.py                  # 回测全部策略")
            print("  python3 backtest.py breakout         # 只回测放量突破")
            print("  python3 backtest.py crypto_trend     # 只回测币圈趋势")
            print("  python3 backtest.py us_stock         # 只回测美股分析")
            print("  python3 backtest.py --days 180       # 回测180天")
            sys.exit(1)

    run_backtest(strategies, days)
