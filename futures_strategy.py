"""
期货趋势扫描策略
================
扫描国内主力期货合约, 基于趋势+动量+量仓配合+风险评分选出推荐

流程:
  1. get_futures_pool() — 获取主力合约列表
  2. 预筛: 排除成交量过低合约
  3. _fetch_futures_daily(symbol) — 拉日K
  4. 计算: MA排列 + ADX + RSI + MACD + 量仓配合 + 方向判断
  5. 评分: trend(0.35) + momentum(0.30) + volume(0.20) + risk(0.15)
  6. 支持做多/做空方向
  7. 输出带保证金计算的推荐

调度:
  09:05 日盘扫描 (全品种)
  21:10 夜盘扫描 (有夜盘品种)
"""

import sys
import time
import traceback
import numpy as np
import pandas as pd
from datetime import datetime

try:
    import akshare as ak
except ImportError:
    ak = None

from config import FUTURES_PARAMS, TOP_N

# ================================================================
#  合约信息表 (~30个活跃品种)
# ================================================================

CONTRACT_INFO = {
    # SHFE 上期所
    "RB": {"name": "螺纹钢", "exchange": "SHFE", "multiplier": 10,   "margin_rate": 0.10, "night": True},
    "HC": {"name": "热卷",   "exchange": "SHFE", "multiplier": 10,   "margin_rate": 0.10, "night": True},
    "AU": {"name": "黄金",   "exchange": "SHFE", "multiplier": 1000, "margin_rate": 0.08, "night": True},
    "AG": {"name": "白银",   "exchange": "SHFE", "multiplier": 15,   "margin_rate": 0.10, "night": True},
    "CU": {"name": "铜",     "exchange": "SHFE", "multiplier": 5,    "margin_rate": 0.10, "night": True},
    "AL": {"name": "铝",     "exchange": "SHFE", "multiplier": 5,    "margin_rate": 0.10, "night": True},
    "ZN": {"name": "锌",     "exchange": "SHFE", "multiplier": 5,    "margin_rate": 0.10, "night": True},
    "PB": {"name": "铅",     "exchange": "SHFE", "multiplier": 5,    "margin_rate": 0.10, "night": True},
    "NI": {"name": "镍",     "exchange": "SHFE", "multiplier": 1,    "margin_rate": 0.12, "night": True},
    "SN": {"name": "锡",     "exchange": "SHFE", "multiplier": 1,    "margin_rate": 0.12, "night": True},
    "SS": {"name": "不锈钢", "exchange": "SHFE", "multiplier": 5,    "margin_rate": 0.10, "night": True},
    "FU": {"name": "燃油",   "exchange": "SHFE", "multiplier": 10,   "margin_rate": 0.10, "night": True},
    "BU": {"name": "沥青",   "exchange": "SHFE", "multiplier": 10,   "margin_rate": 0.10, "night": True},
    "RU": {"name": "橡胶",   "exchange": "SHFE", "multiplier": 10,   "margin_rate": 0.10, "night": True},
    "SP": {"name": "纸浆",   "exchange": "SHFE", "multiplier": 10,   "margin_rate": 0.10, "night": True},
    # DCE 大商所
    "I":  {"name": "铁矿石", "exchange": "DCE",  "multiplier": 100,  "margin_rate": 0.12, "night": True},
    "J":  {"name": "焦炭",   "exchange": "DCE",  "multiplier": 100,  "margin_rate": 0.12, "night": True},
    "JM": {"name": "焦煤",   "exchange": "DCE",  "multiplier": 60,   "margin_rate": 0.12, "night": True},
    "M":  {"name": "豆粕",   "exchange": "DCE",  "multiplier": 10,   "margin_rate": 0.08, "night": True},
    "Y":  {"name": "豆油",   "exchange": "DCE",  "multiplier": 10,   "margin_rate": 0.08, "night": True},
    "P":  {"name": "棕榈油", "exchange": "DCE",  "multiplier": 10,   "margin_rate": 0.08, "night": True},
    "PP": {"name": "聚丙烯", "exchange": "DCE",  "multiplier": 5,    "margin_rate": 0.08, "night": True},
    "L":  {"name": "塑料",   "exchange": "DCE",  "multiplier": 5,    "margin_rate": 0.08, "night": True},
    "EG": {"name": "乙二醇", "exchange": "DCE",  "multiplier": 10,   "margin_rate": 0.08, "night": True},
    "EB": {"name": "苯乙烯", "exchange": "DCE",  "multiplier": 5,    "margin_rate": 0.10, "night": True},
    # CZCE 郑商所
    "MA": {"name": "甲醇",   "exchange": "CZCE", "multiplier": 10,   "margin_rate": 0.08, "night": True},
    "TA": {"name": "PTA",    "exchange": "CZCE", "multiplier": 5,    "margin_rate": 0.08, "night": True},
    "SA": {"name": "纯碱",   "exchange": "CZCE", "multiplier": 20,   "margin_rate": 0.08, "night": True},
    "FG": {"name": "玻璃",   "exchange": "CZCE", "multiplier": 20,   "margin_rate": 0.10, "night": False},
    "SR": {"name": "白糖",   "exchange": "CZCE", "multiplier": 10,   "margin_rate": 0.08, "night": True},
    "CF": {"name": "棉花",   "exchange": "CZCE", "multiplier": 5,    "margin_rate": 0.08, "night": True},
    # CFFEX 中金所
    "IF": {"name": "沪深300", "exchange": "CFFEX", "multiplier": 300,  "margin_rate": 0.12, "night": False},
    "IC": {"name": "中证500", "exchange": "CFFEX", "multiplier": 200,  "margin_rate": 0.14, "night": False},
    "IM": {"name": "中证1000","exchange": "CFFEX", "multiplier": 200,  "margin_rate": 0.14, "night": False},
    # INE 能源中心
    "SC": {"name": "原油",   "exchange": "INE",  "multiplier": 1000, "margin_rate": 0.10, "night": True},
}


# ================================================================
#  技术指标计算
# ================================================================

def _calc_rsi(closes, period=14):
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = pd.Series(gains).rolling(period).mean().values
    avg_loss = pd.Series(losses).rolling(period).mean().values
    with np.errstate(divide='ignore', invalid='ignore'):
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
    return rsi


def _calc_adx(highs, lows, closes, period=14):
    """计算 ADX (平均趋向指标)"""
    n = len(closes)
    if n < period + 1:
        return np.full(n, np.nan)

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
    dx = np.abs(plus_di - minus_di) / np.maximum(plus_di + minus_di, 1e-10) * 100
    adx = pd.Series(dx).rolling(period).mean().values
    return adx


def _calc_macd(closes, fast=12, slow=26, signal=9):
    """计算 MACD"""
    s = pd.Series(closes)
    ema_fast = s.ewm(span=fast, adjust=False).mean()
    ema_slow = s.ewm(span=slow, adjust=False).mean()
    diff = ema_fast - ema_slow
    dea = diff.ewm(span=signal, adjust=False).mean()
    macd_bar = (diff - dea) * 2
    return diff.values, dea.values, macd_bar.values


def _calc_atr(highs, lows, closes, period=14):
    """计算 ATR (平均真实波幅)"""
    n = len(closes)
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i - 1]),
                     abs(lows[i] - closes[i - 1]))
    atr = pd.Series(tr).rolling(period).mean().values
    return atr


# ================================================================
#  数据获取
# ================================================================

def _guarded_call(func, *args, **kwargs):
    """优先走 API 防护层"""
    try:
        from api_guard import guarded_call
        return guarded_call(func, *args, source="akshare", retries=3)
    except ImportError:
        return func(*args)


def get_futures_pool(night_only=False):
    """获取主力合约列表

    Args:
        night_only: True 时只返回有夜盘的品种

    Returns:
        list[dict]: [{"symbol": "RB0", "name": "螺纹钢", ...}, ...]
    """
    print("[1/4] 获取主力合约列表...")

    pool = []
    for code, info in CONTRACT_INFO.items():
        if night_only and not info.get("night", False):
            continue
        pool.append({
            "code": code,
            "name": info["name"],
            "exchange": info["exchange"],
            "multiplier": info["multiplier"],
            "margin_rate": info["margin_rate"],
        })

    print(f"  合约池: {len(pool)} 个品种" + (" (仅夜盘)" if night_only else " (全品种)"))
    return pool


def _fetch_futures_daily(symbol):
    """获取单个品种的主力合约日K数据

    Args:
        symbol: 品种代码, 如 "RB"

    Returns:
        DataFrame or None
    """
    try:
        df = _guarded_call(ak.futures_main_sina, f"{symbol}0")
        if df is None or df.empty:
            return None
        # 标准化列名
        col_map = {
            "日期": "date", "开盘价": "open", "最高价": "high",
            "最低价": "low", "收盘价": "close", "成交量": "volume",
            "持仓量": "open_interest",
        }
        df = df.rename(columns=col_map)
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "open_interest" in df.columns:
            df["open_interest"] = pd.to_numeric(df["open_interest"], errors="coerce")
        return df
    except Exception:
        return None


# ================================================================
#  单品种分析
# ================================================================

def _analyze_contract(code, info, df):
    """分析单个合约, 返回评分结果或None"""
    if df is None or len(df) < 60:
        return None

    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    volumes = df["volume"].values.astype(float)
    oi = df["open_interest"].values.astype(float) if "open_interest" in df.columns else volumes

    price = closes[-1]
    if price <= 0:
        return None

    # --- MA 排列 ---
    ma5 = pd.Series(closes).rolling(5).mean().values
    ma10 = pd.Series(closes).rolling(10).mean().values
    ma20 = pd.Series(closes).rolling(20).mean().values
    ma60 = pd.Series(closes).rolling(60).mean().values

    # 多头排列 MA5>MA10>MA20>MA60
    ma_bull = (ma5[-1] > ma10[-1] > ma20[-1] > ma60[-1]) if not any(np.isnan([ma5[-1], ma10[-1], ma20[-1], ma60[-1]])) else False
    # 空头排列 MA5<MA10<MA20<MA60
    ma_bear = (ma5[-1] < ma10[-1] < ma20[-1] < ma60[-1]) if not any(np.isnan([ma5[-1], ma10[-1], ma20[-1], ma60[-1]])) else False

    # MA排列得分
    if ma_bull:
        ma_score = 1.0
    elif ma_bear:
        ma_score = -1.0
    elif not np.isnan(ma20[-1]) and price > ma20[-1]:
        ma_score = 0.5
    elif not np.isnan(ma20[-1]) and price < ma20[-1]:
        ma_score = -0.5
    else:
        ma_score = 0

    # --- ADX ---
    adx = _calc_adx(highs, lows, closes, 14)
    adx_now = adx[-1] if not np.isnan(adx[-1]) else 0

    # --- RSI ---
    rsi = _calc_rsi(closes, 14)
    rsi_now = rsi[-1] if not np.isnan(rsi[-1]) else 50

    # --- MACD ---
    diff, dea, macd_bar = _calc_macd(closes)
    macd_now = macd_bar[-1] if not np.isnan(macd_bar[-1]) else 0
    macd_prev = macd_bar[-2] if len(macd_bar) >= 2 and not np.isnan(macd_bar[-2]) else 0

    # --- ATR ---
    atr = _calc_atr(highs, lows, closes, 14)
    atr_now = atr[-1] if not np.isnan(atr[-1]) else 0

    # --- 量仓配合 ---
    vol_5 = np.mean(volumes[-5:])
    vol_20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else vol_5
    vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 1.0

    oi_chg = oi[-1] - oi[-5] if len(oi) >= 5 else 0

    # --- 方向判断 ---
    # 综合MA排列 + MACD + RSI 确定方向
    bull_signals = sum([
        ma_score > 0,
        macd_now > 0,
        rsi_now > 50,
        price > ma20[-1] if not np.isnan(ma20[-1]) else False,
    ])
    bear_signals = sum([
        ma_score < 0,
        macd_now < 0,
        rsi_now < 50,
        price < ma20[-1] if not np.isnan(ma20[-1]) else False,
    ])

    if bull_signals >= 3:
        direction = "long"
    elif bear_signals >= 3:
        direction = "short"
    else:
        direction = "neutral"

    # --- 评分 ---
    # s_trend: MA排列 + ADX强度
    min_adx = FUTURES_PARAMS.get("min_adx", 20)
    adx_score = min(adx_now / 50.0, 1.0) if adx_now >= min_adx else adx_now / min_adx * 0.5
    s_trend = abs(ma_score) * 0.6 + adx_score * 0.4

    # s_momentum: RSI + MACD
    if direction == "long":
        rsi_score = min((rsi_now - 30) / 40, 1.0) if rsi_now > 30 else 0
        macd_score = 1.0 if macd_now > 0 and macd_now > macd_prev else 0.5 if macd_now > 0 else 0
    elif direction == "short":
        rsi_score = min((70 - rsi_now) / 40, 1.0) if rsi_now < 70 else 0
        macd_score = 1.0 if macd_now < 0 and macd_now < macd_prev else 0.5 if macd_now < 0 else 0
    else:
        rsi_score = 0.3
        macd_score = 0.3
    s_momentum = rsi_score * 0.5 + macd_score * 0.5

    # s_volume: 量仓配合
    min_vr = FUTURES_PARAMS.get("min_volume_ratio", 1.2)
    vr_score = min(vol_ratio / 3.0, 1.0) if vol_ratio >= min_vr else vol_ratio / min_vr * 0.5
    oi_score = 0.7 if oi_chg > 0 else 0.3  # 增仓加分
    s_volume = vr_score * 0.6 + oi_score * 0.4

    # s_risk: 波动率适中 + ATR可控
    daily_ret = np.diff(closes[-21:]) / closes[-21:-1] if len(closes) >= 21 else np.array([0])
    volatility = np.std(daily_ret) * np.sqrt(252) if len(daily_ret) >= 10 else 0.5
    # 波动率适中最优 (0.15~0.35)
    if 0.15 <= volatility <= 0.35:
        vol_risk = 1.0
    elif volatility < 0.15:
        vol_risk = volatility / 0.15
    else:
        vol_risk = max(0, 1.0 - (volatility - 0.35) / 0.3)
    s_risk = vol_risk

    # 加权总分
    weights = FUTURES_PARAMS.get("weights", {})
    total_score = (
        s_trend * weights.get("s_trend", 0.35) +
        s_momentum * weights.get("s_momentum", 0.30) +
        s_volume * weights.get("s_volume", 0.20) +
        s_risk * weights.get("s_risk", 0.15)
    )

    # 中性方向降权
    if direction == "neutral":
        total_score *= 0.5

    # 突破高/低点加分
    high_20d = np.max(highs[-20:])
    low_20d = np.min(lows[-20:])
    if direction == "long" and price >= high_20d * 0.99:
        total_score *= 1.1
    elif direction == "short" and price <= low_20d * 1.01:
        total_score *= 1.1

    # 保证金计算
    multiplier = info.get("multiplier", 10)
    margin_rate = info.get("margin_rate", 0.10)
    margin_per_lot = price * multiplier * margin_rate

    # ATR止损
    atr_mult = FUTURES_PARAMS.get("atr_stop_multiplier", 2.0)
    stop_distance = atr_now * atr_mult

    # 建仓手数建议 (基于风险百分比)
    risk_pct = FUTURES_PARAMS.get("risk_per_trade_pct", 2.0) / 100
    max_lots = FUTURES_PARAMS.get("max_lots_per_contract", 5)
    account_equity = 100000  # 默认10万
    risk_amount = account_equity * risk_pct
    lots = int(risk_amount / (stop_distance * multiplier)) if stop_distance * multiplier > 0 else 1
    lots = max(1, min(lots, max_lots))

    # 理由
    dir_label = "做多" if direction == "long" else "做空" if direction == "short" else "观望"
    reasons = [dir_label]
    if adx_now >= min_adx:
        reasons.append(f"ADX={adx_now:.0f}")
    if direction == "long" and price >= high_20d * 0.99:
        reasons.append("突破20日高")
    elif direction == "short" and price <= low_20d * 1.01:
        reasons.append("突破20日低")
    if vol_ratio >= min_vr:
        vol_label = "量增" if vol_ratio >= 1.5 else "量平"
        oi_label = "仓增" if oi_chg > 0 else "仓减"
        reasons.append(f"{vol_label}{oi_label}")
    reasons.append(f"保证金{margin_per_lot:.0f}")

    return {
        "code": code,
        "name": info["name"],
        "exchange": info["exchange"],
        "price": price,
        "score": round(total_score, 4),
        "reason": " | ".join(reasons),
        "direction": direction,
        "margin_per_lot": round(margin_per_lot, 0),
        "atr": round(atr_now, 2),
        "adx": round(adx_now, 1),
        "rsi": round(rsi_now, 1),
        "macd": round(macd_now, 2),
        "vol_ratio": round(vol_ratio, 2),
        "lots": lots,
        # 因子分数 (供学习引擎)
        "factor_scores": {
            "s_trend": round(s_trend, 4),
            "s_momentum": round(s_momentum, 4),
            "s_volume": round(s_volume, 4),
            "s_risk": round(s_risk, 4),
        },
    }


# ================================================================
#  主流程
# ================================================================

def run_futures_scan(night_only=False, top_n=None):
    """
    期货趋势扫描主流程

    Args:
        night_only: True 时只扫描有夜盘品种
        top_n: 推荐数量

    Returns:
        list[dict]: 推荐列表
    """
    if top_n is None:
        top_n = FUTURES_PARAMS.get("top_n", 5)

    session = "夜盘" if night_only else "日盘"
    print("=" * 65)
    print(f"  期货趋势扫描策略 ({session})")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    # 1. 获取合约池
    pool = get_futures_pool(night_only=night_only)

    # 2. 逐品种拉日K + 分析
    print(f"\n[2/4] 逐品种拉取日K并分析 ({len(pool)} 个)...")
    results = []
    fail_count = 0

    for i, item in enumerate(pool):
        code = item["code"]
        try:
            time.sleep(0.3)
            df = _fetch_futures_daily(code)
            if df is None or df.empty:
                fail_count += 1
                continue
            result = _analyze_contract(code, item, df)
            if result and result["direction"] != "neutral":
                results.append(result)
        except Exception:
            fail_count += 1
            continue
        if (i + 1) % 10 == 0:
            print(f"  进度: {i + 1}/{len(pool)}  有效: {len(results)}  失败: {fail_count}")

    print(f"  分析完成: {len(results)} 个有方向信号, {fail_count} 个失败")

    if not results:
        print("\n  无有效信号")
        return []

    # 3. 排序选择
    print(f"\n[3/4] 排序选择 TOP {top_n}...")
    results.sort(key=lambda x: x["score"], reverse=True)
    selected = results[:top_n]

    # 4. 输出
    print(f"\n[4/4] 输出推荐")
    print("\n" + "=" * 65)
    print(f"  期货趋势推荐 TOP {len(selected)}  ({session}, 共扫描{len(pool)}个品种)")
    print("=" * 65)

    for rank, item in enumerate(selected, 1):
        dir_icon = "▲" if item["direction"] == "long" else "▼"
        print(f"""
  {rank}. {item['code']} {item['name']} [{item['exchange']}] {dir_icon} | 评分: {item['score']:.3f} | 现价: {item['price']:.1f}
     信号: {item['reason']}
     技术: ADX={item['adx']:.0f}  RSI={item['rsi']:.0f}  MACD={item['macd']:.2f}  量比={item['vol_ratio']:.2f}
     交易: 保证金={item['margin_per_lot']:.0f}/手  ATR={item['atr']:.1f}  建议{item['lots']}手""")

    return selected


def get_futures_recommendations(top_n=None):
    """标准化接口 (供 scheduler 调用)

    Returns:
        list[dict]: 标准化推荐列表
    """
    if not FUTURES_PARAMS.get("enabled", True):
        print("[期货趋势策略] 已禁用")
        return []

    if top_n is None:
        top_n = FUTURES_PARAMS.get("top_n", TOP_N)

    # 根据时间判断日盘/夜盘
    hour = datetime.now().hour
    night_only = hour >= 20 or hour < 3

    try:
        selected = run_futures_scan(night_only=night_only, top_n=top_n)
    except Exception as e:
        print(f"[期货趋势策略异常] {e}")
        traceback.print_exc()
        return []

    if not selected:
        return []

    # 转换为标准格式 (保留交易执行所需字段)
    results = []
    for item in selected:
        results.append({
            "code": item["code"],
            "name": item["name"],
            "price": item["price"],
            "score": item["score"],
            "reason": item["reason"],
            "factor_scores": item.get("factor_scores", {}),
            # 交易执行字段
            "direction": item.get("direction", "long"),
            "atr": item.get("atr", 0),
            "margin_per_lot": item.get("margin_per_lot", 0),
            "lots": item.get("lots", 1),
            "exchange": item.get("exchange", ""),
        })
    return results


# ================================================================
#  入口
# ================================================================

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "day"
    if mode == "night":
        run_futures_scan(night_only=True)
    elif mode == "day":
        run_futures_scan(night_only=False)
    else:
        print(f"用法: python3 futures_strategy.py [day|night]")
        sys.exit(1)
