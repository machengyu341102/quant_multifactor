"""
agent_brain 单元测试
====================
覆盖: observe, 7个检测器, decide, act, should_strategy_run, learn, morning briefing
"""

import json
import os
import sys
import pytest
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

# 确保能导入项目模块
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
    """将 agent_brain 的文件路径重定向到临时目录"""
    import agent_brain
    memory_path = str(tmp_path / "agent_memory.json")
    scorecard_path = str(tmp_path / "scorecard.json")
    monkeypatch.setattr(agent_brain, "_MEMORY_PATH", memory_path)
    monkeypatch.setattr(agent_brain, "_SCORECARD_PATH", scorecard_path)
    return tmp_path


@pytest.fixture
def sample_scorecard(tmp_dir):
    """生成样本 scorecard 数据"""
    import agent_brain
    records = []
    # 集合竞价: 3连亏
    for i in range(3):
        d = (date.today() - timedelta(days=i + 1)).isoformat()
        records.append({
            "rec_date": d, "strategy": "集合竞价选股",
            "code": f"00000{i}", "name": f"测试{i}",
            "entry_price": 10.0, "next_close": 9.5,
            "net_return_pct": -2.0, "result": "loss",
        })
    # 放量突破: 5连亏
    for i in range(5):
        d = (date.today() - timedelta(days=i + 1)).isoformat()
        records.append({
            "rec_date": d, "strategy": "放量突破选股",
            "code": f"30000{i}", "name": f"测试B{i}",
            "entry_price": 20.0, "next_close": 19.0,
            "net_return_pct": -3.0, "result": "loss",
        })
    # 尾盘短线: 3赢2亏
    for i in range(5):
        d = (date.today() - timedelta(days=i + 1)).isoformat()
        res = "win" if i < 3 else "loss"
        ret = 2.0 if i < 3 else -1.5
        records.append({
            "rec_date": d, "strategy": "尾盘短线选股",
            "code": f"60000{i}", "name": f"测试C{i}",
            "entry_price": 15.0, "next_close": 15.0 + ret * 0.15,
            "net_return_pct": ret, "result": res,
        })
    _write_json(agent_brain._SCORECARD_PATH, records)
    return records


# ================================================================
#  TestObserve
# ================================================================

class TestObserve:
    def test_basic_snapshot(self, tmp_dir, sample_scorecard):
        """基本快照应包含所有策略指标"""
        import agent_brain
        snapshot = agent_brain.observe()
        assert "strategy_metrics" in snapshot
        assert "集合竞价选股" in snapshot["strategy_metrics"]
        assert "放量突破选股" in snapshot["strategy_metrics"]
        assert "尾盘短线选股" in snapshot["strategy_metrics"]

    def test_empty_scorecard(self, tmp_dir):
        """空 scorecard 不应崩溃"""
        import agent_brain
        _write_json(agent_brain._SCORECARD_PATH, [])
        snapshot = agent_brain.observe()
        for name in agent_brain.STRATEGY_NAMES:
            metrics = snapshot["strategy_metrics"][name]
            assert metrics["consecutive_losses"] == 0
            assert metrics["rolling_5d_win_rate"] is None


# ================================================================
#  TestDetectConsecutiveLosses
# ================================================================

class TestDetectConsecutiveLosses:
    def test_no_trigger_below_threshold(self, tmp_dir):
        """连亏3次不应触发 (阈值4)"""
        import agent_brain
        snapshot = {"strategy_metrics": {
            "集合竞价选股": {"consecutive_losses": 3},
        }}
        memory = agent_brain._default_memory()
        findings = agent_brain.detect_consecutive_losses(snapshot, memory)
        assert len(findings) == 0

    def test_trigger_at_threshold(self, tmp_dir):
        """连亏4次应触发 critical"""
        import agent_brain
        snapshot = {"strategy_metrics": {
            "集合竞价选股": {"consecutive_losses": 4},
        }}
        memory = agent_brain._default_memory()
        findings = agent_brain.detect_consecutive_losses(snapshot, memory)
        assert len(findings) == 1
        assert findings[0]["severity"] == "critical"
        assert findings[0]["suggested_action"] == "pause_strategy"

    def test_no_trigger_if_already_paused(self, tmp_dir):
        """已暂停的策略不应重复触发"""
        import agent_brain
        snapshot = {"strategy_metrics": {
            "集合竞价选股": {"consecutive_losses": 5},
        }}
        memory = agent_brain._default_memory()
        memory["strategy_states"]["集合竞价选股"]["status"] = "paused"
        findings = agent_brain.detect_consecutive_losses(snapshot, memory)
        assert len(findings) == 0


# ================================================================
#  TestDetectWinRateDegradation
# ================================================================

class TestDetectWinRateDegradation:
    def test_no_trigger_above_threshold(self, tmp_dir):
        """胜率30%不应触发"""
        import agent_brain
        snapshot = {"strategy_metrics": {
            "集合竞价选股": {"rolling_5d_win_rate": 0.30, "total_samples": 10},
        }}
        memory = agent_brain._default_memory()
        findings = agent_brain.detect_win_rate_degradation(snapshot, memory)
        assert len(findings) == 0

    def test_trigger_low_win_rate(self, tmp_dir):
        """胜率10%应触发 warning"""
        import agent_brain
        snapshot = {"strategy_metrics": {
            "放量突破选股": {"rolling_5d_win_rate": 0.10, "total_samples": 10},
        }}
        memory = agent_brain._default_memory()
        findings = agent_brain.detect_win_rate_degradation(snapshot, memory)
        assert len(findings) == 1
        assert findings[0]["severity"] == "warning"


# ================================================================
#  TestDetectRegimeMismatch
# ================================================================

class TestDetectRegimeMismatch:
    def test_no_trigger_good_fit(self, tmp_dir):
        """胜率50%不触发"""
        import agent_brain
        snapshot = {
            "strategy_metrics": {},
            "regime_fit": [{"strategy": "集合竞价选股", "regime": "neutral",
                            "win_rate": 0.50, "samples": 10}],
            "current_regime": "neutral",
        }
        memory = agent_brain._default_memory()
        findings = agent_brain.detect_regime_strategy_mismatch(snapshot, memory)
        assert len(findings) == 0

    def test_trigger_mismatch(self, tmp_dir):
        """胜率20%应触发"""
        import agent_brain
        snapshot = {
            "strategy_metrics": {},
            "regime_fit": [{"strategy": "放量突破选股", "regime": "weak",
                            "win_rate": 0.20, "samples": 8}],
            "current_regime": "weak",
        }
        memory = agent_brain._default_memory()
        findings = agent_brain.detect_regime_strategy_mismatch(snapshot, memory)
        assert len(findings) == 1
        assert findings[0]["suggested_action"] == "pause_strategy"


# ================================================================
#  TestDetectAutoResume
# ================================================================

class TestDetectAutoResume:
    def test_no_resume_before_date(self, tmp_dir):
        """未到恢复日期不触发"""
        import agent_brain
        memory = agent_brain._default_memory()
        memory["strategy_states"]["放量突破选股"]["status"] = "paused"
        future = (date.today() + timedelta(days=3)).isoformat()
        memory["strategy_states"]["放量突破选股"]["auto_resume_date"] = future
        findings = agent_brain.detect_auto_resume({}, memory)
        assert len(findings) == 0

    def test_resume_at_date(self, tmp_dir):
        """到期应触发恢复"""
        import agent_brain
        memory = agent_brain._default_memory()
        memory["strategy_states"]["放量突破选股"]["status"] = "paused"
        past = (date.today() - timedelta(days=1)).isoformat()
        memory["strategy_states"]["放量突破选股"]["auto_resume_date"] = past
        findings = agent_brain.detect_auto_resume({}, memory)
        assert len(findings) == 1
        assert findings[0]["suggested_action"] == "resume_strategy"


# ================================================================
#  TestDecide
# ================================================================

class TestDecide:
    def test_high_confidence_executes(self, tmp_dir):
        """高置信度 finding 应自主执行"""
        import agent_brain
        findings = [{
            "type": "anomaly", "severity": "warning",
            "strategy": "放量突破选股",
            "message": "test", "suggested_action": "pause_strategy",
            "confidence": 0.80,
        }]
        memory = agent_brain._default_memory()
        decisions = agent_brain.decide(findings, memory)
        assert len(decisions) == 1
        assert decisions[0]["execute"] is True

    def test_low_confidence_no_execute(self, tmp_dir):
        """低置信度 finding 不执行, 只记录"""
        import agent_brain
        findings = [{
            "type": "anomaly", "severity": "info",
            "strategy": None,
            "message": "test", "suggested_action": "log_insight",
            "confidence": 0.30,
        }]
        memory = agent_brain._default_memory()
        decisions = agent_brain.decide(findings, memory)
        assert len(decisions) == 1
        assert decisions[0]["execute"] is False
        assert decisions[0]["notify"] is False

    def test_critical_always_executes(self, tmp_dir):
        """critical 无论置信度都执行"""
        import agent_brain
        findings = [{
            "type": "anomaly", "severity": "critical",
            "strategy": "集合竞价选股",
            "message": "test", "suggested_action": "pause_strategy",
            "confidence": 0.20,
        }]
        memory = agent_brain._default_memory()
        decisions = agent_brain.decide(findings, memory)
        assert len(decisions) == 1
        assert decisions[0]["execute"] is True
        assert decisions[0]["notify"] is True


# ================================================================
#  TestActionPause
# ================================================================

class TestActionPause:
    def test_pause_writes_state(self, tmp_dir):
        """暂停应更新内存状态"""
        import agent_brain
        memory = agent_brain._default_memory()
        agent_brain._action_pause_strategy("放量突破选股", memory, "测试暂停")
        state = memory["strategy_states"]["放量突破选股"]
        assert state["status"] == "paused"
        assert state["pause_reason"] == "测试暂停"
        assert state["auto_resume_date"] is not None

    def test_pause_sets_resume_date(self, tmp_dir):
        """暂停应设置自动恢复日期"""
        import agent_brain
        memory = agent_brain._default_memory()
        agent_brain._action_pause_strategy("放量突破选股", memory, "test")
        state = memory["strategy_states"]["放量突破选股"]
        expected = (date.today() + timedelta(
            days=agent_brain.AGENT_PARAMS.get("auto_resume_days", 5)
        )).isoformat()
        assert state["auto_resume_date"] == expected


# ================================================================
#  TestShouldStrategyRun
# ================================================================

class TestShouldStrategyRun:
    def test_active_returns_true(self, tmp_dir):
        """active 策略应返回 True"""
        import agent_brain
        memory = agent_brain._default_memory()
        agent_brain._save_memory(memory)
        assert agent_brain.should_strategy_run("集合竞价选股") is True

    def test_paused_returns_false(self, tmp_dir):
        """paused 策略应返回 False"""
        import agent_brain
        memory = agent_brain._default_memory()
        future = (date.today() + timedelta(days=3)).isoformat()
        memory["strategy_states"]["放量突破选股"]["status"] = "paused"
        memory["strategy_states"]["放量突破选股"]["auto_resume_date"] = future
        memory["strategy_states"]["放量突破选股"]["pause_reason"] = "测试"
        agent_brain._save_memory(memory)
        assert agent_brain.should_strategy_run("放量突破选股") is False

    def test_auto_resume_returns_true(self, tmp_dir):
        """过期暂停应自动恢复返回 True"""
        import agent_brain
        memory = agent_brain._default_memory()
        past = (date.today() - timedelta(days=1)).isoformat()
        memory["strategy_states"]["放量突破选股"]["status"] = "paused"
        memory["strategy_states"]["放量突破选股"]["auto_resume_date"] = past
        agent_brain._save_memory(memory)
        assert agent_brain.should_strategy_run("放量突破选股") is True
        # 验证状态已恢复
        updated = agent_brain._load_memory()
        assert updated["strategy_states"]["放量突破选股"]["status"] == "active"


# ================================================================
#  TestLearnNewRules
# ================================================================

class TestLearnNewRules:
    def test_discover_rule_from_regime_fit(self, tmp_dir):
        """从低胜率 regime_fit 中发现新规则"""
        import agent_brain
        snapshot = {
            "strategy_metrics": {},
            "regime_fit": [{"strategy": "放量突破选股", "regime": "weak",
                            "win_rate": 0.15, "samples": 8}],
        }
        memory = agent_brain._default_memory()
        initial_count = len(memory["rules"])
        agent_brain._discover_new_rules(snapshot, memory)
        assert len(memory["rules"]) == initial_count + 1
        new_rule = memory["rules"][-1]
        assert new_rule["source"] == "learned"
        assert new_rule["confidence"] == 0.50

    def test_no_duplicate_rules(self, tmp_dir):
        """已存在的规则不重复添加"""
        import agent_brain
        snapshot = {
            "strategy_metrics": {},
            "regime_fit": [{"strategy": "放量突破选股", "regime": "weak",
                            "win_rate": 0.15, "samples": 8}],
        }
        memory = agent_brain._default_memory()
        # 发现一次
        agent_brain._discover_new_rules(snapshot, memory)
        count_after_first = len(memory["rules"])
        # 再次不重复
        agent_brain._discover_new_rules(snapshot, memory)
        assert len(memory["rules"]) == count_after_first


# ================================================================
#  TestPruneRules
# ================================================================

class TestPruneRules:
    def test_prune_low_confidence(self, tmp_dir):
        """低置信度 + 足够评估次数的 learned 规则应被清理"""
        import agent_brain
        memory = agent_brain._default_memory()
        memory["rules"].append({
            "id": "R_test_prune", "type": "test",
            "condition": {}, "action": "log_insight",
            "confidence": 0.10, "evidence_count": 15,
            "source": "learned", "description": "低效规则",
        })
        agent_brain._prune_rules(memory)
        ids = [r["id"] for r in memory["rules"]]
        assert "R_test_prune" not in ids

    def test_seed_rules_never_pruned(self, tmp_dir):
        """种子规则永远不被清理"""
        import agent_brain
        memory = agent_brain._default_memory()
        for r in memory["rules"]:
            r["confidence"] = 0.01
            r["evidence_count"] = 100
        agent_brain._prune_rules(memory)
        seed_ids = {r["id"] for r in memory["rules"] if r["source"] == "seed"}
        assert "R001" in seed_ids
        assert "R002" in seed_ids
        assert "R003" in seed_ids


# ================================================================
#  TestMorningBriefing
# ================================================================

class TestMorningBriefing:
    def test_briefing_format(self, tmp_dir, sample_scorecard):
        """早报应包含关键结构"""
        import agent_brain
        # Mock detect_market_regime to avoid network call
        with patch("agent_brain.detect_market_regime",
                   return_value={"regime": "neutral", "score": 0.52},
                   create=True):
            # 使用 monkeypatch 跳过实际 import
            briefing = agent_brain.generate_morning_briefing()
        assert "今日交易简报" in briefing
        assert "策略状态" in briefing
        assert "集合竞价选股" in briefing


# ================================================================
#  TestFullCycle
# ================================================================

class TestFullCycle:
    def test_ooda_cycle_no_crash(self, tmp_dir, sample_scorecard):
        """完整 OODA 循环不应崩溃"""
        import agent_brain
        summary = agent_brain.run_agent_cycle()
        assert "OODA循环完成" in summary
        # 验证 memory 已持久化
        mem = agent_brain._load_memory()
        assert mem["meta"]["total_cycles"] == 1

    def test_ooda_pauses_losing_strategy(self, tmp_dir, sample_scorecard):
        """放量突破5连亏应被暂停"""
        import agent_brain
        agent_brain.run_agent_cycle()
        mem = agent_brain._load_memory()
        assert mem["strategy_states"]["放量突破选股"]["status"] == "paused"

    def test_evening_summary(self, tmp_dir, sample_scorecard):
        """晚间摘要应包含今日洞察"""
        import agent_brain
        agent_brain.run_agent_cycle()
        summary = agent_brain.generate_evening_summary()
        # 如果有洞察就包含标题, 否则为空字符串
        if summary:
            assert "Agent 今日洞察" in summary


# ================================================================
#  TestDetectFactorDecayEnhanced
# ================================================================

class TestDetectFactorDecayEnhanced:
    def test_severe_decay_suggests_deweight(self, tmp_dir):
        """严重因子衰减 (corr < -0.15) 应建议 deweight_factor"""
        import agent_brain
        snapshot = {
            "strategy_metrics": {},
            "signal_health": [
                {"signal": "s_hot", "correlation": -0.20, "predictive_value": 1.0},
            ],
            "regime_fit": [],
        }
        memory = agent_brain._default_memory()
        findings = agent_brain.detect_factor_decay(snapshot, memory)
        assert len(findings) == 1
        assert findings[0]["suggested_action"] == "deweight_factor"
        assert findings[0]["confidence"] == 0.70
        assert findings[0]["signal_name"] == "s_hot"

    def test_mild_decay_logs_insight(self, tmp_dir):
        """轻微因子衰减 (corr between -0.05 and -0.15) 只记录"""
        import agent_brain
        snapshot = {
            "strategy_metrics": {},
            "signal_health": [
                {"signal": "s_rsi", "correlation": -0.08},
            ],
            "regime_fit": [],
        }
        memory = agent_brain._default_memory()
        findings = agent_brain.detect_factor_decay(snapshot, memory)
        assert len(findings) == 1
        assert findings[0]["suggested_action"] == "log_insight"

    def test_healthy_factor_no_finding(self, tmp_dir):
        """健康因子 (corr >= -0.05) 不产生 finding"""
        import agent_brain
        snapshot = {
            "strategy_metrics": {},
            "signal_health": [
                {"signal": "s_trend", "correlation": 0.15},
            ],
            "regime_fit": [],
        }
        memory = agent_brain._default_memory()
        findings = agent_brain.detect_factor_decay(snapshot, memory)
        assert len(findings) == 0


class TestDetectOptimizationRegression:
    def test_regression_found(self, tmp_dir):
        """验证失败的优化应产生 warning finding"""
        import agent_brain
        snapshot = {"strategy_metrics": {}, "signal_health": [], "regime_fit": []}
        memory = agent_brain._default_memory()

        with patch("auto_optimizer.check_pending_verifications",
                   return_value=[{
                       "strategy": "breakout", "verdict": "rolled_back",
                       "pre_score": 70, "post_score": 50,
                   }]):
            findings = agent_brain.detect_optimization_regression(snapshot, memory)
        assert len(findings) == 1
        assert findings[0]["severity"] == "warning"
        assert "回滚" in findings[0]["message"]

    def test_verification_ok(self, tmp_dir):
        """验证通过的优化应产生 info finding"""
        import agent_brain
        snapshot = {"strategy_metrics": {}, "signal_health": [], "regime_fit": []}
        memory = agent_brain._default_memory()

        with patch("auto_optimizer.check_pending_verifications",
                   return_value=[{
                       "strategy": "breakout", "verdict": "verified_ok",
                       "pre_score": 50, "post_score": 55,
                   }]):
            findings = agent_brain.detect_optimization_regression(snapshot, memory)
        assert len(findings) == 1
        assert findings[0]["severity"] == "info"
        assert "通过" in findings[0]["message"]

    def test_no_verifications(self, tmp_dir):
        """无待验证优化时不产生 finding"""
        import agent_brain
        snapshot = {"strategy_metrics": {}, "signal_health": [], "regime_fit": []}
        memory = agent_brain._default_memory()

        with patch("auto_optimizer.check_pending_verifications", return_value=[]):
            findings = agent_brain.detect_optimization_regression(snapshot, memory)
        assert len(findings) == 0


class TestActionDeweightFactor:
    def test_deweight_executes(self, tmp_dir):
        """deweight_factor action 应执行降权"""
        import agent_brain
        finding = {
            "severity": "warning",
            "signal_name": "s_hot",
            "message": "信号s_hot相关性严重转负",
            "suggested_action": "deweight_factor",
        }

        with patch("auto_optimizer.deweight_factor", return_value=True) as mock_dw, \
             patch("auto_optimizer.get_tunable_params",
                   return_value={"weights": {"s_hot": 0.07, "s_trend": 0.12}}), \
             patch("auto_optimizer.SUPPORTED_STRATEGIES", ["breakout"]):
            agent_brain._action_deweight_factor(finding)
            mock_dw.assert_called_once()
            assert mock_dw.call_args[0][0] == "breakout"
            assert mock_dw.call_args[0][1] == "s_hot"


# ================================================================
#  TestUpdateRuleConfidence
# ================================================================

class TestUpdateRuleConfidence:
    def test_ema_update(self, tmp_dir):
        """EMA 更新置信度"""
        import agent_brain
        memory = agent_brain._default_memory()
        old_conf = memory["rules"][0]["confidence"]  # R001 = 0.90
        agent_brain.update_rule_confidence("R001", 1.0, memory)
        new_conf = memory["rules"][0]["confidence"]
        expected = 0.8 * old_conf + 0.2 * 1.0
        assert abs(new_conf - expected) < 1e-6
        assert memory["rules"][0]["evidence_count"] == 1
