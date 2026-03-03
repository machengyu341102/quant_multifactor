"""
portfolio_risk 单元测试
======================
覆盖: 相关性矩阵/回撤计算/分配建议/风控 findings/空数据降级
"""

import json
import os
import sys
import pytest
from datetime import date, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ================================================================
#  Fixtures
# ================================================================

def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@pytest.fixture
def tmp_dir(tmp_path, monkeypatch):
    """将 portfolio_risk 的文件路径重定向到临时目录"""
    import portfolio_risk
    scorecard_path = str(tmp_path / "scorecard.json")
    monkeypatch.setattr(portfolio_risk, "_SCORECARD_PATH", scorecard_path)
    return tmp_path


def _make_scorecard(tmp_dir, days=30, strategies=None):
    """生成样本 scorecard 数据"""
    import portfolio_risk
    if strategies is None:
        strategies = portfolio_risk.STRATEGY_NAMES

    records = []
    for i in range(days):
        d = (date.today() - timedelta(days=i + 1)).isoformat()
        for j, strategy in enumerate(strategies):
            # 每个策略不同的收益模式
            if j == 0:
                ret = 1.0 if i % 3 == 0 else -0.5
            elif j == 1:
                ret = 1.5 if i % 2 == 0 else -1.0
            else:
                ret = 0.5 if i % 4 != 0 else -0.3
            result = "win" if ret > 0 else "loss"
            records.append({
                "rec_date": d, "strategy": strategy,
                "code": f"00{j:04d}", "name": f"测试{j}",
                "entry_price": 10.0,
                "next_close": 10.0 + ret * 0.1,
                "net_return_pct": ret, "result": result,
            })
    _write_json(portfolio_risk._SCORECARD_PATH, records)
    return records


# ================================================================
#  TestPearson
# ================================================================

class TestPearson:
    def test_perfect_correlation(self):
        """完美正相关应返回 1.0"""
        from portfolio_risk import _pearson
        xs = [1, 2, 3, 4, 5]
        ys = [2, 4, 6, 8, 10]
        assert abs(_pearson(xs, ys) - 1.0) < 1e-6

    def test_negative_correlation(self):
        """完美负相关应返回 -1.0"""
        from portfolio_risk import _pearson
        xs = [1, 2, 3, 4, 5]
        ys = [10, 8, 6, 4, 2]
        assert abs(_pearson(xs, ys) - (-1.0)) < 1e-6

    def test_zero_variance(self):
        """零方差应返回 0"""
        from portfolio_risk import _pearson
        xs = [5, 5, 5]
        ys = [1, 2, 3]
        assert _pearson(xs, ys) == 0.0

    def test_insufficient_data(self):
        """不足 2 个数据点返回 0"""
        from portfolio_risk import _pearson
        assert _pearson([1], [2]) == 0.0


# ================================================================
#  TestCalcStrategyCorrelation
# ================================================================

class TestCalcStrategyCorrelation:
    def test_basic_correlation(self, tmp_dir):
        """基本相关性计算不崩溃"""
        _make_scorecard(tmp_dir)
        from portfolio_risk import calc_strategy_correlation
        result = calc_strategy_correlation()
        assert "matrix" in result
        assert "diversification_score" in result
        assert isinstance(result["diversification_score"], float)

    def test_empty_scorecard(self, tmp_dir):
        """空 scorecard 应返回默认值"""
        import portfolio_risk
        _write_json(portfolio_risk._SCORECARD_PATH, [])
        result = portfolio_risk.calc_strategy_correlation()
        assert result["diversification_score"] == 100.0

    def test_single_strategy(self, tmp_dir):
        """只有一个策略时相关性矩阵为空"""
        _make_scorecard(tmp_dir, strategies=["放量突破选股"])
        from portfolio_risk import calc_strategy_correlation
        result = calc_strategy_correlation()
        # 没有共同数据的策略对相关系数为 0
        matrix = result["matrix"]
        for pair, corr in matrix.items():
            assert corr == 0.0


# ================================================================
#  TestCalcPortfolioDrawdown
# ================================================================

class TestCalcPortfolioDrawdown:
    def test_basic_drawdown(self, tmp_dir):
        """基本回撤计算不崩溃"""
        _make_scorecard(tmp_dir)
        from portfolio_risk import calc_portfolio_drawdown
        result = calc_portfolio_drawdown()
        assert "current_drawdown_pct" in result
        assert "max_drawdown_pct" in result
        assert "nav" in result
        assert result["nav"] > 0

    def test_empty_scorecard(self, tmp_dir):
        """空 scorecard 返回默认值"""
        import portfolio_risk
        _write_json(portfolio_risk._SCORECARD_PATH, [])
        result = portfolio_risk.calc_portfolio_drawdown()
        assert result["nav"] == 1.0
        assert result["max_drawdown_pct"] == 0.0
        assert result["breached"] is False

    def test_severe_drawdown_breaches(self, tmp_dir):
        """严重回撤应标记 breached"""
        import portfolio_risk
        # 构造连续大幅亏损的数据
        records = []
        for i in range(10):
            d = (date.today() - timedelta(days=i + 1)).isoformat()
            records.append({
                "rec_date": d, "strategy": "放量突破选股",
                "code": "000001", "name": "测试",
                "entry_price": 10.0, "next_close": 9.0,
                "net_return_pct": -3.0, "result": "loss",
            })
        _write_json(portfolio_risk._SCORECARD_PATH, records)
        result = portfolio_risk.calc_portfolio_drawdown()
        # 10天连亏3%应超过-8%阈值
        assert result["breached"] is True
        assert result["max_drawdown_pct"] < -8.0


# ================================================================
#  TestSuggestAllocation
# ================================================================

class TestSuggestAllocation:
    def test_default_when_no_health(self):
        """无健康度数据时返回默认分配"""
        from portfolio_risk import suggest_allocation
        result = suggest_allocation(None)
        assert "allocation" in result
        assert result["reason"] == "无健康度数据, 保持默认等权分配"

    def test_weighted_by_health(self):
        """健康度高的策略应分配更多"""
        from portfolio_risk import suggest_allocation
        health = {
            "集合竞价选股": {"score": 80},
            "放量突破选股": {"score": 20},
            "尾盘短线选股": {"score": 50},
        }
        result = suggest_allocation(health)
        alloc = result["allocation"]
        # 集合竞价分数最高, 应分配最多
        assert alloc["集合竞价选股"] > alloc["放量突破选股"]

    def test_allocation_sums_to_one(self):
        """分配比例之和应为 1.0"""
        from portfolio_risk import suggest_allocation
        health = {
            "集合竞价选股": {"score": 60},
            "放量突破选股": {"score": 40},
            "尾盘短线选股": {"score": 50},
        }
        result = suggest_allocation(health)
        total = sum(result["allocation"].values())
        assert abs(total - 1.0) < 0.01


# ================================================================
#  TestCheckPortfolioRisk
# ================================================================

class TestCheckPortfolioRisk:
    def test_basic_check(self, tmp_dir):
        """风控检查不崩溃"""
        _make_scorecard(tmp_dir)
        from portfolio_risk import check_portfolio_risk
        with patch("portfolio_risk.evaluate_strategy_health",
                   return_value={"score": 50, "win_rate": 40, "avg_return": 0.5},
                   create=True):
            result = check_portfolio_risk()
        assert "findings" in result
        assert "drawdown" in result
        assert "correlation" in result

    def test_disabled(self, tmp_dir, monkeypatch):
        """禁用时返回空"""
        import portfolio_risk
        monkeypatch.setattr(
            "portfolio_risk.PORTFOLIO_RISK_PARAMS",
            {**portfolio_risk.PORTFOLIO_RISK_PARAMS, "enabled": False}
        )
        result = portfolio_risk.check_portfolio_risk()
        assert result["findings"] == []


# ================================================================
#  TestGenerateReport
# ================================================================

class TestGenerateReport:
    def test_report_format(self, tmp_dir):
        """报告应包含关键结构"""
        _make_scorecard(tmp_dir)
        from portfolio_risk import generate_portfolio_report
        with patch("portfolio_risk.evaluate_strategy_health",
                   return_value={"score": 50, "win_rate": 40, "avg_return": 0.5},
                   create=True):
            report = generate_portfolio_report()
        assert "组合风控报告" in report
        assert "组合回撤" in report
        assert "策略相关性" in report
        assert "资金分配建议" in report
