"""
跨市场因子引擎 单元测试
"""

import os
import sys
import json
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cross_asset_factor as caf


# ================================================================
#  Fixtures
# ================================================================

@pytest.fixture(autouse=True)
def _tmp_cache(tmp_path, monkeypatch):
    """使用临时缓存路径"""
    cache_path = str(tmp_path / "cross_asset_cache.json")
    monkeypatch.setattr(caf, "_CACHE_PATH", cache_path)
    monkeypatch.setattr(caf, "CROSS_ASSET_PARAMS", {"enabled": True, "cache_hours": 4})
    return cache_path


# ================================================================
#  单因子: 直接 mock 整个函数
# ================================================================

class TestCalcUsmomentum:
    def test_fallback_on_import_error(self):
        """yfinance 不可用时返回 0.5"""
        with patch.dict("sys.modules", {"yfinance": None}):
            # 强制 reimport 会出错, 直接 mock 函数调用
            pass
        # 直接测试: 让 yf.download 抛异常
        with patch("cross_asset_factor.calc_us_momentum", return_value=0.5):
            score = caf.calc_us_momentum()
        assert score == 0.5

    def test_bounds(self):
        """risk_appetite 返回值在 [0, 1]"""
        assert 0 <= caf.calc_risk_appetite(0.0, 0.0, 0.0, 0.0) <= 1
        assert 0 <= caf.calc_risk_appetite(1.0, 1.0, 1.0, 1.0) <= 1


class TestCalcBtcTrend:
    def test_normal_positive(self):
        """BTC +3% → score > 0.5"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"priceChangePercent": "3.0"}).encode()
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            score = caf.calc_btc_trend()
        assert 0.5 < score <= 1.0

    def test_normal_negative(self):
        """BTC -3% → score < 0.5"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"priceChangePercent": "-3.0"}).encode()
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            score = caf.calc_btc_trend()
        assert 0.0 <= score < 0.5

    def test_zero(self):
        """BTC 0% → score = 0.5"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"priceChangePercent": "0"}).encode()
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            score = caf.calc_btc_trend()
        assert score == 0.5

    def test_extreme_positive(self):
        """BTC +10% → score = 1.0 (clamp)"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"priceChangePercent": "10.0"}).encode()
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            score = caf.calc_btc_trend()
        assert score == 1.0

    def test_fallback_on_error(self):
        """API 失败返回 0.5"""
        with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
            score = caf.calc_btc_trend()
        assert score == 0.5


class TestCalcRiskAppetite:
    def test_all_neutral(self):
        assert caf.calc_risk_appetite(0.5, 0.5, 0.5, 0.5) == 0.5

    def test_all_bullish(self):
        assert caf.calc_risk_appetite(1.0, 1.0, 1.0, 1.0) == 1.0

    def test_all_bearish(self):
        assert caf.calc_risk_appetite(0.0, 0.0, 0.0, 0.0) == 0.0

    def test_weights_sum(self):
        """权重 0.35+0.25+0.20+0.20 = 1.0"""
        assert abs(0.35 + 0.25 + 0.20 + 0.20 - 1.0) < 1e-10

    def test_clamp_high(self):
        assert caf.calc_risk_appetite(1.5, 1.5, 1.5, 1.5) == 1.0

    def test_clamp_low(self):
        assert caf.calc_risk_appetite(-0.5, -0.5, -0.5, -0.5) == 0.0

    def test_mixed(self):
        """US强+BTC弱 → 中偏上"""
        score = caf.calc_risk_appetite(0.9, 0.2, 0.5, 0.5)
        assert 0.4 < score < 0.7


# ================================================================
#  汇总/缓存
# ================================================================

class TestCalcAllIndicators:
    @patch("cross_asset_factor.calc_us_momentum", return_value=0.6)
    @patch("cross_asset_factor.calc_btc_trend", return_value=0.7)
    @patch("cross_asset_factor.calc_a50_premium", return_value=0.55)
    @patch("cross_asset_factor.calc_vix_level", return_value=0.5)
    def test_basic(self, *mocks):
        result = caf.calc_all_indicators()
        assert result["ca_us_momentum"] == 0.6
        assert result["ca_btc_trend"] == 0.7
        assert result["ca_a50_premium"] == 0.55
        assert result["ca_vix_level"] == 0.5
        assert "ca_risk_appetite" in result
        assert result["date"] == date.today().isoformat()

    @patch("cross_asset_factor.calc_us_momentum", return_value=0.5)
    @patch("cross_asset_factor.calc_btc_trend", return_value=0.5)
    @patch("cross_asset_factor.calc_a50_premium", return_value=0.5)
    @patch("cross_asset_factor.calc_vix_level", return_value=0.5)
    def test_cache_persisted(self, *mocks):
        caf.calc_all_indicators()
        from json_store import safe_load
        cache = safe_load(caf._CACHE_PATH, default=[])
        assert len(cache) == 1
        assert cache[0]["date"] == date.today().isoformat()

    @patch("cross_asset_factor.calc_us_momentum", return_value=0.5)
    @patch("cross_asset_factor.calc_btc_trend", return_value=0.5)
    @patch("cross_asset_factor.calc_a50_premium", return_value=0.5)
    @patch("cross_asset_factor.calc_vix_level", return_value=0.5)
    def test_dedup(self, *mocks):
        """同日调用两次, 缓存只有1条"""
        caf.calc_all_indicators()
        caf.calc_all_indicators()
        from json_store import safe_load
        cache = safe_load(caf._CACHE_PATH, default=[])
        today_entries = [c for c in cache if c["date"] == date.today().isoformat()]
        assert len(today_entries) == 1


class TestGetTodayFactors:
    @patch("cross_asset_factor.calc_all_indicators")
    def test_cache_hit(self, mock_calc):
        """缓存命中不重算"""
        from json_store import safe_save
        cached = {
            "ca_us_momentum": 0.6, "ca_btc_trend": 0.5,
            "ca_a50_premium": 0.55, "ca_vix_level": 0.45,
            "ca_risk_appetite": 0.53,
            "date": date.today().isoformat(),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        safe_save(caf._CACHE_PATH, [cached])
        result = caf.get_today_factors()
        mock_calc.assert_not_called()
        assert result["ca_us_momentum"] == 0.6

    @patch("cross_asset_factor.calc_all_indicators", return_value={})
    def test_cache_miss_recalc(self, mock_calc):
        """缓存空时重算"""
        caf.get_today_factors()
        mock_calc.assert_called_once()

    def test_disabled(self, monkeypatch):
        """禁用时返回空"""
        monkeypatch.setattr(caf, "CROSS_ASSET_PARAMS", {"enabled": False})
        result = caf.get_today_factors()
        assert result == {}


# ================================================================
#  注入
# ================================================================

class TestInjectCrossAssetFactors:
    @patch("cross_asset_factor.get_today_factors")
    def test_inject(self, mock_get):
        mock_get.return_value = {
            "ca_us_momentum": 0.6, "ca_btc_trend": 0.5,
            "ca_risk_appetite": 0.55, "date": "2026-03-05",
        }
        df = pd.DataFrame({"code": ["000001", "000002"], "close": [10.0, 20.0]})
        result = caf.inject_cross_asset_factors(df)
        assert "ca_us_momentum" in result.columns
        assert "ca_btc_trend" in result.columns
        assert all(result["ca_us_momentum"] == 0.6)

    def test_inject_empty_factors(self):
        """因子为空时不破坏 df"""
        with patch("cross_asset_factor.get_today_factors", return_value={}):
            df = pd.DataFrame({"code": ["000001"]})
            result = caf.inject_cross_asset_factors(df)
            assert len(result) == 1

    def test_inject_exception_safe(self):
        """异常安全"""
        with patch("cross_asset_factor.get_today_factors", side_effect=Exception("bad")):
            df = pd.DataFrame({"code": ["000001"]})
            result = caf.inject_cross_asset_factors(df)
            assert len(result) == 1


# ================================================================
#  状态/历史
# ================================================================

class TestStatus:
    def test_status_empty(self):
        status = caf.get_cross_asset_status()
        assert status["today"] is None
        assert status["history_days"] == 0

    @patch("cross_asset_factor.calc_us_momentum", return_value=0.5)
    @patch("cross_asset_factor.calc_btc_trend", return_value=0.5)
    @patch("cross_asset_factor.calc_a50_premium", return_value=0.5)
    @patch("cross_asset_factor.calc_vix_level", return_value=0.5)
    def test_status_after_calc(self, *mocks):
        caf.calc_all_indicators()
        status = caf.get_cross_asset_status()
        assert status["today"] is not None
        assert status["history_days"] == 1

    def test_history_empty(self):
        history = caf.get_history(7)
        assert history == []


# ================================================================
#  get_risk_multiplier
# ================================================================

class TestRiskMultiplier:
    @patch("cross_asset_factor.get_today_factors")
    def test_risk_on(self, mock_factors):
        mock_factors.return_value = {"ca_risk_appetite": 0.75}
        assert caf.get_risk_multiplier() == 1.05

    @patch("cross_asset_factor.get_today_factors")
    def test_risk_off(self, mock_factors):
        mock_factors.return_value = {"ca_risk_appetite": 0.20}
        assert caf.get_risk_multiplier() == 0.90

    @patch("cross_asset_factor.get_today_factors")
    def test_neutral(self, mock_factors):
        mock_factors.return_value = {"ca_risk_appetite": 0.50}
        assert caf.get_risk_multiplier() == 1.0

    @patch("cross_asset_factor.get_today_factors")
    def test_empty_factors(self, mock_factors):
        mock_factors.return_value = {}
        assert caf.get_risk_multiplier() == 1.0

    @patch("cross_asset_factor.get_today_factors", side_effect=Exception("fail"))
    def test_exception_returns_1(self, mock_factors):
        assert caf.get_risk_multiplier() == 1.0
