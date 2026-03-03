"""
experiment_lab 单元测试
======================
覆盖: 实验设计/冷却期/并发限制/回测 mock/采纳逻辑/历史记录
"""

import json
import os
import sys
import pytest
from datetime import date, timedelta, datetime
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ================================================================
#  Fixtures
# ================================================================

def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def tmp_dir(tmp_path, monkeypatch):
    """将 experiment_lab 的文件路径重定向到临时目录"""
    import experiment_lab
    import logging
    experiments_path = str(tmp_path / "experiments.json")
    monkeypatch.setattr(experiment_lab, "_EXPERIMENTS_PATH", experiments_path)
    # 抑制测试日志写入生产文件
    monkeypatch.setattr(experiment_lab, "logger", logging.getLogger("test.experiment_lab"))
    return tmp_path


@pytest.fixture
def sample_finding():
    """生成样本 finding"""
    return {
        "type": "anomaly",
        "severity": "critical",
        "strategy": "放量突破选股",
        "message": "放量突破选股连续亏损4次, 达到阈值4",
        "suggested_action": "pause_strategy",
        "confidence": 0.90,
    }


# ================================================================
#  TestDesignExperiment
# ================================================================

class TestDesignExperiment:
    def test_basic_design(self, tmp_dir, sample_finding):
        """基本实验设计不崩溃"""
        mock_weights = {"w1": 0.3, "w2": 0.3, "w3": 0.4}
        mock_candidates = [{"weights": {"w1": 0.35, "w2": 0.25, "w3": 0.4}}]

        with patch("auto_optimizer.get_tunable_params",
                   return_value={"weights": mock_weights}), \
             patch("auto_optimizer.generate_candidates",
                   return_value=mock_candidates):
            from experiment_lab import design_experiment
            exp = design_experiment("breakout", sample_finding)

        assert exp is not None
        assert exp["strategy"] == "breakout"
        assert "hypothesis" in exp
        assert len(exp["candidates"]) > 0

    def test_no_weights_returns_none(self, tmp_dir, sample_finding):
        """无可调参数时返回 None"""
        with patch("auto_optimizer.get_tunable_params",
                   return_value={}):
            from experiment_lab import design_experiment
            exp = design_experiment("breakout", sample_finding)
        assert exp is None

    def test_hypothesis_consecutive_loss(self, tmp_dir):
        """连亏 finding 应生成对应假设"""
        finding = {
            "severity": "critical",
            "message": "放量突破选股连续亏损4次",
            "suggested_action": "pause_strategy",
        }
        mock_weights = {"w1": 0.5, "w2": 0.5}
        mock_candidates = [{"weights": {"w1": 0.4, "w2": 0.6}}]

        with patch("auto_optimizer.get_tunable_params",
                   return_value={"weights": mock_weights}), \
             patch("auto_optimizer.generate_candidates",
                   return_value=mock_candidates):
            from experiment_lab import design_experiment
            exp = design_experiment("breakout", finding)

        assert "连续亏损" in exp["hypothesis"] or "连亏" in exp["hypothesis"]

    def test_hypothesis_win_rate(self, tmp_dir):
        """胜率下降 finding 应生成对应假设"""
        finding = {
            "severity": "warning",
            "message": "放量突破选股近5日胜率10%",
            "suggested_action": "escalate_human",
        }
        mock_weights = {"w1": 0.5, "w2": 0.5}
        mock_candidates = [{"weights": {"w1": 0.4, "w2": 0.6}}]

        with patch("auto_optimizer.get_tunable_params",
                   return_value={"weights": mock_weights}), \
             patch("auto_optimizer.generate_candidates",
                   return_value=mock_candidates):
            from experiment_lab import design_experiment
            exp = design_experiment("breakout", finding)

        assert "胜率" in exp["hypothesis"]


# ================================================================
#  TestRunExperiment
# ================================================================

class TestRunExperiment:
    def test_found_better(self, tmp_dir):
        """候选优于基线时 conclusion=found_better"""
        experiment = {
            "experiment_id": "EXP_breakout_test_001",
            "strategy": "breakout",
            "hypothesis": "测试",
            "current_weights": {"w1": 0.5, "w2": 0.5},
            "candidates": [{"weights": {"w1": 0.4, "w2": 0.6}}],
        }
        baseline_result = {"win_rate": 40, "avg_return": 0.5,
                           "total_return": 10, "total_trades": 20}
        better_result = {"win_rate": 45, "avg_return": 2.0,
                         "total_return": 20, "total_trades": 20}

        with patch("backtest.backtest_strategy",
                   side_effect=[baseline_result, better_result]):
            from experiment_lab import run_experiment
            result = run_experiment(experiment)

        assert result["conclusion"] == "found_better"
        assert result["best_candidate"] is not None
        assert result["best_candidate"]["improvement_pct"] > 0

    def test_no_improvement(self, tmp_dir):
        """候选不优于基线时 conclusion=no_improvement"""
        experiment = {
            "experiment_id": "EXP_breakout_test_002",
            "strategy": "breakout",
            "hypothesis": "测试",
            "current_weights": {"w1": 0.5, "w2": 0.5},
            "candidates": [{"weights": {"w1": 0.4, "w2": 0.6}}],
        }
        baseline_result = {"win_rate": 50, "avg_return": 2.0,
                           "total_return": 10, "total_trades": 20}
        worse_result = {"win_rate": 40, "avg_return": 1.0,
                        "total_return": 5, "total_trades": 20}

        with patch("backtest.backtest_strategy",
                   side_effect=[baseline_result, worse_result]):
            from experiment_lab import run_experiment
            result = run_experiment(experiment)

        assert result["conclusion"] == "no_improvement"
        assert result["best_candidate"] is None

    def test_backtest_exception(self, tmp_dir):
        """回测异常时 conclusion=error"""
        experiment = {
            "experiment_id": "EXP_test_003",
            "strategy": "breakout",
            "hypothesis": "测试",
            "current_weights": {"w1": 0.5, "w2": 0.5},
            "candidates": [],
        }
        with patch("backtest.backtest_strategy",
                   side_effect=Exception("backtest failed")):
            from experiment_lab import run_experiment
            result = run_experiment(experiment)
        assert result["conclusion"] == "error"


# ================================================================
#  TestAdoptExperimentResult
# ================================================================

class TestAdoptExperimentResult:
    def test_adopt_found_better(self, tmp_dir):
        """found_better 应调用 apply_optimization"""
        experiment = {
            "experiment_id": "EXP_test_adopt",
            "strategy": "breakout",
            "hypothesis": "测试采纳",
            "conclusion": "found_better",
            "best_candidate": {
                "weights": {"w1": 0.4, "w2": 0.6},
                "improvement_pct": 1.5,
                "win_rate": 50,
                "avg_return": 2.0,
            },
        }
        with patch("auto_optimizer.apply_optimization") as mock_apply:
            from experiment_lab import adopt_experiment_result
            result = adopt_experiment_result(experiment)
        assert result is True
        mock_apply.assert_called_once()
        assert experiment["adopted"] is True

    def test_no_adopt_no_improvement(self, tmp_dir):
        """no_improvement 不应采纳"""
        experiment = {
            "conclusion": "no_improvement",
            "best_candidate": None,
        }
        from experiment_lab import adopt_experiment_result
        result = adopt_experiment_result(experiment)
        assert result is False


# ================================================================
#  TestCooldownAndConcurrency
# ================================================================

class TestCooldownAndConcurrency:
    def test_cooldown_blocks(self, tmp_dir):
        """冷却期内应返回 True (跳过)"""
        import experiment_lab
        recent_exp = {
            "experiment_id": "EXP_breakout_recent",
            "strategy": "breakout",
            "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "completed",
        }
        _write_json(experiment_lab._EXPERIMENTS_PATH, [recent_exp])
        assert experiment_lab._check_cooldown("breakout") is True

    def test_cooldown_expired(self, tmp_dir):
        """冷却期过后应返回 False (可实验)"""
        import experiment_lab
        old_exp = {
            "experiment_id": "EXP_breakout_old",
            "strategy": "breakout",
            "completed_at": (date.today() - timedelta(days=30)).isoformat() + " 10:00:00",
            "status": "completed",
        }
        _write_json(experiment_lab._EXPERIMENTS_PATH, [old_exp])
        assert experiment_lab._check_cooldown("breakout") is False

    def test_count_running(self, tmp_dir):
        """应正确计算运行中实验数"""
        import experiment_lab
        exps = [
            {"experiment_id": "EXP_1", "status": "running"},
            {"experiment_id": "EXP_2", "status": "completed"},
            {"experiment_id": "EXP_3", "status": "running"},
        ]
        _write_json(experiment_lab._EXPERIMENTS_PATH, exps)
        assert experiment_lab._count_running() == 2


# ================================================================
#  TestRunAutoExperimentCycle
# ================================================================

class TestRunAutoExperimentCycle:
    def test_disabled(self, tmp_dir, monkeypatch):
        """禁用时返回空列表"""
        import experiment_lab
        monkeypatch.setattr(
            "experiment_lab.EXPERIMENT_PARAMS",
            {**experiment_lab.EXPERIMENT_PARAMS, "enabled": False}
        )
        result = experiment_lab.run_auto_experiment_cycle([], {})
        assert result == []

    def test_no_experimentable_findings(self, tmp_dir):
        """无可实验 findings 时返回空"""
        from experiment_lab import run_auto_experiment_cycle
        findings = [{
            "type": "anomaly",
            "severity": "info",
            "strategy": None,
            "message": "test",
        }]
        result = run_auto_experiment_cycle(findings, {})
        assert result == []

    def test_full_cycle_mock(self, tmp_dir):
        """完整实验循环 (mock 回测)"""
        import experiment_lab
        findings = [{
            "type": "anomaly",
            "severity": "critical",
            "strategy": "放量突破选股",
            "message": "放量突破选股连续亏损4次",
            "suggested_action": "pause_strategy",
            "confidence": 0.90,
        }]
        memory = {}

        mock_weights = {"w1": 0.5, "w2": 0.5}
        mock_candidates = [{"weights": {"w1": 0.4, "w2": 0.6}}]

        baseline = {"win_rate": 40, "avg_return": 0.5,
                    "total_return": 10, "total_trades": 20}
        better = {"win_rate": 45, "avg_return": 2.0,
                  "total_return": 20, "total_trades": 20}

        with patch("auto_optimizer.evaluate_strategy_health",
                   return_value={"score": 30}), \
             patch("auto_optimizer.get_tunable_params",
                   return_value={"weights": mock_weights}), \
             patch("auto_optimizer.generate_candidates",
                   return_value=mock_candidates), \
             patch("backtest.backtest_strategy",
                   side_effect=[baseline, better]), \
             patch("auto_optimizer.apply_optimization"):
            results = experiment_lab.run_auto_experiment_cycle(findings, memory)

        assert len(results) == 1
        assert results[0]["conclusion"] == "found_better"
        assert results[0]["adopted"] is True


# ================================================================
#  TestExperimentHistory
# ================================================================

class TestExperimentHistory:
    def test_empty_history(self, tmp_dir):
        """空历史返回空列表"""
        from experiment_lab import get_experiment_history
        assert get_experiment_history() == []

    def test_filter_by_days(self, tmp_dir):
        """应按天数过滤"""
        import experiment_lab
        exps = [
            {"experiment_id": "EXP_1",
             "created_at": date.today().isoformat() + " 10:00:00"},
            {"experiment_id": "EXP_2",
             "created_at": (date.today() - timedelta(days=60)).isoformat() + " 10:00:00"},
        ]
        _write_json(experiment_lab._EXPERIMENTS_PATH, exps)
        recent = experiment_lab.get_experiment_history(30)
        assert len(recent) == 1
        assert recent[0]["experiment_id"] == "EXP_1"


# ================================================================
#  TestExperimentReport
# ================================================================

class TestExperimentReport:
    def test_empty_report(self, tmp_dir):
        """空历史报告"""
        from experiment_lab import generate_experiment_report
        report = generate_experiment_report()
        assert "自主实验报告" in report
        assert "暂无实验记录" in report

    def test_report_with_data(self, tmp_dir):
        """有数据的报告"""
        import experiment_lab
        exps = [{
            "experiment_id": "EXP_test_report",
            "strategy": "breakout",
            "hypothesis": "测试假设",
            "conclusion": "found_better",
            "adopted": True,
            "status": "completed",
            "best_candidate": {"improvement_pct": 1.5},
            "created_at": date.today().isoformat() + " 10:00:00",
        }]
        _write_json(experiment_lab._EXPERIMENTS_PATH, exps)
        report = experiment_lab.generate_experiment_report()
        assert "EXP_test_report" in report
        assert "已采纳" in report
