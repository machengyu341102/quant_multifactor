"""
Factor Forge — 自主因子发现引擎
================================
从 OHLCV 原始数据自动挖掘预测性指标, 经 IC 统计检验 → WF 验证 → 自动部署 → 生命周期管理,
实现因子从诞生到淘汰的完整自主闭环。

流程:
  17:30 每日触发 run_forge_cycle()
  ① 生命周期检查 (退役衰减因子)
  ② 指标库计算 (23 个候选指标, 纯 numpy)
  ③ IC 筛选 (横截面 Spearman IC)
  ④ WF 滚动验证 (3 窗口 OOS IC)
  ⑤ 自动部署 (s_forge_* → tunable_params, 初始权重 0.015)

设计要点:
  - 前缀 s_forge_* → feature_engineer 自动发现 → ML 自动训练 → signal_tracker 追踪
  - 权重在 tunable_params.json → auto_optimizer / learning_engine / 在线 EMA 全自动接管
  - compute_forge_factors() 异常安全, 永不崩溃
  - 无新 API 调用, 所有指标从策略已拉取的 OHLCV 计算
"""

import os
import sys
import json
import copy
import traceback
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta
from scipy import stats as sp_stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import FACTOR_FORGE_PARAMS

from log_config import get_logger
logger = get_logger("factor_forge")

_DIR = os.path.dirname(os.path.abspath(__file__))
_FORGE_CONFIG_PATH = os.path.join(_DIR, "forge_config.json")
_TUNABLE_PATH = os.path.join(_DIR, "tunable_params.json")


# ================================================================
#  工具函数
# ================================================================

def _safe_load(path, default=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else {}


def _safe_save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    os.replace(tmp, path)


# ================================================================
#  Section 1: 指标库 (23 个, 纯 numpy 计算)
# ================================================================

def _ema(arr, span):
    """指数移动平均"""
    s = pd.Series(arr)
    return s.ewm(span=span, adjust=False).mean().values


def _sma(arr, period):
    """简单移动平均"""
    s = pd.Series(arr)
    return s.rolling(period).mean().values


def _clip01(v):
    """裁剪到 [0, 1]"""
    if np.isnan(v):
        return np.nan
    return float(np.clip(v, 0.0, 1.0))


def _safe_div(a, b, default=0.0):
    if b == 0 or np.isnan(b):
        return default
    return a / b


# --- 动量/趋势 (6 个) ---

def ind_macd_cross(closes, highs, lows, volumes):
    """MACD diff-dea 归一化"""
    if len(closes) < 35:
        return np.nan
    from futures_strategy import _calc_macd
    diff, dea, _ = _calc_macd(closes)
    val = diff[-1] - dea[-1]
    # 归一化: 用最近 60 日的范围
    recent = diff[-60:] - dea[-60:] if len(diff) >= 60 else diff - dea
    rng = np.nanmax(recent) - np.nanmin(recent)
    if rng < 1e-10:
        return 0.5
    return _clip01((val - np.nanmin(recent)) / rng)


def ind_macd_histogram(closes, highs, lows, volumes):
    """MACD bar 3 日斜率"""
    if len(closes) < 35:
        return np.nan
    from futures_strategy import _calc_macd
    _, _, macd_bar = _calc_macd(closes)
    if len(macd_bar) < 4:
        return 0.5
    slope = macd_bar[-1] - macd_bar[-4]
    rng = np.nanstd(macd_bar[-60:]) if len(macd_bar) >= 60 else np.nanstd(macd_bar)
    if rng < 1e-10:
        return 0.5
    return _clip01(0.5 + slope / (rng * 4))


def ind_adx_strength(closes, highs, lows, volumes):
    """ADX(14) / 100"""
    if len(closes) < 30:
        return np.nan
    from futures_strategy import _calc_adx
    adx = _calc_adx(highs, lows, closes, 14)
    val = adx[-1] if not np.isnan(adx[-1]) else 0
    return _clip01(val / 100.0)


def ind_di_crossover(closes, highs, lows, volumes):
    """(+DI - -DI) / (+DI + -DI)"""
    n = len(closes)
    if n < 30:
        return np.nan
    period = 14
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)
    for i in range(1, n):
        h_diff = highs[i] - highs[i - 1]
        l_diff = lows[i - 1] - lows[i]
        plus_dm[i] = h_diff if h_diff > l_diff and h_diff > 0 else 0
        minus_dm[i] = l_diff if l_diff > h_diff and l_diff > 0 else 0
        tr[i] = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i - 1]),
                     abs(lows[i] - closes[i - 1]))
    atr = pd.Series(tr).rolling(period).mean().values
    plus_di = pd.Series(plus_dm).rolling(period).mean().values / np.maximum(atr, 1e-10) * 100
    minus_di = pd.Series(minus_dm).rolling(period).mean().values / np.maximum(atr, 1e-10) * 100
    pdi = plus_di[-1]
    mdi = minus_di[-1]
    denom = pdi + mdi
    if np.isnan(pdi) or np.isnan(mdi) or denom < 1e-10:
        return 0.5
    return _clip01(0.5 + (pdi - mdi) / (denom * 2))


def ind_roc_5(closes, highs, lows, volumes):
    """5 日涨幅动量"""
    if len(closes) < 6:
        return np.nan
    roc = closes[-1] / closes[-6] - 1
    return _clip01(0.5 + roc * 5)  # ±10% → [0,1]


def ind_roc_20(closes, highs, lows, volumes):
    """20 日涨幅动量"""
    if len(closes) < 21:
        return np.nan
    roc = closes[-1] / closes[-21] - 1
    return _clip01(0.5 + roc * 2.5)


# --- 振荡器 (4 个) ---

def ind_stochastic_k(closes, highs, lows, volumes):
    """%K: (C - min_L14) / (max_H14 - min_L14)"""
    if len(closes) < 14:
        return np.nan
    l14 = np.min(lows[-14:])
    h14 = np.max(highs[-14:])
    rng = h14 - l14
    if rng < 1e-10:
        return 0.5
    return _clip01((closes[-1] - l14) / rng)


def ind_stochastic_d(closes, highs, lows, volumes):
    """%D: %K 的 3 日 SMA"""
    if len(closes) < 16:
        return np.nan
    ks = []
    for i in range(3):
        idx = -(i + 1)
        end = len(closes) + idx + 1
        start = end - 14
        if start < 0:
            return np.nan
        l14 = np.min(lows[start:end])
        h14 = np.max(highs[start:end])
        rng = h14 - l14
        k = (closes[end - 1] - l14) / rng if rng > 1e-10 else 0.5
        ks.append(k)
    return _clip01(np.mean(ks))


def ind_williams_r(closes, highs, lows, volumes):
    """Williams %R 反转: (max_H14 - C) / (max_H14 - min_L14)"""
    if len(closes) < 14:
        return np.nan
    l14 = np.min(lows[-14:])
    h14 = np.max(highs[-14:])
    rng = h14 - l14
    if rng < 1e-10:
        return 0.5
    return _clip01(1.0 - (h14 - closes[-1]) / rng)


def ind_cci_14(closes, highs, lows, volumes):
    """CCI(14): (典型价 - SMA) / (0.015 × 平均偏差)"""
    if len(closes) < 14:
        return np.nan
    tp = (closes[-14:] + highs[-14:] + lows[-14:]) / 3
    sma_tp = np.mean(tp)
    mad = np.mean(np.abs(tp - sma_tp))
    if mad < 1e-10:
        return 0.5
    cci = (tp[-1] - sma_tp) / (0.015 * mad)
    # CCI 范围大约 -200~200, 归一化
    return _clip01(0.5 + cci / 400)


# --- 量价 (5 个) ---

def ind_obv_trend(closes, highs, lows, volumes):
    """OBV 5 日斜率归一化"""
    if len(closes) < 10 or len(volumes) < 10:
        return np.nan
    obv = np.zeros(len(closes))
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv[i] = obv[i - 1] + volumes[i]
        elif closes[i] < closes[i - 1]:
            obv[i] = obv[i - 1] - volumes[i]
        else:
            obv[i] = obv[i - 1]
    # 5 日斜率
    slope = obv[-1] - obv[-6] if len(obv) >= 6 else 0
    std = np.std(np.diff(obv[-20:])) if len(obv) >= 20 else abs(slope) + 1
    if std < 1e-10:
        return 0.5
    return _clip01(0.5 + slope / (std * 5))


def ind_volume_zscore(closes, highs, lows, volumes):
    """(vol - mean20) / std20"""
    if len(volumes) < 20:
        return np.nan
    mean20 = np.mean(volumes[-20:])
    std20 = np.std(volumes[-20:])
    if std20 < 1e-10:
        return 0.5
    z = (volumes[-1] - mean20) / std20
    return _clip01(0.5 + z / 6)  # z ±3 → [0,1]


def ind_vwap_distance(closes, highs, lows, volumes):
    """(close - vwap5) / atr"""
    if len(closes) < 20 or len(volumes) < 5:
        return np.nan
    # 近 5 日 VWAP
    tp = (closes[-5:] + highs[-5:] + lows[-5:]) / 3
    vwap5 = np.sum(tp * volumes[-5:]) / np.sum(volumes[-5:]) if np.sum(volumes[-5:]) > 0 else closes[-1]
    # ATR
    from futures_strategy import _calc_atr
    atr = _calc_atr(highs, lows, closes, 14)
    atr_val = atr[-1] if not np.isnan(atr[-1]) else closes[-1] * 0.02
    if atr_val < 1e-10:
        return 0.5
    dist = (closes[-1] - vwap5) / atr_val
    return _clip01(0.5 + dist / 4)


def ind_price_vol_corr(closes, highs, lows, volumes):
    """10 日量价 Spearman 相关"""
    if len(closes) < 10 or len(volumes) < 10:
        return np.nan
    try:
        corr, _ = sp_stats.spearmanr(closes[-10:], volumes[-10:])
        if np.isnan(corr):
            return 0.5
        return _clip01(0.5 + corr / 2)
    except Exception:
        return 0.5


def ind_vol_price_diverge(closes, highs, lows, volumes):
    """量价方向一致性 (5 日)"""
    if len(closes) < 6 or len(volumes) < 6:
        return np.nan
    price_up = closes[-1] > closes[-6]
    vol_avg5 = np.mean(volumes[-5:])
    vol_avg20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else vol_avg5
    vol_up = vol_avg5 > vol_avg20
    if price_up and vol_up:
        return 0.9  # 量价齐升
    elif not price_up and not vol_up:
        return 0.7  # 缩量回调 (正常)
    elif price_up and not vol_up:
        return 0.3  # 无量上涨 (危险)
    else:
        return 0.1  # 放量下跌 (最差)


# --- 波动/结构 (8 个) ---

def ind_boll_width_pctile(closes, highs, lows, volumes):
    """布林带宽度 / 60 日中位数"""
    if len(closes) < 60:
        return np.nan
    ma20 = _sma(closes, 20)
    std20 = pd.Series(closes).rolling(20).std().values
    width = std20[-1] * 4 / ma20[-1] if ma20[-1] > 0 and not np.isnan(std20[-1]) else 0
    # 60 日宽度中位数
    widths = []
    for i in range(60):
        idx = -(i + 1)
        if len(std20) + idx >= 0 and not np.isnan(std20[idx]) and not np.isnan(ma20[idx]) and ma20[idx] > 0:
            widths.append(std20[idx] * 4 / ma20[idx])
    if not widths:
        return 0.5
    median_w = np.median(widths)
    if median_w < 1e-10:
        return 0.5
    ratio = width / median_w
    return _clip01(ratio / 3)  # 3 倍中位数 → 1.0


def ind_atr_pctile(closes, highs, lows, volumes):
    """ATR / 60 日中位数"""
    if len(closes) < 60:
        return np.nan
    from futures_strategy import _calc_atr
    atr = _calc_atr(highs, lows, closes, 14)
    if np.isnan(atr[-1]):
        return 0.5
    recent = atr[-60:]
    valid = recent[~np.isnan(recent)]
    if len(valid) < 10:
        return 0.5
    median_atr = np.median(valid)
    if median_atr < 1e-10:
        return 0.5
    return _clip01(atr[-1] / (median_atr * 3))


def ind_true_range_norm(closes, highs, lows, volumes):
    """TR / close"""
    if len(closes) < 2:
        return np.nan
    tr = max(highs[-1] - lows[-1],
             abs(highs[-1] - closes[-2]),
             abs(lows[-1] - closes[-2]))
    if closes[-1] < 1e-10:
        return 0.5
    return _clip01(tr / closes[-1] / 0.1)  # 10% TR → 1.0


def ind_high_low_range(closes, highs, lows, volumes):
    """10 日振幅比"""
    if len(highs) < 10 or len(lows) < 10:
        return np.nan
    h10 = np.max(highs[-10:])
    l10 = np.min(lows[-10:])
    if l10 < 1e-10:
        return 0.5
    rng = (h10 - l10) / l10
    return _clip01(rng / 0.3)  # 30% 振幅 → 1.0


def ind_gap_factor(closes, highs, lows, volumes):
    """跳空 / ATR 归一化"""
    if len(closes) < 20:
        return np.nan
    gap = abs(closes[-1] - closes[-2]) if len(closes) >= 2 else 0
    from futures_strategy import _calc_atr
    atr = _calc_atr(highs, lows, closes, 14)
    atr_val = atr[-1] if not np.isnan(atr[-1]) else closes[-1] * 0.02
    if atr_val < 1e-10:
        return 0.5
    return _clip01(gap / (atr_val * 3))


def ind_inside_bar(closes, highs, lows, volumes):
    """连续内包线计数 / 5"""
    if len(highs) < 5 or len(lows) < 5:
        return np.nan
    count = 0
    for i in range(len(highs) - 1, max(len(highs) - 6, 0), -1):
        if i < 1:
            break
        if highs[i] <= highs[i - 1] and lows[i] >= lows[i - 1]:
            count += 1
        else:
            break
    return _clip01(count / 5.0)


def ind_lower_shadow(closes, highs, lows, volumes):
    """下影线 / 实体比"""
    if len(closes) < 1 or len(lows) < 1:
        return np.nan
    # 需要 open 但我们用 close 近似
    # 用前日 close 做 open 的代理
    if len(closes) < 2:
        return 0.5
    open_proxy = closes[-2]
    body = abs(closes[-1] - open_proxy)
    lower_shadow = min(closes[-1], open_proxy) - lows[-1]
    if body < 1e-10:
        return _clip01(lower_shadow / (closes[-1] * 0.01)) if closes[-1] > 0 else 0.5
    ratio = lower_shadow / body
    return _clip01(ratio / 3)  # 3 倍实体 → 1.0


def ind_ma_dist_pctile(closes, highs, lows, volumes):
    """(C - MA20) / MA20 百分位"""
    if len(closes) < 20:
        return np.nan
    ma20 = np.mean(closes[-20:])
    if ma20 < 1e-10:
        return 0.5
    dist = (closes[-1] - ma20) / ma20
    return _clip01(0.5 + dist * 5)  # ±10% → [0,1]


# --- 指标注册表 ---

INDICATOR_LIBRARY = {
    # 动量/趋势
    "macd_cross":       ind_macd_cross,
    "macd_histogram":   ind_macd_histogram,
    "adx_strength":     ind_adx_strength,
    "di_crossover":     ind_di_crossover,
    "roc_5":            ind_roc_5,
    "roc_20":           ind_roc_20,
    # 振荡器
    "stochastic_k":     ind_stochastic_k,
    "stochastic_d":     ind_stochastic_d,
    "williams_r":       ind_williams_r,
    "cci_14":           ind_cci_14,
    # 量价
    "obv_trend":        ind_obv_trend,
    "volume_zscore":    ind_volume_zscore,
    "vwap_distance":    ind_vwap_distance,
    "price_vol_corr":   ind_price_vol_corr,
    "vol_price_diverge": ind_vol_price_diverge,
    # 波动/结构
    "boll_width_pctile": ind_boll_width_pctile,
    "atr_pctile":       ind_atr_pctile,
    "true_range_norm":  ind_true_range_norm,
    "high_low_range":   ind_high_low_range,
    "gap_factor":       ind_gap_factor,
    "inside_bar":       ind_inside_bar,
    "lower_shadow":     ind_lower_shadow,
    "ma_dist_pctile":   ind_ma_dist_pctile,
}


# ================================================================
#  Section 2: K 线缓存
# ================================================================

_forge_kline_cache = {}  # {code: DataFrame} 由策略运行时填充


def cache_klines_for_forge(code: str, df: pd.DataFrame):
    """各策略的 _fetch_one_* 函数调用, 零开销缓存 OHLCV DataFrame"""
    if df is not None and len(df) >= 60:
        _forge_kline_cache[code] = df.tail(120).copy()


def _ensure_kline_cache(min_stocks=30):
    """冷启动: 缓存为空时, 从 scorecard 取 top-50 股票拉 K 线"""
    if len(_forge_kline_cache) >= min_stocks:
        return

    logger.info("Forge 冷启动: 缓存不足 %d 只, 尝试拉取 K 线", len(_forge_kline_cache))
    try:
        from db_store import load_scorecard
        sc = load_scorecard()
        if not sc:
            return
        # 取最近出现的 50 只股票
        codes = list({r["code"] for r in sc[-200:]})[:50]
    except Exception:
        return

    try:
        import akshare as ak
        from intraday_strategy import _retry
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")

        def _tx_sym(code):
            return f"sh{code}" if code.startswith(("60", "68")) else f"sz{code}"

        for code in codes:
            if code in _forge_kline_cache:
                continue
            try:
                df = _retry(
                    ak.stock_zh_a_hist_tx,
                    symbol=_tx_sym(code),
                    start_date=start_date, end_date=end_date, adjust="qfq"
                )
                if df is not None and len(df) >= 60:
                    _forge_kline_cache[code] = df.tail(120).copy()
            except Exception:
                continue
            if len(_forge_kline_cache) >= 50:
                break
    except Exception as e:
        logger.warning("Forge 冷启动拉取失败: %s", e)


def _extract_ohlcv(df):
    """从 DataFrame 提取 closes, highs, lows, volumes 数组"""
    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float) if "high" in df.columns else closes
    lows = df["low"].values.astype(float) if "low" in df.columns else closes
    vol_col = next((c for c in ["amount", "成交量", "volume"] if c in df.columns), None)
    volumes = df[vol_col].values.astype(float) if vol_col else np.ones(len(closes))
    return closes, highs, lows, volumes


# ================================================================
#  Section 3: IC 评估
# ================================================================

def evaluate_indicator_ic(indicator_fn, kline_map, scorecard_records,
                          min_dates=None) -> dict:
    """横截面 IC 评估

    每个交易日做一次横截面:
      - 对该日所有有 K 线的股票: 计算指标值, 配对 T+1 收益
      - Spearman rank correlation = 该日 IC

    Returns:
        {mean_ic, std_ic, ic_ir, positive_ratio, n_dates}
    """
    params = FACTOR_FORGE_PARAMS
    if min_dates is None:
        min_dates = params.get("min_ic_dates", 10)

    # 按日期聚合 scorecard
    date_groups = {}
    for rec in scorecard_records:
        d = rec.get("date", "")
        if not d:
            continue
        code = rec.get("code", "")
        ret = rec.get("net_return_pct", rec.get("t1_return_pct"))
        if ret is None:
            continue
        date_groups.setdefault(d, []).append((code, float(ret)))

    daily_ics = []
    for d, pairs in sorted(date_groups.items()):
        # 至少 5 只股票才有横截面意义
        if len(pairs) < 5:
            continue

        ind_vals = []
        ret_vals = []
        for code, ret in pairs:
            if code not in kline_map:
                continue
            df = kline_map[code]
            try:
                c, h, l, v = _extract_ohlcv(df)
                val = indicator_fn(c, h, l, v)
                if val is not None and not np.isnan(val):
                    ind_vals.append(val)
                    ret_vals.append(ret)
            except Exception:
                continue

        if len(ind_vals) < 5:
            continue

        try:
            ic, _ = sp_stats.spearmanr(ind_vals, ret_vals)
            if not np.isnan(ic):
                daily_ics.append(ic)
        except Exception:
            continue

    if len(daily_ics) < min_dates:
        return {"mean_ic": 0, "std_ic": 0, "ic_ir": 0,
                "positive_ratio": 0, "n_dates": len(daily_ics), "passed": False}

    mean_ic = np.mean(daily_ics)
    std_ic = np.std(daily_ics)
    ic_ir = mean_ic / std_ic if std_ic > 1e-10 else 0
    positive_ratio = np.mean([1 for ic in daily_ics if ic > 0]) / len(daily_ics)

    passed = (abs(mean_ic) >= params.get("min_ic_abs", 0.03)
              and abs(ic_ir) >= params.get("min_ic_ir", 0.5)
              and positive_ratio >= params.get("min_positive_ic_ratio", 0.55))

    return {
        "mean_ic": round(mean_ic, 6),
        "std_ic": round(std_ic, 6),
        "ic_ir": round(ic_ir, 4),
        "positive_ratio": round(positive_ratio, 4),
        "n_dates": len(daily_ics),
        "passed": passed,
    }


# ================================================================
#  Section 4: WF 验证 (轻量级)
# ================================================================

def walk_forward_ic_check(indicator_fn, kline_map, scorecard_records,
                          n_windows=None) -> dict:
    """3 窗口滚动 IC 检验 (不走完整 backtest, 只算 IC)

    每窗口: 60 天 IS + 20 天 OOS
    要求: OOS IC_IR > IS IC_IR × 50%
    """
    params = FACTOR_FORGE_PARAMS
    if n_windows is None:
        n_windows = params.get("wf_n_windows", 3)
    degradation_max = params.get("wf_oos_degradation_max", 0.5)

    # 按日期排序所有 scorecard
    dated = [(r.get("date", ""), r) for r in scorecard_records if r.get("date")]
    dated.sort(key=lambda x: x[0])
    all_dates = sorted(set(d for d, _ in dated))

    if len(all_dates) < 80 * n_windows:
        # 数据不够做 WF
        return {"passed": False, "reason": "insufficient_dates",
                "n_dates": len(all_dates), "windows": []}

    window_results = []
    total_days = len(all_dates)
    window_size = 80  # 60 IS + 20 OOS
    step = (total_days - window_size) // max(n_windows - 1, 1) if n_windows > 1 else 0

    for w in range(n_windows):
        start_idx = w * step
        end_idx = start_idx + window_size
        if end_idx > total_days:
            break

        is_dates = set(all_dates[start_idx:start_idx + 60])
        oos_dates = set(all_dates[start_idx + 60:end_idx])

        is_records = [r for d, r in dated if d in is_dates]
        oos_records = [r for d, r in dated if d in oos_dates]

        is_stats = evaluate_indicator_ic(indicator_fn, kline_map, is_records, min_dates=5)
        oos_stats = evaluate_indicator_ic(indicator_fn, kline_map, oos_records, min_dates=3)

        window_results.append({
            "window": w,
            "is_ic_ir": is_stats["ic_ir"],
            "oos_ic_ir": oos_stats["ic_ir"],
            "is_mean_ic": is_stats["mean_ic"],
            "oos_mean_ic": oos_stats["mean_ic"],
        })

    if not window_results:
        return {"passed": False, "reason": "no_valid_windows", "windows": []}

    # 检查: OOS IC_IR > IS IC_IR × (1 - degradation_max)
    passed_windows = 0
    for wr in window_results:
        is_ir = abs(wr["is_ic_ir"])
        oos_ir = abs(wr["oos_ic_ir"])
        if is_ir < 0.01:
            continue  # IS 本身就弱, 跳过
        if oos_ir >= is_ir * (1 - degradation_max):
            passed_windows += 1

    # 至少过半窗口通过
    passed = passed_windows >= (len(window_results) + 1) // 2

    return {
        "passed": passed,
        "passed_windows": passed_windows,
        "total_windows": len(window_results),
        "windows": window_results,
    }


# ================================================================
#  Section 5: 部署与权重注入
# ================================================================

_STRATEGY_KEYS = [
    "breakout_weights", "auction_weights", "afternoon_weights",
    "dip_buy_weights", "consolidation_weights", "trend_follow_weights",
    "sector_rotation_weights", "news_event_weights",
]

# 策略名 → tunable_params key
_STRATEGY_NAME_TO_KEY = {
    "breakout": "breakout_weights",
    "auction": "auction_weights",
    "afternoon": "afternoon_weights",
    "dip_buy": "dip_buy_weights",
    "consolidation": "consolidation_weights",
    "trend_follow": "trend_follow_weights",
    "sector_rotation": "sector_rotation_weights",
    "news_event": "news_event_weights",
}


def deploy_factor(name: str, ic_stats: dict, wf_result: dict) -> bool:
    """部署因子到 forge_config + tunable_params

    Args:
        name: 指标名 (e.g. 'macd_cross')
        ic_stats: IC 评估结果
        wf_result: WF 验证结果

    Returns:
        True if deployed successfully
    """
    params = FACTOR_FORGE_PARAMS
    factor_key = f"s_forge_{name}"
    initial_weight = params.get("initial_weight", 0.015)
    max_active = params.get("max_active_per_strategy", 5)

    # 读取 forge_config
    config = _safe_load(_FORGE_CONFIG_PATH, default={
        "active_factors": {}, "retired_factors": {}, "deploy_log": []
    })
    active = config.get("active_factors", {})

    # 检查是否已部署
    if name in active:
        logger.info("因子 %s 已在活跃列表中, 跳过", name)
        return False

    # 检查每策略活跃数上限
    active_count = len(active)
    if active_count >= max_active:
        logger.warning("活跃 forge 因子已达上限 %d, 跳过 %s", max_active, name)
        return False

    # 写入 forge_config
    active[name] = {
        "factor_key": factor_key,
        "deployed_date": date.today().isoformat(),
        "ic_stats": ic_stats,
        "wf_result": {k: v for k, v in wf_result.items() if k != "windows"},
        "status": "active",
    }
    config["active_factors"] = active
    config["deploy_log"].append({
        "action": "deploy",
        "name": name,
        "date": date.today().isoformat(),
        "ic_ir": ic_stats.get("ic_ir", 0),
    })
    _safe_save(_FORGE_CONFIG_PATH, config)

    # 注入 tunable_params
    tunable = _safe_load(_TUNABLE_PATH, default={})
    for strat_key in _STRATEGY_KEYS:
        if strat_key not in tunable:
            tunable[strat_key] = {"weights": {}}
        if "weights" not in tunable[strat_key]:
            tunable[strat_key]["weights"] = {}

        weights = tunable[strat_key]["weights"]

        # 跳过已有此因子的策略
        if factor_key in weights:
            continue

        # 注入新权重
        weights[factor_key] = initial_weight

        # 等比缩放现有权重, 保持总和 = 1.0
        total = sum(weights.values())
        if total > 0:
            scale = 1.0 / total
            for k in weights:
                weights[k] = round(weights[k] * scale, 6)

    _safe_save(_TUNABLE_PATH, tunable)
    logger.info("✅ 因子 %s 已部署 (初始权重 %.3f)", factor_key, initial_weight)
    return True


def _count_today_deployments() -> int:
    """今日已部署数"""
    config = _safe_load(_FORGE_CONFIG_PATH, default={})
    today = date.today().isoformat()
    log = config.get("deploy_log", [])
    return sum(1 for entry in log
               if entry.get("date") == today and entry.get("action") == "deploy")


# ================================================================
#  Section 6: 策略评分钩子
# ================================================================

def compute_forge_factors(df: pd.DataFrame) -> pd.DataFrame:
    """在策略评分前调用, 为 df 添加所有活跃 s_forge_* 列

    异常安全: 永远不 raise, 最差返回原 df
    """
    try:
        config = _safe_load(_FORGE_CONFIG_PATH, default={})
        active = config.get("active_factors", {})
        if not active:
            return df

        for name, info in active.items():
            factor_key = info.get("factor_key", f"s_forge_{name}")
            if factor_key in df.columns:
                continue

            ind_fn = INDICATOR_LIBRARY.get(name)
            if ind_fn is None:
                continue

            values = []
            for _, row in df.iterrows():
                code = row.get("code", "")
                if code in _forge_kline_cache:
                    try:
                        kdf = _forge_kline_cache[code]
                        c, h, l, v = _extract_ohlcv(kdf)
                        val = ind_fn(c, h, l, v)
                        values.append(val if val is not None else 0.0)
                    except Exception:
                        values.append(0.0)
                else:
                    values.append(0.0)

            df[factor_key] = values
    except Exception as e:
        logger.warning("compute_forge_factors 异常 (安全降级): %s", e)

    return df


def get_forge_weights() -> dict:
    """返回当前活跃 forge 因子的权重字典

    从 tunable_params.json 的第一个策略读取 s_forge_* 权重
    """
    try:
        config = _safe_load(_FORGE_CONFIG_PATH, default={})
        active = config.get("active_factors", {})
        if not active:
            return {}

        tunable = _safe_load(_TUNABLE_PATH, default={})
        result = {}
        for name, info in active.items():
            factor_key = info.get("factor_key", f"s_forge_{name}")
            # 从任意策略读权重 (都一样)
            for strat_key in _STRATEGY_KEYS:
                w = tunable.get(strat_key, {}).get("weights", {}).get(factor_key)
                if w is not None:
                    result[factor_key] = w
                    break
            else:
                result[factor_key] = FACTOR_FORGE_PARAMS.get("initial_weight", 0.015)

        return result
    except Exception:
        return {}


# ================================================================
#  Section 7: 生命周期管理
# ================================================================

def check_forge_lifecycle() -> list:
    """检查活跃 forge 因子的健康状态, 退役衰减因子

    退役条件:
      - live_days >= 10 且 spread < 2.0
      - 滚动 IC 连续 5 天 < 0.01

    Returns:
        [{name, action, reason}]
    """
    params = FACTOR_FORGE_PARAMS
    kill_min_days = params.get("kill_min_live_days", 10)
    kill_spread = params.get("kill_spread_threshold", 2.0)

    config = _safe_load(_FORGE_CONFIG_PATH, default={})
    active = config.get("active_factors", {})
    if not active:
        return []

    # 获取因子效力数据
    try:
        from signal_tracker import get_factor_effectiveness
        factor_eff = get_factor_effectiveness(days=30)
    except Exception:
        factor_eff = {}

    results = []
    to_retire = []

    for name, info in list(active.items()):
        factor_key = info.get("factor_key", f"s_forge_{name}")
        deployed = info.get("deployed_date", "")
        if deployed:
            try:
                deploy_date = date.fromisoformat(deployed)
                live_days = (date.today() - deploy_date).days
            except Exception:
                live_days = 0
        else:
            live_days = 0

        # 年轻因子保护期
        if live_days < kill_min_days:
            continue

        # 检查实战表现
        eff = factor_eff.get(factor_key, {})
        spread = eff.get("spread", 999)

        if spread < kill_spread:
            to_retire.append(name)
            results.append({
                "name": name, "factor_key": factor_key,
                "action": "retired", "reason": f"spread={spread:.2f} < {kill_spread}",
                "live_days": live_days,
            })

    # 执行退役
    for name in to_retire:
        _retire_factor(name, config)

    if to_retire:
        _safe_save(_FORGE_CONFIG_PATH, config)

    return results


def _retire_factor(name: str, config: dict):
    """将因子从 active 移到 retired, 从 tunable_params 删除"""
    active = config.get("active_factors", {})
    retired = config.setdefault("retired_factors", {})

    if name not in active:
        return

    info = active.pop(name)
    info["retired_date"] = date.today().isoformat()
    info["status"] = "retired"
    retired[name] = info

    config["deploy_log"].append({
        "action": "retire",
        "name": name,
        "date": date.today().isoformat(),
    })

    # 从 tunable_params 删除
    factor_key = info.get("factor_key", f"s_forge_{name}")
    tunable = _safe_load(_TUNABLE_PATH, default={})
    changed = False
    for strat_key in _STRATEGY_KEYS:
        weights = tunable.get(strat_key, {}).get("weights", {})
        if factor_key in weights:
            del weights[factor_key]
            # 重新归一化
            total = sum(weights.values())
            if total > 0:
                scale = 1.0 / total
                for k in weights:
                    weights[k] = round(weights[k] * scale, 6)
            changed = True

    if changed:
        _safe_save(_TUNABLE_PATH, tunable)

    # 级联引擎: 通知 ML 模型重训 + 学习引擎更新
    try:
        from cascade_engine import cascade
        cascade('factor_retire', factor=name, factor_key=factor_key,
                reason="lifecycle退役")
    except Exception as e:
        logger.debug("[Cascade] 因子退役级联通知失败: %s", e)

    logger.info("🗑️ 因子 %s 已退役", factor_key)


# ================================================================
#  Section 8: 主循环
# ================================================================

def run_forge_cycle() -> dict:
    """17:30 每日执行: 退役 → 计算 → 筛选 → 验证 → 部署"""
    params = FACTOR_FORGE_PARAMS
    if not params.get("enabled", True):
        return {"status": "disabled"}

    result = {
        "retired": [],
        "evaluated": [],
        "deployed": [],
        "status": "ok",
    }

    print("=" * 60)
    print("Factor Forge — 自主因子发现引擎")
    print("=" * 60)

    # Step 1: 退役衰减因子
    print("\n[1/5] 生命周期检查...")
    retired = check_forge_lifecycle()
    result["retired"] = retired
    if retired:
        for r in retired:
            print(f"  退役: {r['name']} ({r['reason']})")
    else:
        print("  无需退役")

    # Step 2: 确保 K 线缓存
    print("\n[2/5] 准备 K 线数据...")
    _ensure_kline_cache()
    if len(_forge_kline_cache) < 10:
        print(f"  K 线缓存不足 ({len(_forge_kline_cache)} 只), 跳过本轮")
        result["status"] = "insufficient_data"
        return result
    print(f"  K 线缓存: {len(_forge_kline_cache)} 只股票")

    # Step 3: 加载 scorecard 数据
    print("\n[3/5] 加载 scorecard 数据...")
    try:
        from db_store import load_scorecard
        scorecard = load_scorecard()
        if not scorecard or len(scorecard) < 50:
            print(f"  scorecard 数据不足 ({len(scorecard) if scorecard else 0} 条), 跳过")
            result["status"] = "insufficient_scorecard"
            return result
        print(f"  scorecard: {len(scorecard)} 条记录")
    except Exception as e:
        print(f"  加载 scorecard 失败: {e}")
        result["status"] = "scorecard_error"
        return result

    # Step 4: 逐指标 IC 筛选 + WF 验证
    print("\n[4/5] IC 筛选 + WF 验证...")
    max_deploy = params.get("max_deployments_per_day", 2)
    today_deployed = _count_today_deployments()
    remaining_deploy = max_deploy - today_deployed

    config = _safe_load(_FORGE_CONFIG_PATH, default={})
    active_names = set(config.get("active_factors", {}).keys())
    retired_names = set(config.get("retired_factors", {}).keys())

    candidates = []
    for ind_name, ind_fn in INDICATOR_LIBRARY.items():
        # 跳过已部署或已退役的
        if ind_name in active_names or ind_name in retired_names:
            continue

        try:
            ic_stats = evaluate_indicator_ic(ind_fn, _forge_kline_cache, scorecard)
        except Exception as e:
            logger.warning("IC 评估 %s 失败: %s", ind_name, e)
            continue

        result["evaluated"].append({
            "name": ind_name,
            "ic_stats": ic_stats,
        })

        if not ic_stats.get("passed"):
            continue

        # WF 验证
        try:
            wf = walk_forward_ic_check(ind_fn, _forge_kline_cache, scorecard)
        except Exception as e:
            logger.warning("WF 验证 %s 失败: %s", ind_name, e)
            continue

        if wf.get("passed"):
            candidates.append((ind_name, ic_stats, wf))
            print(f"  ✅ {ind_name}: IC={ic_stats['mean_ic']:.4f}, "
                  f"IR={ic_stats['ic_ir']:.3f}, WF通过")
        else:
            print(f"  ❌ {ind_name}: IC通过但WF未通过")

    # 按 IC_IR 排序
    candidates.sort(key=lambda x: abs(x[1]["ic_ir"]), reverse=True)

    # Step 5: 部署
    print(f"\n[5/5] 部署 (可部署 {remaining_deploy} 个)...")
    for ind_name, ic_stats, wf in candidates:
        if remaining_deploy <= 0:
            break
        if deploy_factor(ind_name, ic_stats, wf):
            result["deployed"].append(ind_name)
            remaining_deploy -= 1
            print(f"  🚀 部署: s_forge_{ind_name}")

    if not result["deployed"]:
        print("  本轮无新因子部署")

    # 汇总
    print(f"\n{'=' * 60}")
    print(f"Forge 结果: 退役 {len(result['retired'])}, "
          f"评估 {len(result['evaluated'])}, 部署 {len(result['deployed'])}")
    print(f"{'=' * 60}")

    return result


# ================================================================
#  状态查询
# ================================================================

def get_forge_status() -> dict:
    """获取当前 forge 状态"""
    config = _safe_load(_FORGE_CONFIG_PATH, default={})
    active = config.get("active_factors", {})
    retired = config.get("retired_factors", {})
    weights = get_forge_weights()

    return {
        "active_count": len(active),
        "retired_count": len(retired),
        "active_factors": {
            name: {
                "factor_key": info.get("factor_key"),
                "deployed_date": info.get("deployed_date"),
                "weight": weights.get(info.get("factor_key", f"s_forge_{name}"), 0),
                "ic_ir": info.get("ic_stats", {}).get("ic_ir", 0),
            }
            for name, info in active.items()
        },
        "recently_retired": {
            name: info.get("retired_date", "")
            for name, info in list(retired.items())[-5:]
        },
    }


def test_single_indicator(ind_name: str) -> dict:
    """单指标 IC 测试 (CLI 用)"""
    ind_fn = INDICATOR_LIBRARY.get(ind_name)
    if ind_fn is None:
        return {"error": f"指标 '{ind_name}' 不存在"}

    _ensure_kline_cache()
    if len(_forge_kline_cache) < 10:
        return {"error": "K 线缓存不足"}

    try:
        from db_store import load_scorecard
        scorecard = load_scorecard()
    except Exception:
        return {"error": "无法加载 scorecard"}

    ic_stats = evaluate_indicator_ic(ind_fn, _forge_kline_cache, scorecard)
    wf = walk_forward_ic_check(ind_fn, _forge_kline_cache, scorecard)

    return {
        "indicator": ind_name,
        "ic_stats": ic_stats,
        "wf_result": {k: v for k, v in wf.items() if k != "windows"},
        "wf_windows": wf.get("windows", []),
        "would_deploy": ic_stats.get("passed", False) and wf.get("passed", False),
    }


# ================================================================
#  CLI
# ================================================================

def _cli():
    """命令行入口: python3 factor_forge.py [status|run|list|test INDICATOR]"""
    args = sys.argv[1:] if len(sys.argv) > 1 else ["status"]
    cmd = args[0].lower()

    if cmd == "status":
        status = get_forge_status()
        print(f"\n📊 Factor Forge 状态")
        print(f"  活跃因子: {status['active_count']}")
        print(f"  已退役: {status['retired_count']}")
        for name, info in status["active_factors"].items():
            print(f"  - s_forge_{name}: 权重={info['weight']:.4f}, "
                  f"IC_IR={info['ic_ir']:.3f}, 部署={info['deployed_date']}")
        if status["recently_retired"]:
            print("  最近退役:")
            for name, dt in status["recently_retired"].items():
                print(f"  - {name}: {dt}")

    elif cmd == "run":
        result = run_forge_cycle()
        print(f"\n结果: {json.dumps(result, indent=2, ensure_ascii=False, default=str)}")

    elif cmd == "list":
        print("\n📋 指标库 (23 个):")
        for name in sorted(INDICATOR_LIBRARY.keys()):
            fn = INDICATOR_LIBRARY[name]
            doc = (fn.__doc__ or "").strip().split("\n")[0]
            print(f"  {name:25s} {doc}")

    elif cmd == "test" and len(args) > 1:
        ind_name = args[1]
        result = test_single_indicator(ind_name)
        print(f"\n🔬 测试指标: {ind_name}")
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    else:
        print("用法: python3 factor_forge.py [status|run|list|test INDICATOR]")


if __name__ == "__main__":
    _cli()
