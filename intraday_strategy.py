"""
日内双策略: 集合竞价 + 尾盘短线
================================
策略一 (auction):  9:25竞价结束选股 → 9:30开盘买入 → T+1卖出
策略二 (afternoon): 14:30分析选股 → 14:50-15:00买入 → T+1卖出

用法:
  python3 intraday_strategy.py auction     # 9:25竞价选股
  python3 intraday_strategy.py afternoon   # 14:30尾盘选股
  python3 intraday_strategy.py             # 根据当前时间自动选择
"""

import sys
import akshare as ak
import pandas as pd
import numpy as np
import time
import requests as _requests
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
from enhanced_factors import enhance_candidates, format_enhanced_labels


# ================================================================
#  公共函数
# ================================================================

def _retry_heavy(func, *args, retries=5, delay=3, **kwargs):
    """统一 API 调用入口 — 全部走 api_guard 限流+断路器+智能重试"""
    from api_guard import guarded_call
    return guarded_call(func, *args, source="akshare", retries=retries)


def _sina_batch_quote(codes, batch_size=800):
    """
    新浪批量实时行情 (直接HTTP, 全部走 api_guard 防护)
    每批最多800只, 返回DataFrame
    """
    from api_guard import guarded_sina_request
    headers = {"Referer": "https://finance.sina.com.cn"}
    all_rows = []

    for start in range(0, len(codes), batch_size):
        batch = codes[start:start + batch_size]
        symbols = ",".join(_tx_sym(c).replace("sh", "sh").replace("sz", "sz") for c in batch)
        url = f"https://hq.sinajs.cn/list={symbols}"
        try:
            text = guarded_sina_request(url, headers, timeout=15)
            for line in text.strip().split("\n"):
                parts = line.split("=")
                if len(parts) != 2:
                    continue
                raw_code = parts[0].split("_")[-1]  # sh600036 / sz000001
                code = raw_code[2:]  # 去掉sh/sz前缀
                vals = parts[1].strip('";\n').split(",")
                if len(vals) < 32 or not vals[0]:
                    continue
                all_rows.append({
                    "code": code,
                    "name": vals[0],
                    "open": float(vals[1]) if vals[1] else 0,
                    "prev_close": float(vals[2]) if vals[2] else 0,
                    "price": float(vals[3]) if vals[3] else 0,
                    "high": float(vals[4]) if vals[4] else 0,
                    "low": float(vals[5]) if vals[5] else 0,
                    "volume": float(vals[8]) if vals[8] else 0,
                    "amount": float(vals[9]) if vals[9] else 0,
                })
        except Exception as e:
            print(f"    批量行情请求失败: {type(e).__name__}")
        if start + batch_size < len(codes):
            time.sleep(0.5)

    return pd.DataFrame(all_rows)


def get_realtime_snapshot(pool_codes=None):
    """获取实时快照: 如果提供pool_codes则只查这些股票, 否则尝试全A"""
    if pool_codes:
        print(f"  获取实时行情(新浪批量, {len(pool_codes)}只)...")
        df = _sina_batch_quote(pool_codes)
        print(f"  获取成功: {len(df)} 只")
        return df
    # fallback: akshare全A快照
    print("  获取全A实时快照(新浪源)...")
    df = _retry_heavy(ak.stock_zh_a_spot)
    if "代码" in df.columns:
        df["代码"] = df["代码"].str.replace(r"^(sh|sz)", "", regex=True)
    print(f"  全A快照: {len(df)} 只")
    return df


def get_stock_pool():
    """获取中证1000成分股作为股池, 返回 (codes_set, name_map)
    优先用缓存池 (API防护层), 失败则fallback到原始逻辑"""
    print("  获取中证1000成分股...")
    # 优先走缓存池
    try:
        from api_guard import cached_pool
        pool_set, name_map = cached_pool()
        print(f"  股池: {len(pool_set)} 只 (缓存命中, 已排除科创/北交)")
        return pool_set, name_map
    except ImportError:
        pass
    except Exception:
        print("    缓存池获取失败, 回退原始逻辑...")
    try:
        df = _retry_heavy(ak.index_stock_cons_csindex, symbol="000852")
        code_col = "成分券代码" if "成分券代码" in df.columns else "品种代码"
        name_col = "成分券名称" if "成分券名称" in df.columns else "品种名称"
        all_codes = df[code_col].astype(str).str.zfill(6).tolist()
        name_map = dict(zip(
            df[code_col].astype(str).str.zfill(6),
            df[name_col]
        ))
    except Exception:
        print("    csindex源失败, 尝试原始源...")
        df = _retry_heavy(ak.index_stock_cons, symbol="000852")
        all_codes = df["品种代码"].tolist()
        name_map = dict(zip(df["品种代码"], df["品种名称"]))
    # 排除科创板(688)、北交所(8)、三板(4)
    all_codes = [c for c in all_codes if not c.startswith(("688", "8", "4"))]
    all_codes = list(dict.fromkeys(all_codes))
    codes_set = set(all_codes)
    print(f"  股池: {len(codes_set)} 只 (已排除科创/北交)")
    return codes_set, name_map


def filter_basics(spot_df, pool_set):
    """基础过滤: 限定股池 + 排除ST/涨跌停
    兼容 _sina_batch_quote 输出 和 akshare 两种格式"""
    df = spot_df.copy()
    # 列名标准化 (中文列名 → 英文)
    col_map = {
        "代码": "code", "名称": "name", "最新价": "price",
        "今开": "open", "昨收": "prev_close",
        "涨跌幅": "pct_chg", "量比": "volume_ratio",
        "换手率": "turnover", "流通市值": "float_mv",
        "成交量": "volume", "成交额": "amount",
    }
    for old, new in col_map.items():
        if old in df.columns:
            df = df.rename(columns={old: new})

    # 限定股池
    if "code" in df.columns:
        df = df[df["code"].isin(pool_set)].copy()

    # 排除ST
    df = df[~df["name"].str.contains("ST|\\*ST", na=False)].copy()

    # 计算涨跌幅 (如果缺失)
    if "pct_chg" not in df.columns:
        if "price" in df.columns and "prev_close" in df.columns:
            df["price"] = pd.to_numeric(df["price"], errors="coerce")
            df["prev_close"] = pd.to_numeric(df["prev_close"], errors="coerce")
            df["pct_chg"] = (df["price"] - df["prev_close"]) / df["prev_close"] * 100
    else:
        df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")

    # 排除涨跌停 (涨跌幅绝对值 >= 9.8% 近似涨跌停)
    df = df[df["pct_chg"].abs() < 9.8].copy()

    # 数值转换
    for col in ["price", "open", "prev_close", "volume", "amount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 量比: 用成交额排名百分位近似 (无原始量比时)
    if "volume_ratio" not in df.columns:
        if "amount" in df.columns and df["amount"].sum() > 0:
            df["volume_ratio"] = df["amount"].rank(pct=True) * 5
        else:
            df["volume_ratio"] = 2.0
    else:
        df["volume_ratio"] = pd.to_numeric(df["volume_ratio"], errors="coerce")

    # 换手率: 无数据时用成交量排名近似
    if "turnover" not in df.columns:
        if "volume" in df.columns and df["volume"].sum() > 0:
            df["turnover"] = df["volume"].rank(pct=True) * 5
        else:
            df["turnover"] = 2.0
    else:
        df["turnover"] = pd.to_numeric(df["turnover"], errors="coerce")

    # 排除无效价格
    df = df[df["price"] > 0].copy()

    return df


# 模块级 K 线缓存, 同一运行周期内复用 (避免 chip 模块重复拉)
_kline_cache = {}   # code -> DataFrame (close/high/low)
_kline_cache_ts = 0.0  # 缓存时间戳, 超过 10 分钟清空


def _fetch_one_kline(code, name_map, start_date, end_date):
    """单只股票 K 线获取 + 技术指标计算 (供线程池调用)"""
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
        lows = df["low"].values.astype(float) if "low" in df.columns else highs

        # 存入缓存 (chip 模块复用)
        _kline_cache[code] = {"close": closes, "high": highs, "low": lows}

        rsi_vals = calc_rsi(closes, 14)
        rsi_now = rsi_vals[-1] if not np.isnan(rsi_vals[-1]) else 50

        ma60 = calc_ma(closes, 60)
        above_ma60 = closes[-1] > ma60[-1] if not np.isnan(ma60[-1]) else False

        daily_ret = np.diff(closes[-21:]) / closes[-21:-1]
        volatility = np.std(daily_ret) * np.sqrt(252) if len(daily_ret) >= 10 else 999

        high_5d = np.max(highs[-5:])
        pullback_5d = closes[-1] / high_5d - 1

        high_20d = np.max(highs[-20:])
        pullback_20d = closes[-1] / high_20d - 1

        ret_3d = closes[-1] / closes[-3] - 1 if len(closes) >= 3 else 0

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
        }
    except Exception:
        return "FAIL"


def calc_daily_technicals(codes, name_map, days=120):
    """批量拉日K数据计算技术指标 (5线程并行, 带缓存)"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    global _kline_cache_ts
    # 超过 10 分钟清空缓存
    if time.time() - _kline_cache_ts > 600:
        _kline_cache.clear()
        _kline_cache_ts = time.time()

    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    results = []
    fail_count = 0
    total = len(codes)
    done_count = 0

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {
            pool.submit(_fetch_one_kline, code, name_map, start_date, end_date): code
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


def get_kline_cache():
    """返回当前K线缓存, 供 enhanced_factors 复用"""
    return _kline_cache


def get_hot_concept_names():
    """获取当日热点概念板块名称集合"""
    print("  获取热点概念...")
    try:
        df = _retry(ak.stock_fund_flow_concept)
        df["净额"] = pd.to_numeric(df["净额"], errors="coerce")
        top_inflow = df.sort_values("净额", ascending=False).head(15)
        top_chg = df.sort_values("行业-涨跌幅", ascending=False).head(15)
        hot_names = set(top_inflow["行业"].tolist() + top_chg["行业"].tolist())
        hot_leaders = {}
        for _, row in pd.concat([top_inflow, top_chg]).drop_duplicates("行业").iterrows():
            leader = str(row.get("领涨股", ""))
            if leader:
                hot_leaders[leader] = row["行业"]
        print(f"  热点概念: {len(hot_names)} 个")
        print(f"  资金净流入TOP5: {', '.join(top_inflow['行业'].head(5).tolist())}")
        return hot_names, hot_leaders
    except Exception as e:
        print(f"  热点概念获取失败: {e}")
        return set(), {}


def score_and_rank(df, weights, top_n=5):
    """
    通用打分排名
    weights: dict of {因子列名: 权重}
    每个因子列已经是归一化后的分数
    """
    df = df.copy()
    df["total_score"] = 0
    for col, w in weights.items():
        if col in df.columns:
            df["total_score"] += df[col].fillna(0) * w

    # MA60下方降权
    if "above_ma60" in df.columns:
        below_mask = ~df["above_ma60"]
        df.loc[below_mask, "total_score"] *= 0.8
        below_n = below_mask.sum()
        if below_n > 0:
            print(f"  MA60下方降权(×0.8): {below_n} 只")

    df = df.sort_values("total_score", ascending=False)

    # 行业分散: 同行业最多2只
    df["sector"] = df["name"].apply(classify_sector)
    sector_count = {}
    selected_idx = []
    for idx, row in df.iterrows():
        sec = row["sector"]
        cnt = sector_count.get(sec, 0)
        if cnt < 2:
            selected_idx.append(idx)
            sector_count[sec] = cnt + 1
        if len(selected_idx) >= top_n:
            break

    selected = df.loc[selected_idx] if selected_idx else df.head(top_n)
    sec_dist = selected["sector"].value_counts()
    print(f"  行业分布: {dict(sec_dist)}")
    return selected, df


def auto_detect():
    """根据当前时间自动选择策略"""
    now = datetime.now()
    h, m = now.hour, now.minute
    if h < 12:
        return "auction"
    else:
        return "afternoon"


# ================================================================
#  策略一: 集合竞价策略
# ================================================================

def get_auction_signals():
    """获取竞价异动股列表"""
    print("  获取竞价异动信号...")
    try:
        df = _retry(ak.stock_changes_em, symbol="竞价上涨")
        codes = set(df["代码"].tolist()) if "代码" in df.columns else set()
        print(f"  竞价上涨异动: {len(codes)} 只")
        return codes
    except Exception as e:
        print(f"  竞价异动获取失败: {e}")
        return set()


def run_auction(top_n=5):
    """集合竞价策略主流程"""
    t0 = time.time()
    print("=" * 65)
    print("  日内策略一: 集合竞价选股")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    # ---- 第1步: 获取数据 ----
    print("\n[1/6] 获取基础数据...")
    pool_set, name_map = get_stock_pool()
    spot_df = get_realtime_snapshot(pool_codes=list(pool_set))
    auction_codes = get_auction_signals()

    # ---- 第2步: 竞价信号筛选 ----
    print("\n[2/6] 竞价信号筛选...")
    df = filter_basics(spot_df, pool_set)

    # 计算高开幅度
    df["gap_pct"] = (df["open"] - df["prev_close"]) / df["prev_close"] * 100

    before = len(df)
    # 高开幅度 1%~5%
    df = df[(df["gap_pct"] >= 1) & (df["gap_pct"] <= 5)].copy()
    print(f"  高开 1%-5% 筛选: {before} → {len(df)}")

    before = len(df)
    # 量比 > 1.5
    df = df[df["volume_ratio"] > 1.5].copy()
    print(f"  量比 > 1.5: {before} → {len(df)}")

    before = len(df)
    # 换手率 > 0.5%
    df = df[df["turnover"] > 0.5].copy()
    print(f"  换手率 > 0.5%: {before} → {len(df)}")

    # 标记竞价异动
    df["is_auction_signal"] = df["code"].isin(auction_codes).astype(int)
    auction_n = df["is_auction_signal"].sum()
    print(f"  竞价异动股匹配: {auction_n} 只")
    print(f"  竞价筛选候选: {len(df)} 只")

    if len(df) == 0:
        print("\n  竞价筛选后无候选股, 尝试放宽条件...")
        df = filter_basics(spot_df, pool_set)
        df["gap_pct"] = (df["open"] - df["prev_close"]) / df["prev_close"] * 100
        df = df[(df["gap_pct"] >= 0.5) & (df["gap_pct"] <= 6)].copy()
        df = df[df["volume_ratio"] > 1.0].copy()
        df = df[df["turnover"] > 0.3].copy()
        df["is_auction_signal"] = df["code"].isin(auction_codes).astype(int)
        print(f"  放宽条件后候选: {len(df)} 只")
        if len(df) == 0:
            print("  仍然无候选, 退出")
            return None

    candidate_codes = df["code"].tolist()

    # ---- 第3步: 技术面验证 ----
    print(f"\n[3/6] 技术面验证 ({len(candidate_codes)} 只)...")
    tech_df = calc_daily_technicals(candidate_codes, name_map)

    if tech_df.empty:
        print("  技术面数据获取失败")
        return None

    # 技术面过滤
    before = len(tech_df)
    tech_df = tech_df[tech_df["rsi"].between(30, 60)].copy()
    print(f"  RSI 30-60: {before} → {len(tech_df)}")

    before = len(tech_df)
    tech_df = tech_df[tech_df["volatility"] < 0.55].copy()
    print(f"  波动率 < 55%: {before} → {len(tech_df)}")

    before = len(tech_df)
    tech_df = tech_df[tech_df["pullback_20d"] > -0.25].copy()
    print(f"  20日回撤 > -25%: {before} → {len(tech_df)}")

    # 合并竞价数据 + 技术数据
    merged = tech_df.merge(
        df[["code", "price", "open", "prev_close", "gap_pct",
            "volume_ratio", "turnover", "is_auction_signal"]],
        on="code", how="inner"
    )
    print(f"  合并后候选: {len(merged)} 只")

    if len(merged) == 0:
        print("  技术面过滤后无候选, 退出")
        return None

    # ---- 第4步: 基本面过滤 ----
    print(f"\n[4/6] 基本面过滤...")
    fund_df = fetch_fundamental_batch()
    if not fund_df.empty:
        merged = apply_fundamental_filters(merged, fund_df)
    if len(merged) == 0:
        print("  基本面过滤后无候选, 退出")
        return None

    # ---- 第4.5步: 多维度增强因子 ----
    merged = enhance_candidates(merged, name_map)

    # ---- 第5步: 综合打分 ----
    print(f"\n[5/6] 综合打分 ({len(merged)} 只)...")

    # 获取热点概念
    hot_names, hot_leaders = get_hot_concept_names()
    merged["is_hot_leader"] = merged["name"].isin(hot_leaders.keys()).astype(int)

    def zscore(s):
        std = s.std()
        return (s - s.mean()) / std if std > 0 else s * 0

    # 高开幅度得分: 1-3%最优, 超过3%递减
    gap = merged["gap_pct"].clip(0.5, 6)
    merged["s_gap"] = np.where(gap <= 3, gap / 3, 1.0 - (gap - 3) / 3 * 0.5)
    merged["s_gap"] = zscore(merged["s_gap"])

    # 量比得分: 越大越好, >10递减
    vr = merged["volume_ratio"].clip(1, 15)
    merged["s_volume_ratio"] = np.where(vr <= 10, vr / 10, 1.0 - (vr - 10) / 10)
    merged["s_volume_ratio"] = zscore(merged["s_volume_ratio"])

    # 竞价异动加分
    merged["s_auction"] = merged["is_auction_signal"].astype(float)

    # 趋势得分 (MA60)
    merged["s_trend"] = np.where(merged["above_ma60"], 1.0, -0.5)
    # 5日回踩加分
    pull_bonus = np.where(
        (merged["pullback_5d"] < -0.03) & (merged["pullback_5d"] > -0.15), 1.0, 0
    )
    merged["s_trend"] = zscore(pd.Series(merged["s_trend"].values + pull_bonus, index=merged.index))

    # RSI适中得分: 40-55最优
    rsi = merged["rsi"]
    merged["s_rsi"] = np.where(
        rsi.between(40, 55), 1.0,
        np.where(rsi.between(30, 40) | rsi.between(55, 60), 0.5, 0)
    )
    merged["s_rsi"] = zscore(merged["s_rsi"])

    # 基本面得分
    if not fund_df.empty:
        merged = calc_fundamental_scores(merged, fund_df)
    else:
        merged["s_fundamental"] = 0

    # 热点板块得分
    merged["s_hot"] = merged["is_hot_leader"].astype(float)

    # 换手率得分: 1%-5%最优
    tr = merged["turnover"].clip(0, 10)
    merged["s_turnover"] = np.where(tr.between(1, 5), 1.0, 0.5)
    merged["s_turnover"] = zscore(merged["s_turnover"])

    # 加权打分 (8原始因子 + 3增强因子 = 11因子)
    default_weights = {
        "s_gap": 0.15,
        "s_volume_ratio": 0.12,
        "s_auction": 0.08,
        "s_trend": 0.12,
        "s_rsi": 0.08,
        "s_fundamental": 0.10,
        "s_hot": 0.07,
        "s_turnover": 0.03,
        "s_fund_flow": 0.10,
        "s_lhb": 0.08,
        "s_chip": 0.07,
    }
    # 优先使用调优后的权重 (实验/优化采纳), 降级用默认
    try:
        from auto_optimizer import get_tunable_params
        tuned = get_tunable_params("auction")
        weights = tuned.get("weights", default_weights)
    except Exception:
        weights = default_weights
    selected, full_df = score_and_rank(merged, weights, top_n=top_n + 3)

    # ---- 第6步: 新闻排雷 ----
    news_n = min(top_n + 3, len(full_df))
    news_codes = full_df.head(news_n)["code"].tolist()
    print(f"\n[6/6] 新闻排雷 ({len(news_codes)} 只)...")
    safe_codes, risk_info, news_scores = news_risk_screen(news_codes, name_map)

    # 从安全列表中选TOP N, 过滤低分(得分<0.2不推)
    safe_df = full_df[full_df["code"].isin(safe_codes)]
    if "score" in safe_df.columns:
        safe_df = safe_df[safe_df["score"] >= 0.2]
    safe_df = safe_df.head(top_n)

    elapsed = time.time() - t0

    # ---- 输出结果 ----
    print("\n" + "=" * 65)
    print(f"  集合竞价策略推荐 TOP {len(safe_df)}  (耗时 {elapsed:.0f}s)")
    print("=" * 65)

    for rank, (_, row) in enumerate(safe_df.iterrows(), 1):
        sector_tag = f"[{row.get('sector', '其他')}]"
        trend_tag = "趋势↑" if row["above_ma60"] else "趋势↓"

        # 新闻标签
        code = row["code"]
        news_tag = "新闻无异常"
        if code in risk_info:
            info = risk_info[code]
            if info["risk_keywords"]:
                news_tag = f"⚠风险:[{','.join(info['risk_keywords'])}]"
            if info["positive_keywords"]:
                news_tag += f" ✓正面:[{','.join(info['positive_keywords'])}]"

        # 基本面标签
        fund_tags = []
        if "profit_growth" in row.index and pd.notna(row.get("profit_growth")):
            fund_tags.append(f"利润增长={row['profit_growth']:+.1f}%")
        if "roe" in row.index and pd.notna(row.get("roe")):
            fund_tags.append(f"ROE={row['roe']:.1f}%")
        fund_label = "  ".join(fund_tags) if fund_tags else "无数据"

        auction_tag = " [竞价异动]" if row.get("is_auction_signal") else ""

        # 增强因子标签
        enh = format_enhanced_labels(row)
        enh_parts = [v for v in [enh["fund_flow_label"], enh["lhb_label"], enh["chip_label"]] if v]
        enh_line = "  ".join(enh_parts) if enh_parts else "无增强数据"

        print(f"""
  {rank}. {row['code']} {row.get('name',''):　<8} {sector_tag} | 得分: {row['total_score']:+.3f} | 现价: {row.get('price', row['latest_close']):.2f}
     竞价: 高开{row['gap_pct']:+.1f}%  量比={row['volume_ratio']:.1f}  换手={row['turnover']:.1f}%{auction_tag}
     技术: RSI={row['rsi']:.0f}  {trend_tag}  波动={row['volatility']:.0%}
     基本面: {fund_label}
     增强: {enh_line}
     风控: {news_tag}""")

    # 保存CSV
    today_str = datetime.now().strftime("%Y%m%d")
    output = f"auction_result_{today_str}.csv"
    full_df.to_csv(output, index=False, encoding="utf-8-sig")
    print(f"\n完整排名已保存至: {output}")
    return safe_df


# ================================================================
#  策略二: 尾盘短线策略
# ================================================================

def _fetch_one_intraday(code, name_map):
    """单只股票日内形态分析 (供并行调用)"""
    try:
        sina_sym = _tx_sym(code).replace("sh", "sh").replace("sz", "sz")
        df = _retry(
            ak.stock_zh_a_minute,
            symbol=sina_sym, period="5"
        )
        if df is None or df.empty or len(df) < 10:
            return None

        time_col = "day" if "day" in df.columns else ("时间" if "时间" in df.columns else df.columns[0])
        df["dt"] = pd.to_datetime(df[time_col])
        df["hour"] = df["dt"].dt.hour

        close_col = "close" if "close" in df.columns else "收盘"
        vol_col = "volume" if "volume" in df.columns else "成交量"
        low_col = "low" if "low" in df.columns else "最低"

        today_date = df["dt"].dt.date.iloc[-1]
        df_today = df[df["dt"].dt.date == today_date].copy()
        if len(df_today) < 10:
            return None

        closes_t = pd.to_numeric(df_today[close_col], errors="coerce").values
        volumes_t = pd.to_numeric(df_today[vol_col], errors="coerce").values
        lows_t = pd.to_numeric(df_today[low_col], errors="coerce").values
        hours_t = df_today["hour"].values

        am_mask = hours_t < 12
        pm_mask = hours_t >= 13

        am_vol = volumes_t[am_mask]
        am_avg_vol = np.mean(am_vol) if len(am_vol) > 0 else 1

        last_hour_vol = volumes_t[hours_t >= 14]
        last_hour_avg = np.mean(last_hour_vol) if len(last_hour_vol) > 0 else 0
        tail_volume_ratio = last_hour_avg / am_avg_vol if am_avg_vol > 0 else 0

        pm_closes = closes_t[pm_mask]
        pm_gain = (pm_closes[-1] / pm_closes[0] - 1) * 100 if len(pm_closes) >= 2 else 0

        min_idx = np.argmin(lows_t)
        min_in_am = hours_t[min_idx] < 12

        last_5m_speed = (closes_t[-1] / closes_t[-2] - 1) * 100 if len(closes_t) >= 2 else 0

        return {
            "code": code,
            "name": name_map.get(code, ""),
            "tail_volume_ratio": tail_volume_ratio,
            "pm_gain": pm_gain,
            "min_in_am": min_in_am,
            "last_5m_speed": last_5m_speed,
        }
    except Exception:
        return "FAIL"


def get_intraday_pattern(codes, name_map):
    """
    拉取5分钟K线, 分析日内形态 (20线程并行):
    - 尾盘放量: 最后1小时成交量 > 上午均量
    - 午后趋势: 13:00后价格逐步抬升
    - 盘中支撑: 日内最低价出现在上午
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    total = len(codes)
    print(f"    日内形态分析 ({total} 只, 20线程并行)...")
    results = []
    fail_count = 0
    done = 0

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {
            pool.submit(_fetch_one_intraday, code, name_map): code
            for code in codes
        }
        for fut in as_completed(futures):
            done += 1
            r = fut.result()
            if r is None:
                continue
            elif r == "FAIL":
                fail_count += 1
            else:
                results.append(r)
            if done % 20 == 0:
                print(f"      日内形态进度: {done}/{total}  有效: {len(results)}  失败: {fail_count}")

    print(f"    日内形态完成: {len(results)} 只有效, {fail_count} 只失败")
    return pd.DataFrame(results)


def run_afternoon(top_n=5):
    """尾盘短线策略主流程"""
    t0 = time.time()
    print("=" * 65)
    print("  日内策略二: 尾盘短线选股")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    # ---- 第1步: 获取实时快照 ----
    print("\n[1/7] 获取基础数据...")
    pool_set, name_map = get_stock_pool()
    spot_df = get_realtime_snapshot(pool_codes=list(pool_set))
    hot_names, hot_leaders = get_hot_concept_names()

    # ---- 第2步: 日内强势筛选 ----
    print("\n[2/7] 日内强势筛选...")
    df = filter_basics(spot_df, pool_set)

    before = len(df)
    # 涨跌幅 0%~5%
    df = df[(df["pct_chg"] >= 0) & (df["pct_chg"] <= 5)].copy()
    print(f"  涨跌幅 0%-5%: {before} → {len(df)}")

    before = len(df)
    # 量比 > 1.0
    df = df[df["volume_ratio"] > 1.0].copy()
    print(f"  量比 > 1.0: {before} → {len(df)}")

    before = len(df)
    # 换手率 > 1%
    df = df[df["turnover"] > 1].copy()
    print(f"  换手率 > 1%: {before} → {len(df)}")

    print(f"  日内强势候选: {len(df)} 只")

    if len(df) == 0:
        print("\n  日内强势筛选后无候选, 尝试放宽条件...")
        df = filter_basics(spot_df, pool_set)
        df = df[(df["pct_chg"] >= -1) & (df["pct_chg"] <= 6)].copy()
        df = df[df["volume_ratio"] > 0.8].copy()
        df = df[df["turnover"] > 0.5].copy()
        print(f"  放宽条件后候选: {len(df)} 只")
        if len(df) == 0:
            print("  仍然无候选, 退出")
            return None

    # 限制候选数量, 按涨幅+量比粗排
    df["_rough"] = df["pct_chg"] * 0.5 + df["volume_ratio"] * 0.3 + df["turnover"] * 0.2
    df = df.sort_values("_rough", ascending=False).head(50)
    candidate_codes = df["code"].tolist()

    # ---- 第3步: 日内形态验证 ----
    print(f"\n[3/7] 日内形态分析 ({len(candidate_codes)} 只)...")
    pattern_df = get_intraday_pattern(candidate_codes, name_map)

    if pattern_df.empty:
        print("  日内形态数据获取失败, 跳过形态过滤")
        pattern_df = pd.DataFrame({
            "code": candidate_codes,
            "tail_volume_ratio": 1.0,
            "pm_gain": 0.0,
            "min_in_am": True,
            "last_5m_speed": 0.0,
        })

    # 形态过滤: 尾盘放量 + 午后走强
    before = len(pattern_df)
    pattern_df = pattern_df[pattern_df["tail_volume_ratio"] > 0.8].copy()
    print(f"  尾盘放量过滤: {before} → {len(pattern_df)}")

    before = len(pattern_df)
    pattern_df = pattern_df[pattern_df["pm_gain"] > 0].copy()
    print(f"  午后走强过滤: {before} → {len(pattern_df)}")

    if len(pattern_df) == 0:
        print("  形态过滤后无候选, 放宽至所有候选...")
        pattern_df = get_intraday_pattern(candidate_codes, name_map)
        if pattern_df.empty:
            pattern_df = pd.DataFrame({"code": candidate_codes})
            pattern_df["tail_volume_ratio"] = 1.0
            pattern_df["pm_gain"] = 0.0
            pattern_df["min_in_am"] = True
            pattern_df["last_5m_speed"] = 0.0

    tech_codes = pattern_df["code"].tolist()

    # ---- 第4步: 技术面验证 ----
    print(f"\n[4/7] 技术面验证 ({len(tech_codes)} 只)...")
    tech_df = calc_daily_technicals(tech_codes, name_map)

    if tech_df.empty:
        print("  技术面数据获取失败")
        return None

    # 技术面过滤
    before = len(tech_df)
    tech_df = tech_df[tech_df["rsi"].between(40, 65)].copy()
    print(f"  RSI 40-65: {before} → {len(tech_df)}")

    before = len(tech_df)
    tech_df = tech_df[tech_df["volatility"] < 0.55].copy()
    print(f"  波动率 < 55%: {before} → {len(tech_df)}")

    before = len(tech_df)
    tech_df = tech_df[tech_df["ret_3d"] < 0.08].copy()
    print(f"  近3日涨幅 < 8%: {before} → {len(tech_df)}")

    before = len(tech_df)
    tech_df = tech_df[tech_df["pullback_20d"] > -0.25].copy()
    print(f"  20日回撤 > -25%: {before} → {len(tech_df)}")

    # 合并日内形态 + 技术面 + 快照
    merged = tech_df.merge(pattern_df[["code", "tail_volume_ratio", "pm_gain", "min_in_am", "last_5m_speed"]],
                           on="code", how="inner")
    merged = merged.merge(
        df[["code", "price", "pct_chg", "volume_ratio", "turnover"]],
        on="code", how="inner"
    )
    print(f"  合并后候选: {len(merged)} 只")

    if len(merged) == 0:
        print("  技术面过滤后无候选, 退出")
        return None

    # ---- 第5步: 基本面过滤 ----
    print(f"\n[5/7] 基本面过滤...")
    fund_df = fetch_fundamental_batch()
    if not fund_df.empty:
        merged = apply_fundamental_filters(merged, fund_df)
    if len(merged) == 0:
        print("  基本面过滤后无候选, 退出")
        return None

    # ---- 第5.5步: 多维度增强因子 ----
    merged = enhance_candidates(merged, name_map)

    # ---- 第6步: 综合打分 ----
    print(f"\n[6/7] 综合打分 ({len(merged)} 只)...")

    merged["is_hot_leader"] = merged["name"].isin(hot_leaders.keys()).astype(int)

    def zscore(s):
        std = s.std()
        return (s - s.mean()) / std if std > 0 else s * 0

    # 午后走势得分
    merged["s_pm_gain"] = zscore(merged["pm_gain"].clip(-2, 5))
    # 尾盘放量加分
    merged["s_pm_gain"] += np.where(merged["tail_volume_ratio"] > 1.0, 0.5, 0)
    merged["s_pm_gain"] = zscore(merged["s_pm_gain"])

    # 日内涨幅: 1-3%最优
    pct = merged["pct_chg"].clip(-1, 6)
    merged["s_pct"] = np.where(pct.between(1, 3), 1.0, 0.5)
    merged["s_pct"] = zscore(merged["s_pct"])

    # 量比/换手
    merged["s_vol_turn"] = zscore(merged["volume_ratio"].clip(0.5, 10)) * 0.5 + \
                           zscore(merged["turnover"].clip(0.5, 10)) * 0.5

    # 趋势(MA60)
    merged["s_trend"] = np.where(merged["above_ma60"], 1.0, -0.5)
    merged["s_trend"] = zscore(pd.Series(merged["s_trend"].values, index=merged.index))

    # RSI适中: 40-60最优
    rsi = merged["rsi"]
    merged["s_rsi"] = np.where(rsi.between(40, 60), 1.0, 0.3)
    merged["s_rsi"] = zscore(merged["s_rsi"])

    # 基本面
    if not fund_df.empty:
        merged = calc_fundamental_scores(merged, fund_df)
    else:
        merged["s_fundamental"] = 0

    # 热点板块
    merged["s_hot"] = merged["is_hot_leader"].astype(float)

    # 5分钟涨速
    merged["s_5m_speed"] = zscore(merged["last_5m_speed"].clip(-1, 2))

    # 加权打分 (8原始因子 + 3增强因子 = 11因子)
    default_weights = {
        "s_pm_gain": 0.15,
        "s_pct": 0.08,
        "s_vol_turn": 0.08,
        "s_trend": 0.12,
        "s_rsi": 0.08,
        "s_fundamental": 0.10,
        "s_hot": 0.07,
        "s_5m_speed": 0.07,
        "s_fund_flow": 0.10,
        "s_lhb": 0.08,
        "s_chip": 0.07,
    }
    # 优先使用调优后的权重 (实验/优化采纳), 降级用默认
    try:
        from auto_optimizer import get_tunable_params
        tuned = get_tunable_params("afternoon")
        weights = tuned.get("weights", default_weights)
    except Exception:
        weights = default_weights
    selected, full_df = score_and_rank(merged, weights, top_n=top_n + 3)

    # ---- 第7步: 新闻排雷 ----
    news_n = min(top_n + 3, len(full_df))
    news_codes = full_df.head(news_n)["code"].tolist()
    print(f"\n[7/7] 新闻排雷 ({len(news_codes)} 只)...")
    safe_codes, risk_info, news_scores = news_risk_screen(news_codes, name_map)

    # 从安全列表中选TOP N, 过滤低分(得分<0.2不推)
    safe_df = full_df[full_df["code"].isin(safe_codes)]
    if "score" in safe_df.columns:
        safe_df = safe_df[safe_df["score"] >= 0.2]
    safe_df = safe_df.head(top_n)

    elapsed = time.time() - t0

    # ---- 输出结果 ----
    print("\n" + "=" * 65)
    print(f"  尾盘短线策略推荐 TOP {len(safe_df)}  (耗时 {elapsed:.0f}s)")
    print("=" * 65)

    for rank, (_, row) in enumerate(safe_df.iterrows(), 1):
        sector_tag = f"[{row.get('sector', '其他')}]"
        trend_tag = "趋势↑" if row["above_ma60"] else "趋势↓"

        # 新闻标签
        code = row["code"]
        news_tag = "新闻无异常"
        if code in risk_info:
            info = risk_info[code]
            if info["risk_keywords"]:
                news_tag = f"⚠风险:[{','.join(info['risk_keywords'])}]"
            if info["positive_keywords"]:
                news_tag += f" ✓正面:[{','.join(info['positive_keywords'])}]"

        # 基本面标签
        fund_tags = []
        if "profit_growth" in row.index and pd.notna(row.get("profit_growth")):
            fund_tags.append(f"利润增长={row['profit_growth']:+.1f}%")
        if "roe" in row.index and pd.notna(row.get("roe")):
            fund_tags.append(f"ROE={row['roe']:.1f}%")
        fund_label = "  ".join(fund_tags) if fund_tags else "无数据"

        tail_tag = "尾盘放量" if row.get("tail_volume_ratio", 0) > 1.0 else "尾盘缩量"

        # 增强因子标签
        enh = format_enhanced_labels(row)
        enh_parts = [v for v in [enh["fund_flow_label"], enh["lhb_label"], enh["chip_label"]] if v]
        enh_line = "  ".join(enh_parts) if enh_parts else "无增强数据"

        print(f"""
  {rank}. {row['code']} {row.get('name',''):　<8} {sector_tag} | 得分: {row['total_score']:+.3f} | 现价: {row.get('price', row['latest_close']):.2f}
     日内: 午后涨{row.get('pm_gain', 0):+.1f}%  {tail_tag}  5分涨速{row.get('last_5m_speed', 0):+.1f}%
     技术: RSI={row['rsi']:.0f}  {trend_tag}  波动={row['volatility']:.0%}
     基本面: {fund_label}
     增强: {enh_line}
     风控: {news_tag}""")

    # 保存CSV
    today_str = datetime.now().strftime("%Y%m%d")
    output = f"afternoon_result_{today_str}.csv"
    full_df.to_csv(output, index=False, encoding="utf-8-sig")
    print(f"\n完整排名已保存至: {output}")
    return safe_df


# ================================================================
#  标准化包装函数 (供 scheduler 调用)
# ================================================================

def get_auction_recommendations(top_n=3):
    """包装 run_auction()，返回标准化 list[dict]"""
    try:
        safe_df = run_auction(top_n=top_n)
    except Exception as e:
        print(f"[集合竞价策略异常] {e}")
        return []
    if safe_df is None or safe_df.empty:
        return []
    results = []
    for _, r in safe_df.iterrows():
        price = r.get("latest_close", r.get("price", 0))
        reason_parts = []
        if "gap_pct" in r.index and pd.notna(r.get("gap_pct")):
            reason_parts.append(f"高开{r['gap_pct']:+.1f}%")
        if "volume_ratio" in r.index and pd.notna(r.get("volume_ratio")):
            reason_parts.append(f"量比{r['volume_ratio']:.1f}")
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


def get_afternoon_recommendations(top_n=3):
    """包装 run_afternoon()，返回标准化 list[dict]"""
    try:
        safe_df = run_afternoon(top_n=top_n)
    except Exception as e:
        print(f"[尾盘短线策略异常] {e}")
        return []
    if safe_df is None or safe_df.empty:
        return []
    results = []
    for _, r in safe_df.iterrows():
        price = r.get("latest_close", r.get("price", 0))
        reason_parts = []
        if "pct_chg" in r.index and pd.notna(r.get("pct_chg")):
            reason_parts.append(f"涨幅{r['pct_chg']:+.1f}%")
        if "pm_gain" in r.index and pd.notna(r.get("pm_gain")):
            reason_parts.append(f"午后涨{r['pm_gain']:+.1f}%")
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
    mode = sys.argv[1] if len(sys.argv) > 1 else auto_detect()

    if mode == "auction":
        run_auction()
    elif mode == "afternoon":
        run_afternoon()
    else:
        print(f"未知模式: {mode}")
        print("用法: python3 intraday_strategy.py [auction|afternoon]")
        sys.exit(1)
