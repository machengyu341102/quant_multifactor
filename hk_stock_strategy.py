"""
港股指数分析策略
================
扫描恒生指数+恒生科技, 用于A股情绪参考

流程:
  1. 获取恒生指数 (HSI) + 恒生科技 (HSTECH)
  2. 计算: MA排列 + RSI + MACD + 量能
  3. 评分: 趋势强度 (用于 cross_asset_factor)
  4. 不推送微信, 只输出到终端

数据源:
  akshare 港股数据 (免费)

调度:
  09:05 开盘前 (与期货同时)
"""

import sys
import os
import traceback
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from config import HK_STOCK_PARAMS
except ImportError:
    HK_STOCK_PARAMS = {
        "enabled": True,
        "weights": {"s_trend": 0.4, "s_momentum": 0.3, "s_volume": 0.3},
    }

# ================================================================
#  港股指数池 (仅2个核心指数)
# ================================================================

HK_INDEX_POOL = {
    "HSI":    {"name": "恒生指数",   "code": "HSI"},
    "HSTECH": {"name": "恒生科技",   "code": "HSTECH"},
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


def _calc_macd(closes, fast=12, slow=26, signal=9):
    s = pd.Series(closes)
    ema_fast = s.ewm(span=fast, adjust=False).mean()
    ema_slow = s.ewm(span=slow, adjust=False).mean()
    diff = ema_fast - ema_slow
    dea = diff.ewm(span=signal, adjust=False).mean()
    macd_bar = (diff - dea) * 2
    return diff.values, dea.values, macd_bar.values


# ================================================================
#  数据获取
# ================================================================

def _fetch_hk_index_daily(symbol: str, days: int = 60) -> Optional[pd.DataFrame]:
    """获取港股指数日K线 (akshare)"""
    try:
        import akshare as ak

        # akshare 港股指数接口
        if symbol == "HSI":
            df = ak.stock_hk_index_daily_em(symbol="HSI")
        elif symbol == "HSTECH":
            df = ak.stock_hk_index_daily_em(symbol="HSTECH")
        else:
            return None

        if df is None or df.empty:
            return None

        # 标准化列名
        df = df.rename(columns={
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
        })

        # 取最近 N 天
        df = df.tail(days).copy()
        df = df.sort_values("date").reset_index(drop=True)

        return df

    except Exception as e:
        print(f"  [港股数据异常] {symbol}: {e}")
        return None


# ================================================================
#  评分逻辑
# ================================================================

def _score_hk_index(symbol: str, info: dict) -> Optional[dict]:
    """对单个港股指数评分"""
    df = _fetch_hk_index_daily(symbol, days=60)
    if df is None or len(df) < 30:
        return None

    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    volumes = df["volume"].values

    # MA 排列
    ma5 = pd.Series(closes).rolling(5).mean().values
    ma10 = pd.Series(closes).rolling(10).mean().values
    ma20 = pd.Series(closes).rolling(20).mean().values

    last_close = closes[-1]
    last_ma5 = ma5[-1]
    last_ma10 = ma10[-1]
    last_ma20 = ma20[-1]

    # 趋势得分
    if last_close > last_ma5 > last_ma10 > last_ma20:
        s_trend = 1.0  # 多头排列
    elif last_close < last_ma5 < last_ma10 < last_ma20:
        s_trend = 0.0  # 空头排列
    else:
        s_trend = 0.5  # 中性

    # RSI
    rsi = _calc_rsi(closes)
    last_rsi = rsi[-1] if not np.isnan(rsi[-1]) else 50
    s_momentum = last_rsi / 100.0

    # MACD
    diff, dea, macd_bar = _calc_macd(closes)
    last_macd = macd_bar[-1] if not np.isnan(macd_bar[-1]) else 0
    macd_positive = 1 if last_macd > 0 else 0

    # 量能
    vol_ma5 = pd.Series(volumes).rolling(5).mean().values[-1]
    vol_ma20 = pd.Series(volumes).rolling(20).mean().values[-1]
    vol_ratio = vol_ma5 / vol_ma20 if vol_ma20 > 0 else 1.0
    s_volume = min(vol_ratio / 1.5, 1.0)  # 归一化到 [0, 1]

    # 综合得分
    weights = HK_STOCK_PARAMS.get("weights", {})
    score = (
        s_trend * weights.get("s_trend", 0.4) +
        s_momentum * weights.get("s_momentum", 0.3) +
        s_volume * weights.get("s_volume", 0.3)
    )

    # 方向判断
    if score > 0.6:
        direction = "看多"
    elif score < 0.4:
        direction = "看空"
    else:
        direction = "中性"

    return {
        "symbol": symbol,
        "name": info["name"],
        "score": round(score, 3),
        "direction": direction,
        "close": round(last_close, 2),
        "rsi": round(last_rsi, 1),
        "macd": "正" if macd_positive else "负",
        "vol_ratio": round(vol_ratio, 2),
        "s_trend": round(s_trend, 3),
        "s_momentum": round(s_momentum, 3),
        "s_volume": round(s_volume, 3),
    }


# ================================================================
#  主函数
# ================================================================

def run_hk_stock_strategy(top_n: int = 2) -> list[dict]:
    """港股指数分析 (不推送微信, 只输出终端)"""
    if not HK_STOCK_PARAMS.get("enabled", True):
        print("[港股指数] 策略已禁用")
        return []

    print(f"\n{'=' * 60}")
    print(f"  港股指数分析 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 60}")

    results = []
    for symbol, info in HK_INDEX_POOL.items():
        try:
            result = _score_hk_index(symbol, info)
            if result:
                results.append(result)
                print(f"  {result['name']}: {result['score']:.3f} ({result['direction']}) "
                      f"RSI={result['rsi']} MACD={result['macd']} 量比={result['vol_ratio']}")
        except Exception as e:
            print(f"  [异常] {info['name']}: {e}")
            traceback.print_exc()

    # 按得分排序
    results.sort(key=lambda x: x["score"], reverse=True)

    print(f"\n港股指数分析完成, 共 {len(results)} 个指数")
    return results[:top_n]


# ================================================================
#  CLI 入口
# ================================================================

if __name__ == "__main__":
    results = run_hk_stock_strategy()

    if results:
        print("\n港股指数评分:")
        for r in results:
            print(f"  {r['name']}: {r['score']:.3f} ({r['direction']})")
    else:
        print("\n无港股指数数据")
