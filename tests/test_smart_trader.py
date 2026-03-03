"""
smart_trader.py 单元测试
"""

import sys
import os
import numpy as np
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from smart_trader import (
    calc_atr,
    calc_adaptive_stop,
    calc_trailing_stop,
    check_partial_exit,
    calc_backtest_entry_price,
    simulate_backtest_trade,
    calc_dynamic_sizing,
    detect_market_regime_backtest,
    detect_market_regime,
    _regime_cache,
    # v2.0 新增
    _signal_ma_trend,
    _signal_momentum,
    _signal_volatility,
    _signal_index_rsi,
    _signal_advance_decline,
    _signal_limit_ratio,
    _signal_northbound,
    _signal_margin_trend,
    _fetch_market_breadth,
    _compute_regime_score,
    _score_to_regime,
    get_regime_params,
)


# ================================================================
#  calc_atr
# ================================================================

class TestCalcATR:
    def test_normal(self):
        np.random.seed(42)
        n = 30
        closes = 10.0 + np.cumsum(np.random.randn(n) * 0.1)
        highs = closes + np.abs(np.random.randn(n) * 0.05)
        lows = closes - np.abs(np.random.randn(n) * 0.05)
        atr = calc_atr(highs, lows, closes, period=14)
        assert not np.isnan(atr)
        assert atr > 0

    def test_insufficient_data(self):
        highs = np.array([10.5, 10.6])
        lows = np.array([9.5, 9.4])
        closes = np.array([10.0, 10.1])
        atr = calc_atr(highs, lows, closes, period=14)
        assert np.isnan(atr)

    def test_known_values(self):
        # 简单验证: 固定差值的 ATR
        n = 20
        closes = np.full(n, 10.0)
        highs = np.full(n, 10.5)
        lows = np.full(n, 9.5)
        atr = calc_atr(highs, lows, closes, period=14)
        assert abs(atr - 1.0) < 0.01  # H-L = 1.0, |H-C| = 0.5, |L-C| = 0.5, TR = 1.0


# ================================================================
#  calc_adaptive_stop
# ================================================================

class TestAdaptiveStop:
    def test_normal(self):
        stop = calc_adaptive_stop(entry_price=10.0, atr=0.3)
        # stop = 10 - 1.5*0.3 = 9.55, pct = -4.5%, 在 [-5%, -2%] 内
        assert stop == pytest.approx(9.55, abs=0.01)

    def test_high_volatility_clamp(self):
        # ATR 很大, 应 clamp 到 max_stop_pct (-5%)
        stop = calc_adaptive_stop(entry_price=10.0, atr=1.0)
        # raw: 10 - 1.5 = 8.5, pct = -15%, 被 clamp 到 -5%
        assert stop == pytest.approx(9.5, abs=0.01)

    def test_low_volatility_clamp(self):
        # ATR 很小, 应 clamp 到 min_stop_pct (-2%)
        stop = calc_adaptive_stop(entry_price=10.0, atr=0.05)
        # raw: 10 - 0.075 = 9.925, pct = -0.75%, 被 clamp 到 -2%
        assert stop == pytest.approx(9.8, abs=0.01)

    def test_nan_atr_fallback(self):
        stop = calc_adaptive_stop(entry_price=10.0, atr=float("nan"))
        # 回退到 fallback_stop_pct = -3%
        assert stop == pytest.approx(9.7, abs=0.01)

    def test_zero_atr_fallback(self):
        stop = calc_adaptive_stop(entry_price=10.0, atr=0)
        assert stop == pytest.approx(9.7, abs=0.01)


# ================================================================
#  calc_trailing_stop
# ================================================================

class TestTrailingStop:
    def test_not_activated(self):
        # 盈利 < 2%, 未激活
        result = calc_trailing_stop(
            entry_price=10.0, highest_since_entry=10.15, current_price=10.1
        )
        assert result["trailing_active"] is False
        assert result["should_exit"] is False

    def test_activated_not_triggered(self):
        # 盈利 3%, 已激活; 当前价还在追踪线上方
        result = calc_trailing_stop(
            entry_price=10.0, highest_since_entry=10.3, current_price=10.2
        )
        assert result["trailing_active"] is True
        # trail_stop = 10.3 * (1 - 0.015) = 10.1455
        assert result["trail_stop_price"] == pytest.approx(10.1455, abs=0.01)
        assert result["should_exit"] is False

    def test_activated_and_triggered(self):
        # 最高 +3%, 当前跌到 trail_stop 下方
        result = calc_trailing_stop(
            entry_price=10.0, highest_since_entry=10.3, current_price=10.1
        )
        assert result["trailing_active"] is True
        assert result["should_exit"] is True
        assert result["exit_reason"] == "追踪止盈"

    def test_fixed_target_hit(self):
        # 未激活追踪, 但触及固定止盈 5%
        result = calc_trailing_stop(
            entry_price=10.0, highest_since_entry=10.1, current_price=10.5
        )
        assert result["trailing_active"] is False
        assert result["should_exit"] is True
        assert result["exit_reason"] == "固定止盈"


# ================================================================
#  check_partial_exit
# ================================================================

class TestPartialExit:
    def test_trigger(self):
        result = check_partial_exit(
            entry_price=10.0, current_price=10.35,
            position_info={"partial_exited": False, "remaining_ratio": 1.0}
        )
        assert result["should_partial_exit"] is True
        assert result["exit_ratio"] == 0.5
        assert result["remaining_ratio"] == pytest.approx(0.5)

    def test_already_partial(self):
        result = check_partial_exit(
            entry_price=10.0, current_price=10.5,
            position_info={"partial_exited": True, "remaining_ratio": 0.5}
        )
        assert result["should_partial_exit"] is False
        assert result["remaining_ratio"] == 0.5

    def test_below_threshold(self):
        result = check_partial_exit(
            entry_price=10.0, current_price=10.2,
            position_info={"partial_exited": False, "remaining_ratio": 1.0}
        )
        assert result["should_partial_exit"] is False


# ================================================================
#  calc_backtest_entry_price
# ================================================================

class TestBacktestEntryPrice:
    def test_with_pullback(self):
        # open=10, low=9.85 < 10*(1-0.01)=9.9 → 回撤入场 @9.9
        price, method = calc_backtest_entry_price(
            next_open=10.0, next_high=10.5, next_low=9.85, next_close=10.3, atr=0.3
        )
        assert price == pytest.approx(9.9, abs=0.01)
        assert method == "回撤入场"

    def test_no_pullback(self):
        # open=10, low=9.95 > 9.9 → 无回撤, 用开盘价
        price, method = calc_backtest_entry_price(
            next_open=10.0, next_high=10.5, next_low=9.95, next_close=10.3, atr=0.3
        )
        assert price == pytest.approx(10.0, abs=0.01)
        assert method == "开盘价"


# ================================================================
#  simulate_backtest_trade
# ================================================================

class TestSimulateBacktestTrade:
    def test_stop_loss(self):
        # 次日大幅低开低走 → 触发止损
        result = simulate_backtest_trade(
            entry_price_old=10.0,
            next_open=10.0, next_high=10.05, next_low=9.4, next_close=9.5,
            atr=0.3
        )
        assert result["exit_reason"] == "自适应止损"
        assert result["raw_return"] < 0

    def test_partial_exit(self):
        # 次日高涨到 +3% 以上 → 分批止盈
        result = simulate_backtest_trade(
            entry_price_old=10.0,
            next_open=10.0, next_high=10.35, next_low=9.95, next_close=10.2,
            atr=0.3
        )
        assert result["exit_reason"] == "分批止盈"
        assert result["raw_return"] > 0

    def test_close_exit(self):
        # 正常波动, 不触发任何条件 → 收盘平仓
        result = simulate_backtest_trade(
            entry_price_old=10.0,
            next_open=10.0, next_high=10.15, next_low=9.92, next_close=10.05,
            atr=0.3
        )
        assert result["exit_reason"] == "收盘平仓"

    def test_entry_method_pullback(self):
        # 验证入场方法
        result = simulate_backtest_trade(
            entry_price_old=10.0,
            next_open=10.0, next_high=10.1, next_low=9.85, next_close=10.05,
            atr=0.3
        )
        assert result["entry_method"] == "回撤入场"
        # 入场价应该是 9.9 (10 * 0.99)
        assert result["entry_price"] == pytest.approx(9.9, abs=0.01)


# ================================================================
#  calc_dynamic_sizing
# ================================================================

class TestDynamicSizing:
    def test_score_weighting(self):
        items = [
            {"price": 10.0, "score": 80, "volatility": 0.3},
            {"price": 20.0, "score": 40, "volatility": 0.3},
        ]
        result = calc_dynamic_sizing(100000, items, regime_scale=1.0)
        # 高分股应该分配更多资金
        assert result[0]["suggested_amount"] >= result[1]["suggested_amount"]

    def test_volatility_adjust(self):
        items = [
            {"price": 10.0, "score": 50, "volatility": 0.2},
            {"price": 10.0, "score": 50, "volatility": 0.6},
        ]
        result = calc_dynamic_sizing(100000, items, regime_scale=1.0)
        # 低波动股应该分配更多
        assert result[0]["suggested_shares"] >= result[1]["suggested_shares"]

    def test_regime_scale(self):
        items = [
            {"price": 10.0, "score": 50, "volatility": 0.3},
        ]
        full = calc_dynamic_sizing(100000, items, regime_scale=1.0)
        half = calc_dynamic_sizing(100000, items, regime_scale=0.5)
        assert half[0]["suggested_amount"] <= full[0]["suggested_amount"]

    def test_empty_items(self):
        result = calc_dynamic_sizing(100000, [], regime_scale=1.0)
        assert result == []


# ================================================================
#  v2.0 单信号函数测试
# ================================================================

class TestSignalMATrend:
    def test_strong_uptrend(self):
        closes = np.linspace(90, 110, 80)  # 持续上涨
        score = _signal_ma_trend(closes)
        assert score >= 0.75  # MA5>MA20>MA60, price above all

    def test_downtrend(self):
        closes = np.linspace(110, 90, 80)  # 持续下跌
        score = _signal_ma_trend(closes)
        assert score <= 0.25

    def test_insufficient_data(self):
        closes = np.array([100, 101])
        score = _signal_ma_trend(closes)
        assert score == 0.5


class TestSignalMomentum:
    def test_positive_momentum(self):
        closes = np.linspace(100, 108, 25)  # ~8% rise in 25 days
        score = _signal_momentum(closes)
        assert score > 0.6

    def test_negative_momentum(self):
        closes = np.linspace(108, 100, 25)  # ~8% drop in 25 days
        score = _signal_momentum(closes)
        assert score < 0.4

    def test_insufficient_data(self):
        closes = np.array([100, 101])
        score = _signal_momentum(closes)
        assert score == 0.5


class TestSignalVolatility:
    def test_low_volatility(self):
        # Very stable prices → high score
        np.random.seed(42)
        closes = 100 + np.cumsum(np.random.randn(25) * 0.1)
        score = _signal_volatility(closes)
        assert score > 0.7

    def test_high_volatility(self):
        # Wild swings → low score
        np.random.seed(42)
        closes = 100 + np.cumsum(np.random.randn(25) * 3.0)
        score = _signal_volatility(closes)
        assert score < 0.5

    def test_insufficient_data(self):
        closes = np.array([100, 101])
        score = _signal_volatility(closes)
        assert score == 0.5


class TestSignalIndexRSI:
    def test_overbought(self):
        # Consistent rises → high RSI
        closes = np.linspace(100, 115, 20)
        score = _signal_index_rsi(closes)
        assert score > 0.7

    def test_oversold(self):
        # Consistent drops → low RSI
        closes = np.linspace(115, 100, 20)
        score = _signal_index_rsi(closes)
        assert score < 0.3

    def test_insufficient_data(self):
        closes = np.array([100])
        score = _signal_index_rsi(closes)
        assert score == 0.5


# ================================================================
#  v2.0 合成评分 + Regime 参数
# ================================================================

class TestCompositeScoring:
    def test_all_bullish(self):
        signals = {f"s{i}": 1.0 for i in range(1, 9)}
        score = _compute_regime_score(
            {"s1_ma_trend": 1.0, "s2_momentum": 1.0, "s3_volatility": 1.0,
             "s4_advance_decline": 1.0, "s5_limit_ratio": 1.0,
             "s6_northbound": 1.0, "s7_margin_trend": 1.0, "s8_index_rsi": 1.0},
            {"s1_ma_trend": 0.15, "s2_momentum": 0.15, "s3_volatility": 0.10,
             "s4_advance_decline": 0.15, "s5_limit_ratio": 0.10,
             "s6_northbound": 0.10, "s7_margin_trend": 0.10, "s8_index_rsi": 0.15},
        )
        assert score == pytest.approx(1.0, abs=0.01)

    def test_all_bearish(self):
        signals = {
            "s1_ma_trend": 0.0, "s2_momentum": 0.0, "s3_volatility": 0.0,
            "s4_advance_decline": 0.0, "s5_limit_ratio": 0.0,
            "s6_northbound": 0.0, "s7_margin_trend": 0.0, "s8_index_rsi": 0.0,
        }
        weights = {
            "s1_ma_trend": 0.15, "s2_momentum": 0.15, "s3_volatility": 0.10,
            "s4_advance_decline": 0.15, "s5_limit_ratio": 0.10,
            "s6_northbound": 0.10, "s7_margin_trend": 0.10, "s8_index_rsi": 0.15,
        }
        score = _compute_regime_score(signals, weights)
        assert score == pytest.approx(0.0, abs=0.01)

    def test_mixed_neutral(self):
        signals = {
            "s1_ma_trend": 0.5, "s2_momentum": 0.5, "s3_volatility": 0.5,
            "s8_index_rsi": 0.5,
        }
        weights = {"s1_ma_trend": 0.15, "s2_momentum": 0.15,
                   "s3_volatility": 0.10, "s8_index_rsi": 0.15}
        score = _compute_regime_score(signals, weights)
        assert score == pytest.approx(0.5, abs=0.01)

    def test_auto_normalize(self):
        # Backtest weights don't sum to 1.0, should auto-normalize
        signals = {"s1_ma_trend": 1.0, "s2_momentum": 1.0,
                   "s3_volatility": 1.0, "s8_index_rsi": 1.0}
        weights = {"s1_ma_trend": 0.15, "s2_momentum": 0.15,
                   "s3_volatility": 0.10, "s8_index_rsi": 0.15}
        score = _compute_regime_score(signals, weights)
        assert score == pytest.approx(1.0, abs=0.01)


class TestScoreToRegime:
    def test_bull(self):
        assert _score_to_regime(0.70) == "bull"
        assert _score_to_regime(0.65) == "bull"

    def test_neutral(self):
        assert _score_to_regime(0.50) == "neutral"
        assert _score_to_regime(0.45) == "neutral"

    def test_weak(self):
        assert _score_to_regime(0.35) == "weak"
        assert _score_to_regime(0.30) == "weak"

    def test_bear(self):
        assert _score_to_regime(0.25) == "bear"
        assert _score_to_regime(0.0) == "bear"


class TestGetRegimeParams:
    def test_bull_params(self):
        rp = get_regime_params("bull")
        assert rp["position_scale"] == 1.2
        assert rp["max_positions"] == 9

    def test_bear_params(self):
        rp = get_regime_params("bear")
        assert rp["position_scale"] == 0.0
        assert rp["max_positions"] == 0

    def test_unknown_fallback(self):
        rp = get_regime_params("unknown")
        assert rp["position_scale"] == 0.8  # neutral default


# ================================================================
#  detect_market_regime_backtest (v2.0 — 4信号)
# ================================================================

class TestDetectMarketRegimeBacktest:
    def test_bull(self):
        closes = np.linspace(100, 115, 80)  # 持续上涨
        result = detect_market_regime_backtest(closes, idx=79)
        assert result["regime"] == "bull"
        assert result["position_scale"] == 1.2
        assert "score" in result
        assert result["score"] >= 0.65

    def test_bear(self):
        # 暴跌趋势
        closes = np.linspace(120, 85, 80)  # 持续下跌
        result = detect_market_regime_backtest(closes, idx=79)
        assert result["regime"] == "bear"
        assert result["position_scale"] == 0.0
        assert result["should_trade"] is False

    def test_insufficient_data(self):
        closes = np.array([100, 101, 102])
        result = detect_market_regime_backtest(closes, idx=2)
        assert result["regime"] == "neutral"
        assert result["position_scale"] == 0.8

    def test_has_regime_params(self):
        closes = np.linspace(100, 110, 80)
        result = detect_market_regime_backtest(closes, idx=79)
        assert "regime_params" in result
        rp = result["regime_params"]
        assert "atr_multiplier" in rp
        assert "trail_pct" in rp

    def test_signals_returned(self):
        closes = np.linspace(100, 110, 80)
        result = detect_market_regime_backtest(closes, idx=79)
        assert "signals" in result
        assert "s1_ma_trend" in result["signals"]
        assert "s8_index_rsi" in result["signals"]


# ================================================================
#  API 信号 mock 测试 (S4/S5/S6/S7 + 端到端)
# ================================================================

import pandas as pd


class TestSignalAdvanceDecline:
    def test_bullish_market(self):
        """多数上涨 → 高分"""
        vals = pd.Series([2.0] * 3000 + [-1.0] * 1000)  # 3:1 ratio
        score = _signal_advance_decline(vals)
        assert score > 0.7

    def test_bearish_market(self):
        """多数下跌 → 低分"""
        vals = pd.Series([-2.0] * 3000 + [1.0] * 1000)
        score = _signal_advance_decline(vals)
        assert score < 0.3

    def test_none_input(self):
        """无数据 → 中性"""
        score = _signal_advance_decline(None)
        assert score == 0.5


class TestSignalLimitRatio:
    def test_more_limit_up(self):
        """涨停多于跌停 → 高分"""
        vals = pd.Series([10.0] * 50 + [-10.0] * 10 + [1.0] * 4000)
        score = _signal_limit_ratio(vals)
        assert score > 0.7

    def test_more_limit_down(self):
        """跌停多于涨停 → 低分"""
        vals = pd.Series([-10.0] * 50 + [10.0] * 10 + [1.0] * 4000)
        score = _signal_limit_ratio(vals)
        assert score < 0.3

    def test_none_input(self):
        """无数据 → 中性"""
        score = _signal_limit_ratio(None)
        assert score == 0.5


class TestSignalNorthbound:
    def test_strong_inflow(self):
        """5日净流入 150亿 → 满分"""
        mock_ak = MagicMock()
        df = pd.DataFrame({"日期": pd.date_range("2026-02-20", periods=10),
                           "当日净流入": [10, 10, 10, 10, 10, 30, 30, 30, 30, 30]})
        mock_ak.stock_hsgt_north_net_flow_in_em.return_value = df
        with patch.dict("sys.modules", {"akshare": mock_ak}):
            score = _signal_northbound()
        assert score == pytest.approx(1.0, abs=0.01)

    def test_strong_outflow(self):
        """5日净流出 150亿 → 0分"""
        mock_ak = MagicMock()
        df = pd.DataFrame({"日期": pd.date_range("2026-02-20", periods=10),
                           "当日净流入": [-10, -10, -10, -10, -10, -30, -30, -30, -30, -30]})
        mock_ak.stock_hsgt_north_net_flow_in_em.return_value = df
        with patch.dict("sys.modules", {"akshare": mock_ak}):
            score = _signal_northbound()
        assert score == pytest.approx(0.0, abs=0.01)

    def test_neutral_flow(self):
        """5日净流入 0 → 0.5"""
        mock_ak = MagicMock()
        df = pd.DataFrame({"日期": pd.date_range("2026-02-20", periods=10),
                           "当日净流入": [10, -10, 10, -10, 10, 10, -10, 10, -10, 0]})
        mock_ak.stock_hsgt_north_net_flow_in_em.return_value = df
        with patch.dict("sys.modules", {"akshare": mock_ak}):
            score = _signal_northbound()
        assert score == pytest.approx(0.5, abs=0.01)


class TestSignalMarginTrend:
    def test_margin_increase(self):
        """融资余额增长 ≥3% → 满分"""
        mock_ak = MagicMock()
        base = 10000
        # vals[-6]=base, vals[-1]=base*1.03 → chg=+3%
        df = pd.DataFrame({
            "日期": pd.date_range("2026-02-20", periods=10),
            "融资余额": [base * 0.98] * 4 + [base] * 1 + [base * 1.005] * 2 + [base * 1.01] + [base * 1.02, base * 1.03],
        })
        mock_ak.stock_margin_sse.return_value = df
        with patch.dict("sys.modules", {"akshare": mock_ak}):
            score = _signal_margin_trend()
        assert score >= 0.95

    def test_margin_decrease(self):
        """融资余额下降 ≥3% → 接近0分"""
        mock_ak = MagicMock()
        base = 10000
        # vals[-6]=base, vals[-1]=base*0.97 → chg=-3%
        df = pd.DataFrame({
            "日期": pd.date_range("2026-02-20", periods=10),
            "融资余额": [base * 1.02] * 4 + [base] * 1 + [base * 0.995] * 2 + [base * 0.99] + [base * 0.98, base * 0.97],
        })
        mock_ak.stock_margin_sse.return_value = df
        with patch.dict("sys.modules", {"akshare": mock_ak}):
            score = _signal_margin_trend()
        assert score <= 0.05


class TestDetectMarketRegimeFull:
    """端到端: mock 全部 API, 测完整评分流程"""

    def test_full_bull_regime(self):
        """所有信号看多 → bull"""
        _regime_cache.clear()
        mock_ak = MagicMock()

        # Mock index history (strong uptrend)
        dates = pd.date_range("2025-11-01", periods=80)
        closes_arr = np.linspace(4000, 4600, 80)
        index_df = pd.DataFrame({
            "日期": dates,
            "开盘": closes_arr - 10,
            "最高": closes_arr + 20,
            "最低": closes_arr - 20,
            "收盘": closes_arr,
            "成交量": [1e8] * 80,
        })
        mock_ak.index_zh_a_hist.return_value = index_df

        # Mock breadth (strong bull)
        breadth_vals = pd.Series([3.0] * 3500 + [-1.0] * 500)
        mock_ak.stock_zh_a_spot_em.return_value = pd.DataFrame({"涨跌幅": breadth_vals})

        # Mock northbound (strong inflow)
        north_df = pd.DataFrame({
            "日期": pd.date_range("2026-02-20", periods=10),
            "当日净流入": [30] * 10,
        })
        mock_ak.stock_hsgt_north_net_flow_in_em.return_value = north_df

        # Mock margin (increasing)
        base = 10000
        margin_df = pd.DataFrame({
            "日期": pd.date_range("2026-02-20", periods=10),
            "融资余额": [base * (1 + 0.004 * i) for i in range(10)],
        })
        mock_ak.stock_margin_sse.return_value = margin_df

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            result = detect_market_regime()
        assert result["regime"] == "bull"
        assert result["score"] >= 0.65
        assert result["should_trade"] is True
        assert result["position_scale"] == 1.2
        assert len(result["signals"]) == 8

    def test_full_bear_regime(self):
        """所有信号看空 → bear"""
        _regime_cache.clear()
        mock_ak = MagicMock()

        # Mock index history (strong downtrend)
        dates = pd.date_range("2025-11-01", periods=80)
        closes_arr = np.linspace(5000, 3800, 80)
        index_df = pd.DataFrame({
            "日期": dates,
            "开盘": closes_arr + 10,
            "最高": closes_arr + 20,
            "最低": closes_arr - 20,
            "收盘": closes_arr,
            "成交量": [1e8] * 80,
        })
        mock_ak.index_zh_a_hist.return_value = index_df

        # Mock breadth (strong bear)
        breadth_vals = pd.Series([-3.0] * 3500 + [1.0] * 500)
        mock_ak.stock_zh_a_spot_em.return_value = pd.DataFrame({"涨跌幅": breadth_vals})

        # Mock northbound (strong outflow)
        north_df = pd.DataFrame({
            "日期": pd.date_range("2026-02-20", periods=10),
            "当日净流入": [-30] * 10,
        })
        mock_ak.stock_hsgt_north_net_flow_in_em.return_value = north_df

        # Mock margin (decreasing)
        base = 10000
        margin_df = pd.DataFrame({
            "日期": pd.date_range("2026-02-20", periods=10),
            "融资余额": [base * (1 - 0.004 * i) for i in range(10)],
        })
        mock_ak.stock_margin_sse.return_value = margin_df

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            result = detect_market_regime()
        assert result["regime"] == "bear"
        assert result["score"] < 0.30
        assert result["should_trade"] is False
        assert result["position_scale"] == 0.0

    def test_api_failure_fallback(self):
        """API 全部异常 → neutral 回退"""
        _regime_cache.clear()
        mock_ak = MagicMock()
        mock_ak.index_zh_a_hist.side_effect = Exception("network error")

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            result = detect_market_regime()
        assert result["regime"] == "neutral"
        assert result["should_trade"] is True
        assert "error" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
