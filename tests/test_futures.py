"""
期货趋势策略测试
================
测试合约信息 / 技术指标计算 / 分析逻辑 / 评分
"""

import sys
import os
import unittest
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from futures_strategy import (
    CONTRACT_INFO, get_futures_pool,
    _calc_rsi, _calc_adx, _calc_macd, _calc_atr,
    _analyze_contract,
)
from config import FUTURES_PARAMS


class TestContractInfo(unittest.TestCase):
    """合约信息表测试"""

    def test_has_minimum_contracts(self):
        """至少30个活跃品种"""
        self.assertGreaterEqual(len(CONTRACT_INFO), 30)

    def test_required_fields(self):
        """每个合约有必需字段"""
        for code, info in CONTRACT_INFO.items():
            self.assertIn("name", info, f"{code} missing name")
            self.assertIn("exchange", info, f"{code} missing exchange")
            self.assertIn("multiplier", info, f"{code} missing multiplier")
            self.assertIn("margin_rate", info, f"{code} missing margin_rate")
            self.assertIn("night", info, f"{code} missing night")
            self.assertGreater(info["multiplier"], 0, f"{code} multiplier <= 0")
            self.assertGreater(info["margin_rate"], 0, f"{code} margin_rate <= 0")
            self.assertLess(info["margin_rate"], 1, f"{code} margin_rate >= 1")

    def test_exchange_valid(self):
        """交易所代码合法"""
        valid_exchanges = {"SHFE", "DCE", "CZCE", "CFFEX", "INE"}
        for code, info in CONTRACT_INFO.items():
            self.assertIn(info["exchange"], valid_exchanges, f"{code} invalid exchange")

    def test_key_contracts_present(self):
        """核心品种存在"""
        for key in ["RB", "I", "AU", "AG", "CU", "IF", "SC"]:
            self.assertIn(key, CONTRACT_INFO, f"Missing key contract {key}")


class TestFuturesPool(unittest.TestCase):
    """合约池测试"""

    def test_full_pool(self):
        pool = get_futures_pool(night_only=False)
        self.assertGreaterEqual(len(pool), 30)

    def test_night_pool_subset(self):
        full = get_futures_pool(night_only=False)
        night = get_futures_pool(night_only=True)
        self.assertLessEqual(len(night), len(full))
        # 夜盘品种应该是全品种的子集
        night_codes = {p["code"] for p in night}
        full_codes = {p["code"] for p in full}
        self.assertTrue(night_codes.issubset(full_codes))

    def test_pool_item_structure(self):
        pool = get_futures_pool()
        for item in pool:
            self.assertIn("code", item)
            self.assertIn("name", item)
            self.assertIn("exchange", item)
            self.assertIn("multiplier", item)
            self.assertIn("margin_rate", item)


class TestTechnicalIndicators(unittest.TestCase):
    """技术指标计算测试"""

    def setUp(self):
        """生成模拟数据"""
        np.random.seed(42)
        n = 100
        self.closes = 100 + np.cumsum(np.random.randn(n) * 0.5)
        self.highs = self.closes + np.abs(np.random.randn(n))
        self.lows = self.closes - np.abs(np.random.randn(n))

    def test_rsi_range(self):
        """RSI 值在 0-100 之间"""
        rsi = _calc_rsi(self.closes, 14)
        valid = rsi[~np.isnan(rsi)]
        self.assertTrue(np.all(valid >= 0))
        self.assertTrue(np.all(valid <= 100))

    def test_adx_non_negative(self):
        """ADX 非负"""
        adx = _calc_adx(self.highs, self.lows, self.closes, 14)
        valid = adx[~np.isnan(adx)]
        self.assertTrue(np.all(valid >= 0))

    def test_macd_components(self):
        """MACD 返回3个组件"""
        diff, dea, macd_bar = _calc_macd(self.closes)
        self.assertEqual(len(diff), len(self.closes))
        self.assertEqual(len(dea), len(self.closes))
        self.assertEqual(len(macd_bar), len(self.closes))

    def test_atr_non_negative(self):
        """ATR 非负"""
        atr = _calc_atr(self.highs, self.lows, self.closes, 14)
        valid = atr[~np.isnan(atr)]
        self.assertTrue(np.all(valid >= 0))


class TestAnalyzeContract(unittest.TestCase):
    """合约分析测试"""

    def _make_df(self, trend="up", n=100):
        """生成模拟日K数据"""
        np.random.seed(42)
        if trend == "up":
            closes = 3000 + np.cumsum(np.ones(n) * 5 + np.random.randn(n) * 3)
        elif trend == "down":
            closes = 5000 - np.cumsum(np.ones(n) * 5 + np.random.randn(n) * 3)
        else:
            closes = 3000 + np.cumsum(np.random.randn(n) * 3)
        highs = closes + np.abs(np.random.randn(n)) * 10
        lows = closes - np.abs(np.random.randn(n)) * 10
        volumes = np.random.randint(50000, 200000, n).astype(float)
        oi = np.random.randint(100000, 500000, n).astype(float)
        return pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=n),
            "open": closes - np.random.randn(n) * 5,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
            "open_interest": oi,
        })

    def test_uptrend_long(self):
        """上升趋势应该做多"""
        df = self._make_df("up")
        info = {"name": "测试", "exchange": "SHFE", "multiplier": 10, "margin_rate": 0.10}
        result = _analyze_contract("TEST", info, df)
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "long")
        self.assertGreater(result["score"], 0)

    def test_downtrend_short(self):
        """下降趋势应该做空"""
        df = self._make_df("down")
        info = {"name": "测试", "exchange": "SHFE", "multiplier": 10, "margin_rate": 0.10}
        result = _analyze_contract("TEST", info, df)
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "short")
        self.assertGreater(result["score"], 0)

    def test_result_structure(self):
        """结果应有完整字段"""
        df = self._make_df("up")
        info = {"name": "螺纹钢", "exchange": "SHFE", "multiplier": 10, "margin_rate": 0.10}
        result = _analyze_contract("RB", info, df)
        self.assertIsNotNone(result)
        for key in ["code", "name", "price", "score", "reason", "direction",
                     "margin_per_lot", "atr", "adx", "rsi", "lots", "factor_scores"]:
            self.assertIn(key, result, f"Missing key: {key}")
        self.assertGreater(result["margin_per_lot"], 0)
        self.assertGreater(result["lots"], 0)

    def test_insufficient_data_returns_none(self):
        """数据不足时返回None"""
        df = self._make_df("up", n=30)  # 不足60条
        info = {"name": "测试", "exchange": "SHFE", "multiplier": 10, "margin_rate": 0.10}
        result = _analyze_contract("TEST", info, df)
        self.assertIsNone(result)


class TestConfig(unittest.TestCase):
    """配置测试"""

    def test_weights_sum(self):
        """权重之和应为1.0"""
        weights = FUTURES_PARAMS["weights"]
        total = sum(weights.values())
        self.assertAlmostEqual(total, 1.0, places=2)

    def test_required_params(self):
        """必须参数存在"""
        for key in ["enabled", "top_n", "weights", "min_adx", "min_volume_ratio"]:
            self.assertIn(key, FUTURES_PARAMS, f"Missing param: {key}")


if __name__ == "__main__":
    unittest.main()
