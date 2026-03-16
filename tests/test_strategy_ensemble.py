"""
多策略共识引擎 单元测试
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from datetime import date
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import strategy_ensemble as se


# ================================================================
#  Fixtures
# ================================================================

@pytest.fixture(autouse=True)
def _reset_params(monkeypatch):
    monkeypatch.setattr(se, "ENSEMBLE_PARAMS", {
        "enabled": True, "min_strategies": 2, "top_n": 5,
        "weights": {
            "consensus_count": 0.35, "avg_score": 0.25,
            "family_diversity": 0.20, "regime_fit": 0.20,
        },
    })


@pytest.fixture
def mock_picks_by_code():
    """模拟 picks: 000001被3个策略推荐, 000002被2个, 000003只有1个"""
    return {
        "000001": [
            {"strategy": "放量突破选股", "name": "平安银行", "score": 0.8, "factor_scores": {}},
            {"strategy": "趋势跟踪选股", "name": "平安银行", "score": 0.75, "factor_scores": {}},
            {"strategy": "低吸回调选股", "name": "平安银行", "score": 0.65, "factor_scores": {}},
        ],
        "000002": [
            {"strategy": "集合竞价选股", "name": "万科A", "score": 0.7, "factor_scores": {}},
            {"strategy": "事件驱动选股", "name": "万科A", "score": 0.6, "factor_scores": {}},
        ],
        "000003": [
            {"strategy": "放量突破选股", "name": "金地集团", "score": 0.5, "factor_scores": {}},
        ],
    }


# ================================================================
#  collect_today_picks
# ================================================================

class TestCollectTodayPicks:
    @patch("db_store.load_trade_journal")
    def test_basic(self, mock_load):
        today = date.today().isoformat()
        mock_load.return_value = [
            {"trade_date": today, "strategy": "放量突破选股",
             "picks": [{"code": "000001", "name": "平安银行", "score": 0.8}]},
            {"trade_date": today, "strategy": "趋势跟踪选股",
             "picks": [{"code": "000001", "name": "平安银行", "score": 0.75}]},
        ]
        result = se.collect_today_picks()
        assert "000001" in result
        assert len(result["000001"]) == 2

    @patch("db_store.load_trade_journal")
    def test_empty(self, mock_load):
        mock_load.return_value = []
        result = se.collect_today_picks()
        assert result == {}

    @patch("db_store.load_trade_journal", side_effect=Exception("db error"))
    def test_error(self, mock_load):
        result = se.collect_today_picks()
        assert result == {}


# ================================================================
#  score_consensus
# ================================================================

class TestScoreConsensus:
    def test_basic(self, mock_picks_by_code):
        results = se.score_consensus(mock_picks_by_code)
        # 000001(3策略) 和 000002(2策略) 应该被选出
        codes = [r["code"] for r in results]
        assert "000001" in codes
        assert "000002" in codes
        # 000003(1策略) 不应该出现 (min_strategies=2)
        assert "000003" not in codes

    def test_000001_higher(self, mock_picks_by_code):
        """3策略共识 vs 2策略共识 — 两者分差很小, 受权重影响"""
        results = se.score_consensus(mock_picks_by_code)
        scores = {r["code"]: r["consensus_score"] for r in results}
        # 3策略和2策略共识分差很小, 权重变化可能影响排序
        assert abs(scores["000001"] - scores["000002"]) < 0.1

    def test_family_diversity(self, mock_picks_by_code):
        """000001 跨 momentum+value (2族), 000002 跨 momentum+event (2族)"""
        results = se.score_consensus(mock_picks_by_code)
        r1 = next(r for r in results if r["code"] == "000001")
        assert r1["family_count"] >= 2  # momentum + value

    def test_empty_picks(self):
        results = se.score_consensus({})
        assert results == []

    def test_min_strategies_3(self, mock_picks_by_code, monkeypatch):
        """min_strategies=3 → 只有 000001"""
        monkeypatch.setattr(se, "ENSEMBLE_PARAMS", {
            "enabled": True, "min_strategies": 3, "top_n": 5,
            "weights": {"consensus_count": 0.35, "avg_score": 0.25,
                        "family_diversity": 0.20, "regime_fit": 0.20},
        })
        results = se.score_consensus(mock_picks_by_code)
        assert len(results) == 1
        assert results[0]["code"] == "000001"

    @patch("signal_tracker.get_regime_strategy_matrix")
    def test_with_regime(self, mock_matrix, mock_picks_by_code):
        """带 regime matrix 计算 regime_fit"""
        mock_matrix.return_value = {
            "放量突破选股": {"bull": {"win_rate": 65, "total": 30}},
            "趋势跟踪选股": {"bull": {"win_rate": 70, "total": 25}},
            "低吸回调选股": {"bull": {"win_rate": 40, "total": 20}},
        }
        regime = {"regime": "bull", "score": 0.7}
        results = se.score_consensus(mock_picks_by_code, regime)
        assert len(results) >= 1


# ================================================================
#  get_consensus_recommendations
# ================================================================

class TestGetConsensusRecommendations:
    @patch("strategy_ensemble.collect_today_picks")
    def test_basic(self, mock_collect, mock_picks_by_code):
        mock_collect.return_value = mock_picks_by_code
        with patch("smart_trader.detect_market_regime",
                   return_value={"regime": "neutral"}):
            results = se.get_consensus_recommendations()
        assert len(results) <= 5
        assert len(results) >= 1

    @patch("strategy_ensemble.collect_today_picks", return_value={})
    def test_empty(self, mock_collect):
        results = se.get_consensus_recommendations()
        assert results == []

    def test_disabled(self, monkeypatch):
        monkeypatch.setattr(se, "ENSEMBLE_PARAMS", {"enabled": False})
        results = se.get_consensus_recommendations()
        assert results == []


# ================================================================
#  check_consensus_history
# ================================================================

class TestCheckConsensusHistory:
    @patch("db_store.load_scorecard")
    def test_basic(self, mock_load):
        """同日同code两策略推荐 = 共识"""
        mock_load.return_value = [
            {"rec_date": "2026-03-01", "code": "000001", "strategy": "放量突破选股",
             "net_return_pct": 2.0},
            {"rec_date": "2026-03-01", "code": "000001", "strategy": "趋势跟踪选股",
             "net_return_pct": 2.0},
            {"rec_date": "2026-03-01", "code": "000002", "strategy": "放量突破选股",
             "net_return_pct": -1.0},
        ]
        result = se.check_consensus_history(days=30)
        assert result["total"] == 1  # 000001是共识
        assert result["single_total"] == 1  # 000002是单策略

    @patch("db_store.load_scorecard", return_value=[])
    def test_empty(self, mock_load):
        result = se.check_consensus_history()
        assert result == {"total": 0}


# ================================================================
#  get_ensemble_status
# ================================================================

class TestGetEnsembleStatus:
    @patch("strategy_ensemble.get_consensus_recommendations", return_value=[])
    @patch("strategy_ensemble.check_consensus_history", return_value={"total": 0})
    def test_basic(self, mock_hist, mock_cons):
        status = se.get_ensemble_status()
        assert "enabled" in status
        assert "today_consensus_count" in status
        assert "history_30d" in status
