"""
趋势跟踪 + 板块轮动策略
=======================
策略一 (trend_follow):   日线级别趋势跟踪, 持仓 3-5 天
策略二 (sector_rotation): 板块轮动, 选最强板块龙头

用法:
  python3 trend_sector_strategy.py trend    # 趋势跟踪
  python3 trend_sector_strategy.py sector   # 板块轮动
"""

import sys
import os
import time
import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import as_completed
from resource_manager import get_pool
import logging
import warnings

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from overnight_strategy import (
    _retry, _tx_sym,
    calc_rsi, calc_ma,
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
    TREND_FOLLOW_PARAMS, SECTOR_ROTATION_PARAMS, TOP_N,
    ENHANCED_FACTOR_WEIGHTS,
)
from enhanced_factors import enhance_candidates, format_enhanced_labels


# ================================================================
#  ADX 计算
# ================================================================

def _calc_adx(highs, lows, closes, period=14):
    """计算 ADX 趋势强度指标

    Args:
        highs, lows, closes: numpy arrays
        period: ADX 周期

    Returns:
        adx: float (当前 ADX 值), 0 if insufficient data
    """
    n = len(closes)
    if n < period * 2:
        return 0

    # True Range
    tr = np.zeros(n)
    dm_plus = np.zeros(n)
    dm_minus = np.zeros(n)

    for i in range(1, n):
        h_diff = highs[i] - highs[i - 1]
        l_diff = lows[i - 1] - lows[i]

        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        dm_plus[i] = h_diff if h_diff > l_diff and h_diff > 0 else 0
        dm_minus[i] = l_diff if l_diff > h_diff and l_diff > 0 else 0

    # Smoothed averages (Wilder's smoothing)
    atr = np.zeros(n)
    di_plus = np.zeros(n)
    di_minus = np.zeros(n)

    atr[period] = np.sum(tr[1:period + 1])
    di_plus[period] = np.sum(dm_plus[1:period + 1])
    di_minus[period] = np.sum(dm_minus[1:period + 1])

    for i in range(period + 1, n):
        atr[i] = atr[i - 1] - atr[i - 1] / period + tr[i]
        di_plus[i] = di_plus[i - 1] - di_plus[i - 1] / period + dm_plus[i]
        di_minus[i] = di_minus[i - 1] - di_minus[i - 1] / period + dm_minus[i]

    # DI+ / DI-
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = np.where(atr > 0, 100 * di_plus / atr, 0)
        mdi = np.where(atr > 0, 100 * di_minus / atr, 0)

    # DX
    dx = np.zeros(n)
    for i in range(period, n):
        denom = pdi[i] + mdi[i]
        dx[i] = abs(pdi[i] - mdi[i]) / denom * 100 if denom > 0 else 0

    # ADX = smoothed DX
    adx_start = period * 2
    if adx_start >= n:
        return dx[-1] if n > period else 0

    adx = np.zeros(n)
    adx[adx_start] = np.mean(dx[period:adx_start + 1])
    for i in range(adx_start + 1, n):
        adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    return float(adx[-1])


# ================================================================
#  趋势跟踪: 日K + 技术指标
# ================================================================

def _fetch_one_trend_kline(code, name_map, start_date, end_date):
    """单只股票趋势指标计算 (供线程池调用)"""
    try:
        df = _retry(
            ak.stock_zh_a_hist_tx,
            symbol=_tx_sym(code),
            start_date=start_date, end_date=end_date, adjust="qfq"
        )
        if df.empty or len(df) < 60:
            return None

        closes = df["close"].values.astype(float)
        highs = df["high"].values.astype(float)
        lows = df["low"].values.astype(float)
        vol_col = next((c for c in ["成交量", "volume", "amount"] if c in df.columns), "amount")
        volumes = df[vol_col].values.astype(float)

        # forge 因子缓存
        try:
            from factor_forge import cache_klines_for_forge
            cache_klines_for_forge(code, df)
        except ImportError:
            pass

        # MA系列
        ma5 = calc_ma(closes, 5)
        ma10 = calc_ma(closes, 10)
        ma20 = calc_ma(closes, 20)
        ma60 = calc_ma(closes, 60)

        # 多头排列判断
        ma_aligned = (
            ma5[-1] > ma10[-1] > ma20[-1]
            if len(ma5) >= 5 and len(ma10) >= 10 and len(ma20) >= 20
            else False
        )
        full_aligned = (
            ma5[-1] > ma10[-1] > ma20[-1] > ma60[-1]
            if ma_aligned and len(ma60) >= 60 and not np.isnan(ma60[-1])
            else False
        )

        # ADX
        adx = _calc_adx(highs, lows, closes, 14)

        # MACD (简化: EMA12 - EMA26)
        if len(closes) >= 26:
            ema12 = pd.Series(closes).ewm(span=12).mean().iloc[-1]
            ema26 = pd.Series(closes).ewm(span=26).mean().iloc[-1]
            macd_hist = ema12 - ema26
        else:
            macd_hist = 0

        # 连续上涨天数
        up_days = 0
        for j in range(len(closes) - 1, 0, -1):
            if closes[j] > closes[j - 1]:
                up_days += 1
            else:
                break

        # 量价配合: 上涨时放量
        if len(volumes) >= 5 and len(closes) >= 5:
            price_up = closes[-1] > closes[-5]
            vol_up = np.mean(volumes[-5:]) > np.mean(volumes[-20:]) if len(volumes) >= 20 else False
            vol_price_confirm = 1.0 if price_up and vol_up else 0.3
        else:
            vol_price_confirm = 0.5

        # RSI
        rsi_vals = calc_rsi(closes, 14)
        rsi_now = rsi_vals[-1] if not np.isnan(rsi_vals[-1]) else 50

        # MA20斜率 (近5日)
        if len(ma20) >= 25:
            ma20_slope = (ma20[-1] - ma20[-5]) / ma20[-5] * 100
        else:
            ma20_slope = 0

        # ATR
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
            "adx": adx,
            "ma_aligned": ma_aligned,
            "full_aligned": full_aligned,
            "macd_hist": macd_hist,
            "up_days": up_days,
            "vol_price_confirm": vol_price_confirm,
            "rsi": rsi_now,
            "ma20_slope": ma20_slope,
            "close": closes[-1],
            "atr": atr,
            "ma5": ma5[-1] if len(ma5) >= 5 else 0,
            "ma20": ma20[-1] if len(ma20) >= 20 else 0,
            "above_ma60": (closes[-1] > ma60[-1]
                           if len(ma60) >= 60 and not np.isnan(ma60[-1])
                           else False),
        }
    except Exception:
        return None


def _fetch_trend_data(codes, name_map, days=120):
    """拉日K线计算趋势指标 (5线程并行)"""
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    results = []
    fail_count = 0
    total = len(codes)
    done = 0

    pool = get_pool("trend_sector_scan", max_workers=10)
    futures = {
        pool.submit(_fetch_one_trend_kline, code, name_map, start_date, end_date): code
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
            print(f"    趋势K线进度: {done}/{total} (成功{len(results)} 失败{fail_count})")

    print(f"  趋势K线完成: {len(results)}/{total} 只 (失败{fail_count})")
    return results


def _score_trend_follow(df, name_map):
    """趋势跟踪因子评分"""
    params = TREND_FOLLOW_PARAMS
    adx_threshold = params.get("adx_threshold", 25)

    # 初筛: ADX > threshold + 多头排列
    df = df[df["adx"] > adx_threshold].copy()
    df = df[df["ma_aligned"]].copy()

    if df.empty:
        print(f"  趋势初筛: 无 ADX>{adx_threshold}+多头排列 的标的")
        return df

    print(f"  趋势初筛: {len(df)} 只 (ADX>{adx_threshold} 且多头排列)")

    # --- s_trend_score: ADX趋势强度 + MA斜率 ---
    adx_score = ((df["adx"] - adx_threshold) / 50).clip(0, 1)
    slope_score = (df["ma20_slope"] / 5).clip(0, 1)
    df["s_trend_score"] = adx_score * 0.6 + slope_score * 0.4

    # --- s_ma_alignment: 多头排列程度 ---
    df["s_ma_alignment"] = df["full_aligned"].astype(float) * 0.7 + 0.3

    # --- s_momentum: 动量 (MACD + 连续上涨) ---
    macd_norm = (df["macd_hist"] / df["close"] * 100).clip(-2, 2) / 2 * 0.5 + 0.5
    up_norm = (df["up_days"] / 5).clip(0, 1)
    df["s_momentum"] = macd_norm * 0.6 + up_norm * 0.4

    # --- s_volume_confirm: 量价配合 ---
    df["s_volume_confirm"] = df["vol_price_confirm"]

    # --- s_sector_trend: 所属板块趋势 (简化: 用板块分类) ---
    df["s_sector_trend"] = 0.5  # 默认中性, 后续可对接板块数据

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

    # --- 增强因子 ---
    try:
        df = enhance_candidates(df, name_map)
    except Exception as e:
        print(f"  [增强因子异常] {e}")
        df["s_fund_flow"] = 0.5
        df["s_chip"] = 0.5

    for col in ["s_fund_flow", "s_chip"]:
        if col not in df.columns:
            df[col] = 0.5

    return df


def get_trend_follow_recommendations(top_n=None):
    """主入口 — 趋势跟踪选股"""
    if top_n is None:
        top_n = TOP_N

    print("\n" + "=" * 60)
    print("  趋势跟踪选股")
    print("=" * 60)

    # 1. 股池 + 实时行情
    pool_set, name_map = get_stock_pool()
    spot_df = _sina_batch_quote(list(pool_set))
    if spot_df.empty:
        print("  [警告] 实时行情为空")
        return []

    df = filter_basics(spot_df, pool_set)
    if df.empty:
        return []

    # 取成交额 TOP 100
    if "amount" in df.columns:
        df = df.nlargest(200, "amount")

    # 2. 拉日K计算趋势指标
    tech_records = _fetch_trend_data(df["code"].tolist(), name_map)
    if not tech_records:
        return []

    tech_df = pd.DataFrame(tech_records)
    merge_cols = ["code", "price", "pct_chg", "volume_ratio", "turnover"]
    avail_cols = [c for c in merge_cols if c in df.columns]
    tech_df = tech_df.merge(df[avail_cols], on="code", how="left", suffixes=("", "_rt"))

    # 3. 评分
    scored_df = _score_trend_follow(tech_df, name_map)
    if scored_df.empty:
        print("  评分后无候选")
        return []

    # 4. 排名 — 优先使用在线学习调优后的权重
    try:
        from auto_optimizer import get_tunable_params
        tuned = get_tunable_params("trend_follow")
        weights = tuned.get("weights", TREND_FOLLOW_PARAMS["weights"])
    except Exception:
        weights = TREND_FOLLOW_PARAMS["weights"]
    selected, _ = score_and_rank(scored_df, weights, top_n=top_n * 2, strategy="趋势跟踪选股")

    # 5. 新闻排雷
    try:
        risky = news_risk_screen(selected["code"].tolist(), name_map)
        if risky:
            print(f"  新闻排雷: 排除 {len(risky)} 只")
            selected = selected[~selected["code"].isin(risky)]
    except Exception as e:
        print(f"  [新闻排雷异常] {e}")

    selected = selected.head(top_n)

    # 6. 格式化输出 (标记 holding_days)
    holding_days = TREND_FOLLOW_PARAMS.get("holding_days", 5)
    results = []
    for _, row in selected.iterrows():
        code = row["code"]
        name = row.get("name", name_map.get(code, ""))
        price = row.get("price", row.get("close", 0))
        score = row.get("total_score", 0)

        labels = [f"ADX={row.get('adx', 0):.0f}"]
        if row.get("full_aligned"):
            labels.append("完全多头排列")
        elif row.get("ma_aligned"):
            labels.append("多头排列")
        labels.append(f"连涨{row.get('up_days', 0)}天")
        labels.append(f"持仓T+{holding_days}")
        try:
            labels.extend(format_enhanced_labels(row))
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

        # 附带选股因子分数 (供 ML 训练)
        factor_scores = {c: float(row[c]) for c in row.index if c.startswith("s_") and pd.notna(row.get(c))}
        results.append({
            "code": code,
            "name": name,
            "price": float(price),
            "score": float(score),
            "reason": " | ".join(labels),
            "atr": float(row.get("atr", 0)),
            "holding_days": holding_days,
            "factor_scores": factor_scores,
        })

    print(f"\n  趋势跟踪推荐: {len(results)} 只 (持仓T+{holding_days})")
    return results


# ================================================================
#  板块轮动
# ================================================================

def _get_sector_ranking():
    """获取板块近期涨幅排名

    Returns:
        list[dict] — [{name, pct_5d, rank}, ...]
    """
    try:
        df = _retry_heavy(ak.stock_board_industry_name_em)
        if df.empty:
            return []

        # 列名可能不同, 尝试多种
        name_col = None
        for c in ["板块名称", "名称"]:
            if c in df.columns:
                name_col = c
                break
        if not name_col:
            name_col = df.columns[0]

        pct_col = None
        for c in ["涨跌幅", "最新涨跌幅"]:
            if c in df.columns:
                pct_col = c
                break
        if not pct_col:
            pct_col = df.columns[1] if len(df.columns) > 1 else None

        if not pct_col:
            return []

        df[pct_col] = pd.to_numeric(df[pct_col], errors="coerce")
        df = df.dropna(subset=[pct_col])
        df = df.sort_values(pct_col, ascending=False)

        results = []
        for i, (_, row) in enumerate(df.iterrows()):
            results.append({
                "name": row[name_col],
                "pct": float(row[pct_col]),
                "rank": i + 1,
            })
        return results

    except Exception as e:
        print(f"  [板块排名异常] {e}")
        return []


def _get_sector_stocks(sector_name):
    """获取板块成分股

    Returns:
        list[str] — 股票代码列表
    """
    try:
        df = _retry_heavy(ak.stock_board_industry_cons_em, symbol=sector_name)
        if df.empty:
            return []

        code_col = "代码" if "代码" in df.columns else df.columns[0]
        codes = df[code_col].astype(str).str.zfill(6).tolist()
        # 排除科创/北交
        codes = [c for c in codes if not c.startswith(("688", "8", "4"))]
        return codes
    except Exception as e:
        print(f"    板块成分获取失败({sector_name}): {e}")
        return []


def get_sector_rotation_recommendations(top_n=None):
    """主入口 — 板块轮动选股"""
    if top_n is None:
        top_n = TOP_N

    print("\n" + "=" * 60)
    print("  板块轮动选股")
    print("=" * 60)

    params = SECTOR_ROTATION_PARAMS
    top_sectors = params.get("top_sectors", 3)
    picks_per_sector = params.get("picks_per_sector", 1)

    # 1. 获取板块排名
    sector_ranking = _get_sector_ranking()
    if not sector_ranking:
        print("  [警告] 板块排名获取失败")
        return []

    top_list = sector_ranking[:top_sectors]
    print(f"  TOP {top_sectors} 板块:")
    for s in top_list:
        print(f"    {s['rank']}. {s['name']} 涨{s['pct']:+.2f}%")

    # 2. 获取各板块成分股
    all_candidates = []
    name_map = {}

    for sector_info in top_list:
        sector_name = sector_info["name"]
        codes = _get_sector_stocks(sector_name)
        if not codes:
            continue

        # 获取实时行情
        time.sleep(0.5)
        spot_df = _sina_batch_quote(codes)
        if spot_df.empty:
            continue

        # 更新 name_map
        for _, row in spot_df.iterrows():
            name_map[row["code"]] = row["name"]

        # 基础过滤
        df = spot_df.copy()
        df["pct_chg"] = (df["price"] - df["prev_close"]) / df["prev_close"] * 100
        df = df[df["price"] > 0].copy()
        df = df[~df["name"].str.contains("ST|\\*ST", na=False)].copy()
        # 跟涨过滤: 排除涨停/跌的, 只要 0 < 涨幅 < 板块涨幅*0.8
        sector_pct = sector_info["pct"]
        df = df[df["pct_chg"] > 0].copy()
        df = df[df["pct_chg"] < 9.8].copy()
        if sector_pct > 0:
            df = df[df["pct_chg"] < sector_pct * 0.8].copy()

        if df.empty:
            continue

        df["sector_name"] = sector_name
        df["sector_pct"] = sector_pct
        df["sector_rank"] = sector_info["rank"]

        # 量比估算
        if "amount" in df.columns:
            df["volume_ratio"] = df["amount"].rank(pct=True) * 5
        else:
            df["volume_ratio"] = 2.0

        # --- 板块轮动因子 ---
        # s_sector_momentum: 板块动量 (基于板块涨幅排名)
        max_rank = len(sector_ranking)
        df["s_sector_momentum"] = (1 - sector_info["rank"] / max_rank) if max_rank > 0 else 0.5

        # s_sector_flow: 板块资金 (简化: 用板块涨幅代替)
        df["s_sector_flow"] = (sector_pct / 5).clip(0, 1) if sector_pct > 0 else 0

        # s_sector_breadth: 板块广度 (上涨占比)
        up_ratio = (df["pct_chg"] > 0).mean()
        df["s_sector_breadth"] = float(up_ratio)

        # s_follow_potential: 跟涨潜力评分 (替代 s_leader_score)
        # gap_score: 补涨空间 = (板块涨幅 - 个股涨幅) / 板块涨幅
        gap_score = ((sector_pct - df["pct_chg"]) / sector_pct).clip(0, 1) if sector_pct > 0 else 0.5
        # vol_rank: 成交额排名百分位
        vol_rank = df["volume_ratio"].rank(pct=True)
        # position_score: 盘中位置偏强 (price - low) / (high - low)
        rng = df["high"] - df["low"] if "high" in df.columns and "low" in df.columns else None
        if rng is not None:
            position_score = ((df["price"] - df["low"]) / rng.replace(0, np.nan)).fillna(0.5).clip(0, 1)
        else:
            position_score = 0.5
        # turnover_score: 换手 3~8% 最优
        if "turnover" in df.columns:
            turnover_score = df["turnover"].apply(
                lambda t: 1.0 if 3 <= t <= 8 else (0.6 if (1 <= t < 3 or 8 < t <= 12) else 0.2)
            )
        else:
            turnover_score = 0.5
        df["s_follow_potential"] = (
            gap_score * 0.35
            + vol_rank * 0.30
            + position_score * 0.20
            + turnover_score * 0.15
        )

        # s_relative_strength: 相对大盘强度 (用个股涨幅)
        df["s_relative_strength"] = (df["pct_chg"] / 5).clip(0, 1)

        # s_fundamental & s_chip: 默认中性
        df["s_fundamental"] = 0.5
        df["s_chip"] = 0.5

        all_candidates.append(df)

    if not all_candidates:
        print("  无候选标的")
        return []

    combined = pd.concat(all_candidates, ignore_index=True)
    print(f"  合并候选: {len(combined)} 只 (来自 {len(all_candidates)} 个板块)")

    # 3. 打分排名 (每板块选 picks_per_sector 只) — 优先使用在线学习调优后的权重
    try:
        from auto_optimizer import get_tunable_params
        tuned = get_tunable_params("sector_rotation")
        weights = tuned.get("weights", SECTOR_ROTATION_PARAMS["weights"])
    except Exception:
        weights = SECTOR_ROTATION_PARAMS["weights"]
    combined["total_score"] = 0
    for col, w in weights.items():
        if col in combined.columns:
            combined["total_score"] += combined[col].fillna(0) * w

    # ML 融合: 规则分 + ML预测 → fused_score
    try:
        from ml_factor_model import predict_scores, fuse_scores
        ml_cands = []
        for _, row in combined.iterrows():
            fs = {c: float(row[c]) for c in row.index
                  if c.startswith("s_") and pd.notna(row.get(c))}
            ml_cands.append({
                "code": row.get("code", ""),
                "factor_scores": fs,
                "total_score": float(row.get("total_score", 0)),
            })
        ml_cands = predict_scores(ml_cands, strategy="板块轮动选股")
        ml_cands = fuse_scores(ml_cands)
        ml_map = {c["code"]: c for c in ml_cands if c.get("code")}
        for idx, row in combined.iterrows():
            info = ml_map.get(row.get("code", ""), {})
            if info.get("fused_score") is not None:
                combined.at[idx, "total_score"] = info["fused_score"]
        ml_active = sum(1 for c in ml_cands if abs(c.get("ml_score", 0)) > 0.001)
        if ml_active > 0:
            print(f"  [ML融合] {ml_active}/{len(ml_cands)} 只获得ML预测 (策略: 板块轮动选股)")
    except ImportError:
        pass
    except Exception as e:
        print(f"  [ML融合跳过] {e}")

    combined = combined.sort_values("total_score", ascending=False)

    # 全量候选写入缓冲区 (实盘数据采集)
    try:
        import intraday_strategy as _is
        _is._scored_buffer = []
        for _, row in combined.iterrows():
            fs = {c: float(row[c]) for c in row.index
                  if c.startswith("s_") and pd.notna(row.get(c))}
            if not fs:
                continue
            _is._scored_buffer.append({
                "code": row.get("code", ""),
                "name": row.get("name", name_map.get(row.get("code", ""), "")),
                "price": float(row.get("price", 0)),
                "score": float(row.get("total_score", 0)),
                "factor_scores": fs,
            })
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    # 每板块限选
    selected_rows = []
    sector_picks = {}
    for _, row in combined.iterrows():
        sec = row.get("sector_name", "")
        cnt = sector_picks.get(sec, 0)
        if cnt < picks_per_sector:
            selected_rows.append(row)
            sector_picks[sec] = cnt + 1
        if len(selected_rows) >= top_n:
            break

    if not selected_rows:
        return []

    # 4. 新闻排雷
    selected = pd.DataFrame(selected_rows)
    try:
        risky = news_risk_screen(selected["code"].tolist(), name_map)
        if risky:
            print(f"  新闻排雷: 排除 {len(risky)} 只")
            selected = selected[~selected["code"].isin(risky)]
    except Exception as e:
        print(f"  [新闻排雷异常] {e}")

    # 5. 格式化输出
    results = []
    for _, row in selected.iterrows():
        code = row["code"]
        name = row.get("name", name_map.get(code, ""))
        price = float(row.get("price", 0))
        score = float(row.get("total_score", 0))

        labels = [f"板块:{row.get('sector_name', '')}"]
        labels.append(f"板块涨{row.get('sector_pct', 0):+.1f}%")
        labels.append(f"个股涨{row.get('pct_chg', 0):+.1f}%")
        gap = row.get('sector_pct', 0) - row.get('pct_chg', 0)
        if gap > 0:
            labels.append(f"补涨空间{gap:.1f}%")

        # 附带选股因子分数 (供 ML 训练)
        factor_scores = {c: float(row[c]) for c in row.index if c.startswith("s_") and pd.notna(row.get(c))}
        results.append({
            "code": code,
            "name": name,
            "price": price,
            "score": score,
            "reason": " | ".join(labels),
            "atr": 0,
            "factor_scores": factor_scores,
        })

    print(f"\n  板块轮动推荐: {len(results)} 只")
    return results


# ================================================================
#  CLI 入口
# ================================================================

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "trend"

    if mode == "trend":
        items = get_trend_follow_recommendations()
        for it in items:
            print(f"  {it['code']} {it['name']} ¥{it['price']:.2f} "
                  f"得分:{it['score']:+.3f} {it['reason']}")
    elif mode == "sector":
        items = get_sector_rotation_recommendations()
        for it in items:
            print(f"  {it['code']} {it['name']} ¥{it['price']:.2f} "
                  f"得分:{it['score']:+.3f} {it['reason']}")
    else:
        print("用法:")
        print("  python3 trend_sector_strategy.py trend    # 趋势跟踪")
        print("  python3 trend_sector_strategy.py sector   # 板块轮动")
        sys.exit(1)
