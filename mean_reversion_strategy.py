"""
低吸回调 + 缩量整理突破策略
===========================
两个互补策略共享数据拉取流程, 选股逻辑各异:

策略一 (dip_buy):   RSI<30 超卖反弹, 09:50 开盘下杀后抄底
策略二 (consolidation): 横盘缩量后放量突破, 10:15 盘中选股

用法:
  python3 mean_reversion_strategy.py dip_buy        # 低吸回调
  python3 mean_reversion_strategy.py consolidation   # 缩量整理突破
"""

import sys
import os
import time
import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from overnight_strategy import (
    _retry, _tx_sym,
    calc_rsi, calc_bollinger, calc_ma,
    classify_sector,
    fetch_fundamental_batch, apply_fundamental_filters, calc_fundamental_scores,
    news_risk_screen,
    REQUEST_DELAY,
)
from intraday_strategy import (
    _sina_batch_quote, get_stock_pool, filter_basics, score_and_rank,
    _retry_heavy,
)
from config import (
    DIP_BUY_PARAMS, CONSOLIDATION_PARAMS, TOP_N,
    ENHANCED_FACTOR_WEIGHTS,
)
from enhanced_factors import enhance_candidates, format_enhanced_labels


# ================================================================
#  共享: 日K技术指标拉取
# ================================================================

def _fetch_one_mr_kline(code, name_map, start_date, end_date):
    """单只股票K线获取+技术指标计算 (供线程池调用)"""
    try:
        df = _retry(
            ak.stock_zh_a_hist_tx,
            symbol=_tx_sym(code),
            start_date=start_date, end_date=end_date, adjust="qfq"
        )
        if df.empty or len(df) < 30:
            return None

        closes = df["close"].values.astype(float)
        highs = df["high"].values.astype(float)
        lows = df["low"].values.astype(float)
        opens = df["open"].values.astype(float)
        vol_col = next((c for c in ["成交量", "volume", "amount"] if c in df.columns), "amount")
        volumes = df[vol_col].values.astype(float)

        # RSI
        rsi_vals = calc_rsi(closes, 14)
        rsi_now = rsi_vals[-1] if not np.isnan(rsi_vals[-1]) else 50

        # MA系列
        ma5 = calc_ma(closes, 5)
        ma10 = calc_ma(closes, 10)
        ma20 = calc_ma(closes, 20)
        ma60 = calc_ma(closes, 60)
        above_ma60 = (closes[-1] > ma60[-1]
                      if len(ma60) >= 60 and not np.isnan(ma60[-1])
                      else False)

        # 布林带
        upper, mid, lower = calc_bollinger(closes, 20, 2)

        # 近5日量 vs 20日均量
        avg_vol_5 = np.mean(volumes[-5:]) if len(volumes) >= 5 else 0
        avg_vol_20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else 1
        vol_ratio_5_20 = avg_vol_5 / avg_vol_20 if avg_vol_20 > 0 else 1

        # 近10日振幅
        if len(highs) >= 10 and len(lows) >= 10:
            range_10d = (np.max(highs[-10:]) - np.min(lows[-10:])) / np.min(lows[-10:]) * 100
        else:
            range_10d = 999

        # 近5日涨跌幅
        ret_5d = (closes[-1] / closes[-5] - 1) * 100 if len(closes) >= 5 else 0

        # 下影线比率 (今日)
        body = abs(closes[-1] - opens[-1])
        lower_shadow = min(opens[-1], closes[-1]) - lows[-1]
        shadow_ratio = lower_shadow / body if body > 0 else 0

        # ATR (14日)
        if len(closes) >= 15:
            tr_list = []
            for j in range(1, min(15, len(closes))):
                tr = max(
                    highs[-j] - lows[-j],
                    abs(highs[-j] - closes[-j - 1]),
                    abs(lows[-j] - closes[-j - 1]),
                )
                tr_list.append(tr)
            atr = np.mean(tr_list)
        else:
            atr = 0

        return {
            "code": code,
            "name": name_map.get(code, ""),
            "rsi": rsi_now,
            "ma5": ma5[-1] if len(ma5) >= 5 else 0,
            "ma10": ma10[-1] if len(ma10) >= 10 else 0,
            "ma20": ma20[-1] if len(ma20) >= 20 else 0,
            "ma60": ma60[-1] if len(ma60) >= 60 else 0,
            "above_ma60": above_ma60,
            "boll_upper": upper[-1] if len(upper) >= 20 else 0,
            "boll_mid": mid[-1] if len(mid) >= 20 else 0,
            "boll_lower": lower[-1] if len(lower) >= 20 else 0,
            "vol_ratio_5_20": vol_ratio_5_20,
            "range_10d": range_10d,
            "ret_5d": ret_5d,
            "shadow_ratio": shadow_ratio,
            "close": closes[-1],
            "atr": atr,
            "avg_vol_5": avg_vol_5,
            "avg_vol_20": avg_vol_20,
            "today_volume": volumes[-1] if len(volumes) > 0 else 0,
        }
    except Exception:
        return None


def _fetch_daily_klines(codes, name_map, days=120):
    """拉日K线, 计算通用技术指标 (5线程并行)

    Returns:
        list[dict] — 每只股票一条记录, 包含各种技术字段
    """
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    results = []
    fail_count = 0
    total = len(codes)
    done = 0

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {
            pool.submit(_fetch_one_mr_kline, code, name_map, start_date, end_date): code
            for code in codes
        }
        for fut in as_completed(futures):
            done += 1
            r = fut.result()
            if r is not None:
                results.append(r)
            else:
                fail_count += 1
            if done % 20 == 0:
                print(f"    日K进度: {done}/{total} (成功{len(results)} 失败{fail_count})")

    print(f"  日K技术指标完成: {len(results)}/{total} 只 (失败{fail_count})")
    return results


# 模块级缓存: _fetch_candidates + enhance_candidates 结果 (10分钟有效)
_candidates_cache = {"tech_df": None, "name_map": None, "pool_size": 0, "ts": 0}
_enhance_cache = {"results": {}, "ts": 0}  # code -> enhanced row


def _fetch_candidates(top_n_pool=100):
    """共享数据拉取: 股池 → 实时行情 → 初步过滤 → 日K技术

    10分钟内重复调用直接复用缓存 (dip_buy 09:50 → consolidation 10:15).

    Returns:
        (tech_df, name_map) — tech_df 包含实时行情+技术指标
    """
    global _candidates_cache
    now = time.time()
    # 缓存有效: 10分钟内 且 池子够大
    if (_candidates_cache["tech_df"] is not None
            and now - _candidates_cache["ts"] < 600
            and _candidates_cache["pool_size"] >= top_n_pool):
        print(f"  [缓存] 复用 {int(now - _candidates_cache['ts'])}秒前的候选数据 "
              f"({len(_candidates_cache['tech_df'])} 只)")
        return _candidates_cache["tech_df"].copy(), _candidates_cache["name_map"]

    # 1. 股池
    pool_set, name_map = get_stock_pool()

    # 2. 实时行情
    spot_df = _sina_batch_quote(list(pool_set))
    if spot_df.empty:
        print("  [警告] 实时行情为空")
        return pd.DataFrame(), name_map

    # 3. 基础过滤
    df = filter_basics(spot_df, pool_set)
    if df.empty:
        print("  [警告] 过滤后无候选")
        return pd.DataFrame(), name_map

    # 4. 取成交额 TOP N 拉日K
    if "amount" in df.columns:
        df = df.nlargest(top_n_pool, "amount")
    else:
        df = df.head(top_n_pool)

    codes_to_fetch = df["code"].tolist()
    tech_records = _fetch_daily_klines(codes_to_fetch, name_map)
    if not tech_records:
        return pd.DataFrame(), name_map

    tech_df = pd.DataFrame(tech_records)

    # 合并实时行情
    merge_cols = ["code", "price", "pct_chg", "volume_ratio", "turnover", "open", "prev_close"]
    avail_cols = [c for c in merge_cols if c in df.columns]
    tech_df = tech_df.merge(df[avail_cols], on="code", how="left", suffixes=("", "_rt"))

    # 写入缓存
    _candidates_cache["tech_df"] = tech_df.copy()
    _candidates_cache["name_map"] = name_map
    _candidates_cache["pool_size"] = top_n_pool
    _candidates_cache["ts"] = time.time()

    return tech_df, name_map


def _cached_enhance(df, name_map):
    """enhance_candidates 带10分钟缓存, 避免 dip_buy/consolidation 重复调用"""
    global _enhance_cache
    now = time.time()
    enhanced_cols = ["s_fund_flow", "s_chip"]

    # 检查缓存是否有效
    if _enhance_cache["results"] and now - _enhance_cache["ts"] < 600:
        cached = _enhance_cache["results"]
        hit = 0
        for col in enhanced_cols:
            if col not in df.columns:
                df[col] = 0.5
        for idx, row in df.iterrows():
            code = row["code"]
            if code in cached:
                for col in enhanced_cols:
                    if col in cached[code]:
                        df.at[idx, col] = cached[code][col]
                hit += 1
        miss_codes = [c for c in df["code"].tolist() if c not in cached]
        if miss_codes:
            # 对未命中的部分单独增强
            miss_df = df[df["code"].isin(miss_codes)].copy()
            try:
                miss_df = enhance_candidates(miss_df, name_map)
                for _, r in miss_df.iterrows():
                    cached[r["code"]] = {col: r.get(col, 0.5) for col in enhanced_cols}
                    for col in enhanced_cols:
                        df.loc[df["code"] == r["code"], col] = r.get(col, 0.5)
            except Exception:
                pass
        print(f"  [增强因子缓存] 命中{hit} 新增{len(miss_codes)}")
        return df

    # 无缓存, 全量调用
    df = enhance_candidates(df, name_map)
    # 写入缓存
    cached = {}
    for _, row in df.iterrows():
        cached[row["code"]] = {col: row.get(col, 0.5) for col in enhanced_cols}
    _enhance_cache["results"] = cached
    _enhance_cache["ts"] = time.time()
    return df


# ================================================================
#  低吸回调选股
# ================================================================

def _score_dip_buy(df, name_map):
    """低吸因子评分"""
    params = DIP_BUY_PARAMS
    rsi_threshold = params.get("rsi_threshold", 30)

    # 初筛: 当日涨幅 < 0 且 RSI < threshold
    if "pct_chg" in df.columns:
        df = df[df["pct_chg"] < 0].copy()
    df = df[df["rsi"] < rsi_threshold].copy()

    if df.empty:
        print(f"  低吸初筛: 无 RSI<{rsi_threshold} 的下跌股")
        return df

    print(f"  低吸初筛: {len(df)} 只 (RSI<{rsi_threshold} 且当日下跌)")

    # --- s_rsi_oversold: RSI越低分越高 ---
    df["s_rsi_oversold"] = (rsi_threshold - df["rsi"]) / rsi_threshold
    df["s_rsi_oversold"] = df["s_rsi_oversold"].clip(0, 1)

    # --- s_volume_shrink: 缩量程度 (量比越低越安全) ---
    df["s_volume_shrink"] = 1 - df["vol_ratio_5_20"].clip(0, 2) / 2
    df["s_volume_shrink"] = df["s_volume_shrink"].clip(0, 1)

    # --- s_support: 支撑位距离 (接近MA20/MA60) ---
    ma_support_dist = np.minimum(
        (df["close"] - df["ma20"]).abs() / df["close"],
        (df["close"] - df["ma60"]).abs() / df["close"],
    )
    df["s_support"] = 1 - ma_support_dist.clip(0, 0.1) / 0.1
    df["s_support"] = df["s_support"].clip(0, 1).fillna(0)

    # --- s_rebound_signal: 反弹信号 (下影线) ---
    df["s_rebound_signal"] = (df["shadow_ratio"] / 3).clip(0, 1)

    # --- s_ma_distance: 偏离均线程度 (越偏离越有反弹空间) ---
    if df["ma20"].gt(0).any():
        df["s_ma_distance"] = ((df["ma20"] - df["close"]) / df["ma20"]).clip(0, 0.1) / 0.1
    else:
        df["s_ma_distance"] = 0
    df["s_ma_distance"] = df["s_ma_distance"].clip(0, 1).fillna(0)

    # --- 基本面 ---
    try:
        fund_df = fetch_fundamental_batch(df["code"].tolist())
        if fund_df is not None and not fund_df.empty:
            fund_scores = calc_fundamental_scores(fund_df)
            df = df.merge(fund_scores[["code", "s_fundamental"]], on="code", how="left")
        else:
            df["s_fundamental"] = 0.5
    except Exception:
        df["s_fundamental"] = 0.5
    df["s_fundamental"] = df["s_fundamental"].fillna(0.5)

    # --- 增强因子 (Tushare批量, ~20秒) ---
    try:
        df = _cached_enhance(df, name_map)
    except Exception as e:
        print(f"  [增强因子异常] {e}")
        df["s_fund_flow"] = 0.5
        df["s_chip"] = 0.5

    for col in ["s_fund_flow", "s_chip"]:
        if col not in df.columns:
            df[col] = 0.5

    return df


def get_dip_buy_recommendations(top_n=None):
    """主入口 — 低吸回调选股"""
    if top_n is None:
        top_n = TOP_N

    print("\n" + "=" * 60)
    print("  低吸回调选股")
    print("=" * 60)

    tech_df, name_map = _fetch_candidates(top_n_pool=100)  # 共享缓存, consolidation复用
    if tech_df.empty:
        print("  无候选标的")
        return []

    df = _score_dip_buy(tech_df, name_map)
    if df.empty:
        print("  评分后无候选")
        return []

    # 打分排名
    weights = DIP_BUY_PARAMS["weights"]
    selected, _ = score_and_rank(df, weights, top_n=top_n * 2)

    # 新闻排雷
    codes_to_check = selected["code"].tolist()
    try:
        risky = news_risk_screen(codes_to_check, name_map)
        if risky:
            print(f"  新闻排雷: 排除 {len(risky)} 只")
            selected = selected[~selected["code"].isin(risky)]
    except Exception as e:
        print(f"  [新闻排雷异常] {e}")

    selected = selected.head(top_n)

    # 格式化输出
    results = []
    for _, row in selected.iterrows():
        code = row["code"]
        name = row.get("name", name_map.get(code, ""))
        price = row.get("price", row.get("close", 0))
        score = row.get("total_score", 0)

        labels = [f"RSI={row.get('rsi', 0):.0f}"]
        labels.append(f"5日跌{row.get('ret_5d', 0):.1f}%")
        if row.get("shadow_ratio", 0) > 1:
            labels.append("长下影线")
        try:
            labels.extend(format_enhanced_labels(row))
        except Exception:
            pass

        results.append({
            "code": code,
            "name": name,
            "price": float(price),
            "score": float(score),
            "reason": " | ".join(labels),
            "atr": float(row.get("atr", 0)),
        })

    print(f"\n  低吸回调推荐: {len(results)} 只")
    return results


# ================================================================
#  缩量整理突破选股
# ================================================================

def _score_consolidation(df, name_map):
    """缩量整理因子评分"""
    params = CONSOLIDATION_PARAMS
    vol_threshold = params.get("volume_ratio_threshold", 0.6)

    # 初筛: 近10日振幅 < 10% 且 近5日量/20日量 < vol_threshold
    df = df[df["range_10d"] < 10].copy()
    df = df[df["vol_ratio_5_20"] < vol_threshold].copy()

    if df.empty:
        print(f"  缩量整理初筛: 无符合条件 (振幅<10% 且 量比<{vol_threshold})")
        return df

    # 今日放量确认 (量比 > 1.5)
    if "volume_ratio" in df.columns:
        df = df[df["volume_ratio"] > 1.5].copy()

    if df.empty:
        print("  缩量整理: 无今日放量确认 (量比>1.5)")
        return df

    print(f"  缩量整理初筛: {len(df)} 只")

    # --- s_volume_contract: 缩量程度 (量比越低=缩量越充分, 分越高) ---
    df["s_volume_contract"] = (1 - df["vol_ratio_5_20"] / vol_threshold).clip(0, 1)

    # --- s_price_range: 价格区间收窄 (振幅越小=整理越充分) ---
    df["s_price_range"] = (1 - df["range_10d"] / 10).clip(0, 1)

    # --- s_breakout_ready: 突破准备度 (价格贴近布林上轨) ---
    if df["boll_upper"].gt(0).any():
        df["s_breakout_ready"] = (
            1 - (df["boll_upper"] - df["close"]) / df["close"]
        ).clip(0, 1)
    else:
        df["s_breakout_ready"] = 0.5

    # --- s_ma_support: 均线支撑 (MA5/MA10收拢在价格下方) ---
    ma_close = (df["close"] - df["ma20"]) / df["close"]
    df["s_ma_support"] = (1 - ma_close.abs().clip(0, 0.05) / 0.05).clip(0, 1)
    df["s_ma_support"] = df["s_ma_support"].fillna(0)

    # --- s_trend_strength: 整理前趋势强度 (近20日均线斜率) ---
    if df["ma20"].gt(0).any() and df["ma60"].gt(0).any():
        df["s_trend_strength"] = ((df["ma20"] - df["ma60"]) / df["ma60"]).clip(0, 0.1) / 0.1
    else:
        df["s_trend_strength"] = 0.5
    df["s_trend_strength"] = df["s_trend_strength"].clip(0, 1).fillna(0.5)

    # --- 基本面 ---
    try:
        fund_df = fetch_fundamental_batch(df["code"].tolist())
        if fund_df is not None and not fund_df.empty:
            fund_scores = calc_fundamental_scores(fund_df)
            df = df.merge(fund_scores[["code", "s_fundamental"]], on="code", how="left")
        else:
            df["s_fundamental"] = 0.5
    except Exception:
        df["s_fundamental"] = 0.5
    df["s_fundamental"] = df["s_fundamental"].fillna(0.5)

    # --- 增强因子 (Tushare批量, ~20秒) ---
    try:
        df = _cached_enhance(df, name_map)
    except Exception as e:
        print(f"  [增强因子异常] {e}")
        df["s_fund_flow"] = 0.5
        df["s_chip"] = 0.5

    for col in ["s_fund_flow", "s_chip"]:
        if col not in df.columns:
            df[col] = 0.5

    return df


def get_consolidation_recommendations(top_n=None):
    """主入口 — 缩量整理突破选股"""
    if top_n is None:
        top_n = TOP_N

    print("\n" + "=" * 60)
    print("  缩量整理突破选股")
    print("=" * 60)

    tech_df, name_map = _fetch_candidates(top_n_pool=100)
    if tech_df.empty:
        print("  无候选标的")
        return []

    df = _score_consolidation(tech_df, name_map)
    if df.empty:
        print("  评分后无候选")
        return []

    # 打分排名
    weights = CONSOLIDATION_PARAMS["weights"]
    selected, _ = score_and_rank(df, weights, top_n=top_n * 2)

    # 新闻排雷
    codes_to_check = selected["code"].tolist()
    try:
        risky = news_risk_screen(codes_to_check, name_map)
        if risky:
            print(f"  新闻排雷: 排除 {len(risky)} 只")
            selected = selected[~selected["code"].isin(risky)]
    except Exception as e:
        print(f"  [新闻排雷异常] {e}")

    selected = selected.head(top_n)

    # 格式化输出
    results = []
    for _, row in selected.iterrows():
        code = row["code"]
        name = row.get("name", name_map.get(code, ""))
        price = row.get("price", row.get("close", 0))
        score = row.get("total_score", 0)

        labels = [f"10日振幅{row.get('range_10d', 0):.1f}%"]
        labels.append(f"量比缩至{row.get('vol_ratio_5_20', 0):.2f}")
        if row.get("volume_ratio", 0) > 2:
            labels.append("今日强放量")
        try:
            labels.extend(format_enhanced_labels(row))
        except Exception:
            pass

        results.append({
            "code": code,
            "name": name,
            "price": float(price),
            "score": float(score),
            "reason": " | ".join(labels),
            "atr": float(row.get("atr", 0)),
        })

    print(f"\n  缩量整理推荐: {len(results)} 只")
    return results


# ================================================================
#  CLI 入口
# ================================================================

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "dip_buy"

    if mode == "dip_buy":
        items = get_dip_buy_recommendations()
        for it in items:
            print(f"  {it['code']} {it['name']} ¥{it['price']:.2f} "
                  f"得分:{it['score']:+.3f} {it['reason']}")
    elif mode == "consolidation":
        items = get_consolidation_recommendations()
        for it in items:
            print(f"  {it['code']} {it['name']} ¥{it['price']:.2f} "
                  f"得分:{it['score']:+.3f} {it['reason']}")
    else:
        print("用法:")
        print("  python3 mean_reversion_strategy.py dip_buy        # 低吸回调")
        print("  python3 mean_reversion_strategy.py consolidation   # 缩量整理突破")
        sys.exit(1)
