"""
开盘前作战计划测试
"""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from morning_prep import (
    _collect_cross_market,
    _collect_futures_positions,
    _collect_agent_insights,
    _collect_learning_summary,
    _collect_strategy_health,
    generate_morning_plan,
    run_morning_prep,
)


# ================================================================
#  测试: 数据收集 (各收集器独立容错)
# ================================================================

class TestCollectors:
    def test_cross_market_fail_safe(self):
        # 没有真实数据时应返回 None 而不是异常
        result = _collect_cross_market()
        # 可能返回数据也可能返回None, 不应抛异常
        assert result is None or isinstance(result, dict)

    def test_futures_fail_safe(self):
        result = _collect_futures_positions()
        assert result is None or isinstance(result, dict)

    def test_insights_fail_safe(self):
        result = _collect_agent_insights()
        assert isinstance(result, list)

    def test_learning_fail_safe(self):
        result = _collect_learning_summary()
        assert result is None or isinstance(result, dict)

    def test_health_fail_safe(self):
        result = _collect_strategy_health()
        assert isinstance(result, dict)


# ================================================================
#  测试: 作战计划生成
# ================================================================

class TestGeneratePlan:
    @patch("morning_prep._collect_strategy_health")
    @patch("morning_prep._collect_learning_summary")
    @patch("morning_prep._collect_agent_insights")
    @patch("morning_prep._collect_futures_positions")
    @patch("morning_prep._collect_cross_market")
    def test_bullish_plan(self, mock_cm, mock_fut, mock_ins, mock_learn, mock_health):
        mock_cm.return_value = {
            "composite_signal": 0.6, "a_stock_impact": "bullish",
            "us_signal": 0.5, "a50_signal": 0.3, "crypto_signal": 0.4,
            "suggestion": "外围强势", "divergences": [],
        }
        mock_fut.return_value = {"count": 0}
        mock_ins.return_value = []
        mock_learn.return_value = None
        mock_health.return_value = {}

        result = generate_morning_plan()
        assert result["risk_level"] == "low"
        assert "plan_text" in result
        assert "跨市场研判" in result["plan_text"]
        assert "操作要点" in result["plan_text"]

    @patch("morning_prep._collect_strategy_health")
    @patch("morning_prep._collect_learning_summary")
    @patch("morning_prep._collect_agent_insights")
    @patch("morning_prep._collect_futures_positions")
    @patch("morning_prep._collect_cross_market")
    def test_bearish_plan(self, mock_cm, mock_fut, mock_ins, mock_learn, mock_health):
        mock_cm.return_value = {
            "composite_signal": -0.6, "a_stock_impact": "bearish",
            "us_signal": -0.5, "a50_signal": -0.3, "crypto_signal": -0.4,
            "suggestion": "控制仓位", "divergences": [],
        }
        mock_fut.return_value = {"count": 1, "total_margin": 5000, "total_pnl": -2000,
                                  "positions": [{"code": "RB", "name": "螺纹钢",
                                                 "direction": "long", "pnl_pct": -3.5}]}
        mock_ins.return_value = [{"text": "螺纹钢连续亏损"}]
        mock_learn.return_value = None
        mock_health.return_value = {"策略A": {"status": "failed"}}

        result = generate_morning_plan()
        assert result["risk_level"] == "high"
        assert result["risk_factors"] >= 3

    @patch("morning_prep._collect_strategy_health")
    @patch("morning_prep._collect_learning_summary")
    @patch("morning_prep._collect_agent_insights")
    @patch("morning_prep._collect_futures_positions")
    @patch("morning_prep._collect_cross_market")
    def test_all_none(self, mock_cm, mock_fut, mock_ins, mock_learn, mock_health):
        mock_cm.return_value = None
        mock_fut.return_value = None
        mock_ins.return_value = []
        mock_learn.return_value = None
        mock_health.return_value = {}

        result = generate_morning_plan()
        assert result is not None
        assert "plan_text" in result
        assert result["risk_level"] in ("low", "medium", "high")

    @patch("morning_prep._collect_strategy_health")
    @patch("morning_prep._collect_learning_summary")
    @patch("morning_prep._collect_agent_insights")
    @patch("morning_prep._collect_futures_positions")
    @patch("morning_prep._collect_cross_market")
    def test_result_fields(self, mock_cm, mock_fut, mock_ins, mock_learn, mock_health):
        mock_cm.return_value = None
        mock_fut.return_value = None
        mock_ins.return_value = []
        mock_learn.return_value = None
        mock_health.return_value = {}

        result = generate_morning_plan()
        for key in ["cross_market", "futures", "insights", "learning",
                     "health", "plan_text", "risk_level", "risk_factors", "timestamp"]:
            assert key in result, f"Missing key: {key}"


# ================================================================
#  测试: 标准化接口
# ================================================================

class TestRunMorningPrep:
    @patch("morning_prep.generate_morning_plan")
    def test_returns_result(self, mock_gen):
        mock_gen.return_value = {"plan_text": "test", "risk_level": "low"}
        result = run_morning_prep()
        assert result["plan_text"] == "test"

    @patch("morning_prep.MORNING_PREP_PARAMS", {"enabled": False})
    def test_disabled(self):
        result = run_morning_prep()
        assert result == {}

    @patch("morning_prep.generate_morning_plan")
    def test_exception_safe(self, mock_gen):
        mock_gen.side_effect = RuntimeError("test error")
        result = run_morning_prep()
        assert result == {}
