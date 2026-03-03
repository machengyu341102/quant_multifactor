"""
美股收盘分析策略测试
"""
import sys
import os
import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from us_stock_strategy import (
    US_STOCK_POOL,
    get_us_stock_pool,
    _fetch_us_daily,
    _analyze_us_stock,
    _calc_rsi,
    _calc_adx,
    _calc_macd,
    _calc_atr,
    run_us_stock_scan,
    get_us_stock_recommendations,
)


# ================================================================
#  辅助: 生成模拟K线数据
# ================================================================

def _make_kline_df(n=100, trend="up"):
    """生成模拟日K DataFrame"""
    np.random.seed(42)
    base = 150.0
    if trend == "up":
        prices = base + np.cumsum(np.random.uniform(0, 2, n))
    elif trend == "down":
        prices = base - np.cumsum(np.random.uniform(0, 2, n))
    else:
        prices = base + np.cumsum(np.random.uniform(-1, 1, n))

    df = pd.DataFrame({
        "open": prices * 0.998,
        "high": prices * 1.01,
        "low": prices * 0.99,
        "close": prices,
        "volume": np.random.uniform(1e6, 5e6, n),
    })
    df.index = pd.date_range("2025-10-01", periods=n)
    return df


# ================================================================
#  测试: 标的池
# ================================================================

class TestUSStockPool:
    def test_pool_has_stocks(self):
        assert len(US_STOCK_POOL) >= 30

    def test_get_pool(self):
        pool = get_us_stock_pool()
        assert len(pool) == len(US_STOCK_POOL)
        assert all("symbol" in p and "name" in p and "sector" in p for p in pool)

    def test_key_stocks_in_pool(self):
        for sym in ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"]:
            assert sym in US_STOCK_POOL, f"{sym} missing from pool"

    def test_sectors_exist(self):
        sectors = set(info["sector"] for info in US_STOCK_POOL.values())
        assert "科技" in sectors
        assert "ETF" in sectors


# ================================================================
#  测试: 技术指标
# ================================================================

class TestIndicators:
    def test_rsi_range(self):
        closes = np.array([100 + i * 0.5 for i in range(100)], dtype=float)
        rsi = _calc_rsi(closes, 14)
        valid = rsi[~np.isnan(rsi)]
        assert len(valid) > 0
        assert all(0 <= v <= 100 for v in valid)

    def test_adx_range(self):
        n = 100
        closes = np.array([100 + i * 0.3 for i in range(n)], dtype=float)
        highs = closes * 1.02
        lows = closes * 0.98
        adx = _calc_adx(highs, lows, closes, 14)
        valid = adx[~np.isnan(adx)]
        assert len(valid) > 0
        assert all(v >= 0 for v in valid)

    def test_macd_output(self):
        closes = np.array([100 + i * 0.2 for i in range(100)], dtype=float)
        diff, dea, bar = _calc_macd(closes)
        assert len(diff) == 100

    def test_atr_non_negative(self):
        n = 100
        closes = np.array([100 + i * 0.3 for i in range(n)], dtype=float)
        highs = closes * 1.02
        lows = closes * 0.98
        atr = _calc_atr(highs, lows, closes, 14)
        valid = atr[~np.isnan(atr)]
        assert all(v >= 0 for v in valid)


# ================================================================
#  测试: 单标的分析
# ================================================================

class TestAnalyzeUSStock:
    def test_uptrend_long(self):
        df = _make_kline_df(100, trend="up")
        info = {"name": "苹果", "sector": "科技"}
        result = _analyze_us_stock("AAPL", info, df)
        assert result is not None
        assert result["direction"] == "long"
        assert result["score"] > 0

    def test_downtrend_short(self):
        df = _make_kline_df(100, trend="down")
        info = {"name": "英特尔", "sector": "半导体"}
        result = _analyze_us_stock("INTC", info, df)
        assert result is not None
        assert result["direction"] == "short"

    def test_short_data_returns_none(self):
        df = _make_kline_df(30, trend="up")
        info = {"name": "苹果", "sector": "科技"}
        result = _analyze_us_stock("AAPL", info, df)
        assert result is None

    def test_none_df_returns_none(self):
        info = {"name": "苹果", "sector": "科技"}
        result = _analyze_us_stock("AAPL", info, None)
        assert result is None

    def test_result_fields(self):
        df = _make_kline_df(100, trend="up")
        info = {"name": "英伟达", "sector": "科技"}
        result = _analyze_us_stock("NVDA", info, df)
        assert result is not None
        for key in ["symbol", "name", "sector", "price", "score", "reason",
                     "direction", "atr", "adx", "rsi", "macd", "vol_ratio",
                     "stop_distance", "pct_chg", "pct_5d", "factor_scores"]:
            assert key in result, f"Missing key: {key}"
        fs = result["factor_scores"]
        for fk in ["s_trend", "s_momentum", "s_volume", "s_risk"]:
            assert fk in fs


# ================================================================
#  测试: 主流程
# ================================================================

class TestRunScan:
    @patch("us_stock_strategy._fetch_us_daily")
    def test_scan_with_mock(self, mock_fetch):
        mock_fetch.return_value = _make_kline_df(100, trend="up")
        results = run_us_stock_scan(top_n=3)
        assert isinstance(results, list)
        assert len(results) <= 3
        if results:
            assert results[0]["score"] >= results[-1]["score"]

    @patch("us_stock_strategy._fetch_us_daily")
    def test_scan_empty(self, mock_fetch):
        mock_fetch.return_value = None
        results = run_us_stock_scan(top_n=3)
        assert results == []


# ================================================================
#  测试: 标准化接口
# ================================================================

class TestGetRecommendations:
    @patch("us_stock_strategy.run_us_stock_scan")
    def test_standard_format(self, mock_scan):
        mock_scan.return_value = [{
            "symbol": "NVDA", "name": "英伟达", "sector": "科技",
            "price": 850, "score": 0.9, "reason": "做多 | 科技 | ADX=35",
            "direction": "long", "atr": 15, "pct_chg": 3.2,
            "factor_scores": {"s_trend": 0.9},
        }]
        items = get_us_stock_recommendations(top_n=3)
        assert len(items) == 1
        assert items[0]["code"] == "NVDA"
        assert items[0]["name"] == "英伟达"
        assert "factor_scores" in items[0]

    @patch("us_stock_strategy.US_STOCK_PARAMS", {"enabled": False})
    def test_disabled(self):
        items = get_us_stock_recommendations()
        assert items == []
