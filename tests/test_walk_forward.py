"""walk_forward.py 单元测试"""

import os
import sys
import json
import types
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestGenerateGrid:
    """参数网格生成"""

    def test_empty_weights(self):
        from walk_forward import _generate_grid
        assert _generate_grid({}) == []

    def test_grid_size(self):
        from walk_forward import _generate_grid
        weights = {"a": 0.3, "b": 0.3, "c": 0.4}
        grid = _generate_grid(weights, grid_size=5)
        assert len(grid) == 6  # 5 + 1 baseline

    def test_baseline_is_first(self):
        from walk_forward import _generate_grid
        weights = {"a": 0.3, "b": 0.3, "c": 0.4}
        grid = _generate_grid(weights, grid_size=3)
        # baseline 应该接近原始权重
        for k, v in weights.items():
            assert abs(grid[0][k] - v) < 0.01

    def test_all_positive(self):
        from walk_forward import _generate_grid
        weights = {"a": 0.5, "b": 0.5}
        grid = _generate_grid(weights, grid_size=10, delta=0.3)
        for params in grid:
            for v in params.values():
                assert v > 0

    def test_normalized(self):
        from walk_forward import _generate_grid
        weights = {"a": 0.3, "b": 0.3, "c": 0.4}
        grid = _generate_grid(weights, grid_size=5)
        for params in grid[1:]:  # 跳过 baseline (非归一化)
            total = sum(params.values())
            assert abs(total - 1.0) < 0.01


class TestBacktestWindow:
    """单窗口回测"""

    def _make_kline_map(self, n_days=100, n_stocks=5):
        """生成模拟K线数据"""
        dates = [(datetime(2025, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
                 for i in range(n_days)]
        kline_map = {}
        rng = np.random.RandomState(42)
        for i in range(n_stocks):
            code = f"{600000 + i:06d}"
            base_price = 10 + rng.random() * 40
            closes = [base_price]
            for _ in range(n_days - 1):
                closes.append(closes[-1] * (1 + rng.normal(0, 0.02)))
            closes = np.array(closes)
            highs = closes * (1 + rng.uniform(0, 0.03, n_days))
            lows = closes * (1 - rng.uniform(0, 0.03, n_days))
            opens = closes * (1 + rng.normal(0, 0.01, n_days))
            volumes = rng.uniform(1e6, 1e7, n_days)

            df = pd.DataFrame({
                "date": dates,
                "open": opens,
                "close": closes,
                "high": highs,
                "low": lows,
                "volume": volumes,
            })
            kline_map[code] = df
        return kline_map

    @patch("backtest.SMART_TRADE_ENABLED", False)
    def test_window_returns_dict(self):
        from walk_forward import _backtest_window
        kline_map = self._make_kline_map()
        result = _backtest_window(
            kline_map, "breakout", "2025-01-20", "2025-03-01")
        assert isinstance(result, dict)
        assert "total_trades" in result
        assert "win_rate" in result

    @patch("backtest.SMART_TRADE_ENABLED", False)
    def test_empty_range(self):
        from walk_forward import _backtest_window
        kline_map = self._make_kline_map()
        result = _backtest_window(
            kline_map, "breakout", "2099-01-01", "2099-12-31")
        assert result["total_trades"] == 0


class TestWFSummary:
    """Walk-Forward 汇总计算"""

    def test_calc_summary(self):
        from walk_forward import _calc_wf_summary
        windows = [
            {
                "is_stats": {"total_trades": 20, "win_rate": 60, "avg_return": 0.5, "sharpe": 1.2},
                "oos_stats": {"total_trades": 10, "win_rate": 50, "avg_return": 0.3, "sharpe": 0.8},
            },
            {
                "is_stats": {"total_trades": 20, "win_rate": 55, "avg_return": 0.4, "sharpe": 1.0},
                "oos_stats": {"total_trades": 10, "win_rate": 48, "avg_return": 0.2, "sharpe": 0.6},
            },
        ]
        summary = _calc_wf_summary(windows)
        assert "oos_efficiency" in summary
        assert "oos_degradation" in summary
        assert "overfitting_risk" in summary
        assert summary["avg_is_win_rate"] > summary["avg_oos_win_rate"]

    def test_efficiency_positive(self):
        from walk_forward import _calc_wf_summary
        windows = [
            {
                "is_stats": {"total_trades": 20, "win_rate": 60, "avg_return": 1.0, "sharpe": 1.5},
                "oos_stats": {"total_trades": 10, "win_rate": 58, "avg_return": 0.8, "sharpe": 1.2},
            },
        ]
        summary = _calc_wf_summary(windows)
        assert summary["oos_efficiency"] > 0
        assert summary["oos_efficiency"] <= 1.0
        assert summary["overfitting_risk"] == "low"

    def test_high_overfitting(self):
        from walk_forward import _calc_wf_summary
        windows = [
            {
                "is_stats": {"total_trades": 20, "win_rate": 80, "avg_return": 2.0, "sharpe": 2.0},
                "oos_stats": {"total_trades": 10, "win_rate": 40, "avg_return": -0.5, "sharpe": -0.2},
            },
        ]
        summary = _calc_wf_summary(windows)
        assert summary["overfitting_risk"] == "high"
        assert summary["oos_degradation"] > 0.3

    def test_empty_windows(self):
        from walk_forward import _calc_wf_summary
        summary = _calc_wf_summary([])
        assert "error" in summary


class TestWFReport:
    """报告生成"""

    def test_report_format(self):
        from walk_forward import generate_wf_report
        result = {
            "strategy": "breakout",
            "timestamp": "2026-03-02T22:00:00",
            "n_windows": 2,
            "params": {"train_days": 120, "test_days": 30},
            "windows": [
                {
                    "window": 1,
                    "train_period": "2025-09-01~2025-12-31",
                    "test_period": "2026-01-01~2026-01-31",
                    "is_stats": {"win_rate": 60, "avg_return": 0.5, "total_trades": 20},
                    "oos_stats": {"win_rate": 50, "avg_return": 0.3, "total_trades": 10},
                },
            ],
            "summary": {
                "avg_is_win_rate": 60, "avg_oos_win_rate": 50,
                "avg_is_return": 0.5, "avg_oos_return": 0.3,
                "avg_is_sharpe": 1.2, "avg_oos_sharpe": 0.8,
                "oos_efficiency": 0.6, "oos_degradation": 0.167,
                "sharpe_decay": 0.333, "oos_return_std": 0.1,
                "overfitting_risk": "low", "valid_windows": 2,
            },
        }
        report = generate_wf_report(result)
        assert "Walk-Forward" in report
        assert "breakout" in report
        assert "OOS Efficiency" in report
        assert "过拟合风险" in report

    def test_report_error(self):
        from walk_forward import generate_wf_report
        result = {
            "strategy": "test",
            "timestamp": "2026-01-01",
            "n_windows": 0,
            "params": {},
            "windows": [],
            "summary": {"error": "no data"},
        }
        report = generate_wf_report(result)
        assert "错误" in report


class TestWFPersistence:
    """持久化"""

    def test_save_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr("walk_forward._WF_RESULTS_PATH",
                            str(tmp_path / "wf.json"))
        from walk_forward import _save_wf_results, get_wf_history

        result = {
            "strategy": "breakout",
            "timestamp": datetime.now().isoformat(),
            "summary": {"overfitting_risk": "low"},
        }
        _save_wf_results(result)

        history = get_wf_history("breakout", days=1)
        assert len(history) == 1
        assert history[0]["strategy"] == "breakout"

    def test_latest_risk(self, tmp_path, monkeypatch):
        monkeypatch.setattr("walk_forward._WF_RESULTS_PATH",
                            str(tmp_path / "wf.json"))
        from walk_forward import _save_wf_results, get_latest_overfitting_risk

        _save_wf_results({
            "strategy": "breakout",
            "timestamp": datetime.now().isoformat(),
            "summary": {"overfitting_risk": "medium"},
        })
        assert get_latest_overfitting_risk("breakout") == "medium"
        assert get_latest_overfitting_risk("unknown_strat") == "unknown"


class TestWFDefaults:
    """默认参数"""

    def test_defaults_exist(self):
        from walk_forward import WF_DEFAULTS
        assert WF_DEFAULTS["n_windows"] > 0
        assert WF_DEFAULTS["train_days"] > WF_DEFAULTS["test_days"]
        assert WF_DEFAULTS["step_days"] > 0
