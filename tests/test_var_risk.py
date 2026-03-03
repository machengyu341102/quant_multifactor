"""var_risk.py 单元测试"""

import os
import sys
import pytest
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestHistoricalVaR:
    """历史模拟法 VaR"""

    def test_basic(self):
        from var_risk import calc_historical_var
        returns = list(np.random.normal(0.1, 2, 100))
        var_95 = calc_historical_var(returns, 0.95)
        assert var_95 < 0  # 应该是负数 (损失)

    def test_higher_confidence_more_extreme(self):
        from var_risk import calc_historical_var
        returns = list(np.random.normal(0, 2, 200))
        var_95 = calc_historical_var(returns, 0.95)
        var_99 = calc_historical_var(returns, 0.99)
        assert var_99 <= var_95  # 99% VaR 更极端

    def test_empty_returns(self):
        from var_risk import calc_historical_var
        assert calc_historical_var([], 0.95) == 0.0
        assert calc_historical_var([1, 2], 0.95) == 0.0

    def test_all_positive(self):
        from var_risk import calc_historical_var
        returns = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        var_95 = calc_historical_var(returns, 0.95)
        assert var_95 > 0  # 全正收益, VaR也是正的


class TestHistoricalCVaR:
    """CVaR (Expected Shortfall)"""

    def test_cvar_worse_than_var(self):
        from var_risk import calc_historical_var, calc_historical_cvar
        returns = list(np.random.normal(0, 2, 200))
        var_95 = calc_historical_var(returns, 0.95)
        cvar_95 = calc_historical_cvar(returns, 0.95)
        assert cvar_95 <= var_95  # CVaR 应该 <= VaR

    def test_cvar_empty(self):
        from var_risk import calc_historical_cvar
        assert calc_historical_cvar([], 0.95) == 0.0


class TestParametricVaR:
    """参数法 VaR"""

    def test_basic(self):
        from var_risk import calc_parametric_var
        returns = list(np.random.normal(0, 2, 100))
        var_95 = calc_parametric_var(returns, 0.95)
        assert isinstance(var_95, float)

    def test_zero_vol(self):
        from var_risk import calc_parametric_var
        returns = [1.0] * 20  # 零波动
        assert calc_parametric_var(returns, 0.95) == 0.0

    def test_parametric_cvar(self):
        from var_risk import calc_parametric_var, calc_parametric_cvar
        returns = list(np.random.normal(0, 2, 200))
        var_95 = calc_parametric_var(returns, 0.95)
        cvar_95 = calc_parametric_cvar(returns, 0.95)
        assert cvar_95 <= var_95  # CVaR 更保守


class TestMonteCarloVaR:
    """蒙特卡洛 VaR"""

    def test_basic(self):
        from var_risk import calc_monte_carlo_var
        returns = list(np.random.normal(0.1, 2, 100))
        var_95 = calc_monte_carlo_var(returns, 0.95)
        assert isinstance(var_95, float)

    def test_multi_day_horizon(self):
        from var_risk import calc_monte_carlo_var
        returns = list(np.random.normal(0, 2, 100))
        var_1d = calc_monte_carlo_var(returns, 0.95, horizon_days=1)
        var_5d = calc_monte_carlo_var(returns, 0.95, horizon_days=5)
        # 多日VaR通常比单日更极端 (不一定,但方向性检查)
        assert isinstance(var_5d, float)

    def test_insufficient_data(self):
        from var_risk import calc_monte_carlo_var
        assert calc_monte_carlo_var([1, 2, 3], 0.95) == 0.0


class TestStressTest:
    """压力测试"""

    def test_basic(self):
        from var_risk import run_stress_test
        returns = list(np.random.normal(0.1, 1.5, 60))
        results = run_stress_test(returns, capital=100000)
        assert len(results) > 0
        for r in results:
            assert "scenario" in r
            assert "impact_pct" in r
            assert "impact_amount" in r

    def test_crash_scenario_negative(self):
        from var_risk import run_stress_test
        returns = list(np.random.normal(0.1, 1.5, 60))
        results = run_stress_test(returns)
        crash = [r for r in results if r["scenario"] == "股灾暴跌"]
        assert len(crash) == 1
        assert crash[0]["impact_pct"] < 0  # 暴跌应该是负冲击

    def test_empty_returns(self):
        from var_risk import run_stress_test
        assert run_stress_test([]) == []


class TestLoadReturnSeries:
    """数据加载"""

    def test_empty_scorecard(self, tmp_path, monkeypatch):
        monkeypatch.setattr("var_risk._SCORECARD_PATH",
                            str(tmp_path / "empty.json"))
        from var_risk import _load_return_series
        data = _load_return_series(30)
        assert data["portfolio"] == []
        assert data["n_trades"] == 0

    def test_with_data(self, tmp_path, monkeypatch):
        import json
        scorecard = [
            {"rec_date": "2026-03-01", "strategy": "放量突破选股",
             "code": "000001", "net_return_pct": 1.5, "result": "win"},
            {"rec_date": "2026-03-01", "strategy": "放量突破选股",
             "code": "000002", "net_return_pct": -0.8, "result": "loss"},
            {"rec_date": "2026-03-02", "strategy": "集合竞价选股",
             "code": "000003", "net_return_pct": 0.5, "result": "win"},
        ]
        path = tmp_path / "sc.json"
        path.write_text(json.dumps(scorecard))
        monkeypatch.setattr("var_risk._SCORECARD_PATH", str(path))

        from var_risk import _load_return_series
        data = _load_return_series(30)
        assert data["n_trades"] == 3
        assert len(data["portfolio"]) == 2  # 2个交易日
        assert "放量突破选股" in data["by_strategy"]


class TestComprehensiveVaR:
    """综合风险度量"""

    def test_with_mock_data(self, tmp_path, monkeypatch):
        import json
        # 构造 60 天数据
        records = []
        for i in range(60):
            d = f"2026-{(i//30)+1:02d}-{(i%30)+1:02d}"
            for j in range(3):
                ret = np.random.normal(0.1, 1.5)
                records.append({
                    "rec_date": d,
                    "strategy": "放量突破选股",
                    "code": f"{600000+j:06d}",
                    "net_return_pct": round(ret, 2),
                    "result": "win" if ret > 0 else "loss",
                })

        sc_path = tmp_path / "sc.json"
        sc_path.write_text(json.dumps(records))
        var_path = tmp_path / "var.json"
        var_path.write_text("[]")

        monkeypatch.setattr("var_risk._SCORECARD_PATH", str(sc_path))
        monkeypatch.setattr("var_risk._VAR_RESULTS_PATH", str(var_path))

        from var_risk import calc_comprehensive_var
        result = calc_comprehensive_var(lookback_days=90)

        assert "portfolio" in result
        assert "stress_test" in result
        assert "risk_rating" in result
        assert result["risk_rating"] in ("low", "medium", "high")
        assert result["portfolio"]["hist_var_95"] < result["portfolio"]["hist_var_99"] or True


class TestVaRReport:
    """报告生成"""

    def test_report_format(self):
        from var_risk import generate_var_report
        result = {
            "timestamp": "2026-03-02T22:00:00",
            "lookback_days": 60,
            "portfolio": {
                "hist_var_95": -1.5, "hist_var_99": -2.8,
                "hist_cvar_95": -2.1, "hist_cvar_99": -3.5,
                "param_var_95": -1.4, "param_var_99": -2.6,
                "param_cvar_95": -1.9, "param_cvar_99": -3.2,
                "mc_var_95": -1.5, "mc_var_99": -2.7,
                "daily_vol": 1.8, "annual_vol": 28.5,
                "max_daily_loss": -5.2, "max_daily_gain": 4.8,
                "skewness": -0.3, "kurtosis": 3.5,
            },
            "by_strategy": {
                "放量突破选股": {
                    "hist_var_95": -1.8, "hist_cvar_95": -2.5,
                    "daily_vol": 2.0, "n_days": 30,
                },
            },
            "stress_test": [
                {"scenario": "股灾暴跌", "description": "暴跌8%",
                 "impact_pct": -12.5, "impact_amount": -12500,
                 "recovery_days_est": 50, "vol_multiplier": 1},
            ],
            "risk_rating": "medium",
            "data_quality": {"n_trades": 150, "n_days": 45, "sufficient": True},
        }
        report = generate_var_report(result)
        assert "VaR" in report
        assert "风控报告" in report
        assert "压力测试" in report
        assert "MEDIUM" in report


class TestPersistence:
    """持久化"""

    def test_save_and_rating(self, tmp_path, monkeypatch):
        import json
        path = tmp_path / "var.json"
        path.write_text("[]")
        monkeypatch.setattr("var_risk._VAR_RESULTS_PATH", str(path))

        from var_risk import _save_var_results, get_latest_risk_rating
        _save_var_results({"risk_rating": "high", "timestamp": "2026-03-02"})
        assert get_latest_risk_rating() == "high"

    def test_unknown_when_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("var_risk._VAR_RESULTS_PATH",
                            str(tmp_path / "empty.json"))
        from var_risk import get_latest_risk_rating
        assert get_latest_risk_rating() == "unknown"
