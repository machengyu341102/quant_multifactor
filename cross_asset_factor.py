"""
跨市场因子引擎
=============
将跨市场信号量化为因子, 注入A股评分。散户无法获取的信息优势。

因子:
  ca_us_momentum   — S&P 500 + NASDAQ 隔夜动量 [0,1]
  ca_btc_trend     — BTC 24h 动量 [0,1]
  ca_a50_premium   — A50 期货 vs 昨日A股 → 跳空预测 [0,1]
  ca_vix_level     — VIX 恐慌指数 → risk off [0,1] (高=low risk)
  ca_hk_sentiment  — 恒生指数 + 恒生科技 → 港股情绪 [0,1]
  ca_risk_appetite — 综合风险偏好 [0,1]

调度: 07:35 (morning_prep 之后、策略之前)
数据: cross_asset_cache.json

CLI:
  python3 cross_asset_factor.py          # 计算并显示
  python3 cross_asset_factor.py status   # 显示缓存状态
  python3 cross_asset_factor.py calc     # 强制重算
  python3 cross_asset_factor.py history  # 近7天历史
"""

import os
import sys
import traceback
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from log_config import get_logger
from json_store import safe_load, safe_save

logger = get_logger("cross_asset_factor")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_PATH = os.path.join(_BASE_DIR, "cross_asset_cache.json")

try:
    from config import CROSS_ASSET_PARAMS
except ImportError:
    CROSS_ASSET_PARAMS = {"enabled": True, "cache_hours": 4}


# ================================================================
#  单因子计算
# ================================================================

def calc_us_momentum() -> float:
    """S&P 500 + NASDAQ 隔夜收益 → [0,1]
    1日收益映射: -3% → 0, 0% → 0.5, +3% → 1.0
    """
    try:
        import yfinance as yf
        tickers = yf.download(["^GSPC", "^IXIC"], period="5d", interval="1d",
                              progress=False, threads=True)
        close = tickers["Close"]
        if close.empty or len(close) < 2:
            return 0.5

        # 最近1日收益率
        ret_sp = (close["^GSPC"].iloc[-1] / close["^GSPC"].iloc[-2] - 1) if "^GSPC" in close.columns else 0
        ret_nq = (close["^IXIC"].iloc[-1] / close["^IXIC"].iloc[-2] - 1) if "^IXIC" in close.columns else 0

        # 加权平均 (NASDAQ 权重稍高 — 科技股与A股相关性更强)
        avg_ret = ret_sp * 0.4 + ret_nq * 0.6

        # 映射 [-3%, +3%] → [0, 1]
        score = max(0.0, min(1.0, (avg_ret + 0.03) / 0.06))
        return round(score, 4)
    except Exception as e:
        logger.warning("calc_us_momentum failed: %s", e)
        return 0.5


def calc_btc_trend() -> float:
    """BTC 24h 动量 → [0,1]
    使用 Binance 公开 REST API (无需认证)
    24h 涨跌幅映射: -5% → 0, 0% → 0.5, +5% → 1.0
    """
    try:
        import urllib.request
        import json

        url = "https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT"
        req = urllib.request.Request(url, headers={"User-Agent": "quant/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        pct_change = float(data.get("priceChangePercent", 0)) / 100  # 百分比→小数

        # 映射 [-5%, +5%] → [0, 1]
        score = max(0.0, min(1.0, (pct_change + 0.05) / 0.10))
        return round(score, 4)
    except Exception as e:
        logger.warning("calc_btc_trend failed: %s", e)
        return 0.5


def calc_a50_premium() -> float:
    """A50 期货 vs 昨日A股收盘 → 跳空预测 [0,1]
    A50 溢价映射: -2% → 0, 0% → 0.5, +2% → 1.0
    """
    try:
        import yfinance as yf
        # 富时中国A50期货
        a50 = yf.download("XIN9.FGI", period="5d", interval="1d", progress=False)
        if a50.empty or len(a50) < 2:
            return 0.5

        close_col = "Close"
        if isinstance(a50.columns, type(a50.columns)) and hasattr(a50.columns, 'get_level_values'):
            try:
                a50.columns = a50.columns.get_level_values(0)
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

        if "Close" not in a50.columns:
            return 0.5

        # A50 最新 vs 前日 (代理 overnight premium)
        ret = a50["Close"].iloc[-1] / a50["Close"].iloc[-2] - 1

        # 映射 [-2%, +2%] → [0, 1]
        score = max(0.0, min(1.0, (ret + 0.02) / 0.04))
        return round(score, 4)
    except Exception as e:
        logger.warning("calc_a50_premium failed: %s", e)
        return 0.5


def calc_vix_level() -> float:
    """VIX 恐慌指数水平 → [0,1] (高VIX=low score=risk off)
    VIX 映射: 35+ → 0 (恐慌), 20 → 0.5, 10 → 1.0 (贪婪)
    """
    try:
        import yfinance as yf
        vix = yf.download("^VIX", period="5d", interval="1d", progress=False)
        if vix.empty:
            return 0.5

        if isinstance(vix.columns, type(vix.columns)) and hasattr(vix.columns, 'get_level_values'):
            try:
                vix.columns = vix.columns.get_level_values(0)
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

        if "Close" not in vix.columns:
            return 0.5

        vix_val = float(vix["Close"].iloc[-1])

        # 映射 VIX [10, 35] → [1.0, 0.0] (反向)
        score = max(0.0, min(1.0, (35 - vix_val) / 25))
        return round(score, 4)
    except Exception as e:
        logger.warning("calc_vix_level failed: %s", e)
        return 0.5


def calc_risk_appetite(us: float, btc: float, vix: float, a50: float) -> float:
    """综合风险偏好 = 加权组合
    = us_momentum*0.35 + btc_trend*0.25 + vix_level*0.20 + a50*0.20
    """
    score = us * 0.35 + btc * 0.25 + vix * 0.20 + a50 * 0.20
    return round(max(0.0, min(1.0, score)), 4)


def calc_hk_sentiment() -> float:
    """港股情绪 (恒生指数 + 恒生科技) → [0,1]
    1日收益映射: -2% → 0, 0% → 0.5, +2% → 1.0
    """
    try:
        import akshare as ak

        # 恒生指数
        hsi = ak.stock_hk_index_daily_em(symbol="HSI")
        if hsi is None or hsi.empty:
            return 0.5
        hsi = hsi.tail(2)
        ret_hsi = (hsi.iloc[-1]["收盘"] / hsi.iloc[-2]["收盘"] - 1) if len(hsi) >= 2 else 0

        # 恒生科技
        hstech = ak.stock_hk_index_daily_em(symbol="HSTECH")
        if hstech is None or hstech.empty:
            ret_hstech = 0
        else:
            hstech = hstech.tail(2)
            ret_hstech = (hstech.iloc[-1]["收盘"] / hstech.iloc[-2]["收盘"] - 1) if len(hstech) >= 2 else 0

        # 加权平均 (科技权重稍高)
        avg_ret = ret_hsi * 0.4 + ret_hstech * 0.6

        # 映射 [-2%, +2%] → [0, 1]
        score = max(0.0, min(1.0, (avg_ret + 0.02) / 0.04))
        return round(score, 4)
    except Exception as e:
        logger.warning("calc_hk_sentiment failed: %s", e)
        return 0.5


# ================================================================
#  汇总计算 + 缓存
# ================================================================

def calc_all_indicators() -> dict:
    """计算所有6个跨市场因子 + 1个综合风险偏好
    缓存到 cross_asset_cache.json (按日期)
    """
    logger.info("计算跨市场因子...")
    us = calc_us_momentum()
    btc = calc_btc_trend()
    a50 = calc_a50_premium()
    vix = calc_vix_level()
    hk = calc_hk_sentiment()
    risk = calc_risk_appetite(us, btc, vix, a50)

    result = {
        "ca_us_momentum": us,
        "ca_btc_trend": btc,
        "ca_a50_premium": a50,
        "ca_vix_level": vix,
        "ca_hk_sentiment": hk,
        "ca_risk_appetite": risk,
        "date": date.today().isoformat(),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 持久化缓存 (保留近30天历史)
    cache = safe_load(_CACHE_PATH, default=[])
    if not isinstance(cache, list):
        cache = []
    # 去重: 同日只保留最新
    cache = [c for c in cache if c.get("date") != result["date"]]
    cache.append(result)
    cache = cache[-30:]  # 只留最近30天
    safe_save(_CACHE_PATH, cache)

    logger.info("跨市场因子: US=%.3f BTC=%.3f A50=%.3f VIX=%.3f HK=%.3f → risk=%.3f",
                us, btc, a50, vix, hk, risk)
    return result


def get_today_factors() -> dict:
    """读缓存, 若过期则重算

    Returns:
        {ca_us_momentum, ca_btc_trend, ca_a50_premium, ca_vix_level, ca_risk_appetite}
    """
    if not CROSS_ASSET_PARAMS.get("enabled", True):
        return {}

    cache = safe_load(_CACHE_PATH, default=[])
    if not isinstance(cache, list):
        cache = []

    today_str = date.today().isoformat()
    cache_hours = CROSS_ASSET_PARAMS.get("cache_hours", 4)

    # 查找今日缓存
    for entry in reversed(cache):
        if entry.get("date") == today_str:
            # 检查是否过期
            ts = entry.get("timestamp", "")
            if ts:
                try:
                    cached_time = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                    age_hours = (datetime.now() - cached_time).total_seconds() / 3600
                    if age_hours < cache_hours:
                        return entry
                except ValueError:
                    pass
            else:
                return entry

    # 缓存不存在或过期, 重算
    try:
        return calc_all_indicators()
    except Exception as e:
        logger.error("get_today_factors failed: %s", e)
        return {}


def inject_cross_asset_factors(df):
    """为股票 DataFrame 添加 ca_* 列 (所有行相同值 = 当日宏观因子)
    异常安全: 失败返回原 df

    注意: ca_* 因子是宏观级别 (同一天所有股票值相同), 不适合作为
    ML 逐股特征。应通过 get_risk_multiplier() 做 regime 调整。
    """
    try:
        factors = get_today_factors()
        if not factors:
            return df

        import pandas as pd
        ca_keys = [k for k in factors if k.startswith("ca_")]
        for key in ca_keys:
            df[key] = factors[key]

        return df
    except Exception as e:
        logger.warning("inject_cross_asset_factors failed: %s", e)
        return df


def get_risk_multiplier() -> float:
    """根据跨市场风险偏好返回得分乘数

    用于策略 total_score 的 regime 调整:
      risk_appetite >= 0.65 (Risk On)  → 1.05  (略加分)
      risk_appetite <= 0.35 (Risk Off) → 0.90  (降权)
      其余 (中性)                      → 1.00

    异常安全: 失败返回 1.0 (不调整)
    """
    try:
        factors = get_today_factors()
        if not factors:
            return 1.0
        risk = factors.get("ca_risk_appetite", 0.5)
        if risk >= 0.65:
            return 1.05
        elif risk <= 0.35:
            return 0.90
        else:
            return 1.0
    except Exception:
        return 1.0


# ================================================================
#  状态查询
# ================================================================

def get_cross_asset_status() -> dict:
    """当前状态: 最新因子值, 缓存时间, 历史天数"""
    cache = safe_load(_CACHE_PATH, default=[])
    if not isinstance(cache, list):
        cache = []

    today_str = date.today().isoformat()
    today_entry = None
    for entry in reversed(cache):
        if entry.get("date") == today_str:
            today_entry = entry
            break

    return {
        "enabled": CROSS_ASSET_PARAMS.get("enabled", True),
        "today": today_entry,
        "history_days": len(cache),
        "cache_path": _CACHE_PATH,
    }


def get_history(days: int = 7) -> list[dict]:
    """近N天历史"""
    cache = safe_load(_CACHE_PATH, default=[])
    if not isinstance(cache, list):
        return []
    return cache[-days:]


# ================================================================
#  CLI
# ================================================================

def _print_factors(factors: dict):
    """格式化输出因子"""
    if not factors:
        print("  (无数据)")
        return
    print(f"  日期: {factors.get('date', '?')}")
    print(f"  时间: {factors.get('timestamp', '?')}")
    print(f"  US动量:  {factors.get('ca_us_momentum', 0):.4f}")
    print(f"  BTC趋势: {factors.get('ca_btc_trend', 0):.4f}")
    print(f"  A50溢价: {factors.get('ca_a50_premium', 0):.4f}")
    print(f"  VIX水平: {factors.get('ca_vix_level', 0):.4f}")
    print(f"  风险偏好: {factors.get('ca_risk_appetite', 0):.4f}")

    risk = factors.get("ca_risk_appetite", 0.5)
    if risk >= 0.65:
        label = "Risk On (偏多)"
    elif risk <= 0.35:
        label = "Risk Off (偏空)"
    else:
        label = "中性"
    print(f"  判断: {label}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "calc"

    print("=" * 50)
    print("  跨市场因子引擎")
    print("=" * 50)

    if mode == "status":
        status = get_cross_asset_status()
        print(f"\n  启用: {status['enabled']}")
        print(f"  缓存天数: {status['history_days']}")
        if status["today"]:
            print("\n  今日因子:")
            _print_factors(status["today"])
        else:
            print("  今日: 尚未计算")

    elif mode == "calc":
        factors = calc_all_indicators()
        print("\n  计算完成:")
        _print_factors(factors)

    elif mode == "history":
        history = get_history(7)
        if history:
            print(f"\n  近{len(history)}天:")
            for h in history:
                risk = h.get("ca_risk_appetite", 0)
                label = "RiskOn" if risk >= 0.65 else ("RiskOff" if risk <= 0.35 else "中性")
                print(f"  {h['date']} risk={risk:.3f} [{label}] "
                      f"US={h.get('ca_us_momentum', 0):.3f} "
                      f"BTC={h.get('ca_btc_trend', 0):.3f} "
                      f"A50={h.get('ca_a50_premium', 0):.3f} "
                      f"VIX={h.get('ca_vix_level', 0):.3f}")
        else:
            print("  无历史数据")

    else:
        # 默认: 获取今日因子 (有缓存就用缓存)
        factors = get_today_factors()
        _print_factors(factors)
