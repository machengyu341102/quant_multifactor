"""
跨市场信号推演策略
==================
综合币圈+美股+A股期货的夜间信号, 推演次日A股开盘影响

流程:
  1. 收集三个市场的最新数据 (BTC/ETH, 美股指数, 富时A50)
  2. 计算跨市场信号: 风险偏好/避险/联动/背离
  3. 推演对A股的影响: 利多/利空/中性
  4. 生成次日操作建议
  5. 直推微信

调度:
  夜班期间 06:00 运行 (美股收盘+夜盘收盘后, 综合推演)
"""

import sys
import traceback
import numpy as np
import pandas as pd
import requests
from datetime import datetime

try:
    from config import CROSS_MARKET_PARAMS
except ImportError:
    CROSS_MARKET_PARAMS = {"enabled": True}

# ================================================================
#  数据源定义
# ================================================================

# Binance 公开 API
BINANCE_KLINE_URL = "https://api.binance.com/api/v3/klines"

# 跨市场标的
CROSS_MARKET_SYMBOLS = {
    "crypto": {
        "BTCUSDT": {"name": "比特币", "weight": 0.6},
        "ETHUSDT": {"name": "以太坊", "weight": 0.4},
    },
    "us_index": {
        "SPY":  {"name": "标普500",   "weight": 0.4},
        "QQQ":  {"name": "纳斯达克",  "weight": 0.35},
        "IWM":  {"name": "罗素2000",  "weight": 0.15},
        "SOXX": {"name": "半导体ETF", "weight": 0.1},
    },
    # A50期货 用 Binance 没有, 用 yfinance
    "a50": {
        "XIN9.FGI": {"name": "富时A50期货", "weight": 1.0},
    },
}


# ================================================================
#  数据获取
# ================================================================

def _fetch_binance_recent(pair, interval="1h", limit=24):
    """获取 Binance 最近 N 根K线"""
    try:
        from api_guard import guarded_call
        def _do():
            r = requests.get(BINANCE_KLINE_URL,
                             params={"symbol": pair, "interval": interval, "limit": limit},
                             timeout=15)
            r.raise_for_status()
            return r.json()
        data = guarded_call(_do, source="binance", retries=2)
    except (ImportError, Exception):
        try:
            r = requests.get(BINANCE_KLINE_URL,
                             params={"symbol": pair, "interval": interval, "limit": limit},
                             timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception:
            return None

    if not data:
        return None
    closes = [float(k[4]) for k in data]
    volumes = [float(k[5]) for k in data]
    return {"closes": closes, "volumes": volumes}


def _fetch_yf_recent(symbol, period="5d"):
    """获取 Yahoo Finance 最近数据"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period)
        if df is None or df.empty:
            return None
        closes = df["Close"].values.tolist()
        volumes = df["Volume"].values.tolist()
        return {"closes": closes, "volumes": volumes}
    except Exception:
        return None


# ================================================================
#  信号计算
# ================================================================

def _calc_pct_change(closes):
    """计算最近一日涨跌幅"""
    if not closes or len(closes) < 2:
        return 0
    return (closes[-1] / closes[-2] - 1) * 100


def _calc_momentum(closes, n=5):
    """计算 N 期动量"""
    if not closes or len(closes) < n + 1:
        return 0
    return (closes[-1] / closes[-n - 1] - 1) * 100


def _calc_volatility(closes, n=20):
    """计算波动率"""
    if not closes or len(closes) < n:
        return 0
    arr = np.array(closes[-n:])
    rets = np.diff(arr) / arr[:-1]
    return float(np.std(rets)) if len(rets) > 0 else 0


def analyze_cross_market():
    """
    跨市场信号分析

    Returns:
        dict: {
            "crypto_signal": float,       # 币圈信号 (-1~1)
            "us_signal": float,           # 美股信号 (-1~1)
            "a50_signal": float,          # A50信号 (-1~1)
            "composite_signal": float,    # 综合信号 (-1~1)
            "risk_appetite": str,         # 风险偏好 (risk_on/risk_off/neutral)
            "a_stock_impact": str,        # 对A股影响 (bullish/bearish/neutral)
            "details": list,              # 详细分析
            "suggestion": str,            # 操作建议
        }
    """
    details = []

    # --- 1. 币圈信号 ---
    crypto_signal = 0.0
    for pair, info in CROSS_MARKET_SYMBOLS["crypto"].items():
        data = _fetch_binance_recent(pair, interval="1h", limit=24)
        if data:
            pct = _calc_pct_change(data["closes"])
            mom = _calc_momentum(data["closes"], 12)
            # 归一化到 -1~1
            sig = np.clip(pct / 5.0, -1, 1) * 0.6 + np.clip(mom / 10.0, -1, 1) * 0.4
            crypto_signal += sig * info["weight"]
            details.append(f"{info['name']}: 日涨跌{pct:+.1f}% 12h动量{mom:+.1f}%")

    # --- 2. 美股信号 ---
    us_signal = 0.0
    for sym, info in CROSS_MARKET_SYMBOLS["us_index"].items():
        data = _fetch_yf_recent(sym, period="5d")
        if data:
            pct = _calc_pct_change(data["closes"])
            mom = _calc_momentum(data["closes"], 3)
            sig = np.clip(pct / 3.0, -1, 1) * 0.6 + np.clip(mom / 5.0, -1, 1) * 0.4
            us_signal += sig * info["weight"]
            details.append(f"{info['name']}: 日涨跌{pct:+.1f}% 3日{mom:+.1f}%")

    # --- 3. A50信号 ---
    a50_signal = 0.0
    for sym, info in CROSS_MARKET_SYMBOLS["a50"].items():
        data = _fetch_yf_recent(sym, period="5d")
        if data:
            pct = _calc_pct_change(data["closes"])
            a50_signal = np.clip(pct / 2.0, -1, 1)
            details.append(f"{info['name']}: 日涨跌{pct:+.1f}%")

    # --- 4. 综合信号 ---
    # 权重: 美股(0.45) > A50(0.30) > 币圈(0.25)
    composite = us_signal * 0.45 + a50_signal * 0.30 + crypto_signal * 0.25
    composite = float(np.clip(composite, -1, 1))

    # --- 5. 风险偏好判断 ---
    if composite > 0.3:
        risk_appetite = "risk_on"
    elif composite < -0.3:
        risk_appetite = "risk_off"
    else:
        risk_appetite = "neutral"

    # --- 6. 对A股影响 ---
    if composite > 0.2:
        impact = "bullish"
    elif composite < -0.2:
        impact = "bearish"
    else:
        impact = "neutral"

    # --- 7. 操作建议 ---
    if impact == "bullish":
        if composite > 0.5:
            suggestion = "外围强势, 建议积极做多, 可适当加仓"
        else:
            suggestion = "外围偏多, 可维持现有仓位, 关注高开回落风险"
    elif impact == "bearish":
        if composite < -0.5:
            suggestion = "外围大跌, 建议控制仓位, 防范低开风险, 等待企稳再介入"
        else:
            suggestion = "外围偏弱, 建议谨慎观望, 减少追高"
    else:
        suggestion = "外围信号混杂, 建议以A股自身技术面为主"

    # 背离检测
    divergences = []
    if crypto_signal > 0.3 and us_signal < -0.3:
        divergences.append("币圈强/美股弱 → 关注避险资产")
    if crypto_signal < -0.3 and us_signal > 0.3:
        divergences.append("美股强/币圈弱 → 传统资产占优")
    if us_signal > 0.3 and a50_signal < -0.3:
        divergences.append("美股强/A50弱 → A股可能独立走势")
    if divergences:
        details.extend([f"背离: {d}" for d in divergences])

    return {
        "crypto_signal": round(float(crypto_signal), 3),
        "us_signal": round(float(us_signal), 3),
        "a50_signal": round(float(a50_signal), 3),
        "composite_signal": round(composite, 3),
        "risk_appetite": risk_appetite,
        "a_stock_impact": impact,
        "details": details,
        "suggestion": suggestion,
        "divergences": divergences,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ================================================================
#  主流程
# ================================================================

def run_cross_market_analysis():
    """
    跨市场信号推演主流程

    Returns:
        dict: 分析结果
    """
    print("=" * 65)
    print(f"  跨市场信号推演")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    result = analyze_cross_market()

    # 输出
    impact_map = {"bullish": "利多 ▲", "bearish": "利空 ▼", "neutral": "中性 ─"}
    risk_map = {"risk_on": "风险偏好 (Risk On)", "risk_off": "避险 (Risk Off)", "neutral": "中性"}

    print(f"\n  综合信号: {result['composite_signal']:+.3f}")
    print(f"  对A股影响: {impact_map.get(result['a_stock_impact'], '未知')}")
    print(f"  风险偏好: {risk_map.get(result['risk_appetite'], '未知')}")
    print(f"\n  子信号:")
    print(f"    美股: {result['us_signal']:+.3f}")
    print(f"    A50:  {result['a50_signal']:+.3f}")
    print(f"    币圈: {result['crypto_signal']:+.3f}")
    print(f"\n  详细:")
    for d in result["details"]:
        print(f"    {d}")
    print(f"\n  建议: {result['suggestion']}")

    return result


def get_cross_market_signal():
    """标准化接口 (供 scheduler 调用)

    Returns:
        dict: 跨市场分析结果
    """
    if not CROSS_MARKET_PARAMS.get("enabled", True):
        print("[跨市场推演] 已禁用")
        return {}

    try:
        return run_cross_market_analysis()
    except Exception as e:
        print(f"[跨市场推演异常] {e}")
        traceback.print_exc()
        return {}


# ================================================================
#  入口
# ================================================================

if __name__ == "__main__":
    result = run_cross_market_analysis()
    if result:
        try:
            from notifier import notify_wechat_raw
            impact_map = {"bullish": "利多▲", "bearish": "利空▼", "neutral": "中性─"}
            lines = [
                f"综合信号: {result['composite_signal']:+.3f} → {impact_map.get(result['a_stock_impact'], '?')}",
                f"美股{result['us_signal']:+.3f} | A50{result['a50_signal']:+.3f} | 币圈{result['crypto_signal']:+.3f}",
                "",
            ]
            for d in result["details"]:
                lines.append(d)
            lines.append(f"\n建议: {result['suggestion']}")
            notify_wechat_raw("跨市场信号推演", "\n".join(lines))
            print("\n[微信推送完成]")
        except Exception as e:
            print(f"\n[微信推送失败] {e}")
