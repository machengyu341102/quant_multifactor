"""
币圈趋势策略测试
"""
import sys
import os
import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from crypto_strategy import (
    CRYPTO_POOL,
    get_crypto_pool,
    _fetch_crypto_klines,
    _analyze_crypto,
    _calc_rsi,
    _calc_adx,
    _calc_macd,
    _calc_atr,
    run_crypto_scan,
    get_crypto_recommendations,
)


# ================================================================
#  辅助: 生成模拟K线数据
# ================================================================

def _make_kline_df(n=100, trend="up"):
    """生成模拟的 Binance 格式日K DataFrame"""
    np.random.seed(42)
    base = 50000.0
    if trend == "up":
        prices = base + np.cumsum(np.random.uniform(0, 500, n))
    elif trend == "down":
        prices = base - np.cumsum(np.random.uniform(0, 500, n))
    else:
        prices = base + np.cumsum(np.random.uniform(-200, 200, n))

    df = pd.DataFrame({
        "open": prices * 0.998,
        "high": prices * 1.01,
        "low": prices * 0.99,
        "close": prices,
        "volume": np.random.uniform(1000, 5000, n),
        "quote_volume": np.random.uniform(1e7, 5e7, n),
        "date": pd.date_range("2025-10-01", periods=n),
    })
    return df


# ================================================================
#  测试: 币种池
# ================================================================

class TestCryptoPool:
    def test_pool_has_coins(self):
        assert len(CRYPTO_POOL) >= 20

    def test_get_crypto_pool(self):
        pool = get_crypto_pool()
        assert len(pool) == len(CRYPTO_POOL)
        assert all("pair" in p and "name" in p and "symbol" in p for p in pool)

    def test_btc_in_pool(self):
        assert "BTCUSDT" in CRYPTO_POOL
        assert CRYPTO_POOL["BTCUSDT"]["name"] == "比特币"


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
        assert len(dea) == 100
        assert len(bar) == 100

    def test_atr_non_negative(self):
        n = 100
        closes = np.array([100 + i * 0.3 for i in range(n)], dtype=float)
        highs = closes * 1.02
        lows = closes * 0.98
        atr = _calc_atr(highs, lows, closes, 14)
        valid = atr[~np.isnan(atr)]
        assert all(v >= 0 for v in valid)


# ================================================================
#  测试: 单币种分析
# ================================================================

class TestAnalyzeCrypto:
    def test_uptrend_long(self):
        df = _make_kline_df(100, trend="up")
        info = {"symbol": "BTC", "name": "比特币"}
        result = _analyze_crypto("BTCUSDT", info, df)
        assert result is not None
        assert result["direction"] == "long"
        assert result["score"] > 0
        assert "pair" in result
        assert "factor_scores" in result

    def test_downtrend_short(self):
        df = _make_kline_df(100, trend="down")
        info = {"symbol": "ETH", "name": "以太坊"}
        result = _analyze_crypto("ETHUSDT", info, df)
        assert result is not None
        assert result["direction"] == "short"

    def test_short_data_returns_none(self):
        df = _make_kline_df(30, trend="up")  # 不足60条
        info = {"symbol": "SOL", "name": "Solana"}
        result = _analyze_crypto("SOLUSDT", info, df)
        assert result is None

    def test_none_df_returns_none(self):
        info = {"symbol": "SOL", "name": "Solana"}
        result = _analyze_crypto("SOLUSDT", info, None)
        assert result is None

    def test_result_fields(self):
        df = _make_kline_df(100, trend="up")
        info = {"symbol": "BTC", "name": "比特币"}
        result = _analyze_crypto("BTCUSDT", info, df)
        assert result is not None
        for key in ["pair", "symbol", "name", "price", "score", "reason",
                     "direction", "atr", "adx", "rsi", "macd", "vol_ratio",
                     "stop_distance", "factor_scores"]:
            assert key in result, f"Missing key: {key}"
        fs = result["factor_scores"]
        for fk in ["s_trend", "s_momentum", "s_volume", "s_risk"]:
            assert fk in fs


# ================================================================
#  测试: 主流程
# ================================================================

class TestRunCryptoScan:
    @patch("crypto_strategy._fetch_crypto_klines")
    def test_scan_with_mock(self, mock_fetch):
        mock_fetch.return_value = _make_kline_df(100, trend="up")
        results = run_crypto_scan(top_n=3)
        assert isinstance(results, list)
        assert len(results) <= 3
        if results:
            assert results[0]["score"] >= results[-1]["score"]

    @patch("crypto_strategy._fetch_crypto_klines")
    def test_scan_empty(self, mock_fetch):
        mock_fetch.return_value = None
        results = run_crypto_scan(top_n=3)
        assert results == []


# ================================================================
#  测试: 标准化接口
# ================================================================

class TestGetRecommendations:
    @patch("crypto_strategy.run_crypto_scan")
    def test_standard_format(self, mock_scan):
        mock_scan.return_value = [{
            "pair": "BTCUSDT", "symbol": "BTC", "name": "比特币",
            "price": 60000, "score": 0.85, "reason": "做多 | ADX=30",
            "direction": "long", "atr": 1500, "factor_scores": {"s_trend": 0.8},
        }]
        items = get_crypto_recommendations(top_n=3)
        assert len(items) == 1
        assert items[0]["code"] == "BTC"
        assert items[0]["name"] == "比特币"
        assert "factor_scores" in items[0]

    @patch("crypto_strategy.CRYPTO_PARAMS", {"enabled": False})
    def test_disabled(self):
        items = get_crypto_recommendations()
        assert items == []
