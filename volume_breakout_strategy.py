"""
10:00 放量突破策略
==================
盘中放量突破选股 → 捕捉早盘主力拉升

逻辑:
  1. 获取中证1000股池 → 新浪批量实时行情
  2. 初筛: 涨幅1%-7% + 量比>2.0 + 换手>1% + 现价>开盘价
  3. 取 TOP 50 → 拉日K线计算技术指标
  4. 基本面过滤
  5. 多因子打分 → 新闻排雷 → 输出 TOP 3

用法:
  python3 volume_breakout_strategy.py
"""

import sys
import time
import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings

warnings.filterwarnings("ignore")

from overnight_strategy import (
    _retry, _tx_sym, _sina_market,
    calc_rsi, calc_bollinger, calc_ma,
    classify_sector, SECTOR_RULES,
    fetch_fundamental_batch, apply_fundamental_filters, calc_fundamental_scores,
    news_risk_screen, RISK_KEYWORDS, POSITIVE_KEYWORDS,
    REQUEST_DELAY, RETRY_TIMES,
)
from intraday_strategy import (
    _sina_batch_quote, get_stock_pool, filter_basics,
    get_hot_concept_names, score_and_rank,
    _retry_heavy,
)
from config import BREAKOUT_PARAMS, TOP_N, ENHANCED_FACTOR_WEIGHTS
from enhanced_factors import enhance_candidates, format_enhanced_labels


# ================================================================
#  技术指标计算 (放量突破专用, 增加均线对齐 + 阻力突破)
# ================================================================

def _fetch_one_breakout(code, name_map, start_date, end_date):
    """单只股票放量突破指标计算 (供线程池调用)"""
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
        vol_col = next((c for c in ["成交量", "volume", "amount"] if c in df.columns), "amount")
        volumes = df[vol_col].values.astype(float)

        # 存入 intraday K 线缓存 (供 chip 模块复用)
        try:
            from intraday_strategy import _kline_cache
            lows = df["low"].values.astype(float) if "low" in df.columns else highs
            _kline_cache[code] = {"close": closes, "high": highs, "low": lows}
        except ImportError:
            pass

        rsi_vals = calc_rsi(closes, 14)
        rsi_now = rsi_vals[-1] if not np.isnan(rsi_vals[-1]) else 50

        ma60 = calc_ma(closes, 60)
        above_ma60 = closes[-1] > ma60[-1] if len(ma60) >= 60 and not np.isnan(ma60[-1]) else False

        daily_ret = np.diff(closes[-21:]) / closes[-21:-1]
        volatility = np.std(daily_ret) * np.sqrt(252) if len(daily_ret) >= 10 else 999

        high_5d = np.max(highs[-5:])
        pullback_5d = closes[-1] / high_5d - 1
        high_20d = np.max(highs[-20:])
        pullback_20d = closes[-1] / high_20d - 1

        ret_3d = closes[-1] / closes[-3] - 1 if len(closes) >= 3 else 0

        if len(volumes) >= 6:
            avg_vol_5 = np.mean(volumes[-6:-1])
            vol_ratio_daily = volumes[-1] / avg_vol_5 if avg_vol_5 > 0 else 1
            consecutive_vol = all(
                volumes[-j] > avg_vol_5 for j in range(1, min(4, len(volumes)))
            )
        else:
            vol_ratio_daily = 1
            consecutive_vol = False

        ma5 = calc_ma(closes, 5)
        ma10 = calc_ma(closes, 10)
        ma20 = calc_ma(closes, 20)

        ma_aligned = False
        ma5_cross = False
        if (len(ma5) >= 20 and len(ma10) >= 20 and len(ma20) >= 20
                and not np.isnan(ma5[-1]) and not np.isnan(ma10[-1]) and not np.isnan(ma20[-1])):
            ma_aligned = (closes[-1] > ma5[-1] > ma10[-1] > ma20[-1])
            if len(ma5) >= 3 and len(ma10) >= 3:
                ma5_cross = (ma5[-1] > ma10[-1]) and (ma5[-3] <= ma10[-3])

        resistance_ratio = closes[-1] / high_20d if high_20d > 0 else 0

        return {
            "code": code,
            "name": name_map.get(code, ""),
            "latest_close": closes[-1],
            "rsi": rsi_now,
            "above_ma60": above_ma60,
            "volatility": volatility,
            "pullback_5d": pullback_5d,
            "pullback_20d": pullback_20d,
            "ret_3d": ret_3d,
            "vol_ratio_daily": vol_ratio_daily,
            "consecutive_vol": consecutive_vol,
            "ma_aligned": ma_aligned,
            "ma5_cross": ma5_cross,
            "resistance_ratio": resistance_ratio,
        }
    except Exception:
        return "FAIL"


def calc_breakout_technicals(codes, name_map, days=120):
    """
    拉日K线, 计算放量突破专用技术指标 (5线程并行):
    - RSI / MA60 / 波动率 / 回撤 / 3日收益
    - 量比强度 + 连续3日放量
    - 均线多头排列 + MA5金叉MA10
    - 20日新高突破度
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    results = []
    fail_count = 0
    total = len(codes)
    done_count = 0

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {
            pool.submit(_fetch_one_breakout, code, name_map, start_date, end_date): code
            for code in codes
        }
        for fut in as_completed(futures):
            done_count += 1
            r = fut.result()
            if r is None:
                continue
            elif r == "FAIL":
                fail_count += 1
            else:
                results.append(r)
            if done_count % 20 == 0:
                print(f"    技术面进度: {done_count}/{total}  有效: {len(results)}  "
                      f"失败: {fail_count}")

    print(f"    技术面完成: {len(results)} 只有效, {fail_count} 只失败")
    return pd.DataFrame(results)


# ================================================================
#  因子打分
# ================================================================

def _zscore(series):
    """Z-score标准化, 避免全零std"""
    s = series.fillna(0)
    std = s.std()
    if std == 0 or np.isnan(std):
        return s * 0
    return (s - s.mean()) / std


def calc_breakout_scores(df, hot_names, hot_leaders):
    """计算放量突破8因子得分"""
    df = df.copy()

    # --- s_volume_breakout (25%): 量比强度 + 连续放量 ---
    df["s_volume_breakout"] = _zscore(df["vol_ratio_daily"])
    # 连续3日放量额外加0.5分
    df.loc[df["consecutive_vol"], "s_volume_breakout"] += 0.5

    # --- s_ma_alignment (20%): 均线多头排列 + 金叉 ---
    df["s_ma_alignment"] = 0.0
    df.loc[df["ma_aligned"], "s_ma_alignment"] = 1.0
    df.loc[df["ma5_cross"], "s_ma_alignment"] += 0.5

    # --- s_momentum (15%): 日内涨幅1-3%最优 + 3日趋势 ---
    # 日内涨幅分: 1-3% 满分, 超过3%线性衰减, 超过5%再衰减
    pct = df["pct_chg"] if "pct_chg" in df.columns else 0
    pct_score = pd.Series(0.0, index=df.index)
    if "pct_chg" in df.columns:
        pct_score = df["pct_chg"].apply(
            lambda x: 1.0 if 1 <= x <= 3 else (0.6 if 3 < x <= 5 else (0.3 if x > 5 else 0.5))
        )
    df["s_momentum"] = _zscore(pct_score + df["ret_3d"].clip(-0.1, 0.1) * 5)

    # --- s_rsi (10%): RSI 45-65 最优 ---
    df["s_rsi"] = df["rsi"].apply(
        lambda x: 1.0 if 45 <= x <= 65 else (0.5 if 35 <= x < 45 or 65 < x <= 75 else 0.0)
    )
    df["s_rsi"] = _zscore(df["s_rsi"])

    # --- s_fundamental (10%): 由外部 calc_fundamental_scores 提供, 此处留占位 ---
    if "s_fundamental" not in df.columns:
        df["s_fundamental"] = 0

    # --- s_hot (10%): 热门板块龙头加分 ---
    df["s_hot"] = 0.0
    if hot_names and hot_leaders:
        for idx, row in df.iterrows():
            name = row.get("name", "")
            sector = row.get("sector", classify_sector(name))
            if name in hot_leaders:
                df.at[idx, "s_hot"] = 1.5  # 龙头股
            elif any(kw in name for kw in hot_names):
                df.at[idx, "s_hot"] = 0.5
    df["s_hot"] = _zscore(df["s_hot"])

    # --- s_turnover (5%): 换手率 2%-8% 最优 ---
    if "turnover" in df.columns:
        df["s_turnover"] = df["turnover"].apply(
            lambda x: 1.0 if 2 <= x <= 8 else (0.5 if 1 <= x < 2 or 8 < x <= 15 else 0.0)
        )
    else:
        df["s_turnover"] = 0.5
    df["s_turnover"] = _zscore(df["s_turnover"])

    # --- s_resistance_break (5%): 接近/突破20日新高 ---
    df["s_resistance_break"] = df["resistance_ratio"].apply(
        lambda x: 1.0 if x >= 0.98 else (0.5 if x >= 0.95 else 0.0)
    )
    df["s_resistance_break"] = _zscore(df["s_resistance_break"])

    return df


# ================================================================
#  主策略流程
# ================================================================

def run_breakout(top_n=None):
    """放量突破策略主流程"""
    if top_n is None:
        top_n = TOP_N

    params = BREAKOUT_PARAMS
    t0 = time.time()
    print("=" * 65)
    print("  盘中策略: 10:00 放量突破选股")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    # ---- 第1步: 获取数据 ----
    print("\n[1/6] 获取基础数据...")
    pool_set, name_map = get_stock_pool()
    spot_df = _sina_batch_quote(list(pool_set))
    print(f"  实时行情: {len(spot_df)} 只")
    hot_names, hot_leaders = get_hot_concept_names()

    # ---- 第2步: 放量突破初筛 ----
    print("\n[2/6] 放量突破初筛...")
    df = filter_basics(spot_df, pool_set)

    # 计算涨幅 (确保有 pct_chg)
    if "pct_chg" not in df.columns:
        df["pct_chg"] = (df["price"] - df["prev_close"]) / df["prev_close"] * 100

    before = len(df)
    df = df[(df["pct_chg"] >= params["pct_min"]) & (df["pct_chg"] <= params["pct_max"])].copy()
    print(f"  涨幅 {params['pct_min']}%-{params['pct_max']}%: {before} → {len(df)}")

    before = len(df)
    df = df[df["volume_ratio"] > params["volume_ratio_min"]].copy()
    print(f"  量比 > {params['volume_ratio_min']}: {before} → {len(df)}")

    before = len(df)
    df = df[df["turnover"] > params["turnover_min"]].copy()
    print(f"  换手 > {params['turnover_min']}%: {before} → {len(df)}")

    before = len(df)
    df = df[df["price"] > df["open"]].copy()
    print(f"  现价 > 开盘价: {before} → {len(df)}")

    if df.empty:
        print("\n  初筛后无满足条件的标的, 策略结束")
        return None

    # 取量比最高的 TOP 50 进入精选
    if len(df) > 50:
        df = df.nlargest(50, "volume_ratio")
        print(f"  取量比 TOP 50 进入精选")
    else:
        print(f"  全部 {len(df)} 只进入精选")

    candidate_codes = df["code"].tolist()
    candidate_turnover = dict(zip(df["code"], df["turnover"]))
    candidate_pct = dict(zip(df["code"], df["pct_chg"]))
    candidate_vr = dict(zip(df["code"], df["volume_ratio"]))

    # ---- 第3步: 技术指标 ----
    print("\n[3/6] 计算技术指标...")
    tech_df = calc_breakout_technicals(candidate_codes, name_map, days=120)

    if tech_df.empty:
        print("  技术指标计算无有效结果, 策略结束")
        return None

    # 回填实时数据
    tech_df["turnover"] = tech_df["code"].map(candidate_turnover)
    tech_df["pct_chg"] = tech_df["code"].map(candidate_pct)
    tech_df["volume_ratio"] = tech_df["code"].map(candidate_vr)

    # 基础技术面过滤
    before = len(tech_df)
    tech_df = tech_df[tech_df["volatility"] < 0.45].copy()
    print(f"  波动率 < 45%: {before} → {len(tech_df)}")

    before = len(tech_df)
    tech_df = tech_df[tech_df["pullback_20d"] > -0.25].copy()
    print(f"  20日回撤 > -25%: {before} → {len(tech_df)}")

    if tech_df.empty:
        print("  技术面过滤后无标的, 策略结束")
        return None

    # ---- 第4步: 基本面过滤 ----
    print("\n[4/6] 基本面过滤...")
    fund_df = fetch_fundamental_batch()
    tech_df = apply_fundamental_filters(tech_df, fund_df)
    print(f"  基本面过滤后: {len(tech_df)} 只")

    if tech_df.empty:
        print("  基本面过滤后无标的, 策略结束")
        return None

    # 基本面打分
    tech_df = calc_fundamental_scores(tech_df, fund_df)

    # ---- 第4.5步: 多维度增强因子 ----
    tech_df = enhance_candidates(tech_df, name_map)

    # ---- 第5步: 多因子打分 ----
    print("\n[5/6] 多因子打分...")
    tech_df = calc_breakout_scores(tech_df, hot_names, hot_leaders)

    # 优先使用调优后的权重 (实验/优化采纳), 降级用 config.py 默认
    try:
        from auto_optimizer import get_tunable_params
        tuned = get_tunable_params("breakout")
        weights = tuned.get("weights", params["weights"])
    except Exception:
        weights = params["weights"]
    selected, full_df = score_and_rank(tech_df, weights, top_n=top_n)

    if selected.empty:
        print("  打分排名后无标的, 策略结束")
        return None

    # ---- 第6步: 新闻排雷 ----
    print("\n[6/6] 新闻排雷...")
    safe_codes, risk_info, news_scores = news_risk_screen(
        selected["code"].tolist(), name_map
    )
    safe_df = selected[selected["code"].isin(safe_codes)].copy()

    if safe_df.empty:
        print("  新闻排雷后无安全标的")
        # 降级: 取风险最低的
        safe_df = selected.head(top_n)
        print(f"  降级取前 {len(safe_df)} 只 (请关注新闻风险)")

    # 添加新闻情绪分
    safe_df["news_score"] = safe_df["code"].map(news_scores).fillna(0)

    # ---- 输出结果 ----
    elapsed = time.time() - t0
    print(f"\n{'=' * 65}")
    print(f"  放量突破推荐 TOP {len(safe_df)} (耗时 {elapsed:.0f}s)")
    print(f"{'=' * 65}")

    for rank, (_, row) in enumerate(safe_df.iterrows(), 1):
        sector_tag = row.get("sector", classify_sector(row.get("name", "")))
        trend_tag = "↑MA60上方" if row.get("above_ma60") else "↓MA60下方"
        ma_tag = "多头排列" if row.get("ma_aligned") else ""
        vol_tag = "连续放量" if row.get("consecutive_vol") else ""

        news_tag = "新闻无异常"
        code = row["code"]
        if code in risk_info:
            info = risk_info[code]
            if info["risk_keywords"]:
                news_tag = f"⚠风险:[{','.join(info['risk_keywords'])}]"
            if info["positive_keywords"]:
                news_tag += f" ✓正面:[{','.join(info['positive_keywords'])}]"

        fund_tags = []
        if "profit_growth" in row.index and pd.notna(row.get("profit_growth")):
            fund_tags.append(f"利润增长={row['profit_growth']:+.1f}%")
        if "roe" in row.index and pd.notna(row.get("roe")):
            fund_tags.append(f"ROE={row['roe']:.1f}%")
        fund_label = "  ".join(fund_tags) if fund_tags else "无数据"

        # 增强因子标签
        enh = format_enhanced_labels(row)
        enh_parts = [v for v in [enh["fund_flow_label"], enh["lhb_label"], enh["chip_label"]] if v]
        enh_line = "  ".join(enh_parts) if enh_parts else "无增强数据"

        print(f"""
  {rank}. {row['code']} {row.get('name',''):　<8} {sector_tag} | 得分: {row['total_score']:+.3f} | 现价: {row.get('price', row['latest_close']):.2f}
     放量: 量比={row.get('volume_ratio', 0):.1f}  换手={row.get('turnover', 0):.1f}%  {vol_tag}
     涨幅: {row.get('pct_chg', 0):+.1f}%  3日收益={row.get('ret_3d', 0):+.1%}  {ma_tag}
     技术: RSI={row['rsi']:.0f}  {trend_tag}  波动={row['volatility']:.0%}  突破度={row.get('resistance_ratio', 0):.1%}
     基本面: {fund_label}
     增强: {enh_line}
     风控: {news_tag}""")

    # 保存CSV
    today_str = datetime.now().strftime("%Y%m%d")
    output = f"breakout_result_{today_str}.csv"
    full_df.to_csv(output, index=False, encoding="utf-8-sig")
    print(f"\n完整排名已保存至: {output}")
    return safe_df


# ================================================================
#  标准化包装函数 (供 scheduler 调用)
# ================================================================

def get_breakout_recommendations(top_n=None):
    """包装 run_breakout(), 返回标准化 list[dict]"""
    if top_n is None:
        top_n = TOP_N
    try:
        safe_df = run_breakout(top_n=top_n)
    except Exception as e:
        print(f"[放量突破策略异常] {e}")
        return []
    if safe_df is None or safe_df.empty:
        return []
    results = []
    for _, r in safe_df.iterrows():
        price = r.get("latest_close", r.get("price", 0))
        reason_parts = []
        if "pct_chg" in r.index and pd.notna(r.get("pct_chg")):
            reason_parts.append(f"涨幅{r['pct_chg']:+.1f}%")
        if "volume_ratio" in r.index and pd.notna(r.get("volume_ratio")):
            reason_parts.append(f"量比{r['volume_ratio']:.1f}")
        if r.get("ma_aligned"):
            reason_parts.append("均线多头")
        if r.get("consecutive_vol"):
            reason_parts.append("连续放量")
        if "rsi" in r.index and pd.notna(r.get("rsi")):
            reason_parts.append(f"RSI={r['rsi']:.0f}")
        if "sector" in r.index:
            reason_parts.append(r["sector"])
        # 增强因子标签
        enh = format_enhanced_labels(r)
        for label in [enh["fund_flow_label"], enh["lhb_label"], enh["chip_label"]]:
            if label:
                reason_parts.append(label)
        # 附带选股因子分数 (供学习引擎分析)
        factor_scores = {c: float(r[c]) for c in r.index if c.startswith("s_") and pd.notna(r.get(c))}
        results.append({
            "code": r["code"],
            "name": r.get("name", ""),
            "price": float(price) if pd.notna(price) else 0,
            "score": float(r.get("total_score", 0)),
            "reason": " | ".join(reason_parts),
            "factor_scores": factor_scores,
        })
    return results


# ================================================================
#  入口
# ================================================================

if __name__ == "__main__":
    run_breakout()
