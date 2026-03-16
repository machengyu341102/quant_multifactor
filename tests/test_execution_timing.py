"""
入场时机分析器 单元测试
"""

import os
import sys
import pytest
from unittest.mock import patch
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import execution_timing as et


# ================================================================
#  Fixtures
# ================================================================

@pytest.fixture(autouse=True)
def _tmp_timing(tmp_path, monkeypatch):
    timing_path = str(tmp_path / "timing_analysis.json")
    monkeypatch.setattr(et, "_TIMING_PATH", timing_path)
    monkeypatch.setattr(et, "TIMING_PARAMS", {
        "enabled": True, "lookback_days": 60, "min_samples": 5,
    })
    return timing_path


@pytest.fixture
def mock_scorecard():
    """60天 scorecard — 每策略多条"""
    records = []
    # 放量突破 (midday_10): 20条, 胜率 60%
    for i in range(20):
        ret = 2.0 if i < 12 else -1.5
        records.append({
            "rec_date": f"2026-02-{(i%28)+1:02d}",
            "code": f"00{i:04d}",
            "strategy": "放量突破选股",
            "score": 0.7 + (i % 5) * 0.05,
            "net_return_pct": ret,
            "entry_price": 10.0 + i * 0.1,
            "next_low": 10.0 + i * 0.1 - 0.15,
            "rec_price": 10.0 + i * 0.1,
        })
    # 集合竞价 (morning_open): 10条
    for i in range(10):
        ret = 1.5 if i < 5 else -2.0
        records.append({
            "rec_date": f"2026-02-{(i%28)+1:02d}",
            "code": f"01{i:04d}",
            "strategy": "集合竞价选股",
            "score": 0.6 + (i % 4) * 0.1,
            "net_return_pct": ret,
            "entry_price": 20.0,
            "next_low": 19.6,
            "rec_price": 20.0,
        })
    # 尾盘短线选股 (afternoon): 8条
    for i in range(8):
        ret = 3.0 if i < 6 else -1.0
        records.append({
            "rec_date": f"2026-02-{(i%28)+1:02d}",
            "code": f"02{i:04d}",
            "strategy": "尾盘短线选股",
            "score": 0.65,
            "net_return_pct": ret,
            "entry_price": 15.0,
            "next_low": 14.7,
            "rec_price": 15.0,
        })
    return records


# ================================================================
#  analyze_slot_performance
# ================================================================

class TestAnalyzeSlotPerformance:
    @patch("execution_timing._load_scorecard")
    def test_basic(self, mock_load, mock_scorecard):
        mock_load.return_value = mock_scorecard
        result = et.analyze_slot_performance(60)
        assert "midday_10" in result
        assert "morning_open" in result
        assert "afternoon" in result
        assert result["midday_10"]["n_signals"] == 20

    @patch("execution_timing._load_scorecard", return_value=[])
    def test_empty(self, mock_load):
        result = et.analyze_slot_performance(60)
        assert result == {}


# ================================================================
#  analyze_score_tier_timing
# ================================================================

class TestAnalyzeScoreTierTiming:
    @patch("execution_timing._load_scorecard")
    def test_basic(self, mock_load, mock_scorecard):
        mock_load.return_value = mock_scorecard
        result = et.analyze_score_tier_timing(60)
        # midday_10 有 20 条, 应该有 tier 分析
        if "midday_10" in result:
            assert "high_score_return" in result["midday_10"]
            assert "spread" in result["midday_10"]

    @patch("execution_timing._load_scorecard", return_value=[])
    def test_empty(self, mock_load):
        result = et.analyze_score_tier_timing(60)
        assert result == {}


# ================================================================
#  analyze_pullback_opportunity
# ================================================================

class TestAnalyzePullbackOpportunity:
    @patch("execution_timing._load_scorecard")
    def test_basic(self, mock_load, mock_scorecard):
        mock_load.return_value = mock_scorecard
        result = et.analyze_pullback_opportunity(60)
        # 放量突破有 20 条 → 超过 min_samples=5
        assert "放量突破选股" in result
        pb = result["放量突破选股"]
        assert "avg_pullback_pct" in pb
        assert pb["avg_pullback_pct"] < 0  # 最低价通常低于入场价
        assert pb["n_samples"] == 20

    @patch("execution_timing._load_scorecard", return_value=[])
    def test_empty(self, mock_load):
        result = et.analyze_pullback_opportunity(60)
        assert result == {}


# ================================================================
#  get_timing_advice
# ================================================================

class TestGetTimingAdvice:
    @patch("execution_timing.analyze_pullback_opportunity")
    @patch("execution_timing.analyze_slot_performance")
    def test_wait_pullback(self, mock_slot, mock_pb):
        mock_slot.return_value = {"midday_10": {"avg_t1": 1.5, "win_rate": 60}}
        mock_pb.return_value = {
            "放量突破选股": {
                "avg_pullback_pct": -2.0,
                "pullback_hit_rate": 75.0,
                "n_samples": 30,
            },
        }
        result = et.get_timing_advice()
        assert "放量突破选股" in result
        assert result["放量突破选股"]["action"] == "wait_pullback"

    @patch("execution_timing.analyze_pullback_opportunity")
    @patch("execution_timing.analyze_slot_performance")
    def test_buy_now(self, mock_slot, mock_pb):
        mock_slot.return_value = {}
        mock_pb.return_value = {
            "集合竞价选股": {
                "avg_pullback_pct": -0.3,
                "pullback_hit_rate": 30.0,
                "n_samples": 25,
            },
        }
        result = et.get_timing_advice()
        assert result["集合竞价选股"]["action"] == "buy_now"


# ================================================================
#  run_timing_analysis
# ================================================================

class TestRunTimingAnalysis:
    @patch("execution_timing._load_scorecard")
    def test_basic(self, mock_load, mock_scorecard, _tmp_timing):
        mock_load.return_value = mock_scorecard
        result = et.run_timing_analysis(60)
        assert "slot_performance" in result
        assert "score_tier_timing" in result
        assert "pullback_opportunity" in result
        assert "timing_advice" in result
        assert "timestamp" in result

        # 验证持久化
        from json_store import safe_load
        saved = safe_load(_tmp_timing, default={})
        assert "slot_performance" in saved

    def test_disabled(self, monkeypatch):
        monkeypatch.setattr(et, "TIMING_PARAMS", {"enabled": False})
        result = et.run_timing_analysis()
        assert result == {}


# ================================================================
#  format_timing_report
# ================================================================

class TestFormatReport:
    def test_format(self):
        result = {
            "timing_advice": {
                "放量突破选股": {
                    "action": "wait_pullback",
                    "pullback_target_pct": -1.0,
                    "hit_rate": 70,
                    "confidence": 0.7,
                },
                "集合竞价选股": {
                    "action": "buy_now",
                    "pullback_target_pct": 0,
                    "hit_rate": 25,
                    "confidence": 0.8,
                },
            },
            "slot_performance": {
                "midday_10": {"avg_t1": 1.5, "win_rate": 60, "n_signals": 20},
            },
        }
        report = et.format_timing_report(result)
        assert "等回踩" in report
        assert "立即买入" in report
        assert "最佳时段" in report

    def test_empty(self):
        report = et.format_timing_report({})
        assert "数据不足" in report
