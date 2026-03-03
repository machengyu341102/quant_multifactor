"""
跨市场信号推演策略测试
"""
import sys
import os
import numpy as np
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cross_market_strategy import (
    CROSS_MARKET_SYMBOLS,
    _calc_pct_change,
    _calc_momentum,
    _calc_volatility,
    analyze_cross_market,
    run_cross_market_analysis,
    get_cross_market_signal,
)


# ================================================================
#  测试: 工具函数
# ================================================================

class TestCalcFunctions:
    def test_pct_change_up(self):
        closes = [100, 102]
        assert abs(_calc_pct_change(closes) - 2.0) < 0.01

    def test_pct_change_down(self):
        closes = [100, 95]
        assert abs(_calc_pct_change(closes) - (-5.0)) < 0.01

    def test_pct_change_empty(self):
        assert _calc_pct_change([]) == 0
        assert _calc_pct_change([100]) == 0

    def test_momentum(self):
        closes = [100, 101, 102, 103, 104, 105]
        mom = _calc_momentum(closes, 5)
        assert mom > 0

    def test_momentum_short(self):
        assert _calc_momentum([100], 5) == 0

    def test_volatility(self):
        closes = list(range(100, 120))
        vol = _calc_volatility(closes, 20)
        assert vol >= 0

    def test_volatility_empty(self):
        assert _calc_volatility([], 20) == 0


# ================================================================
#  测试: 符号定义
# ================================================================

class TestSymbols:
    def test_crypto_symbols(self):
        assert "BTCUSDT" in CROSS_MARKET_SYMBOLS["crypto"]
        assert "ETHUSDT" in CROSS_MARKET_SYMBOLS["crypto"]

    def test_us_index_symbols(self):
        assert "SPY" in CROSS_MARKET_SYMBOLS["us_index"]
        assert "QQQ" in CROSS_MARKET_SYMBOLS["us_index"]

    def test_weights_sum(self):
        for market, symbols in CROSS_MARKET_SYMBOLS.items():
            total = sum(info["weight"] for info in symbols.values())
            assert abs(total - 1.0) < 0.01, f"{market} weights sum to {total}"


# ================================================================
#  测试: 跨市场分析
# ================================================================

class TestAnalyzeCrossMarket:
    @patch("cross_market_strategy._fetch_yf_recent")
    @patch("cross_market_strategy._fetch_binance_recent")
    def test_bullish_result(self, mock_binance, mock_yf):
        # 模拟全面上涨
        mock_binance.return_value = {"closes": [100 + i * 2 for i in range(24)], "volumes": [1000] * 24}
        mock_yf.return_value = {"closes": [100 + i * 1 for i in range(5)], "volumes": [1e6] * 5}

        result = analyze_cross_market()
        assert result["composite_signal"] > 0
        assert result["a_stock_impact"] in ("bullish", "neutral")
        assert "timestamp" in result

    @patch("cross_market_strategy._fetch_yf_recent")
    @patch("cross_market_strategy._fetch_binance_recent")
    def test_bearish_result(self, mock_binance, mock_yf):
        # 模拟全面下跌
        mock_binance.return_value = {"closes": [100 - i * 2 for i in range(24)], "volumes": [1000] * 24}
        mock_yf.return_value = {"closes": [100 - i * 1 for i in range(5)], "volumes": [1e6] * 5}

        result = analyze_cross_market()
        assert result["composite_signal"] < 0
        assert result["a_stock_impact"] in ("bearish", "neutral")

    @patch("cross_market_strategy._fetch_yf_recent")
    @patch("cross_market_strategy._fetch_binance_recent")
    def test_all_fail(self, mock_binance, mock_yf):
        mock_binance.return_value = None
        mock_yf.return_value = None

        result = analyze_cross_market()
        assert result["composite_signal"] == 0
        assert result["a_stock_impact"] == "neutral"

    @patch("cross_market_strategy._fetch_yf_recent")
    @patch("cross_market_strategy._fetch_binance_recent")
    def test_result_fields(self, mock_binance, mock_yf):
        mock_binance.return_value = {"closes": [100] * 24, "volumes": [1000] * 24}
        mock_yf.return_value = {"closes": [100] * 5, "volumes": [1e6] * 5}

        result = analyze_cross_market()
        for key in ["crypto_signal", "us_signal", "a50_signal",
                     "composite_signal", "risk_appetite", "a_stock_impact",
                     "details", "suggestion", "divergences", "timestamp"]:
            assert key in result, f"Missing key: {key}"

    @patch("cross_market_strategy._fetch_yf_recent")
    @patch("cross_market_strategy._fetch_binance_recent")
    def test_risk_appetite_values(self, mock_binance, mock_yf):
        mock_binance.return_value = {"closes": [100] * 24, "volumes": [1000] * 24}
        mock_yf.return_value = {"closes": [100] * 5, "volumes": [1e6] * 5}

        result = analyze_cross_market()
        assert result["risk_appetite"] in ("risk_on", "risk_off", "neutral")


# ================================================================
#  测试: 标准化接口
# ================================================================

class TestGetSignal:
    @patch("cross_market_strategy.run_cross_market_analysis")
    def test_returns_result(self, mock_run):
        mock_run.return_value = {"composite_signal": 0.5, "a_stock_impact": "bullish"}
        result = get_cross_market_signal()
        assert result["composite_signal"] == 0.5

    @patch("cross_market_strategy.CROSS_MARKET_PARAMS", {"enabled": False})
    def test_disabled(self):
        result = get_cross_market_signal()
        assert result == {}
