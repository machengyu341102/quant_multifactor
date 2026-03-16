"""
环境路由器 单元测试
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import regime_router as rr


# ================================================================
#  Fixtures
# ================================================================

@pytest.fixture(autouse=True)
def _tmp_routing(tmp_path, monkeypatch):
    """临时路由文件"""
    routing_path = str(tmp_path / "regime_routing.json")
    monkeypatch.setattr(rr, "_ROUTING_PATH", routing_path)
    monkeypatch.setattr(rr, "REGIME_ROUTER_PARAMS", {
        "enabled": True, "lookback_days": 60, "min_ratio": 0.05,
        "max_ratio": 0.30, "min_samples": 10, "default_fitness": 0.5,
    })
    return routing_path


@pytest.fixture
def mock_regime_bull():
    return {"regime": "bull", "score": 0.75, "signals": {}}


@pytest.fixture
def mock_regime_bear():
    return {"regime": "bear", "score": 0.20, "signals": {}}


@pytest.fixture
def mock_matrix():
    """策略×环境胜率矩阵"""
    return {
        "放量突破选股": {
            "bull": {"win_rate": 65.0, "total": 30},
            "bear": {"win_rate": 20.0, "total": 15},
        },
        "低吸回调选股": {
            "bull": {"win_rate": 40.0, "total": 25},
            "bear": {"win_rate": 55.0, "total": 20},
        },
        "缩量整理选股": {
            "bull": {"win_rate": 50.0, "total": 35},
            "bear": {"win_rate": 45.0, "total": 30},
        },
        "趋势跟踪选股": {
            "bull": {"win_rate": 70.0, "total": 22},
            "bear": {"win_rate": 15.0, "total": 12},
        },
    }


# ================================================================
#  calc_strategy_fitness
# ================================================================

class TestCalcStrategyFitness:
    @patch("signal_tracker.get_regime_strategy_matrix")
    @patch("regime_router._get_current_regime")
    def test_bull_regime(self, mock_regime, mock_matrix_fn, mock_regime_bull, mock_matrix):
        mock_regime.return_value = mock_regime_bull
        mock_matrix_fn.return_value = mock_matrix

        result = rr.calc_strategy_fitness()

        assert "breakout" in result
        assert result["breakout"]["regime"] == "bull"
        # breakout 牛市 win_rate=65%, total=30 → confidence=1.0
        # fitness = 0.65 * 1.0 = 0.65
        assert result["breakout"]["fitness"] == 0.65

    @patch("signal_tracker.get_regime_strategy_matrix")
    @patch("regime_router._get_current_regime")
    def test_bear_regime(self, mock_regime, mock_matrix_fn, mock_regime_bear, mock_matrix):
        mock_regime.return_value = mock_regime_bear
        mock_matrix_fn.return_value = mock_matrix

        result = rr.calc_strategy_fitness()

        # breakout 熊市 win_rate=20%, total=15 → confidence=0.75
        assert result["breakout"]["fitness"] == pytest.approx(0.20 * 0.75, abs=0.01)
        # dip_buy 熊市 win_rate=55%, total=20 → confidence=1.0
        assert result["dip_buy"]["fitness"] == pytest.approx(0.55, abs=0.01)

    @patch("signal_tracker.get_regime_strategy_matrix")
    @patch("regime_router._get_current_regime")
    def test_insufficient_data(self, mock_regime, mock_matrix_fn, mock_regime_bull):
        """数据不足 → default_fitness"""
        mock_regime.return_value = mock_regime_bull
        mock_matrix_fn.return_value = {}

        result = rr.calc_strategy_fitness()
        for key, val in result.items():
            assert val["fitness"] == 0.5  # default


# ================================================================
#  get_capital_ratios
# ================================================================

class TestGetCapitalRatios:
    @patch("regime_router.calc_strategy_fitness")
    def test_basic(self, mock_fitness, _tmp_routing):
        mock_fitness.return_value = {
            "auction": {"fitness": 0.5, "win_rate": 50, "samples": 20, "regime": "neutral"},
            "breakout": {"fitness": 0.8, "win_rate": 65, "samples": 30, "regime": "neutral"},
            "dip_buy": {"fitness": 0.3, "win_rate": 30, "samples": 15, "regime": "neutral"},
        }
        ratios = rr.get_capital_ratios()
        assert isinstance(ratios, dict)
        assert abs(sum(ratios.values()) - 1.0) < 0.01  # 归一化
        # breakout 适应度最高 → 比例最大
        assert ratios.get("breakout", 0) >= ratios.get("dip_buy", 0)

    @patch("regime_router.calc_strategy_fitness")
    def test_clamp(self, mock_fitness, _tmp_routing):
        """min/max ratio 限制"""
        mock_fitness.return_value = {
            "auction": {"fitness": 0.01, "win_rate": 1, "samples": 5, "regime": "bear"},
            "breakout": {"fitness": 0.99, "win_rate": 99, "samples": 50, "regime": "bear"},
        }
        ratios = rr.get_capital_ratios()
        for v in ratios.values():
            assert v >= 0.04  # close to min_ratio after normalization
            assert v <= 1.0

    def test_disabled(self, monkeypatch):
        """禁用时等权"""
        monkeypatch.setattr(rr, "REGIME_ROUTER_PARAMS", {"enabled": False})
        ratios = rr.get_capital_ratios()
        n = len(rr._STRATEGY_NAME_MAP)
        expected = round(1.0 / n, 4)
        for v in ratios.values():
            assert abs(v - expected) < 0.01


# ================================================================
#  should_skip_strategy
# ================================================================

class TestShouldSkipStrategy:
    def test_no_routing(self, _tmp_routing):
        """路由未运行 → 不跳过"""
        assert rr.should_skip_strategy("放量突破选股") is False

    @patch("regime_router._load_today_routing")
    def test_skip_low_ratio(self, mock_load):
        mock_load.return_value = {
            "date": date.today().isoformat(),
            "ratios": {"breakout": 0.02, "dip_buy": 0.15},
        }
        assert rr.should_skip_strategy("放量突破选股") is True
        assert rr.should_skip_strategy("低吸回调选股") is False

    @patch("regime_router._load_today_routing")
    def test_unknown_strategy(self, mock_load):
        """未知策略不跳过"""
        mock_load.return_value = {
            "date": date.today().isoformat(),
            "ratios": {"breakout": 0.15},
        }
        assert rr.should_skip_strategy("未知策略") is False

    def test_disabled(self, monkeypatch):
        """禁用时不跳过"""
        monkeypatch.setattr(rr, "REGIME_ROUTER_PARAMS", {"enabled": False})
        assert rr.should_skip_strategy("放量突破选股") is False


# ================================================================
#  get_position_scale
# ================================================================

class TestGetPositionScale:
    @patch("regime_router._load_today_routing")
    def test_high_ratio(self, mock_load):
        """高 ratio → scale > 1"""
        # 9个策略, avg = 1/9 ≈ 0.111, breakout=0.25 → scale≈2.25 (clamped to 2.0)
        ratios = {k: 0.08 for k in rr._STRATEGY_NAME_MAP.values()}
        ratios["breakout"] = 0.25
        mock_load.return_value = {
            "date": date.today().isoformat(),
            "ratios": ratios,
        }
        scale = rr.get_position_scale("放量突破选股")
        assert scale > 1.0

    @patch("regime_router._load_today_routing")
    def test_low_ratio(self, mock_load):
        """低 ratio → scale < 1"""
        ratios = {k: 0.15 for k in rr._STRATEGY_NAME_MAP.values()}
        ratios["breakout"] = 0.06
        mock_load.return_value = {
            "date": date.today().isoformat(),
            "ratios": ratios,
        }
        scale = rr.get_position_scale("放量突破选股")
        assert scale < 1.0

    def test_disabled(self, monkeypatch):
        """禁用返回 1.0"""
        monkeypatch.setattr(rr, "REGIME_ROUTER_PARAMS", {"enabled": False})
        assert rr.get_position_scale("放量突破选股") == 1.0

    def test_no_routing(self, _tmp_routing):
        """无路由数据返回 1.0"""
        assert rr.get_position_scale("放量突破选股") == 1.0


# ================================================================
#  get_routing_status
# ================================================================

class TestGetRoutingStatus:
    def test_not_calculated(self, _tmp_routing):
        status = rr.get_routing_status()
        assert status["status"] == "not_calculated"

    @patch("regime_router.calc_strategy_fitness")
    def test_after_calc(self, mock_fitness, _tmp_routing):
        mock_fitness.return_value = {
            "auction": {"fitness": 0.5, "win_rate": 50, "samples": 20, "regime": "neutral"},
            "breakout": {"fitness": 0.6, "win_rate": 60, "samples": 25, "regime": "neutral"},
        }
        rr.get_capital_ratios()
        status = rr.get_routing_status()
        assert status["status"] == "active"
        assert "strategies" in status
