"""
币圈趋势扫描策略
================
扫描主流加密货币, 基于趋势+动量+量能+风险评分选出推荐

流程:
  1. get_crypto_pool() — 获取币种池 (20+主流币)
  2. _fetch_crypto_klines(symbol) — Binance REST /api/v3/klines 拉日K
  3. 计算: MA排列 + ADX + RSI + MACD + 量能变化 + 方向判断
  4. 评分: trend(0.35) + momentum(0.30) + volume(0.20) + risk(0.15)
  5. 支持做多/做空/中性方向
  6. 直推微信

数据源:
  Binance 公开 REST API, 无需 API Key
  https://api.binance.com/api/v3/klines

调度:
  夜班期间 (22:30~08:30) 扫描一次
"""

import sys
import time
import traceback
import requests
import numpy as np
import pandas as pd
from datetime import datetime

try:
    from config import CRYPTO_PARAMS, TOP_N
except ImportError:
    CRYPTO_PARAMS = {
        "enabled": True,
        "top_n": 5,
        "weights": {"s_trend": 0.35, "s_momentum": 0.30, "s_volume": 0.20, "s_risk": 0.15},
        "min_adx": 20,
        "min_volume_ratio": 1.2,
    }
    TOP_N = 3

# ================================================================
#  币种池 (20+主流币, USDT交易对)
# ================================================================

CRYPTO_POOL = {
    "BTCUSDT":  {"name": "比特币",     "symbol": "BTC"},
    "ETHUSDT":  {"name": "以太坊",     "symbol": "ETH"},
    "SOLUSDT":  {"name": "Solana",     "symbol": "SOL"},
    "BNBUSDT":  {"name": "BNB",        "symbol": "BNB"},
    "XRPUSDT":  {"name": "瑞波币",     "symbol": "XRP"},
    "ADAUSDT":  {"name": "Cardano",    "symbol": "ADA"},
    "DOGEUSDT": {"name": "狗狗币",     "symbol": "DOGE"},
    "AVAXUSDT": {"name": "Avalanche",  "symbol": "AVAX"},
    "DOTUSDT":  {"name": "波卡",       "symbol": "DOT"},
    "LINKUSDT": {"name": "Chainlink",  "symbol": "LINK"},
    "MATICUSDT":{"name": "Polygon",    "symbol": "MATIC"},
    "UNIUSDT":  {"name": "Uniswap",    "symbol": "UNI"},
    "ATOMUSDT": {"name": "Cosmos",     "symbol": "ATOM"},
    "LTCUSDT":  {"name": "莱特币",     "symbol": "LTC"},
    "ETCUSDT":  {"name": "以太经典",   "symbol": "ETC"},
    "NEARUSDT": {"name": "NEAR",       "symbol": "NEAR"},
    "APTUSDT":  {"name": "Aptos",      "symbol": "APT"},
    "FILUSDT":  {"name": "Filecoin",   "symbol": "FIL"},
    "ARUSDT":   {"name": "Arweave",    "symbol": "AR"},
    "OPUSDT":   {"name": "Optimism",   "symbol": "OP"},
    "ARBUSDT":  {"name": "Arbitrum",   "symbol": "ARB"},
    "SUIUSDT":  {"name": "Sui",        "symbol": "SUI"},
    "SEIUSDT":  {"name": "Sei",        "symbol": "SEI"},
    "TIAUSDT":  {"name": "Celestia",   "symbol": "TIA"},
}

BINANCE_KLINE_URL = "https://api.binance.com/api/v3/klines"


# ================================================================
#  技术指标计算 (与 futures_strategy 一致)
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
    s = pd.Series(closes)
    ema_fast = s.ewm(span=fast, adjust=False).mean()
    ema_slow = s.ewm(span=slow, adjust=False).mean()
    diff = ema_fast - ema_slow
    dea = diff.ewm(span=signal, adjust=False).mean()
    macd_bar = (diff - dea) * 2
    return diff.values, dea.values, macd_bar.values


def _calc_atr(highs, lows, closes, period=14):
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

def _guarded_request(url, params, source="binance"):
    """优先走 API 防护层"""
    try:
        from api_guard import guarded_call
        def _do_get():
            r = requests.get(url, params=params, timeout=15)
            if r.status_code in (403, 429, 418, 451):
                raise RuntimeError(f"Binance HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()
        return guarded_call(_do_get, source=source, retries=3)
    except ImportError:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()


def get_crypto_pool():
    """获取币种池

    Returns:
        list[dict]: [{"pair": "BTCUSDT", "name": "比特币", "symbol": "BTC"}, ...]
    """
    print("[1/4] 获取币种池...")
    pool = []
    for pair, info in CRYPTO_POOL.items():
        pool.append({
            "pair": pair,
            "name": info["name"],
            "symbol": info["symbol"],
        })
    print(f"  币种池: {len(pool)} 个币种")
    return pool


def _fetch_crypto_klines(pair, interval="1d", limit=100):
    """获取单个币种的日K线数据 (Binance REST API)

    Args:
        pair: 交易对, 如 "BTCUSDT"
        interval: K线周期, 默认日K
        limit: K线条数

    Returns:
        DataFrame or None
    """
    try:
        params = {"symbol": pair, "interval": interval, "limit": limit}
        data = _guarded_request(BINANCE_KLINE_URL, params, source="binance")
        if not data:
            return None

        # Binance kline 格式: [open_time, open, high, low, close, volume, close_time, ...]
        df = pd.DataFrame(data, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_vol",
            "taker_buy_quote_vol", "ignore",
        ])
        for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["date"] = pd.to_datetime(df["open_time"], unit="ms")
        return df
    except Exception:
        return None


# ================================================================
#  单币种分析
# ================================================================

def _analyze_crypto(pair, info, df):
    """分析单个币种, 返回评分结果或None"""
    if df is None or len(df) < 60:
        return None

    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    volumes = df["volume"].values.astype(float)

    price = closes[-1]
    if price <= 0:
        return None

    # --- MA 排列 ---
    ma5 = pd.Series(closes).rolling(5).mean().values
    ma10 = pd.Series(closes).rolling(10).mean().values
    ma20 = pd.Series(closes).rolling(20).mean().values
    ma60 = pd.Series(closes).rolling(60).mean().values

    ma_bull = (ma5[-1] > ma10[-1] > ma20[-1] > ma60[-1]) if not any(np.isnan([ma5[-1], ma10[-1], ma20[-1], ma60[-1]])) else False
    ma_bear = (ma5[-1] < ma10[-1] < ma20[-1] < ma60[-1]) if not any(np.isnan([ma5[-1], ma10[-1], ma20[-1], ma60[-1]])) else False

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

    # --- 量能变化 ---
    vol_5 = np.mean(volumes[-5:])
    vol_20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else vol_5
    vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 1.0

    # --- 方向判断 ---
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
    min_adx = CRYPTO_PARAMS.get("min_adx", 20)
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

    # s_volume: 量能变化
    min_vr = CRYPTO_PARAMS.get("min_volume_ratio", 1.2)
    vr_score = min(vol_ratio / 3.0, 1.0) if vol_ratio >= min_vr else vol_ratio / min_vr * 0.5
    s_volume = vr_score

    # s_risk: 波动率适中
    daily_ret = np.diff(closes[-21:]) / closes[-21:-1] if len(closes) >= 21 else np.array([0])
    volatility = np.std(daily_ret) * np.sqrt(365) if len(daily_ret) >= 10 else 0.5  # 币圈用365天年化
    # 币圈波动率较高, 适中范围调整为 0.30~0.80
    if 0.30 <= volatility <= 0.80:
        vol_risk = 1.0
    elif volatility < 0.30:
        vol_risk = volatility / 0.30
    else:
        vol_risk = max(0, 1.0 - (volatility - 0.80) / 0.5)
    s_risk = vol_risk

    # 加权总分
    weights = CRYPTO_PARAMS.get("weights", {})
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

    # ATR止损距离
    atr_mult = CRYPTO_PARAMS.get("atr_stop_multiplier", 2.0)
    stop_distance = atr_now * atr_mult

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
        reasons.append(vol_label)

    return {
        "pair": pair,
        "symbol": info["symbol"],
        "name": info["name"],
        "price": price,
        "score": round(total_score, 4),
        "reason": " | ".join(reasons),
        "direction": direction,
        "atr": round(atr_now, 2),
        "adx": round(adx_now, 1),
        "rsi": round(rsi_now, 1),
        "macd": round(macd_now, 4),
        "vol_ratio": round(vol_ratio, 2),
        "stop_distance": round(stop_distance, 2),
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

def run_crypto_scan(top_n=None):
    """
    币圈趋势扫描主流程

    Args:
        top_n: 推荐数量

    Returns:
        list[dict]: 推荐列表
    """
    if top_n is None:
        top_n = CRYPTO_PARAMS.get("top_n", 5)

    print("=" * 65)
    print(f"  币圈趋势扫描策略")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    # 1. 获取币种池
    pool = get_crypto_pool()

    # 2. 逐币种拉日K + 分析
    print(f"\n[2/4] 逐币种拉取日K并分析 ({len(pool)} 个)...")
    results = []
    fail_count = 0

    for i, item in enumerate(pool):
        pair = item["pair"]
        try:
            time.sleep(0.2)  # Binance 公开API限频
            df = _fetch_crypto_klines(pair)
            if df is None or df.empty:
                fail_count += 1
                continue
            result = _analyze_crypto(pair, item, df)
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
    print(f"  币圈趋势推荐 TOP {len(selected)}  (共扫描{len(pool)}个币种)")
    print("=" * 65)

    for rank, item in enumerate(selected, 1):
        dir_icon = "▲" if item["direction"] == "long" else "▼"
        print(f"""
  {rank}. {item['symbol']} {item['name']} {dir_icon} | 评分: {item['score']:.3f} | 现价: ${item['price']:.2f}
     信号: {item['reason']}
     技术: ADX={item['adx']:.0f}  RSI={item['rsi']:.0f}  MACD={item['macd']:.4f}  量比={item['vol_ratio']:.2f}
     止损参考: ATR={item['atr']:.2f}  止损距离=${item['stop_distance']:.2f}""")

    return selected


def get_crypto_recommendations(top_n=None):
    """标准化接口 (供 scheduler 调用)

    Returns:
        list[dict]: 标准化推荐列表
    """
    if not CRYPTO_PARAMS.get("enabled", True):
        print("[币圈趋势策略] 已禁用")
        return []

    if top_n is None:
        top_n = CRYPTO_PARAMS.get("top_n", TOP_N)

    try:
        selected = run_crypto_scan(top_n=top_n)
    except Exception as e:
        print(f"[币圈趋势策略异常] {e}")
        traceback.print_exc()
        return []

    if not selected:
        return []

    # 转换为标准格式
    results = []
    for item in selected:
        results.append({
            "code": item["symbol"],
            "name": item["name"],
            "price": item["price"],
            "score": item["score"],
            "reason": item["reason"],
            "factor_scores": item.get("factor_scores", {}),
            "direction": item.get("direction", "long"),
            "atr": item.get("atr", 0),
            "pair": item.get("pair", ""),
        })
    return results


# ================================================================
#  入口
# ================================================================

if __name__ == "__main__":
    results = run_crypto_scan()
    if results:
        # 直推微信
        try:
            from notifier import notify_wechat_raw
            lines = [f"币圈趋势扫描 TOP {len(results)}"]
            for r in results:
                d = "▲" if r["direction"] == "long" else "▼"
                lines.append(f"{d} {r['symbol']} {r['name']} ${r['price']:.2f} 评分{r['score']:.3f}")
                lines.append(f"  {r['reason']}")
            notify_wechat_raw("币圈趋势扫描", "\n".join(lines))
            print("\n[微信推送完成]")
        except Exception as e:
            print(f"\n[微信推送失败] {e}")
