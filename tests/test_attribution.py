"""
收益归因引擎 单元测试
"""

import os
import sys
import pytest
from unittest.mock import patch
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import attribution as attr


# ================================================================
#  Fixtures
# ================================================================

@pytest.fixture(autouse=True)
def _reset_params(monkeypatch):
    monkeypatch.setattr(attr, "ATTRIBUTION_PARAMS", {"enabled": True, "lookback_days": 30})


@pytest.fixture
def mock_scorecard():
    """30天 scorecard 数据"""
    return [
        {"rec_date": "2026-03-01", "code": "000001", "strategy": "放量突破选股",
         "score": 0.8, "net_return_pct": 3.0, "regime": "bull",
         "entry_price": 10.0, "next_low": 9.8},
        {"rec_date": "2026-03-01", "code": "000002", "strategy": "放量突破选股",
         "score": 0.6, "net_return_pct": -1.5, "regime": "bull",
         "entry_price": 20.0, "next_low": 19.5},
        {"rec_date": "2026-03-02", "code": "000003", "strategy": "低吸回调选股",
         "score": 0.7, "net_return_pct": 2.0, "regime": "neutral",
         "entry_price": 15.0, "next_low": 14.7},
        {"rec_date": "2026-03-02", "code": "000004", "strategy": "尾盘短线选股",
         "score": 0.5, "net_return_pct": -2.0, "regime": "neutral",
         "entry_price": 12.0, "next_low": 11.5},
        {"rec_date": "2026-03-03", "code": "000005", "strategy": "趋势跟踪选股",
         "score": 0.9, "net_return_pct": 5.0, "regime": "bull",
         "entry_price": 25.0, "next_low": 24.8},
        {"rec_date": "2026-03-03", "code": "000006", "strategy": "集合竞价选股",
         "score": 0.4, "net_return_pct": -0.5, "regime": "weak",
         "entry_price": 8.0, "next_low": 7.6},
    ]


# ================================================================
#  calc_strategy_pnl
# ================================================================

class TestCalcStrategyPnl:
    @patch("attribution._load_scorecard")
    def test_basic(self, mock_load, mock_scorecard):
        mock_load.return_value = mock_scorecard
        result = attr.calc_strategy_pnl(30)
        assert len(result) >= 1
        # 放量突破: 3.0 + (-1.5) = 1.5
        breakout = next((r for r in result if r["strategy"] == "放量突破选股"), None)
        assert breakout is not None
        assert breakout["total_pnl"] == 1.5
        assert breakout["n_signals"] == 2
        assert breakout["win_rate"] == 50.0

    @patch("attribution._load_scorecard", return_value=[])
    def test_empty(self, mock_load):
        result = attr.calc_strategy_pnl(30)
        assert result == []

    @patch("attribution._load_scorecard")
    def test_sharpe(self, mock_load, mock_scorecard):
        mock_load.return_value = mock_scorecard
        result = attr.calc_strategy_pnl(30)
        for r in result:
            assert "sharpe" in r


# ================================================================
#  calc_factor_contribution
# ================================================================

class TestCalcFactorContribution:
    @patch("signal_tracker.get_factor_effectiveness")
    def test_basic(self, mock_factors):
        mock_factors.return_value = {
            "s_volume_breakout": {"spread": 0.15, "predictive": True},
            "s_ma_alignment": {"spread": 0.10, "predictive": True},
            "s_rsi": {"spread": -0.05, "predictive": False},
        }
        result = attr.calc_factor_contribution(30)
        assert len(result) == 3
        # 排序: contribution 从大到小 (受 tunable_params 权重影响)
        assert result[0]["contribution"] >= result[1]["contribution"]
        assert result[0]["contribution"] > 0

    @patch("signal_tracker.get_factor_effectiveness", return_value={})
    def test_empty(self, mock_factors):
        result = attr.calc_factor_contribution(30)
        assert result == []


# ================================================================
#  calc_regime_pnl
# ================================================================

class TestCalcRegimePnl:
    @patch("attribution._load_scorecard")
    def test_basic(self, mock_load, mock_scorecard):
        mock_load.return_value = mock_scorecard
        result = attr.calc_regime_pnl(30)
        assert len(result) >= 1
        regimes = {r["regime"] for r in result}
        assert "bull" in regimes


# ================================================================
#  calc_timing_pnl
# ================================================================

class TestCalcTimingPnl:
    @patch("attribution._load_scorecard")
    def test_basic(self, mock_load, mock_scorecard):
        mock_load.return_value = mock_scorecard
        result = attr.calc_timing_pnl(30)
        assert len(result) >= 1
        slots = {r["slot"] for r in result}
        # 放量突破→midday, 低吸→midday, 尾盘→afternoon, 趋势→midday, 竞价→morning
        assert "midday" in slots

    @patch("attribution._load_scorecard", return_value=[])
    def test_empty(self, mock_load):
        result = attr.calc_timing_pnl(30)
        assert result == []


# ================================================================
#  calc_score_band_pnl
# ================================================================

class TestCalcScoreBandPnl:
    @patch("attribution._load_scorecard")
    def test_basic(self, mock_load, mock_scorecard):
        mock_load.return_value = mock_scorecard
        result = attr.calc_score_band_pnl(30)
        # 至少有 high/mid/low 之一
        assert len(result) >= 1
        bands = {r["band"] for r in result}
        assert len(bands) >= 1


# ================================================================
#  run_full_attribution
# ================================================================

class TestRunFullAttribution:
    @patch("attribution._load_scorecard")
    @patch("signal_tracker.get_factor_effectiveness")
    def test_basic(self, mock_factors, mock_load, mock_scorecard):
        mock_load.return_value = mock_scorecard
        mock_factors.return_value = {
            "s_volume": {"spread": 0.1, "predictive": True},
        }
        result = attr.run_full_attribution(30)
        assert "strategy" in result
        assert "factor" in result
        assert "regime" in result
        assert "timing" in result
        assert "score_band" in result
        assert "alpha_sources" in result
        assert "alpha_drains" in result

    @patch("attribution._load_scorecard", return_value=[])
    @patch("signal_tracker.get_factor_effectiveness", return_value={})
    def test_empty(self, mock_factors, mock_load):
        result = attr.run_full_attribution(30)
        assert result["strategy"] == []


# ================================================================
#  format_attribution_report
# ================================================================

class TestFormatReport:
    def test_format(self):
        result = {
            "days": 30,
            "alpha_sources": ["放量突破 +5.0%"],
            "alpha_drains": ["尾盘短线选股 -3.0%"],
            "strategy": [{"strategy": "放量突破选股", "total_pnl": 5.0,
                          "win_rate": 60, "sharpe": 1.2}],
            "regime": [{"regime": "bull", "total_pnl": 3.0, "n_signals": 10}],
            "score_band": [{"band": "high", "win_rate": 65, "avg_return": 2.0}],
        }
        report = attr.format_attribution_report(result)
        assert "Alpha来源" in report
        assert "Alpha流失" in report
        assert "策略排行" in report
