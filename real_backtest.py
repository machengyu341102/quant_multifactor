"""
real_backtest.py  --  真实历史回测数据生成引擎 v1.0

用 akshare 拉取真实 OHLCV 日线, 按各策略原生因子公式计算 factor_scores,
用真实收盘价算 T+1 收益率, 写入 scorecard DB.

特点:
  - 零前瞻偏差: 每天 T 只用 T 及之前的数据算因子
  - 真实因子: 复用各策略评分公式 (RSI / Bollinger / MACD / ADX / MA / 量比等)
  - 真实标签: T+1 收益率 = (次日收盘 / 当日收盘 - 1) * 100
  - 策略筛选: 每条记录只在满足该策略初筛条件时才生成

用法:
  python3 real_backtest.py [N_STOCKS] [--clean]
  python3 real_backtest.py 100 --clean   # 清旧数据 + 跑100只
  python3 real_backtest.py 50            # 增量跑50只
"""
import sqlite3
import json
import time
import sys
import numpy as np
import pandas as pd
import akshare as ak

_DB = "quant_data.db"
_MARKER = "REAL_BT"      # 标识回测记录, 区分真实交易
_SLEEP = 0.35             # API 间隔 (秒)

# ==================================================================
#  技术指标 (pandas Series, 自动对齐, 零前瞻偏差)
# ==================================================================

def _rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return (100 - 100 / (1 + rs)).fillna(50)


def _adx(high, low, close, period=14):
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    mask = plus_dm > minus_dm
    plus_dm = plus_dm.where(mask, 0)
    minus_dm = minus_dm.where(~mask, 0)
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = plus_dm.rolling(period).mean() / atr * 100
    minus_di = minus_dm.rolling(period).mean() / atr * 100
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1) * 100
    return dx.rolling(period).mean().fillna(0)


# ==================================================================
#  一次性计算所有技术特征 (per stock)
# ==================================================================

def _compute_features(df):
    """对一只股票的 K 线数据, 一次性计算所有技术特征 + T+1 收益."""
    c, h, l, v, o = df["close"], df["high"], df["low"], df["volume"], df["open"]

    # --- 基础指标 ---
    df["rsi"]       = _rsi(c, 14)
    df["ma5"]       = c.rolling(5).mean()
    df["ma10"]      = c.rolling(10).mean()
    df["ma20"]      = c.rolling(20).mean()
    df["ma60"]      = c.rolling(60).mean()

    boll_mid        = c.rolling(20).mean()
    boll_std        = c.rolling(20).std()
    df["boll_upper"]= boll_mid + 2 * boll_std
    df["boll_lower"]= boll_mid - 2 * boll_std
    bw = (df["boll_upper"] - df["boll_lower"]).replace(0, 1)
    df["boll_pos"]  = ((c - df["boll_lower"]) / bw).clip(0, 1).fillna(0.5)

    df["above_ma60"]= c > df["ma60"]

    vol5  = v.rolling(5).mean()
    vol20 = v.rolling(20).mean()
    df["vol_ratio"]     = (v / vol5.replace(0, 1)).fillna(1)
    df["vol_ratio_5_20"]= (vol5 / vol20.replace(0, 1)).fillna(1)

    dr = c.pct_change()
    df["volatility"]     = dr.rolling(20).std() * np.sqrt(252)
    df["pullback_5d"]    = c / h.rolling(5).max() - 1
    df["pullback_20d"]   = c / h.rolling(20).max() - 1
    df["overnight_wr"]   = (dr > 0).rolling(20).mean().fillna(0.5)
    df["ret_3d"]         = c / c.shift(3) - 1

    # RSI 连续 <40 天数
    rsi_low = (df["rsi"] < 40).astype(int)
    grp = (rsi_low != rsi_low.shift()).cumsum()
    df["rsi_low_days"] = rsi_low.groupby(grp).cumsum()

    # 均线排列
    df["ma_aligned"]  = (c > df["ma5"]) & (df["ma5"] > df["ma10"]) & (df["ma10"] > df["ma20"])
    df["full_aligned"]= df["ma_aligned"] & (df["ma20"] > df["ma60"])
    ma5gt10 = df["ma5"] > df["ma10"]
    df["ma5_cross"]   = ma5gt10 & (~ma5gt10.shift(2).fillna(False))

    # ADX / MACD
    df["adx"] = _adx(h, l, c, 14)
    df["macd_hist"] = c.ewm(span=12).mean() - c.ewm(span=26).mean()

    # 连涨天数
    up = (c > c.shift(1)).astype(int)
    ug = (up != up.shift()).cumsum()
    df["up_days"] = up.groupby(ug).cumsum()

    # 量价配合
    df["vol_price_confirm"] = ((c > c.shift(5)) & (vol5 > vol20)).astype(float)
    df.loc[df["vol_price_confirm"] == 0, "vol_price_confirm"] = 0.3

    df["ma20_slope"] = (df["ma20"] / df["ma20"].shift(5) - 1) * 100
    df["resistance_ratio"] = c / h.rolling(20).max()
    df["range_10d"] = (h.rolling(10).max() / l.rolling(10).min() - 1) * 100
    body = (c - o).abs().clip(lower=0.01)
    lower_shadow = pd.concat([c, o], axis=1).min(axis=1) - l
    df["shadow_ratio"] = (lower_shadow / body).clip(0, 5)
    df["consecutive_vol"] = (v > v.shift(1)) & (v.shift(1) > v.shift(2))

    if "pct_chg" not in df.columns:
        df["pct_chg"] = dr * 100
    if "turnover" not in df.columns:
        df["turnover"] = 3.0

    # 集合竞价/尾盘所需额外指标
    df["gap_pct"] = (o / c.shift(1) - 1).fillna(0) * 100       # 高开幅度(%)
    df["pm_gain"] = (c - df[["open", "close"]].shift(0).min(axis=1)) / c.shift(1) * 100  # 午后涨幅近似
    # 日内位置 (close 在 open~high 的位置)
    body_range = (h - l).replace(0, 1)
    df["intraday_pos"] = (c - l) / body_range  # 0=收在最低, 1=收在最高

    # T+1 收益率 (标签)
    df["ret_t1"] = c.shift(-1) / c - 1
    return df


# ==================================================================
#  5 策略因子评分 (直接从 row 计算, 零前瞻)
# ==================================================================

def _f_overnight(r):
    """隔夜选股"""
    if r["volatility"] >= 0.45 or pd.isna(r["volatility"]):
        return None
    if r["pullback_20d"] <= -0.25:
        return None
    if r["ret_3d"] >= 0.08:
        return None
    if (not r["above_ma60"]) and r["rsi_low_days"] >= 5:
        return None
    rsi = r["rsi"]
    return {
        "s_rsi":        round(np.clip((50 - rsi) / 40, -1, 1), 4),
        "s_boll":       round(np.clip(0.5 - r["boll_pos"], -0.5, 0.5), 4),
        "s_vol":        round(np.clip((1 - r["vol_ratio"]) / 2, -1, 1), 4),
        "s_volatility": round(np.clip((0.3 - r["volatility"]) / 0.3, -1, 1), 4),
        "s_trend":      round(np.clip(
            ((1.0 if r["above_ma60"] else -0.5) +
             (1.0 if -0.15 < r["pullback_5d"] < -0.03 else
              (-0.5 if r["pullback_5d"] < -0.15 else 0))) / 2, -1, 1), 4),
        "s_overnight":  round(float(r["overnight_wr"] - 0.5), 4),
        "s_flow_1d": 0.0, "s_flow_trend": 0.0,
        "s_hot": 0.0, "s_fundamental": 0.0,
    }


def _f_breakout(r):
    """放量突破选股"""
    pct = r["pct_chg"]
    if pct < 1 or pct > 7:
        return None
    if r["vol_ratio"] < 1.5:
        return None
    if r["close"] <= r["open"]:
        return None
    s_vb = np.clip(r["vol_ratio"] / 3, 0, 1)
    if r["consecutive_vol"]:
        s_vb = min(1.0, s_vb + 0.3)
    s_ma = 1.0 if r["ma_aligned"] else 0.0
    if r["ma5_cross"]:
        s_ma = min(1.0, s_ma + 0.3)
    pct_s = 1.0 if 1 <= pct <= 3 else (0.6 if pct <= 5 else 0.3)
    s_mom = np.clip((pct_s + np.clip(r["ret_3d"], -0.1, 0.1) * 5) / 2, 0, 1)
    rsi = r["rsi"]
    s_rsi = 1.0 if 45 <= rsi <= 65 else (0.5 if 35 <= rsi <= 75 else 0.0)
    to = r["turnover"]
    s_to = 1.0 if 2 <= to <= 8 else (0.5 if 1 <= to <= 15 else 0.0)
    rr = r["resistance_ratio"]
    s_rb = 1.0 if rr >= 0.98 else (0.5 if rr >= 0.95 else 0.0)
    return {
        "s_volume_breakout":  round(float(s_vb), 4),
        "s_ma_alignment":     round(float(s_ma), 4),
        "s_momentum":         round(float(s_mom), 4),
        "s_rsi":              round(float(s_rsi), 4),
        "s_turnover":         round(float(s_to), 4),
        "s_resistance_break": round(float(s_rb), 4),
        "s_fundamental": 0.0, "s_hot": 0.0,
        "s_fund_flow": 0.0,   "s_chip": 0.0,
    }


def _f_dip_buy(r):
    """低吸回调选股"""
    if r["rsi"] >= 30 or r["pct_chg"] >= 0:
        return None
    rsi = r["rsi"]
    c = r["close"]
    ma20, ma60 = r["ma20"], r.get("ma60", 0)
    if ma20 > 0 and ma60 > 0:
        d20 = abs(c - ma20) / c
        d60 = abs(c - ma60) / c
        s_sup = np.clip(1 - min(d20, d60) / 0.1, 0, 1)
    else:
        s_sup = 0.5
    s_mad = np.clip((ma20 - c) / ma20 / 0.1, 0, 1) if ma20 > 0 else 0.0
    return {
        "s_rsi_oversold":   round(np.clip((30 - rsi) / 30, 0, 1), 4),
        "s_volume_shrink":  round(np.clip(1 - r["vol_ratio_5_20"] / 2, 0, 1), 4),
        "s_support":        round(float(s_sup), 4),
        "s_rebound_signal": round(np.clip(r["shadow_ratio"] / 3, 0, 1), 4),
        "s_ma_distance":    round(float(s_mad), 4),
        "s_fundamental": 0.0, "s_fund_flow": 0.0, "s_chip": 0.0,
    }


def _f_consolidation(r):
    """缩量整理选股 — 窄幅整理+缩量+今日放量"""
    if r["range_10d"] >= 15:
        return None
    if r["vol_ratio_5_20"] >= 0.8:
        return None
    if r["vol_ratio"] <= 1.0:
        return None
    c = r["close"]
    ma20 = r["ma20"]
    ma60 = r.get("ma60", 0)
    bu = r["boll_upper"]
    return {
        "s_volume_contract": round(np.clip(1 - r["vol_ratio_5_20"] / 0.6, 0, 1), 4),
        "s_price_range":     round(np.clip(1 - r["range_10d"] / 10, 0, 1), 4),
        "s_breakout_ready":  round(np.clip(1 - (bu - c) / c, 0, 1) if bu > 0 else 0.5, 4),
        "s_ma_support":      round(np.clip(1 - abs(c - ma20) / c / 0.05, 0, 1)
                                   if ma20 > 0 else 0.5, 4),
        "s_trend_strength":  round(np.clip((ma20 - ma60) / ma60 / 0.1, 0, 1)
                                   if ma20 > 0 and ma60 > 0 else 0.5, 4),
        "s_fundamental": 0.0, "s_fund_flow": 0.0, "s_chip": 0.0,
    }


def _f_trend_follow(r):
    """趋势跟踪选股"""
    if r["adx"] <= 25 or not r["ma_aligned"]:
        return None
    adx_s = np.clip((r["adx"] - 25) / 50, 0, 1)
    slope_s = np.clip(r["ma20_slope"] / 5, 0, 1)
    macd_n = np.clip(r["macd_hist"] / r["close"] * 100 / 2, -1, 1) * 0.5 + 0.5
    up_n = np.clip(r["up_days"] / 5, 0, 1)
    return {
        "s_trend_score":    round(float(adx_s * 0.6 + slope_s * 0.4), 4),
        "s_ma_alignment":   round(0.7 + 0.3 * float(r["full_aligned"]), 4),
        "s_momentum":       round(float(macd_n * 0.6 + up_n * 0.4), 4),
        "s_volume_confirm": round(float(r["vol_price_confirm"]), 4),
        "s_sector_trend": 0.0, "s_fundamental": 0.0,
        "s_fund_flow": 0.0, "s_chip": 0.0,
    }


def _f_auction(r):
    """集合竞价选股 — 高开+放量+趋势"""
    gap = r["gap_pct"]
    if gap < 0.5 or gap > 6:
        return None
    vr = r["vol_ratio"]
    if vr < 1.5:
        return None
    gap_s = np.clip(gap / 3, 0, 1) if gap <= 3 else np.clip(1 - (gap - 3) / 3 * 0.5, 0, 1)
    vr_s = np.clip(vr / 10, 0, 1) if vr <= 10 else np.clip(1 - (vr - 10) / 10, 0, 1)
    rsi = r["rsi"]
    rsi_s = 1.0 if 40 <= rsi <= 55 else (0.5 if 30 <= rsi <= 60 else 0.0)
    trend_s = 1.0 if r["above_ma60"] else -0.5
    if -0.15 < r["pullback_5d"] < -0.03:
        trend_s += 1.0
    trend_s = np.clip(trend_s / 2, -1, 1)
    to = r["turnover"]
    to_s = 1.0 if 1 <= to <= 5 else 0.5
    return {
        "s_gap":          round(float(gap_s), 4),
        "s_volume_ratio": round(float(vr_s), 4),
        "s_auction":      round(0.5, 4),  # 回测无竞价异动数据, 默认中性
        "s_trend":        round(float(trend_s), 4),
        "s_rsi":          round(float(rsi_s), 4),
        "s_turnover":     round(float(to_s), 4),
        "s_fundamental":  0.0, "s_hot": 0.0,
        "s_fund_flow":    0.0, "s_chip": 0.0,
    }


def _f_afternoon(r):
    """尾盘短线选股 — 午后蓄势+涨幅适中+量能"""
    pct = r["pct_chg"]
    if pct < 0.5 or pct > 5:
        return None
    vr = r["vol_ratio"]
    if vr < 1.0:
        return None
    # 午后涨幅 (用 日涨幅 * 日内位置 近似)
    pm = pct * r.get("intraday_pos", 0.5)
    pm_s = np.clip(pm / 3, 0, 1) if pm > 0 else 0.0
    pct_s = 1.0 if 1 <= pct <= 3 else 0.5
    vt_s = np.clip(vr / 5, 0, 1) * 0.5 + np.clip(r["turnover"] / 8, 0, 1) * 0.5
    rsi = r["rsi"]
    rsi_s = 1.0 if 40 <= rsi <= 60 else 0.3
    trend_s = 1.0 if r["above_ma60"] else -0.5
    speed_s = np.clip(r.get("intraday_pos", 0.5), 0, 1)
    return {
        "s_pm_gain":     round(float(pm_s), 4),
        "s_pct":         round(float(pct_s), 4),
        "s_vol_turn":    round(float(vt_s), 4),
        "s_trend":       round(float(np.clip(trend_s, -1, 1)), 4),
        "s_rsi":         round(float(rsi_s), 4),
        "s_5m_speed":    round(float(speed_s), 4),
        "s_fundamental": 0.0, "s_hot": 0.0,
        "s_fund_flow":   0.0, "s_chip": 0.0,
    }


def _f_sector_rotation(r):
    """板块轮动选股 — 涨幅适中+量能+趋势 (板块因子用个股特征近似)"""
    pct = r["pct_chg"]
    if pct < 0 or pct > 8:
        return None
    if r["vol_ratio"] < 0.8:
        return None
    # 补涨空间 = 涨了一点但没涨透 (1~3%最优)
    gap_s = 1.0 if 1 <= pct <= 3 else (0.5 if 0 <= pct <= 5 else 0.2)
    # 量能
    vol_s = np.clip(r["vol_ratio"] / 3, 0, 1)
    # 日内位置偏强
    pos_s = r.get("intraday_pos", 0.5)
    # 换手适中
    to = r["turnover"]
    to_s = 1.0 if 3 <= to <= 8 else (0.5 if 1 <= to <= 12 else 0.2)
    # 趋势
    trend_s = 1.0 if r["above_ma60"] else 0.3
    mom_s = np.clip((r["ret_3d"] + 0.05) / 0.1, 0, 1)
    return {
        "s_follow_potential":  round(float(gap_s), 4),
        "s_sector_momentum":   round(float(mom_s), 4),
        "s_sector_flow":       round(float(vol_s), 4),
        "s_sector_breadth":    round(float(pos_s), 4),
        "s_relative_strength": round(float(trend_s), 4),
        "s_chip":              round(float(to_s), 4),
        "s_fundamental":       0.0,
    }


_STRATS = {
    "隔夜选股":     _f_overnight,
    "放量突破选股":  _f_breakout,
    "低吸回调选股":  _f_dip_buy,
    "缩量整理选股":  _f_consolidation,
    "趋势跟踪选股":  _f_trend_follow,
    "集合竞价选股":  _f_auction,
    "尾盘短线选股":  _f_afternoon,
    "板块轮动选股":  _f_sector_rotation,
}


# ==================================================================
#  数据拉取
# ==================================================================

def _sina_sym(code):
    """股票代码 → 新浪符号 (sh/sz prefix)"""
    c = str(code).zfill(6)
    return f"sh{c}" if c.startswith(("6", "9")) else f"sz{c}"


def _fetch_kline(code, start_date="20240101"):
    """拉取真实日线 (新浪源, 前复权, 自动重试)"""
    sym = _sina_sym(code)
    for attempt in range(3):
        try:
            df = ak.stock_zh_a_daily(
                symbol=sym, start_date=start_date,
                end_date=time.strftime("%Y%m%d"), adjust="qfq",
            )
            break
        except Exception as e:
            if attempt == 2:
                return None
            time.sleep(2 * (attempt + 1))
    if df is None or len(df) < 80:
        return None
    # 新浪源列名: date, open, high, low, close, volume, amount,
    #              outstanding_share, turnover (小数, 需×100)
    for col in ("open", "close", "high", "low", "volume", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["turnover"] = pd.to_numeric(df.get("turnover"), errors="coerce").fillna(0) * 100
    df["pct_chg"] = df["close"].pct_change() * 100
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df.dropna(subset=["close"]).reset_index(drop=True)


def _get_pool(n=100):
    """CSI1000 成分股"""
    try:
        df = ak.index_stock_cons(symbol="000852")
        codes = df["品种代码"].tolist()
        names = dict(zip(df["品种代码"], df["品种名称"]))
    except Exception:
        df = ak.index_stock_cons_csindex(symbol="000852")
        codes = df["成分券代码"].astype(str).str.zfill(6).tolist()
        names = dict(zip(codes, df["成分券名称"]))
    codes = [c for c in codes if not str(c).startswith(("688", "8", "4"))]
    return codes[:n], names


# ==================================================================
#  处理单只股票
# ==================================================================

def _process_stock(code, name, start_date):
    """拉K线 → 算因子 → 返回 DB 记录列表"""
    df = _fetch_kline(code, start_date)
    if df is None:
        return []
    df = _compute_features(df)

    # 仅取 MA60 有效 + 有 T+1 收益的行
    mask = df["ma60"].notna() & df["ret_t1"].notna() & df["rsi"].notna()
    valid = df[mask]
    if valid.empty:
        return []

    records = []
    for _, row in valid.iterrows():
        ret = row["ret_t1"]
        if pd.isna(ret):
            continue
        dt = row["date"]
        price = row["close"]
        ret_pct = round(float(ret) * 100, 4)

        for strat, fn in _STRATS.items():
            try:
                fs = fn(row)
            except Exception:
                continue
            if fs is None:
                continue
            tech_vals = [v for v in fs.values() if v != 0.0]
            score = round(np.mean(tech_vals), 4) if tech_vals else 0.0
            records.append((
                dt, code, _MARKER, strat,
                score, json.dumps(fs), ret_pct,
                round(float(price), 2),
                1 if ret > 0 else 0,
                "win" if ret > 0 else "loss",
            ))
    return records


# ==================================================================
#  主引擎
# ==================================================================

def run(n_stocks=100, start_date="20240101", clean_old=False):
    print("=" * 65)
    print("  真实历史回测引擎 v1.0")
    print(f"  股票数={n_stocks}  起始={start_date}  清旧={clean_old}")
    print("=" * 65)

    conn = sqlite3.connect(_DB)
    cur = conn.cursor()

    if clean_old:
        cur.execute("DELETE FROM scorecard WHERE name IN (?, 'AUTH_BACKFILL', 'ml_backfill', '')",
                    (_MARKER,))
        conn.commit()
        deleted = cur.execute("SELECT changes()").fetchone()[0]
        print(f"  清除旧回测数据: {deleted} 条")

    # 已有记录 → 跳过 (支持断点续跑)
    cur.execute(f"SELECT DISTINCT code FROM scorecard WHERE name=?", (_MARKER,))
    done_codes = {r[0] for r in cur.fetchall()}

    codes, names = _get_pool(n_stocks)
    todo = [c for c in codes if c not in done_codes]
    print(f"\n  股池 {len(codes)} 只, 已完成 {len(done_codes)}, 待跑 {len(todo)}")

    total = 0
    sc = {s: 0 for s in _STRATS}
    t0 = time.time()

    for i, code in enumerate(todo):
        try:
            recs = _process_stock(code, names.get(code, ""), start_date)
            if recs:
                cur.executemany(
                    "INSERT OR IGNORE INTO scorecard "
                    "(rec_date,code,name,strategy,score,factor_scores,"
                    "net_return_pct,rec_price,win,result) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)", recs)
                conn.commit()
                for r in recs:
                    sc[r[3]] = sc.get(r[3], 0) + 1
                total += len(recs)

            if (i + 1) % 5 == 0 or i == len(todo) - 1:
                el = time.time() - t0
                eta = el / (i + 1) * (len(todo) - i - 1)
                print(f"  [{i+1}/{len(todo)}] {code} +{len(recs)} | "
                      f"累计 {total} | ETA {eta/60:.1f}m")
            time.sleep(_SLEEP)
        except Exception as e:
            print(f"  [{i+1}/{len(todo)}] {code} err: {e}")
            time.sleep(1)

    conn.close()
    el = time.time() - t0

    print(f"\n{'=' * 65}")
    print(f"  完成! {el/60:.1f} 分钟 | 新增 {total} 条")
    for s, c in sorted(sc.items(), key=lambda x: -x[1]):
        print(f"    {s}: {c}")

    # 质量检查
    _quality_check()
    return total


def _quality_check():
    """数据质量报告"""
    conn = sqlite3.connect(_DB)
    cur = conn.cursor()
    cur.execute(f"""
        SELECT strategy, COUNT(*),
               ROUND(AVG(net_return_pct), 3),
               ROUND(AVG(CASE WHEN win=1 THEN 1.0 ELSE 0.0 END), 3),
               ROUND(MIN(net_return_pct), 2),
               ROUND(MAX(net_return_pct), 2)
        FROM scorecard WHERE name=?
        GROUP BY strategy ORDER BY COUNT(*) DESC
    """, (_MARKER,))
    rows = cur.fetchall()
    if not rows:
        print("  (无 REAL_BT 数据)")
        conn.close()
        return
    print(f"\n  数据质量 (REAL_BT):")
    for r in rows:
        print(f"    {r[0]:12s} | N={r[1]:5d} | avg_ret={r[2]:+.3f}% | "
              f"WR={r[3]:.1%} | [{r[4]:+.1f}%, {r[5]:+.1f}%]")

    # 整体统计
    cur.execute(f"SELECT COUNT(*), AVG(net_return_pct), "
                f"AVG(abs(net_return_pct)) FROM scorecard WHERE name=?",
                (_MARKER,))
    t = cur.fetchone()
    print(f"  整体: {t[0]} 条 | mean_ret={t[1]:+.3f}% | mean|ret|={t[2]:.3f}%")
    conn.close()


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 100
    clean = "--clean" in sys.argv
    run(n_stocks=n, start_date="20240101", clean_old=clean)
